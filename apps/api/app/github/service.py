"""Workspace-authorized GitHub installation and repository orchestration."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from apps.api.app.auth.authorization import Permission, authorize
from apps.api.app.auth.service import AuthService
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.core.workspace_context import WorkspacePrincipal
from apps.api.app.domain.workspace import GitHubInstallation, RepositoryConnection
from apps.api.app.github.installations import GitHubInstallationProvider
from apps.api.app.ports.workspace_repository import WorkspaceRepository


class GitHubOnboardingService:
    def __init__(
        self,
        repository: WorkspaceRepository,
        provider: GitHubInstallationProvider,
        auth: AuthService,
    ) -> None:
        self.repository = repository
        self.provider = provider
        self.auth = auth

    async def connect(
        self, principal: WorkspacePrincipal, github_installation_id: int
    ) -> GitHubInstallation:
        authorize(Permission.MANAGE_REPOSITORIES, principal)
        metadata = await self.provider.get_installation(github_installation_id)
        now = datetime.now(UTC)
        installation = self.repository.upsert_installation(
            GitHubInstallation(
                str(uuid4()),
                principal.workspace_id,
                metadata.github_installation_id,
                metadata.account_id,
                metadata.account_login,
                metadata.account_type,
                now,
                now,
            )
        )
        if installation.workspace_id != principal.workspace_id:
            raise DriftGuardError(
                code="workspace_access_denied",
                message="This GitHub installation belongs to another workspace.",
                status_code=403,
            )
        self.auth.audit(
            principal.workspace_id,
            principal.user_id,
            "github_installation.connected",
            "github_installation",
            installation.installation_id,
        )
        return installation

    async def sync(
        self, principal: WorkspacePrincipal, installation_id: str
    ) -> list[RepositoryConnection]:
        authorize(Permission.MANAGE_REPOSITORIES, principal)
        installation = self._installation(principal, installation_id)
        if installation.revoked_at:
            raise DriftGuardError(
                code="github_installation_revoked",
                message="The GitHub App installation has been revoked.",
                status_code=409,
            )
        available = await self.provider.list_repositories(installation.github_installation_id)
        existing = {
            item.github_repository_id: item
            for item in self.repository.list_repositories(principal.workspace_id)
            if item.installation_id == installation_id
        }
        now = datetime.now(UTC)
        seen: set[int] = set()
        for item in available:
            seen.add(item.github_repository_id)
            current = existing.get(item.github_repository_id)
            self.repository.upsert_repository(
                RepositoryConnection(
                    current.connection_id if current else str(uuid4()),
                    principal.workspace_id,
                    installation_id,
                    item.github_repository_id,
                    item.owner,
                    item.name,
                    item.full_name,
                    item.default_branch,
                    item.private,
                    item.html_url,
                    current.enabled if current else True,
                    current.created_at if current else now,
                    now,
                    now,
                )
            )
        for github_id, current in existing.items():
            if github_id not in seen:
                self.repository.upsert_repository(
                    replace(
                        current, enabled=False, updated_at=now, last_synced_at=now, removed_at=now
                    )
                )
        self.auth.audit(
            principal.workspace_id,
            principal.user_id,
            "repository.synchronized",
            "github_installation",
            installation_id,
            {"repository_count": len(available)},
        )
        return self.repository.list_repositories(principal.workspace_id)

    def set_enabled(
        self, principal: WorkspacePrincipal, connection_id: str, enabled: bool
    ) -> RepositoryConnection:
        authorize(Permission.MANAGE_REPOSITORIES, principal)
        connection = self.require_repository(principal, connection_id, require_enabled=False)
        updated = replace(connection, enabled=enabled, updated_at=datetime.now(UTC))
        updated = self.repository.upsert_repository(updated)
        self.auth.audit(
            principal.workspace_id,
            principal.user_id,
            "repository.enabled" if enabled else "repository.disabled",
            "repository_connection",
            connection_id,
        )
        return updated

    def require_repository(
        self,
        principal: WorkspacePrincipal,
        connection_id: str,
        *,
        require_enabled: bool = True,
    ) -> RepositoryConnection:
        authorize(Permission.READ_REPOSITORIES, principal)
        connection = self.repository.get_repository(connection_id)
        if connection is None or connection.workspace_id != principal.workspace_id:
            raise DriftGuardError(
                code="repository_not_authorized",
                message="This repository is not authorized for the active workspace.",
                status_code=403,
            )
        if connection.removed_at or (require_enabled and not connection.enabled):
            raise DriftGuardError(
                code="repository_not_authorized",
                message="DriftGuard access to this repository is disabled or removed.",
                status_code=403,
            )
        return connection

    def _installation(
        self, principal: WorkspacePrincipal, installation_id: str
    ) -> GitHubInstallation:
        installation = self.repository.get_installation(installation_id)
        if installation is None or installation.workspace_id != principal.workspace_id:
            raise DriftGuardError(
                code="github_installation_not_found",
                message="The GitHub App installation was not found in this workspace.",
                status_code=404,
            )
        return installation
