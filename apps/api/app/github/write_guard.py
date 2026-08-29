"""Workspace authorization guard around the existing safe GitHub write provider."""

from __future__ import annotations

from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.core.workspace_context import current_principal
from apps.api.app.ports.workspace_repository import WorkspaceRepository
from apps.api.app.pull_requests.provider import (
    GitHubBranchState,
    GitHubPullRequestResult,
    GitHubRepositoryMetadata,
    GitHubWriteProvider,
)


class WorkspaceAuthorizedGitHubWriteProvider(GitHubWriteProvider):
    def __init__(self, delegate: GitHubWriteProvider, repository: WorkspaceRepository) -> None:
        self.delegate = delegate
        self.repository = repository
        self.name = delegate.name

    async def prepare_repository(
        self,
        repository_url: str,
        ref: str | None,
        expected_commit_sha: str | None = None,
    ) -> GitHubRepositoryMetadata:
        principal = current_principal()
        if not principal.local:
            normalized = repository_url.rstrip("/").casefold()
            connection = next(
                (
                    item
                    for item in self.repository.list_repositories(principal.workspace_id)
                    if item.enabled
                    and item.removed_at is None
                    and item.html_url.rstrip("/").casefold() == normalized
                ),
                None,
            )
            if connection is None:
                raise DriftGuardError(
                    code="repository_not_authorized",
                    message=(
                        "Pull Requests are limited to repositories authorized for this workspace."
                    ),
                    status_code=403,
                )
            installation = self.repository.get_installation(connection.installation_id)
            if installation is None or installation.workspace_id != principal.workspace_id:
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
            metadata = await self.delegate.prepare_repository(
                repository_url, ref, expected_commit_sha
            )
            if (
                metadata.installation_id is not None
                and metadata.installation_id != installation.github_installation_id
            ):
                raise DriftGuardError(
                    code="repository_not_authorized",
                    message=(
                        "GitHub did not authorize this repository through the workspace "
                        "installation."
                    ),
                    status_code=403,
                )
            return metadata
        return await self.delegate.prepare_repository(repository_url, ref, expected_commit_sha)

    async def get_branch(
        self, metadata: GitHubRepositoryMetadata, branch: str
    ) -> GitHubBranchState | None:
        return await self.delegate.get_branch(metadata, branch)

    async def create_branch(
        self, metadata: GitHubRepositoryMetadata, branch: str, base_sha: str
    ) -> GitHubBranchState:
        return await self.delegate.create_branch(metadata, branch, base_sha)

    async def create_commit(
        self,
        metadata: GitHubRepositoryMetadata,
        *,
        base_sha: str,
        message: str,
        files: dict[str, str],
    ) -> str:
        return await self.delegate.create_commit(
            metadata, base_sha=base_sha, message=message, files=files
        )

    async def update_branch(
        self, metadata: GitHubRepositoryMetadata, branch: str, commit_sha: str
    ) -> GitHubBranchState:
        return await self.delegate.update_branch(metadata, branch, commit_sha)

    async def find_pull_request(
        self, metadata: GitHubRepositoryMetadata, branch: str
    ) -> GitHubPullRequestResult | None:
        return await self.delegate.find_pull_request(metadata, branch)

    async def create_pull_request(
        self,
        metadata: GitHubRepositoryMetadata,
        *,
        branch: str,
        title: str,
        body: str,
    ) -> GitHubPullRequestResult:
        return await self.delegate.create_pull_request(
            metadata, branch=branch, title=title, body=body
        )
