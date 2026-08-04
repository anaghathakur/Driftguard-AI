"""Convert OpenAPI 3.x documents into stable domain models."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from urllib.parse import unquote

from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.domain.openapi import (
    NormalizedContract,
    NormalizedField,
    NormalizedOperation,
    NormalizedParameter,
    NormalizedResponse,
    operation_key,
)

HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
MAX_SCHEMA_DEPTH = 20


class LocalReferenceResolver:
    def __init__(self, document: dict[str, Any]) -> None:
        self.document = document

    def resolve(self, value: Any, seen: frozenset[str] = frozenset()) -> Any:
        if not isinstance(value, dict) or "$ref" not in value:
            return value
        reference = value["$ref"]
        if not isinstance(reference, str) or not reference.startswith("#/"):
            raise DriftGuardError(
                code="unsupported_reference",
                message="Only local OpenAPI references are supported in this milestone.",
            )
        if reference in seen:
            raise DriftGuardError(
                code="circular_reference",
                message="A circular local OpenAPI reference was detected.",
            )
        target: Any = self.document
        try:
            for raw_part in reference[2:].split("/"):
                part = unquote(raw_part).replace("~1", "/").replace("~0", "~")
                target = target[part]
        except (KeyError, TypeError) as exc:
            raise DriftGuardError(
                code="unresolved_reference",
                message="A local OpenAPI reference could not be resolved.",
                details={"reference": reference},
            ) from exc
        resolved = deepcopy(target)
        siblings = {key: val for key, val in value.items() if key != "$ref"}
        if isinstance(resolved, dict):
            resolved.update(siblings)
        return self.resolve(resolved, seen | {reference})


def _schema_type(schema: dict[str, Any]) -> str:
    schema_type = schema.get("type")
    if isinstance(schema_type, str):
        if schema_type == "array":
            items = schema.get("items", {})
            item_type = items.get("type", "unknown") if isinstance(items, dict) else "unknown"
            return f"array[{item_type}]"
        return schema_type
    if "properties" in schema:
        return "object"
    return "unknown"


def _enum_values(schema: dict[str, Any]) -> tuple[str, ...]:
    values = schema.get("enum", [])
    if not isinstance(values, list):
        return ()
    return tuple(sorted(str(value) for value in values))


def _merge_all_of(schema: dict[str, Any], resolver: LocalReferenceResolver) -> dict[str, Any]:
    schema = resolver.resolve(schema)
    if not isinstance(schema, dict):
        return {}
    merged = {key: deepcopy(value) for key, value in schema.items() if key != "allOf"}
    all_of = schema.get("allOf", [])
    if not isinstance(all_of, list):
        return merged
    merged_properties = dict(merged.get("properties", {}))
    merged_required = set(merged.get("required", []))
    for member in all_of:
        resolved = _merge_all_of(member, resolver) if isinstance(member, dict) else {}
        properties = resolved.get("properties", {})
        if isinstance(properties, dict):
            merged_properties.update(properties)
        required = resolved.get("required", [])
        if isinstance(required, list):
            merged_required.update(str(item) for item in required)
    if merged_properties:
        merged["properties"] = merged_properties
    if merged_required:
        merged["required"] = sorted(merged_required)
    return merged


def _extract_fields(
    raw_schema: Any,
    resolver: LocalReferenceResolver,
    prefix: str = "",
    depth: int = 0,
) -> dict[str, NormalizedField]:
    if depth > MAX_SCHEMA_DEPTH:
        raise DriftGuardError(
            code="schema_nesting_too_deep",
            message="An OpenAPI schema exceeds the supported nesting depth.",
        )
    if not isinstance(raw_schema, dict):
        return {}
    schema = _merge_all_of(raw_schema, resolver)
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return {}
    raw_required = schema.get("required", [])
    required = set(raw_required) if isinstance(raw_required, list) else set()
    fields: dict[str, NormalizedField] = {}
    for name in sorted(properties):
        raw_property = properties[name]
        if not isinstance(raw_property, dict):
            continue
        property_schema = _merge_all_of(raw_property, resolver)
        field_name = f"{prefix}.{name}" if prefix else name
        fields[field_name] = NormalizedField(
            name=field_name,
            data_type=_schema_type(property_schema),
            required=name in required,
            enum=_enum_values(property_schema),
        )
        fields.update(_extract_fields(property_schema, resolver, field_name, depth + 1))
    return fields


def _content_schema(container: Any, resolver: LocalReferenceResolver) -> dict[str, Any]:
    if not isinstance(container, dict):
        return {}
    container = resolver.resolve(container)
    content = container.get("content", {})
    if not isinstance(content, dict) or not content:
        return {}
    media = content.get("application/json")
    if not isinstance(media, dict):
        media = next((value for value in content.values() if isinstance(value, dict)), {})
    schema = media.get("schema", {})
    return schema if isinstance(schema, dict) else {}


def _normalize_parameters(
    path_parameters: Any,
    operation_parameters: Any,
    resolver: LocalReferenceResolver,
) -> tuple[NormalizedParameter, ...]:
    combined: dict[tuple[str, str], NormalizedParameter] = {}
    for collection in (path_parameters, operation_parameters):
        if not isinstance(collection, list):
            continue
        for raw_parameter in collection:
            if not isinstance(raw_parameter, dict):
                continue
            parameter = resolver.resolve(raw_parameter)
            name = parameter.get("name")
            location = parameter.get("in")
            if not isinstance(name, str) or not isinstance(location, str):
                continue
            raw_schema = parameter.get("schema", {})
            schema = _merge_all_of(raw_schema, resolver) if isinstance(raw_schema, dict) else {}
            combined[(name, location)] = NormalizedParameter(
                name=name,
                location=location,
                data_type=_schema_type(schema),
                required=bool(parameter.get("required", False)) or location == "path",
                enum=_enum_values(schema),
            )
    return tuple(combined[key] for key in sorted(combined))


def _normalize_responses(
    raw_responses: Any, resolver: LocalReferenceResolver
) -> dict[str, NormalizedResponse]:
    if not isinstance(raw_responses, dict):
        return {}
    responses: dict[str, NormalizedResponse] = {}
    for status in sorted(raw_responses, key=str):
        response = resolver.resolve(raw_responses[status])
        schema = _content_schema(response, resolver)
        status_code = str(status)
        responses[status_code] = NormalizedResponse(
            status_code=status_code,
            fields=_extract_fields(schema, resolver),
        )
    return responses


def _normalize_authentication(raw_security: Any) -> tuple[str, ...]:
    if not isinstance(raw_security, list):
        return ()
    schemes: set[str] = set()
    for requirement in raw_security:
        if isinstance(requirement, dict):
            schemes.update(str(name) for name in requirement)
    return tuple(sorted(schemes))


def normalize_openapi(document: dict[str, Any]) -> NormalizedContract:
    resolver = LocalReferenceResolver(document)
    operations: dict[str, NormalizedOperation] = {}
    global_security = document.get("security", [])
    for path in sorted(document["paths"]):
        raw_path_item = document["paths"][path]
        if not isinstance(raw_path_item, dict):
            continue
        path_item = resolver.resolve(raw_path_item)
        for method in sorted(set(path_item) & HTTP_METHODS):
            raw_operation = path_item[method]
            if not isinstance(raw_operation, dict):
                continue
            operation = resolver.resolve(raw_operation)
            security = operation.get("security", global_security)
            description_parts = [operation.get("summary", ""), operation.get("description", "")]
            normalized = NormalizedOperation(
                path=path,
                method=method.upper(),
                operation_id=operation.get("operationId"),
                description="\n".join(
                    str(part).strip() for part in description_parts if str(part).strip()
                ),
                parameters=_normalize_parameters(
                    path_item.get("parameters", []), operation.get("parameters", []), resolver
                ),
                request_fields=_extract_fields(
                    _content_schema(operation.get("requestBody", {}), resolver), resolver
                ),
                responses=_normalize_responses(operation.get("responses", {}), resolver),
                authentication=_normalize_authentication(security),
            )
            operations[operation_key(path, method)] = normalized
    info = document["info"]
    return NormalizedContract(
        title=info["title"],
        version=info["version"],
        openapi_version=document["openapi"],
        operations=operations,
    )
