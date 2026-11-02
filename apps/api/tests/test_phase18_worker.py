from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from apps.api.app.api.routes.automation import discover_repository_contracts
from apps.api.app.core.config import settings
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.core.workspace_context import (
    LOCAL_WORKSPACE_ID,
    WorkspacePrincipal,
    workspace_scope,
)
from apps.api.app.domain.automation import (
    BackgroundJob,
    BackgroundJobStatus,
    BackgroundJobType,
    CheckRunConclusion,
    CheckRunStatus,
)
from apps.api.app.domain.workspace import (
    GitHubInstallation,
    RepositoryConnection,
    WorkspaceRole,
)
from apps.api.app.github.automation_provider import MockGitHubAutomationProvider
from apps.api.app.github.contracts import ContractDiscoveryService
from apps.api.app.github.worker import AutomationWorker
from apps.api.app.infrastructure.sqlite_analysis_repository import SQLiteAnalysisRepository
from apps.api.app.infrastructure.sqlite_automation_repository import SQLiteAutomationRepository
from apps.api.app.infrastructure.sqlite_workspace_repository import SQLiteWorkspaceRepository
from apps.api.app.migration.provider import MockMigrationRecommendationProvider
from apps.api.app.migration.service import MigrationRecommendationService
from apps.api.app.risk.classifier import RiskClassifier
from apps.api.app.services.analysis_pipeline import AnalysisPipelineService

BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
OLD_SPEC = b"""openapi: 3.0.3
info: {title: Payments, version: '1.0'}
paths:
  /payments:
    post:
      responses:
        '200': {description: ok}
"""
NEW_SPEC = b"""openapi: 3.0.3
info: {title: Payments, version: '2.0'}
paths: {}
"""


def _setup(tmp_path, provider=None, *, max_retries=2):
    database = tmp_path / "worker.sqlite3"
    workspaces = SQLiteWorkspaceRepository(database)
    workspaces.initialize()
    automation = SQLiteAutomationRepository(database)
    automation.initialize()
    analyses = SQLiteAnalysisRepository(database)
    analyses.initialize()
    now = datetime.now(UTC)
    installation = workspaces.upsert_installation(
        GitHubInstallation(
            "installation-1", LOCAL_WORKSPACE_ID, 91, 4, "acme", "Organization", now, now
        )
    )
    connection = workspaces.upsert_repository(
        RepositoryConnection(
            "repository-1", LOCAL_WORKSPACE_ID, installation.installation_id, 501,
            "acme", "payments", "acme/payments", "main", True,
            "https://github.com/acme/payments", True, now, now, now,
        )
    )
    github = provider or MockGitHubAutomationProvider()
    pipeline = AnalysisPipelineService(
        analyses,
        RiskClassifier(settings.risk_model_path, settings.risk_model_metadata_path),
        MigrationRecommendationService(MockMigrationRecommendationProvider()),
    )
    worker = AutomationWorker(
        automation, workspaces, None, github,
        ContractDiscoveryService(automation, github), pipeline,
        frontend_url="https://driftguard.example",
        enabled=False, poll_seconds=1, max_retries=max_retries, retry_base_seconds=1,
    )
    return automation, workspaces, github, worker, installation, connection


def _pr_job(automation, installation, connection):
    return automation.enqueue_job(
        BackgroundJob(
            "job-1", LOCAL_WORKSPACE_ID, BackgroundJobType.GITHUB_PR_CONTRACT_CHECK,
            BackgroundJobStatus.QUEUED,
            {
                "installation_id": installation.installation_id,
                "repository_connection_id": connection.connection_id,
                "pull_request_number": 7,
                "base_sha": BASE_SHA,
                "head_sha": HEAD_SHA,
            },
            0, datetime.now(UTC),
        )
    )


def test_provider_pr_job_compares_immutable_snapshots_and_reconciles_check(tmp_path):
    automation, _, github, worker, installation, connection = _setup(tmp_path)
    github.snapshots[(connection.github_repository_id, BASE_SHA)] = {"openapi.yaml": OLD_SPEC}
    github.snapshots[(connection.github_repository_id, HEAD_SHA)] = {"openapi.yaml": NEW_SPEC}
    _pr_job(automation, installation, connection)

    assert asyncio.run(worker.run_once()) == 1

    job = automation.get_job("job-1", LOCAL_WORKSPACE_ID)
    assert job.status is BackgroundJobStatus.SUCCEEDED
    checks = automation.list_checks(LOCAL_WORKSPACE_ID, connection.connection_id)
    assert len(checks) == 1
    assert checks[0].status is CheckRunStatus.COMPLETED
    assert checks[0].conclusion is CheckRunConclusion.ACTION_REQUIRED
    assert "Breaking changes: 1" in checks[0].summary
    assert checks[0].analysis_id
    assert checks[0].details_url.startswith("https://driftguard.example/")
    assert [name for name, _ in github.calls].count("create_check") == 1
    assert [name for name, _ in github.calls].count("update_check") == 1
    fetched = [value for name, value in github.calls if name == "fetch_file"]
    assert {value[2] for value in fetched} == {BASE_SHA, HEAD_SHA}


