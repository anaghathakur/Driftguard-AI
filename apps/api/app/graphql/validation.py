"""Deterministic static checks for patched GraphQL consumer documents."""

from __future__ import annotations

import re

from graphql import GraphQLError, GraphQLSchema, parse, validate
from graphql.language import FieldNode, OperationDefinitionNode, print_ast

from apps.api.app.domain.repository import RepositoryScan
from apps.api.app.graphql.impact import _fields, _parse_documents
from apps.api.app.schemas.comparison import ApiChange, ChangeType
from apps.api.app.schemas.validation import (
    FindingCategory,
    FindingSeverity,
    FindingStatus,
    ValidationFinding,
)


def validate_graphql_contract(
    changes: list[ApiChange],
    scan: RepositoryScan,
    *,
    new_schema: GraphQLSchema | None = None,
) -> list[ValidationFinding]:
    documents = _parse_documents(scan)
    findings: list[ValidationFinding] = _parse_findings(scan)
    if new_schema is not None:
        findings.extend(_schema_findings(documents, new_schema))
    for change in changes:
        if change.change_type not in {
            ChangeType.ARGUMENT_REMOVED,
            ChangeType.REQUIRED_ARGUMENT_ADDED,
            ChangeType.GRAPHQL_INPUT_TYPE_CHANGED,
            ChangeType.NULLABILITY_TIGHTENED,
        }:
            continue
        fields = [
            (parsed, operation, field)
            for parsed in documents
            for operation, field in _operation_fields(change, parsed.document)
        ]
        if not fields:
            findings.append(
                _finding(
                    change,
                    FindingStatus.UNKNOWN,
                    FindingSeverity.MEDIUM,
                    "No statically parsed GraphQL consumer operation could be validated.",
                )
            )
            continue
        for index, (parsed, operation, field) in enumerate(fields):
            arguments = {item.name.value: item for item in field.arguments}
            present = bool(change.subject and change.subject in arguments)
            if change.change_type is ChangeType.ARGUMENT_REMOVED:
                status = FindingStatus.FAIL if present else FindingStatus.PASS
                message = (
                    f"Removed GraphQL argument '{change.subject}' is still supplied."
                    if present
                    else f"Removed GraphQL argument '{change.subject}' is absent."
                )
            else:
                status = FindingStatus.PASS if present else FindingStatus.FAIL
                message = (
                    f"Required GraphQL argument '{change.subject}' is supplied."
                    if present
                    else f"Required GraphQL argument '{change.subject}' is missing."
                )
                if present and change.new_type:
                    variable_name = getattr(arguments[change.subject].value, "name", None)
                    variable = variable_name.value if variable_name else None
                    declared = _variable_type(operation, variable)
                    if variable and declared and declared != change.new_type:
                        status = FindingStatus.FAIL
                        message = (
                            f"GraphQL variable '${variable}' uses {declared}; "
                            f"the contract requires {change.new_type}."
                        )
                    elif variable and declared is None:
                        status = FindingStatus.UNKNOWN
                        message = (
                            f"GraphQL variable '${variable}' could not be resolved statically."
                        )
            findings.append(
                _finding(
                    change,
                    status,
                    FindingSeverity.HIGH if status is FindingStatus.FAIL else FindingSeverity.INFO,
                    message,
                    suffix=f":{index}",
                    file_path=parsed.file.path,
                    line=(field.loc.start_token.line if field.loc else None),
                )
            )
    return findings


def validate_graphql_document(content: str) -> None:
    try:
        parse(content)
    except GraphQLError as exc:
        raise ValueError("Invalid GraphQL document") from exc


def _schema_findings(documents, schema: GraphQLSchema) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    for parsed in documents:
        for index, error in enumerate(validate(schema, parsed.document)):
            location = error.locations[0] if error.locations else None
            findings.append(
                ValidationFinding(
                    check_id=f"graphql:schema:{parsed.file.path}:{index}",
                    category=FindingCategory.STATIC_ANALYSIS,
                    status=FindingStatus.FAIL,
                    severity=FindingSeverity.HIGH,
                    message=_safe_schema_message(error),
                    file_path=parsed.file.path,
                    line=location.line if location else None,
                    column=location.column if location else None,
                )
            )
    return findings


