"""Public analysis history, pipeline, and persisted-match schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from apps.api.app.domain.analysis import (
    AnalysisKind,
    AnalysisStatus,
    PipelineStageStatus,
)
from apps.api.app.schemas.comparison import ComparisonSummary, ContractMetadata
from apps.api.app.schemas.impact import (
    ImpactSummary,
    MatchConfidence,
    MatchKind,
    RepositoryScanSummary,
)


class FileHashes(BaseModel):
    old_spec: str = Field(pattern=r"^[a-f0-9]{64}$")
    new_spec: str = Field(pattern=r"^[a-f0-9]{64}$")
    repository: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class AnalysisFailureResponse(BaseModel):
    stage_name: str
    error_code: str
    message: str
    status_code: int
    created_at: datetime


class AnalysisListItem(BaseModel):
    analysis_id: str
    kind: AnalysisKind
    status: AnalysisStatus
    created_at: datetime
    completed_at: datetime | None
    total_changes: int
    total_matches: int
    failure: AnalysisFailureResponse | None = None


class AnalysisDetail(BaseModel):
    analysis_id: str
    kind: AnalysisKind
    status: AnalysisStatus
    request_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    old_filename: str
    new_filename: str
    repository_filename: str | None
    file_hashes: FileHashes
    old_contract: ContractMetadata | None
    new_contract: ContractMetadata | None
    comparison_summary: ComparisonSummary | None
    repository_summary: RepositoryScanSummary | None
    impact_summary: ImpactSummary | None
    failure: AnalysisFailureResponse | None = None


class PersistedMatchResponse(BaseModel):
    change_id: str
    file_path: str
    line: int = Field(ge=1)
    column: int = Field(ge=1)
    match_kind: MatchKind
    confidence: MatchConfidence
    evidence: str = Field(max_length=240)


class PipelineStageResponse(BaseModel):
    stage_name: str
    ordinal: int
    status: PipelineStageStatus
    started_at: datetime
    completed_at: datetime | None
    duration_ms: int | None
    error_code: str | None
    error_message: str | None
