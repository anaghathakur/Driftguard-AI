"""Public schemas for repository scanning and API impact results."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from apps.api.app.schemas.comparison import ComparisonResponse


class MatchKind(StrEnum):
    OPERATION_ID = "operation_id"
    PATH_AND_METHOD = "path_and_method"
    PATH = "path"


class MatchConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"


class RepositoryScanSummary(BaseModel):
    archive_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    archive_entries: int
    scanned_files: int
    scanned_bytes: int
    skipped_files: int
    skipped_reasons: dict[str, int]


class ImpactMatch(BaseModel):
    file_path: str
    line: int = Field(ge=1)
    column: int = Field(ge=1)
    match_kind: MatchKind
    confidence: MatchConfidence
    evidence: str = Field(max_length=240)


class ChangeImpact(BaseModel):
    change_id: str
    path: str
    method: str
    matches: list[ImpactMatch]


class ImpactSummary(BaseModel):
    total_changes: int
    impacted_changes: int
    impacted_files: int
    total_matches: int


class ImpactAnalysisResponse(BaseModel):
    comparison: ComparisonResponse
    repository: RepositoryScanSummary
    impact_summary: ImpactSummary
    impacts: list[ChangeImpact]
