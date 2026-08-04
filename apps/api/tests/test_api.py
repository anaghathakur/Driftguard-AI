from __future__ import annotations

import json
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile


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
    response = client.post(
        "/api/v1/specifications/compare", files={"old_spec": upload(base_spec)}
    )
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
                    "demo/src/client.py": (
                        'response = requests.post("/payments", json=payload)\n'
                    ),
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
