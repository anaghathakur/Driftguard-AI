from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime

import pytest

from apps.api.app.domain.analysis import AnalysisKind, AnalysisStatus, AnalysisSubmission
from apps.api.app.openapi.normalizer import normalize_openapi
from apps.api.app.risk.classifier import RiskClassifier
from apps.api.app.services.analysis_pipeline import AnalysisPipelineService
from apps.api.app.services.comparison import SpecificationComparisonService


def specification_bytes(spec) -> bytes:
    return json.dumps(spec, sort_keys=True).encode()


def test_database_initializes_all_milestone_tables(analysis_repository):
    connection = sqlite3.connect(analysis_repository.database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        connection.close()

    assert {
        "analyses",
        "analysis_changes",
        "repository_matches",
        "risk_predictions",
        "pipeline_stages",
        "analysis_failures",
    } <= tables


def test_duplicate_comparison_reuses_persisted_analysis(
    analysis_repository, base_spec, clone
):
    new = clone(base_spec)
    new["paths"]["/payments"]["post"]["parameters"][0]["schema"]["type"] = "integer"
    old_content = specification_bytes(base_spec)
    new_content = specification_bytes(new)
    service = AnalysisPipelineService(
        analysis_repository, RiskClassifier("missing.joblib", "missing.json")
    )

    first = service.compare(
        old_filename="old.json",
        old_content=old_content,
        new_filename="new.json",
        new_content=new_content,
    )
    duplicate = service.compare(
        old_filename="renamed-old.json",
        old_content=old_content,
        new_filename="renamed-new.json",
        new_content=new_content,
    )

    assert duplicate.analysis_id == first.analysis_id
    assert duplicate.duplicate is True
    assert len(analysis_repository.list_analyses(limit=10, offset=0)) == 1
    stored = analysis_repository.get_analysis(first.analysis_id)
    assert stored is not None
    assert stored.status == AnalysisStatus.SUCCEEDED
    assert stored.old_file_sha256 == hashlib.sha256(old_content).hexdigest()
    assert stored.created_at.tzinfo is not None


def test_result_write_rolls_back_all_changes_on_constraint_failure(
    analysis_repository, base_spec, clone
):
    new = clone(base_spec)
    new["paths"]["/payments"]["post"]["parameters"][0]["schema"]["type"] = "integer"
    old_content = specification_bytes(base_spec)
    new_content = specification_bytes(new)
    comparison_service = SpecificationComparisonService()
    comparison = comparison_service.compare_contracts(
        old_contract=normalize_openapi(base_spec),
        old_content=old_content,
        new_contract=normalize_openapi(new),
        new_content=new_content,
    )
    created_at = datetime.now(UTC)
    creation = analysis_repository.create_or_get(
        AnalysisSubmission(
            kind=AnalysisKind.COMPARISON,
            request_fingerprint="f" * 64,
            old_filename="old.json",
            new_filename="new.json",
            repository_filename=None,
            old_file_sha256="a" * 64,
            new_file_sha256="b" * 64,
            repository_file_sha256=None,
            created_at=created_at,
        )
    )
    stage_id = analysis_repository.start_stage(
        creation.analysis.analysis_id, "persist_results", 1, created_at
    )
    invalid_comparison = comparison.model_copy(
        update={"changes": [comparison.changes[0], comparison.changes[0]]}
    )

    with pytest.raises(sqlite3.IntegrityError):
        analysis_repository.save_success(
            analysis_id=creation.analysis.analysis_id,
            comparison=invalid_comparison,
            repository_summary=None,
            impact_summary=None,
            impacts=[],
            risk_predictions=[],
            migration_recommendations=[],
            stage_id=stage_id,
            completed_at=datetime.now(UTC),
            duration_ms=1,
        )

    assert analysis_repository.get_changes(creation.analysis.analysis_id) == []
    stored = analysis_repository.get_analysis(creation.analysis.analysis_id)
    assert stored is not None
    assert stored.status == AnalysisStatus.RUNNING
    assert analysis_repository.get_pipeline(creation.analysis.analysis_id)[0].status.value == (
        "running"
    )
