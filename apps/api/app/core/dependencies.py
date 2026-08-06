"""FastAPI dependency providers for application services and adapters."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from apps.api.app.core.config import settings
from apps.api.app.infrastructure.sqlite_analysis_repository import (
    SQLiteAnalysisRepository,
)
from apps.api.app.migration.provider import (
    GeminiMigrationRecommendationProvider,
    MigrationRecommendationProvider,
    MockMigrationRecommendationProvider,
)
from apps.api.app.migration.service import (
    MigrationRecommendationService,
)
from apps.api.app.ports.analysis_repository import (
    AnalysisRepository,
)
from apps.api.app.risk.classifier import RiskClassifier
from apps.api.app.services.analysis_pipeline import (
    AnalysisPipelineService,
)


@lru_cache
def get_default_analysis_repository() -> SQLiteAnalysisRepository:
    repository = SQLiteAnalysisRepository(
        settings.database_path
    )
    repository.initialize()

    return repository


def get_analysis_repository() -> AnalysisRepository:
    return get_default_analysis_repository()


@lru_cache
def get_risk_classifier() -> RiskClassifier:
    return RiskClassifier(
        settings.risk_model_path,
        settings.risk_model_metadata_path,
    )


@lru_cache
def get_migration_provider() -> MigrationRecommendationProvider:
    if settings.ai_provider == "gemini":
        return GeminiMigrationRecommendationProvider(
            api_key=settings.gemini_api_key,
            model_name=settings.gemini_model,
            timeout_seconds=settings.ai_timeout_seconds,
            max_retries=settings.ai_max_retries,
        )

    if settings.ai_provider == "mock":
        return MockMigrationRecommendationProvider()

    raise RuntimeError(
        
            "DRIFTGUARD_AI_PROVIDER must be either "
            "'mock' or 'gemini'"
        
    )


@lru_cache
def get_migration_recommendation_service() -> (
    MigrationRecommendationService
):
    return MigrationRecommendationService(
        get_migration_provider(),
        prompt_version=settings.ai_prompt_version,
        schema_version=settings.ai_schema_version,
    )


def get_analysis_pipeline_service(
    repository: Annotated[
        AnalysisRepository,
        Depends(get_analysis_repository),
    ],
    risk_classifier: Annotated[
        RiskClassifier,
        Depends(get_risk_classifier),
    ],
    migration_service: Annotated[
        MigrationRecommendationService,
        Depends(
            get_migration_recommendation_service
        ),
    ],
) -> AnalysisPipelineService:
    return AnalysisPipelineService(
        repository,
        risk_classifier,
        migration_service,
    )