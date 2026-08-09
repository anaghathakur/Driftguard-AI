"""Validated schemas for review-only proposed source patches."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PatchStatus(StrEnum):
    VALIDATED = "validated"


class PatchProvider(StrEnum):
    MOCK = "mock"
    GEMINI = "gemini"


class PatchProviderMode(StrEnum):
    DETERMINISTIC_MOCK = "deterministic_mock"
    EXTERNAL = "external"


class StructuredPatchEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    expected_original: str = Field(min_length=1, max_length=50_000)
    replacement: str = Field(max_length=50_000)
    reason: str = Field(min_length=1, max_length=500)
    related_change_ids: list[str] = Field(min_length=1, max_length=10)


class StructuredPatchFile(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    file_path: str = Field(min_length=1, max_length=500)
    language: str = Field(min_length=1, max_length=30)
    related_symbol: str | None = Field(default=None, max_length=500)
    edits: list[StructuredPatchEdit] = Field(min_length=1, max_length=50)


class GeneratedPatchContent(BaseModel):
    """Strict provider output before trusted validation."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    summary: str = Field(min_length=1, max_length=500)
    files: list[StructuredPatchFile] = Field(min_length=1, max_length=20)
    warnings: list[str] = Field(default_factory=list, max_length=10)


class PatchValidationResult(BaseModel):
    source_snapshot_verified: bool
    paths_safe: bool
    allowed_scope_verified: bool
    edit_anchors_verified: bool
    syntax_valid: bool
    limits_valid: bool
    warnings: list[str] = Field(default_factory=list, max_length=10)


class PatchProposal(BaseModel):
    patch_id: str
    analysis_id: str
    created_at: datetime
    status: PatchStatus
    summary: str = Field(min_length=1, max_length=500)
    provider: PatchProvider
    provider_model: str = Field(min_length=1, max_length=200)
    provider_mode: PatchProviderMode
    patch_profile_version: str = Field(min_length=1, max_length=50)
    source_repository_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    request_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    files_changed: int = Field(ge=1)
    edit_count: int = Field(ge=1)
    validation: PatchValidationResult
    warnings: list[str] = Field(default_factory=list, max_length=10)
    unified_diff: str = Field(min_length=1, max_length=200_000)
    files: list[StructuredPatchFile] = Field(min_length=1, max_length=20)
    redactions_applied: int = Field(default=0, ge=0)


class PatchProposalListItem(BaseModel):
    patch_id: str
    analysis_id: str
    created_at: datetime
    status: PatchStatus
    summary: str
    provider: PatchProvider
    provider_model: str
    files_changed: int
    edit_count: int
