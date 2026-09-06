"""Identity, workspace, GitHub onboarding, and audit records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class WorkspaceRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    DEVELOPER = "developer"
    VIEWER = "viewer"
    MEMBER = "developer"  # Backward-compatible code alias; persisted `member` is migrated.


@dataclass(frozen=True, slots=True)
class User:
    user_id: str
    github_user_id: int
    github_login: str
    github_display_name: str | None
    avatar_url: str | None
    created_at: datetime
    updated_at: datetime
    external_auth_provider: str = "github"
    external_subject: str | None = None
    email: str | None = None


@dataclass(frozen=True, slots=True)
class Workspace:
    workspace_id: str
    name: str
    slug: str
    created_at: datetime
    updated_at: datetime
    created_by_user_id: str | None = None


@dataclass(frozen=True, slots=True)
class WorkspaceMembership:
    membership_id: str
    workspace_id: str
    user_id: str
    role: WorkspaceRole
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AuthSession:
    session_hash: str
    user_id: str
    active_workspace_id: str | None
    csrf_hash: str
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class OAuthState:
    state_hash: str
    return_to: str
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class GitHubInstallation:
    installation_id: str
    workspace_id: str
    github_installation_id: int
    github_account_id: int
    github_account_login: str
    account_type: str
    created_at: datetime
    updated_at: datetime
    revoked_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RepositoryConnection:
    connection_id: str
    workspace_id: str
    installation_id: str
    github_repository_id: int
    owner: str
    name: str
    full_name: str
    default_branch: str
    private: bool
    html_url: str
    enabled: bool
    created_at: datetime
    updated_at: datetime
    last_synced_at: datetime
    removed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_id: str
    workspace_id: str | None
    user_id: str | None
    action: str
    resource_type: str
    resource_id: str | None
    metadata_safe: dict[str, object]
    created_at: datetime
