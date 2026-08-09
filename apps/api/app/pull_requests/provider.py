"""Mock and GitHub App providers for least-privilege repository writes."""

from __future__ import annotations

import base64
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.repository.github_source import parse_github_repository_url
from apps.api.app.schemas.pull_request import GitHubWriteProviderName


@dataclass(frozen=True, slots=True)
class GitHubRepositoryMetadata:
    owner: str
    repository: str
    default_branch: str
    base_ref: str
    base_commit_sha: str
    installation_id: int | None = None


@dataclass(frozen=True, slots=True)
class GitHubBranchState:
    name: str
    commit_sha: str


@dataclass(frozen=True, slots=True)
class GitHubPullRequestResult:
    number: int
    url: str
    commit_sha: str


class GitHubWriteProvider(ABC):
    name: GitHubWriteProviderName

    @abstractmethod
    async def prepare_repository(
        self,
        repository_url: str,
        ref: str | None,
        expected_commit_sha: str | None = None,
    ) -> GitHubRepositoryMetadata: ...

    @abstractmethod
    async def get_branch(
        self, metadata: GitHubRepositoryMetadata, branch: str
    ) -> GitHubBranchState | None: ...

    @abstractmethod
    async def create_branch(
        self, metadata: GitHubRepositoryMetadata, branch: str, base_sha: str
    ) -> GitHubBranchState: ...

    @abstractmethod
    async def create_commit(
        self,
        metadata: GitHubRepositoryMetadata,
        *,
        base_sha: str,
        message: str,
        files: dict[str, str],
    ) -> str: ...

    @abstractmethod
    async def update_branch(
        self, metadata: GitHubRepositoryMetadata, branch: str, commit_sha: str
    ) -> GitHubBranchState: ...

    @abstractmethod
    async def find_pull_request(
        self, metadata: GitHubRepositoryMetadata, branch: str
    ) -> GitHubPullRequestResult | None: ...

    @abstractmethod
    async def create_pull_request(
        self,
        metadata: GitHubRepositoryMetadata,
        *,
        branch: str,
        title: str,
        body: str,
    ) -> GitHubPullRequestResult: ...


class MockGitHubWriteProvider(GitHubWriteProvider):
    """Deterministic provider that records writes without contacting GitHub."""

    name = GitHubWriteProviderName.MOCK

    def __init__(
        self,
        *,
        base_commit_sha: str | None = None,
        default_branch: str = "main",
        pull_request_number: int = 42,
    ) -> None:
        self.base_commit_sha = base_commit_sha
        self.default_branch = default_branch
        self.pull_request_number = pull_request_number
        self.branches: dict[str, str] = {}
        self.pull_requests: dict[str, GitHubPullRequestResult] = {}
        self.created_files: dict[str, str] = {}
        self.branch_base_shas: list[str] = []
        self.commit_base_shas: list[str] = []
        self.commit_messages: list[str] = []
        self.pull_request_titles: list[str] = []
        self.pull_request_bodies: list[str] = []
        self.calls: list[str] = []

    async def prepare_repository(
        self,
        repository_url: str,
        ref: str | None,
        expected_commit_sha: str | None = None,
    ) -> GitHubRepositoryMetadata:
        parsed = parse_github_repository_url(repository_url)
        self.calls.append("prepare_repository")
        return GitHubRepositoryMetadata(
            owner=parsed.owner,
            repository=parsed.repository,
            default_branch=self.default_branch,
            base_ref=ref or self.default_branch,
            base_commit_sha=self.base_commit_sha or expected_commit_sha or "a" * 40,
            installation_id=1,
        )

    async def get_branch(
        self, metadata: GitHubRepositoryMetadata, branch: str
    ) -> GitHubBranchState | None:
        del metadata
        self.calls.append("get_branch")
        sha = self.branches.get(branch)
        return GitHubBranchState(branch, sha) if sha else None

    async def create_branch(
        self, metadata: GitHubRepositoryMetadata, branch: str, base_sha: str
    ) -> GitHubBranchState:
        del metadata
        self.calls.append("create_branch")
        if branch in self.branches:
            raise _write_conflict()
        self.branch_base_shas.append(base_sha)
        self.branches[branch] = base_sha
        return GitHubBranchState(branch, base_sha)

    async def create_commit(
        self,
        metadata: GitHubRepositoryMetadata,
        *,
        base_sha: str,
        message: str,
        files: dict[str, str],
    ) -> str:
        del metadata
        self.calls.append("create_commit")
        self.commit_base_shas.append(base_sha)
        self.created_files = dict(files)
        self.commit_messages.append(message)
        digest = _sha40(base_sha + message + json.dumps(files, sort_keys=True))
        return digest

    async def update_branch(
        self, metadata: GitHubRepositoryMetadata, branch: str, commit_sha: str
    ) -> GitHubBranchState:
        del metadata
        self.calls.append("update_branch_force_false")
        if branch not in self.branches:
            raise _write_conflict()
        self.branches[branch] = commit_sha
        return GitHubBranchState(branch, commit_sha)

    async def find_pull_request(
        self, metadata: GitHubRepositoryMetadata, branch: str
    ) -> GitHubPullRequestResult | None:
        del metadata
        self.calls.append("find_pull_request")
        return self.pull_requests.get(branch)

    async def create_pull_request(
        self,
        metadata: GitHubRepositoryMetadata,
        *,
        branch: str,
        title: str,
        body: str,
    ) -> GitHubPullRequestResult:
        self.calls.append("create_pull_request")
        self.pull_request_titles.append(title)
        self.pull_request_bodies.append(body)
        sha = self.branches[branch]
        result = GitHubPullRequestResult(
            number=self.pull_request_number,
            url=(
                f"https://github.com/{metadata.owner}/{metadata.repository}/pull/"
                f"{self.pull_request_number}"
            ),
            commit_sha=sha,
        )
        self.pull_requests[branch] = result
        return result