def _parse_findings(scan: RepositoryScan) -> list[ValidationFinding]:
    """Surface malformed embedded documents instead of silently skipping them."""

    findings: list[ValidationFinding] = []
    for source in scan.files:
        candidates = _document_candidates(source.path, source.content)
        for index, (body, offset) in enumerate(candidates):
            try:
                parse(body, no_location=False)
            except GraphQLError:
                line = source.content.count("\n", 0, offset) + 1
                findings.append(
                    ValidationFinding(
                        check_id=f"graphql:syntax:{source.path}:{index}",
                        category=FindingCategory.STATIC_ANALYSIS,
                        status=FindingStatus.FAIL,
                        severity=FindingSeverity.HIGH,
                        message="A patched GraphQL consumer document has invalid syntax.",
                        file_path=source.path,
                        line=line,
                    )
                )
    return findings


def _document_candidates(path: str, content: str) -> list[tuple[str, int]]:
    suffix = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    if suffix in {"graphql", "gql"}:
        return [(content, 0)]
    if suffix in {"js", "jsx", "ts", "tsx"}:
        return [
            (match.group("body"), match.start("body"))
            for match in re.finditer(
                r"(?:\b(?:gql|graphql)\s*)`(?P<body>[\s\S]*?)`", content, re.MULTILINE
            )
        ]
    if suffix == "py":
        return [
            (match.group("body"), match.start("body"))
            for match in re.finditer(
                r"(?P<quote>'''|\"\"\")(?P<body>[\s\S]*?)(?P=quote)", content, re.MULTILINE
            )
            if re.search(
                r"\b(query|mutation|subscription|fragment)\b|\{\s*[_A-Za-z]",
                match.group("body"),
            )
        ]
    return []


def _safe_schema_message(error: GraphQLError) -> str:
    message = error.message
    if "is never used" in message:
        return "A GraphQL operation has an unused variable."
    if "is not defined" in message:
        return "A GraphQL operation references an undefined variable."
    if "Cannot query field" in message:
        return "A GraphQL operation selects a field that is absent from the new schema."
    if "Unknown argument" in message:
        return "A GraphQL operation supplies an argument that is absent from the new schema."
    if "is required" in message:
        return "A GraphQL operation is missing a required argument or input field."
    if "Expected type" in message or "Variable" in message:
        return "A GraphQL operation has an incompatible variable, enum, or input value."
    return "A GraphQL operation does not validate against the new schema."


def _operation_fields(change: ApiChange, document):
    parent, _, target = (change.operation_identifier or "").partition(".")
    fragments = {
        definition.name.value: definition
        for definition in document.definitions
        if definition.kind == "fragment_definition"
    }
    for definition in document.definitions:
        if not isinstance(definition, OperationDefinitionNode):
            continue
        if definition.operation.value.title() != parent:
            continue
        for field, depth in _fields(definition.selection_set, fragments):
            if depth == 0 and isinstance(field, FieldNode) and field.name.value == target:
                yield definition, field


def _variable_type(operation: OperationDefinitionNode, name: str | None) -> str | None:
    if not name:
        return None
    for definition in operation.variable_definitions or ():
        if definition.variable.name.value == name:
            return print_ast(definition.type)
    return None


def _finding(
    change: ApiChange,
    status: FindingStatus,
    severity: FindingSeverity,
    message: str,
    *,
    suffix: str = "",
    file_path: str | None = None,
    line: int | None = None,
) -> ValidationFinding:
    return ValidationFinding(
        check_id=f"graphql:{change.change_id}{suffix}",
        category=FindingCategory.REQUIRED_REQUEST_FIELD,
        status=status,
        severity=severity,
        message=message,
        change_id=change.change_id,
        file_path=file_path,
        line=line,
    )
