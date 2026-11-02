"""SQLite implementation of the analysis repository port."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from apps.api.app.core.redaction import redact_secrets
from apps.api.app.core.workspace_context import (
    LOCAL_WORKSPACE_ID,
    current_workspace_id,
)
from apps.api.app.domain.analysis import (
    AnalysisCreation,
    AnalysisKind,
    AnalysisRecord,
    AnalysisStatus,
    AnalysisSubmission,
    FailureRecord,
    PipelineStageRecord,
    PipelineStageStatus,
    RepositorySourceType,
    StoredMatch,
)
from apps.api.app.ports.analysis_repository import AnalysisRepository
from apps.api.app.schemas.comparison import ApiChange, ComparisonResponse
from apps.api.app.schemas.impact import (
    ChangeImpact,
    ImpactSummary,
    RepositoryScanSummary,
)
from apps.api.app.schemas.migration import MigrationRecommendation
from apps.api.app.schemas.patch import PatchProposal
from apps.api.app.schemas.pull_request import GitHubPullRequestRecord
from apps.api.app.schemas.risk import RiskPrediction
from apps.api.app.schemas.validation import PatchValidationRun

SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    analysis_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    kind TEXT NOT NULL CHECK (kind IN ('comparison', 'impact')),
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    request_fingerprint TEXT NOT NULL UNIQUE CHECK (length(request_fingerprint) = 64),
    old_filename TEXT NOT NULL,
    new_filename TEXT NOT NULL,
    repository_filename TEXT,
    old_file_sha256 TEXT NOT NULL CHECK (length(old_file_sha256) = 64),
    new_file_sha256 TEXT NOT NULL CHECK (length(new_file_sha256) = 64),
    repository_file_sha256 TEXT CHECK (
        repository_file_sha256 IS NULL OR length(repository_file_sha256) = 64
    ),
    repository_source_type TEXT CHECK (
        repository_source_type IS NULL OR repository_source_type IN ('zip', 'github')
    ),
    repository_url TEXT,
    repository_ref TEXT,
    repository_commit_sha TEXT CHECK (
        repository_commit_sha IS NULL OR length(repository_commit_sha) = 40
    ),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    old_contract_json TEXT,
    new_contract_json TEXT,
    comparison_summary_json TEXT,
    repository_summary_json TEXT,
    impact_summary_json TEXT
);

CREATE TABLE IF NOT EXISTS analysis_changes (
    change_row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    change_id TEXT NOT NULL,
    change_type TEXT NOT NULL,
    path TEXT NOT NULL,
    method TEXT NOT NULL,
    subject TEXT,
    old_value_json TEXT,
    new_value_json TEXT,
    breaking INTEGER NOT NULL CHECK (breaking IN (0, 1)),
    category TEXT NOT NULL,
    severity TEXT NOT NULL,
    explanation TEXT NOT NULL,
    contract_type TEXT NOT NULL DEFAULT 'openapi',
    operation_kind TEXT NOT NULL DEFAULT 'http_operation',
    operation_identifier TEXT,
    contract_location TEXT,
    old_type TEXT,
    new_type TEXT,
    old_required INTEGER,
    new_required INTEGER,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (analysis_id, ordinal),
    UNIQUE (analysis_id, change_id),
    FOREIGN KEY (analysis_id) REFERENCES analyses(analysis_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS repository_matches (
    match_id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id TEXT NOT NULL,
    change_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    line INTEGER NOT NULL CHECK (line > 0),
    column_number INTEGER NOT NULL CHECK (column_number > 0),
    match_kind TEXT NOT NULL,
    confidence TEXT NOT NULL,
    evidence TEXT NOT NULL CHECK (length(evidence) <= 240),
    symbol TEXT,
    language TEXT,
    impact_depth INTEGER NOT NULL DEFAULT 0 CHECK (impact_depth >= 0),
    analysis_kind TEXT NOT NULL DEFAULT 'lexical',
    trace_json TEXT NOT NULL DEFAULT '[]',
    UNIQUE (analysis_id, change_id, ordinal),
    FOREIGN KEY (analysis_id, change_id)
        REFERENCES analysis_changes(analysis_id, change_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS risk_predictions (
    prediction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id TEXT NOT NULL,
    change_id TEXT NOT NULL,
    risk_level TEXT NOT NULL CHECK (risk_level IN ('low', 'medium', 'high', 'critical')),
    risk_score REAL NOT NULL CHECK (risk_score >= 0 AND risk_score <= 100),
    prediction_source TEXT NOT NULL CHECK (
        prediction_source IN ('model', 'deterministic_fallback')
    ),
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL,
    baseline_level TEXT NOT NULL CHECK (
        baseline_level IN ('low', 'medium', 'high', 'critical')
    ),
    baseline_score REAL NOT NULL CHECK (baseline_score >= 0 AND baseline_score <= 100),
    class_probabilities_json TEXT NOT NULL,
    features_json TEXT NOT NULL,
    reasons_json TEXT NOT NULL,
    top_drivers_json TEXT NOT NULL,
    fallback_reason TEXT,
    predicted_at TEXT NOT NULL,
    UNIQUE (analysis_id, change_id),
    FOREIGN KEY (analysis_id, change_id)
        REFERENCES analysis_changes(analysis_id, change_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS migration_recommendations (
    recommendation_id TEXT PRIMARY KEY,
    analysis_id TEXT NOT NULL,
    change_id TEXT NOT NULL,
    provider TEXT NOT NULL CHECK (
        provider IN ('mock', 'gemini', 'deterministic')
    ),
    provider_model TEXT NOT NULL,
    recommendation_source TEXT NOT NULL CHECK (
        recommendation_source IN (
            'mock',
            'gemini',
            'deterministic_fallback'
        )
    ),
    recommendation_source_actual TEXT,
    prompt_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    summary TEXT NOT NULL CHECK (length(summary) <= 500),
    why_it_matters TEXT NOT NULL CHECK (length(why_it_matters) <= 1000),
    affected_code_explanation TEXT NOT NULL CHECK (
        length(affected_code_explanation) <= 1000
    ),
    migration_steps_json TEXT NOT NULL,
    suggested_tests_json TEXT NOT NULL,
    code_example TEXT NOT NULL CHECK (length(code_example) <= 2000),
    assumptions_json TEXT NOT NULL,
    warnings_json TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (
        confidence >= 0 AND confidence <= 1
    ),
    provider_warning TEXT CHECK (
        provider_warning IS NULL
        OR length(provider_warning) <= 500
    ),
    redactions_applied INTEGER NOT NULL CHECK (
        redactions_applied >= 0
    ),
    generated_at TEXT NOT NULL,
    UNIQUE (
        analysis_id,
        change_id,
        prompt_version,
        schema_version,
        provider_model
    ),
    FOREIGN KEY (analysis_id, change_id)
        REFERENCES analysis_changes(analysis_id, change_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS pipeline_stages (
    stage_id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
    error_code TEXT,
    error_message TEXT,
    UNIQUE (analysis_id, ordinal),
    FOREIGN KEY (analysis_id) REFERENCES analyses(analysis_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS analysis_failures (
    failure_id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    error_code TEXT NOT NULL,
    safe_message TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (analysis_id) REFERENCES analyses(analysis_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS patch_proposals (
    patch_id TEXT PRIMARY KEY,
    analysis_id TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL UNIQUE CHECK (length(request_fingerprint) = 64),
    created_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status = 'validated'),
    summary TEXT NOT NULL CHECK (length(summary) <= 500),
    provider TEXT NOT NULL CHECK (provider IN ('mock', 'gemini')),
    provider_actual TEXT,
    provider_model TEXT NOT NULL,
    provider_mode TEXT NOT NULL CHECK (
        provider_mode IN ('deterministic_mock', 'external')
    ),
    provider_mode_actual TEXT,
    patch_profile_version TEXT NOT NULL,
    source_repository_hash TEXT NOT NULL CHECK (length(source_repository_hash) = 64),
    files_changed INTEGER NOT NULL CHECK (files_changed > 0),
    edit_count INTEGER NOT NULL CHECK (edit_count > 0),
    validation_json TEXT NOT NULL,
    warnings_json TEXT NOT NULL,
    unified_diff TEXT NOT NULL,
    files_json TEXT NOT NULL,
    redactions_applied INTEGER NOT NULL CHECK (redactions_applied >= 0),
    FOREIGN KEY (analysis_id) REFERENCES analyses(analysis_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS patch_validation_runs (
    validation_id TEXT PRIMARY KEY,
    patch_id TEXT NOT NULL,
    analysis_id TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL UNIQUE CHECK (length(request_fingerprint) = 64),
    created_at TEXT NOT NULL,
    validation_profile_version TEXT NOT NULL,
    readiness TEXT NOT NULL CHECK (
        readiness IN ('ready_for_review', 'needs_review', 'blocked')
    ),
    source_repository_hash TEXT NOT NULL CHECK (length(source_repository_hash) = 64),
    validation_json TEXT NOT NULL,
    FOREIGN KEY (patch_id) REFERENCES patch_proposals(patch_id) ON DELETE CASCADE,
    FOREIGN KEY (analysis_id) REFERENCES analyses(analysis_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS github_pull_request_records (
    pr_record_id TEXT PRIMARY KEY,
    analysis_id TEXT NOT NULL,
    patch_id TEXT NOT NULL,
    validation_id TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL UNIQUE CHECK (length(request_fingerprint) = 64),
    status TEXT NOT NULL CHECK (status IN ('preparing', 'created', 'failed')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    record_json TEXT NOT NULL,
    FOREIGN KEY (analysis_id) REFERENCES analyses(analysis_id) ON DELETE CASCADE,
    FOREIGN KEY (patch_id) REFERENCES patch_proposals(patch_id) ON DELETE CASCADE,
    FOREIGN KEY (validation_id) REFERENCES patch_validation_runs(validation_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_analyses_created_at ON analyses(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_changes_analysis ON analysis_changes(analysis_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_matches_analysis ON repository_matches(analysis_id, match_id);
CREATE INDEX IF NOT EXISTS idx_risks_analysis ON risk_predictions(analysis_id, prediction_id);
CREATE INDEX IF NOT EXISTS idx_migrations_analysis
    ON migration_recommendations(analysis_id, generated_at);
CREATE INDEX IF NOT EXISTS idx_pipeline_analysis ON pipeline_stages(analysis_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_failures_analysis ON analysis_failures(analysis_id, failure_id);
CREATE INDEX IF NOT EXISTS idx_patches_analysis
    ON patch_proposals(analysis_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_patch_validations_patch
    ON patch_validation_runs(analysis_id, patch_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pull_requests_analysis
    ON github_pull_request_records(analysis_id, created_at DESC);
"""


