"""Public schemas for repository scanning and API impact results."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from apps.api.app.schemas.comparison import ComparisonResponse


class MatchKind(StrEnum):
    OPERATION_ID = "operation_id"
    PATH_AND_METHOD = "path_and_method"
    PATH = "path"
    DIRECT_SEMANTIC = "direct_semantic"
    WRAPPER = "wrapper"
    TRANSITIVE_CALL = "transitive_call"


class MatchConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"


class ImpactAnalysisKind(StrEnum):
    LEXICAL = "lexical"
    DIRECT = "direct"
    WRAPPER = "wrapper"
    TRANSITIVE = "transitive"


class ImpactTraceRelation(StrEnum):
    DIRECT_API_USAGE = "direct_api_usage"
    CALLS = "calls"


class ImpactTraceStep(BaseModel):
    file_path: str
    symbol: str | None = None
    relation: ImpactTraceRelation
    line: int = Field(ge=1)
    column: int = Field(ge=1)
    evidence: str = Field(default="", max_length=240)


class CodeAnalysisSummary(BaseModel):
    supported_files: int = 0
    parser_failures: int = 0
    parser_failure_files: list[str] = Field(default_factory=list, max_length=20)
    symbols_discovered: int = 0
    call_edges_resolved: int = 0
    direct_api_anchors: int = 0
    transitive_matches: int = 0
    max_impact_depth: int = 0


class RepositoryScanSummary(BaseModel):
    archive_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    archive_entries: int
    scanned_files: int
    scanned_bytes: int
    skipped_files: int
    skipped_reasons: dict[str, int]
    code_analysis: CodeAnalysisSummary | None = None


class ImpactMatch(BaseModel):
    file_path: str
    line: int = Field(ge=1)
    column: int = Field(ge=1)
    match_kind: MatchKind
    confidence: MatchConfidence
    evidence: str = Field(max_length=240)
    symbol: str | None = None
    language: str | None = None
    impact_depth: int = Field(default=0, ge=0)
    analysis_kind: ImpactAnalysisKind = ImpactAnalysisKind.LEXICAL
    trace: list[ImpactTraceStep] = Field(default_factory=list, max_length=10)


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
    analysis_id: str | None = None
    duplicate: bool = False
