"""SQLite persistence for durable GitHub automation state."""
# ruff: noqa: E501

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

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

SCHEMA = """
CREATE TABLE IF NOT EXISTS github_webhook_deliveries (
    delivery_id TEXT PRIMARY KEY,
    github_delivery_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    action TEXT,
    github_installation_id INTEGER,
    github_repository_id INTEGER,
    received_at TEXT NOT NULL,
    status TEXT NOT NULL,
    processed_at TEXT,
    failure_code TEXT
);
CREATE TABLE IF NOT EXISTS background_jobs (
    job_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_safe_json TEXT NOT NULL,
    attempt_count INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    next_attempt_at TEXT,
    failure_code TEXT,
    failure_message_safe TEXT
);
CREATE TABLE IF NOT EXISTS repository_contracts (
    contract_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    repository_connection_id TEXT NOT NULL,
    path TEXT NOT NULL,
    contract_kind TEXT NOT NULL,
    title TEXT NOT NULL,
    version TEXT NOT NULL,
    discovered_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_seen_commit TEXT NOT NULL,
    enabled INTEGER NOT NULL CHECK(enabled IN (0, 1)),
    manually_configured INTEGER NOT NULL CHECK(manually_configured IN (0, 1)),
    UNIQUE(workspace_id, repository_connection_id, path)
);
CREATE TABLE IF NOT EXISTS api_dependencies (
    dependency_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    repository_connection_id TEXT NOT NULL,
    contract_id TEXT,
    monitor_id TEXT,
    evidence_type TEXT NOT NULL,
    confidence REAL NOT NULL,
    source_path TEXT,
    confirmed INTEGER NOT NULL CHECK(confirmed IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS github_check_records (
    check_record_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    repository_connection_id TEXT NOT NULL,
    logical_key TEXT NOT NULL,
    head_sha TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    github_check_run_id INTEGER,
    job_id TEXT,
    analysis_id TEXT,
    conclusion TEXT,
    details_url TEXT,
    summary TEXT NOT NULL,
    annotations_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(workspace_id, logical_key)
);
CREATE INDEX IF NOT EXISTS idx_jobs_due ON background_jobs(status, next_attempt_at, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_workspace ON background_jobs(workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_contracts_repository ON repository_contracts(workspace_id, repository_connection_id);
CREATE INDEX IF NOT EXISTS idx_dependencies_repository ON api_dependencies(workspace_id, repository_connection_id);
CREATE INDEX IF NOT EXISTS idx_checks_repository ON github_check_records(workspace_id, repository_connection_id, updated_at DESC);
"""


