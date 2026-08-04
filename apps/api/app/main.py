"""DriftGuard AI FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from apps.api.app.api.routes.analyses import router as analyses_router
from apps.api.app.api.routes.health import router as health_router
from apps.api.app.api.routes.impact import router as impact_router
from apps.api.app.api.routes.specifications import router as specifications_router
from apps.api.app.core.config import settings
from apps.api.app.core.dependencies import get_default_analysis_repository
from apps.api.app.core.exceptions import register_exception_handlers


@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_default_analysis_repository()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(health_router, prefix=settings.api_prefix)
    app.include_router(specifications_router, prefix=settings.api_prefix)
    app.include_router(impact_router, prefix=settings.api_prefix)
    app.include_router(analyses_router, prefix=settings.api_prefix)
    return app


app = create_app()
