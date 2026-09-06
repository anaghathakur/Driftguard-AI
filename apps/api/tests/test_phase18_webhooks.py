from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from apps.api.app.core.dependencies import get_github_webhook_service
from apps.api.app.core.workspace_context import LOCAL_WORKSPACE_ID
from apps.api.app.domain.automation import BackgroundJobType, WebhookDeliveryStatus
from apps.api.app.domain.workspace import GitHubInstallation, RepositoryConnection
from apps.api.app.github.webhooks import GitHubWebhookService
from apps.api.app.infrastructure.sqlite_automation_repository import SQLiteAutomationRepository
from apps.api.app.infrastructure.sqlite_workspace_repository import SQLiteWorkspaceRepository
from apps.api.app.main import create_app

SECRET = "phase-18-test-secret"
SHA_A = "a" * 40
SHA_B = "b" * 40


def _services(tmp_path):
    database = tmp_path / "automation.sqlite3"
    workspaces = SQLiteWorkspaceRepository(database)
    workspaces.initialize()
    automation = SQLiteAutomationRepository(database)
    automation.initialize()
    now = datetime.now(UTC)
    installation = workspaces.upsert_installation(
        GitHubInstallation(
            "installation-1", LOCAL_WORKSPACE_ID, 91, 4, "acme", "Organization", now, now
        )
    )
    repository = workspaces.upsert_repository(
        RepositoryConnection(
            "repository-1", LOCAL_WORKSPACE_ID, installation.installation_id, 501,
            "acme", "payments", "acme/payments", "main", True,
            "https://github.com/acme/payments", True, now, now, now,
        )
    )
    return automation, workspaces, installation, repository


def _headers(body: bytes, *, delivery: str = "delivery-1", signature_body: bytes | None = None):
    digest = hmac.new(SECRET.encode(), signature_body or body, hashlib.sha256).hexdigest()
    return {
        "X-Hub-Signature-256": f"sha256={digest}",
        "X-GitHub-Event": "push",
        "X-GitHub-Delivery": delivery,
        "Content-Type": "application/json",
    }


def _push(*paths: str) -> bytes:
    return json.dumps(
        {
            "installation": {"id": 91},
            "repository": {"id": 501},
            "before": SHA_A,
            "after": SHA_B,
            "commits": [{"added": list(paths), "modified": [], "removed": []}],
        },
        separators=(",", ":"),
    ).encode()


def test_valid_signature_queues_contract_push_and_duplicate_is_idempotent(tmp_path):
    automation, workspaces, _, _ = _services(tmp_path)
    service = GitHubWebhookService(automation, workspaces, secret=SECRET)
    app = create_app()
    app.dependency_overrides[get_github_webhook_service] = lambda: service
    body = _push("openapi.yaml")

    with TestClient(app) as client:
        first = client.post("/api/v1/github/webhooks", content=body, headers=_headers(body))
        duplicate = client.post("/api/v1/github/webhooks", content=body, headers=_headers(body))

    assert first.status_code == 202
    assert first.json()["status"] == "queued"
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "duplicate"
    jobs = automation.list_jobs(LOCAL_WORKSPACE_ID)
    assert len(jobs) == 1
    assert jobs[0].job_type is BackgroundJobType.GITHUB_PUSH_SCAN


def test_webhook_payload_cannot_select_an_arbitrary_workspace(tmp_path):
    automation, workspaces, _, _ = _services(tmp_path)
    service = GitHubWebhookService(automation, workspaces, secret=SECRET)
    payload = json.loads(_push("openapi.yaml"))
    payload["workspace_id"] = "attacker-workspace"
    payload["organization_id"] = "attacker-workspace"
    body = json.dumps(payload, separators=(",", ":")).encode()

    status, result = service.accept(
        raw_body=body,
        signature=_headers(body)["X-Hub-Signature-256"],
        event_type="push",
        github_delivery_id="spoofed-workspace",
    )

    assert status == 202
    assert result["status"] == "queued"
    assert len(automation.list_jobs(LOCAL_WORKSPACE_ID)) == 1
    assert automation.list_jobs("attacker-workspace") == []


def test_missing_invalid_and_tampered_signatures_are_rejected_before_persistence(tmp_path):
    automation, workspaces, _, _ = _services(tmp_path)
    service = GitHubWebhookService(automation, workspaces, secret=SECRET)
    app = create_app()
    app.dependency_overrides[get_github_webhook_service] = lambda: service
    body = _push("openapi.yaml")

    with TestClient(app) as client:
        missing = client.post(
            "/api/v1/github/webhooks",
            content=body,
            headers={"X-GitHub-Event": "push", "X-GitHub-Delivery": "missing"},
        )
        invalid = client.post(
            "/api/v1/github/webhooks",
            content=body,
            headers={**_headers(body, delivery="invalid"), "X-Hub-Signature-256": "sha256=0"},
        )
        tampered = client.post(
            "/api/v1/github/webhooks",
            content=body,
            headers=_headers(body, delivery="tampered", signature_body=_push("README.md")),
        )

    assert [missing.status_code, invalid.status_code, tampered.status_code] == [401, 401, 401]
    assert automation.list_jobs(LOCAL_WORKSPACE_ID) == []


def test_irrelevant_push_is_acknowledged_without_job(tmp_path):
    automation, workspaces, _, _ = _services(tmp_path)
    service = GitHubWebhookService(automation, workspaces, secret=SECRET)
    body = _push("README.md", "src/widget.py")

    status, result = service.accept(
        raw_body=body,
        signature=_headers(body)["X-Hub-Signature-256"],
        event_type="push",
        github_delivery_id="irrelevant",
    )

    assert status == 202
    assert result["status"] == "ignored"
    assert automation.list_jobs(LOCAL_WORKSPACE_ID) == []
    assert automation.get_delivery("irrelevant").status is WebhookDeliveryStatus.IGNORED


def test_pull_request_event_persists_immutable_base_and_head(tmp_path):
    automation, workspaces, _, _ = _services(tmp_path)
    service = GitHubWebhookService(automation, workspaces, secret=SECRET)
    body = json.dumps(
        {
            "action": "opened", "number": 7,
            "installation": {"id": 91}, "repository": {"id": 501},
            "pull_request": {
                "number": 7, "base": {"sha": SHA_A}, "head": {"sha": SHA_B}
            },
        },
        separators=(",", ":"),
    ).encode()
    signature = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()

    status, result = service.accept(
        raw_body=body, signature=signature, event_type="pull_request",
        github_delivery_id="pr-opened",
    )

    job = automation.get_job(result["job_id"], LOCAL_WORKSPACE_ID)
    assert status == 202
    assert job.job_type is BackgroundJobType.GITHUB_PR_CONTRACT_CHECK
    assert job.payload_safe["base_sha"] == SHA_A
    assert job.payload_safe["head_sha"] == SHA_B


def test_deleted_installation_revokes_access_without_deleting_repository(tmp_path):
    automation, workspaces, installation, repository = _services(tmp_path)
    service = GitHubWebhookService(automation, workspaces, secret=SECRET)
    body = json.dumps(
        {"action": "deleted", "installation": {"id": 91}}, separators=(",", ":")
    ).encode()
    signature = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()

    status, _ = service.accept(
        raw_body=body, signature=signature, event_type="installation",
        github_delivery_id="installation-deleted",
    )

    assert status == 202
    assert workspaces.get_installation(installation.installation_id).revoked_at is not None
    stored = workspaces.get_repository(repository.connection_id)
    assert stored is not None
    assert stored.enabled is False
    assert stored.removed_at is not None
