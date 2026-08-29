"""Schemas for safe, structured API migration recommendations."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

MigrationListItem = Annotated[
    str,
    Field(min_length=1, max_length=500),
]


class MigrationProvider(StrEnum):
    """Supported migration recommendation providers."""

    MOCK = "mock"
    GEMINI = "gemini"
    DETERMINISTIC = "deterministic"


class RecommendationSource(StrEnum):
    """How the final migration recommendation was produced."""

    MOCK = "mock"
    GEMINI = "gemini"
    DETERMINISTIC_FALLBACK = "deterministic_fallback"


class GeneratedMigrationContent(BaseModel):
    """Validated content produced by a provider."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    summary: str = Field(
        min_length=1,
        max_length=500,
    )

    why_it_matters: str = Field(
        min_length=1,
        max_length=1_000,
    )

    affected_code_explanation: str = Field(
        min_length=1,
        max_length=1_000,
    )

    migration_steps: list[MigrationListItem] = Field(
        min_length=1,
        max_length=8,
    )

    suggested_tests: list[MigrationListItem] = Field(
        min_length=1,
        max_length=8,
    )

    code_example: str = Field(
        default="",
        max_length=2_000,
    )

    assumptions: list[MigrationListItem] = Field(
        default_factory=list,
        max_length=6,
    )

    warnings: list[MigrationListItem] = Field(
        default_factory=list,
        max_length=8,
    )

    confidence: float = Field(
        ge=0,
        le=1,
    )


class MigrationRecommendation(GeneratedMigrationContent):
    """Complete persisted recommendation returned through the API."""

    recommendation_id: str
    analysis_id: str | None = None
    change_id: str

    provider: MigrationProvider
    provider_model: str
    recommendation_source: RecommendationSource

    provider_warning: str | None = Field(
        default=None,
        max_length=500,
    )

    redactions_applied: int = Field(
        default=0,
        ge=0,
    )

    prompt_version: str
    schema_version: str
    generated_at: datetime


class MigrationProviderStatus(BaseModel):
    """Public provider status that never exposes credentials."""

    configured_provider: MigrationProvider
    active_provider: MigrationProvider
    provider_model: str
    available: bool

    prompt_version: str
    schema_version: str

    fallback_enabled: bool = True
    warning: str | None = None
