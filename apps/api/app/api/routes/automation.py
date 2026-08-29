"""Workspace-scoped GitHub automation configuration and status endpoints."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from apps.api.app.core.dependencies import (
    get_automation_repository,
    get_github_automation_provider,
    get_github_onboarding_service,
)
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.core.workspace_context import current_principal
from apps.api.app.domain.automation import (
    ApiDependency,
    BackgroundJob,
    BackgroundJobStatus,
    BackgroundJobType,
    ContractKind,
    RepositoryContract,
)
from apps.api.app.github.automation_provider import GitHubAutomationProvider
from apps.api.app.github.contracts import is_contract_candidate
from apps.api.app.github.service import GitHubOnboardingService
from apps.api.app.openapi.parser import parse_openapi_document
from apps.api.app.ports.automation_repository import AutomationRepository

router = APIRouter(prefix="/github/automation", tags=["GitHub automation"])
Automation = Annotated[AutomationRepository, Depends(get_automation_repository)]
Onboarding = Annotated[GitHubOnboardingService, Depends(get_github_onboarding_service)]
Provider = Annotated[GitHubAutomationProvider, Depends(get_github_automation_provider)]


class ContractPathRequest(BaseModel):
    path: str = Field(min_length=1, max_length=1024)


class EnabledRequest(BaseModel):
    enabled: bool


class DependencyRequest(BaseModel):
    contract_id: str | None = Field(default=None, max_length=100)
    monitor_id: str | None = Field(default=None, max_length=100)
    source_path: str | None = Field(default=None, max_length=1024)


@router.get("/repositories/{connection_id}")
def repository_automation(
    connection_id: str, automation: Automation, onboarding: Onboarding
) -> dict[str, object]:
    principal = current_principal()
    connection = onboarding.require_repository(principal, connection_id, require_enabled=False)
    return {
        "repository_id": connection.connection_id,
        "automation_enabled": connection.enabled and connection.removed_at is None,
        "contracts": [
            _serialize(item)
            for item in automation.list_contracts(principal.workspace_id, connection_id)
        ],
        "dependencies": [
            _serialize(item)
            for item in automation.list_dependencies(principal.workspace_id, connection_id)
        ],
        "checks": [
            _serialize(item)
            for item in automation.list_checks(principal.workspace_id, connection_id)
        ],
    }


@router.get("/jobs")
def list_jobs(automation: Automation, limit: int = 50) -> list[dict[str, object]]:
    safe_limit = min(max(limit, 1), 100)
    return [
        _serialize(item)
        for item in automation.list_jobs(current_principal().workspace_id, safe_limit)
    ]


@router.get("/jobs/{job_id}")
def get_job(job_id: str, automation: Automation) -> dict[str, object]:
    job = automation.get_job(job_id, current_principal().workspace_id)
    if job is None:
        raise DriftGuardError(
            code="job_not_found", message="The automation job was not found.", status_code=404
        )
    return _serialize(job)


@router.post("/repositories/{connection_id}/analyze", status_code=202)
async def analyze_repository(
    connection_id: str,
    automation: Automation,
    onboarding: Onboarding,
    provider: Provider,
) -> dict[str, object]:
    principal = current_principal()
    connection = onboarding.require_repository(principal, connection_id)
    installation = onboarding.repository.get_installation(connection.installation_id)
    if installation is None or installation.revoked_at:
        raise DriftGuardError(
            code="github_installation_revoked",
            message="Reconnect the GitHub App installation before analyzing this repository.",
            status_code=409,
        )
    commit_sha = await provider.resolve_commit(
        installation.github_installation_id, connection, connection.default_branch
    )
    now = datetime.now(UTC)
    job = automation.enqueue_job(
        BackgroundJob(
            str(uuid4()),
            principal.workspace_id,
            BackgroundJobType.GITHUB_PUSH_SCAN,
            BackgroundJobStatus.QUEUED,
            {
                "installation_id": installation.installation_id,
                "repository_connection_id": connection.connection_id,
                "after_sha": commit_sha,
                "changed_paths": await provider.list_paths(
                    installation.github_installation_id, connection, commit_sha
                ),
            },
            0,
            now,
        )
    )
    return {"status": "queued", "job": _serialize(job)}


@router.post("/repositories/{connection_id}/contracts", status_code=201)
async def configure_contract(
    connection_id: str,
    request: ContractPathRequest,
    automation: Automation,
    onboarding: Onboarding,
    provider: Provider,
) -> dict[str, object]:
    principal = current_principal()
    connection = onboarding.require_repository(principal, connection_id)
    path = _safe_contract_path(request.path)
    installation = onboarding.repository.get_installation(connection.installation_id)
    if installation is None or installation.revoked_at:
        raise DriftGuardError(
            code="github_installation_revoked",
            message="Reconnect the GitHub App installation before configuring contracts.",
            status_code=409,
        )
    commit_sha = await provider.resolve_commit(
        installation.github_installation_id, connection, connection.default_branch
    )
    paths = await provider.list_paths(installation.github_installation_id, connection, commit_sha)
    if path not in paths:
        raise DriftGuardError(
            code="contract_not_discovered",
            message="The contract path does not exist in the authorized repository snapshot.",
            status_code=404,
        )
    content = await provider.fetch_file(
        installation.github_installation_id, connection, path, commit_sha
    )
    document = parse_openapi_document(path, content)
    now = datetime.now(UTC)
    existing = next(
        (
            item
            for item in automation.list_contracts(principal.workspace_id, connection_id)
            if item.path == path
        ),
        None,
    )
    contract = automation.upsert_contract(
        RepositoryContract(
            existing.contract_id if existing else str(uuid4()),
            principal.workspace_id,
            connection_id,
            path,
            ContractKind.OPENAPI,
            str(document["info"]["title"]),
            str(document["openapi"]),
            existing.discovered_at if existing else now,
            now,
            commit_sha,
            True,
            True,
        )
    )
    return _serialize(contract)


@router.patch("/repositories/{connection_id}/contracts/{contract_id}")
def set_contract_enabled(
    connection_id: str,
    contract_id: str,
    request: EnabledRequest,
    automation: Automation,
    onboarding: Onboarding,
) -> dict[str, object]:
    principal = current_principal()
    onboarding.require_repository(principal, connection_id, require_enabled=False)
    contract = automation.get_contract(contract_id)
    if (
        contract is None
        or contract.workspace_id != principal.workspace_id
        or contract.repository_connection_id != connection_id
    ):
        raise DriftGuardError(
            code="contract_not_discovered",
            message="The repository contract was not found.",
            status_code=404,
        )
    return _serialize(
        automation.upsert_contract(
            replace(contract, enabled=request.enabled, updated_at=datetime.now(UTC))
        )
    )


@router.post("/repositories/{connection_id}/dependencies", status_code=201)
def confirm_dependency(
    connection_id: str,
    request: DependencyRequest,
    automation: Automation,
    onboarding: Onboarding,
) -> dict[str, object]:
    principal = current_principal()
    onboarding.require_repository(principal, connection_id)
    if not request.contract_id and not request.monitor_id:
        raise DriftGuardError(
            code="dependency_reference_required",
            message="Select a contract or monitor for this dependency.",
            status_code=422,
        )
    now = datetime.now(UTC)
    dependency = automation.save_dependency(
        ApiDependency(
            str(uuid4()),
            principal.workspace_id,
            connection_id,
            "manual_confirmation",
            1.0,
            now,
            now,
            request.contract_id,
            request.monitor_id,
            request.source_path,
            True,
        )
    )
    return _serialize(dependency)


def _safe_contract_path(value: str) -> str:
    normalized = value.replace("\\", "/").strip()
    pure = PurePosixPath(normalized)
    if (
        not normalized
        or normalized.startswith("/")
        or ".." in pure.parts
        or not is_contract_candidate(normalized)
    ):
        raise DriftGuardError(
            code="contract_path_invalid",
            message="Select a JSON or YAML contract path inside the repository.",
            status_code=400,
        )
    return normalized


def _serialize(value) -> dict[str, object]:
    result = asdict(value)
    for key, item in tuple(result.items()):
        if hasattr(item, "value"):
            result[key] = item.value
        elif isinstance(item, datetime):
            result[key] = item.isoformat()
        elif isinstance(item, tuple):
            result[key] = list(item)
    return result
