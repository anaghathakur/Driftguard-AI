from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from apps.api.app.core.dependencies import get_risk_classifier
from apps.api.app.domain.repository import RepositoryScan, ScannedSourceFile
from apps.api.app.infrastructure.sqlite_analysis_repository import (
    SCHEMA,
    SQLiteAnalysisRepository,
)
from apps.api.app.migration.context import MigrationContext, PromptBuildResult
from apps.api.app.migration.provider import DeterministicMigrationRecommendationProvider
from apps.api.app.schemas.comparison import (
    ApiChange,
    ChangeCategory,
    ChangeType,
    Severity,
)
from apps.api.app.schemas.impact import ChangeImpact
from apps.api.app.schemas.migration import MigrationProvider
from apps.api.app.schemas.validation import ValidationExecutionStatus
from apps.api.app.services.analysis_pipeline import AnalysisPipelineService
from apps.api.app.validation.execution import (
    DiscoveredCommand,
    ValidationExecutionEngine,
    validate_discovered_command,
)


def _scan(files: dict[str, str]) -> RepositoryScan:
    return RepositoryScan(
        archive_sha256="a" * 64,
        archive_entries=len(files),
        files=tuple(
            ScannedSourceFile(path=path, content=content, size_bytes=len(content.encode()))
            for path, content in sorted(files.items())
        ),
        skipped_files=0,
        skipped_reasons={},
    )


def _engine(*, timeout: float = 2, maximum: int = 10_000) -> ValidationExecutionEngine:
    return ValidationExecutionEngine(
        provider="local",
        deployment_environment="test",
        timeout_seconds=timeout,
        output_max_bytes=maximum,
    )


def test_deterministic_migration_provider_is_real_and_non_rename_assertive():
    provider = DeterministicMigrationRecommendationProvider()
    change = ApiChange(
        change_id="removed-email",
        change_type=ChangeType.REQUEST_FIELD_REMOVED,
        path="/payments",
        method="POST",
        subject="email",
        breaking=True,
        category=ChangeCategory.BREAKING,
        severity=Severity.HIGH,
        explanation="The request field email was removed.",
    )
    content = provider.generate(
        MigrationContext(
            analysis_id="analysis",
            change=change,
            impact=ChangeImpact(
                change_id=change.change_id,
                path=change.path,
                method=change.method,
                matches=[],
            ),
            risk=None,  # type: ignore[arg-type]
        ),
        PromptBuildResult("", "", 0, ()),
    )
    combined = " ".join([content.summary, *content.migration_steps, *content.warnings])
    assert provider.name is MigrationProvider.DETERMINISTIC
    assert "rename" not in combined.lower()
    assert "replacement" in combined.lower()


def test_execution_uses_disposable_copy_and_preserves_original(monkeypatch):
    scan = _scan(
        {
            "repo/pyproject.toml": "[tool.pytest.ini_options]\n",
            "repo/test_payment.py": "def test_payment():\n    assert VALUE == 2\n",
            "repo/payment.py": "VALUE = 1\n",
        }
    )
    captured: dict[str, Path | str] = {}

    def successful(argv, **kwargs):
        cwd = Path(kwargs["cwd"])
        captured["cwd"] = cwd
        captured["patched"] = (cwd / "payment.py").read_text(encoding="utf-8")
        assert kwargs["shell"] is False
        return subprocess.CompletedProcess(argv, 0, stdout=b"1 passed", stderr=b"")

    monkeypatch.setattr(subprocess, "run", successful)
    result = _engine().execute(scan, {"repo/payment.py": "VALUE = 2\n"})

    assert result.status is ValidationExecutionStatus.PASSED
    assert result.isolated_temporary_copy is True
    assert captured["patched"] == "VALUE = 2\n"
    assert not Path(captured["cwd"]).exists()
    assert next(item for item in scan.files if item.path.endswith("payment.py")).content == (
        "VALUE = 1\n"
    )


