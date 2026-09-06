"""Public schemas for contract comparison results."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ChangeCategory(StrEnum):
    NON_BREAKING = "non_breaking"
    POTENTIALLY_BREAKING = "potentially_breaking"
    BREAKING = "breaking"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ContractType(StrEnum):
    OPENAPI = "openapi"
    GRAPHQL = "graphql"


class OperationKind(StrEnum):
    HTTP_OPERATION = "http_operation"
    QUERY = "query"
    MUTATION = "mutation"
    SUBSCRIPTION = "subscription"
    OBJECT_FIELD = "object_field"
    INTERFACE_FIELD = "interface_field"
    INPUT_FIELD = "input_field"
    ENUM = "enum"
    TYPE = "type"


class ChangeType(StrEnum):
    ENDPOINT_ADDED = "endpoint_added"
    ENDPOINT_REMOVED = "endpoint_removed"
    HTTP_METHOD_ADDED = "http_method_added"
    HTTP_METHOD_REMOVED = "http_method_removed"
    REQUIRED_PARAMETER_ADDED = "required_parameter_added"
    OPTIONAL_PARAMETER_ADDED = "optional_parameter_added"
    PARAMETER_REMOVED = "parameter_removed"
    PARAMETER_RENAMED = "parameter_renamed"
    PARAMETER_TYPE_CHANGED = "parameter_data_type_changed"
    PARAMETER_LOCATION_CHANGED = "parameter_location_changed"
    REQUEST_FIELD_ADDED = "request_body_field_added"
    REQUIRED_REQUEST_FIELD_ADDED = "required_request_body_field_added"
    REQUEST_FIELD_REMOVED = "request_body_field_removed"
    REQUEST_FIELD_TYPE_CHANGED = "request_body_field_data_type_changed"
    RESPONSE_STATUS_ADDED = "response_status_code_added"
    RESPONSE_STATUS_REMOVED = "response_status_code_removed"
    RESPONSE_FIELD_ADDED = "response_field_added"
    RESPONSE_FIELD_REMOVED = "response_field_removed"
    RESPONSE_FIELD_TYPE_CHANGED = "response_field_data_type_changed"
    AUTHENTICATION_ADDED = "authentication_requirement_added"
    AUTHENTICATION_CHANGED = "authentication_method_changed"
    ENUM_VALUE_ADDED = "enum_value_added"
    ENUM_VALUE_REMOVED = "enum_value_removed"
    DESCRIPTION_ONLY = "description_only"
    TYPE_ADDED = "type_added"
    TYPE_REMOVED = "type_removed"
    FIELD_ADDED = "field_added"
    FIELD_REMOVED = "field_removed"
    INPUT_FIELD_ADDED = "input_field_added"
    REQUIRED_INPUT_FIELD_ADDED = "required_input_field_added"
    INPUT_FIELD_REMOVED = "input_field_removed"
    ARGUMENT_ADDED = "argument_added"
    REQUIRED_ARGUMENT_ADDED = "required_argument_added"
    ARGUMENT_REMOVED = "argument_removed"
    GRAPHQL_INPUT_TYPE_CHANGED = "graphql_input_type_changed"
    GRAPHQL_RETURN_TYPE_CHANGED = "graphql_return_type_changed"
    NULLABILITY_TIGHTENED = "nullability_tightened"
    NULLABILITY_RELAXED = "nullability_relaxed"


class ApiChange(BaseModel):
    change_id: str
    change_type: ChangeType
    path: str = ""
    method: str = ""
    subject: str | None = None
    old_value: Any = None
    new_value: Any = None
    breaking: bool
    category: ChangeCategory
    severity: Severity
    explanation: str
    contract_type: ContractType = ContractType.OPENAPI
    operation_kind: OperationKind = OperationKind.HTTP_OPERATION
    operation_identifier: str | None = None
    contract_location: str | None = None
    old_type: str | None = None
    new_type: str | None = None
    old_required: bool | None = None
    new_required: bool | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ComparisonSummary(BaseModel):
    total_changes: int = 0
    breaking_changes: int = 0
    potentially_breaking_changes: int = 0
    non_breaking_changes: int = 0


class ContractMetadata(BaseModel):
    title: str
    version: str
    openapi_version: str | None = None
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    operation_count: int

    contract_type: ContractType = ContractType.OPENAPI
    schema_version: str | None = None


class ComparisonResponse(BaseModel):
    old_contract: ContractMetadata
    new_contract: ContractMetadata
    summary: ComparisonSummary
    changes: list[ApiChange]
    analysis_id: str | None = None
    duplicate: bool = False