class SQLiteAnalysisRepository(AnalysisRepository):
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            connection.execute(
                "CREATE TABLE IF NOT EXISTS analysis_contract_sources ("
                "analysis_id TEXT PRIMARY KEY REFERENCES analyses(analysis_id) ON DELETE CASCADE,"
                "old_content BLOB NOT NULL, new_content BLOB NOT NULL)"
            )
            _ensure_analysis_source_columns(connection)
            _ensure_analysis_change_columns(connection)
            _ensure_repository_match_columns(connection)
            _ensure_analysis_workspace_column(connection)
            _ensure_phase22_provider_columns(connection)
            connection.commit()

    def save_contract_sources(self, analysis_id: str, old: bytes, new: bytes) -> None:
        from apps.api.app.contracts.snapshots import verify_sources

        verify_sources(self.get_analysis(analysis_id), old, new)
        with self._transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO analysis_contract_sources VALUES (?, ?, ?)",
                (analysis_id, old, new),
            )

    def get_contract_sources(self, analysis_id: str) -> tuple[bytes, bytes] | None:
        from apps.api.app.contracts.snapshots import verify_sources

        analysis = self.get_analysis(analysis_id)
        if analysis is None:
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT old_content, new_content FROM analysis_contract_sources "
                "WHERE analysis_id=?",
                (analysis_id,),
            ).fetchone()
        if row is None:
            return None
        result = bytes(row[0]), bytes(row[1])
        verify_sources(analysis, *result)
        return result

    def create_or_get(self, submission: AnalysisSubmission) -> AnalysisCreation:
        workspace_id = current_workspace_id()
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM analyses WHERE request_fingerprint = ? AND workspace_id = ?",
                (submission.request_fingerprint, workspace_id),
            ).fetchone()
            if existing is not None:
                return AnalysisCreation(analysis=_analysis_record(existing), duplicate=True)

            analysis_id = str(uuid4())
            timestamp = _timestamp(submission.created_at)
            connection.execute(
                """
                INSERT INTO analyses (
                    analysis_id, workspace_id, kind, status, request_fingerprint,
                    old_filename, new_filename, repository_filename,
                    old_file_sha256, new_file_sha256, repository_file_sha256,
                    repository_source_type, repository_url, repository_ref,
                    repository_commit_sha,
                    created_at, updated_at
                ) VALUES (?, ?, ?, 'running', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    analysis_id,
                    workspace_id,
                    submission.kind.value,
                    submission.request_fingerprint,
                    submission.old_filename,
                    submission.new_filename,
                    submission.repository_filename,
                    submission.old_file_sha256,
                    submission.new_file_sha256,
                    submission.repository_file_sha256,
                    (
                        submission.repository_source_type.value
                        if submission.repository_source_type
                        else None
                    ),
                    submission.repository_url,
                    submission.repository_ref,
                    submission.repository_commit_sha,
                    timestamp,
                    timestamp,
                ),
            )
            created = connection.execute(
                "SELECT * FROM analyses WHERE analysis_id = ? AND workspace_id = ?",
                (analysis_id, workspace_id),
            ).fetchone()
            return AnalysisCreation(analysis=_analysis_record(created), duplicate=False)

    def start_stage(
        self,
        analysis_id: str,
        stage_name: str,
        ordinal: int,
        started_at: datetime,
    ) -> int:
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO pipeline_stages (
                    analysis_id, stage_name, ordinal, status, started_at
                ) VALUES (?, ?, ?, 'running', ?)
                """,
                (analysis_id, stage_name, ordinal, _timestamp(started_at)),
            )
            connection.execute(
                "UPDATE analyses SET updated_at = ? WHERE analysis_id = ?",
                (_timestamp(started_at), analysis_id),
            )
            return int(cursor.lastrowid)

    def complete_stage(self, stage_id: int, completed_at: datetime, duration_ms: int) -> None:
        with self._transaction() as connection:
            connection.execute(
                """
                UPDATE pipeline_stages
                SET status = 'succeeded', completed_at = ?, duration_ms = ?
                WHERE stage_id = ? AND status = 'running'
                """,
                (_timestamp(completed_at), duration_ms, stage_id),
            )

    def fail_analysis(
        self,
        *,
        analysis_id: str,
        stage_id: int,
        stage_name: str,
        error_code: str,
        safe_message: str,
        status_code: int,
        failed_at: datetime,
        duration_ms: int,
    ) -> None:
        safe_code = error_code[:100]
        safe_text = safe_message[:500]
        timestamp = _timestamp(failed_at)
        with self._transaction() as connection:
            connection.execute(
                """
                UPDATE pipeline_stages
                SET status = 'failed', completed_at = ?, duration_ms = ?,
                    error_code = ?, error_message = ?
                WHERE stage_id = ?
                """,
                (timestamp, duration_ms, safe_code, safe_text, stage_id),
            )
            connection.execute(
                """
                UPDATE analyses
                SET status = 'failed', updated_at = ?, completed_at = ?
                WHERE analysis_id = ?
                """,
                (timestamp, timestamp, analysis_id),
            )
            connection.execute(
                """
                INSERT INTO analysis_failures (
                    analysis_id, stage_name, error_code, safe_message,
                    status_code, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    analysis_id,
                    stage_name,
                    safe_code,
                    safe_text,
                    status_code,
                    timestamp,
                ),
            )

    def save_success(
        self,
        *,
        analysis_id: str,
        comparison: ComparisonResponse,
        repository_summary: RepositoryScanSummary | None,
        impact_summary: ImpactSummary | None,
        impacts: list[ChangeImpact],
        risk_predictions: list[RiskPrediction],
        migration_recommendations: list[MigrationRecommendation],
        stage_id: int,
        completed_at: datetime,
        duration_ms: int,
    ) -> None:
        timestamp = _timestamp(completed_at)
        with self._transaction() as connection:
            # A long-running development process may hold a repository instance that
            # predates the additive Phase 22 migration. Keep the affected writes
            # self-healing without changing legacy CHECK constraints or stored data.
            _ensure_phase22_provider_columns(connection)
            for ordinal, change in enumerate(comparison.changes, start=1):
                connection.execute(
                    """
                    INSERT INTO analysis_changes (
                        analysis_id, ordinal, change_id, change_type, path, method,
                        subject, old_value_json, new_value_json, breaking, category,
                        severity, explanation, contract_type, operation_kind,
                        operation_identifier, contract_location, old_type, new_type,
                        old_required, new_required, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        analysis_id,
                        ordinal,
                        change.change_id,
                        change.change_type.value,
                        change.path,
                        change.method,
                        change.subject,
                        _json(change.old_value),
                        _json(change.new_value),
                        int(change.breaking),
                        change.category.value,
                        change.severity.value,
                        change.explanation,
                        change.contract_type.value,
                        change.operation_kind.value,
                        change.operation_identifier,
                        change.contract_location,
                        change.old_type,
                        change.new_type,
                        None if change.old_required is None else int(change.old_required),
                        None if change.new_required is None else int(change.new_required),
                        _json(change.metadata),
                    ),
                )
            for impact in impacts:
                for ordinal, match in enumerate(impact.matches, start=1):
                    connection.execute(
                        """
                        INSERT INTO repository_matches (
                            analysis_id, change_id, ordinal, file_path, line,
                            column_number, match_kind, confidence, evidence,
                            symbol, language, impact_depth, analysis_kind,
                            trace_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            analysis_id,
                            impact.change_id,
                            ordinal,
                            match.file_path,
                            match.line,
                            match.column,
                            match.match_kind.value,
                            match.confidence.value,
                            redact_secrets(match.evidence[:240])[0][:240],
                            match.symbol,
                            match.language,
                            match.impact_depth,
                            match.analysis_kind.value,
                            _safe_trace_json(match.trace),
                        ),
                    )
            for prediction in risk_predictions:
                connection.execute(
                    """
                    INSERT INTO risk_predictions (
                        analysis_id, change_id, risk_level, risk_score,
                        prediction_source, model_name, model_version,
                        baseline_level, baseline_score, class_probabilities_json,
                        features_json, reasons_json, top_drivers_json,
                        fallback_reason, predicted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        analysis_id,
                        prediction.change_id,
                        prediction.risk_level.value,
                        prediction.risk_score,
                        prediction.prediction_source.value,
                        prediction.model_name,
                        prediction.model_version,
                        prediction.baseline_level.value,
                        prediction.baseline_score,
                        _json(
                            {
                                level.value: probability
                                for level, probability in prediction.class_probabilities.items()
                            }
                        ),
                        _json(prediction.features),
                        _json(prediction.reasons),
                        _json(
                            [driver.model_dump(mode="json") for driver in prediction.top_drivers]
                        ),
                        prediction.fallback_reason,
                        _timestamp(prediction.predicted_at),
                    ),
                )
            for recommendation in migration_recommendations:
                connection.execute(
                    """
                    INSERT INTO migration_recommendations (
                        recommendation_id,
                        analysis_id,
                        change_id,
                        provider,
                        provider_model,
                        recommendation_source,
                        recommendation_source_actual,
                        prompt_version,
                        schema_version,
                        summary,
                        why_it_matters,
                        affected_code_explanation,
                        migration_steps_json,
                        suggested_tests_json,
                        code_example,
                        assumptions_json,
                        warnings_json,
                        confidence,
                        provider_warning,
                        redactions_applied,
                        generated_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        recommendation.recommendation_id,
                        analysis_id,
                        recommendation.change_id,
                        recommendation.provider.value,
                        recommendation.provider_model,
                        (
                            "deterministic_fallback"
                            if recommendation.recommendation_source.value == "deterministic"
                            else recommendation.recommendation_source.value
                        ),
                        recommendation.recommendation_source.value,
                        recommendation.prompt_version,
                        recommendation.schema_version,
                        recommendation.summary,
                        recommendation.why_it_matters,
                        recommendation.affected_code_explanation,
                        _json(recommendation.migration_steps),
                        _json(recommendation.suggested_tests),
                        recommendation.code_example,
                        _json(recommendation.assumptions),
                        _json(recommendation.warnings),
                        recommendation.confidence,
                        recommendation.provider_warning,
                        recommendation.redactions_applied,
                        _timestamp(recommendation.generated_at),
                    ),
                )

            connection.execute(
                """
                UPDATE pipeline_stages
                SET status = 'succeeded', completed_at = ?, duration_ms = ?
                WHERE stage_id = ? AND status = 'running'
                """,
                (timestamp, duration_ms, stage_id),
            )
            connection.execute(
                """
                UPDATE analyses
                SET status = 'succeeded', updated_at = ?, completed_at = ?,
                    old_contract_json = ?, new_contract_json = ?,
                    comparison_summary_json = ?, repository_summary_json = ?,
                    impact_summary_json = ?
                WHERE analysis_id = ? AND status = 'running'
                """,
                (
                    timestamp,
                    timestamp,
                    _model_json(comparison.old_contract),
                    _model_json(comparison.new_contract),
                    _model_json(comparison.summary),
                    _model_json(repository_summary),
                    _model_json(impact_summary),
                    analysis_id,
                ),
            )

    def list_analyses(self, *, limit: int, offset: int) -> list[AnalysisRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM analyses WHERE workspace_id = ?
                ORDER BY created_at DESC, analysis_id DESC
                LIMIT ? OFFSET ?
                """,
                (current_workspace_id(), limit, offset),
            ).fetchall()
        return [_analysis_record(row) for row in rows]

    def get_analysis(self, analysis_id: str) -> AnalysisRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM analyses WHERE analysis_id = ? AND workspace_id = ?",
                (analysis_id, current_workspace_id()),
            ).fetchone()
        return _analysis_record(row) if row is not None else None

    def get_changes(self, analysis_id: str) -> list[ApiChange]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM analysis_changes
                WHERE analysis_id = ? ORDER BY ordinal
                """,
                (analysis_id,),
            ).fetchall()
        return [
            ApiChange.model_validate(
                {
                    "change_id": row["change_id"],
                    "change_type": row["change_type"],
                    "path": row["path"],
                    "method": row["method"],
                    "subject": row["subject"],
                    "old_value": _load_json(row["old_value_json"]),
                    "new_value": _load_json(row["new_value_json"]),
                    "breaking": bool(row["breaking"]),
                    "category": row["category"],
                    "severity": row["severity"],
                    "explanation": row["explanation"],
                    "contract_type": row["contract_type"],
                    "operation_kind": row["operation_kind"],
                    "operation_identifier": row["operation_identifier"],
                    "contract_location": row["contract_location"],
                    "old_type": row["old_type"],
                    "new_type": row["new_type"],
                    "old_required": _optional_bool(row["old_required"]),
                    "new_required": _optional_bool(row["new_required"]),
                    "metadata": _load_json(row["metadata_json"]) or {},
                }
            )
            for row in rows
        ]

    def get_matches(self, analysis_id: str) -> list[StoredMatch]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM repository_matches
                WHERE analysis_id = ? ORDER BY match_id
                """,
                (analysis_id,),
            ).fetchall()
        return [
            StoredMatch(
                change_id=row["change_id"],
                file_path=row["file_path"],
                line=row["line"],
                column=row["column_number"],
                match_kind=row["match_kind"],
                confidence=row["confidence"],
                evidence=row["evidence"],
                symbol=row["symbol"],
                language=row["language"],
                impact_depth=row["impact_depth"],
                analysis_kind=row["analysis_kind"],
                trace=tuple(_load_json(row["trace_json"]) or []),
            )
            for row in rows
        ]

    def get_pipeline(self, analysis_id: str) -> list[PipelineStageRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM pipeline_stages
                WHERE analysis_id = ? ORDER BY ordinal
                """,
                (analysis_id,),
            ).fetchall()
        return [_stage_record(row) for row in rows]

    def get_risk_predictions(self, analysis_id: str) -> list[RiskPrediction]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM risk_predictions
                WHERE analysis_id = ? ORDER BY prediction_id
                """,
                (analysis_id,),
            ).fetchall()
        return [
            RiskPrediction.model_validate(
                {
                    "analysis_id": row["analysis_id"],
                    "change_id": row["change_id"],
                    "risk_level": row["risk_level"],
                    "risk_score": row["risk_score"],
                    "prediction_source": row["prediction_source"],
                    "model_name": row["model_name"],
                    "model_version": row["model_version"],
                    "baseline_level": row["baseline_level"],
                    "baseline_score": row["baseline_score"],
                    "class_probabilities": _load_json(row["class_probabilities_json"]),
                    "features": _load_json(row["features_json"]),
                    "reasons": _load_json(row["reasons_json"]),
                    "top_drivers": _load_json(row["top_drivers_json"]),
                    "fallback_reason": row["fallback_reason"],
                    "predicted_at": _datetime(row["predicted_at"]),
                }
            )
            for row in rows
        ]

    def get_migration_recommendations(
        self,
        analysis_id: str,
    ) -> list[MigrationRecommendation]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM migration_recommendations
                WHERE analysis_id = ?
                ORDER BY generated_at, recommendation_id
                """,
                (analysis_id,),
            ).fetchall()

        return [
            MigrationRecommendation.model_validate(
                {
                    "recommendation_id": row["recommendation_id"],
                    "analysis_id": row["analysis_id"],
                    "change_id": row["change_id"],
                    "provider": row["provider"],
                    "provider_model": row["provider_model"],
                    "recommendation_source": (
                        row["recommendation_source_actual"] or row["recommendation_source"]
                    ),
                    "prompt_version": row["prompt_version"],
                    "schema_version": row["schema_version"],
                    "summary": row["summary"],
                    "why_it_matters": row["why_it_matters"],
                    "affected_code_explanation": row["affected_code_explanation"],
                    "migration_steps": _load_json(row["migration_steps_json"]),
                    "suggested_tests": _load_json(row["suggested_tests_json"]),
                    "code_example": row["code_example"],
                    "assumptions": _load_json(row["assumptions_json"]),
                    "warnings": _load_json(row["warnings_json"]),
                    "confidence": row["confidence"],
                    "provider_warning": row["provider_warning"],
                    "redactions_applied": row["redactions_applied"],
                    "generated_at": _datetime(row["generated_at"]),
                }
            )
            for row in rows
        ]

    def get_failure(self, analysis_id: str) -> FailureRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM analysis_failures
                WHERE analysis_id = ? ORDER BY failure_id DESC LIMIT 1
                """,
                (analysis_id,),
            ).fetchone()
        if row is None:
            return None
        return FailureRecord(
            failure_id=row["failure_id"],
            analysis_id=row["analysis_id"],
            stage_name=row["stage_name"],
            error_code=row["error_code"],
            safe_message=row["safe_message"],
            status_code=row["status_code"],
            created_at=_datetime(row["created_at"]),
        )

    def save_patch_proposal(self, proposal: PatchProposal) -> PatchProposal:
        with self._transaction() as connection:
            _ensure_phase22_provider_columns(connection)
            existing = connection.execute(
                "SELECT * FROM patch_proposals WHERE request_fingerprint = ?",
                (proposal.request_fingerprint,),
            ).fetchone()
            if existing is not None:
                return _patch_proposal(existing)
            connection.execute(
                """
                INSERT INTO patch_proposals (
                    patch_id, analysis_id, request_fingerprint, created_at,
                    status, summary, provider, provider_actual, provider_model,
                    provider_mode, provider_mode_actual,
                    patch_profile_version, source_repository_hash,
                    files_changed, edit_count, validation_json, warnings_json,
                    unified_diff, files_json, redactions_applied
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proposal.patch_id,
                    proposal.analysis_id,
                    proposal.request_fingerprint,
                    _timestamp(proposal.created_at),
                    proposal.status.value,
                    proposal.summary,
                    (
                        "mock"
                        if proposal.provider.value == "deterministic"
                        else proposal.provider.value
                    ),
                    proposal.provider.value,
                    proposal.provider_model,
                    (
                        "deterministic_mock"
                        if proposal.provider_mode.value == "evidence_based"
                        else proposal.provider_mode.value
                    ),
                    proposal.provider_mode.value,
                    proposal.patch_profile_version,
                    proposal.source_repository_hash,
                    proposal.files_changed,
                    proposal.edit_count,
                    _json(proposal.validation.model_dump(mode="json")),
                    _json(proposal.warnings),
                    proposal.unified_diff,
                    _json([item.model_dump(mode="json") for item in proposal.files]),
                    proposal.redactions_applied,
                ),
            )
        return proposal

    def get_patch_proposal(
        self,
        analysis_id: str,
        patch_id: str,
    ) -> PatchProposal | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM patch_proposals
                WHERE analysis_id = ? AND patch_id = ?
                """,
                (analysis_id, patch_id),
            ).fetchone()
        return _patch_proposal(row) if row is not None else None

    def get_patch_by_fingerprint(
        self,
        analysis_id: str,
        fingerprint: str,
    ) -> PatchProposal | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM patch_proposals
                WHERE analysis_id = ? AND request_fingerprint = ?
                """,
                (analysis_id, fingerprint),
            ).fetchone()
        return _patch_proposal(row) if row is not None else None

    def list_patch_proposals(self, analysis_id: str) -> list[PatchProposal]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM patch_proposals
                WHERE analysis_id = ? ORDER BY created_at DESC, patch_id
                """,
                (analysis_id,),
            ).fetchall()
        return [_patch_proposal(row) for row in rows]

    def save_patch_validation(self, validation: PatchValidationRun) -> PatchValidationRun:
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM patch_validation_runs WHERE request_fingerprint = ?",
                (validation.request_fingerprint,),
            ).fetchone()
            if existing is not None:
                return _patch_validation(existing)
            connection.execute(
                """
                INSERT INTO patch_validation_runs (
                    validation_id, patch_id, analysis_id, request_fingerprint,
                    created_at, validation_profile_version, readiness,
                    source_repository_hash, validation_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    validation.validation_id,
                    validation.patch_id,
                    validation.analysis_id,
                    validation.request_fingerprint,
                    _timestamp(validation.created_at),
                    validation.validation_profile_version,
                    validation.readiness.value,
                    validation.source_repository_hash,
                    _json(validation.model_dump(mode="json")),
                ),
            )
        return validation

    def get_patch_validation(
        self, analysis_id: str, patch_id: str, validation_id: str
    ) -> PatchValidationRun | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM patch_validation_runs
                WHERE analysis_id = ? AND patch_id = ? AND validation_id = ?
                """,
                (analysis_id, patch_id, validation_id),
            ).fetchone()
        return _patch_validation(row) if row is not None else None

    def get_patch_validation_by_fingerprint(
        self, analysis_id: str, patch_id: str, fingerprint: str
    ) -> PatchValidationRun | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM patch_validation_runs
                WHERE analysis_id = ? AND patch_id = ? AND request_fingerprint = ?
                """,
                (analysis_id, patch_id, fingerprint),
            ).fetchone()
        return _patch_validation(row) if row is not None else None

    def list_patch_validations(self, analysis_id: str, patch_id: str) -> list[PatchValidationRun]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM patch_validation_runs
                WHERE analysis_id = ? AND patch_id = ?
                ORDER BY created_at DESC, validation_id
                """,
                (analysis_id, patch_id),
            ).fetchall()
        return [_patch_validation(row) for row in rows]

    def save_pull_request_record(self, record: GitHubPullRequestRecord) -> GitHubPullRequestRecord:
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO github_pull_request_records (
                    pr_record_id, analysis_id, patch_id, validation_id,
                    request_fingerprint, status, created_at, updated_at, record_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(pr_record_id) DO UPDATE SET
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    record_json = excluded.record_json
                """,
                (
                    record.pr_record_id,
                    record.analysis_id,
                    record.patch_id,
                    record.validation_id,
                    record.request_fingerprint,
                    record.status.value,
                    _timestamp(record.created_at),
                    _timestamp(record.updated_at),
                    _json(record.model_dump(mode="json")),
                ),
            )
        return record

    def get_pull_request_record(
        self, analysis_id: str, pr_record_id: str
    ) -> GitHubPullRequestRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM github_pull_request_records
                WHERE analysis_id = ? AND pr_record_id = ?
                """,
                (analysis_id, pr_record_id),
            ).fetchone()
        return _pull_request_record(row) if row is not None else None

    def get_pull_request_by_fingerprint(
        self, analysis_id: str, fingerprint: str
    ) -> GitHubPullRequestRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM github_pull_request_records
                WHERE analysis_id = ? AND request_fingerprint = ?
                """,
                (analysis_id, fingerprint),
            ).fetchone()
        return _pull_request_record(row) if row is not None else None

    def list_pull_request_records(self, analysis_id: str) -> list[GitHubPullRequestRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM github_pull_request_records
                WHERE analysis_id = ? ORDER BY created_at DESC, pr_record_id
                """,
                (analysis_id,),
            ).fetchall()
        return [_pull_request_record(row) for row in rows]

    def delete(self, analysis_id: str) -> bool:
        with self._transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM analyses WHERE analysis_id = ? AND workspace_id = ?",
                (analysis_id, current_workspace_id()),
            )
            return cursor.rowcount > 0

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
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


