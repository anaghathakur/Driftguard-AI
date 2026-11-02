"""DriftGuard AI FastAPI application factory."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.app.api.routes.analyses import (
    router as analyses_router,
)
from apps.api.app.api.routes.auth import router as auth_router
from apps.api.app.api.routes.automation import router as automation_router
from apps.api.app.api.routes.contracts import router as contracts_router
from apps.api.app.api.routes.github_webhooks import router as github_webhooks_router
from apps.api.app.api.routes.health import (
    router as health_router,
)
from apps.api.app.api.routes.impact import (
    router as impact_router,
)
from apps.api.app.api.routes.migration import (
    router as migration_router,
)
from apps.api.app.api.routes.monitors import (
    router as monitors_router,
)
from apps.api.app.api.routes.patches import (
    router as patches_router,
)
from apps.api.app.api.routes.pull_requests import router as pull_requests_router
from apps.api.app.api.routes.repositories import router as repositories_router
from apps.api.app.api.routes.risk import (
    router as risk_router,
)
from apps.api.app.api.routes.specifications import (
    router as specifications_router,
)
from apps.api.app.api.routes.validations import router as validations_router
from apps.api.app.auth.middleware import WorkspaceContextMiddleware
from apps.api.app.core.config import settings, validate_security_settings
from apps.api.app.core.dependencies import (
    get_auth_service,
    get_automation_repository,
    get_automation_worker,
    get_default_analysis_repository,
    get_default_monitor_repository,
    get_monitor_scheduler,
    get_rate_limiter,
    get_workspace_repository,
)
from apps.api.app.core.exceptions import (
    register_exception_handlers,
)
from apps.api.app.core.rate_limit import DistributedRateLimitMiddleware
from apps.api.app.core.security_headers import SecurityHeadersMiddleware

logger = logging.getLogger("driftguard.lifecycle")

OPENAPI_TAGS = [
    {"name": "operations", "description": "Process health and configuration readiness."},
    {"name": "authentication", "description": "GitHub identity and workspace sessions."},
    {"name": "GitHub repositories", "description": "Authorized GitHub App repositories."},
    {"name": "specifications", "description": "OpenAPI contract comparison."},
    {"name": "contracts", "description": "OpenAPI and GraphQL contract comparison."},
    {"name": "impact", "description": "Repository-aware change-impact analysis."},
    {"name": "analyses", "description": "Persisted analyses, insights, and reports."},
    {"name": "risk", "description": "Risk-model provenance and status."},
    {"name": "migration", "description": "Migration-provider status."},
    {"name": "monitors", "description": "API contract monitoring and managed job execution."},
    {"name": "patches", "description": "Review-only proposed code patches."},
    {"name": "patch validations", "description": "Static validation and test intelligence."},
    {"name": "pull requests", "description": "Explicit, validated GitHub PR workflow."},
]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_default_analysis_repository()
    get_default_monitor_repository()
    get_workspace_repository().initialize()
    get_automation_repository().initialize()
    automation_worker = get_automation_worker()
    scheduler = get_monitor_scheduler()
    logger.info(
        "DriftGuard starting storage=%s scheduler=%s github_write_provider=%s",
        settings.storage_backend,
        "enabled" if scheduler.enabled else "disabled",
        settings.github_write_provider,
    )
    scheduler.start()
    automation_worker.start()
    try:
        yield
    finally:
        await automation_worker.stop()
        await scheduler.stop()
        logger.info("DriftGuard stopped cleanly")


def create_app() -> FastAPI:
    validate_security_settings(settings)
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "Detect OpenAPI and GraphQL contract drift, trace repository impact, generate and "
            "statically validate review-only migration patches and human-review Pull Requests."
        ),
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
    )

    register_exception_handlers(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_allowed_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(
        SecurityHeadersMiddleware,
        production=settings.deployment_environment == "production",
    )
    app.add_middleware(
        DistributedRateLimitMiddleware,
        limiter=get_rate_limiter(),
    )

    app.add_middleware(
        WorkspaceContextMiddleware,
        settings=settings,
        auth_service=get_auth_service(),
    )

    app.include_router(health_router)
    app.include_router(
        health_router,
        prefix=settings.api_prefix,
    )
    app.include_router(
        specifications_router,
        prefix=settings.api_prefix,
    )
    app.include_router(
        contracts_router,
        prefix=settings.api_prefix,
    )
    app.include_router(
        auth_router,
        prefix=settings.api_prefix,
    )
    app.include_router(
        repositories_router,
        prefix=settings.api_prefix,
    )
    app.include_router(
        github_webhooks_router,
        prefix=settings.api_prefix,
    )
    app.include_router(
        automation_router,
        prefix=settings.api_prefix,
    )
    app.include_router(
        impact_router,
        prefix=settings.api_prefix,
    )
    app.include_router(
        analyses_router,
        prefix=settings.api_prefix,
    )
    app.include_router(
        risk_router,
        prefix=settings.api_prefix,
    )
    app.include_router(
        migration_router,
        prefix=settings.api_prefix,
    )
    app.include_router(
        monitors_router,
        prefix=settings.api_prefix,
    )
    app.include_router(
        patches_router,
        prefix=settings.api_prefix,
    )
    app.include_router(
        validations_router,
        prefix=settings.api_prefix,
    )
    app.include_router(
        pull_requests_router,
        prefix=settings.api_prefix,
    )

    return app


app = create_app()
