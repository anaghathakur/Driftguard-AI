"""Protocol-neutral contract comparison endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile

from apps.api.app.auth.authorization import Permission, requires
from apps.api.app.core.config import settings
from apps.api.app.core.dependencies import get_analysis_pipeline_service
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.schemas.comparison import ComparisonResponse
from apps.api.app.services.analysis_pipeline import AnalysisPipelineService

router = APIRouter(
    prefix="/contracts",
    tags=["contracts"],
    dependencies=[Depends(requires(Permission.RUN_ANALYSES))],
)


async def _read_contract(upload: UploadFile) -> bytes:
    maximum = max(settings.max_spec_file_bytes, settings.max_graphql_document_bytes)
    content = await upload.read(maximum + 1)
    await upload.close()
    if len(content) > maximum:
        raise DriftGuardError(
            code="specification_too_large",
            message="The uploaded contract exceeds the configured size limit.",
            status_code=413,
            details={"max_bytes": maximum},
        )
    return content


@router.post("/compare", response_model=ComparisonResponse)
async def compare_contracts(
    old_contract: Annotated[UploadFile, File()],
    new_contract: Annotated[UploadFile, File()],
    service: Annotated[AnalysisPipelineService, Depends(get_analysis_pipeline_service)],
    contract_type: Annotated[str, Form()] = "auto",
) -> ComparisonResponse:
    old_content = await _read_contract(old_contract)
    new_content = await _read_contract(new_contract)
    return service.compare(
        old_filename=old_contract.filename or "",
        old_content=old_content,
        new_filename=new_contract.filename or "",
        new_content=new_content,
        contract_type=contract_type,
    )
