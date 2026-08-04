"""Persistence-neutral analysis and pipeline records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class AnalysisKind(StrEnum):
    COMPARISON = "comparison"
    IMPACT = "impact"


class AnalysisStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PipelineStageStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class AnalysisSubmission:
    kind: AnalysisKind
    request_fingerprint: str
    old_filename: str
    new_filename: str
    repository_filename: str | None
    old_file_sha256: str
    new_file_sha256: str
    repository_file_sha256: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AnalysisRecord:
    analysis_id: str
    kind: AnalysisKind
    status: AnalysisStatus
    request_fingerprint: str
    old_filename: str
    new_filename: str
    repository_filename: str | None
    old_file_sha256: str
    new_file_sha256: str
    repository_file_sha256: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    old_contract: dict[str, object] | None
    new_contract: dict[str, object] | None
    comparison_summary: dict[str, object] | None
    repository_summary: dict[str, object] | None
    impact_summary: dict[str, object] | None


@dataclass(frozen=True, slots=True)
class AnalysisCreation:
    analysis: AnalysisRecord
    duplicate: bool


@dataclass(frozen=True, slots=True)
class StoredMatch:
    change_id: str
    file_path: str
    line: int
    column: int
    match_kind: str
    confidence: str
    evidence: str


@dataclass(frozen=True, slots=True)
class PipelineStageRecord:
    stage_id: int
    analysis_id: str
    stage_name: str
    ordinal: int
    status: PipelineStageStatus
    started_at: datetime
    completed_at: datetime | None
    duration_ms: int | None
    error_code: str | None
    error_message: str | None


@dataclass(frozen=True, slots=True)
class FailureRecord:
    failure_id: int
    analysis_id: str
    stage_name: str
    error_code: str
    safe_message: str
    status_code: int
    created_at: datetime
