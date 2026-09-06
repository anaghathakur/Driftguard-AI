"""Explicit, non-dynamic registry for supported contract adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.api.app.contracts.adapter import ContractAdapter
from apps.api.app.contracts.graphql_adapter import GraphQLContractAdapter
from apps.api.app.contracts.openapi_adapter import OpenAPIContractAdapter
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.schemas.comparison import ComparisonResponse, ContractType


@dataclass(frozen=True, slots=True)
class PreparedContractComparison:
    contract_type: ContractType
    adapter: ContractAdapter
    old_contract: Any
    new_contract: Any
    response: ComparisonResponse


class ContractAdapterRegistry:
    def __init__(self, adapters: tuple[ContractAdapter, ...] | None = None) -> None:
        self.adapters = adapters or (OpenAPIContractAdapter(), GraphQLContractAdapter())

    def detect(self, filename: str, content: bytes) -> ContractAdapter:
        matches = [adapter for adapter in self.adapters if adapter.can_handle(filename, content)]
        if len(matches) != 1:
            raise DriftGuardError(
                code="unsupported_contract_type",
                message="The contract must be OpenAPI 3.x JSON/YAML or GraphQL SDL.",
            )
        return matches[0]

    def resolve(
        self, filename: str, content: bytes, requested: ContractType | str | None = None
    ) -> ContractAdapter:
        if requested is None or requested == "auto":
            return self.detect(filename, content)
        try:
            contract_type = ContractType(requested)
        except ValueError as exc:
            raise DriftGuardError(
                code="unsupported_contract_type",
                message="The selected contract type is not supported.",
            ) from exc
        adapter = next(item for item in self.adapters if item.contract_type is contract_type)
        if not adapter.can_handle(filename, content):
            raise DriftGuardError(
                code="contract_type_mismatch",
                message="The selected contract type does not match the uploaded file.",
            )
        return adapter

    def prepare_comparison(
        self,
        *,
        old_filename: str,
        old_content: bytes,
        new_filename: str,
        new_content: bytes,
        requested: ContractType | str | None = None,
    ) -> PreparedContractComparison:
        old_adapter = self.resolve(old_filename, old_content, requested)
        new_adapter = self.resolve(new_filename, new_content, requested)
        if old_adapter.contract_type is not new_adapter.contract_type:
            raise DriftGuardError(
                code="contract_type_mismatch",
                message="Old and new contracts must use the same contract type.",
            )
        old_contract = old_adapter.parse(old_filename, old_content)
        new_contract = new_adapter.parse(new_filename, new_content)
        response = old_adapter.compare_parsed(old_contract, old_content, new_contract, new_content)
        return PreparedContractComparison(
            old_adapter.contract_type, old_adapter, old_contract, new_contract, response
        )


default_contract_registry = ContractAdapterRegistry()
