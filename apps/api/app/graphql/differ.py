"""Deterministic GraphQL SDL compatibility rules."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from graphql import (
    GraphQLArgument,
    GraphQLEnumType,
    GraphQLField,
    GraphQLInputField,
    GraphQLInputObjectType,
    GraphQLInterfaceType,
    GraphQLObjectType,
    GraphQLSchema,
    is_list_type,
    is_non_null_type,
    is_specified_scalar_type,
)
from graphql.pyutils import Undefined

from apps.api.app.core.config import settings
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.graphql.parser import GraphQLContract
from apps.api.app.schemas.comparison import (
    ApiChange,
    ChangeCategory,
    ChangeType,
    OperationKind,
    Severity,
)


class GraphQLContractDiffer:
    def compare(self, old: GraphQLContract, new: GraphQLContract) -> list[ApiChange]:
        self._changes: list[ApiChange] = []
        old_types = _user_types(old.schema)
        new_types = _user_types(new.schema)
        for name in sorted(set(old_types) - set(new_types)):
            self._add(
                ChangeType.TYPE_REMOVED,
                name,
                OperationKind.TYPE,
                subject=name,
                old_value=_type_kind(old_types[name]),
                category=ChangeCategory.BREAKING,
                severity=Severity.CRITICAL,
                explanation=f"GraphQL type '{name}' was removed.",
            )
        for name in sorted(set(new_types) - set(old_types)):
            self._add(
                ChangeType.TYPE_ADDED,
                name,
                OperationKind.TYPE,
                subject=name,
                new_value=_type_kind(new_types[name]),
                category=ChangeCategory.NON_BREAKING,
                severity=Severity.LOW,
                explanation=f"GraphQL type '{name}' was added.",
            )
        for name in sorted(set(old_types) & set(new_types)):
            self._compare_type(name, old_types[name], new_types[name], old.schema, new.schema)
        maximum = getattr(settings, "max_graphql_changes", 1_000)
        if len(self._changes) > maximum:
            raise DriftGuardError(
                code="graphql_change_limit_exceeded",
                message="The GraphQL comparison produced too many changes.",
                status_code=413,
                details={"maximum": maximum},
            )
        return sorted(
            self._changes,
            key=lambda item: (
                item.operation_identifier or "",
                item.change_type.value,
                item.subject or "",
            ),
        )

    def _compare_type(
        self, name: str, old: Any, new: Any, old_schema: GraphQLSchema, new_schema: GraphQLSchema
    ) -> None:
        if type(old) is not type(new):
            self._add(
                ChangeType.GRAPHQL_RETURN_TYPE_CHANGED,
                name,
                OperationKind.TYPE,
                subject=name,
                old_type=_type_kind(old),
                new_type=_type_kind(new),
                category=ChangeCategory.BREAKING,
                severity=Severity.HIGH,
                explanation=f"GraphQL type '{name}' changed kind.",
            )
            return
        if isinstance(old, (GraphQLObjectType, GraphQLInterfaceType)):
            self._compare_output_fields(name, old, new, old_schema, new_schema)
        elif isinstance(old, GraphQLInputObjectType):
            self._compare_input_fields(name, old, new)
        elif isinstance(old, GraphQLEnumType):
            self._compare_enum(name, old, new)

    def _compare_output_fields(
        self,
        type_name: str,
        old: GraphQLObjectType | GraphQLInterfaceType,
        new: GraphQLObjectType | GraphQLInterfaceType,
        old_schema: GraphQLSchema,
        new_schema: GraphQLSchema,
    ) -> None:
        old_names, new_names = set(old.fields), set(new.fields)
        for field_name in sorted(old_names - new_names):
            identifier = f"{type_name}.{field_name}"
            self._add(
                ChangeType.FIELD_REMOVED,
                identifier,
                _operation_kind(type_name, old_schema, isinstance(old, GraphQLInterfaceType)),
                subject=field_name,
                old_type=str(old.fields[field_name].type),
                category=ChangeCategory.BREAKING,
                severity=Severity.HIGH,
                explanation=f"GraphQL field '{identifier}' was removed.",
            )
        for field_name in sorted(new_names - old_names):
            identifier = f"{type_name}.{field_name}"
            self._add(
                ChangeType.FIELD_ADDED,
                identifier,
                _operation_kind(type_name, new_schema, isinstance(new, GraphQLInterfaceType)),
                subject=field_name,
                new_type=str(new.fields[field_name].type),
                category=ChangeCategory.NON_BREAKING,
                severity=Severity.LOW,
                explanation=f"GraphQL output field '{identifier}' was added.",
            )
        for field_name in sorted(old_names & new_names):
            identifier = f"{type_name}.{field_name}"
            old_field, new_field = old.fields[field_name], new.fields[field_name]
            self._compare_arguments(identifier, old_field, new_field, new_schema)
            if str(old_field.type) != str(new_field.type):
                category = _output_type_category(old_field.type, new_field.type)
                self._add(
                    ChangeType.GRAPHQL_RETURN_TYPE_CHANGED,
                    identifier,
                    _operation_kind(type_name, new_schema, isinstance(new, GraphQLInterfaceType)),
                    subject=field_name,
                    old_type=str(old_field.type),
                    new_type=str(new_field.type),
                    category=category,
                    severity=Severity.HIGH
                    if category is ChangeCategory.BREAKING
                    else Severity.MEDIUM,
                    explanation=(
                        f"GraphQL field '{identifier}' changed return type from "
                        f"{old_field.type} to {new_field.type}."
                    ),
                )

    def _compare_arguments(
        self, identifier: str, old: GraphQLField, new: GraphQLField, schema: GraphQLSchema
    ) -> None:
        old_names, new_names = set(old.args), set(new.args)
        for name in sorted(old_names - new_names):
            argument = old.args[name]
            self._add(
                ChangeType.ARGUMENT_REMOVED,
                identifier,
                _operation_kind(identifier.split(".", 1)[0], schema),
                subject=name,
                old_type=str(argument.type),
                old_required=_required(argument),
                category=ChangeCategory.BREAKING,
                severity=Severity.HIGH,
                explanation=f"Argument '{name}' was removed from GraphQL field '{identifier}'.",
            )
        for name in sorted(new_names - old_names):
            argument = new.args[name]
            required = _required(argument)
            self._add(
                ChangeType.REQUIRED_ARGUMENT_ADDED if required else ChangeType.ARGUMENT_ADDED,
                identifier,
                _operation_kind(identifier.split(".", 1)[0], schema),
                subject=name,
                new_type=str(argument.type),
                new_required=required,
                category=ChangeCategory.BREAKING if required else ChangeCategory.NON_BREAKING,
                severity=Severity.HIGH if required else Severity.LOW,
                explanation=(
                    f"Required argument '{name}: {argument.type}' was added to '{identifier}'."
                    if required
                    else f"Optional argument '{name}: {argument.type}' was added to '{identifier}'."
                ),
            )
        for name in sorted(old_names & new_names):
            old_arg, new_arg = old.args[name], new.args[name]
            if str(old_arg.type) == str(new_arg.type):
                continue
            category, change_type = _input_type_change(old_arg.type, new_arg.type)
            self._add(
                change_type,
                identifier,
                _operation_kind(identifier.split(".", 1)[0], schema),
                subject=name,
                old_type=str(old_arg.type),
                new_type=str(new_arg.type),
                old_required=_required(old_arg),
                new_required=_required(new_arg),
                category=category,
                severity=Severity.HIGH if category is ChangeCategory.BREAKING else Severity.LOW,
                explanation=(
                    f"Argument '{name}' on '{identifier}' changed type from "
                    f"{old_arg.type} to {new_arg.type}."
                ),
            )

    def _compare_input_fields(
        self, type_name: str, old: GraphQLInputObjectType, new: GraphQLInputObjectType
    ) -> None:
        old_names, new_names = set(old.fields), set(new.fields)
        for name in sorted(old_names - new_names):
            field = old.fields[name]
            self._add(
                ChangeType.INPUT_FIELD_REMOVED,
                f"{type_name}.{name}",
                OperationKind.INPUT_FIELD,
                subject=name,
                old_type=str(field.type),
                old_required=_required(field),
                category=ChangeCategory.BREAKING,
                severity=Severity.HIGH,
                explanation=f"Input field '{type_name}.{name}' was removed.",
            )
        for name in sorted(new_names - old_names):
            field = new.fields[name]
            required = _required(field)
            self._add(
                ChangeType.REQUIRED_INPUT_FIELD_ADDED if required else ChangeType.INPUT_FIELD_ADDED,
                f"{type_name}.{name}",
                OperationKind.INPUT_FIELD,
                subject=name,
                new_type=str(field.type),
                new_required=required,
                category=ChangeCategory.BREAKING if required else ChangeCategory.NON_BREAKING,
                severity=Severity.HIGH if required else Severity.LOW,
                explanation=(
                    f"Required input field '{type_name}.{name}: {field.type}' was added."
                    if required
                    else f"Optional input field '{type_name}.{name}: {field.type}' was added."
                ),
            )
        for name in sorted(old_names & new_names):
            old_field, new_field = old.fields[name], new.fields[name]
            if str(old_field.type) == str(new_field.type):
                continue
            category, change_type = _input_type_change(old_field.type, new_field.type)
            self._add(
                change_type,
                f"{type_name}.{name}",
                OperationKind.INPUT_FIELD,
                subject=name,
                old_type=str(old_field.type),
                new_type=str(new_field.type),
                old_required=_required(old_field),
                new_required=_required(new_field),
                category=category,
                severity=Severity.HIGH if category is ChangeCategory.BREAKING else Severity.LOW,
                explanation=(
                    f"Input field '{type_name}.{name}' changed type from "
                    f"{old_field.type} to {new_field.type}."
                ),
            )

    def _compare_enum(self, name: str, old: GraphQLEnumType, new: GraphQLEnumType) -> None:
        for value in sorted(set(old.values) - set(new.values)):
            self._add(
                ChangeType.ENUM_VALUE_REMOVED,
                name,
                OperationKind.ENUM,
                subject=value,
                old_value=value,
                category=ChangeCategory.BREAKING,
                severity=Severity.HIGH,
                explanation=f"Enum value '{name}.{value}' was removed.",
            )
        for value in sorted(set(new.values) - set(old.values)):
            self._add(
                ChangeType.ENUM_VALUE_ADDED,
                name,
                OperationKind.ENUM,
                subject=value,
                new_value=value,
                category=ChangeCategory.POTENTIALLY_BREAKING,
                severity=Severity.MEDIUM,
                explanation=(
                    f"Enum value '{name}.{value}' was added; exhaustive consumers may need review."
                ),
            )

    def _add(
        self,
        change_type: ChangeType,
        identifier: str,
        operation_kind: OperationKind,
        *,
        subject: str | None = None,
        old_value: Any = None,
        new_value: Any = None,
        old_type: str | None = None,
        new_type: str | None = None,
        old_required: bool | None = None,
        new_required: bool | None = None,
        category: ChangeCategory,
        severity: Severity,
        explanation: str,
    ) -> None:
        payload = [
            "graphql",
            change_type.value,
            identifier,
            subject,
            old_value,
            new_value,
            old_type,
            new_type,
        ]
        change_id = hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()
        ).hexdigest()[:24]
        self._changes.append(
            ApiChange(
                change_id=change_id,
                change_type=change_type,
                subject=subject,
                old_value=old_value,
                new_value=new_value,
                breaking=category is ChangeCategory.BREAKING,
                category=category,
                severity=severity,
                explanation=explanation,
                contract_type="graphql",
                operation_kind=operation_kind,
                operation_identifier=identifier,
                contract_location=identifier,
                old_type=old_type,
                new_type=new_type,
                old_required=old_required,
                new_required=new_required,
                metadata={"schema_subject": identifier},
            )
        )


def _user_types(schema: GraphQLSchema) -> dict[str, Any]:
    return {
        name: value
        for name, value in schema.type_map.items()
        if not name.startswith("__") and not is_specified_scalar_type(value)
    }


def _type_kind(value: Any) -> str:
    return value.__class__.__name__.removeprefix("GraphQL").removesuffix("Type").lower()


def _required(value: GraphQLArgument | GraphQLInputField) -> bool:
    return is_non_null_type(value.type) and value.default_value is Undefined


def _operation_kind(
    type_name: str, schema: GraphQLSchema, interface: bool = False
) -> OperationKind:
    if schema.query_type and schema.query_type.name == type_name:
        return OperationKind.QUERY
    if schema.mutation_type and schema.mutation_type.name == type_name:
        return OperationKind.MUTATION
    if schema.subscription_type and schema.subscription_type.name == type_name:
        return OperationKind.SUBSCRIPTION
    return OperationKind.INTERFACE_FIELD if interface else OperationKind.OBJECT_FIELD


def _shape(value: Any) -> tuple[str, ...]:
    result: list[str] = []
    current = value
    while is_non_null_type(current) or is_list_type(current):
        if is_non_null_type(current):
            result.append("!")
        else:
            result.append("[]")
        current = current.of_type
    result.append(str(current))
    return tuple(result)


def _input_type_change(old: Any, new: Any) -> tuple[ChangeCategory, ChangeType]:
    if not is_non_null_type(old) and is_non_null_type(new) and str(old) == str(new.of_type):
        return ChangeCategory.BREAKING, ChangeType.NULLABILITY_TIGHTENED
    if is_non_null_type(old) and not is_non_null_type(new) and str(old.of_type) == str(new):
        return ChangeCategory.NON_BREAKING, ChangeType.NULLABILITY_RELAXED
    if _shape(old) != _shape(new):
        return ChangeCategory.BREAKING, ChangeType.GRAPHQL_INPUT_TYPE_CHANGED
    return ChangeCategory.POTENTIALLY_BREAKING, ChangeType.GRAPHQL_INPUT_TYPE_CHANGED


def _output_type_category(old: Any, new: Any) -> ChangeCategory:
    if is_non_null_type(old) and not is_non_null_type(new) and str(old.of_type) == str(new):
        return ChangeCategory.BREAKING
    if not is_non_null_type(old) and is_non_null_type(new) and str(old) == str(new.of_type):
        return ChangeCategory.POTENTIALLY_BREAKING
    return (
        ChangeCategory.BREAKING
        if _shape(old) != _shape(new)
        else ChangeCategory.POTENTIALLY_BREAKING
    )