class SQLiteAutomationRepository(AutomationRepository):
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as connection:
            connection.executescript(SCHEMA)

    def create_delivery(self, delivery: WebhookDelivery) -> bool:
        try:
            with self._transaction() as connection:
                connection.execute(
                    "INSERT INTO github_webhook_deliveries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    _delivery_values(delivery),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def get_delivery(self, github_delivery_id: str) -> WebhookDelivery | None:
        return self._one(
            "SELECT * FROM github_webhook_deliveries WHERE github_delivery_id = ?",
            (github_delivery_id,),
            _delivery,
        )

    def get_delivery_by_id(self, delivery_id: str) -> WebhookDelivery | None:
        return self._one(
            "SELECT * FROM github_webhook_deliveries WHERE delivery_id = ?",
            (delivery_id,),
            _delivery,
        )

    def save_delivery(self, delivery: WebhookDelivery) -> None:
        with self._transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO github_webhook_deliveries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                _delivery_values(delivery),
            )

    def enqueue_job(self, job: BackgroundJob) -> BackgroundJob:
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO background_jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                _job_values(job),
            )
        return job

    def claim_due_jobs(self, now: datetime, limit: int = 10) -> list[BackgroundJob]:
        with self._transaction() as connection:
            rows = connection.execute(
                """SELECT * FROM background_jobs
                   WHERE status = ? OR (status = ? AND next_attempt_at <= ?)
                   ORDER BY created_at LIMIT ?""",
                (
                    BackgroundJobStatus.QUEUED.value,
                    BackgroundJobStatus.RETRY_SCHEDULED.value,
                    _iso(now),
                    limit,
                ),
            ).fetchall()
            ids = [row["job_id"] for row in rows]
            for job_id in ids:
                connection.execute(
                    """UPDATE background_jobs SET status = ?, started_at = ?,
                       next_attempt_at = NULL, attempt_count = attempt_count + 1
                       WHERE job_id = ?""",
                    (BackgroundJobStatus.RUNNING.value, _iso(now), job_id),
                )
            claimed = [
                connection.execute(
                    "SELECT * FROM background_jobs WHERE job_id = ?", (job_id,)
                ).fetchone()
                for job_id in ids
            ]
        return [_job(row) for row in claimed]

    def save_job(self, job: BackgroundJob) -> None:
        with self._transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO background_jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                _job_values(job),
            )

    def get_job(self, job_id: str, workspace_id: str | None = None) -> BackgroundJob | None:
        if workspace_id is None:
            return self._one("SELECT * FROM background_jobs WHERE job_id = ?", (job_id,), _job)
        return self._one(
            "SELECT * FROM background_jobs WHERE job_id = ? AND workspace_id = ?",
            (job_id, workspace_id),
            _job,
        )

    def list_jobs(self, workspace_id: str, limit: int = 50) -> list[BackgroundJob]:
        return self._many(
            "SELECT * FROM background_jobs WHERE workspace_id = ? ORDER BY created_at DESC LIMIT ?",
            (workspace_id, limit),
            _job,
        )

    def upsert_contract(self, contract: RepositoryContract) -> RepositoryContract:
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO repository_contracts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(workspace_id, repository_connection_id, path) DO UPDATE SET
                   contract_kind=excluded.contract_kind, title=excluded.title,
                   version=excluded.version, updated_at=excluded.updated_at,
                   last_seen_commit=excluded.last_seen_commit, enabled=excluded.enabled,
                   manually_configured=excluded.manually_configured""",
                _contract_values(contract),
            )
            row = connection.execute(
                """SELECT * FROM repository_contracts
                   WHERE workspace_id = ? AND repository_connection_id = ? AND path = ?""",
                (contract.workspace_id, contract.repository_connection_id, contract.path),
            ).fetchone()
        return _contract(row)

    def get_contract(self, contract_id: str) -> RepositoryContract | None:
        return self._one(
            "SELECT * FROM repository_contracts WHERE contract_id = ?", (contract_id,), _contract
        )

    def list_contracts(self, workspace_id: str, repository_id: str) -> list[RepositoryContract]:
        return self._many(
            """SELECT * FROM repository_contracts WHERE workspace_id = ?
               AND repository_connection_id = ? ORDER BY path""",
            (workspace_id, repository_id),
            _contract,
        )

    def save_dependency(self, dependency: ApiDependency) -> ApiDependency:
        with self._transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO api_dependencies VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                _dependency_values(dependency),
            )
        return dependency

    def list_dependencies(self, workspace_id: str, repository_id: str) -> list[ApiDependency]:
        return self._many(
            """SELECT * FROM api_dependencies WHERE workspace_id = ?
               AND repository_connection_id = ? ORDER BY confidence DESC, updated_at DESC""",
            (workspace_id, repository_id),
            _dependency,
        )

    def upsert_check(self, check: GitHubCheckRecord) -> GitHubCheckRecord:
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO github_check_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(workspace_id, logical_key) DO UPDATE SET
                   head_sha=excluded.head_sha, name=excluded.name, status=excluded.status,
                   github_check_run_id=excluded.github_check_run_id, job_id=excluded.job_id,
                   analysis_id=excluded.analysis_id, conclusion=excluded.conclusion,
                   details_url=excluded.details_url, summary=excluded.summary,
                   annotations_json=excluded.annotations_json, updated_at=excluded.updated_at""",
                _check_values(check),
            )
            row = connection.execute(
                "SELECT * FROM github_check_records WHERE workspace_id = ? AND logical_key = ?",
                (check.workspace_id, check.logical_key),
            ).fetchone()
        return _check(row)

    def get_check_by_logical_key(
        self, workspace_id: str, logical_key: str
    ) -> GitHubCheckRecord | None:
        return self._one(
            "SELECT * FROM github_check_records WHERE workspace_id = ? AND logical_key = ?",
            (workspace_id, logical_key),
            _check,
        )

    def list_checks(self, workspace_id: str, repository_id: str) -> list[GitHubCheckRecord]:
        return self._many(
            """SELECT * FROM github_check_records WHERE workspace_id = ?
               AND repository_connection_id = ? ORDER BY updated_at DESC""",
            (workspace_id, repository_id),
            _check,
        )

    def _one(self, sql: str, values: tuple[object, ...], mapper):
        with self._connect() as connection:
            row = connection.execute(sql, values).fetchone()
        return mapper(row) if row else None

    def _many(self, sql: str, values: tuple[object, ...], mapper):
        with self._connect() as connection:
            rows = connection.execute(sql, values).fetchall()
        return [mapper(row) for row in rows]

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def _delivery_values(value: WebhookDelivery) -> tuple[object, ...]:
    return (
        value.delivery_id,
        value.github_delivery_id,
        value.event_type,
        value.action,
        value.github_installation_id,
        value.github_repository_id,
        _iso(value.received_at),
        value.status.value,
        _iso(value.processed_at),
        value.failure_code,
    )


