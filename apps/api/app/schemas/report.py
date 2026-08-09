"""Schemas for complete persisted analysis reports."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from apps.api.app.schemas.analysis import (
    AnalysisDetail,
    PersistedMatchResponse,
    PipelineStageResponse,
)
from apps.api.app.schemas.comparison import ApiChange
from apps.api.app.schemas.migration import MigrationRecommendation
from apps.api.app.schemas.patch import PatchProposal
from apps.api.app.schemas.risk import RiskPrediction


class AnalysisReportSummary(BaseModel):
    """High-level totals included in an exported analysis report."""

    total_changes: int
    breaking_changes: int
    potentially_breaking_changes: int
    non_breaking_changes: int
    repository_matches: int
    impacted_files: int
    direct_matches: int = 0
    transitive_matches: int = 0
    max_impact_depth: int = 0
    risk_predictions: int
    migration_recommendations: int
    patch_proposals: int = 0


class AnalysisReport(BaseModel):
    """Complete persisted DriftGuard analysis report."""

    report_version: str
    generated_at: datetime
    analysis: AnalysisDetail
    summary: AnalysisReportSummary
    changes: list[ApiChange]
    matches: list[PersistedMatchResponse]
    risks: list[RiskPrediction]
    migrations: list[MigrationRecommendation]
    patches: list[PatchProposal] = Field(default_factory=list)
    pipeline: list[PipelineStageResponse]
