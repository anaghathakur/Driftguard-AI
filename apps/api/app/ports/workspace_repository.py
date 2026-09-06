"""Persistence port for Phase 16 identity and GitHub onboarding state."""

from __future__ import annotations

from abc import ABC, abstractmethod

from apps.api.app.domain.workspace import (
    AuditEvent,
    AuthSession,
    GitHubInstallation,
    OAuthState,
    RepositoryConnection,
    User,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)


class WorkspaceRepository(ABC):
    @abstractmethod
    def initialize(self) -> None: ...

    @abstractmethod
    def upsert_user(self, user: User) -> User: ...

    @abstractmethod
    def get_user(self, user_id: str) -> User | None: ...

    @abstractmethod
    def get_user_by_github_id(self, github_user_id: int) -> User | None: ...

    @abstractmethod
    def create_workspace(self, workspace: Workspace, membership: WorkspaceMembership) -> None: ...

    @abstractmethod
    def ensure_workspace(
        self, workspace: Workspace, membership: WorkspaceMembership
    ) -> bool: ...

    @abstractmethod
    def get_workspace(self, workspace_id: str) -> Workspace | None: ...

    @abstractmethod
    def list_memberships(self, user_id: str) -> list[tuple[WorkspaceMembership, Workspace]]: ...
    @abstractmethod
    def list_workspace_members(
        self, workspace_id: str
    ) -> list[tuple[WorkspaceMembership, User]]: ...

    @abstractmethod
    def save_membership(self, membership: WorkspaceMembership) -> WorkspaceMembership: ...

    @abstractmethod
    def delete_membership(self, user_id: str, workspace_id: str) -> bool: ...

    @abstractmethod
    def count_members_by_role(self, workspace_id: str, role: WorkspaceRole) -> int: ...

    @abstractmethod
    def get_user_by_external_identity(self, provider: str, subject: str) -> User | None: ...

    @abstractmethod
    def get_membership(self, user_id: str, workspace_id: str) -> WorkspaceMembership | None: ...

    @abstractmethod
    def save_session(self, session: AuthSession) -> None: ...

    @abstractmethod
    def get_session(self, session_hash: str) -> AuthSession | None: ...

    @abstractmethod
    def update_session_workspace(self, session_hash: str, workspace_id: str) -> None: ...

    @abstractmethod
    def delete_session(self, session_hash: str) -> None: ...

    @abstractmethod
    def save_oauth_state(self, state: OAuthState) -> None: ...

    @abstractmethod
    def consume_oauth_state(self, state_hash: str) -> OAuthState | None: ...

    @abstractmethod
    def upsert_installation(self, installation: GitHubInstallation) -> GitHubInstallation: ...

    @abstractmethod
    def get_installation(self, installation_id: str) -> GitHubInstallation | None: ...

    @abstractmethod
    def get_installation_by_github_id(
        self, github_installation_id: int
    ) -> GitHubInstallation | None: ...

    @abstractmethod
    def list_installations(self, workspace_id: str) -> list[GitHubInstallation]: ...

    @abstractmethod
    def upsert_repository(self, repository: RepositoryConnection) -> RepositoryConnection: ...

    @abstractmethod
    def get_repository(self, connection_id: str) -> RepositoryConnection | None: ...

    @abstractmethod
    def get_repository_by_github_id(
        self, workspace_id: str, github_repository_id: int
    ) -> RepositoryConnection | None: ...

    @abstractmethod
    def list_repositories(self, workspace_id: str) -> list[RepositoryConnection]: ...

    @abstractmethod
    def save_audit_event(self, event: AuditEvent) -> None: ...

    @abstractmethod
    def list_audit_events(self, workspace_id: str, limit: int = 100) -> list[AuditEvent]: ...