def test_manual_repository_discovery_uses_current_immutable_snapshot(tmp_path):
    automation, workspaces, github, _, installation, connection = _setup(tmp_path)
    github.refs[(connection.github_repository_id, connection.default_branch)] = HEAD_SHA
    github.snapshots[(connection.github_repository_id, HEAD_SHA)] = {
        "openapi.yaml": NEW_SPEC,
        "src/client.py": b"print('not a contract')\n",
    }

    class Onboarding:
        repository = workspaces

        @staticmethod
        def require_repository(principal, connection_id, *, require_enabled=True):
            del require_enabled
            assert principal.workspace_id == LOCAL_WORKSPACE_ID
            assert connection_id == connection.connection_id
            return connection

    principal = WorkspacePrincipal(
        LOCAL_WORKSPACE_ID,
        "developer-1",
        role=WorkspaceRole.DEVELOPER,
    )
    with workspace_scope(principal):
        result = asyncio.run(
            discover_repository_contracts(
                connection.connection_id,
                Onboarding(),
                github,
                ContractDiscoveryService(automation, github),
            )
        )

    assert result["status"] == "completed"
    assert result["commit_sha"] == HEAD_SHA
    assert [item["path"] for item in result["contracts"]] == ["openapi.yaml"]
    stored = automation.list_contracts(LOCAL_WORKSPACE_ID, connection.connection_id)
    assert len(stored) == 1
    assert stored[0].last_seen_commit == HEAD_SHA


def test_job_survives_repository_recreation(tmp_path):
    automation, workspaces, github, worker, installation, connection = _setup(tmp_path)
    _pr_job(automation, installation, connection)
    restarted = SQLiteAutomationRepository(automation.database_path)
    restarted.initialize()
    worker.automation = restarted
    worker.discovery = ContractDiscoveryService(restarted, github)

    asyncio.run(worker.run_once())

    assert restarted.get_job("job-1", LOCAL_WORKSPACE_ID).status is BackgroundJobStatus.SUCCEEDED


def test_stale_running_job_is_recovered_after_worker_restart(tmp_path):
    automation, _, github, worker, installation, connection = _setup(tmp_path)
    github.snapshots[(connection.github_repository_id, BASE_SHA)] = {"openapi.yaml": OLD_SPEC}
    github.snapshots[(connection.github_repository_id, HEAD_SHA)] = {"openapi.yaml": NEW_SPEC}
    job = _pr_job(automation, installation, connection)
    now = datetime.now(UTC)
    automation.save_job(
        replace(
            job,
            status=BackgroundJobStatus.RUNNING,
            attempt_count=1,
            started_at=now - timedelta(minutes=2),
        )
    )

    assert asyncio.run(worker.run_once(now=now)) == 1
    recovered = automation.get_job(job.job_id, LOCAL_WORKSPACE_ID)
    assert recovered is not None
    assert recovered.status is BackgroundJobStatus.SUCCEEDED
    assert recovered.attempt_count == 2


class _RateLimitedProvider(MockGitHubAutomationProvider):
    async def changed_paths(self, installation_id, repository, base_sha, head_sha):
        del installation_id, repository, base_sha, head_sha
        raise DriftGuardError(
            code="github_rate_limited",
            message="GitHub rate-limited the repository operation.",
            status_code=429,
        )


def test_transient_failure_is_bounded_retry(tmp_path):
    provider = _RateLimitedProvider()
    automation, _, _, worker, installation, connection = _setup(
        tmp_path, provider, max_retries=2
    )
    _pr_job(automation, installation, connection)

    asyncio.run(worker.run_once())

    job = automation.get_job("job-1", LOCAL_WORKSPACE_ID)
    assert job.status is BackgroundJobStatus.RETRY_SCHEDULED
    assert job.attempt_count == 1
    assert job.next_attempt_at is not None
    assert job.failure_code == "github_rate_limited"


def test_revoked_installation_fails_permanently_without_github_call(tmp_path):
    automation, workspaces, github, worker, installation, connection = _setup(tmp_path)
    workspaces.upsert_installation(
        GitHubInstallation(
            installation.installation_id, installation.workspace_id,
            installation.github_installation_id, installation.github_account_id,
            installation.github_account_login, installation.account_type,
            installation.created_at, datetime.now(UTC), datetime.now(UTC),
        )
    )
    _pr_job(automation, installation, connection)

    asyncio.run(worker.run_once())

    job = automation.get_job("job-1", LOCAL_WORKSPACE_ID)
    assert job.status is BackgroundJobStatus.FAILED
    assert job.failure_code == "github_installation_revoked"
    assert github.calls == []
