"""Explicit GitHub pull-request preview, creation, and history endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from apps.api.app.core.dependencies import get_pull_request_workflow_service
from apps.api.app.pull_requests.service import PullRequestWorkflowService
from apps.api.app.schemas.pull_request import (
    GitHubPullRequestRecord,
    PullRequestListItem,
    PullRequestPreview,
)

router = APIRouter(prefix="/analyses", tags=["pull requests"])
PullRequestService = Annotated[
    PullRequestWorkflowService, Depends(get_pull_request_workflow_service)
]


@router.get(
    "/{analysis_id}/patches/{patch_id}/validations/{validation_id}/pull-request/preview",
    response_model=PullRequestPreview,
)
async def preview_pull_request(
    analysis_id: str,
    patch_id: str,
    validation_id: str,
    service: PullRequestService,
) -> PullRequestPreview:
    return await service.preview(analysis_id, patch_id, validation_id)


@router.post(
    "/{analysis_id}/patches/{patch_id}/validations/{validation_id}/pull-request",
    response_model=GitHubPullRequestRecord,
)
async def create_pull_request(
    analysis_id: str,
    patch_id: str,
    validation_id: str,
    service: PullRequestService,
) -> GitHubPullRequestRecord:
    return await service.create(analysis_id, patch_id, validation_id)


@router.get(
    "/{analysis_id}/pull-requests",
    response_model=list[PullRequestListItem],
)
def list_pull_requests(analysis_id: str, service: PullRequestService) -> list[PullRequestListItem]:
    return service.list(analysis_id)


@router.get(
    "/{analysis_id}/pull-requests/{pr_record_id}",
    response_model=GitHubPullRequestRecord,
)
def get_pull_request(
    analysis_id: str, pr_record_id: str, service: PullRequestService
) -> GitHubPullRequestRecord:
    return service.get(analysis_id, pr_record_id)
