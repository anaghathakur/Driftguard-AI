from __future__ import annotations

import json
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from apps.api.app.core.config import _origins


def upload(spec, filename="api.json"):
    return (filename, json.dumps(spec).encode(), "application/json")


def repository_upload(files, filename="repository.zip"):
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return (filename, output.getvalue(), "application/zip")


def test_successful_comparison_returns_structured_response(client, base_spec, clone):
    new = clone(base_spec)
    schema = new["paths"]["/payments"]["post"]["requestBody"]["content"]
    schema = schema["application/json"]["schema"]
    schema["properties"]["customer_id"] = {"type": "string"}
    schema["required"].append("customer_id")
    response = client.post(
        "/api/v1/specifications/compare",
        files={"old_spec": upload(base_spec), "new_spec": upload(new)},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == {
        "total_changes": 1,
        "breaking_changes": 1,
        "potentially_breaking_changes": 0,
        "non_breaking_changes": 0,
    }
    assert len(body["old_contract"]["sha256"]) == 64
    assert body["changes"][0]["change_id"]


def test_invalid_json_has_safe_error_shape(client, base_spec):
    response = client.post(
        "/api/v1/specifications/compare",
        files={
            "old_spec": ("old.json", b"{bad", "application/json"),
            "new_spec": upload(base_spec),
        },
    )
    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "invalid_specification_syntax",
            "message": "The uploaded JSON file cannot be parsed.",
            "details": {},
        }
    }


def test_missing_file_has_safe_validation_error(client, base_spec):
    response = client.post("/api/v1/specifications/compare", files={"old_spec": upload(base_spec)})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_validation_error"
    assert "traceback" not in response.text.lower()


def test_unsupported_file_extension(client, base_spec):
    response = client.post(
        "/api/v1/specifications/compare",
        files={
            "old_spec": ("old.txt", b"hello", "text/plain"),
            "new_spec": upload(base_spec),
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_specification_format"


def test_health_endpoints(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/v1/health").json() == {"status": "ok"}

    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ready.json()["checks"]["storage"] == "sqlite"
    assert ready.json()["checks"]["github_write_provider"] == "mock"
    assert ready.json()["issues"] == []
    assert client.get("/api/v1/ready").json() == ready.json()


def test_local_cors_preflight_is_allowed(client):
    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_origin_configuration_is_bounded(monkeypatch):
    monkeypatch.setenv(
        "TEST_DRIFTGUARD_ORIGINS",
        "https://demo.example, http://localhost:5173/, https://demo.example",
    )
    assert _origins("TEST_DRIFTGUARD_ORIGINS", ()) == (
        "https://demo.example",
        "http://localhost:5173",
    )

    monkeypatch.setenv("TEST_DRIFTGUARD_ORIGINS", "*")
    with pytest.raises(RuntimeError):
        _origins("TEST_DRIFTGUARD_ORIGINS", ())


def test_impact_analysis_returns_comparison_scan_and_matches(client, base_spec, clone):
    new = clone(base_spec)
    schema = new["paths"]["/payments"]["post"]["requestBody"]["content"]
    schema = schema["application/json"]["schema"]
    schema["properties"]["customer_id"] = {"type": "string"}
    schema["required"].append("customer_id")

    response = client.post(
        "/api/v1/impact/analyze",
        files={
            "old_spec": upload(base_spec, "old.json"),
            "new_spec": upload(new, "new.json"),
            "repository": repository_upload(
                {
                    "demo/src/client.py": ('response = requests.post("/payments", json=payload)\n'),
                    "demo/README.md": "ignored",
                }
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["comparison"]["summary"]["breaking_changes"] == 1
    assert body["repository"]["scanned_files"] == 1
    assert body["repository"]["skipped_reasons"] == {"unsupported_extension": 1}
    assert body["impact_summary"] == {
        "total_changes": 1,
        "impacted_changes": 1,
        "impacted_files": 1,
        "total_matches": 1,
    }
    assert body["impacts"][0]["matches"][0]["match_kind"] == "path_and_method"


def test_impact_analysis_rejects_unsafe_repository_archive(client, base_spec):
    response = client.post(
        "/api/v1/impact/analyze",
        files={
            "old_spec": upload(base_spec, "old.json"),
            "new_spec": upload(base_spec, "new.json"),
            "repository": repository_upload({"../secret.py": "pass"}),
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsafe_repository_archive"
    assert "traceback" not in response.text.lower()
