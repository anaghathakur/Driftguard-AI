from __future__ import annotations

import json

import pytest

from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.openapi.normalizer import normalize_openapi
from apps.api.app.openapi.parser import parse_openapi_document


def test_valid_json_openapi_file(base_spec):
    parsed = parse_openapi_document("api.json", json.dumps(base_spec).encode())
    assert parsed["openapi"] == "3.0.3"


def test_valid_yaml_openapi_file():
    content = b"openapi: 3.1.0\ninfo: {title: Demo, version: 1.0.0}\npaths: {}\n"
    assert parse_openapi_document("api.yaml", content)["info"]["title"] == "Demo"


@pytest.mark.parametrize(
    ("filename", "content", "code"),
    [
        ("api.json", b"{bad", "invalid_specification_syntax"),
        ("api.yaml", b"openapi: [", "invalid_specification_syntax"),
        ("api.txt", b"hello", "unsupported_specification_format"),
        ("api.json", b"{}", "unsupported_openapi_version"),
    ],
)
def test_invalid_uploads_return_structured_domain_errors(filename, content, code):
    with pytest.raises(DriftGuardError) as error:
        parse_openapi_document(filename, content)
    assert error.value.code == code


def test_invalid_structure_requires_info_and_paths():
    content = b'{"openapi":"3.0.0","info":{},"paths":[]}'
    with pytest.raises(DriftGuardError) as error:
        parse_openapi_document("api.json", content)
    assert error.value.code == "invalid_openapi_document"


def test_local_schema_reference_is_resolved(base_spec):
    base_spec["components"] = {
        "schemas": {
            "Payment": {
                "type": "object",
                "required": ["amount"],
                "properties": {"amount": {"type": "integer"}},
            }
        }
    }
    operation = base_spec["paths"]["/payments"]["post"]
    operation["requestBody"]["content"]["application/json"]["schema"] = {
        "$ref": "#/components/schemas/Payment"
    }
    normalized = normalize_openapi(base_spec)
    assert normalized.operations["POST /payments"].request_fields["amount"].required


def test_remote_reference_is_rejected(base_spec):
    operation = base_spec["paths"]["/payments"]["post"]
    operation["requestBody"]["content"]["application/json"]["schema"] = {
        "$ref": "https://example.test/schema.json"
    }
    with pytest.raises(DriftGuardError) as error:
        normalize_openapi(base_spec)
    assert error.value.code == "unsupported_reference"


def test_cyclic_yaml_alias_is_rejected():
    content = (
        b"openapi: 3.0.0\n"
        b"info: &info {title: Demo, version: 1.0}\n"
        b"paths: {}\n"
        b"cycle: &cycle [*cycle]\n"
    )
    with pytest.raises(DriftGuardError) as error:
        parse_openapi_document("api.yaml", content)
    assert error.value.code == "cyclic_document_structure"