def _analysis_record(row: sqlite3.Row) -> AnalysisRecord:
    return AnalysisRecord(
        analysis_id=row["analysis_id"],
        kind=AnalysisKind(row["kind"]),
        status=AnalysisStatus(row["status"]),
        request_fingerprint=row["request_fingerprint"],
        old_filename=row["old_filename"],
        new_filename=row["new_filename"],
        repository_filename=row["repository_filename"],
        old_file_sha256=row["old_file_sha256"],
        new_file_sha256=row["new_file_sha256"],
        repository_file_sha256=row["repository_file_sha256"],
        created_at=_datetime(row["created_at"]),
        updated_at=_datetime(row["updated_at"]),
        completed_at=_datetime(row["completed_at"]) if row["completed_at"] else None,
        old_contract=_load_json(row["old_contract_json"]),
        new_contract=_load_json(row["new_contract_json"]),
        comparison_summary=_load_json(row["comparison_summary_json"]),
        repository_summary=_load_json(row["repository_summary_json"]),
        impact_summary=_load_json(row["impact_summary_json"]),
        repository_source_type=(
            RepositorySourceType(row["repository_source_type"])
            if row["repository_source_type"]
            else None
        ),
        repository_url=row["repository_url"],
        repository_ref=row["repository_ref"],
        repository_commit_sha=row["repository_commit_sha"],
    )


