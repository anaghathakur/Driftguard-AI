"""Resolve workspace-connected repositories before public GitHub acquisition."""

from __future__ import annotations

from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.core.workspace_context import current_workspace_id
from apps.api.app.github.installations import GitHubInstallationProvider
from apps.api.app.ports.workspace_repository import WorkspaceRepository
from apps.api.app.repository.github_source import (
    GitHubRepositoryArchive,
    GitHubRepositorySource,
)


class ConnectedAwareGitHubRepositorySource(GitHubRepositorySource):
    def __init__(
        self,
        workspace_repository: WorkspaceRepository,
        installation_provider: GitHubInstallationProvider,
    ) -> None:
        super().__init__()
        self.workspace_repository = workspace_repository
        self.installation_provider = installation_provider

    async def fetch(self, repository_url: str, ref: str | None = None) -> GitHubRepositoryArchive:
        workspace_id = current_workspace_id()
        normalized = repository_url.rstrip("/").casefold()
        connection = next(
            (
                item
                for item in self.workspace_repository.list_repositories(workspace_id)
                if item.enabled
                and item.removed_at is None
                and item.html_url.rstrip("/").casefold() == normalized
            ),
            None,
        )
        if connection is None:
            return await super().fetch(repository_url, ref)
        installation = self.workspace_repository.get_installation(connection.installation_id)
        if installation is None or installation.workspace_id != workspace_id:
            raise DriftGuardError(
                code="github_installation_not_found",
                message="The repository's GitHub App installation is unavailable.",
                status_code=404,
            )
        if installation.revoked_at is not None:
            raise DriftGuardError(
                code="github_installation_revoked",
                message="The GitHub App installation has been revoked.",
                status_code=409,
            )
        return await self.installation_provider.fetch_repository(
            installation.github_installation_id,
            connection.github_repository_id,
            ref,
        )
