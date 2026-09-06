"""Backward-compatible adapter around the existing OpenAPI implementation."""

from __future__ import annotations

from apps.api.app.domain.openapi import NormalizedContract
from apps.api.app.openapi.normalizer import normalize_openapi
from apps.api.app.openapi.parser import SUPPORTED_EXTENSIONS, parse_openapi_document
from apps.api.app.schemas.comparison import ComparisonResponse, ContractType
from apps.api.app.services.comparison import SpecificationComparisonService


class OpenAPIContractAdapter:
    contract_type = ContractType.OPENAPI

    def can_handle(self, filename: str, content: bytes) -> bool:
        del content
        return any(filename.lower().endswith(extension) for extension in SUPPORTED_EXTENSIONS)

    def parse(self, filename: str, content: bytes) -> NormalizedContract:
        return normalize_openapi(parse_openapi_document(filename, content))

    def compare_parsed(
        self,
        old_contract: NormalizedContract,
        old_content: bytes,
        new_contract: NormalizedContract,
        new_content: bytes,
    ) -> ComparisonResponse:
        response = SpecificationComparisonService().compare_contracts(
            old_contract=old_contract,
            old_content=old_content,
            new_contract=new_contract,
            new_content=new_content,
        )
        return response.model_copy(
            update={
                "old_contract": response.old_contract.model_copy(
                    update={"contract_type": ContractType.OPENAPI}
                ),
                "new_contract": response.new_contract.model_copy(
                    update={"contract_type": ContractType.OPENAPI}
                ),
                "changes": [
                    change.model_copy(
                        update={
                            "contract_type": ContractType.OPENAPI,
                            "operation_identifier": f"{change.method.upper()} {change.path}",
                        }
                    )
                    for change in response.changes
                ],
            }
        )
