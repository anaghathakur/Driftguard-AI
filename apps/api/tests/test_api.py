from __future__ import annotations

import json


def upload(spec, filename="api.json"):
    return (filename, json.dumps(spec).encode(), "application/json")


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

