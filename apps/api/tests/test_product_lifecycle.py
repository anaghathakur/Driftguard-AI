from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from apps.api.app.core.dependencies import (
    get_github_repository_source,
    get_github_write_provider,
)
from apps.api.app.main import app
from apps.api.app.pull_requests.provider import MockGitHubWriteProvider
from apps.api.app.repository.github_source import GitHubRepositoryArchive
from apps.api.tests.test_patches import archive_bytes

BASE_SHA = "a" * 40
PROJECT_ROOT = Path(__file__).parents[3]


class DemoGitHubSource:
    def __init__(self, files: dict[str, str]) -> None:
        self.files = files
        self.calls = 0

    async def fetch(self, repository_url: str, ref: str | None = None):
        self.calls += 1
        assert repository_url == "https://github.com/driftguard/payments-demo"
        return GitHubRepositoryArchive(
            owner="driftguard",
            repository="payments-demo",
            ref=ref,
            filename="github-driftguard-payments-demo-main.zip",
            content=archive_bytes(self.files),
            commit_sha=BASE_SHA,
        )


def _fixture_files(name: str) -> dict[str, str]:
    root = PROJECT_ROOT / "sample-data" / "repositories" / name
    return {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*.py"))
    }


def _spec_upload(name: str):
    path = PROJECT_ROOT / "sample-data" / "specifications" / name
    return name, path.read_bytes(), "application/yaml"


def test_complete_zero_cost_product_lifecycle_is_deterministic_and_idempotent(
    client,
):
    files = _fixture_files("payments-ready")
    original_files = deepcopy(files)
    source = DemoGitHubSource(files)
    provider = MockGitHubWriteProvider(base_commit_sha=BASE_SHA)
    app.dependency_overrides[get_github_repository_source] = lambda: source
    app.dependency_overrides[get_github_write_provider] = lambda: provider

    analyzed = client.post(
        "/api/v1/impact/analyze/github",
        files={
            "old_spec": _spec_upload("payments-old.yaml"),
            "new_spec": _spec_upload("payments-new.yaml"),
        },
        data={
            "repository_url": "https://github.com/driftguard/payments-demo",
            "ref": "main",
        },
    )
    assert analyzed.status_code == 200, analyzed.text
    analysis = analyzed.json()
    assert analysis["comparison"]["summary"]["breaking_changes"] >= 1
    payment_impacts = [
        impact
        for impact in analysis["impacts"]
        if any(match["file_path"] == "demo/payment_client.py" for match in impact["matches"])
    ]
    assert payment_impacts
    symbols = {
        match["symbol"]
        for impact in payment_impacts
        for match in impact["matches"]
        if match["symbol"]
    }
    assert any(symbol.endswith("payment_client.create_payment") for symbol in symbols)
    assert any(symbol.endswith("checkout.checkout") for symbol in symbols)
    assert any(symbol.endswith("order_service.submit_order") for symbol in symbols)

    analysis_id = analysis["analysis_id"]
    risks = client.get(f"/api/v1/analyses/{analysis_id}/risks").json()
    migrations = client.get(f"/api/v1/analyses/{analysis_id}/migrations").json()
    assert risks and all(item["analysis_id"] == analysis_id for item in risks)
    assert migrations and all(item["analysis_id"] == analysis_id for item in migrations)

    generated = client.post(f"/api/v1/analyses/{analysis_id}/patches")
    assert generated.status_code == 200, generated.text
    patch = generated.json()
    assert patch["files_changed"] == 1
    assert [item["file_path"] for item in patch["files"]] == ["demo/payment_client.py"]
    assert files == original_files

    validated = client.post(
        f"/api/v1/analyses/{analysis_id}/patches/{patch['patch_id']}/validations"
    )
    assert validated.status_code == 200, validated.text
    validation = validated.json()
    assert validation["readiness"] == "ready_for_review"
    assert {item["file_path"] for item in validation["related_tests"]} >= {
        "tests/test_payment_client.py",
        "tests/test_checkout.py",
    }
    assert any("submit_order" in (gap["symbol"] or "") for gap in validation["test_gaps"])
    assert validation["static_only"] is True
    assert files == original_files

    workflow_url = (
        f"/api/v1/analyses/{analysis_id}/patches/{patch['patch_id']}/validations/"
        f"{validation['validation_id']}/pull-request"
    )
    preview = client.get(f"{workflow_url}/preview")
    assert preview.status_code == 200, preview.text
    assert preview.json()["tests_executed"] is False

    first = client.post(workflow_url)
    second = client.post(workflow_url)
    assert first.status_code == second.status_code == 200
    assert first.json()["pr_record_id"] == second.json()["pr_record_id"]
    assert first.json()["pull_request_number"] == second.json()["pull_request_number"] == 42
    assert provider.calls.count("create_pull_request") == 1
    assert files == original_files

    report = client.get(f"/api/v1/analyses/{analysis_id}/report")
    pdf = client.get(f"/api/v1/analyses/{analysis_id}/report.pdf")
    assert report.status_code == 200
    assert report.json()["summary"]["pull_requests"] == 1
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
