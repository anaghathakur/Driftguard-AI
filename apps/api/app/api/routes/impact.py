"""Repository-aware API impact endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile

from apps.api.app.core.config import settings
from apps.api.app.core.dependencies import get_analysis_pipeline_service
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.schemas.impact import ImpactAnalysisResponse
from apps.api.app.services.analysis_pipeline import AnalysisPipelineService

router = APIRouter(prefix="/impact", tags=["impact"])


async def _read_repository(upload: UploadFile) -> bytes:
    content = await upload.read(settings.max_repository_archive_bytes + 1)
    await upload.close()
    if len(content) > settings.max_repository_archive_bytes:
        raise DriftGuardError(
            code="repository_archive_too_large",
            message="The uploaded repository ZIP exceeds the configured size limit.",
            status_code=413,
            details={"max_bytes": settings.max_repository_archive_bytes},
        )
    return content


async def _read_specification(upload: UploadFile) -> bytes:
    content = await upload.read(settings.max_spec_file_bytes + 1)
    await upload.close()
    if len(content) > settings.max_spec_file_bytes:
        raise DriftGuardError(
            code="specification_too_large",
            message="The uploaded OpenAPI file exceeds the configured size limit.",
            status_code=413,
            details={"max_bytes": settings.max_spec_file_bytes},
        )
    return content


@router.post("/analyze", response_model=ImpactAnalysisResponse)
async def analyze_impact(
    old_spec: Annotated[UploadFile, File()],
    new_spec: Annotated[UploadFile, File()],
    repository: Annotated[UploadFile, File()],
    service: Annotated[AnalysisPipelineService, Depends(get_analysis_pipeline_service)],
) -> ImpactAnalysisResponse:
    old_content = await _read_specification(old_spec)
    new_content = await _read_specification(new_spec)
    repository_content = await _read_repository(repository)
    return service.analyze_impact(
        old_filename=old_spec.filename or "",
        old_content=old_content,
        new_filename=new_spec.filename or "",
        new_content=new_content,
        repository_filename=repository.filename or "",
        repository_content=repository_content,
    )
