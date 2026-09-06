"""Bounded schemas for static patch validation and test intelligence."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ValidationReadiness(StrEnum):
    READY_FOR_REVIEW = "ready_for_review"
    NEEDS_REVIEW = "needs_review"
    BLOCKED = "blocked"


class FindingStatus(StrEnum):
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"
    UNKNOWN = "unknown"


class FindingSeverity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FindingCategory(StrEnum):
    ENDPOINT_METHOD = "endpoint_method"
    REQUIRED_REQUEST_FIELD = "required_request_field"
    REMOVED_REQUEST_FIELD = "removed_request_field"
    CALLER_SIGNATURE = "caller_signature"
    STALE_VALUE = "stale_value"
    PATCH_SCOPE = "patch_scope"
    STATIC_ANALYSIS = "static_analysis"


class TestRelevance(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TestPlanProviderName(StrEnum):
    MOCK = "mock"
    GEMINI = "gemini"
    DETERMINISTIC = "deterministic"


class TestPlanProviderMode(StrEnum):
    DETERMINISTIC_MOCK = "deterministic_mock"
    DETERMINISTIC = "deterministic"
    EXTERNAL = "external"


class ValidationExecutionStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    PARTIAL = "partial"
    NOT_CONFIGURED = "not_configured"
    BLOCKED = "blocked"


class ValidationCommandResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str = Field(min_length=1, max_length=30)
    display_name: str = Field(min_length=1, max_length=120)
    argv: list[str] = Field(min_length=1, max_length=12)
    exit_code: int | None = None
    timed_out: bool = False
    duration_ms: int = Field(ge=0)
    stdout_summary: str = Field(default="", max_length=20_000)
    stderr_summary: str = Field(default="", max_length=20_000)
    output_truncated: bool = False


class ValidationExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ValidationExecutionStatus
    ecosystem: str | None = Field(default=None, max_length=30)
    commands: list[ValidationCommandResult] = Field(default_factory=list, max_length=8)
    checks: list[str] = Field(default_factory=list, max_length=20)
    duration_ms: int = Field(default=0, ge=0)
    isolated_temporary_copy: bool = False
    original_repository_unchanged: bool = True
    message: str = Field(min_length=1, max_length=500)


class TestType(StrEnum):
    UNIT = "unit"
    INTEGRATION = "integration"
    REGRESSION = "regression"
    NEGATIVE = "negative"
    CONTRACT = "contract"


class TestPriority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ValidationFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_id: str = Field(min_length=1, max_length=120)
    category: FindingCategory
    status: FindingStatus
    severity: FindingSeverity
    message: str = Field(min_length=1, max_length=500)
    change_id: str | None = Field(default=None, max_length=120)
    file_path: str | None = Field(default=None, max_length=500)
    symbol: str | None = Field(default=None, max_length=500)
    line: int | None = Field(default=None, ge=1)
    column: int | None = Field(default=None, ge=1)
    evidence: str | None = Field(default=None, max_length=240)


class RelatedTest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_path: str = Field(min_length=1, max_length=500)
    language: str = Field(min_length=1, max_length=30)
    relevance: TestRelevance
    reasons: list[str] = Field(min_length=1, max_length=8)
    related_symbols: list[str] = Field(default_factory=list, max_length=20)
    related_changes: list[str] = Field(default_factory=list, max_length=20)
    lines: list[int] = Field(default_factory=list, max_length=20)


class TestGap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gap_id: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=500)
    symbol: str | None = Field(default=None, max_length=500)
    file_path: str | None = Field(default=None, max_length=500)
    impact_depth: int = Field(default=0, ge=0)


class TestPlanCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    test_type: TestType
    target: str = Field(min_length=1, max_length=500)
    rationale: str = Field(min_length=1, max_length=500)
    steps: list[str] = Field(min_length=1, max_length=8)
    expected_result: str = Field(min_length=1, max_length=500)
    priority: TestPriority


class TestPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=500)
    cases: list[TestPlanCase] = Field(default_factory=list, max_length=30)


class PatchValidationRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    validation_id: str
    patch_id: str
    analysis_id: str
    created_at: datetime
    validation_profile_version: str = Field(min_length=1, max_length=50)
    readiness: ValidationReadiness
    source_repository_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    request_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    passed_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    unknown_count: int = Field(ge=0)
    contract_findings: list[ValidationFinding] = Field(default_factory=list, max_length=200)
    dependency_findings: list[ValidationFinding] = Field(default_factory=list, max_length=200)
    related_tests: list[RelatedTest] = Field(default_factory=list, max_length=200)
    test_gaps: list[TestGap] = Field(default_factory=list, max_length=200)
    test_plan: TestPlan
    provider: TestPlanProviderName
    provider_model: str = Field(min_length=1, max_length=200)
    provider_mode: TestPlanProviderMode
    warnings: list[str] = Field(default_factory=list, max_length=20)
    modified_files: list[str] = Field(default_factory=list, max_length=50)
    direct_impacted_files: list[str] = Field(default_factory=list, max_length=100)
    transitive_impacted_files: list[str] = Field(default_factory=list, max_length=100)
    unrelated_modified_files: list[str] = Field(default_factory=list, max_length=50)
    execution: ValidationExecution | None = None
    static_only: bool = True


class PatchValidationListItem(BaseModel):
    validation_id: str
    patch_id: str
    analysis_id: str
    created_at: datetime
    readiness: ValidationReadiness
    passed_count: int
    warning_count: int
    failed_count: int
    unknown_count: int
    provider: TestPlanProviderName
    provider_model: str
