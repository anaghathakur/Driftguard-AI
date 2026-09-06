"""GitHub App installation access for onboarding and selective source ingestion."""

from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from dataclasses import dataclass
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from apps.api.app.core.config import settings
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.pull_requests.provider import GitHubAppWriteProvider
from apps.api.app.repository.github_source import GitHubRepositoryArchive
from apps.api.app.repository.policy import RepositoryFilteringPolicy
from apps.api.app.repository.scanner import SOURCE_EXTENSIONS


@dataclass(frozen=True, slots=True)
class InstallationMetadata:
    github_installation_id: int
    account_id: int
    account_login: str
    account_type: str


@dataclass(frozen=True, slots=True)
class GitHubRepositoryInfo:
    github_repository_id: int
    owner: str
    name: str
    full_name: str
    default_branch: str
    private: bool
    html_url: str


class GitHubInstallationProvider(ABC):
    @abstractmethod
    async def get_installation(self, installation_id: int) -> InstallationMetadata: ...

    @abstractmethod
    async def list_repositories(self, installation_id: int) -> list[GitHubRepositoryInfo]: ...

    @abstractmethod
    async def fetch_repository(
        self, installation_id: int, repository_id: int, ref: str | None
    ) -> GitHubRepositoryArchive: ...


class MockGitHubInstallationProvider(GitHubInstallationProvider):
    """Deterministic provider for local tests; no token or customer code is persisted."""

    def __init__(self) -> None:
        self.installations: dict[int, InstallationMetadata] = {
            1: InstallationMetadata(1, 1, "driftguard-dev", "User")
        }
        self.repositories: dict[int, list[GitHubRepositoryInfo]] = {1: []}
        self.archives: dict[int, GitHubRepositoryArchive] = {}

    async def get_installation(self, installation_id: int) -> InstallationMetadata:
        value = self.installations.get(installation_id)
        if value is None:
            raise _installation_not_found()
        return value

    async def list_repositories(self, installation_id: int) -> list[GitHubRepositoryInfo]:
        await self.get_installation(installation_id)
        return list(self.repositories.get(installation_id, []))

    async def fetch_repository(
        self, installation_id: int, repository_id: int, ref: str | None
    ) -> GitHubRepositoryArchive:
        await self.get_installation(installation_id)
        authorized = {
            item.github_repository_id for item in self.repositories.get(installation_id, [])
        }
        if repository_id not in authorized:
            raise _repository_not_authorized()
        archive = self.archives.get(repository_id)
        if archive is None:
            raise DriftGuardError(
                code="repository_not_found",
                message="The connected GitHub repository is unavailable.",
                status_code=404,
            )
        if ref and ref != archive.ref:
            return GitHubRepositoryArchive(
                owner=archive.owner,
                repository=archive.repository,
                ref=ref,
                filename=archive.filename,
                content=archive.content,
                commit_sha=archive.commit_sha,
            )
        return archive


