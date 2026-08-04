"""FastAPI dependency providers for application services and adapters."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from apps.api.app.core.config import settings
from apps.api.app.infrastructure.sqlite_analysis_repository import (
    SQLiteAnalysisRepository,
)
from apps.api.app.ports.analysis_repository import AnalysisRepository
from apps.api.app.services.analysis_pipeline import AnalysisPipelineService


@lru_cache
def get_default_analysis_repository() -> SQLiteAnalysisRepository:
    repository = SQLiteAnalysisRepository(settings.database_path)
    repository.initialize()
    return repository


def get_analysis_repository() -> AnalysisRepository:
    return get_default_analysis_repository()


def get_analysis_pipeline_service(
    repository: Annotated[AnalysisRepository, Depends(get_analysis_repository)],
) -> AnalysisPipelineService:
    return AnalysisPipelineService(repository)
