"""Orchestrate specification validation, normalization, and comparison."""

from __future__ import annotations

import hashlib

from apps.api.app.domain.openapi import NormalizedContract
from apps.api.app.openapi.differ import ContractDiffer, categories
from apps.api.app.openapi.normalizer import normalize_openapi
from apps.api.app.openapi.parser import parse_openapi_document
from apps.api.app.schemas.comparison import (
    ChangeCategory,
    ComparisonResponse,
    ComparisonSummary,
    ContractMetadata,
)


class SpecificationComparisonService:
    def compare(
        self,
        *,
        old_filename: str,
        old_content: bytes,
        new_filename: str,
        new_content: bytes,
    ) -> ComparisonResponse:
        old_contract = normalize_openapi(parse_openapi_document(old_filename, old_content))
        new_contract = normalize_openapi(parse_openapi_document(new_filename, new_content))
        return self.compare_contracts(
            old_contract=old_contract,
            old_content=old_content,
            new_contract=new_contract,
            new_content=new_content,
        )

    def compare_contracts(
        self,
        *,
        old_contract: NormalizedContract,
        old_content: bytes,
        new_contract: NormalizedContract,
        new_content: bytes,
    ) -> ComparisonResponse:
        changes = ContractDiffer().compare(old_contract, new_contract)
        counts = categories(changes)
        return ComparisonResponse(
            old_contract=self._metadata(old_contract, old_content),
            new_contract=self._metadata(new_contract, new_content),
            summary=ComparisonSummary(
                total_changes=len(changes),
                breaking_changes=counts[ChangeCategory.BREAKING],
                potentially_breaking_changes=counts[ChangeCategory.POTENTIALLY_BREAKING],
                non_breaking_changes=counts[ChangeCategory.NON_BREAKING],
            ),
            changes=changes,
        )

    @staticmethod
    def _metadata(contract: NormalizedContract, content: bytes) -> ContractMetadata:
        return ContractMetadata(
            title=contract.title,
            version=contract.version,
            openapi_version=contract.openapi_version,
            sha256=hashlib.sha256(content).hexdigest(),
            operation_count=len(contract.operations),
        )
