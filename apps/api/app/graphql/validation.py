"""Deterministic static checks for patched GraphQL consumer documents."""

from __future__ import annotations

from graphql import GraphQLError, parse
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
    changes: list[ApiChange], scan: RepositoryScan
) -> list[ValidationFinding]:
    documents = _parse_documents(scan)
    findings: list[ValidationFinding] = []
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
