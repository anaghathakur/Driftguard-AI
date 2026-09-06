"""GraphQL SDL contract adapter."""

from __future__ import annotations

import hashlib

from apps.api.app.graphql.differ import GraphQLContractDiffer
from apps.api.app.graphql.parser import GRAPHQL_EXTENSIONS, GraphQLContract, parse_graphql_schema
from apps.api.app.schemas.comparison import (
    ChangeCategory,
    ComparisonResponse,
    ComparisonSummary,
    ContractMetadata,
    ContractType,
)


class GraphQLContractAdapter:
    contract_type = ContractType.GRAPHQL

    def can_handle(self, filename: str, content: bytes) -> bool:
        del content
        return filename.lower().endswith(GRAPHQL_EXTENSIONS)

    def parse(self, filename: str, content: bytes) -> GraphQLContract:
        return parse_graphql_schema(filename, content)

    def compare_parsed(
        self,
        old_contract: GraphQLContract,
        old_content: bytes,
        new_contract: GraphQLContract,
        new_content: bytes,
    ) -> ComparisonResponse:
        changes = GraphQLContractDiffer().compare(old_contract, new_contract)
        return ComparisonResponse(
            old_contract=_metadata(old_contract, old_content),
            new_contract=_metadata(new_contract, new_content),
            summary=ComparisonSummary(
                total_changes=len(changes),
                breaking_changes=sum(item.category is ChangeCategory.BREAKING for item in changes),
                potentially_breaking_changes=sum(
                    item.category is ChangeCategory.POTENTIALLY_BREAKING for item in changes
                ),
                non_breaking_changes=sum(
                    item.category is ChangeCategory.NON_BREAKING for item in changes
                ),
            ),
            changes=changes,
        )


def _metadata(contract: GraphQLContract, content: bytes) -> ContractMetadata:
    return ContractMetadata(
        title=contract.title,
        version=contract.version,
        sha256=hashlib.sha256(content).hexdigest(),
        operation_count=contract.operation_count,
        contract_type=ContractType.GRAPHQL,
        schema_version="GraphQL SDL",
    )
