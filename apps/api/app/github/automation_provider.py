"""GitHub snapshot and Check Run boundary for native automation."""

from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from dataclasses import dataclass
from urllib.parse import quote

from apps.api.app.core.config import settings
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.domain.automation import CheckAnnotation, CheckRunConclusion, CheckRunStatus
from apps.api.app.domain.workspace import RepositoryConnection
from apps.api.app.pull_requests.provider import GitHubAppWriteProvider


@dataclass(frozen=True, slots=True)
class CheckRunRequest:
    name: str
    head_sha: str
    status: CheckRunStatus
    summary: str
    details_url: str | None = None
    conclusion: CheckRunConclusion | None = None
    annotations: tuple[CheckAnnotation, ...] = ()


class GitHubAutomationProvider(ABC):
    name: str

    @abstractmethod
    async def resolve_commit(
        self, installation_id: int, repository: RepositoryConnection, ref: str
    ) -> str: ...

    @abstractmethod
    async def list_paths(
        self, installation_id: int, repository: RepositoryConnection, commit_sha: str
    ) -> list[str]: ...

    @abstractmethod
    async def changed_paths(
        self,
        installation_id: int,
        repository: RepositoryConnection,
        base_sha: str,
        head_sha: str,
    ) -> list[str]: ...

    @abstractmethod
    async def fetch_file(
        self,
        installation_id: int,
        repository: RepositoryConnection,
        path: str,
        commit_sha: str,
    ) -> bytes: ...

    @abstractmethod
    async def create_check(
        self,
        installation_id: int,
        repository: RepositoryConnection,
        request: CheckRunRequest,
    ) -> int: ...

    @abstractmethod
    async def update_check(
        self,
        installation_id: int,
        repository: RepositoryConnection,
        check_run_id: int,
        request: CheckRunRequest,
    ) -> None: ...


class MockGitHubAutomationProvider(GitHubAutomationProvider):
    """Deterministic snapshot/check provider; never contacts or mutates GitHub."""

    name = "mock"

    def __init__(self) -> None:
        self.snapshots: dict[tuple[int, str], dict[str, bytes]] = {}
        self.refs: dict[tuple[int, str], str] = {}
        self.checks: dict[int, CheckRunRequest] = {}
        self.calls: list[tuple[str, object]] = []
        self._next_check_id = 1

    async def resolve_commit(
        self, installation_id: int, repository: RepositoryConnection, ref: str
    ) -> str:
        del installation_id
        key = (repository.github_repository_id, ref)
        value = self.refs.get(key, ref if _is_sha(ref) else "a" * 40)
        self.calls.append(("resolve_commit", (repository.connection_id, ref, value)))
        return value

    async def list_paths(
        self, installation_id: int, repository: RepositoryConnection, commit_sha: str
    ) -> list[str]:
        del installation_id
        self.calls.append(("list_paths", (repository.connection_id, commit_sha)))
        return sorted(self.snapshots.get((repository.github_repository_id, commit_sha), {}))

    async def changed_paths(
        self,
        installation_id: int,
        repository: RepositoryConnection,
        base_sha: str,
        head_sha: str,
    ) -> list[str]:
        del installation_id
        base = self.snapshots.get((repository.github_repository_id, base_sha), {})
        head = self.snapshots.get((repository.github_repository_id, head_sha), {})
        paths = {path for path in base.keys() | head.keys() if base.get(path) != head.get(path)}
        self.calls.append(("changed_paths", (repository.connection_id, base_sha, head_sha)))
        return sorted(paths)

    async def fetch_file(
        self,
        installation_id: int,
        repository: RepositoryConnection,
        path: str,
        commit_sha: str,
    ) -> bytes:
        del installation_id
        _validate_path(path)
        self.calls.append(("fetch_file", (repository.connection_id, path, commit_sha)))
        try:
            return self.snapshots[(repository.github_repository_id, commit_sha)][path]
        except KeyError as exc:
            raise DriftGuardError(
                code="github_file_not_found",
                message="The contract file was not found at the immutable commit.",
                status_code=404,
            ) from exc

    async def create_check(
        self,
        installation_id: int,
        repository: RepositoryConnection,
        request: CheckRunRequest,
    ) -> int:
        del installation_id, repository
        check_id = self._next_check_id
        self._next_check_id += 1
        self.checks[check_id] = request
        self.calls.append(("create_check", check_id))
        return check_id

    async def update_check(
        self,
        installation_id: int,
        repository: RepositoryConnection,
        check_run_id: int,
        request: CheckRunRequest,
    ) -> None:
        del installation_id, repository
        if check_run_id not in self.checks:
            raise DriftGuardError(
                code="github_check_update_failed",
                message="The GitHub Check Run could not be reconciled.",
                status_code=502,
            )
        self.checks[check_run_id] = request
        self.calls.append(("update_check", check_run_id))


