"""DriftGuard AI FastAPI application factory."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.app.api.routes.analyses import (
    router as analyses_router,
)
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
from apps.api.app.api.routes.risk import (
    router as risk_router,
)
from apps.api.app.api.routes.specifications import (
    router as specifications_router,
)
from apps.api.app.api.routes.validations import router as validations_router
from apps.api.app.core.config import settings
from apps.api.app.core.dependencies import (
    get_default_analysis_repository,
    get_default_monitor_repository,
    get_monitor_scheduler,
)
from apps.api.app.core.exceptions import (
    register_exception_handlers,
)

logger = logging.getLogger("driftguard.lifecycle")

OPENAPI_TAGS = [
    {"name": "operations", "description": "Process health and configuration readiness."},
    {"name": "specifications", "description": "OpenAPI contract comparison."},
    {"name": "impact", "description": "Repository-aware change-impact analysis."},
    {"name": "analyses", "description": "Persisted analyses, insights, and reports."},
    {"name": "risk", "description": "Risk-model provenance and status."},
    {"name": "migration", "description": "Migration-provider status."},
    {"name": "monitors", "description": "Process-local API contract monitoring."},
    {"name": "patches", "description": "Review-only proposed code patches."},
    {"name": "patch validations", "description": "Static validation and test intelligence."},
    {"name": "pull requests", "description": "Explicit, validated GitHub PR workflow."},
]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_default_analysis_repository()
    get_default_monitor_repository()
    scheduler = get_monitor_scheduler()
    logger.info(
        "DriftGuard starting storage=%s scheduler=%s github_write_provider=%s",
        settings.storage_backend,
        "enabled" if scheduler.enabled else "disabled",
        settings.github_write_provider,
    )
    scheduler.start()
    try:
        yield
    finally:
        await scheduler.stop()
        logger.info("DriftGuard stopped cleanly")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "Detect OpenAPI drift, trace repository impact, generate and statically validate "
            "review-only migration patches, and explicitly prepare human-review Pull Requests."
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
