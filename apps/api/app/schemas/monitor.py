"""API schemas for automatic OpenAPI monitoring."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from apps.api.app.domain.monitor import MonitorCheckStatus


class MonitorCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    specification_url: str = Field(min_length=1, max_length=2048)
    repository_url: str = Field(min_length=1, max_length=2048)
    repository_ref: str | None = Field(default=None, max_length=200)
    check_interval_minutes: int = Field(default=60, ge=1, le=10_080)
    enabled: bool = True


class MonitorUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    specification_url: str | None = Field(default=None, min_length=1, max_length=2048)
    repository_url: str | None = Field(default=None, min_length=1, max_length=2048)
    repository_ref: str | None = Field(default=None, max_length=200)
    check_interval_minutes: int | None = Field(default=None, ge=1, le=10_080)
    enabled: bool | None = None

    @model_validator(mode="after")
    def require_update(self) -> MonitorUpdateRequest:
        if not self.model_fields_set:
            raise ValueError("At least one monitor field must be provided.")
        nullable = {"repository_ref"}
        for field in self.model_fields_set - nullable:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null.")
        return self


class MonitorResponse(BaseModel):
    monitor_id: str
    name: str
    specification_url: str
    repository_url: str
    repository_ref: str | None
    check_interval_minutes: int
    enabled: bool
    baseline_filename: str
    baseline_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    baseline_observed_at: datetime
    created_at: datetime
    updated_at: datetime
    last_checked_at: datetime | None
    last_changed_at: datetime | None
    last_successful_analysis_id: str | None
    last_check_status: MonitorCheckStatus | None
    last_error_code: str | None
    last_error_message: str | None


class MonitorCheckResponse(BaseModel):
    check_id: str
    monitor_id: str
    status: MonitorCheckStatus
    checked_at: datetime
    completed_at: datetime | None
    duration_ms: int | None
    previous_spec_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    observed_spec_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    analysis_id: str | None
    error_code: str | None
    error_message: str | None
