"""Read validated contract files from workspace-authorized GitHub App repositories."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import PurePosixPath

from apps.api.app.contracts.registry import default_contract_registry
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.core.workspace_context import current_workspace_id
from apps.api.app.domain.workspace import RepositoryConnection
from apps.api.app.github.automation_provider import GitHubAutomationProvider
from apps.api.app.github.installations import GitHubInstallationProvider
from apps.api.app.monitoring.specification_source import RemoteSpecification
from apps.api.app.ports.workspace_repository import WorkspaceRepository


@dataclass(frozen=True, slots=True)
class GitHubFileSpecification:
    specification: RemoteSpecification
    repository: RepositoryConnection
    commit_sha: str


class GitHubFileContractSource:
    """Fetch a contract at an immutable, GitHub-App-authorized commit only."""

    def __init__(
        self,
        workspace_repository: WorkspaceRepository,
        provider: GitHubAutomationProvider,
        installation_provider: GitHubInstallationProvider,
    ) -> None:
        self.workspace_repository = workspace_repository
        self.provider = provider
        self.installation_provider = installation_provider

    async def fetch(
        self,
        repository_connection_id: str,
        path: str,
        ref: str | None = None,
    ) -> GitHubFileSpecification:
        _validate_path(path)
        repository = self._repository(repository_connection_id)
        installation = self.workspace_repository.get_installation(repository.installation_id)
        if installation is None or installation.workspace_id != current_workspace_id():
            raise DriftGuardError(
                code="github_installation_not_found",
                message="The repository's GitHub App installation is unavailable.",
                status_code=404,
            )
        if installation.revoked_at is not None:
            raise DriftGuardError(
                code="github_installation_revoked",
                message="The repository's GitHub App installation has been revoked.",
                status_code=409,
            )

        commit_sha = await self.provider.resolve_commit(
            installation.github_installation_id,
            repository,
            ref or repository.default_branch,
        )
        content = await self.provider.fetch_file(
            installation.github_installation_id,
            repository,
            path,
            commit_sha,
        )
        filename = PurePosixPath(path).name
        adapter = default_contract_registry.resolve(filename, content)
        # Contract parsing is validation only. Downloaded content is never executed.
        adapter.parse(filename, content)
        specification = RemoteSpecification(
            source_url=f"github://{repository.full_name}/{path}@{commit_sha}",
            filename=filename,
            content_type="application/octet-stream",
            content=content,
            sha256=hashlib.sha256(content).hexdigest(),
            contract_type=adapter.contract_type,
        )
        return GitHubFileSpecification(specification, repository, commit_sha)

    async def fetch_repository(
        self,
        repository: RepositoryConnection,
        commit_sha: str,
    ):
        installation = self.workspace_repository.get_installation(repository.installation_id)
        if installation is None or installation.workspace_id != current_workspace_id():
            raise DriftGuardError(
                code="github_installation_not_found",
                message="The repository's GitHub App installation is unavailable.",
                status_code=404,
            )
        return await self.installation_provider.fetch_repository(
            installation.github_installation_id,
            repository.github_repository_id,
            commit_sha,
        )

    def _repository(self, connection_id: str) -> RepositoryConnection:
        repository = self.workspace_repository.get_repository(connection_id)
        if (
            repository is None
            or repository.workspace_id != current_workspace_id()
            or not repository.enabled
            or repository.removed_at is not None
        ):
            raise DriftGuardError(
                code="repository_not_authorized",
                message="This repository is not authorized for the active workspace.",
                status_code=403,
            )
        return repository


def _validate_path(path: str) -> None:
    normalized = path.replace("\\", "/")
    parts = normalized.split("/")
    if (
        not normalized
        or normalized.startswith("/")
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise DriftGuardError(
            code="contract_path_invalid",
            message="The contract path must stay inside the authorized repository.",
            status_code=422,
        )
