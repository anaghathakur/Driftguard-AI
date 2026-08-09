"""Safe metadata models for explicit GitHub pull-request workflows."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from apps.api.app.schemas.validation import ValidationReadiness


class PullRequestStatus(StrEnum):
    PREPARING = "preparing"
    CREATED = "created"
    FAILED = "failed"


class GitHubWriteProviderName(StrEnum):
    MOCK = "mock"
    GITHUB_APP = "github_app"


class PullRequestPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository_owner: str
    repository_name: str
    base_ref: str
    base_commit_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    branch_name: str
    files_changed: int = Field(ge=1)
    edit_count: int = Field(ge=1)
    validation_readiness: ValidationReadiness
    tests_executed: bool = False


class GitHubPullRequestRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pr_record_id: str
    analysis_id: str
    patch_id: str
    validation_id: str
    repository_owner: str
    repository_name: str
    base_ref: str
    base_commit_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    branch_name: str = Field(min_length=1, max_length=200)
    commit_sha: str | None = Field(default=None, pattern=r"^[a-f0-9]{40}$")
    pull_request_number: int | None = Field(default=None, ge=1)
    pull_request_url: str | None = Field(default=None, max_length=2048)
    status: PullRequestStatus
    created_at: datetime
    updated_at: datetime
    provider: GitHubWriteProviderName
    request_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    pull_request_profile_version: str = Field(min_length=1, max_length=50)
    validation_readiness: ValidationReadiness
    files_changed: int = Field(ge=1)
    edit_count: int = Field(ge=1)
    modified_file_sha256: dict[str, str] = Field(default_factory=dict, max_length=20)
    failure_code: str | None = Field(default=None, max_length=120)
    failure_message: str | None = Field(default=None, max_length=500)
    tests_executed: bool = False


class PullRequestListItem(BaseModel):
    pr_record_id: str
    analysis_id: str
    patch_id: str
    validation_id: str
    repository_owner: str
    repository_name: str
    branch_name: str
    pull_request_number: int | None
    pull_request_url: str | None
    status: PullRequestStatus
    created_at: datetime
    validation_readiness: ValidationReadiness
