"""Small internal adapter boundary used by the analysis pipeline."""

from __future__ import annotations

from typing import Any, Protocol

from apps.api.app.schemas.comparison import ComparisonResponse, ContractType


class ContractAdapter(Protocol):
    contract_type: ContractType

    def can_handle(self, filename: str, content: bytes) -> bool: ...

    def parse(self, filename: str, content: bytes) -> Any: ...

    def compare_parsed(
        self, old_contract: Any, old_content: bytes, new_contract: Any, new_content: bytes
    ) -> ComparisonResponse: ...
