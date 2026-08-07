"""Persisted analysis history endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    Query,
    Response,
    status,
)

from apps.api.app.core.dependencies import (
    get_analysis_pipeline_service,
)
from apps.api.app.reports.pdf_report import build_analysis_pdf
from apps.api.app.schemas.analysis import (
    AnalysisDetail,
    AnalysisListItem,
    PersistedMatchResponse,
    PipelineStageResponse,
)
from apps.api.app.schemas.comparison import ApiChange
from apps.api.app.schemas.migration import (
    MigrationRecommendation,
)
from apps.api.app.schemas.report import AnalysisReport
from apps.api.app.schemas.risk import RiskPrediction
from apps.api.app.services.analysis_pipeline import (
    AnalysisPipelineService,
)
from apps.api.app.services.report_service import (
    build_analysis_report,
)

router = APIRouter(
    prefix="/analyses",
    tags=["analyses"],
)

AnalysisService = Annotated[
    AnalysisPipelineService,
    Depends(get_analysis_pipeline_service),
]


@router.get(
    "",
    response_model=list[AnalysisListItem],
)
def list_analyses(
    service: AnalysisService,
    limit: Annotated[
        int,
        Query(ge=1, le=100),
    ] = 50,
    offset: Annotated[
        int,
        Query(ge=0),
    ] = 0,
) -> list[AnalysisListItem]:
    return service.list_analyses(
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{analysis_id}",
    response_model=AnalysisDetail,
)
def get_analysis(
    analysis_id: str,
    service: AnalysisService,
) -> AnalysisDetail:
    return service.get_analysis(analysis_id)


@router.get(
    "/{analysis_id}/changes",
    response_model=list[ApiChange],
)
def get_analysis_changes(
    analysis_id: str,
    service: AnalysisService,
) -> list[ApiChange]:
    return service.get_changes(analysis_id)


@router.get(
    "/{analysis_id}/matches",
    response_model=list[PersistedMatchResponse],
)
def get_analysis_matches(
    analysis_id: str,
    service: AnalysisService,
) -> list[PersistedMatchResponse]:
    return service.get_matches(analysis_id)


@router.get(
    "/{analysis_id}/pipeline",
    response_model=list[PipelineStageResponse],
)
def get_analysis_pipeline(
    analysis_id: str,
    service: AnalysisService,
) -> list[PipelineStageResponse]:
    return service.get_pipeline(analysis_id)


@router.get(
    "/{analysis_id}/risks",
    response_model=list[RiskPrediction],
)
def get_analysis_risks(
    analysis_id: str,
    service: AnalysisService,
) -> list[RiskPrediction]:
    return service.get_risk_predictions(analysis_id)


@router.get(
    "/{analysis_id}/risks/{change_id}",
    response_model=RiskPrediction,
)
def get_analysis_risk(
    analysis_id: str,
    change_id: str,
    service: AnalysisService,
) -> RiskPrediction:
    return service.get_risk_prediction(
        analysis_id,
        change_id,
    )


@router.get(
    "/{analysis_id}/migrations",
    response_model=list[MigrationRecommendation],
)
def get_analysis_migrations(
    analysis_id: str,
    service: AnalysisService,
) -> list[MigrationRecommendation]:
    return service.get_migration_recommendations(
        analysis_id
    )


@router.get(
    "/{analysis_id}/migrations/{change_id}",
    response_model=MigrationRecommendation,
)
def get_analysis_migration(
    analysis_id: str,
    change_id: str,
    service: AnalysisService,
) -> MigrationRecommendation:
    return service.get_migration_recommendation(
        analysis_id,
        change_id,
    )


@router.get(
    "/{analysis_id}/report",
    response_model=AnalysisReport,
)
def get_analysis_report(
    analysis_id: str,
    service: AnalysisService,
) -> AnalysisReport:
    return build_analysis_report(
        service,
        analysis_id,
    )


@router.get(
    "/{analysis_id}/report.pdf",
)
def get_analysis_pdf_report(
    analysis_id: str,
    service: AnalysisService,
) -> Response:
    report = build_analysis_report(
        service,
        analysis_id,
    )
    pdf_bytes = build_analysis_pdf(report)
    filename = f"driftguard-analysis-{analysis_id}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{filename}"'
            )
        },
    )


@router.delete(
    "/{analysis_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_analysis(
    analysis_id: str,
    service: AnalysisService,
) -> Response:
    service.delete(analysis_id)

    return Response(
        status_code=status.HTTP_204_NO_CONTENT
    )