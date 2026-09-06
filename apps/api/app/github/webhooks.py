"""Verified, idempotent GitHub App webhook intake."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import PurePosixPath
from uuid import uuid4

from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.domain.automation import (
    BackgroundJob,
    BackgroundJobStatus,
    BackgroundJobType,
    WebhookDelivery,
    WebhookDeliveryStatus,
)
from apps.api.app.ports.automation_repository import AutomationRepository
from apps.api.app.ports.workspace_repository import WorkspaceRepository

SUPPORTED_EVENTS = {"installation", "installation_repositories", "push", "pull_request", "ping"}
PR_ACTIONS = {"opened", "synchronize", "reopened", "ready_for_review"}
CONTRACT_NAMES = {
    "openapi.json",
    "openapi.yaml",
    "openapi.yml",
    "swagger.json",
    "swagger.yaml",
    "swagger.yml",
    "schema.graphql",
    "schema.gql",
}
LIKELY_DIRECTORIES = {"api", "docs", "spec", "specs", "openapi", "graphql", "contracts"}
METADATA_NAMES = {
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    ".driftguard.yml",
    ".driftguard.yaml",
}


class GitHubWebhookService:
    def __init__(
        self,
        automation: AutomationRepository,
        workspaces: WorkspaceRepository,
        *,
        secret: str,
    ) -> None:
        self.automation = automation
        self.workspaces = workspaces
        self.secret = secret

    def accept(
        self,
        *,
        raw_body: bytes,
        signature: str | None,
        event_type: str | None,
        github_delivery_id: str | None,
    ) -> tuple[int, dict[str, object]]:
        self._verify(raw_body, signature)
        event = _required_header(event_type, "X-GitHub-Event")
        delivery_key = _required_header(github_delivery_id, "X-GitHub-Delivery")
        if len(event) > 80 or len(delivery_key) > 255:
            raise _invalid_headers()
        try:
            payload = json.loads(raw_body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise DriftGuardError(
                code="github_webhook_payload_invalid",
                message="The GitHub webhook payload is invalid.",
                status_code=400,
            ) from exc
        if not isinstance(payload, dict):
            raise DriftGuardError(
                code="github_webhook_payload_invalid",
                message="The GitHub webhook payload must be an object.",
                status_code=400,
            )

        installation_id = _nested_int(payload, "installation", "id")
        repository_id = _nested_int(payload, "repository", "id")
        action = _safe_action(payload.get("action"))
        now = datetime.now(UTC)
        delivery = WebhookDelivery(
            str(uuid4()),
            delivery_key,
            event,
            action,
            installation_id,
            repository_id,
            now,
            WebhookDeliveryStatus.RECEIVED,
        )
        if not self.automation.create_delivery(delivery):
            existing = self.automation.get_delivery(delivery_key)
            return 200, {
                "status": "duplicate",
                "delivery_id": existing.delivery_id if existing else delivery_key,
            }

        if event not in SUPPORTED_EVENTS:
            self.automation.save_delivery(
                replace(
                    delivery,
                    status=WebhookDeliveryStatus.IGNORED,
                    processed_at=now,
                    failure_code="github_webhook_event_unsupported",
                )
            )
            return 202, {"status": "ignored", "delivery_id": delivery.delivery_id}
        if event == "ping":
            self.automation.save_delivery(
                replace(delivery, status=WebhookDeliveryStatus.PROCESSED, processed_at=now)
            )
            return 200, {"status": "accepted", "delivery_id": delivery.delivery_id}

        installation = (
            self.workspaces.get_installation_by_github_id(installation_id)
            if installation_id is not None
            else None
        )
        if installation is None:
            self.automation.save_delivery(
                replace(
                    delivery,
                    status=WebhookDeliveryStatus.IGNORED,
                    processed_at=now,
                    failure_code="github_installation_not_connected",
                )
            )
            return 202, {"status": "ignored", "delivery_id": delivery.delivery_id}

        if event == "installation" and action in {"deleted", "suspend"}:
            revoked = replace(installation, revoked_at=now, updated_at=now)
            self.workspaces.upsert_installation(revoked)
            for item in self.workspaces.list_repositories(installation.workspace_id):
                if item.installation_id == installation.installation_id:
                    self.workspaces.upsert_repository(
                        replace(item, enabled=False, removed_at=now, updated_at=now)
                    )
            self.automation.save_delivery(
                replace(delivery, status=WebhookDeliveryStatus.PROCESSED, processed_at=now)
            )
            return 202, {"status": "processed", "delivery_id": delivery.delivery_id}

        if installation.revoked_at:
            self.automation.save_delivery(
                replace(
                    delivery,
                    status=WebhookDeliveryStatus.IGNORED,
                    processed_at=now,
                    failure_code="github_installation_revoked",
                )
            )
            return 202, {"status": "ignored", "delivery_id": delivery.delivery_id}

        job_type: BackgroundJobType | None = None
        payload_safe: dict[str, object] = {
            "delivery_id": delivery.delivery_id,
            "installation_id": installation.installation_id,
        }
        if event in {"installation", "installation_repositories"}:
            job_type = BackgroundJobType.REPOSITORY_SYNC
        elif event == "push":
            paths = _push_paths(payload)
            repository = self._repository(installation.workspace_id, repository_id)
            known = {
                item.path
                for item in self.automation.list_contracts(
                    installation.workspace_id, repository.connection_id
                )
                if item.enabled
            }
            if not any(is_relevant_path(path, known) for path in paths):
                self.automation.save_delivery(
                    replace(delivery, status=WebhookDeliveryStatus.IGNORED, processed_at=now)
                )
                return 202, {"status": "ignored", "delivery_id": delivery.delivery_id}
            job_type = BackgroundJobType.GITHUB_PUSH_SCAN
            payload_safe.update(
                {
                    "repository_connection_id": repository.connection_id,
                    "before_sha": _safe_sha(payload.get("before")),
                    "after_sha": _safe_sha(payload.get("after")),
                    "changed_paths": sorted(paths)[:500],
                }
            )
        elif event == "pull_request":
            if action not in PR_ACTIONS:
                self.automation.save_delivery(
                    replace(delivery, status=WebhookDeliveryStatus.IGNORED, processed_at=now)
                )
                return 202, {"status": "ignored", "delivery_id": delivery.delivery_id}
            repository = self._repository(installation.workspace_id, repository_id)
            pull_request = payload.get("pull_request")
            if not isinstance(pull_request, dict):
                raise _invalid_payload()
            payload_safe.update(
                {
                    "repository_connection_id": repository.connection_id,
                    "pull_request_number": _positive_int(
                        pull_request.get("number") or payload.get("number")
                    ),
                    "base_sha": _nested_sha(pull_request, "base", "sha"),
                    "head_sha": _nested_sha(pull_request, "head", "sha"),
                }
            )
            job_type = BackgroundJobType.GITHUB_PR_CONTRACT_CHECK

        if job_type is None:
            self.automation.save_delivery(
                replace(delivery, status=WebhookDeliveryStatus.IGNORED, processed_at=now)
            )
            return 202, {"status": "ignored", "delivery_id": delivery.delivery_id}
        job = self.automation.enqueue_job(
            BackgroundJob(
                str(uuid4()),
                installation.workspace_id,
                job_type,
                BackgroundJobStatus.QUEUED,
                payload_safe,
                0,
                now,
            )
        )
        self.automation.save_delivery(replace(delivery, status=WebhookDeliveryStatus.QUEUED))
        return 202, {
            "status": "queued",
            "delivery_id": delivery.delivery_id,
            "job_id": job.job_id,
        }

    def _verify(self, body: bytes, signature: str | None) -> None:
        if not self.secret:
            raise DriftGuardError(
                code="github_webhook_not_configured",
                message="GitHub webhook verification is not configured.",
                status_code=503,
            )
        if not signature or not signature.startswith("sha256="):
            raise _signature_invalid()
        supplied = signature.removeprefix("sha256=")
        if len(supplied) != 64:
            raise _signature_invalid()
        expected = hmac.new(self.secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, supplied.lower()):
            raise _signature_invalid()

    def _repository(self, workspace_id: str, repository_id: int | None):
        if repository_id is None:
            raise _invalid_payload()
        repository = self.workspaces.get_repository_by_github_id(workspace_id, repository_id)
        if repository is None or repository.removed_at or not repository.enabled:
            raise DriftGuardError(
                code="repository_not_authorized",
                message="This repository is not authorized for GitHub automation.",
                status_code=403,
            )
        return repository


def is_relevant_path(path: str, known_contracts: set[str] | frozenset[str] = frozenset()) -> bool:
    normalized = path.replace("\\", "/").strip("/")
    pure = PurePosixPath(normalized)
    if not normalized or ".." in pure.parts:
        return False
    name = pure.name.lower()
    if normalized in known_contracts or name in CONTRACT_NAMES or name in METADATA_NAMES:
        return True
    return pure.suffix.lower() in {".json", ".yaml", ".yml", ".graphql", ".gql"} and bool(
        set(part.lower() for part in pure.parts[:-1]) & LIKELY_DIRECTORIES
    )


def _push_paths(payload: dict[str, object]) -> set[str]:
    paths: set[str] = set()
    commits = payload.get("commits")
    if isinstance(commits, list):
        for commit in commits[:100]:
            if not isinstance(commit, dict):
                continue
            for key in ("added", "modified", "removed"):
                values = commit.get(key)
                if isinstance(values, list):
                    paths.update(str(value)[:1024] for value in values[:500])
    return paths


def _required_header(value: str | None, name: str) -> str:
    if not value or not value.strip():
        raise DriftGuardError(
            code="github_webhook_headers_invalid",
            message=f"The {name} header is required.",
            status_code=400,
        )
    return value.strip()


def _nested_int(payload: dict[str, object], key: str, nested: str) -> int | None:
    value = payload.get(key)
    if not isinstance(value, dict):
        return None
    try:
        return int(value.get(nested))
    except (TypeError, ValueError):
        return None


def _nested_sha(payload: dict[str, object], key: str, nested: str) -> str:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise _invalid_payload()
    return _safe_sha(value.get(nested))


def _safe_sha(value: object) -> str:
    sha = str(value or "").lower()
    if len(sha) != 40 or any(character not in "0123456789abcdef" for character in sha):
        raise _invalid_payload()
    return sha


def _positive_int(value: object) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise _invalid_payload() from exc
    if result <= 0:
        raise _invalid_payload()
    return result


def _safe_action(value: object) -> str | None:
    return str(value)[:80] if isinstance(value, str) else None


def _signature_invalid() -> DriftGuardError:
    return DriftGuardError(
        code="github_webhook_signature_invalid",
        message="The GitHub webhook signature is missing or invalid.",
        status_code=401,
    )


def _invalid_payload() -> DriftGuardError:
    return DriftGuardError(
        code="github_webhook_payload_invalid",
        message="The GitHub webhook payload is missing required fields.",
        status_code=400,
    )


def _invalid_headers() -> DriftGuardError:
    return DriftGuardError(
        code="github_webhook_headers_invalid",
        message="The GitHub webhook headers are invalid.",
        status_code=400,
    )
