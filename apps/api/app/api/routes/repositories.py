"""Authenticated GitHub App installation and repository endpoints."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse

from apps.api.app.auth.authorization import Permission, authorize, requires
from apps.api.app.core.config import settings
from apps.api.app.core.dependencies import get_github_onboarding_service
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.core.workspace_context import current_principal
from apps.api.app.github.service import GitHubOnboardingService
from apps.api.app.schemas.repository_connection import (
    InstallationConnectRequest,
    InstallationResponse,
    RepositoryConnectionResponse,
    RepositoryEnableRequest,
)

router = APIRouter(
    prefix="/github",
    tags=["GitHub repositories"],
    dependencies=[Depends(requires(Permission.READ_REPOSITORIES))],
)
Service = Annotated[GitHubOnboardingService, Depends(get_github_onboarding_service)]


@router.get("/installations/start")
def start_installation(service: Service, return_to: str | None = None) -> RedirectResponse:
    authorize(Permission.MANAGE_REPOSITORIES)
    if not settings.github_app_install_url:
        raise DriftGuardError(
            code="github_app_not_configured",
            message="The GitHub App installation URL is not configured.",
            status_code=503,
        )
    state = service.auth.issue_state(return_to)
    separator = "&" if "?" in settings.github_app_install_url else "?"
    return RedirectResponse(
        f"{settings.github_app_install_url}{separator}{urlencode({'state': state})}"
    )


@router.get("/installations/callback")
async def installation_callback(
    installation_id: int,
    state: str,
    service: Service,
) -> RedirectResponse:
    authorization = service.auth.consume_state(state)
    await service.connect(current_principal(), installation_id)
    return RedirectResponse(authorization.return_to)


@router.get("/installations", response_model=list[InstallationResponse])
def list_installations(service: Service) -> list[InstallationResponse]:
    principal = current_principal()
    return [
        _installation(item)
        for item in service.repository.list_installations(principal.workspace_id)
    ]


@router.post("/installations", response_model=InstallationResponse, status_code=201)
async def connect_installation(
    request: InstallationConnectRequest, service: Service
) -> InstallationResponse:
    if settings.github_write_provider != "mock":
        raise DriftGuardError(
            code="github_installation_setup_required",
            message="Start GitHub App installation from the authenticated setup flow.",
            status_code=409,
        )
    return _installation(await service.connect(current_principal(), request.github_installation_id))


@router.post(
    "/installations/{installation_id}/sync",
    response_model=list[RepositoryConnectionResponse],
)
async def sync_installation(
    installation_id: str, service: Service
) -> list[RepositoryConnectionResponse]:
    return [_repository(item) for item in await service.sync(current_principal(), installation_id)]


@router.get("/repositories", response_model=list[RepositoryConnectionResponse])
def list_repositories(service: Service) -> list[RepositoryConnectionResponse]:
    principal = current_principal()
    return [
        _repository(item) for item in service.repository.list_repositories(principal.workspace_id)
    ]


@router.patch("/repositories/{connection_id}", response_model=RepositoryConnectionResponse)
def set_repository_enabled(
    connection_id: str, request: RepositoryEnableRequest, service: Service
) -> RepositoryConnectionResponse:
    return _repository(service.set_enabled(current_principal(), connection_id, request.enabled))


def _installation(item) -> InstallationResponse:
    return InstallationResponse(
        id=item.installation_id,
        github_installation_id=item.github_installation_id,
        account_id=item.github_account_id,
        account_login=item.github_account_login,
        account_type=item.account_type,
        connected_at=item.created_at,
        revoked=item.revoked_at is not None,
    )


def _repository(item) -> RepositoryConnectionResponse:
    return RepositoryConnectionResponse(
        id=item.connection_id,
        installation_id=item.installation_id,
        github_repository_id=item.github_repository_id,
        owner=item.owner,
        name=item.name,
        full_name=item.full_name,
        default_branch=item.default_branch,
        private=item.private,
        html_url=item.html_url,
        enabled=item.enabled,
        last_synced_at=item.last_synced_at,
        removed=item.removed_at is not None,
    )
