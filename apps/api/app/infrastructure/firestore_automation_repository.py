"""Firestore persistence for durable GitHub automation state.

This adapter is intentionally separate from the legacy SQLite adapter.  Firestore
transactions protect webhook idempotency and job leases so Cloud Run Jobs can run
concurrently without claiming the same work twice.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from google.api_core.exceptions import AlreadyExists
from google.cloud import firestore

from apps.api.app.domain.automation import (
    ApiDependency,
    BackgroundJob,
    BackgroundJobStatus,
    BackgroundJobType,
    CheckAnnotation,
    CheckRunConclusion,
    CheckRunStatus,
    ContractKind,
    GitHubCheckRecord,
    RepositoryContract,
    WebhookDelivery,
    WebhookDeliveryStatus,
)
from apps.api.app.ports.automation_repository import AutomationRepository


class FirestoreAutomationRepository(AutomationRepository):
    """Workspace-safe automation records backed by Firestore.

    The database must have the composite indexes documented in the Google Cloud
    deployment guide.  Each claim/recovery uses one transaction per job, which
    avoids a long-running transaction and makes competing Cloud Run Job workers
    safely converge on a single owner.
    """

    def __init__(
        self,
        *,
        project_id: str | None = None,
        database_id: str = "(default)",
        client: Any | None = None,
    ) -> None:
        self.client = client or firestore.Client(
            project=project_id or None,
            database=database_id,
        )

    def initialize(self) -> None:
        """Firestore collections are created on first write."""

    def create_delivery(self, delivery: WebhookDelivery) -> bool:
        try:
            self._deliveries.document(_delivery_key(delivery.github_delivery_id)).create(
                _delivery_data(delivery)
            )
        except AlreadyExists:
            return False
        return True

    def get_delivery(self, github_delivery_id: str) -> WebhookDelivery | None:
        return _read(
            self._deliveries.document(_delivery_key(github_delivery_id)),
            _delivery,
        )

    def get_delivery_by_id(self, delivery_id: str) -> WebhookDelivery | None:
        snapshot = next(
            iter(
                self._deliveries.where("delivery_id", "==", delivery_id).limit(1).stream()
            ),
            None,
        )
        return _delivery(snapshot.to_dict() or {}) if snapshot else None

    def save_delivery(self, delivery: WebhookDelivery) -> None:
        self._deliveries.document(_delivery_key(delivery.github_delivery_id)).set(
            _delivery_data(delivery)
        )

    def enqueue_job(self, job: BackgroundJob) -> BackgroundJob:
        self._jobs.document(job.job_id).create(_job_data(job))
        return job

    def claim_due_jobs(self, now: datetime, limit: int = 10) -> list[BackgroundJob]:
        queued = list(
            self._jobs.where("status", "==", BackgroundJobStatus.QUEUED.value)
            .order_by("created_at")
            .limit(limit)
            .stream()
        )
        retries = list(
            self._jobs.where("status", "==", BackgroundJobStatus.RETRY_SCHEDULED.value)
            .where("next_attempt_at", "<=", now)
            .order_by("next_attempt_at")
            .limit(limit)
            .stream()
        )
        candidates = sorted(
            (*queued, *retries),
            key=lambda item: _datetime((item.to_dict() or {})["created_at"]),
        )[:limit]
        return [claimed for item in candidates if (claimed := self._claim(item.reference, now))]

    def recover_stale_jobs(
        self, now: datetime, *, retry_limit: int, stale_after_seconds: float
    ) -> list[BackgroundJob]:
        cutoff = now - timedelta(seconds=max(1.0, stale_after_seconds))
        snapshots = self._jobs.where("status", "==", BackgroundJobStatus.RUNNING.value).where(
            "started_at", "<=", cutoff
        ).order_by("started_at").stream()
        result: list[BackgroundJob] = []
        for item in snapshots:
            recovered = self._recover(item.reference, now, retry_limit, cutoff)
            if recovered:
                result.append(recovered)
        return result

    def save_job(self, job: BackgroundJob) -> None:
        self._jobs.document(job.job_id).set(_job_data(job))

    def get_job(self, job_id: str, workspace_id: str | None = None) -> BackgroundJob | None:
        job = _read(self._jobs.document(job_id), _job)
        if job is None or (workspace_id is not None and job.workspace_id != workspace_id):
            return None
        return job

    def list_jobs(self, workspace_id: str, limit: int = 50) -> list[BackgroundJob]:
        return [
            _job(item.to_dict() or {})
            for item in self._jobs.where("workspace_id", "==", workspace_id)
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .stream()
        ]

    def upsert_contract(self, contract: RepositoryContract) -> RepositoryContract:
        ref = self._contracts.document(
            _key(contract.workspace_id, contract.repository_connection_id, contract.path)
        )
        existing = _read(ref, _contract)
        value = replace(
            contract,
            contract_id=existing.contract_id if existing else contract.contract_id,
            discovered_at=existing.discovered_at if existing else contract.discovered_at,
        )
        ref.set(_contract_data(value))
        return value

    def get_contract(self, contract_id: str) -> RepositoryContract | None:
        snapshot = next(
            iter(
                self._contracts.where("contract_id", "==", contract_id).limit(1).stream()
            ),
            None,
        )
        return _contract(snapshot.to_dict() or {}) if snapshot else None

    def list_contracts(self, workspace_id: str, repository_id: str) -> list[RepositoryContract]:
        return [
            _contract(item.to_dict() or {})
            for item in self._contracts.where("workspace_id", "==", workspace_id)
            .where("repository_connection_id", "==", repository_id)
            .order_by("path")
            .stream()
        ]

    def save_dependency(self, dependency: ApiDependency) -> ApiDependency:
        self._dependencies.document(dependency.dependency_id).set(_dependency_data(dependency))
        return dependency

    def list_dependencies(self, workspace_id: str, repository_id: str) -> list[ApiDependency]:
        values = [
            _dependency(item.to_dict() or {})
            for item in self._dependencies.where("workspace_id", "==", workspace_id)
            .where("repository_connection_id", "==", repository_id)
            .stream()
        ]
        return sorted(values, key=lambda item: (item.confidence, item.updated_at), reverse=True)

    def upsert_check(self, check: GitHubCheckRecord) -> GitHubCheckRecord:
        ref = self._checks.document(_key(check.workspace_id, check.logical_key))
        existing = _read(ref, _check)
        value = replace(
            check,
            check_record_id=existing.check_record_id if existing else check.check_record_id,
            created_at=existing.created_at if existing else check.created_at,
        )
        ref.set(_check_data(value))
        return value

    def get_check_by_logical_key(
        self, workspace_id: str, logical_key: str
    ) -> GitHubCheckRecord | None:
        return _read(self._checks.document(_key(workspace_id, logical_key)), _check)

    def list_checks(self, workspace_id: str, repository_id: str) -> list[GitHubCheckRecord]:
        return [
            _check(item.to_dict() or {})
            for item in self._checks.where("workspace_id", "==", workspace_id)
            .where("repository_connection_id", "==", repository_id)
            .order_by("updated_at", direction=firestore.Query.DESCENDING)
            .stream()
        ]

    @property
    def _deliveries(self):
        return self.client.collection("automation_deliveries")

    @property
    def _jobs(self):
        return self.client.collection("automation_jobs")

    @property
    def _contracts(self):
        return self.client.collection("automation_contracts")

    @property
    def _dependencies(self):
        return self.client.collection("automation_dependencies")

    @property
    def _checks(self):
        return self.client.collection("automation_checks")

    def _claim(self, reference, now: datetime) -> BackgroundJob | None:
        transaction = self.client.transaction()

        @firestore.transactional
        def claim(txn):
            snapshot = reference.get(transaction=txn)
            if not snapshot.exists:
                return None
            job = _job(snapshot.to_dict() or {})
            due = job.status is BackgroundJobStatus.QUEUED or (
                job.status is BackgroundJobStatus.RETRY_SCHEDULED
                and job.next_attempt_at is not None
                and job.next_attempt_at <= now
            )
            if not due:
                return None
            claimed = replace(
                job,
                status=BackgroundJobStatus.RUNNING,
                started_at=now,
                next_attempt_at=None,
                attempt_count=job.attempt_count + 1,
            )
            txn.set(reference, _job_data(claimed))
            return claimed

        return claim(transaction)

    def _recover(
        self,
        reference,
        now: datetime,
        retry_limit: int,
        cutoff: datetime,
    ) -> BackgroundJob | None:
        transaction = self.client.transaction()

        @firestore.transactional
        def recover(txn):
            snapshot = reference.get(transaction=txn)
            if not snapshot.exists:
                return None
            job = _job(snapshot.to_dict() or {})
            if (
                job.status is not BackgroundJobStatus.RUNNING
                or job.started_at is None
                or job.started_at > cutoff
            ):
                return None
            retry = job.attempt_count <= retry_limit
            recovered = replace(
                job,
                status=(
                    BackgroundJobStatus.RETRY_SCHEDULED if retry else BackgroundJobStatus.FAILED
                ),
                completed_at=None if retry else now,
                next_attempt_at=now if retry else None,
                failure_code="worker_interrupted",
                failure_message_safe=(
                    "A background worker stopped before this job completed."
                    if retry
                    else "A background worker stopped and the retry limit was reached."
                ),
            )
            txn.set(reference, _job_data(recovered))
            return recovered

        return recover(transaction)


def _key(*values: str) -> str:
    return hashlib.sha256("\x1f".join(values).encode("utf-8")).hexdigest()


def _delivery_key(github_delivery_id: str) -> str:
    return _key("delivery", github_delivery_id)


def _read(reference, mapper):
    snapshot = reference.get()
    return mapper(snapshot.to_dict() or {}) if snapshot.exists else None


def _delivery_data(value: WebhookDelivery) -> dict[str, object]:
    return {
        "delivery_id": value.delivery_id,
        "github_delivery_id": value.github_delivery_id,
        "event_type": value.event_type,
        "action": value.action,
        "github_installation_id": value.github_installation_id,
        "github_repository_id": value.github_repository_id,
        "received_at": value.received_at,
        "status": value.status.value,
        "processed_at": value.processed_at,
        "failure_code": value.failure_code,
    }


def _job_data(value: BackgroundJob) -> dict[str, object]:
    return {
        "job_id": value.job_id,
        "workspace_id": value.workspace_id,
        "job_type": value.job_type.value,
        "status": value.status.value,
        "payload_safe": value.payload_safe,
        "attempt_count": value.attempt_count,
        "created_at": value.created_at,
        "started_at": value.started_at,
        "completed_at": value.completed_at,
        "next_attempt_at": value.next_attempt_at,
        "failure_code": value.failure_code,
        "failure_message_safe": value.failure_message_safe,
    }


def _contract_data(value: RepositoryContract) -> dict[str, object]:
    return {
        "contract_id": value.contract_id,
        "workspace_id": value.workspace_id,
        "repository_connection_id": value.repository_connection_id,
        "path": value.path,
        "contract_kind": value.contract_kind.value,
        "title": value.title,
        "version": value.version,
        "discovered_at": value.discovered_at,
        "updated_at": value.updated_at,
        "last_seen_commit": value.last_seen_commit,
        "enabled": value.enabled,
        "manually_configured": value.manually_configured,
    }


def _dependency_data(value: ApiDependency) -> dict[str, object]:
    return {
        "dependency_id": value.dependency_id,
        "workspace_id": value.workspace_id,
        "repository_connection_id": value.repository_connection_id,
        "evidence_type": value.evidence_type,
        "confidence": value.confidence,
        "created_at": value.created_at,
        "updated_at": value.updated_at,
        "contract_id": value.contract_id,
        "monitor_id": value.monitor_id,
        "source_path": value.source_path,
        "confirmed": value.confirmed,
    }


def _check_data(value: GitHubCheckRecord) -> dict[str, object]:
    return {
        "check_record_id": value.check_record_id,
        "workspace_id": value.workspace_id,
        "repository_connection_id": value.repository_connection_id,
        "logical_key": value.logical_key,
        "head_sha": value.head_sha,
        "name": value.name,
        "status": value.status.value,
        "created_at": value.created_at,
        "updated_at": value.updated_at,
        "github_check_run_id": value.github_check_run_id,
        "job_id": value.job_id,
        "analysis_id": value.analysis_id,
        "conclusion": value.conclusion.value if value.conclusion else None,
        "details_url": value.details_url,
        "summary": value.summary,
        "annotations": [
            {
                "path": item.path,
                "start_line": item.start_line,
                "end_line": item.end_line,
                "annotation_level": item.annotation_level,
                "message": item.message,
                "title": item.title,
            }
            for item in value.annotations
        ],
    }


def _delivery(data: dict[str, Any]) -> WebhookDelivery:
    return WebhookDelivery(
        str(data["delivery_id"]),
        str(data["github_delivery_id"]),
        str(data["event_type"]),
        data.get("action"),
        data.get("github_installation_id"),
        data.get("github_repository_id"),
        _datetime(data["received_at"]),
        WebhookDeliveryStatus(data["status"]),
        _optional_datetime(data.get("processed_at")),
        data.get("failure_code"),
    )


def _job(data: dict[str, Any]) -> BackgroundJob:
    return BackgroundJob(
        str(data["job_id"]),
        str(data["workspace_id"]),
        BackgroundJobType(data["job_type"]),
        BackgroundJobStatus(data["status"]),
        dict(data.get("payload_safe") or {}),
        int(data["attempt_count"]),
        _datetime(data["created_at"]),
        _optional_datetime(data.get("started_at")),
        _optional_datetime(data.get("completed_at")),
        _optional_datetime(data.get("next_attempt_at")),
        data.get("failure_code"),
        data.get("failure_message_safe"),
    )


def _contract(data: dict[str, Any]) -> RepositoryContract:
    return RepositoryContract(
        str(data["contract_id"]),
        str(data["workspace_id"]),
        str(data["repository_connection_id"]),
        str(data["path"]),
        ContractKind(data["contract_kind"]),
        str(data["title"]),
        str(data["version"]),
        _datetime(data["discovered_at"]),
        _datetime(data["updated_at"]),
        str(data["last_seen_commit"]),
        bool(data["enabled"]),
        bool(data.get("manually_configured", False)),
    )


def _dependency(data: dict[str, Any]) -> ApiDependency:
    return ApiDependency(
        str(data["dependency_id"]),
        str(data["workspace_id"]),
        str(data["repository_connection_id"]),
        str(data["evidence_type"]),
        float(data["confidence"]),
        _datetime(data["created_at"]),
        _datetime(data["updated_at"]),
        data.get("contract_id"),
        data.get("monitor_id"),
        data.get("source_path"),
        bool(data.get("confirmed", False)),
    )


def _check(data: dict[str, Any]) -> GitHubCheckRecord:
    annotations = tuple(CheckAnnotation(**item) for item in data.get("annotations", []))
    return GitHubCheckRecord(
        str(data["check_record_id"]),
        str(data["workspace_id"]),
        str(data["repository_connection_id"]),
        str(data["logical_key"]),
        str(data["head_sha"]),
        str(data["name"]),
        CheckRunStatus(data["status"]),
        _datetime(data["created_at"]),
        _datetime(data["updated_at"]),
        data.get("github_check_run_id"),
        data.get("job_id"),
        data.get("analysis_id"),
        CheckRunConclusion(data["conclusion"]) if data.get("conclusion") else None,
        data.get("details_url"),
        str(data.get("summary", "")),
        annotations,
    )


def _datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise TypeError("Expected a datetime-compatible Firestore value.")


def _optional_datetime(value: Any) -> datetime | None:
    return _datetime(value) if value is not None else None
