"""FastAPI dependency providers for application services and adapters."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from apps.api.app.core.config import settings
from apps.api.app.infrastructure.firestore_analysis_repository import (
    FirestoreAnalysisRepository,
)
from apps.api.app.infrastructure.firestore_monitor_repository import (
    FirestoreMonitorRepository,
)
from apps.api.app.infrastructure.sqlite_analysis_repository import (
    SQLiteAnalysisRepository,
)
from apps.api.app.infrastructure.sqlite_monitor_repository import (
    SQLiteMonitorRepository,
)
from apps.api.app.migration.provider import (
    GeminiMigrationRecommendationProvider,
    MigrationRecommendationProvider,
    MockMigrationRecommendationProvider,
    _send_json,
)
from apps.api.app.migration.service import (
    MigrationRecommendationService,
)
from apps.api.app.monitoring.scheduler import MonitorScheduler
from apps.api.app.monitoring.service import ApiMonitorService, MonitorCheckService
from apps.api.app.monitoring.specification_source import OpenApiSpecificationSource
from apps.api.app.patches.provider import (
    GeminiPatchGenerationProvider,
    MockPatchGenerationProvider,
    PatchGenerationProvider,
)
from apps.api.app.patches.service import PatchProposalService
from apps.api.app.ports.analysis_repository import (
    AnalysisRepository,
)
from apps.api.app.ports.monitor_repository import ApiMonitorRepository
from apps.api.app.repository.github_source import (
    GitHubRepositorySource,
)
from apps.api.app.risk.classifier import RiskClassifier
from apps.api.app.services.analysis_pipeline import (
    AnalysisPipelineService,
)
from apps.api.app.validation.provider import (
    GeminiTestPlanProvider,
    MockTestPlanProvider,
    TestPlanProvider,
)
from apps.api.app.validation.service import PatchValidationService


@lru_cache
def get_default_analysis_repository() -> AnalysisRepository:
    if settings.storage_backend == "sqlite":
        repository: AnalysisRepository = SQLiteAnalysisRepository(
            settings.database_path
        )
        repository.initialize()
        return repository

    if settings.storage_backend == "firestore":
        repository = FirestoreAnalysisRepository(
            project_id=settings.firestore_project_id or None,
            database_id=settings.firestore_database_id,
        )
        repository.initialize()
        return repository

    raise RuntimeError(
        "DRIFTGUARD_STORAGE_BACKEND must be either "
        "'sqlite' or 'firestore'"
    )


def get_analysis_repository() -> AnalysisRepository:
    return get_default_analysis_repository()


@lru_cache
def get_default_monitor_repository() -> ApiMonitorRepository:
    if settings.storage_backend == "sqlite":
        repository: ApiMonitorRepository = SQLiteMonitorRepository(
            settings.database_path
        )
        repository.initialize()
        return repository
    if settings.storage_backend == "firestore":
        repository = FirestoreMonitorRepository(
            project_id=settings.firestore_project_id or None,
            database_id=settings.firestore_database_id,
        )
        repository.initialize()
        return repository
    raise RuntimeError(
        "DRIFTGUARD_STORAGE_BACKEND must be either "
        "'sqlite' or 'firestore'"
    )


def get_monitor_repository() -> ApiMonitorRepository:
    return get_default_monitor_repository()


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


def get_github_repository_source() -> GitHubRepositorySource:
    return GitHubRepositorySource()


@lru_cache
def get_patch_provider() -> PatchGenerationProvider:
    if settings.ai_provider == "gemini":
        return GeminiPatchGenerationProvider(
            api_key=settings.gemini_api_key,
            model_name=settings.gemini_model,
            timeout_seconds=settings.ai_timeout_seconds,
            max_retries=settings.ai_max_retries,
            sender=_send_json,
        )
    return MockPatchGenerationProvider()


def get_patch_proposal_service(
    repository: Annotated[AnalysisRepository, Depends(get_analysis_repository)],
    provider: Annotated[PatchGenerationProvider, Depends(get_patch_provider)],
    github_source: Annotated[
        GitHubRepositorySource,
        Depends(get_github_repository_source),
    ],
) -> PatchProposalService:
    return PatchProposalService(repository, provider, github_source)


@lru_cache
def get_test_plan_provider() -> TestPlanProvider:
    if settings.test_plan_provider == "gemini":
        return GeminiTestPlanProvider(
            api_key=settings.gemini_api_key,
            model_name=settings.gemini_model,
            timeout_seconds=settings.ai_timeout_seconds,
            max_retries=settings.ai_max_retries,
            sender=_send_json,
        )
    if settings.test_plan_provider == "mock":
        return MockTestPlanProvider()
    raise RuntimeError("DRIFTGUARD_TEST_PLAN_PROVIDER must be either 'mock' or 'gemini'")


def get_patch_validation_service(
    repository: Annotated[AnalysisRepository, Depends(get_analysis_repository)],
    provider: Annotated[TestPlanProvider, Depends(get_test_plan_provider)],
    github_source: Annotated[
        GitHubRepositorySource, Depends(get_github_repository_source)
    ],
) -> PatchValidationService:
    return PatchValidationService(repository, provider, github_source)


def get_openapi_specification_source() -> OpenApiSpecificationSource:
    return OpenApiSpecificationSource()


def get_api_monitor_service(
    repository: Annotated[ApiMonitorRepository, Depends(get_monitor_repository)],
    specification_source: Annotated[
        OpenApiSpecificationSource,
        Depends(get_openapi_specification_source),
    ],
) -> ApiMonitorService:
    return ApiMonitorService(repository, specification_source)


def get_monitor_check_service(
    repository: Annotated[ApiMonitorRepository, Depends(get_monitor_repository)],
    specification_source: Annotated[
        OpenApiSpecificationSource,
        Depends(get_openapi_specification_source),
    ],
    github_source: Annotated[
        GitHubRepositorySource,
        Depends(get_github_repository_source),
    ],
    analysis_pipeline: Annotated[
        AnalysisPipelineService,
        Depends(get_analysis_pipeline_service),
    ],
) -> MonitorCheckService:
    return MonitorCheckService(
        repository,
        specification_source,
        github_source,
        analysis_pipeline,
    )


@lru_cache
def get_default_monitor_check_service() -> MonitorCheckService:
    return MonitorCheckService(
        get_default_monitor_repository(),
        OpenApiSpecificationSource(),
        GitHubRepositorySource(),
        AnalysisPipelineService(
            get_default_analysis_repository(),
            get_risk_classifier(),
            get_migration_recommendation_service(),
        ),
    )


@lru_cache
def get_monitor_scheduler() -> MonitorScheduler:
    return MonitorScheduler(
        get_default_monitor_repository(),
        get_default_monitor_check_service(),
        enabled=settings.monitor_scheduler_enabled,
        poll_seconds=settings.monitor_poll_seconds,
    )
