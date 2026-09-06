"""OpenAPI specification endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile

from apps.api.app.auth.authorization import Permission, requires
from apps.api.app.core.config import settings
from apps.api.app.core.dependencies import get_analysis_pipeline_service
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.openapi.parser import SUPPORTED_EXTENSIONS
from apps.api.app.schemas.comparison import ComparisonResponse
from apps.api.app.services.analysis_pipeline import AnalysisPipelineService

router = APIRouter(
    prefix="/specifications",
    tags=["specifications"],
    dependencies=[Depends(requires(Permission.RUN_ANALYSES))],
)


async def _read_limited(upload: UploadFile) -> bytes:
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


def _validate_openapi_filename(upload: UploadFile) -> None:
    filename = upload.filename or ""
    if Path(filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise DriftGuardError(
            code="unsupported_specification_format",
            message="OpenAPI files must use a .json, .yaml, or .yml extension.",
            details={"filename": Path(filename).name},
        )


@router.post("/compare", response_model=ComparisonResponse)
async def compare_specifications(
    old_spec: Annotated[UploadFile, File()],
    new_spec: Annotated[UploadFile, File()],
    service: Annotated[AnalysisPipelineService, Depends(get_analysis_pipeline_service)],
) -> ComparisonResponse:
    _validate_openapi_filename(old_spec)
    _validate_openapi_filename(new_spec)
    old_content = await _read_limited(old_spec)
    new_content = await _read_limited(new_spec)
    return service.compare(
        old_filename=old_spec.filename or "",
        old_content=old_content,
        new_filename=new_spec.filename or "",
        new_content=new_content,
        contract_type="openapi",
    )
