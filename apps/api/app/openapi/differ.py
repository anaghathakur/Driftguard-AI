"""Deterministic rules for comparing normalized API contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from apps.api.app.domain.openapi import (
    NormalizedContract,
    NormalizedField,
    NormalizedOperation,
    NormalizedParameter,
)
from apps.api.app.schemas.comparison import (
    ApiChange,
    ChangeCategory,
    ChangeType,
    Severity,
)


class ContractDiffer:
    def __init__(self) -> None:
        self._changes: list[ApiChange] = []

    def compare(self, old: NormalizedContract, new: NormalizedContract) -> list[ApiChange]:
        self._changes = []
        old_keys = set(old.operations)
        new_keys = set(new.operations)
        old_paths = {operation.path for operation in old.operations.values()}
        new_paths = {operation.path for operation in new.operations.values()}

        for key in sorted(old_keys - new_keys):
            operation = old.operations[key]
            change_type = (
                ChangeType.ENDPOINT_REMOVED
                if operation.path not in new_paths
                else ChangeType.HTTP_METHOD_REMOVED
            )
            self._add(
                change_type,
                operation,
                old_value=key,
                new_value=None,
                category=ChangeCategory.BREAKING,
                severity=Severity.CRITICAL,
                explanation=f"{operation.method} {operation.path} is no longer available.",
            )
        for key in sorted(new_keys - old_keys):
            operation = new.operations[key]
            change_type = (
                ChangeType.ENDPOINT_ADDED
                if operation.path not in old_paths
                else ChangeType.HTTP_METHOD_ADDED
            )
            self._add(
                change_type,
                operation,
                old_value=None,
                new_value=key,
                category=ChangeCategory.NON_BREAKING,
                severity=Severity.LOW,
                explanation=f"{operation.method} {operation.path} is now available.",
            )
        for key in sorted(old_keys & new_keys):
            self._compare_operation(old.operations[key], new.operations[key])
        return sorted(
            self._changes,
            key=lambda change: (
                change.path,
                change.method,
                change.change_type.value,
                change.subject or "",
            ),
        )

    def _compare_operation(self, old: NormalizedOperation, new: NormalizedOperation) -> None:
        starting_change_count = len(self._changes)
        self._compare_parameters(old, new)
        self._compare_fields(old, new, old.request_fields, new.request_fields, "request")
        self._compare_responses(old, new)
        self._compare_authentication(old, new)
        if old.description != new.description and len(self._changes) == starting_change_count:
            self._add(
                ChangeType.DESCRIPTION_ONLY,
                new,
                subject="description",
                old_value=old.description,
                new_value=new.description,
                category=ChangeCategory.NON_BREAKING,
                severity=Severity.LOW,
                explanation="Only the operation documentation changed.",
            )

    def _compare_parameters(self, old: NormalizedOperation, new: NormalizedOperation) -> None:
        old_parameters = {(item.name, item.location): item for item in old.parameters}
        new_parameters = {(item.name, item.location): item for item in new.parameters}
        removed = set(old_parameters) - set(new_parameters)
        added = set(new_parameters) - set(old_parameters)

        for name in sorted({key[0] for key in removed} & {key[0] for key in added}):
            old_key = next(key for key in sorted(removed) if key[0] == name)
            new_key = next(key for key in sorted(added) if key[0] == name)
            old_parameter = old_parameters[old_key]
            new_parameter = new_parameters[new_key]
            self._add(
                ChangeType.PARAMETER_LOCATION_CHANGED,
                new,
                subject=name,
                old_value=old_parameter.location,
                new_value=new_parameter.location,
                category=ChangeCategory.BREAKING,
                severity=Severity.HIGH,
                explanation=(
                    f"Parameter '{name}' moved from {old_parameter.location} "
                    f"to {new_parameter.location}."
                ),
            )
            removed.remove(old_key)
            added.remove(new_key)

        for old_key in sorted(removed):
            old_parameter = old_parameters[old_key]
            candidates = [
                new_key
                for new_key in sorted(added)
                if _parameters_look_renamed(old_parameter, new_parameters[new_key])
            ]
            if len(candidates) != 1:
                continue
            new_key = candidates[0]
            reciprocal_candidates = [
                candidate
                for candidate in sorted(removed)
                if _parameters_look_renamed(old_parameters[candidate], new_parameters[new_key])
            ]
            if len(reciprocal_candidates) != 1:
                continue
            new_parameter = new_parameters[new_key]
            self._add(
                ChangeType.PARAMETER_RENAMED,
                new,
                subject=new_parameter.name,
                old_value=old_parameter.name,
                new_value=new_parameter.name,
                category=(
                    ChangeCategory.BREAKING
                    if new_parameter.required
                    else ChangeCategory.POTENTIALLY_BREAKING
                ),
                severity=Severity.HIGH if new_parameter.required else Severity.MEDIUM,
                explanation=(
                    f"Parameter '{old_parameter.name}' appears to have been renamed "
                    f"to '{new_parameter.name}'."
                ),
            )
            removed.remove(old_key)
            added.remove(new_key)

        for key in sorted(removed):
            parameter = old_parameters[key]
            self._add(
                ChangeType.PARAMETER_REMOVED,
                new,
                subject=parameter.name,
                old_value=parameter.model_dump(),
                new_value=None,
                category=ChangeCategory.POTENTIALLY_BREAKING,
                severity=Severity.MEDIUM,
                explanation=f"Parameter '{parameter.name}' was removed from {parameter.location}.",
            )
        for key in sorted(added):
            parameter = new_parameters[key]
            required = parameter.required
            self._add(
                ChangeType.REQUIRED_PARAMETER_ADDED
                if required
                else ChangeType.OPTIONAL_PARAMETER_ADDED,
                new,
                subject=parameter.name,
                old_value=None,
                new_value=parameter.model_dump(),
                category=ChangeCategory.BREAKING if required else ChangeCategory.NON_BREAKING,
                severity=Severity.HIGH if required else Severity.LOW,
                explanation=(
                    f"Required parameter '{parameter.name}' was added to {parameter.location}."
                    if required
                    else f"Optional parameter '{parameter.name}' was added to {parameter.location}."
                ),
            )
        for key in sorted(set(old_parameters) & set(new_parameters)):
            old_parameter = old_parameters[key]
            new_parameter = new_parameters[key]
            if old_parameter.data_type != new_parameter.data_type:
                self._add(
                    ChangeType.PARAMETER_TYPE_CHANGED,
                    new,
                    subject=old_parameter.name,
                    old_value=old_parameter.data_type,
                    new_value=new_parameter.data_type,
                    category=ChangeCategory.BREAKING,
                    severity=Severity.HIGH,
                    explanation=f"Parameter '{old_parameter.name}' changed data type.",
                )
            self._compare_enum(old, new, old_parameter, new_parameter, "parameter")

    def _compare_fields(
        self,
        old_operation: NormalizedOperation,
        new_operation: NormalizedOperation,
        old_fields: dict[str, NormalizedField],
        new_fields: dict[str, NormalizedField],
        context: str,
        status: str | None = None,
    ) -> None:
        old_names = set(old_fields)
        new_names = set(new_fields)
        for name in sorted(old_names - new_names):
            change_type = (
                ChangeType.REQUEST_FIELD_REMOVED
                if context == "request"
                else ChangeType.RESPONSE_FIELD_REMOVED
            )
            self._add(
                change_type,
                new_operation,
                subject=name,
                old_value=old_fields[name].model_dump(),
                new_value=None,
                category=(
                    ChangeCategory.POTENTIALLY_BREAKING
                    if context == "request"
                    else ChangeCategory.BREAKING
                ),
                severity=Severity.HIGH,
                explanation=(
                    f"{context.title()} field '{name}' was removed{_status_suffix(status)}."
                ),
            )
        for name in sorted(new_names - old_names):
            field = new_fields[name]
            if context == "request":
                change_type = (
                    ChangeType.REQUIRED_REQUEST_FIELD_ADDED
                    if field.required
                    else ChangeType.REQUEST_FIELD_ADDED
                )
                category = (
                    ChangeCategory.BREAKING if field.required else ChangeCategory.NON_BREAKING
                )
                severity = Severity.HIGH if field.required else Severity.LOW
            else:
                change_type = ChangeType.RESPONSE_FIELD_ADDED
                category = ChangeCategory.NON_BREAKING
                severity = Severity.LOW
            self._add(
                change_type,
                new_operation,
                subject=name,
                old_value=None,
                new_value=field.model_dump(),
                category=category,
                severity=severity,
                explanation=f"{context.title()} field '{name}' was added{_status_suffix(status)}.",
            )
        for name in sorted(old_names & new_names):
            old_field = old_fields[name]
            new_field = new_fields[name]
            if old_field.data_type != new_field.data_type:
                change_type = (
                    ChangeType.REQUEST_FIELD_TYPE_CHANGED
                    if context == "request"
                    else ChangeType.RESPONSE_FIELD_TYPE_CHANGED
                )
                self._add(
                    change_type,
                    new_operation,
                    subject=name,
                    old_value=old_field.data_type,
                    new_value=new_field.data_type,
                    category=ChangeCategory.BREAKING,
                    severity=Severity.HIGH,
                    explanation=(
                        f"{context.title()} field '{name}' changed data type"
                        f"{_status_suffix(status)}."
                    ),
                )
            if context == "request" and not old_field.required and new_field.required:
                self._add(
                    ChangeType.REQUIRED_REQUEST_FIELD_ADDED,
                    new_operation,
                    subject=name,
                    old_value={"required": False},
                    new_value={"required": True},
                    category=ChangeCategory.BREAKING,
                    severity=Severity.HIGH,
                    explanation=f"Request field '{name}' is now required.",
                )
            self._compare_enum(old_operation, new_operation, old_field, new_field, context)

    def _compare_responses(self, old: NormalizedOperation, new: NormalizedOperation) -> None:
        old_statuses = set(old.responses)
        new_statuses = set(new.responses)
        for status in sorted(old_statuses - new_statuses):
            self._add(
                ChangeType.RESPONSE_STATUS_REMOVED,
                new,
                subject=status,
                old_value=status,
                new_value=None,
                category=ChangeCategory.POTENTIALLY_BREAKING,
                severity=Severity.HIGH,
                explanation=f"Response status code {status} was removed.",
            )
        for status in sorted(new_statuses - old_statuses):
            self._add(
                ChangeType.RESPONSE_STATUS_ADDED,
                new,
                subject=status,
                old_value=None,
                new_value=status,
                category=ChangeCategory.NON_BREAKING,
                severity=Severity.LOW,
                explanation=f"Response status code {status} was added.",
            )
        for status in sorted(old_statuses & new_statuses):
            self._compare_fields(
                old,
                new,
                old.responses[status].fields,
                new.responses[status].fields,
                "response",
                status,
            )

    def _compare_authentication(self, old: NormalizedOperation, new: NormalizedOperation) -> None:
        if old.authentication == new.authentication:
            return
        added = not old.authentication and bool(new.authentication)
        self._add(
            ChangeType.AUTHENTICATION_ADDED if added else ChangeType.AUTHENTICATION_CHANGED,
            new,
            subject="authentication",
            old_value=list(old.authentication),
            new_value=list(new.authentication),
            category=ChangeCategory.BREAKING,
            severity=Severity.CRITICAL,
            explanation=(
                "Authentication is now required for this operation."
                if added
                else "The authentication schemes for this operation changed."
            ),
        )

    def _compare_enum(
        self,
        old_operation: NormalizedOperation,
        new_operation: NormalizedOperation,
        old_item: NormalizedField | NormalizedParameter,
        new_item: NormalizedField | NormalizedParameter,
        context: str,
    ) -> None:
        removed = sorted(set(old_item.enum) - set(new_item.enum))
        added = sorted(set(new_item.enum) - set(old_item.enum))
        for value in removed:
            self._add(
                ChangeType.ENUM_VALUE_REMOVED,
                new_operation,
                subject=old_item.name,
                old_value=value,
                new_value=None,
                category=ChangeCategory.BREAKING,
                severity=Severity.HIGH,
                explanation=f"Enum value '{value}' was removed from {context} '{old_item.name}'.",
            )
        for value in added:
            self._add(
                ChangeType.ENUM_VALUE_ADDED,
                new_operation,
                subject=new_item.name,
                old_value=None,
                new_value=value,
                category=ChangeCategory.NON_BREAKING,
                severity=Severity.LOW,
                explanation=f"Enum value '{value}' was added to {context} '{new_item.name}'.",
            )

    def _add(
        self,
        change_type: ChangeType,
        operation: NormalizedOperation,
        *,
        subject: str | None = None,
        old_value: Any,
        new_value: Any,
        category: ChangeCategory,
        severity: Severity,
        explanation: str,
    ) -> None:
        identity = json.dumps(
            [change_type.value, operation.path, operation.method, subject, old_value, new_value],
            sort_keys=True,
            default=str,
        )
        change_id = hashlib.sha256(identity.encode()).hexdigest()[:16]
        self._changes.append(
            ApiChange(
                change_id=change_id,
                change_type=change_type,
                path=operation.path,
                method=operation.method,
                subject=subject,
                old_value=old_value,
                new_value=new_value,
                breaking=category == ChangeCategory.BREAKING,
                category=category,
                severity=severity,
                explanation=explanation,
            )
        )


def _status_suffix(status: str | None) -> str:
    return f" in response {status}" if status else ""


def _parameters_look_renamed(old: NormalizedParameter, new: NormalizedParameter) -> bool:
    return (
        old.name != new.name
        and old.location == new.location
        and old.data_type == new.data_type
        and old.required == new.required
        and old.enum == new.enum
    )


def categories(changes: Iterable[ApiChange]) -> dict[ChangeCategory, int]:
    counts = {category: 0 for category in ChangeCategory}
    for change in changes:
        counts[change.category] += 1
    return counts
