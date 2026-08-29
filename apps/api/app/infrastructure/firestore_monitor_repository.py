"""Firestore monitor repository."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from google.cloud import firestore

from apps.api.app.core.workspace_context import (
    LOCAL_WORKSPACE_ID,
    current_workspace_id,
)
from apps.api.app.domain.monitor import ApiMonitor, MonitorCheckRecord, MonitorCheckStatus
from apps.api.app.ports.monitor_repository import ApiMonitorRepository

_MONITORS = "api_monitors"
_CHECKS = "checks"
_BASELINE_CHUNKS = "baseline_chunks"
_BASELINE_CHUNK_BYTES = 700_000


class FirestoreMonitorRepository(ApiMonitorRepository):
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
        self._monitors = self.client.collection(_MONITORS)

    def initialize(self) -> None:
        """Firestore is schemaless."""

    def create(self, monitor: ApiMonitor) -> None:
        self._write_monitor(monitor, create=True)

    def save(self, monitor: ApiMonitor) -> None:
        self._write_monitor(monitor)

    def get(self, monitor_id: str) -> ApiMonitor | None:
        snapshot = self._monitors.document(monitor_id).get()
        if not snapshot.exists:
            return None
        data = snapshot.to_dict() or {}
        if data.get("workspace_id", LOCAL_WORKSPACE_ID) != current_workspace_id():
            return None
        return _monitor(
            snapshot.to_dict() or {},
            _baseline_content(snapshot.reference),
        )

    def list(self) -> list[ApiMonitor]:
        query = self._monitors.order_by(
            "created_at",
            direction=firestore.Query.DESCENDING,
        )
        workspace_id = current_workspace_id()
        return [
            _monitor(
                snapshot.to_dict() or {},
                _baseline_content(snapshot.reference),
            )
            for snapshot in query.stream()
            if (snapshot.to_dict() or {}).get("workspace_id", LOCAL_WORKSPACE_ID) == workspace_id
        ]

    def list_due(self, now: datetime) -> list[ApiMonitor]:
        return [
            monitor
            for monitor in self.list()
            if monitor.enabled
            and (monitor.last_checked_at or monitor.created_at)
            + timedelta(minutes=monitor.check_interval_minutes)
            <= now
        ]

    def delete(self, monitor_id: str) -> bool:
        reference = self._monitors.document(monitor_id)
        snapshot = reference.get()
        if (
            not snapshot.exists
            or (snapshot.to_dict() or {}).get("workspace_id", LOCAL_WORKSPACE_ID)
            != current_workspace_id()
        ):
            return False
        self.client.recursive_delete(reference)
        return True

    def start_check(self, monitor: ApiMonitor, check: MonitorCheckRecord) -> None:
        reference = self._monitors.document(monitor.monitor_id)
        batch = self.client.batch()
        batch.set(reference.collection(_CHECKS).document(check.check_id), _check_data(check))
        batch.set(reference, _monitor_data(monitor))
        batch.commit()

    def finish_check(self, monitor: ApiMonitor, check: MonitorCheckRecord) -> None:
        reference = self._monitors.document(monitor.monitor_id)
        existing_chunks = list(reference.collection(_BASELINE_CHUNKS).stream())
        batch = self.client.batch()
        batch.set(reference.collection(_CHECKS).document(check.check_id), _check_data(check))
        batch.set(reference, _monitor_data(monitor))
        for snapshot in existing_chunks:
            batch.delete(snapshot.reference)
        for ordinal, content in enumerate(_chunks(monitor.baseline_content)):
            batch.set(
                reference.collection(_BASELINE_CHUNKS).document(f"{ordinal:04d}"),
                {"ordinal": ordinal, "content": content},
            )
        batch.commit()

    def list_checks(self, monitor_id: str) -> list[MonitorCheckRecord]:
        query = (
            self._monitors.document(monitor_id)
            .collection(_CHECKS)
            .order_by("checked_at", direction=firestore.Query.DESCENDING)
        )
        return [_check(snapshot.to_dict() or {}) for snapshot in query.stream()]

    def _write_monitor(self, monitor: ApiMonitor, *, create: bool = False) -> None:
        reference = self._monitors.document(monitor.monitor_id)
        existing_chunks = [] if create else list(reference.collection(_BASELINE_CHUNKS).stream())
        batch = self.client.batch()
        if create:
            batch.create(reference, _monitor_data(monitor))
        else:
            batch.set(reference, _monitor_data(monitor))
        for snapshot in existing_chunks:
            batch.delete(snapshot.reference)
        for ordinal, content in enumerate(_chunks(monitor.baseline_content)):
            batch.set(
                reference.collection(_BASELINE_CHUNKS).document(f"{ordinal:04d}"),
                {"ordinal": ordinal, "content": content},
            )
        batch.commit()


def _monitor_data(monitor: ApiMonitor) -> dict[str, Any]:
    return {
        "monitor_id": monitor.monitor_id,
        "workspace_id": current_workspace_id(),
        "name": monitor.name,
        "specification_url": monitor.specification_url,
        "repository_url": monitor.repository_url,
        "repository_ref": monitor.repository_ref,
        "check_interval_minutes": monitor.check_interval_minutes,
        "enabled": monitor.enabled,
        "baseline_filename": monitor.baseline_filename,
        "baseline_sha256": monitor.baseline_sha256,
        "baseline_chunk_count": len(tuple(_chunks(monitor.baseline_content))),
        "baseline_observed_at": monitor.baseline_observed_at,
        "created_at": monitor.created_at,
        "updated_at": monitor.updated_at,
        "last_checked_at": monitor.last_checked_at,
        "last_changed_at": monitor.last_changed_at,
        "last_successful_analysis_id": monitor.last_successful_analysis_id,
        "last_check_status": (
            monitor.last_check_status.value if monitor.last_check_status else None
        ),
        "last_error_code": monitor.last_error_code,
        "last_error_message": monitor.last_error_message,
    }


def _check_data(check: MonitorCheckRecord) -> dict[str, Any]:
    return {
        "check_id": check.check_id,
        "monitor_id": check.monitor_id,
        "status": check.status.value,
        "checked_at": check.checked_at,
        "completed_at": check.completed_at,
        "duration_ms": check.duration_ms,
        "previous_spec_hash": check.previous_spec_hash,
        "observed_spec_hash": check.observed_spec_hash,
        "analysis_id": check.analysis_id,
        "error_code": check.error_code,
        "error_message": check.error_message,
    }


def _monitor(data: dict[str, Any], baseline_content: bytes) -> ApiMonitor:
    return ApiMonitor(
        monitor_id=str(data["monitor_id"]),
        name=str(data["name"]),
        specification_url=str(data["specification_url"]),
        repository_url=str(data["repository_url"]),
        repository_ref=data.get("repository_ref"),
        check_interval_minutes=int(data["check_interval_minutes"]),
        enabled=bool(data["enabled"]),
        baseline_filename=str(data["baseline_filename"]),
        baseline_content=baseline_content,
        baseline_sha256=str(data["baseline_sha256"]),
        baseline_observed_at=_datetime(data["baseline_observed_at"]),
        created_at=_datetime(data["created_at"]),
        updated_at=_datetime(data["updated_at"]),
        last_checked_at=_optional_datetime(data.get("last_checked_at")),
        last_changed_at=_optional_datetime(data.get("last_changed_at")),
        last_successful_analysis_id=data.get("last_successful_analysis_id"),
        last_check_status=(
            MonitorCheckStatus(data["last_check_status"]) if data.get("last_check_status") else None
        ),
        last_error_code=data.get("last_error_code"),
        last_error_message=data.get("last_error_message"),
    )


def _check(data: dict[str, Any]) -> MonitorCheckRecord:
    return MonitorCheckRecord(
        check_id=str(data["check_id"]),
        monitor_id=str(data["monitor_id"]),
        status=MonitorCheckStatus(data["status"]),
        checked_at=_datetime(data["checked_at"]),
        completed_at=_optional_datetime(data.get("completed_at")),
        duration_ms=data.get("duration_ms"),
        previous_spec_hash=str(data["previous_spec_hash"]),
        observed_spec_hash=data.get("observed_spec_hash"),
        analysis_id=data.get("analysis_id"),
        error_code=data.get("error_code"),
        error_message=data.get("error_message"),
    )


def _datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise TypeError("Expected a datetime-compatible Firestore value.")


def _optional_datetime(value: Any) -> datetime | None:
    return _datetime(value) if value is not None else None


def _chunks(content: bytes) -> tuple[bytes, ...]:
    return tuple(
        content[offset : offset + _BASELINE_CHUNK_BYTES]
        for offset in range(0, len(content), _BASELINE_CHUNK_BYTES)
    )


def _baseline_content(reference: Any) -> bytes:
    query = reference.collection(_BASELINE_CHUNKS).order_by("ordinal")
    return b"".join(bytes((snapshot.to_dict() or {})["content"]) for snapshot in query.stream())