class RealGitHubInstallationProvider(GitHubInstallationProvider):
    """GitHub REST adapter using short-lived installation tokens only in memory."""

    def __init__(self, app_id: str, private_key_path: str, timeout_seconds: float) -> None:
        self.client = GitHubAppWriteProvider(
            app_id=app_id,
            private_key_path=private_key_path,
            timeout_seconds=timeout_seconds,
        )
        self.policy = RepositoryFilteringPolicy(SOURCE_EXTENSIONS)

    async def get_installation(self, installation_id: int) -> InstallationMetadata:
        data = await self.client._request(
            "GET",
            f"/app/installations/{installation_id}",
            token=self.client._app_jwt(),
            app_auth=True,
            expected={200},
            not_found_code="github_installation_not_found",
        )
        account = data.get("account") or {}
        return InstallationMetadata(
            installation_id,
            int(account.get("id", 0)),
            str(account.get("login", "")),
            str(account.get("type", "Unknown")),
        )

    async def list_repositories(self, installation_id: int) -> list[GitHubRepositoryInfo]:
        await self.get_installation(installation_id)
        token = await self._installation_token(installation_id)
        data = await self.client._request(
            "GET",
            "/installation/repositories",
            token=token,
            expected={200},
            params={"per_page": "100"},
        )
        return [_repository_info(item) for item in data.get("repositories", [])]

    async def fetch_repository(
        self, installation_id: int, repository_id: int, ref: str | None
    ) -> GitHubRepositoryArchive:
        repositories = await self.list_repositories(installation_id)
        repository = next(
            (item for item in repositories if item.github_repository_id == repository_id), None
        )
        if repository is None:
            raise _repository_not_authorized()
        token = await self._installation_token(installation_id)
        owner, name = repository.owner, repository.name
        selected_ref = ref or repository.default_branch
        commit = await self.client._request(
            "GET",
            f"/repos/{owner}/{name}/commits/{selected_ref}",
            token=token,
            expected={200},
            not_found_code="repository_not_found",
        )
        commit_sha = str(commit.get("sha", ""))
        tree = await self.client._request(
            "GET",
            f"/repos/{owner}/{name}/git/trees/{commit_sha}",
            token=token,
            expected={200},
            params={"recursive": "1"},
        )
        entries = tree.get("tree") or []
        if tree.get("truncated") or len(entries) > settings.max_repository_tree_entries:
            raise DriftGuardError(
                code="repository_file_limit_exceeded",
                message="Repository tree exceeds the configured entry limit.",
                status_code=413,
                details={
                    "limit": "github_tree_entries",
                    "actual_entries": len(entries),
                    "configured_max_entries": settings.max_repository_tree_entries,
                    "github_tree_truncated": bool(tree.get("truncated")),
                    "configuration": "DRIFTGUARD_MAX_REPOSITORY_TREE_ENTRIES",
                },
            )
        candidates = [
            item
            for item in entries
            if item.get("type") == "blob" and self.policy.includes(str(item.get("path", "")))
        ]
        if len(candidates) > settings.max_repository_source_files:
            raise DriftGuardError(
                code="repository_source_limit_exceeded",
                message="Repository contains too many source files to analyze safely.",
                status_code=413,
                details={
                    "limit": "source_files",
                    "actual_files": len(candidates),
                    "configured_max_files": settings.max_repository_source_files,
                    "configuration": "DRIFTGUARD_MAX_REPOSITORY_SOURCE_FILES",
                },
            )
        declared_bytes = sum(int(item.get("size", 0)) for item in candidates)
        if declared_bytes > settings.max_repository_source_bytes:
            raise DriftGuardError(
                code="repository_source_limit_exceeded",
                message="Repository source content exceeds the aggregate analysis limit.",
                status_code=413,
                details={"maximum": settings.max_repository_source_bytes},
            )
        root = f"{name}-{commit_sha[:12]}"
        output = BytesIO()
        actual_bytes = 0
        with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
            for item in candidates:
                size = int(item.get("size", 0))
                if size > settings.max_repository_source_file_bytes:
                    raise DriftGuardError(
                        code="repository_too_large",
                        message="A source file exceeds the per-file analysis limit.",
                        status_code=413,
                    )
                blob = await self.client._request(
                    "GET",
                    f"/repos/{owner}/{name}/git/blobs/{item['sha']}",
                    token=token,
                    expected={200},
                )
                raw = base64.b64decode(str(blob.get("content", "")), validate=False)
                actual_bytes += len(raw)
                if actual_bytes > settings.max_repository_source_bytes:
                    raise DriftGuardError(
                        code="repository_source_limit_exceeded",
                        message="Repository source content exceeds the aggregate analysis limit.",
                        status_code=413,
                    )
                archive.writestr(f"{root}/{item['path']}", raw)
        content = output.getvalue()
        if len(content) > settings.max_repository_archive_bytes:
            raise DriftGuardError(
                code="repository_too_large",
                message="The filtered repository snapshot exceeds the archive limit.",
                status_code=413,
            )
        return GitHubRepositoryArchive(
            owner=owner,
            repository=name,
            ref=selected_ref,
            filename=f"{name}-{commit_sha[:12]}.zip",
            content=content,
            commit_sha=commit_sha,
        )

    async def _installation_token(self, installation_id: int) -> str:
        data = await self.client._request(
            "POST",
            f"/app/installations/{installation_id}/access_tokens",
            token=self.client._app_jwt(),
            app_auth=True,
            expected={201},
            json_body={"permissions": {"contents": "read", "metadata": "read"}},
        )
        token = str(data.get("token", ""))
        if not token:
            raise DriftGuardError(
                code="github_installation_revoked",
                message="The GitHub App installation is unavailable or revoked.",
                status_code=409,
            )
        return token


def _repository_info(value: dict[str, object]) -> GitHubRepositoryInfo:
    owner = value.get("owner") or {}
    return GitHubRepositoryInfo(
        int(value["id"]),
        str(owner.get("login", "")),
        str(value["name"]),
        str(value["full_name"]),
        str(value.get("default_branch", "main")),
        bool(value.get("private", False)),
        str(value.get("html_url", "")),
    )


def _installation_not_found() -> DriftGuardError:
    return DriftGuardError(
        code="github_installation_not_found",
        message="The GitHub App installation was not found.",
        status_code=404,
    )


def _repository_not_authorized() -> DriftGuardError:
    return DriftGuardError(
        code="repository_not_authorized",
        message="This repository is not authorized for the active workspace installation.",
        status_code=403,
    )
