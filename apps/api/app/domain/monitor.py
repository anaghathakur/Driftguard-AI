"""Persistence-neutral API monitor records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class MonitorCheckStatus(StrEnum):
    CHECKING = "checking"
    UNCHANGED = "unchanged"
    CHANGED = "changed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ApiMonitor:
    monitor_id: str
    name: str
    specification_url: str
    repository_url: str
    repository_ref: str | None
    check_interval_minutes: int
    enabled: bool
    baseline_filename: str
    baseline_content: bytes
    baseline_sha256: str
    baseline_observed_at: datetime
    created_at: datetime
    updated_at: datetime
    last_checked_at: datetime | None = None
    last_changed_at: datetime | None = None
    last_successful_analysis_id: str | None = None
    last_check_status: MonitorCheckStatus | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None


@dataclass(frozen=True, slots=True)
class MonitorCheckRecord:
    check_id: str
    monitor_id: str
    status: MonitorCheckStatus
    checked_at: datetime
    completed_at: datetime | None
    duration_ms: int | None
    previous_spec_hash: str
    observed_spec_hash: str | None
    analysis_id: str | None
    error_code: str | None
    error_message: str | None
