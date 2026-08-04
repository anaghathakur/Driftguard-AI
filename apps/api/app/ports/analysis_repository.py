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
from apps.api.app.schemas.comparison import ApiChange, ComparisonResponse
from apps.api.app.schemas.impact import ChangeImpact, ImpactSummary, RepositoryScanSummary


class AnalysisRepository(ABC):
    @abstractmethod
    def initialize(self) -> None: ...

    @abstractmethod
    def create_or_get(self, submission: AnalysisSubmission) -> AnalysisCreation: ...

    @abstractmethod
    def start_stage(
        self, analysis_id: str, stage_name: str, ordinal: int, started_at: datetime
    ) -> int: ...

    @abstractmethod
    def complete_stage(
        self, stage_id: int, completed_at: datetime, duration_ms: int
    ) -> None: ...

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
    ) -> None: ...

    @abstractmethod
    def save_success(
        self,
        *,
        analysis_id: str,
        comparison: ComparisonResponse,
        repository_summary: RepositoryScanSummary | None,
        impact_summary: ImpactSummary | None,
        impacts: list[ChangeImpact],
        stage_id: int,
        completed_at: datetime,
        duration_ms: int,
    ) -> None: ...

    @abstractmethod
    def list_analyses(self, *, limit: int, offset: int) -> list[AnalysisRecord]: ...

    @abstractmethod
    def get_analysis(self, analysis_id: str) -> AnalysisRecord | None: ...

    @abstractmethod
    def get_changes(self, analysis_id: str) -> list[ApiChange]: ...

    @abstractmethod
    def get_matches(self, analysis_id: str) -> list[StoredMatch]: ...

    @abstractmethod
    def get_pipeline(self, analysis_id: str) -> list[PipelineStageRecord]: ...

    @abstractmethod
    def get_failure(self, analysis_id: str) -> FailureRecord | None: ...

    @abstractmethod
    def delete(self, analysis_id: str) -> bool: ...
