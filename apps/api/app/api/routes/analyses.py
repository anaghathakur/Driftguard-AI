"""Persisted analysis history endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from apps.api.app.core.dependencies import get_analysis_pipeline_service
from apps.api.app.schemas.analysis import (
    AnalysisDetail,
    AnalysisListItem,
    PersistedMatchResponse,
    PipelineStageResponse,
)
from apps.api.app.schemas.comparison import ApiChange
from apps.api.app.services.analysis_pipeline import AnalysisPipelineService

router = APIRouter(prefix="/analyses", tags=["analyses"])
AnalysisService = Annotated[
    AnalysisPipelineService, Depends(get_analysis_pipeline_service)
]


@router.get("", response_model=list[AnalysisListItem])
def list_analyses(
    service: AnalysisService,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AnalysisListItem]:
    return service.list_analyses(limit=limit, offset=offset)


@router.get("/{analysis_id}", response_model=AnalysisDetail)
def get_analysis(analysis_id: str, service: AnalysisService) -> AnalysisDetail:
    return service.get_analysis(analysis_id)


@router.get("/{analysis_id}/changes", response_model=list[ApiChange])
def get_analysis_changes(
    analysis_id: str, service: AnalysisService
) -> list[ApiChange]:
    return service.get_changes(analysis_id)


@router.get("/{analysis_id}/matches", response_model=list[PersistedMatchResponse])
def get_analysis_matches(
    analysis_id: str, service: AnalysisService
) -> list[PersistedMatchResponse]:
    return service.get_matches(analysis_id)


@router.get("/{analysis_id}/pipeline", response_model=list[PipelineStageResponse])
def get_analysis_pipeline(
    analysis_id: str, service: AnalysisService
) -> list[PipelineStageResponse]:
    return service.get_pipeline(analysis_id)


@router.delete("/{analysis_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_analysis(analysis_id: str, service: AnalysisService) -> Response:
    service.delete(analysis_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
