from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from apps.api.app.core import config
from apps.api.app.core.dependencies import get_github_repository_source
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.github import installations as installations_module
from apps.api.app.github.installations import (
    GitHubRepositoryInfo,
    RealGitHubInstallationProvider,
)
from apps.api.app.main import app
from apps.api.app.repository.github_source import GitHubRepositoryArchive


def _graphql_upload(name: str, content: bytes) -> tuple[str, bytes, str]:
    return (name, content, "application/graphql")


def _large_graphql_schema(field_count: int = 5_500) -> bytes:
    fields = "\n".join(f"  field{index}: String" for index in range(field_count))
    return f"type Query {{\n{fields}\n}}\n".encode()


def _openapi_upload(name: str) -> tuple[str, bytes, str]:
    content = json.dumps(
        {
            "openapi": "3.0.3",
            "info": {"title": "Limit regression", "version": "1.0.0"},
            "paths": {},
        }
    ).encode()
    return (name, content, "application/json")


def _archive_with_entries(entry_count: int) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for index in range(entry_count):
            archive.writestr(f"repository/docs/file-{index:05d}.txt", b"bounded fixture")
    return output.getvalue()


class _StaticGitHubSource:
    def __init__(self, content: bytes) -> None:
        self.content = content

    async def fetch(self, repository_url: str, ref: str | None = None) -> GitHubRepositoryArchive:
        del repository_url
        return GitHubRepositoryArchive(
            owner="example",
            repository="large-repository",
            ref=ref or "main",
            filename="large-repository.zip",
            content=self.content,
            commit_sha="a" * 40,
        )


def test_contract_http_route_honors_raised_graphql_ast_limit_after_prior_failure(
    client, monkeypatch
) -> None:
    schema = _large_graphql_schema()
    files = {
        "old_contract": _graphql_upload("schema-main.graphql", schema),
        "new_contract": _graphql_upload("schema-staging.graphql", schema),
    }

    monkeypatch.setattr(config, "settings", replace(config.settings, max_graphql_ast_nodes=20_000))
    rejected = client.post(
        "/api/v1/contracts/compare",
        files=files,
        data={"contract_type": "graphql"},
    )

    assert rejected.status_code == 413
    assert rejected.json()["error"]["code"] == "graphql_contract_too_complex"
    assert rejected.json()["error"]["details"]["configured_max_ast_nodes"] == 20_000

    monkeypatch.setattr(config, "settings", replace(config.settings, max_graphql_ast_nodes=30_000))
    accepted = client.post(
        "/api/v1/contracts/compare",
        files=files,
        data={"contract_type": "graphql"},
    )

    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["old_contract"]["contract_type"] == "graphql"
    assert accepted.json()["duplicate"] is False
    assert len(client.get("/api/v1/analyses").json()) == 2


def test_public_github_route_honors_raised_archive_entry_limit_after_prior_failure(
    client, monkeypatch
) -> None:
    archive = _archive_with_entries(2_001)
    app.dependency_overrides[get_github_repository_source] = lambda: _StaticGitHubSource(archive)
    files = {
        "old_spec": _openapi_upload("old.json"),
        "new_spec": _openapi_upload("new.json"),
    }
    data = {
        "repository_url": "https://github.com/example/large-repository",
        "ref": "main",
        "contract_type": "openapi",
    }

    monkeypatch.setattr(config, "settings", replace(config.settings, max_repository_files=2_000))
    rejected = client.post("/api/v1/impact/analyze/github", files=files, data=data)

    assert rejected.status_code == 413
    error = rejected.json()["error"]
    assert error["code"] == "repository_file_limit_exceeded"
    assert error["message"] == "Repository archive exceeds the configured entry limit."
    assert error["details"] == {
        "limit": "archive_entries",
        "actual_entries": 2_001,
        "configured_max_entries": 2_000,
        "configuration": "DRIFTGUARD_MAX_REPOSITORY_FILES",
    }

    monkeypatch.setattr(config, "settings", replace(config.settings, max_repository_files=2_100))
    accepted = client.post("/api/v1/impact/analyze/github", files=files, data=data)

    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["repository"]["archive_entries"] == 2_001
    assert accepted.json()["duplicate"] is False
    assert len(client.get("/api/v1/analyses").json()) == 2


def test_connected_github_tree_limit_reports_actual_and_configured_entries(monkeypatch) -> None:
    provider = RealGitHubInstallationProvider("1", "unused-private-key.pem", 1.0)

    async def list_repositories(_installation_id: int) -> list[GitHubRepositoryInfo]:
        return [
            GitHubRepositoryInfo(
                99,
                "example",
                "large-repository",
                "example/large-repository",
                "main",
                True,
                "https://github.com/example/large-repository",
            )
        ]

    async def installation_token(_installation_id: int) -> str:
        return "installation-token"

    class _Client:
        async def _request(self, method: str, path: str, **_kwargs):
            assert method == "GET"
            if "/commits/" in path:
                return {"sha": "b" * 40}
            if "/git/trees/" in path:
                return {
                    "truncated": False,
                    "tree": [
                        {"type": "blob", "path": f"src/file-{index}.ts", "sha": str(index)}
                        for index in range(3)
                    ],
                }
            raise AssertionError(f"Unexpected GitHub request: {path}")

    provider.list_repositories = list_repositories  # type: ignore[method-assign]
    provider._installation_token = installation_token  # type: ignore[method-assign]
    provider.client = _Client()  # type: ignore[assignment]
    monkeypatch.setattr(
        installations_module,
        "settings",
        replace(installations_module.settings, max_repository_tree_entries=2),
    )

    with pytest.raises(DriftGuardError) as raised:
        asyncio.run(provider.fetch_repository(1, 99, "main"))

    assert raised.value.code == "repository_file_limit_exceeded"
    assert raised.value.details == {
        "limit": "github_tree_entries",
        "actual_entries": 3,
        "configured_max_entries": 2,
        "github_tree_truncated": False,
        "configuration": "DRIFTGUARD_MAX_REPOSITORY_TREE_ENTRIES",
    }
