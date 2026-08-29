from __future__ import annotations

import json
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from apps.api.app.core.dependencies import get_github_repository_source
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.main import app
from apps.api.app.repository.github_source import GitHubRepositoryArchive


def upload(specification, filename):
    return (filename, json.dumps(specification).encode(), "application/json")


def repository_archive() -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "demo/src/client.py",
            'response = requests.post("/payments", json=payload)\n',
        )
    return output.getvalue()


class FakeGitHubSource:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.calls: list[tuple[str, str | None]] = []

    async def fetch(self, repository_url: str, ref: str | None = None):
        self.calls.append((repository_url, ref))
        return GitHubRepositoryArchive(
            owner="example",
            repository="payment-client",
            ref=ref,
            filename="github-example-payment-client-main.zip",
            content=self.content,
        )


def test_github_impact_route_reuses_existing_analysis_pipeline(
    client,
    base_spec,
    clone,
):
    new_spec = clone(base_spec)
    request_schema = new_spec["paths"]["/payments"]["post"]["requestBody"]
    request_schema = request_schema["content"]["application/json"]["schema"]
    request_schema["properties"]["customer_id"] = {"type": "string"}
    request_schema["required"].append("customer_id")
    source = FakeGitHubSource(repository_archive())
    app.dependency_overrides[get_github_repository_source] = lambda: source

    response = client.post(
        "/api/v1/impact/analyze/github",
        files={
            "old_spec": upload(base_spec, "old.json"),
            "new_spec": upload(new_spec, "new.json"),
        },
        data={
            "repository_url": "https://github.com/example/payment-client",
            "ref": "main",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert source.calls == [("https://github.com/example/payment-client", "main")]
    assert body["comparison"]["summary"]["breaking_changes"] == 1
    assert body["repository"]["scanned_files"] == 1
    assert body["impact_summary"]["total_matches"] == 1
    assert body["impacts"][0]["matches"][0]["file_path"] == "demo/src/client.py"
    assert body["analysis_id"]


def test_github_impact_route_uses_driftguard_error_envelope(
    client,
    base_spec,
):
    class FailingGitHubSource:
        async def fetch(self, repository_url: str, ref: str | None = None):
            raise DriftGuardError(
                code="github_timeout",
                message="GitHub did not respond before the configured timeout.",
                status_code=504,
            )

    app.dependency_overrides[get_github_repository_source] = FailingGitHubSource
    response = client.post(
        "/api/v1/impact/analyze/github",
        files={
            "old_spec": upload(base_spec, "old.json"),
            "new_spec": upload(base_spec, "new.json"),
        },
        data={"repository_url": "https://github.com/example/payment-client"},
    )

    assert response.status_code == 504
    assert response.json() == {
        "error": {
            "code": "github_timeout",
            "message": "GitHub did not respond before the configured timeout.",
            "details": {},
        }
    }
