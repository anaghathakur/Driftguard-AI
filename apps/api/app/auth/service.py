"""Server-side session, OAuth-state, workspace, and audit orchestration."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from apps.api.app.auth.provider import GitHubOAuthProvider
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.core.workspace_context import WorkspacePrincipal
from apps.api.app.domain.workspace import (
    AuditEvent,
    AuthSession,
    OAuthState,
    User,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)
from apps.api.app.ports.workspace_repository import WorkspaceRepository


class AuthService:
    def __init__(
        self,
        repository: WorkspaceRepository,
        provider: GitHubOAuthProvider,
        *,
        callback_url: str,
        frontend_url: str,
        session_ttl_hours: int,
        session_secret: str,
    ) -> None:
        self.repository = repository
        self.provider = provider
        self.callback_url = callback_url
        self.frontend_url = frontend_url.rstrip("/")
        self.session_ttl_hours = session_ttl_hours
        self.session_secret = session_secret.encode()

    def begin(self, return_to: str | None = None) -> str:
        state = self.issue_state(return_to)
        return self.provider.authorization_url(state, self.callback_url)

    def issue_state(self, return_to: str | None = None) -> str:
        target = self._safe_return_to(return_to)
        state = secrets.token_urlsafe(32)
        now = _now()
        self.repository.save_oauth_state(
            OAuthState(self._hash(state), target, now, now + timedelta(minutes=10))
        )
        return state

    def consume_state(self, state: str) -> OAuthState:
        stored = self.repository.consume_oauth_state(self._hash(state))
        if stored is None or stored.expires_at <= _now():
            raise DriftGuardError(
                code="oauth_state_invalid",
                message="The GitHub authorization state is invalid or expired.",
                status_code=401,
            )
        return stored

    async def callback(self, code: str, state: str) -> tuple[str, str, str]:
        stored = self.consume_state(state)
        identity = await self.provider.resolve_identity(code, self.callback_url)
        now = _now()
        existing = self.repository.get_user_by_github_id(identity.github_user_id)
        user = self.repository.upsert_user(
            User(
                existing.user_id if existing else str(uuid4()),
                identity.github_user_id,
                identity.login,
                identity.display_name,
                identity.avatar_url,
                existing.created_at if existing else now,
                now,
            )
        )
        memberships = self.repository.list_memberships(user.user_id)
        session_token = secrets.token_urlsafe(48)
        csrf_token = secrets.token_urlsafe(32)
        self.repository.save_session(
            AuthSession(
                self._hash(session_token),
                user.user_id,
                memberships[0][1].workspace_id if memberships else None,
                self._hash(csrf_token),
                now,
                now + timedelta(hours=self.session_ttl_hours),
            )
        )
        self.audit(None, user.user_id, "user.signed_in", "user", user.user_id)
        return session_token, csrf_token, stored.return_to

    def authenticate(self, token: str | None) -> tuple[AuthSession, User, Workspace | None]:
        if not token:
            raise _auth_required()
        session = self.repository.get_session(self._hash(token))
        if session is None or session.expires_at <= _now():
            if session:
                self.repository.delete_session(session.session_hash)
            raise DriftGuardError(
                code="invalid_session",
                message="The session is invalid or expired.",
                status_code=401,
            )
        user = self.repository.get_user(session.user_id)
        if user is None:
            raise _auth_required()
        workspace = None
        if session.active_workspace_id:
            if self.repository.get_membership(user.user_id, session.active_workspace_id) is None:
                raise DriftGuardError(
                    code="workspace_access_denied",
                    message="The active workspace is not available to this user.",
                    status_code=403,
                )
            workspace = self.repository.get_workspace(session.active_workspace_id)
        return session, user, workspace

    def principal(self, token: str | None) -> WorkspacePrincipal:
        _session, user, workspace = self.authenticate(token)
        if workspace is None:
            raise DriftGuardError(
                code="workspace_required",
                message="Create or select a workspace before using team resources.",
                status_code=409,
            )
        return WorkspacePrincipal(workspace.workspace_id, user.user_id, user.github_login)

    def verify_csrf(self, session: AuthSession, token: str | None) -> None:
        if not token or not secrets.compare_digest(session.csrf_hash, self._hash(token)):
            raise DriftGuardError(
                code="csrf_validation_failed",
                message="The request security token is missing or invalid.",
                status_code=403,
            )

    def create_workspace(self, session: AuthSession, user: User, name: str) -> Workspace:
        clean_name = " ".join(name.split())
        if not 2 <= len(clean_name) <= 80:
            raise DriftGuardError(
                code="workspace_name_invalid",
                message="Workspace name must contain between 2 and 80 characters.",
                status_code=422,
            )
        now = _now()
        workspace_id = str(uuid4())
        base_slug = re.sub(r"[^a-z0-9]+", "-", clean_name.lower()).strip("-") or "workspace"
        workspace = Workspace(workspace_id, clean_name, f"{base_slug}-{workspace_id[:8]}", now, now)
        membership = WorkspaceMembership(
            str(uuid4()), workspace_id, user.user_id, WorkspaceRole.OWNER, now
        )
        self.repository.create_workspace(workspace, membership)
        self.repository.update_session_workspace(session.session_hash, workspace_id)
        self.audit(workspace_id, user.user_id, "workspace.created", "workspace", workspace_id)
        return workspace

    def switch_workspace(self, session: AuthSession, user: User, workspace_id: str) -> Workspace:
        if self.repository.get_membership(user.user_id, workspace_id) is None:
            raise DriftGuardError(
                code="workspace_access_denied",
                message="You do not belong to the requested workspace.",
                status_code=403,
            )
        workspace = self.repository.get_workspace(workspace_id)
        if workspace is None:
            raise DriftGuardError(
                code="workspace_required",
                message="The workspace no longer exists.",
                status_code=404,
            )
        self.repository.update_session_workspace(session.session_hash, workspace_id)
        return workspace

    def logout(self, session: AuthSession) -> None:
        self.repository.delete_session(session.session_hash)

    def audit(
        self,
        workspace_id: str | None,
        user_id: str | None,
        action: str,
        resource_type: str,
        resource_id: str | None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        safe = {
            key: value
            for key, value in (metadata or {}).items()
            if key.lower() not in {"token", "secret", "authorization", "cookie", "code"}
        }
        self.repository.save_audit_event(
            AuditEvent(
                str(uuid4()),
                workspace_id,
                user_id,
                action,
                resource_type,
                resource_id,
                safe,
                _now(),
            )
        )

    def _safe_return_to(self, return_to: str | None) -> str:
        if not return_to:
            return self.frontend_url
        allowed_prefix = self.frontend_url + "/"
        if return_to != self.frontend_url and not return_to.startswith(allowed_prefix):
            raise DriftGuardError(
                code="oauth_redirect_invalid",
                message="The requested sign-in redirect is not allowed.",
                status_code=400,
            )
        return return_to

    def _hash(self, value: str) -> str:
        return hmac.new(self.session_secret, value.encode(), hashlib.sha256).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def _auth_required() -> DriftGuardError:
    return DriftGuardError(
        code="auth_required", message="Sign in with GitHub to continue.", status_code=401
    )
