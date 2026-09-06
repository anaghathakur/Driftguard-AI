"""FastAPI dependency providers for application services and adapters."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from apps.api.app.auth.provider import (
    GitHubOAuthProvider,
    MockGitHubOAuthProvider,
    RealGitHubOAuthProvider,
)
from apps.api.app.auth.service import AuthService
from apps.api.app.core.config import settings
from apps.api.app.github.automation_provider import (
    GitHubAutomationProvider,
    MockGitHubAutomationProvider,
    RealGitHubAutomationProvider,
)
from apps.api.app.github.consumer_automation import ConsumerAutomationDispatcher
from apps.api.app.github.contracts import ContractDiscoveryService
from apps.api.app.github.installations import (
    GitHubInstallationProvider,
    MockGitHubInstallationProvider,
    RealGitHubInstallationProvider,
)
from apps.api.app.github.service import GitHubOnboardingService
from apps.api.app.github.source import ConnectedAwareGitHubRepositorySource
from apps.api.app.github.webhooks import GitHubWebhookService
from apps.api.app.github.worker import AutomationWorker
from apps.api.app.github.write_guard import WorkspaceAuthorizedGitHubWriteProvider
from apps.api.app.infrastructure.firestore_analysis_repository import (
    FirestoreAnalysisRepository,
)
from apps.api.app.infrastructure.firestore_monitor_repository import (
    FirestoreMonitorRepository,
)
from apps.api.app.infrastructure.sqlite_analysis_repository import (
    SQLiteAnalysisRepository,
)
from apps.api.app.infrastructure.sqlite_automation_repository import (
    SQLiteAutomationRepository,
)
from apps.api.app.infrastructure.sqlite_monitor_repository import (
    SQLiteMonitorRepository,
)
from apps.api.app.infrastructure.sqlite_workspace_repository import (
    SQLiteWorkspaceRepository,
)
from apps.api.app.migration.provider import (
    DeterministicMigrationRecommendationProvider,
    GeminiMigrationRecommendationProvider,
    MigrationRecommendationProvider,
    MockMigrationRecommendationProvider,
    _send_json,
)
from apps.api.app.migration.service import (
    MigrationRecommendationService,
)
from apps.api.app.monitoring.scheduler import MonitorScheduler
from apps.api.app.monitoring.service import (
    ApiMonitorService,
    MonitorCheckService,
)
from apps.api.app.monitoring.specification_source import (
    OpenApiSpecificationSource,
)
from apps.api.app.patches.provider import (
    DeterministicPatchGenerationProvider,
    GeminiPatchGenerationProvider,
    MockPatchGenerationProvider,
    PatchGenerationProvider,
)
from apps.api.app.patches.service import PatchProposalService
from apps.api.app.ports.analysis_repository import (
    AnalysisRepository,
)
from apps.api.app.ports.automation_repository import AutomationRepository
from apps.api.app.ports.monitor_repository import ApiMonitorRepository
from apps.api.app.ports.workspace_repository import WorkspaceRepository
from apps.api.app.pull_requests.provider import (
    GitHubAppWriteProvider,
    GitHubWriteProvider,
    MockGitHubWriteProvider,
)
from apps.api.app.pull_requests.service import PullRequestWorkflowService
from apps.api.app.repository.github_source import (
    GitHubRepositorySource,
)
from apps.api.app.risk.classifier import RiskClassifier
from apps.api.app.services.analysis_pipeline import (
    AnalysisPipelineService,
)
from apps.api.app.validation.provider import (
    DeterministicTestPlanProvider,
    GeminiTestPlanProvider,
    MockTestPlanProvider,
    TestPlanProvider,
)
from apps.api.app.validation.service import PatchValidationService


@lru_cache
def get_workspace_repository() -> WorkspaceRepository:
    if settings.storage_backend == "sqlite":
        repository: WorkspaceRepository = SQLiteWorkspaceRepository(settings.database_path)
        repository.initialize()
        return repository
    from apps.api.app.infrastructure.firestore_workspace_repository import (
        FirestoreWorkspaceRepository,
    )

    repository = FirestoreWorkspaceRepository(
        project_id=settings.firestore_project_id or None,
        database_id=settings.firestore_database_id,
    )
    repository.initialize()
    return repository


@lru_cache
def get_github_oauth_provider() -> GitHubOAuthProvider:
    if settings.github_oauth_provider == "mock":
        return MockGitHubOAuthProvider()
    if settings.github_oauth_provider == "github":
        return RealGitHubOAuthProvider(
            settings.github_oauth_client_id,
            settings.github_oauth_client_secret,
            settings.github_timeout_seconds,
        )
    raise RuntimeError("DRIFTGUARD_GITHUB_OAUTH_PROVIDER must be 'github' or 'mock'")


@lru_cache
def get_auth_service() -> AuthService:
    return AuthService(
        get_workspace_repository(),
        get_github_oauth_provider(),
        callback_url=settings.github_oauth_callback_url,
        frontend_url=settings.frontend_url,
        session_ttl_hours=settings.session_ttl_hours,
        session_secret=settings.session_secret or "local-development-only",
    )


@lru_cache
def get_github_installation_provider() -> GitHubInstallationProvider:
    if settings.github_write_provider == "mock":
        return MockGitHubInstallationProvider()
    if settings.github_write_provider == "github_app":
        return RealGitHubInstallationProvider(
            settings.github_app_id,
            settings.github_app_private_key_path,
            settings.github_timeout_seconds,
        )
    raise RuntimeError("A supported GitHub App provider is required")


def get_github_onboarding_service() -> GitHubOnboardingService:
    return GitHubOnboardingService(
        get_workspace_repository(),
        get_github_installation_provider(),
        get_auth_service(),
    )


@lru_cache
def get_automation_repository() -> AutomationRepository:
    repository: AutomationRepository = SQLiteAutomationRepository(settings.database_path)
    repository.initialize()
    return repository


def get_github_webhook_service() -> GitHubWebhookService:
    return GitHubWebhookService(
        get_automation_repository(),
        get_workspace_repository(),
        secret=settings.github_webhook_secret,
    )


@lru_cache
def get_github_automation_provider() -> GitHubAutomationProvider:
    if settings.github_check_provider == "mock":
        return MockGitHubAutomationProvider()
    if settings.github_check_provider == "github_app":
        return RealGitHubAutomationProvider(
            settings.github_app_id,
            settings.github_app_private_key_path,
            settings.github_timeout_seconds,
        )
    raise RuntimeError("DRIFTGUARD_GITHUB_CHECK_PROVIDER must be either 'mock' or 'github_app'")


@lru_cache
def get_contract_discovery_service() -> ContractDiscoveryService:
    return ContractDiscoveryService(get_automation_repository(), get_github_automation_provider())


@lru_cache
def get_automation_worker() -> AutomationWorker:
    return AutomationWorker(
        get_automation_repository(),
        get_workspace_repository(),
        get_github_onboarding_service(),
        get_github_automation_provider(),
        get_contract_discovery_service(),
        AnalysisPipelineService(
            get_default_analysis_repository(),
            get_risk_classifier(),
            get_migration_recommendation_service(),
        ),
        frontend_url=settings.frontend_url,
        enabled=settings.automation_worker_enabled,
        poll_seconds=settings.automation_worker_poll_seconds,
        max_retries=settings.automation_max_retries,
        retry_base_seconds=settings.automation_retry_base_seconds,
    )


@lru_cache
def get_default_analysis_repository() -> AnalysisRepository:
    if settings.storage_backend == "sqlite":
        repository: AnalysisRepository = SQLiteAnalysisRepository(settings.database_path)
        repository.initialize()
        return repository

    if settings.storage_backend == "firestore":
        repository = FirestoreAnalysisRepository(
            project_id=settings.firestore_project_id or None,
            database_id=settings.firestore_database_id,
        )
        repository.initialize()
        return repository

    raise RuntimeError("DRIFTGUARD_STORAGE_BACKEND must be either 'sqlite' or 'firestore'")


def get_analysis_repository() -> AnalysisRepository:
    return get_default_analysis_repository()


@lru_cache
def get_default_monitor_repository() -> ApiMonitorRepository:
    if settings.storage_backend == "sqlite":
        repository: ApiMonitorRepository = SQLiteMonitorRepository(settings.database_path)
        repository.initialize()
        return repository
    if settings.storage_backend == "firestore":
        repository = FirestoreMonitorRepository(
            project_id=settings.firestore_project_id or None,
            database_id=settings.firestore_database_id,
        )
        repository.initialize()
        return repository
    raise RuntimeError("DRIFTGUARD_STORAGE_BACKEND must be either 'sqlite' or 'firestore'")


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
    if settings.migration_provider == "gemini":
        return GeminiMigrationRecommendationProvider(
            api_key=settings.gemini_api_key,
            model_name=settings.gemini_model,
            timeout_seconds=settings.ai_timeout_seconds,
            max_retries=settings.ai_max_retries,
        )

    if settings.migration_provider == "deterministic":
        return DeterministicMigrationRecommendationProvider()

    if settings.migration_provider == "mock":
        return MockMigrationRecommendationProvider()

    raise RuntimeError(
        "DRIFTGUARD_MIGRATION_PROVIDER must be 'deterministic', 'gemini', or 'mock'"
    )


@lru_cache
def get_migration_recommendation_service() -> MigrationRecommendationService:
    return MigrationRecommendationService(
        get_migration_provider(),
        prompt_version=settings.ai_prompt_version,
        schema_version=settings.ai_schema_version,
        allow_deterministic_fallback=settings.deployment_environment != "production",
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
        Depends(get_migration_recommendation_service),
    ],
) -> AnalysisPipelineService:
    return AnalysisPipelineService(
        repository,
        risk_classifier,
        migration_service,
    )


def get_github_repository_source() -> GitHubRepositorySource:
    return ConnectedAwareGitHubRepositorySource(
        get_workspace_repository(),
        get_github_installation_provider(),
    )


@lru_cache
def get_patch_provider() -> PatchGenerationProvider:
    if settings.patch_provider == "gemini":
        return GeminiPatchGenerationProvider(
            api_key=settings.gemini_api_key,
            model_name=settings.gemini_model,
            timeout_seconds=settings.ai_timeout_seconds,
            max_retries=settings.ai_max_retries,
            sender=_send_json,
        )
    if settings.patch_provider == "deterministic":
        return DeterministicPatchGenerationProvider()
    if settings.patch_provider == "mock":
        return MockPatchGenerationProvider()
    raise RuntimeError(
        "DRIFTGUARD_PATCH_PROVIDER must be 'deterministic', 'gemini', or 'mock'"
    )


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
    if settings.test_plan_provider == "deterministic":
        return DeterministicTestPlanProvider()
    if settings.test_plan_provider == "mock":
        return MockTestPlanProvider()
    raise RuntimeError(
        "DRIFTGUARD_TEST_PLAN_PROVIDER must be 'deterministic', 'gemini', or 'mock'"
    )


def get_patch_validation_service(
    repository: Annotated[AnalysisRepository, Depends(get_analysis_repository)],
    provider: Annotated[TestPlanProvider, Depends(get_test_plan_provider)],
    github_source: Annotated[GitHubRepositorySource, Depends(get_github_repository_source)],
) -> PatchValidationService:
    return PatchValidationService(repository, provider, github_source)


@lru_cache
def get_github_write_provider() -> GitHubWriteProvider:
    if settings.github_write_provider == "mock":
        delegate: GitHubWriteProvider = MockGitHubWriteProvider()
    elif settings.github_write_provider == "github_app":
        delegate = GitHubAppWriteProvider(
            app_id=settings.github_app_id,
            private_key_path=settings.github_app_private_key_path,
            timeout_seconds=settings.github_timeout_seconds,
        )
    else:
        raise RuntimeError("DRIFTGUARD_GITHUB_WRITE_PROVIDER must be either 'mock' or 'github_app'")
    return WorkspaceAuthorizedGitHubWriteProvider(delegate, get_workspace_repository())


def get_pull_request_workflow_service(
    repository: Annotated[AnalysisRepository, Depends(get_analysis_repository)],
    provider: Annotated[GitHubWriteProvider, Depends(get_github_write_provider)],
    github_source: Annotated[GitHubRepositorySource, Depends(get_github_repository_source)],
) -> PullRequestWorkflowService:
    return PullRequestWorkflowService(repository, provider, github_source)


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
        consumer_dispatcher=ConsumerAutomationDispatcher(
            get_automation_repository(), get_workspace_repository()
        ).dispatch,
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
        consumer_dispatcher=ConsumerAutomationDispatcher(
            get_automation_repository(), get_workspace_repository()
        ).dispatch,
    )


@lru_cache
def get_monitor_scheduler() -> MonitorScheduler:
    return MonitorScheduler(
        get_default_monitor_repository(),
        get_default_monitor_check_service(),
        enabled=settings.monitor_scheduler_enabled,
        poll_seconds=settings.monitor_poll_seconds,
    )
