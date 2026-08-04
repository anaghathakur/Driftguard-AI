"""OpenAPI specification endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, UploadFile

from apps.api.app.core.config import settings
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.schemas.comparison import ComparisonResponse
from apps.api.app.services.comparison import SpecificationComparisonService

router = APIRouter(prefix="/specifications", tags=["specifications"])


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


@router.post("/compare", response_model=ComparisonResponse)
async def compare_specifications(
    old_spec: Annotated[UploadFile, File()],
    new_spec: Annotated[UploadFile, File()],
) -> ComparisonResponse:
    old_content = await _read_limited(old_spec)
    new_content = await _read_limited(new_spec)
    return SpecificationComparisonService().compare(
        old_filename=old_spec.filename or "",
        old_content=old_content,
        new_filename=new_spec.filename or "",
        new_content=new_content,
    )
