"""Repository interface for durable analysis state."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from apps.api.app.domain.analysis import (
    AnalysisCreation,
    AnalysisRecord,
    AnalysisSubmission,
    FailureRecord,
    PipelineStageRecord,
    StoredMatch,
)
from apps.api.app.schemas.comparison import (
    ApiChange,
    ComparisonResponse,
)
from apps.api.app.schemas.impact import (
    ChangeImpact,
    ImpactSummary,
    RepositoryScanSummary,
)
from apps.api.app.schemas.migration import (
    MigrationRecommendation,
)
from apps.api.app.schemas.patch import PatchProposal
from apps.api.app.schemas.risk import RiskPrediction


class AnalysisRepository(ABC):
    @abstractmethod
    def initialize(self) -> None:
        """Initialize database structures."""

    @abstractmethod
    def create_or_get(
        self,
        submission: AnalysisSubmission,
    ) -> AnalysisCreation:
        """Create an analysis or return an existing duplicate."""

    @abstractmethod
    def start_stage(
        self,
        analysis_id: str,
        stage_name: str,
        ordinal: int,
        started_at: datetime,
    ) -> int:
        """Start a pipeline stage."""

    @abstractmethod
    def complete_stage(
        self,
        stage_id: int,
        completed_at: datetime,
        duration_ms: int,
    ) -> None:
        """Mark a pipeline stage successful."""

    @abstractmethod
    def fail_analysis(
        self,
        *,
        analysis_id: str,
        stage_id: int,
        stage_name: str,
        error_code: str,
        safe_message: str,
        status_code: int,
        failed_at: datetime,
        duration_ms: int,
    ) -> None:
        """Persist a safe failed-analysis record."""

    @abstractmethod
    def save_success(
        self,
        *,
        analysis_id: str,
        comparison: ComparisonResponse,
        repository_summary: RepositoryScanSummary | None,
        impact_summary: ImpactSummary | None,
        impacts: list[ChangeImpact],
        risk_predictions: list[RiskPrediction],
        migration_recommendations: list[
            MigrationRecommendation
        ],
        stage_id: int,
        completed_at: datetime,
        duration_ms: int,
    ) -> None:
        """Persist one successful complete analysis."""

    @abstractmethod
    def list_analyses(
        self,
        *,
        limit: int,
        offset: int,
    ) -> list[AnalysisRecord]:
        """Return paginated analysis history."""

    @abstractmethod
    def get_analysis(
        self,
        analysis_id: str,
    ) -> AnalysisRecord | None:
        """Retrieve analysis metadata."""

    @abstractmethod
    def get_changes(
        self,
        analysis_id: str,
    ) -> list[ApiChange]:
        """Retrieve persisted contract changes."""

    @abstractmethod
    def get_matches(
        self,
        analysis_id: str,
    ) -> list[StoredMatch]:
        """Retrieve persisted repository matches."""

    @abstractmethod
    def get_pipeline(
        self,
        analysis_id: str,
    ) -> list[PipelineStageRecord]:
        """Retrieve pipeline stages."""

    @abstractmethod
    def get_risk_predictions(
        self,
        analysis_id: str,
    ) -> list[RiskPrediction]:
        """Retrieve risk predictions."""

    @abstractmethod
    def get_migration_recommendations(
        self,
        analysis_id: str,
    ) -> list[MigrationRecommendation]:
        """Retrieve migration recommendations."""

    @abstractmethod
    def get_failure(
        self,
        analysis_id: str,
    ) -> FailureRecord | None:
        """Retrieve the safe failure record."""

    @abstractmethod
    def save_patch_proposal(self, proposal: PatchProposal) -> PatchProposal:
        """Persist a validated proposal or return its idempotent equivalent."""

    @abstractmethod
    def get_patch_proposal(
        self,
        analysis_id: str,
        patch_id: str,
    ) -> PatchProposal | None:
        """Retrieve one patch proposal belonging to an analysis."""

    @abstractmethod
    def get_patch_by_fingerprint(
        self,
        analysis_id: str,
        fingerprint: str,
    ) -> PatchProposal | None:
        """Retrieve an idempotent patch proposal by fingerprint."""

    @abstractmethod
    def list_patch_proposals(self, analysis_id: str) -> list[PatchProposal]:
        """Retrieve patch proposals for one analysis."""

    @abstractmethod
    def delete(
        self,
        analysis_id: str,
    ) -> bool:
        """Delete an analysis and all dependent records."""
