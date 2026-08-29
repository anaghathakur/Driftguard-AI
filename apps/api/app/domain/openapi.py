"""Normalized OpenAPI domain models independent of source document layout."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DomainModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class NormalizedField(DomainModel):
    name: str
    data_type: str = "unknown"
    required: bool = False
    enum: tuple[str, ...] = ()


class NormalizedParameter(DomainModel):
    name: str
    location: str
    data_type: str = "unknown"
    required: bool = False
    enum: tuple[str, ...] = ()


class NormalizedResponse(DomainModel):
    status_code: str
    fields: dict[str, NormalizedField] = Field(default_factory=dict)


class NormalizedOperation(DomainModel):
    path: str
    method: str
    operation_id: str | None = None
    description: str = ""
    parameters: tuple[NormalizedParameter, ...] = ()
    request_fields: dict[str, NormalizedField] = Field(default_factory=dict)
    responses: dict[str, NormalizedResponse] = Field(default_factory=dict)
    authentication: tuple[str, ...] = ()


class NormalizedContract(DomainModel):
    title: str
    version: str
    openapi_version: str
    operations: dict[str, NormalizedOperation] = Field(default_factory=dict)


def operation_key(path: str, method: str) -> str:
    return f"{method.upper()} {path}"
