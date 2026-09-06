"""GitHub sign-in and workspace-session endpoints."""
# ruff: noqa: E501

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse

from apps.api.app.auth.service import AuthService
from apps.api.app.core.config import settings
from apps.api.app.core.dependencies import get_auth_service
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.core.workspace_context import (
    LOCAL_WORKSPACE_ID,
    LOCAL_WORKSPACE_NAME,
    LOCAL_WORKSPACE_SLUG,
    current_principal,
)
from apps.api.app.domain.workspace import WorkspaceRole
from apps.api.app.schemas.auth import (
    AuditEventResponse,
    AuthStatusResponse,
    UserResponse,
    WorkspaceCreateRequest,
    WorkspaceMemberResponse,
    WorkspaceMemberRoleRequest,
    WorkspaceResponse,
    WorkspaceSwitchRequest,
)

router = APIRouter(prefix="/auth", tags=["authentication"])
Auth = Annotated[AuthService, Depends(get_auth_service)]


@router.get("/status", response_model=AuthStatusResponse)
def auth_status(request: Request, service: Auth) -> AuthStatusResponse:
    if settings.auth_mode == "local":
        return AuthStatusResponse(
            mode="local",
            authenticated=False,
            github_auth_configured=False,
            google_auth_configured=False,
            workspace=WorkspaceResponse(
                id=LOCAL_WORKSPACE_ID,
                name=LOCAL_WORKSPACE_NAME,
                slug=LOCAL_WORKSPACE_SLUG,
                role="owner",
            ),
        )
    auth = request.state.auth
    if auth is None:
        return AuthStatusResponse(
            mode="github",
            authenticated=False,
            development_auth=_development_auth_enabled(),
            github_auth_configured=_github_auth_configured(),
        )
    session, user, workspace = auth
    memberships = service.repository.list_memberships(user.user_id)
    responses = [
        WorkspaceResponse(
            id=item.workspace_id, name=space.name, slug=space.slug, role=item.role.value
        )
        for item, space in memberships
    ]
    active = next(
        (item for item in responses if workspace and item.id == workspace.workspace_id), None
    )
    return AuthStatusResponse(
        mode="github",
        authenticated=True,
        development_auth=_development_auth_enabled(),
        github_auth_configured=_github_auth_configured(),
        user=UserResponse(
            id=user.user_id,
            github_login=user.github_login,
            github_display_name=user.github_display_name,
            avatar_url=user.avatar_url,
            auth_provider=user.external_auth_provider,
            email=user.email,
        ),
        workspace=active,
        workspaces=responses,
        csrf_token=request.cookies.get("driftguard_csrf"),
    )


@router.get("/github/start")
def github_start(
    service: Auth,
    return_to: Annotated[str | None, Query()] = None,
    identity: Annotated[str | None, Query(pattern="^(primary|secondary)$")] = None,
) -> RedirectResponse:
    if settings.auth_mode != "github":
        raise DriftGuardError(
            code="auth_not_enabled",
            message="GitHub authentication is not enabled in local mode.",
            status_code=409,
        )
    if identity is not None and not _development_auth_enabled():
        raise DriftGuardError(
            code="development_identity_unavailable",
            message="Development identities are not available for this authentication provider.",
            status_code=404,
        )
    return RedirectResponse(service.begin(return_to, identity))


@router.get("/github/callback")
async def github_callback(code: str, state: str, service: Auth) -> RedirectResponse:
    session_token, csrf_token, return_to = await service.callback(code, state)
    response = RedirectResponse(return_to)
    response.set_cookie(
        settings.session_cookie_name,
        session_token,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        max_age=settings.session_ttl_hours * 3600,
        path="/",
    )
    response.set_cookie(
        "driftguard_csrf",
        csrf_token,
        httponly=False,
        secure=settings.secure_cookies,
        samesite="lax",
        max_age=settings.session_ttl_hours * 3600,
        path="/",
    )
    return response


@router.post("/workspaces", response_model=WorkspaceResponse, status_code=201)
def create_workspace(
    payload: WorkspaceCreateRequest, request: Request, service: Auth
) -> WorkspaceResponse:
    session, user, _workspace = _auth(request)
    workspace = service.create_workspace(session, user, payload.name)
    return WorkspaceResponse(
        id=workspace.workspace_id, name=workspace.name, slug=workspace.slug, role="owner"
    )


@router.post("/workspaces/switch", response_model=WorkspaceResponse)
def switch_workspace(
    payload: WorkspaceSwitchRequest, request: Request, service: Auth
) -> WorkspaceResponse:
    session, user, _workspace = _auth(request)
    workspace = service.switch_workspace(session, user, payload.workspace_id)
    membership = service.repository.get_membership(user.user_id, workspace.workspace_id)
    return WorkspaceResponse(
        id=workspace.workspace_id,
        name=workspace.name,
        slug=workspace.slug,
        role=membership.role.value,
    )


@router.post("/logout", status_code=204)
def logout(request: Request, service: Auth) -> Response:
    session, _user, _workspace = _auth(request)
    service.logout(session)
    response = Response(status_code=204)
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie("driftguard_csrf", path="/")
    return response


@router.get(
    "/workspaces/current/members",
    response_model=list[WorkspaceMemberResponse],
)
def list_workspace_members(service: Auth) -> list[WorkspaceMemberResponse]:
    return [
        _member_response(membership, user)
        for membership, user in service.list_members(current_principal())
    ]


@router.patch(
    "/workspaces/current/members/{user_id}",
    response_model=WorkspaceMemberResponse,
)
def change_workspace_member_role(
    user_id: str,
    payload: WorkspaceMemberRoleRequest,
    service: Auth,
) -> WorkspaceMemberResponse:
    membership = service.change_member_role(
        current_principal(), user_id, WorkspaceRole(payload.role)
    )
    user = service.repository.get_user(user_id)
    if user is None:
        raise DriftGuardError(
            code="workspace_member_not_found",
            message="The requested workspace member was not found.",
            status_code=404,
        )
    return _member_response(membership, user)


@router.delete("/workspaces/current/members/{user_id}", status_code=204)
def remove_workspace_member(user_id: str, service: Auth) -> Response:
    service.remove_member(current_principal(), user_id)
    return Response(status_code=204)


@router.get("/workspaces/current/audit", response_model=list[AuditEventResponse])
def list_workspace_audit(
    service: Auth, limit: Annotated[int, Query(ge=1, le=200)] = 100
) -> list[AuditEventResponse]:
    return [
        AuditEventResponse(
            id=event.event_id,
            user_id=event.user_id,
            action=event.action,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            metadata=event.metadata_safe,
            created_at=event.created_at,
        )
        for event in service.list_audit_events(current_principal(), limit)
    ]


def _member_response(membership, user) -> WorkspaceMemberResponse:
    return WorkspaceMemberResponse(
        user_id=user.user_id,
        github_login=user.github_login,
        github_display_name=user.github_display_name,
        avatar_url=user.avatar_url,
        email=user.email,
        role=membership.role.value,
        joined_at=membership.created_at,
    )


def _auth(request: Request):
    if request.state.auth is None:
        raise DriftGuardError(
            code="auth_required", message="Sign in with GitHub to continue.", status_code=401
        )
    return request.state.auth


def _development_auth_enabled(value=settings) -> bool:
    return (
        value.deployment_environment == "development"
        and value.github_oauth_provider == "mock"
    )


def _github_auth_configured(value=settings) -> bool:
    return (
        value.github_oauth_provider == "github"
        and bool(value.github_oauth_client_id)
        and bool(value.github_oauth_client_secret)
    )
