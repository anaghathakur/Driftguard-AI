"""Analysis/patch-scoped static validation endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile

from apps.api.app.core.config import settings
from apps.api.app.core.dependencies import get_patch_validation_service
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.schemas.validation import PatchValidationListItem, PatchValidationRun
from apps.api.app.validation.service import PatchValidationService

router = APIRouter(prefix="/analyses", tags=["patch validations"])
ValidationService = Annotated[PatchValidationService, Depends(get_patch_validation_service)]


@router.post(
    "/{analysis_id}/patches/{patch_id}/validations",
    response_model=PatchValidationRun,
)
async def validate_patch(
    analysis_id: str,
    patch_id: str,
    service: ValidationService,
    repository: Annotated[UploadFile | None, File()] = None,
) -> PatchValidationRun:
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
    return await service.validate(
        analysis_id,
        patch_id,
        repository_content=content,
        repository_filename=filename,
    )


@router.get(
    "/{analysis_id}/patches/{patch_id}/validations",
    response_model=list[PatchValidationListItem],
)
def list_patch_validations(
    analysis_id: str, patch_id: str, service: ValidationService
) -> list[PatchValidationListItem]:
    return service.list(analysis_id, patch_id)


@router.get(
    "/{analysis_id}/patches/{patch_id}/validations/{validation_id}",
    response_model=PatchValidationRun,
)
def get_patch_validation(
    analysis_id: str, patch_id: str, validation_id: str, service: ValidationService
) -> PatchValidationRun:
    return service.get(analysis_id, patch_id, validation_id)
