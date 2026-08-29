from __future__ import annotations

import json
import sqlite3
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile


def upload(spec, filename="api.json"):
    content = spec if isinstance(spec, bytes) else json.dumps(spec).encode()
    return (filename, content, "application/json")


def repository_upload(files, filename="repository.zip"):
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return (filename, output.getvalue(), "application/zip")


def impact_files(base_spec, new):
    return {
        "old_spec": upload(base_spec, "old.json"),
        "new_spec": upload(new, "new.json"),
        "repository": repository_upload(
            {"src/client.py": 'requests.post("/payments", json=payload)'}
        ),
    }


def changed_spec(base_spec, clone):
    new = clone(base_spec)
    schema = new["paths"]["/payments"]["post"]["requestBody"]["content"]
    schema = schema["application/json"]["schema"]
    schema["properties"]["customer_id"] = {"type": "string"}
    schema["required"].append("customer_id")
    return new


def test_impact_history_endpoints_and_cascading_delete(
    client, analysis_repository, base_spec, clone
):
    response = client.post(
        "/api/v1/impact/analyze",
        files=impact_files(base_spec, changed_spec(base_spec, clone)),
    )
    assert response.status_code == 200
    analysis_id = response.json()["analysis_id"]

    history = client.get("/api/v1/analyses").json()
    assert len(history) == 1
    assert history[0]["analysis_id"] == analysis_id
    assert history[0]["status"] == "succeeded"
    assert history[0]["total_changes"] == 1
    assert history[0]["total_matches"] == 1

    detail = client.get(f"/api/v1/analyses/{analysis_id}").json()
    assert detail["kind"] == "impact"
    assert detail["created_at"].endswith("Z")
    assert len(detail["request_fingerprint"]) == 64
    assert len(detail["file_hashes"]["repository"]) == 64

    changes = client.get(f"/api/v1/analyses/{analysis_id}/changes").json()
    matches = client.get(f"/api/v1/analyses/{analysis_id}/matches").json()
    pipeline = client.get(f"/api/v1/analyses/{analysis_id}/pipeline").json()
    assert len(changes) == 1
    assert matches[0]["change_id"] == changes[0]["change_id"]
    assert matches[0]["evidence"] == 'requests.post("/payments", json=payload)'
    assert [stage["stage_name"] for stage in pipeline] == [
        "validate_and_normalize_specifications",
        "compare_contracts",
        "scan_repository",
        "match_api_usage",
        "classify_risk",
        "generate_migration_recommendations",
        "persist_results",
    ]
    assert {stage["status"] for stage in pipeline} == {"succeeded"}

    assert client.delete(f"/api/v1/analyses/{analysis_id}").status_code == 204
    assert client.get(f"/api/v1/analyses/{analysis_id}").status_code == 404
    assert client.get("/api/v1/analyses").json() == []
    connection = sqlite3.connect(analysis_repository.database_path)
    try:
        for table in (
            "analysis_changes",
            "repository_matches",
            "risk_predictions",
            "pipeline_stages",
            "analysis_failures",
        ):
            count = connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            assert count == 0
    finally:
        connection.close()


def test_duplicate_impact_submission_reuses_result(client, base_spec, clone):
    new = changed_spec(base_spec, clone)
    files = impact_files(base_spec, new)
    first = client.post("/api/v1/impact/analyze", files=files)
    second = client.post("/api/v1/impact/analyze", files=files)

    assert first.status_code == second.status_code == 200
    assert second.json()["analysis_id"] == first.json()["analysis_id"]
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True
    assert len(client.get("/api/v1/analyses").json()) == 1


def test_failed_analysis_and_failed_pipeline_stage_are_preserved(client, base_spec):
    files = {
        "old_spec": upload(b"{bad", "old.json"),
        "new_spec": upload(base_spec, "new.json"),
    }
    response = client.post("/api/v1/specifications/compare", files=files)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_specification_syntax"
    history = client.get("/api/v1/analyses").json()
    assert len(history) == 1
    assert history[0]["status"] == "failed"
    assert history[0]["failure"]["error_code"] == "invalid_specification_syntax"
    analysis_id = history[0]["analysis_id"]

    detail = client.get(f"/api/v1/analyses/{analysis_id}").json()
    pipeline = client.get(f"/api/v1/analyses/{analysis_id}/pipeline").json()
    assert detail["failure"]["message"] == "The uploaded JSON file cannot be parsed."
    assert pipeline[0]["stage_name"] == "validate_and_normalize_specifications"
    assert pipeline[0]["status"] == "failed"
    assert pipeline[0]["error_code"] == "invalid_specification_syntax"
    assert "traceback" not in json.dumps(detail).lower()

    duplicate = client.post("/api/v1/specifications/compare", files=files)
    assert duplicate.status_code == 400
    assert len(client.get("/api/v1/analyses").json()) == 1


def test_comparison_history_has_no_repository_data(client, base_spec, clone):
    response = client.post(
        "/api/v1/specifications/compare",
        files={
            "old_spec": upload(base_spec, "old.json"),
            "new_spec": upload(changed_spec(base_spec, clone), "new.json"),
        },
    )
    analysis_id = response.json()["analysis_id"]
    detail = client.get(f"/api/v1/analyses/{analysis_id}").json()

    assert detail["kind"] == "comparison"
    assert detail["file_hashes"]["repository"] is None
    assert detail["repository_summary"] is None
    assert client.get(f"/api/v1/analyses/{analysis_id}/matches").json() == []
    pipeline = client.get(f"/api/v1/analyses/{analysis_id}/pipeline").json()
    assert [stage["stage_name"] for stage in pipeline] == [
        "validate_and_normalize_specifications",
        "compare_contracts",
        "classify_risk",
        "generate_migration_recommendations",
        "persist_results",
    ]


def test_repository_archives_and_complete_source_files_are_not_stored(
    client, analysis_repository, base_spec, clone
):
    private_source = (
        'requests.post("/payments", json=payload)\n'
        "PRIVATE_SOURCE_SENTINEL_THAT_MUST_NOT_BE_PERSISTED\n"
    )
    files = {
        "old_spec": upload(base_spec, "old.json"),
        "new_spec": upload(changed_spec(base_spec, clone), "new.json"),
        "repository": repository_upload({"src/client.py": private_source}),
    }

    response = client.post("/api/v1/impact/analyze", files=files)

    assert response.status_code == 200
    database_bytes = analysis_repository.database_path.read_bytes()
    assert b"PRIVATE_SOURCE_SENTINEL_THAT_MUST_NOT_BE_PERSISTED" not in database_bytes
    matches = client.get(f"/api/v1/analyses/{response.json()['analysis_id']}/matches").json()
    assert matches[0]["evidence"] == 'requests.post("/payments", json=payload)'


def test_unknown_analysis_returns_safe_not_found_for_all_endpoints(client):
    paths = [
        "/api/v1/analyses/missing",
        "/api/v1/analyses/missing/changes",
        "/api/v1/analyses/missing/matches",
        "/api/v1/analyses/missing/pipeline",
    ]
    for path in paths:
        response = client.get(path)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "analysis_not_found"
    assert client.delete("/api/v1/analyses/missing").status_code == 404
