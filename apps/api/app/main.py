"""DriftGuard AI FastAPI application factory."""

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
from apps.api.app.api.routes.risk import (
    router as risk_router,
)
from apps.api.app.api.routes.specifications import (
    router as specifications_router,
)
from apps.api.app.core.config import settings
from apps.api.app.core.dependencies import (
    get_default_analysis_repository,
    get_default_monitor_repository,
    get_monitor_scheduler,
)
from apps.api.app.core.exceptions import (
    register_exception_handlers,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_default_analysis_repository()
    get_default_monitor_repository()
    scheduler = get_monitor_scheduler()
    scheduler.start()
    try:
        yield
    finally:
        await scheduler.stop()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )

    register_exception_handlers(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
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

    return app


app = create_app()
