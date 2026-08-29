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
)
from apps.api.app.schemas.auth import (
    AuthStatusResponse,
    UserResponse,
    WorkspaceCreateRequest,
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
            workspace=WorkspaceResponse(
                id=LOCAL_WORKSPACE_ID,
                name=LOCAL_WORKSPACE_NAME,
                slug=LOCAL_WORKSPACE_SLUG,
                role="owner",
            ),
        )
    auth = request.state.auth
    if auth is None:
        return AuthStatusResponse(mode="github", authenticated=False)
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
        user=UserResponse(
            id=user.user_id,
            github_login=user.github_login,
            github_display_name=user.github_display_name,
            avatar_url=user.avatar_url,
        ),
        workspace=active,
        workspaces=responses,
        csrf_token=request.cookies.get("driftguard_csrf"),
    )


@router.get("/github/start")
def github_start(
    service: Auth,
    return_to: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    if settings.auth_mode != "github":
        raise DriftGuardError(
            code="auth_not_enabled",
            message="GitHub authentication is not enabled in local mode.",
            status_code=409,
        )
    return RedirectResponse(service.begin(return_to))


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


def _auth(request: Request):
    if request.state.auth is None:
        raise DriftGuardError(
            code="auth_required", message="Sign in with GitHub to continue.", status_code=401
        )
    return request.state.auth
