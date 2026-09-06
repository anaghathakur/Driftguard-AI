"""Request authentication and workspace-context middleware."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from apps.api.app.auth.service import AuthService
from apps.api.app.core.config import Settings
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.core.workspace_context import (
    LOCAL_WORKSPACE_ID,
    WorkspacePrincipal,
    reset_principal,
    set_principal,
)


class WorkspaceContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, settings: Settings, auth_service: AuthService) -> None:
        super().__init__(app)
        self.settings = settings
        self.auth_service = auth_service

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method == "OPTIONS":
            return await call_next(request)
        principal = WorkspacePrincipal(LOCAL_WORKSPACE_ID, local=True)
        request.state.auth = None
        try:
            if self.settings.auth_mode == "github":
                session_token = request.cookies.get(self.settings.session_cookie_name)
                public = _is_public(request.url.path)
                if session_token:
                    session, user, workspace = self.auth_service.authenticate(session_token)
                    request.state.auth = (session, user, workspace)
                    if workspace:
                        membership = self.auth_service.repository.get_membership(
                            user.user_id, workspace.workspace_id
                        )
                        if membership is None:
                            raise _workspace_access_denied()
                        principal = WorkspacePrincipal(
                            workspace.workspace_id,
                            user.user_id,
                            user.github_login,
                            role=membership.role,
                        )
                    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not public:
                        self.auth_service.verify_csrf(session, request.headers.get("X-CSRF-Token"))
                elif not public:
                    raise DriftGuardError(
                        code="auth_required",
                        message="Sign in with GitHub to continue.",
                        status_code=401,
                    )
                if not public and principal.local and not _allows_missing_workspace(request):
                    raise DriftGuardError(
                        code="workspace_required",
                        message="Create or select a workspace before using team resources.",
                        status_code=409,
                    )
            elif self.settings.auth_mode != "local":
                raise DriftGuardError(
                    code="auth_configuration_invalid",
                    message="The authentication mode is unsupported.",
                    status_code=503,
                )
            token = set_principal(principal)
            try:
                response = await call_next(request)
                action = _audit_action(request.method, request.url.path)
                if action and response.status_code < 400:
                    resource_type, resource_id = _resource(request.url.path)
                    self.auth_service.audit(
                        principal.workspace_id,
                        principal.user_id,
                        action,
                        resource_type,
                        resource_id,
                    )
                return response
            finally:
                reset_principal(token)
        except DriftGuardError as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={
                    "error": {
                        "code": exc.code,
                        "message": exc.message,
                        "details": exc.details,
                    }
                },
            )


def _is_public(path: str) -> bool:
    return path in {
        "/health",
        "/ready",
        "/api/v1/health",
        "/api/v1/ready",
        "/api/v1/auth/status",
        "/api/v1/auth/github/start",
        "/api/v1/auth/github/callback",
        "/api/v1/github/webhooks",
    }


def _allows_missing_workspace(request: Request) -> bool:
    return request.method == "POST" and request.url.path == "/api/v1/auth/workspaces"


def _audit_action(method: str, path: str) -> str | None:
    if method == "POST" and ("/impact/analyze" in path or path.endswith("/compare")):
        return "analysis.created"
    if method == "POST" and path.endswith("/patches"):
        return "patch.generated"
    if method == "POST" and path.endswith("/validations"):
        return "validation.run"
    if method == "GET" and path.endswith("/pull-request/preview"):
        return "pull_request.previewed"
    if method == "POST" and path.endswith("/pull-request"):
        return "pull_request.created"
    if path == "/api/v1/monitors" and method == "POST":
        return "monitor.created"
    if "/api/v1/monitors/" in path and method == "PATCH":
        return "monitor.updated"
    if "/api/v1/monitors/" in path and method == "DELETE":
        return "monitor.deleted"
    if path.endswith("/check") and "/api/v1/monitors/" in path and method == "POST":
        return "monitor.checked"
    return None


def _resource(path: str) -> tuple[str, str | None]:
    parts = [part for part in path.split("/") if part]
    if "analyses" in parts:
        index = parts.index("analyses")
        return "analysis", parts[index + 1] if len(parts) > index + 1 else None
    if "monitors" in parts:
        index = parts.index("monitors")
        return "monitor", parts[index + 1] if len(parts) > index + 1 else None
    return "analysis", None


def _workspace_access_denied() -> DriftGuardError:
    return DriftGuardError(
        code="workspace_access_denied",
        message="The active workspace is not available to this user.",
        status_code=403,
    )
