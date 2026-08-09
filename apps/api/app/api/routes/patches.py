"""Analysis-scoped proposed patch endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile

from apps.api.app.core.config import settings
from apps.api.app.core.dependencies import get_patch_proposal_service
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.patches.service import PatchProposalService
from apps.api.app.schemas.patch import PatchProposal, PatchProposalListItem

router = APIRouter(prefix="/analyses", tags=["patches"])

PatchService = Annotated[
    PatchProposalService,
    Depends(get_patch_proposal_service),
]


@router.post("/{analysis_id}/patches", response_model=PatchProposal)
async def generate_patch_proposal(
    analysis_id: str,
    service: PatchService,
    repository: Annotated[UploadFile | None, File()] = None,
) -> PatchProposal:
    content: bytes | None = None
    filename: str | None = None
    if repository is not None:
        content = await repository.read(settings.max_repository_archive_bytes + 1)
        filename = repository.filename or "repository.zip"
        await repository.close()
        if len(content) > settings.max_repository_archive_bytes:
            raise DriftGuardError(
                code="repository_archive_too_large",
                message="The uploaded repository ZIP exceeds the configured size limit.",
                status_code=413,
                details={"max_bytes": settings.max_repository_archive_bytes},
            )
    return await service.generate(
        analysis_id,
        repository_content=content,
        repository_filename=filename,
    )


@router.get(
    "/{analysis_id}/patches",
    response_model=list[PatchProposalListItem],
)
def list_patch_proposals(
    analysis_id: str,
    service: PatchService,
) -> list[PatchProposalListItem]:
    return service.list(analysis_id)


@router.get(
    "/{analysis_id}/patches/{patch_id}",
    response_model=PatchProposal,
)
def get_patch_proposal(
    analysis_id: str,
    patch_id: str,
    service: PatchService,
) -> PatchProposal:
    return service.get(analysis_id, patch_id)