def test_execution_reports_failure_timeout_and_output_limit(monkeypatch):
    scan = _scan(
        {
            "pyproject.toml": "[tool.pytest.ini_options]\n",
            "test_failure.py": "def test_failure():\n    assert False\n",
        }
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **_kwargs: subprocess.CompletedProcess(
            argv, 2, stdout=b"x" * 4_000, stderr=b"failed"
        ),
    )
    failed = _engine(maximum=1_000).execute(scan, {})
    assert failed.status is ValidationExecutionStatus.FAILED
    assert failed.commands[0].output_truncated is True

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(["pytest"], timeout=1, output=b"partial")

    monkeypatch.setattr(subprocess, "run", timeout)
    timed_out = _engine(timeout=1).execute(scan, {})
    assert timed_out.status is ValidationExecutionStatus.FAILED
    assert timed_out.commands[0].timed_out is True


def test_execution_rejects_arbitrary_command_and_unsupported_project():
    with pytest.raises(ValueError, match="allowlist"):
        validate_discovered_command(
            DiscoveredCommand("test", "unsafe", ("powershell", "-Command", "whoami"), ".")
        )
    result = _engine().execute(_scan({"README.md": "nothing executable"}), {})
    assert result.status is ValidationExecutionStatus.NOT_CONFIGURED
    assert result.commands == []


def test_execution_is_not_available_in_production_process():
    engine = ValidationExecutionEngine(
        provider="local",
        deployment_environment="production",
        timeout_seconds=1,
        output_max_bytes=1_000,
    )
    result = engine.execute(_scan({"test_example.py": "def test_ok(): assert True\n"}), {})
    assert result.status is ValidationExecutionStatus.NOT_CONFIGURED


def test_legacy_phase22_database_self_heals_for_graphql_and_openapi(tmp_path):
    database = tmp_path / "legacy-phase22.sqlite3"
    legacy_schema = (
        SCHEMA.replace("    recommendation_source_actual TEXT,\n", "")
        .replace("    provider_actual TEXT,\n", "")
        .replace("    provider_mode_actual TEXT,\n", "")
    )
    with sqlite3.connect(database) as connection:
        connection.executescript(legacy_schema)

    service = AnalysisPipelineService(
        SQLiteAnalysisRepository(database),
        get_risk_classifier(),
    )
    graphql = service.compare(
        old_filename="saleor-minimized-old.graphql",
        old_content=b"type Query { product(id: ID!): String }",
        new_filename="saleor-minimized-new.graphql",
        new_content=b"type Query { product(sku: String!): String }",
    )

    old_openapi = {
        "openapi": "3.0.0",
        "info": {"title": "OpenAPI control", "version": "1"},
        "paths": {"/control": {"post": {"responses": {"200": {"description": "ok"}}}}},
    }
    new_openapi = json.loads(json.dumps(old_openapi))
    new_openapi["paths"]["/control"]["post"]["parameters"] = [
        {
            "name": "required_id",
            "in": "query",
            "required": True,
            "schema": {"type": "string"},
        }
    ]
    openapi = service.compare(
        old_filename="control-old.json",
        old_content=json.dumps(old_openapi).encode(),
        new_filename="control-new.json",
        new_content=json.dumps(new_openapi).encode(),
    )

    assert graphql.summary.total_changes == 2
    assert openapi.summary.total_changes == 1
    with sqlite3.connect(database) as connection:
        migration_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(migration_recommendations)")
        }
        patch_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(patch_proposals)")
        }
        sources = {
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT recommendation_source_actual "
                "FROM migration_recommendations"
            )
        }
    assert "recommendation_source_actual" in migration_columns
    assert {"provider_actual", "provider_mode_actual"} <= patch_columns
    assert sources == {"deterministic"}


def test_phase22_additive_columns_commit_during_legacy_initialization(tmp_path):
    database = tmp_path / "legacy-phase22-initialize.sqlite3"
    legacy_schema = (
        SCHEMA.replace("    recommendation_source_actual TEXT,\n", "")
        .replace("    provider_actual TEXT,\n", "")
        .replace("    provider_mode_actual TEXT,\n", "")
    )
    with sqlite3.connect(database) as connection:
        connection.executescript(legacy_schema)

    SQLiteAnalysisRepository(database).initialize()

    with sqlite3.connect(database) as connection:
        migration_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(migration_recommendations)")
        }
        patch_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(patch_proposals)")
        }
    assert "recommendation_source_actual" in migration_columns
    assert {"provider_actual", "provider_mode_actual"} <= patch_columns
