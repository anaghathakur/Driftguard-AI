"""Validated contract discovery for immutable repository snapshots."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import PurePosixPath
from uuid import uuid4

from apps.api.app.contracts.registry import default_contract_registry
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.domain.automation import ContractKind, RepositoryContract
from apps.api.app.domain.workspace import GitHubInstallation, RepositoryConnection
from apps.api.app.github.automation_provider import GitHubAutomationProvider
from apps.api.app.github.webhooks import CONTRACT_NAMES, LIKELY_DIRECTORIES
from apps.api.app.ports.automation_repository import AutomationRepository

MAX_DISCOVERY_CANDIDATES = 100


class ContractDiscoveryService:
    def __init__(
        self, repository: AutomationRepository, provider: GitHubAutomationProvider
    ) -> None:
        self.repository = repository
        self.provider = provider

    async def discover(
        self,
        installation: GitHubInstallation,
        connection: RepositoryConnection,
        commit_sha: str,
        *,
        paths: list[str] | None = None,
    ) -> list[RepositoryContract]:
        candidates = paths
        if candidates is None:
            candidates = await self.provider.list_paths(
                installation.github_installation_id, connection, commit_sha
            )
        selected = [path for path in candidates if is_contract_candidate(path)]
        if len(selected) > MAX_DISCOVERY_CANDIDATES:
            selected = selected[:MAX_DISCOVERY_CANDIDATES]
        existing = {
            item.path: item
            for item in self.repository.list_contracts(
                connection.workspace_id, connection.connection_id
            )
        }
        discovered: list[RepositoryContract] = []
        now = datetime.now(UTC)
        for path in selected:
            try:
                content = await self.provider.fetch_file(
                    installation.github_installation_id, connection, path, commit_sha
                )
                adapter = default_contract_registry.resolve(path, content)
                document = adapter.parse(path, content)
            except DriftGuardError as exc:
                if exc.code in {
                    "invalid_specification_syntax",
                    "invalid_openapi_document",
                    "unsupported_openapi_version",
                    "github_file_not_found",
                    "graphql_parse_error",
                    "graphql_schema_invalid",
                    "invalid_graphql_contract",
                    "unsupported_contract_type",
                }:
                    continue
                raise
            current = existing.get(path)
            contract = RepositoryContract(
                current.contract_id if current else str(uuid4()),
                connection.workspace_id,
                connection.connection_id,
                path,
                ContractKind(adapter.contract_type.value),
                str(document.title),
                str(document.version),
                current.discovered_at if current else now,
                now,
                commit_sha,
                current.enabled if current else True,
                current.manually_configured if current else False,
            )
            discovered.append(self.repository.upsert_contract(contract))
        return discovered


def is_contract_candidate(path: str) -> bool:
    normalized = path.replace("\\", "/").strip("/")
    pure = PurePosixPath(normalized)
    if not normalized or ".." in pure.parts:
        return False
    if pure.suffix.lower() not in {".json", ".yaml", ".yml", ".graphql", ".gql"}:
        return False
    if pure.name.lower() in CONTRACT_NAMES:
        return True
    return bool({part.lower() for part in pure.parts[:-1]} & LIKELY_DIRECTORIES)