def _patch_proposal(row: sqlite3.Row) -> PatchProposal:
    return PatchProposal.model_validate(
        {
            "patch_id": row["patch_id"],
            "analysis_id": row["analysis_id"],
            "request_fingerprint": row["request_fingerprint"],
            "created_at": _datetime(row["created_at"]),
            "status": row["status"],
            "summary": row["summary"],
            "provider": row["provider_actual"] or row["provider"],
            "provider_model": row["provider_model"],
            "provider_mode": row["provider_mode_actual"] or row["provider_mode"],
            "patch_profile_version": row["patch_profile_version"],
            "source_repository_hash": row["source_repository_hash"],
            "files_changed": row["files_changed"],
            "edit_count": row["edit_count"],
            "validation": _load_json(row["validation_json"]),
            "warnings": _load_json(row["warnings_json"]),
            "unified_diff": row["unified_diff"],
            "files": _load_json(row["files_json"]),
            "redactions_applied": row["redactions_applied"],
        }
    )


def _patch_validation(row: sqlite3.Row) -> PatchValidationRun:
    return PatchValidationRun.model_validate(_load_json(row["validation_json"]))


def _pull_request_record(row: sqlite3.Row) -> GitHubPullRequestRecord:
    return GitHubPullRequestRecord.model_validate(_load_json(row["record_json"]))


