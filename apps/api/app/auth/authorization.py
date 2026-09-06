"""Centralized workspace role and capability authorization."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.core.workspace_context import WorkspacePrincipal, current_principal
from apps.api.app.domain.workspace import WorkspaceRole


class Permission(StrEnum):
    READ_WORKSPACE = "workspace:read"
    MANAGE_ORGANIZATION = "organization:manage"
    MANAGE_MEMBERS = "members:manage"
    READ_AUDIT = "audit:read"
    READ_REPOSITORIES = "repositories:read"
    MANAGE_REPOSITORIES = "repositories:manage"
    READ_ANALYSES = "analyses:read"
    RUN_ANALYSES = "analyses:run"
    DELETE_ANALYSES = "analyses:delete"
    READ_MONITORS = "monitors:read"
    MANAGE_MONITORS = "monitors:manage"
    RUN_MONITOR_CHECKS = "monitors:check"
    GENERATE_PATCH = "patches:generate"
    VALIDATE_PATCH = "patches:validate"
    CREATE_PULL_REQUEST = "pull_requests:create"


_VIEWER = frozenset(
    {
        Permission.READ_WORKSPACE,
        Permission.READ_AUDIT,
        Permission.READ_REPOSITORIES,
        Permission.READ_ANALYSES,
        Permission.READ_MONITORS,
    }
)
_DEVELOPER = _VIEWER | {
    Permission.RUN_ANALYSES,
    Permission.RUN_MONITOR_CHECKS,
    Permission.GENERATE_PATCH,
    Permission.VALIDATE_PATCH,
    Permission.CREATE_PULL_REQUEST,
}
_ADMIN = _DEVELOPER | {
    Permission.MANAGE_MEMBERS,
    Permission.MANAGE_REPOSITORIES,
    Permission.DELETE_ANALYSES,
    Permission.MANAGE_MONITORS,
}
_OWNER = _ADMIN | {Permission.MANAGE_ORGANIZATION}

ROLE_PERMISSIONS: dict[WorkspaceRole, frozenset[Permission]] = {
    WorkspaceRole.OWNER: frozenset(_OWNER),
    WorkspaceRole.ADMIN: frozenset(_ADMIN),
    WorkspaceRole.DEVELOPER: frozenset(_DEVELOPER),
    WorkspaceRole.VIEWER: _VIEWER,
}


def authorize(
    permission: Permission,
    principal: WorkspacePrincipal | None = None,
) -> WorkspacePrincipal:
    resolved = principal or current_principal()
    if resolved.local or resolved.system:
        return resolved
    if resolved.user_id is None or resolved.role is None:
        raise DriftGuardError(
            code="auth_required",
            message="Sign in to continue.",
            status_code=401,
        )
    if permission not in ROLE_PERMISSIONS[resolved.role]:
        raise DriftGuardError(
            code="permission_denied",
            message="Your workspace role does not allow this action.",
            status_code=403,
            details={"required_permission": permission.value},
        )
    return resolved


def requires(permission: Permission) -> Callable[[], WorkspacePrincipal]:
    def dependency() -> WorkspacePrincipal:
        return authorize(permission)

    return dependency


def can(role: WorkspaceRole, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[role]