class RealGitHubAutomationProvider(GitHubAutomationProvider):
    """Least-privilege GitHub App REST adapter using short-lived tokens."""

    name = "github_app"

    def __init__(self, app_id: str, private_key_path: str, timeout_seconds: float) -> None:
        self.client = GitHubAppWriteProvider(
            app_id=app_id,
            private_key_path=private_key_path,
            timeout_seconds=timeout_seconds,
        )

    async def resolve_commit(
        self, installation_id: int, repository: RepositoryConnection, ref: str
    ) -> str:
        token = await self._token(installation_id, repository)
        data = await self._request(
            "GET", repository, f"/commits/{quote(ref, safe='')}", token, {200}
        )
        sha = str(data.get("sha", "")).lower()
        if not _is_sha(sha):
            raise _snapshot_unavailable()
        return sha

    async def list_paths(
        self, installation_id: int, repository: RepositoryConnection, commit_sha: str
    ) -> list[str]:
        _require_sha(commit_sha)
        token = await self._token(installation_id, repository)
        data = await self._request(
            "GET",
            repository,
            f"/git/trees/{commit_sha}",
            token,
            {200},
            params={"recursive": "1"},
        )
        tree = data.get("tree")
        if data.get("truncated") or not isinstance(tree, list):
            raise _snapshot_unavailable()
        if len(tree) > settings.max_repository_tree_entries:
            raise DriftGuardError(
                code="repository_file_limit_exceeded",
                message="Repository tree exceeds the configured entry limit.",
                status_code=413,
            )
        return [str(item["path"]) for item in tree if item.get("type") == "blob"]

    async def changed_paths(
        self,
        installation_id: int,
        repository: RepositoryConnection,
        base_sha: str,
        head_sha: str,
    ) -> list[str]:
        _require_sha(base_sha)
        _require_sha(head_sha)
        token = await self._token(installation_id, repository)
        data = await self._request(
            "GET",
            repository,
            f"/compare/{base_sha}...{head_sha}",
            token,
            {200},
            params={"per_page": "100"},
        )
        files = data.get("files")
        if not isinstance(files, list):
            return []
        return [str(item.get("filename", "")) for item in files[:300] if item.get("filename")]

    async def fetch_file(
        self,
        installation_id: int,
        repository: RepositoryConnection,
        path: str,
        commit_sha: str,
    ) -> bytes:
        _validate_path(path)
        _require_sha(commit_sha)
        token = await self._token(installation_id, repository)
        data = await self._request(
            "GET",
            repository,
            f"/contents/{quote(path, safe='/')}",
            token,
            {200},
            params={"ref": commit_sha},
        )
        if data.get("type") != "file" or data.get("encoding") != "base64":
            raise _snapshot_unavailable()
        try:
            content = base64.b64decode(str(data.get("content", "")), validate=False)
        except ValueError as exc:
            raise _snapshot_unavailable() from exc
        if len(content) > settings.max_spec_file_bytes:
            raise DriftGuardError(
                code="specification_too_large",
                message="The discovered contract exceeds the configured limit.",
                status_code=413,
            )
        return content

    async def create_check(
        self,
        installation_id: int,
        repository: RepositoryConnection,
        request: CheckRunRequest,
    ) -> int:
        token = await self._token(installation_id, repository)
        data = await self._request(
            "POST", repository, "/check-runs", token, {201}, json_body=_check_body(request)
        )
        try:
            return int(data["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise _check_error("create") from exc

    async def update_check(
        self,
        installation_id: int,
        repository: RepositoryConnection,
        check_run_id: int,
        request: CheckRunRequest,
    ) -> None:
        token = await self._token(installation_id, repository)
        await self._request(
            "PATCH",
            repository,
            f"/check-runs/{check_run_id}",
            token,
            {200},
            json_body=_check_body(request, include_head=False),
        )

    async def _token(self, installation_id: int, repository: RepositoryConnection) -> str:
        data = await self.client._request(
            "POST",
            f"/app/installations/{installation_id}/access_tokens",
            token=self.client._app_jwt(),
            app_auth=True,
            expected={201},
            json_body={
                "permissions": {"contents": "read", "checks": "write", "metadata": "read"},
                "repository_ids": [repository.github_repository_id],
            },
        )
        token = str(data.get("token", ""))
        if not token:
            raise DriftGuardError(
                code="github_installation_revoked",
                message="The GitHub App installation is unavailable or revoked.",
                status_code=409,
            )
        return token

    async def _request(
        self,
        method: str,
        repository: RepositoryConnection,
        suffix: str,
        token: str,
        expected: set[int],
        *,
        json_body=None,
        params=None,
    ):
        try:
            return await self.client._request(
                method,
                f"/repos/{quote(repository.owner, safe='')}/"
                f"{quote(repository.name, safe='')}{suffix}",
                token=token,
                expected=expected,
                json_body=json_body,
                params=params,
            )
        except DriftGuardError as exc:
            if exc.code == "github_write_failed" and method in {"POST", "PATCH"}:
                raise _check_error("create" if method == "POST" else "update") from exc
            raise


def _check_body(request: CheckRunRequest, *, include_head: bool = True) -> dict[str, object]:
    output: dict[str, object] = {
        "title": request.name,
        "summary": request.summary[:65_535],
    }
    if request.annotations:
        output["annotations"] = [
            {
                "path": item.path,
                "start_line": item.start_line,
                "end_line": item.end_line,
                "annotation_level": item.annotation_level,
                "message": item.message[:65_535],
                **({"title": item.title[:255]} if item.title else {}),
            }
            for item in request.annotations[: settings.max_check_annotations]
        ]
    body: dict[str, object] = {
        "name": request.name,
        "status": request.status.value,
        "output": output,
    }
    if include_head:
        body["head_sha"] = request.head_sha
    if request.details_url:
        body["details_url"] = request.details_url
    if request.status is CheckRunStatus.COMPLETED and request.conclusion:
        body["conclusion"] = request.conclusion.value
    return body


def _validate_path(path: str) -> None:
    parts = path.replace("\\", "/").split("/")
    if not path or path.startswith(("/", "\\")) or ".." in parts or "" in parts:
        raise DriftGuardError(
            code="contract_path_invalid",
            message="The contract path must stay inside the authorized repository.",
            status_code=400,
        )


def _require_sha(value: str) -> None:
    if not _is_sha(value):
        raise _snapshot_unavailable()


def _is_sha(value: str) -> bool:
    return len(value) == 40 and all(character in "0123456789abcdef" for character in value)


def _snapshot_unavailable() -> DriftGuardError:
    return DriftGuardError(
        code="github_snapshot_unavailable",
        message="The immutable GitHub repository snapshot is unavailable.",
        status_code=502,
    )


def _check_error(operation: str) -> DriftGuardError:
    return DriftGuardError(
        code=f"github_check_{operation}_failed",
        message="GitHub could not update the DriftGuard Check Run.",
        status_code=502,
    )