def _delivery(row: sqlite3.Row) -> WebhookDelivery:
    return WebhookDelivery(
        row["delivery_id"],
        row["github_delivery_id"],
        row["event_type"],
        row["action"],
        row["github_installation_id"],
        row["github_repository_id"],
        _dt(row["received_at"]),
        WebhookDeliveryStatus(row["status"]),
        _dt(row["processed_at"]),
        row["failure_code"],
    )


def _job_values(value: BackgroundJob) -> tuple[object, ...]:
    return (
        value.job_id,
        value.workspace_id,
        value.job_type.value,
        value.status.value,
        json.dumps(value.payload_safe, sort_keys=True, separators=(",", ":")),
        value.attempt_count,
        _iso(value.created_at),
        _iso(value.started_at),
        _iso(value.completed_at),
        _iso(value.next_attempt_at),
        value.failure_code,
        value.failure_message_safe,
    )


def _job(row: sqlite3.Row) -> BackgroundJob:
    return BackgroundJob(
        row["job_id"],
        row["workspace_id"],
        BackgroundJobType(row["job_type"]),
        BackgroundJobStatus(row["status"]),
        json.loads(row["payload_safe_json"]),
        row["attempt_count"],
        _dt(row["created_at"]),
        _dt(row["started_at"]),
        _dt(row["completed_at"]),
        _dt(row["next_attempt_at"]),
        row["failure_code"],
        row["failure_message_safe"],
    )


def _contract_values(value: RepositoryContract) -> tuple[object, ...]:
    return (
        value.contract_id,
        value.workspace_id,
        value.repository_connection_id,
        value.path,
        value.contract_kind.value,
        value.title,
        value.version,
        _iso(value.discovered_at),
        _iso(value.updated_at),
        value.last_seen_commit,
        int(value.enabled),
        int(value.manually_configured),
    )


def _contract(row: sqlite3.Row) -> RepositoryContract:
    return RepositoryContract(
        row["contract_id"],
        row["workspace_id"],
        row["repository_connection_id"],
        row["path"],
        ContractKind(row["contract_kind"]),
        row["title"],
        row["version"],
        _dt(row["discovered_at"]),
        _dt(row["updated_at"]),
        row["last_seen_commit"],
        bool(row["enabled"]),
        bool(row["manually_configured"]),
    )


def _dependency_values(value: ApiDependency) -> tuple[object, ...]:
    return (
        value.dependency_id,
        value.workspace_id,
        value.repository_connection_id,
        value.contract_id,
        value.monitor_id,
        value.evidence_type,
        value.confidence,
        value.source_path,
        int(value.confirmed),
        _iso(value.created_at),
        _iso(value.updated_at),
    )


def _dependency(row: sqlite3.Row) -> ApiDependency:
    return ApiDependency(
        row["dependency_id"],
        row["workspace_id"],
        row["repository_connection_id"],
        row["evidence_type"],
        row["confidence"],
        _dt(row["created_at"]),
        _dt(row["updated_at"]),
        row["contract_id"],
        row["monitor_id"],
        row["source_path"],
        bool(row["confirmed"]),
    )


def _check_values(value: GitHubCheckRecord) -> tuple[object, ...]:
    annotations = [
        {
            "path": item.path,
            "start_line": item.start_line,
            "end_line": item.end_line,
            "annotation_level": item.annotation_level,
            "message": item.message,
            "title": item.title,
        }
        for item in value.annotations
    ]
    return (
        value.check_record_id,
        value.workspace_id,
        value.repository_connection_id,
        value.logical_key,
        value.head_sha,
        value.name,
        value.status.value,
        value.github_check_run_id,
        value.job_id,
        value.analysis_id,
        value.conclusion.value if value.conclusion else None,
        value.details_url,
        value.summary,
        json.dumps(annotations, separators=(",", ":")),
        _iso(value.created_at),
        _iso(value.updated_at),
    )


def _check(row: sqlite3.Row) -> GitHubCheckRecord:
    annotations = tuple(CheckAnnotation(**item) for item in json.loads(row["annotations_json"]))
    return GitHubCheckRecord(
        row["check_record_id"],
        row["workspace_id"],
        row["repository_connection_id"],
        row["logical_key"],
        row["head_sha"],
        row["name"],
        CheckRunStatus(row["status"]),
        _dt(row["created_at"]),
        _dt(row["updated_at"]),
        row["github_check_run_id"],
        row["job_id"],
        row["analysis_id"],
        CheckRunConclusion(row["conclusion"]) if row["conclusion"] else None,
        row["details_url"],
        row["summary"],
        annotations,
    )