def _stage_record(row: sqlite3.Row) -> PipelineStageRecord:
    return PipelineStageRecord(
        stage_id=row["stage_id"],
        analysis_id=row["analysis_id"],
        stage_name=row["stage_name"],
        ordinal=row["ordinal"],
        status=PipelineStageStatus(row["status"]),
        started_at=_datetime(row["started_at"]),
        completed_at=_datetime(row["completed_at"]) if row["completed_at"] else None,
        duration_ms=row["duration_ms"],
        error_code=row["error_code"],
        error_message=row["error_message"],
    )


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _model_json(value: Any) -> str | None:
    if value is None:
        return None
    return _json(value.model_dump(mode="json"))


def _load_json(value: str | None) -> Any:
    return json.loads(value) if value is not None else None


def _safe_trace_json(trace: list[Any]) -> str:
    safe: list[dict[str, Any]] = []
    for step in trace[:10]:
        data = step.model_dump(mode="json")
        data["evidence"] = redact_secrets(str(data.get("evidence", ""))[:240])[0][:240]
        safe.append(data)
    return _json(safe)


def _ensure_phase22_provider_columns(connection: sqlite3.Connection) -> None:
    migration_columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(migration_recommendations)")
    }
    if "recommendation_source_actual" not in migration_columns:
        connection.execute(
            "ALTER TABLE migration_recommendations "
            "ADD COLUMN recommendation_source_actual TEXT"
        )
    patch_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(patch_proposals)")
    }
    additions = {
        "provider_actual": "TEXT",
        "provider_mode_actual": "TEXT",
    }
    for name, definition in additions.items():
        if name not in patch_columns:
            connection.execute(
                f"ALTER TABLE patch_proposals ADD COLUMN {name} {definition}"
            )


