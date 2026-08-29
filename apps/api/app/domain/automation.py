"""Durable GitHub automation, contract discovery, and Check Run records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class WebhookDeliveryStatus(StrEnum):
    RECEIVED = "received"
    QUEUED = "queued"
    PROCESSED = "processed"
    IGNORED = "ignored"
    FAILED = "failed"


class BackgroundJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRY_SCHEDULED = "retry_scheduled"


class BackgroundJobType(StrEnum):
    REPOSITORY_SYNC = "repository_sync"
    GITHUB_PUSH_SCAN = "github_push_scan"
    GITHUB_PR_CONTRACT_CHECK = "github_pr_contract_check"
    CONSUMER_IMPACT_ANALYSIS = "consumer_impact_analysis"


class ContractKind(StrEnum):
    OPENAPI = "openapi"


class CheckRunStatus(StrEnum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class CheckRunConclusion(StrEnum):
    SUCCESS = "success"
    NEUTRAL = "neutral"
    FAILURE = "failure"
    ACTION_REQUIRED = "action_required"


@dataclass(frozen=True, slots=True)
class WebhookDelivery:
    delivery_id: str
    github_delivery_id: str
    event_type: str
    action: str | None
    github_installation_id: int | None
    github_repository_id: int | None
    received_at: datetime
    status: WebhookDeliveryStatus
    processed_at: datetime | None = None
    failure_code: str | None = None


@dataclass(frozen=True, slots=True)
class BackgroundJob:
    job_id: str
    workspace_id: str
    job_type: BackgroundJobType
    status: BackgroundJobStatus
    payload_safe: dict[str, object]
    attempt_count: int
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    next_attempt_at: datetime | None = None
    failure_code: str | None = None
    failure_message_safe: str | None = None


@dataclass(frozen=True, slots=True)
class RepositoryContract:
    contract_id: str
    workspace_id: str
    repository_connection_id: str
    path: str
    contract_kind: ContractKind
    title: str
    version: str
    discovered_at: datetime
    updated_at: datetime
    last_seen_commit: str
    enabled: bool
    manually_configured: bool = False


@dataclass(frozen=True, slots=True)
class ApiDependency:
    dependency_id: str
    workspace_id: str
    repository_connection_id: str
    evidence_type: str
    confidence: float
    created_at: datetime
    updated_at: datetime
    contract_id: str | None = None
    monitor_id: str | None = None
    source_path: str | None = None
    confirmed: bool = False


@dataclass(frozen=True, slots=True)
class CheckAnnotation:
    path: str
    start_line: int
    end_line: int
    annotation_level: str
    message: str
    title: str | None = None


@dataclass(frozen=True, slots=True)
class GitHubCheckRecord:
    check_record_id: str
    workspace_id: str
    repository_connection_id: str
    logical_key: str
    head_sha: str
    name: str
    status: CheckRunStatus
    created_at: datetime
    updated_at: datetime
    github_check_run_id: int | None = None
    job_id: str | None = None
    analysis_id: str | None = None
    conclusion: CheckRunConclusion | None = None
    details_url: str | None = None
    summary: str = ""
    annotations: tuple[CheckAnnotation, ...] = field(default_factory=tuple)
