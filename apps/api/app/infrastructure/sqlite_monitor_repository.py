"""SQLite monitor repository."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from apps.api.app.core.workspace_context import (
    LOCAL_WORKSPACE_ID,
    current_workspace_id,
)
from apps.api.app.domain.monitor import ApiMonitor, MonitorCheckRecord, MonitorCheckStatus
from apps.api.app.ports.monitor_repository import ApiMonitorRepository

SCHEMA = """
CREATE TABLE IF NOT EXISTS api_monitors (
    monitor_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    name TEXT NOT NULL,
    specification_url TEXT NOT NULL,
    repository_url TEXT NOT NULL,
    repository_ref TEXT,
    check_interval_minutes INTEGER NOT NULL CHECK (check_interval_minutes > 0),
    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    baseline_filename TEXT NOT NULL,
    baseline_content BLOB NOT NULL,
    baseline_sha256 TEXT NOT NULL CHECK (length(baseline_sha256) = 64),
    baseline_observed_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_checked_at TEXT,
    last_changed_at TEXT,
    last_successful_analysis_id TEXT,
    last_check_status TEXT CHECK (
        last_check_status IS NULL OR
        last_check_status IN ('checking', 'unchanged', 'changed', 'failed')
    ),
    last_error_code TEXT,
    last_error_message TEXT,
    FOREIGN KEY (last_successful_analysis_id)
        REFERENCES analyses(analysis_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS monitor_checks (
    check_id TEXT PRIMARY KEY,
    monitor_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('checking', 'unchanged', 'changed', 'failed')),
    checked_at TEXT NOT NULL,
    completed_at TEXT,
    duration_ms INTEGER,
    previous_spec_hash TEXT NOT NULL CHECK (length(previous_spec_hash) = 64),
    observed_spec_hash TEXT CHECK (
        observed_spec_hash IS NULL OR length(observed_spec_hash) = 64
    ),
    analysis_id TEXT,
    error_code TEXT,
    error_message TEXT,
    FOREIGN KEY (monitor_id) REFERENCES api_monitors(monitor_id) ON DELETE CASCADE,
    FOREIGN KEY (analysis_id) REFERENCES analyses(analysis_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_monitor_checks_monitor_time
ON monitor_checks(monitor_id, checked_at DESC);
"""


class SQLiteMonitorRepository(ApiMonitorRepository):
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            _ensure_workspace_column(connection)

    def create(self, monitor: ApiMonitor) -> None:
        with self._transaction() as connection:
            connection.execute(
                f"INSERT INTO api_monitors (workspace_id, {_MONITOR_COLUMNS}) "
                f"VALUES (?, {_MONITOR_MARKERS})",
                (current_workspace_id(), *_monitor_values(monitor)),
            )

    def save(self, monitor: ApiMonitor) -> None:
        with self._transaction() as connection:
            self._update_monitor(connection, monitor)

    def get(self, monitor_id: str) -> ApiMonitor | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM api_monitors WHERE monitor_id = ? AND workspace_id = ?",
                (monitor_id, current_workspace_id()),
            ).fetchone()
        return _monitor(row) if row is not None else None

    def list(self) -> list[ApiMonitor]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM api_monitors WHERE workspace_id = ? ORDER BY created_at DESC",
                (current_workspace_id(),),
            ).fetchall()
        return [_monitor(row) for row in rows]

    def list_due(self, now: datetime) -> list[ApiMonitor]:
        return [
            monitor
            for monitor in self.list()
            if monitor.enabled
            and (monitor.last_checked_at or monitor.created_at)
            + timedelta(minutes=monitor.check_interval_minutes)
            <= now
        ]

    def list_due_all(self, now: datetime) -> list[tuple[str, ApiMonitor]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM api_monitors WHERE enabled = 1 ORDER BY created_at"
            ).fetchall()
        result = []
        for row in rows:
            monitor = _monitor(row)
            if (monitor.last_checked_at or monitor.created_at) + timedelta(
                minutes=monitor.check_interval_minutes
            ) <= now:
                result.append((str(row["workspace_id"]), monitor))
        return result

    def delete(self, monitor_id: str) -> bool:
        with self._transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM api_monitors WHERE monitor_id = ? AND workspace_id = ?",
                (monitor_id, current_workspace_id()),
            )
        return cursor.rowcount > 0

    def start_check(self, monitor: ApiMonitor, check: MonitorCheckRecord) -> None:
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO monitor_checks (
                    check_id, monitor_id, status, checked_at, completed_at, duration_ms,
                    previous_spec_hash, observed_spec_hash, analysis_id,
                    error_code, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _check_values(check),
            )
            self._update_monitor(connection, monitor)

    def finish_check(self, monitor: ApiMonitor, check: MonitorCheckRecord) -> None:
        with self._transaction() as connection:
            connection.execute(
                """
                UPDATE monitor_checks SET
                    status = ?, completed_at = ?, duration_ms = ?,
                    observed_spec_hash = ?, analysis_id = ?,
                    error_code = ?, error_message = ?
                WHERE check_id = ?
                """,
                (
                    check.status.value,
                    _iso(check.completed_at),
                    check.duration_ms,
                    check.observed_spec_hash,
                    check.analysis_id,
                    check.error_code,
                    check.error_message,
                    check.check_id,
                ),
            )
            self._update_monitor(connection, monitor)

    def list_checks(self, monitor_id: str) -> list[MonitorCheckRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM monitor_checks
                WHERE monitor_id = ?
                ORDER BY checked_at DESC
                """,
                (monitor_id,),
            ).fetchall()
        return [_check(row) for row in rows]

    @staticmethod
    def _update_monitor(
        connection: sqlite3.Connection,
        monitor: ApiMonitor,
    ) -> None:
        assignments = ", ".join(
            f"{column} = ?" for column in _MONITOR_COLUMN_NAMES if column != "monitor_id"
        )
        values = _monitor_values(monitor)
        connection.execute(
            f"UPDATE api_monitors SET {assignments} WHERE monitor_id = ? AND workspace_id = ?",
            (*values[1:], monitor.monitor_id, current_workspace_id()),
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise


_MONITOR_COLUMN_NAMES = (
    "monitor_id",
    "name",
    "specification_url",
    "repository_url",
    "repository_ref",
    "check_interval_minutes",
    "enabled",
    "baseline_filename",
    "baseline_content",
    "baseline_sha256",
    "baseline_observed_at",
    "created_at",
    "updated_at",
    "last_checked_at",
    "last_changed_at",
    "last_successful_analysis_id",
    "last_check_status",
    "last_error_code",
    "last_error_message",
)
_MONITOR_COLUMNS = ", ".join(_MONITOR_COLUMN_NAMES)
_MONITOR_MARKERS = ", ".join("?" for _ in _MONITOR_COLUMN_NAMES)


def _monitor_values(monitor: ApiMonitor) -> tuple[object, ...]:
    return (
        monitor.monitor_id,
        monitor.name,
        monitor.specification_url,
        monitor.repository_url,
        monitor.repository_ref,
        monitor.check_interval_minutes,
        int(monitor.enabled),
        monitor.baseline_filename,
        monitor.baseline_content,
        monitor.baseline_sha256,
        _iso(monitor.baseline_observed_at),
        _iso(monitor.created_at),
        _iso(monitor.updated_at),
        _iso(monitor.last_checked_at),
        _iso(monitor.last_changed_at),
        monitor.last_successful_analysis_id,
        monitor.last_check_status.value if monitor.last_check_status else None,
        monitor.last_error_code,
        monitor.last_error_message,
    )


def _check_values(check: MonitorCheckRecord) -> tuple[object, ...]:
    return (
        check.check_id,
        check.monitor_id,
        check.status.value,
        _iso(check.checked_at),
        _iso(check.completed_at),
        check.duration_ms,
        check.previous_spec_hash,
        check.observed_spec_hash,
        check.analysis_id,
        check.error_code,
        check.error_message,
    )


def _monitor(row: sqlite3.Row) -> ApiMonitor:
    return ApiMonitor(
        monitor_id=row["monitor_id"],
        name=row["name"],
        specification_url=row["specification_url"],
        repository_url=row["repository_url"],
        repository_ref=row["repository_ref"],
        check_interval_minutes=row["check_interval_minutes"],
        enabled=bool(row["enabled"]),
        baseline_filename=row["baseline_filename"],
        baseline_content=bytes(row["baseline_content"]),
        baseline_sha256=row["baseline_sha256"],
        baseline_observed_at=_datetime(row["baseline_observed_at"]),
        created_at=_datetime(row["created_at"]),
        updated_at=_datetime(row["updated_at"]),
        last_checked_at=_optional_datetime(row["last_checked_at"]),
        last_changed_at=_optional_datetime(row["last_changed_at"]),
        last_successful_analysis_id=row["last_successful_analysis_id"],
        last_check_status=(
            MonitorCheckStatus(row["last_check_status"]) if row["last_check_status"] else None
        ),
        last_error_code=row["last_error_code"],
        last_error_message=row["last_error_message"],
    )


def _check(row: sqlite3.Row) -> MonitorCheckRecord:
    return MonitorCheckRecord(
        check_id=row["check_id"],
        monitor_id=row["monitor_id"],
        status=MonitorCheckStatus(row["status"]),
        checked_at=_datetime(row["checked_at"]),
        completed_at=_optional_datetime(row["completed_at"]),
        duration_ms=row["duration_ms"],
        previous_spec_hash=row["previous_spec_hash"],
        observed_spec_hash=row["observed_spec_hash"],
        analysis_id=row["analysis_id"],
        error_code=row["error_code"],
        error_message=row["error_message"],
    )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _optional_datetime(value: str | None) -> datetime | None:
    return _datetime(value) if value else None


def _ensure_workspace_column(connection: sqlite3.Connection) -> None:
    columns = {row[1] for row in connection.execute("PRAGMA table_info(api_monitors)")}
    if "workspace_id" not in columns:
        connection.execute(
            "ALTER TABLE api_monitors ADD COLUMN workspace_id TEXT NOT NULL "
            f"DEFAULT '{LOCAL_WORKSPACE_ID}'"
        )
    connection.execute(
        "UPDATE api_monitors SET workspace_id = ? WHERE workspace_id IS NULL OR workspace_id = ''",
        (LOCAL_WORKSPACE_ID,),
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_api_monitors_workspace "
        "ON api_monitors(workspace_id, created_at DESC)"
    )