class GitHubAppWriteProvider(GitHubWriteProvider):
    """GitHub REST implementation using short-lived installation tokens in memory."""

    name = GitHubWriteProviderName.GITHUB_APP
    api_url = "https://api.github.com"

    def __init__(
        self,
        *,
        app_id: str,
        private_key_path: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.app_id = app_id.strip()
        self.private_key_path = private_key_path.strip()
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self._tokens: dict[tuple[str, str], str] = {}

    async def prepare_repository(
        self,
        repository_url: str,
        ref: str | None,
        expected_commit_sha: str | None = None,
    ) -> GitHubRepositoryMetadata:
        del expected_commit_sha
        repository = parse_github_repository_url(repository_url)
        jwt = self._app_jwt()
        installation = await self._request(
            "GET",
            f"/repos/{_q(repository.owner)}/{_q(repository.repository)}/installation",
            token=jwt,
            app_auth=True,
            expected={200},
            not_found_code="github_app_not_installed",
        )
        installation_id = int(installation["id"])
        token_data = await self._request(
            "POST",
            f"/app/installations/{installation_id}/access_tokens",
            token=jwt,
            app_auth=True,
            expected={201},
            json_body={
                "permissions": {"contents": "write", "pull_requests": "write"},
                "repositories": [repository.repository],
            },
        )
        token = str(token_data.get("token", ""))
        if not token:
            raise DriftGuardError(
                code="github_app_token_failed",
                message="GitHub App installation authentication failed.",
                status_code=502,
            )
        self._tokens[(repository.owner, repository.repository)] = token
        repo_data = await self._repo_request(
            "GET", repository.owner, repository.repository, "", expected={200}
        )
        default_branch = str(repo_data.get("default_branch", ""))
        base_ref = ref or default_branch
        if not base_ref:
            raise DriftGuardError(
                code="github_branch_required",
                message="A GitHub base branch could not be determined.",
                status_code=409,
            )
        ref_data = await self._repo_request(
            "GET",
            repository.owner,
            repository.repository,
            f"/git/ref/heads/{quote(base_ref, safe='')}",
            expected={200},
            not_found_code="github_branch_required",
        )
        sha = str((ref_data.get("object") or {}).get("sha", "")).lower()
        if not _is_sha(sha):
            raise DriftGuardError(
                code="github_base_commit_unavailable",
                message="GitHub did not return an immutable base commit.",
                status_code=502,
            )
        return GitHubRepositoryMetadata(
            owner=repository.owner,
            repository=repository.repository,
            default_branch=default_branch,
            base_ref=base_ref,
            base_commit_sha=sha,
            installation_id=installation_id,
        )

    async def get_branch(
        self, metadata: GitHubRepositoryMetadata, branch: str
    ) -> GitHubBranchState | None:
        data = await self._repo_request(
            "GET",
            metadata.owner,
            metadata.repository,
            f"/git/ref/heads/{quote(branch, safe='')}",
            expected={200, 404},
        )
        if data.get("_status") == 404:
            return None
        sha = str((data.get("object") or {}).get("sha", ""))
        return GitHubBranchState(branch, sha)

    async def create_branch(
        self, metadata: GitHubRepositoryMetadata, branch: str, base_sha: str
    ) -> GitHubBranchState:
        await self._repo_request(
            "POST",
            metadata.owner,
            metadata.repository,
            "/git/refs",
            expected={201},
            json_body={"ref": f"refs/heads/{branch}", "sha": base_sha},
        )
        return GitHubBranchState(branch, base_sha)

    async def create_commit(
        self,
        metadata: GitHubRepositoryMetadata,
        *,
        base_sha: str,
        message: str,
        files: dict[str, str],
    ) -> str:
        base = await self._repo_request(
            "GET", metadata.owner, metadata.repository, f"/git/commits/{base_sha}", expected={200}
        )
        base_tree = str((base.get("tree") or {}).get("sha", ""))
        entries: list[dict[str, str]] = []
        for path, content in sorted(files.items()):
            blob = await self._repo_request(
                "POST",
                metadata.owner,
                metadata.repository,
                "/git/blobs",
                expected={201},
                json_body={
                    "content": base64.b64encode(content.encode()).decode(),
                    "encoding": "base64",
                },
            )
            entries.append(
                {"path": path, "mode": "100644", "type": "blob", "sha": str(blob["sha"])}
            )
        tree = await self._repo_request(
            "POST",
            metadata.owner,
            metadata.repository,
            "/git/trees",
            expected={201},
            json_body={"base_tree": base_tree, "tree": entries},
        )
        commit = await self._repo_request(
            "POST",
            metadata.owner,
            metadata.repository,
            "/git/commits",
            expected={201},
            json_body={"message": message, "tree": tree["sha"], "parents": [base_sha]},
        )
        return str(commit["sha"])

    async def update_branch(
        self, metadata: GitHubRepositoryMetadata, branch: str, commit_sha: str
    ) -> GitHubBranchState:
        await self._repo_request(
            "PATCH",
            metadata.owner,
            metadata.repository,
            f"/git/refs/heads/{quote(branch, safe='')}",
            expected={200},
            json_body={"sha": commit_sha, "force": False},
        )
        return GitHubBranchState(branch, commit_sha)

    async def find_pull_request(
        self, metadata: GitHubRepositoryMetadata, branch: str
    ) -> GitHubPullRequestResult | None:
        data = await self._repo_request(
            "GET",
            metadata.owner,
            metadata.repository,
            "/pulls",
            expected={200},
            params={
                "state": "open",
                "head": f"{metadata.owner}:{branch}",
                "base": metadata.base_ref,
            },
        )
        if not isinstance(data.get("_items"), list) or not data["_items"]:
            return None
        item = data["_items"][0]
        return GitHubPullRequestResult(
            number=int(item["number"]),
            url=str(item["html_url"]),
            commit_sha=str((item.get("head") or {}).get("sha", "")),
        )

    async def create_pull_request(
        self,
        metadata: GitHubRepositoryMetadata,
        *,
        branch: str,
        title: str,
        body: str,
    ) -> GitHubPullRequestResult:
        data = await self._repo_request(
            "POST",
            metadata.owner,
            metadata.repository,
            "/pulls",
            expected={201},
            json_body={"title": title, "body": body, "head": branch, "base": metadata.base_ref},
        )
        return GitHubPullRequestResult(
            number=int(data["number"]),
            url=str(data["html_url"]),
            commit_sha=str((data.get("head") or {}).get("sha", "")),
        )

    def _app_jwt(self) -> str:
        if not self.app_id or not self.private_key_path:
            raise DriftGuardError(
                code="github_app_not_configured",
                message="GitHub App write access is not configured.",
                status_code=503,
            )
        path = Path(self.private_key_path)
        try:
            private_key = path.read_bytes()
            from google.auth.crypt import RSASigner

            signer = RSASigner.from_string(private_key)
        except Exception as exc:
            raise DriftGuardError(
                code="github_app_signing_failed",
                message="GitHub App signing configuration is invalid.",
                status_code=503,
            ) from exc
        now = int(time.time())
        header = _b64json({"alg": "RS256", "typ": "JWT"})
        payload = _b64json({"iat": now - 30, "exp": now + 540, "iss": self.app_id})
        unsigned = f"{header}.{payload}".encode()
        signature = _b64(signer.sign(unsigned))
        return f"{header}.{payload}.{signature}"

    async def _repo_request(
        self,
        method: str,
        owner: str,
        repository: str,
        suffix: str,
        *,
        expected: set[int],
        json_body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        not_found_code: str | None = None,
    ) -> dict[str, Any]:
        token = self._tokens.get((owner, repository))
        if not token:
            raise DriftGuardError(
                code="github_app_token_failed",
                message="GitHub App installation authentication is unavailable.",
                status_code=503,
            )
        return await self._request(
            method,
            f"/repos/{_q(owner)}/{_q(repository)}{suffix}",
            token=token,
            expected=expected,
            json_body=json_body,
            params=params,
            not_found_code=not_found_code,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        token: str,
        expected: set[int],
        app_auth: bool = False,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        not_found_code: str | None = None,
    ) -> dict[str, Any]:
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "DriftGuard-AI/0.1",
            "X-GitHub-Api-Version": "2026-03-10",
        }
        if app_auth:
            headers["Authorization"] = f"Bearer {token}"
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds), transport=self.transport
            ) as client:
                response = await client.request(
                    method,
                    f"{self.api_url}{path}",
                    headers=headers,
                    json=json_body,
                    params=params,
                )
        except httpx.TimeoutException as exc:
            raise DriftGuardError(
                code="github_write_timeout",
                message="GitHub did not confirm the repository operation before timeout.",
                status_code=504,
            ) from exc
        except httpx.RequestError as exc:
            raise DriftGuardError(
                code="github_write_unavailable",
                message="GitHub write services are temporarily unavailable.",
                status_code=502,
            ) from exc
        if response.status_code not in expected:
            if response.status_code == 404 and not_found_code:
                raise DriftGuardError(
                    code=not_found_code,
                    message="The GitHub App installation or requested branch was not found.",
                    status_code=404,
                )
            if response.status_code == 403 and (
                response.headers.get("X-RateLimit-Remaining") == "0"
                or "rate limit" in response.text.lower()
            ):
                raise DriftGuardError(
                    code="github_rate_limited",
                    message="GitHub rate-limited the repository operation.",
                    status_code=429,
                )
            if response.status_code in {401, 403}:
                raise DriftGuardError(
                    code="github_write_permission_denied",
                    message="The GitHub App lacks permission for this repository operation.",
                    status_code=403,
                )
            if response.status_code == 429:
                raise DriftGuardError(
                    code="github_rate_limited",
                    message="GitHub rate-limited the repository operation.",
                    status_code=429,
                )
            if response.status_code == 422:
                raise _write_conflict()
            raise DriftGuardError(
                code="github_write_failed",
                message="GitHub could not complete the repository operation.",
                status_code=502,
            )
        if response.status_code == 404:
            return {"_status": 404}
        data = response.json() if response.content else {}
        return {"_items": data} if isinstance(data, list) else dict(data)


def _write_conflict() -> DriftGuardError:
    return DriftGuardError(
        code="github_branch_conflict",
        message="The deterministic DriftGuard branch exists in an unexpected state.",
        status_code=409,
    )


def _q(value: str) -> str:
    return quote(value, safe="")


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _b64json(value: dict[str, Any]) -> str:
    return _b64(json.dumps(value, separators=(",", ":")).encode())


def _is_sha(value: str) -> bool:
    return len(value) == 40 and all(character in "0123456789abcdef" for character in value)


def _sha40(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode()).hexdigest()[:40]
