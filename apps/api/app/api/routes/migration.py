"""Migration recommendation provider endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from apps.api.app.core.dependencies import (
    get_migration_recommendation_service,
)
from apps.api.app.migration.service import (
    MigrationRecommendationService,
)
from apps.api.app.schemas.migration import (
    MigrationProviderStatus,
)

router = APIRouter(
    prefix="/migration",
    tags=["migration"],
)


@router.get(
    "/provider",
    response_model=MigrationProviderStatus,
)
def get_migration_provider_status(
    service: Annotated[
        MigrationRecommendationService,
        Depends(get_migration_recommendation_service),
    ],
) -> MigrationProviderStatus:
    """Return safe information about the active provider."""

    return service.status()
