from __future__ import annotations

import hashlib
import json
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from apps.api.app.core.dependencies import (
    get_github_repository_source,
    get_monitor_repository,
    get_openapi_specification_source,
)
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.infrastructure.sqlite_monitor_repository import SQLiteMonitorRepository
from apps.api.app.main import app
from apps.api.app.monitoring.specification_source import RemoteSpecification
from apps.api.app.repository.github_source import GitHubRepositoryArchive


def remote_spec(*, currency_required: bool) -> RemoteSpecification:
    required = ["amount", "currency"] if currency_required else ["amount"]
    content = json.dumps(
        {
            "openapi": "3.0.3",
            "info": {"title": "Payments", "version": "2" if currency_required else "1"},
            "paths": {
                "/payments": {
                    "post": {
                        "operationId": "createPayment",
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": required,
                                        "properties": {
                                            "amount": {"type": "integer"},
                                            "currency": {"type": "string"},
                                        },
                                    }
                                }
                            }
                        },
                        "responses": {"201": {"description": "Created"}},
                    }
                }
            },
        }
    ).encode()
    return RemoteSpecification(
        source_url="https://api.example.com/openapi.json",
        filename="openapi.json",
        content_type="application/json",
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
    )


def repository_zip() -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "demo/client.py",
            'requests.post(f"{base_url}/payments", json=payload)\n',
        )
    return output.getvalue()


class FakeSpecificationSource:
    def __init__(self, *values: RemoteSpecification) -> None:
        self.values = list(values)

    async def fetch(self, _url: str):
        if len(self.values) > 1:
            return self.values.pop(0)
        return self.values[0]


class FakeGitHubSource:
    def __init__(self) -> None:
        self.calls = 0

    async def fetch(self, repository_url: str, ref: str | None = None):
        self.calls += 1
        return GitHubRepositoryArchive(
            owner="example",
            repository="client",
            ref=ref,
            filename="github-example-client-main.zip",
            content=repository_zip(),
        )


def monitor_request():
    return {
        "name": "Payments API",
        "specification_url": "https://api.example.com/openapi.json",
        "repository_url": "https://github.com/example/client",
        "repository_ref": "main",
        "check_interval_minutes": 60,
        "enabled": True,
    }


def configure(client, analysis_repository, source, github):
    monitor_repository = SQLiteMonitorRepository(analysis_repository.database_path)
    monitor_repository.initialize()
    app.dependency_overrides[get_monitor_repository] = lambda: monitor_repository
    app.dependency_overrides[get_openapi_specification_source] = lambda: source
    app.dependency_overrides[get_github_repository_source] = lambda: github
    return monitor_repository


def test_monitor_api_creation_crud_and_unchanged_check(
    client,
    analysis_repository,
):
    baseline = remote_spec(currency_required=False)
    source = FakeSpecificationSource(baseline)
    github = FakeGitHubSource()
    configure(client, analysis_repository, source, github)

    created = client.post("/api/v1/monitors", json=monitor_request())
    assert created.status_code == 201
    monitor = created.json()
    monitor_id = monitor["monitor_id"]
    assert monitor["baseline_sha256"] == baseline.sha256
    assert client.get("/api/v1/analyses").json() == []

    assert client.get("/api/v1/monitors").json()[0]["monitor_id"] == monitor_id
    assert client.get(f"/api/v1/monitors/{monitor_id}").status_code == 200

    updated = client.patch(
        f"/api/v1/monitors/{monitor_id}",
        json={"enabled": False, "check_interval_minutes": 120},
    )
    assert updated.status_code == 200
    assert updated.json()["enabled"] is False
    assert updated.json()["check_interval_minutes"] == 120

    checked = client.post(f"/api/v1/monitors/{monitor_id}/check")
    assert checked.status_code == 200
    assert checked.json()["status"] == "unchanged"
    assert github.calls == 0
    history = client.get(f"/api/v1/monitors/{monitor_id}/checks")
    assert history.json()[0]["status"] == "unchanged"

    deleted = client.delete(f"/api/v1/monitors/{monitor_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/monitors/{monitor_id}").status_code == 404


def test_monitor_api_changed_check_runs_existing_impact_pipeline(
    client,
    analysis_repository,
):
    source = FakeSpecificationSource(
        remote_spec(currency_required=False),
        remote_spec(currency_required=True),
    )
    github = FakeGitHubSource()
    configure(client, analysis_repository, source, github)
    created = client.post("/api/v1/monitors", json=monitor_request()).json()

    checked = client.post(f"/api/v1/monitors/{created['monitor_id']}/check")

    assert checked.status_code == 200
    result = checked.json()
    assert result["status"] == "changed"
    assert result["analysis_id"]
    assert github.calls == 1
    detail = client.get(f"/api/v1/monitors/{created['monitor_id']}").json()
    assert detail["baseline_sha256"] == remote_spec(currency_required=True).sha256
    assert detail["last_successful_analysis_id"] == result["analysis_id"]
    assert len(client.get(f"/api/v1/analyses/{result['analysis_id']}/risks").json()) == 1
    assert (
        len(client.get(f"/api/v1/analyses/{result['analysis_id']}/migrations").json())
        == 1
    )


def test_monitor_api_rejects_empty_update_and_missing_monitor(
    client,
    analysis_repository,
):
    configure(
        client,
        analysis_repository,
        FakeSpecificationSource(remote_spec(currency_required=False)),
        FakeGitHubSource(),
    )

    assert client.patch("/api/v1/monitors/missing", json={}).status_code == 422
    response = client.post("/api/v1/monitors/missing/check")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "monitor_not_found"


def test_monitor_creation_rejects_invalid_remote_specification(
    client,
    analysis_repository,
):
    class InvalidSpecificationSource:
        async def fetch(self, _url: str):
            raise DriftGuardError(
                code="unsupported_openapi_version",
                message="The document must declare an OpenAPI 3.x version.",
            )

    monitor_repository = configure(
        client,
        analysis_repository,
        InvalidSpecificationSource(),
        FakeGitHubSource(),
    )

    response = client.post("/api/v1/monitors", json=monitor_request())

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_openapi_version"
    assert monitor_repository.list() == []
    assert client.get("/api/v1/analyses").json() == []
