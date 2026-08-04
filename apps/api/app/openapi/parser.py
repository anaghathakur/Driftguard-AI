"""Parse and validate untrusted OpenAPI uploads."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from apps.api.app.core.exceptions import DriftGuardError

SUPPORTED_EXTENSIONS = {".json", ".yaml", ".yml"}
MAX_DOCUMENT_DEPTH = 100
MAX_DOCUMENT_NODES = 100_000


def _validate_document_complexity(document: Any) -> None:
    node_count = 0
    active_containers: set[int] = set()

    def visit(value: Any, depth: int) -> None:
        nonlocal node_count
        node_count += 1
        if depth > MAX_DOCUMENT_DEPTH or node_count > MAX_DOCUMENT_NODES:
            raise DriftGuardError(
                code="specification_too_complex",
                message="The OpenAPI document exceeds supported complexity limits.",
            )
        if not isinstance(value, (dict, list)):
            return
        identity = id(value)
        if identity in active_containers:
            raise DriftGuardError(
                code="cyclic_document_structure",
                message="The OpenAPI document contains a cyclic YAML alias.",
            )
        active_containers.add(identity)
        children = value.values() if isinstance(value, dict) else value
        for child in children:
            visit(child, depth + 1)
        active_containers.remove(identity)

    visit(document, 0)


def parse_openapi_document(filename: str, content: bytes) -> dict[str, Any]:
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise DriftGuardError(
            code="unsupported_specification_format",
            message="OpenAPI files must use a .json, .yaml, or .yml extension.",
            details={"filename": Path(filename).name},
        )
    if not content:
        raise DriftGuardError(
            code="empty_specification", message="The uploaded OpenAPI file is empty."
        )

    try:
        document = json.loads(content) if extension == ".json" else yaml.safe_load(content)
    except (json.JSONDecodeError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise DriftGuardError(
            code="invalid_specification_syntax",
            message=f"The uploaded {extension[1:].upper()} file cannot be parsed.",
        ) from exc

    if not isinstance(document, dict):
        raise DriftGuardError(
            code="invalid_openapi_document",
            message="The OpenAPI document must be an object.",
        )

    _validate_document_complexity(document)

    openapi_version = document.get("openapi")
    if not isinstance(openapi_version, str) or not openapi_version.startswith("3."):
        raise DriftGuardError(
            code="unsupported_openapi_version",
            message="The document must declare an OpenAPI 3.x version.",
        )
    info = document.get("info")
    if (
        not isinstance(info, dict)
        or not isinstance(info.get("title"), str)
        or not isinstance(info.get("version"), str)
    ):
        raise DriftGuardError(
            code="invalid_openapi_document",
            message="The document must contain info.title and info.version strings.",
        )
    if not isinstance(document.get("paths"), dict):
        raise DriftGuardError(
            code="invalid_openapi_document",
            message="The document must contain a paths object.",
        )
    return document