def _ensure_analysis_source_columns(connection: sqlite3.Connection) -> None:
    columns = {row[1] for row in connection.execute("PRAGMA table_info(analyses)").fetchall()}
    additions = {
        "repository_source_type": "TEXT",
        "repository_url": "TEXT",
        "repository_ref": "TEXT",
        "repository_commit_sha": "TEXT",
    }
    for name, definition in additions.items():
        if name not in columns:
            connection.execute(f"ALTER TABLE analyses ADD COLUMN {name} {definition}")


def _ensure_analysis_workspace_column(connection: sqlite3.Connection) -> None:
    columns = {row[1] for row in connection.execute("PRAGMA table_info(analyses)")}
    if "workspace_id" not in columns:
        connection.execute(
            "ALTER TABLE analyses ADD COLUMN workspace_id TEXT NOT NULL "
            f"DEFAULT '{LOCAL_WORKSPACE_ID}'"
        )
    connection.execute(
        "UPDATE analyses SET workspace_id = ? WHERE workspace_id IS NULL OR workspace_id = ''",
        (LOCAL_WORKSPACE_ID,),
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_analyses_workspace_created "
        "ON analyses(workspace_id, created_at DESC)"
    )


def _ensure_repository_match_columns(connection: sqlite3.Connection) -> None:
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(repository_matches)").fetchall()
    }
    additions = {
        "symbol": "TEXT",
        "language": "TEXT",
        "impact_depth": "INTEGER NOT NULL DEFAULT 0",
        "analysis_kind": "TEXT NOT NULL DEFAULT 'lexical'",
        "trace_json": "TEXT NOT NULL DEFAULT '[]'",
    }
    for name, definition in additions.items():
        if name not in columns:
            connection.execute(f"ALTER TABLE repository_matches ADD COLUMN {name} {definition}")


def _ensure_analysis_change_columns(connection: sqlite3.Connection) -> None:
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(analysis_changes)").fetchall()
    }
    additions = {
        "contract_type": "TEXT NOT NULL DEFAULT 'openapi'",
        "operation_kind": "TEXT NOT NULL DEFAULT 'http_operation'",
        "operation_identifier": "TEXT",
        "contract_location": "TEXT",
        "old_type": "TEXT",
        "new_type": "TEXT",
        "old_required": "INTEGER",
        "new_required": "INTEGER",
        "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
    }
    for name, definition in additions.items():
        if name not in columns:
            connection.execute(f"ALTER TABLE analysis_changes ADD COLUMN {name} {definition}")


def _optional_bool(value: Any) -> bool | None:
    return None if value is None else bool(value)
