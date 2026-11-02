"""Database-backed local worker for durable GitHub automation jobs."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from uuid import uuid4

from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.core.workspace_context import WorkspacePrincipal, workspace_scope
from apps.api.app.domain.automation import (
    BackgroundJob,
    BackgroundJobStatus,
    BackgroundJobType,
    CheckRunConclusion,
    CheckRunStatus,
    GitHubCheckRecord,
    WebhookDeliveryStatus,
)
from apps.api.app.github.automation_provider import CheckRunRequest, GitHubAutomationProvider
from apps.api.app.github.contracts import ContractDiscoveryService, is_contract_candidate
from apps.api.app.github.service import GitHubOnboardingService
from apps.api.app.ports.automation_repository import AutomationRepository
from apps.api.app.ports.workspace_repository import WorkspaceRepository
from apps.api.app.schemas.comparison import ChangeCategory, ComparisonResponse
from apps.api.app.services.analysis_pipeline import AnalysisPipelineService

logger = logging.getLogger("driftguard.automation")
TRANSIENT_CODES = {
    "github_rate_limited",
    "github_write_timeout",
    "github_write_unavailable",
    "github_write_failed",
    "github_check_create_failed",
    "github_check_update_failed",
    "github_snapshot_unavailable",
}


class AutomationWorker:
    def __init__(
        self,
        automation: AutomationRepository,
        workspaces: WorkspaceRepository,
        onboarding: GitHubOnboardingService,
        provider: GitHubAutomationProvider,
        discovery: ContractDiscoveryService,
        pipeline: AnalysisPipelineService,
        *,
        frontend_url: str,
        enabled: bool,
        poll_seconds: float,
        max_retries: int,
        retry_base_seconds: float,
    ) -> None:
        self.automation = automation
        self.workspaces = workspaces
        self.onboarding = onboarding
        self.provider = provider
        self.discovery = discovery
        self.pipeline = pipeline
        self.frontend_url = frontend_url.rstrip("/")
        self.enabled = enabled
        self.poll_seconds = poll_seconds
        self.max_retries = max_retries
        self.retry_base_seconds = retry_base_seconds
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if not self.enabled or self._task is not None:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(), name="driftguard-automation-worker")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop_event.set()
        await self._task
        self._task = None

    async def run_once(self, *, now: datetime | None = None) -> int:
        claimed_at = now or datetime.now(UTC)
        recovered = self.automation.recover_stale_jobs(
            claimed_at,
            retry_limit=self.max_retries,
            stale_after_seconds=max(60.0, self.poll_seconds * 3),
        )
        for job in recovered:
            if job.status is BackgroundJobStatus.FAILED:
                await self._fail_check(
                    job,
                    DriftGuardError(
                        code="worker_interrupted",
                        message=job.failure_message_safe or "The background job was interrupted.",
                        status_code=500,
                    ),
                )
        if recovered:
            logger.warning("recovered_stale_jobs count=%s", len(recovered))
        jobs = self.automation.claim_due_jobs(claimed_at)
        for job in jobs:
            await self._process(job, claimed_at)
        return len(jobs)

    async def _process(self, job: BackgroundJob, now: datetime) -> None:
        try:
            with workspace_scope(WorkspacePrincipal(job.workspace_id, system=True)):
                await self._handler(job)(job)
        except Exception as exc:
            error = _safe_error(exc)
            if error.code in TRANSIENT_CODES and job.attempt_count <= self.max_retries:
                delay = self.retry_base_seconds * (2 ** max(job.attempt_count - 1, 0))
                self.automation.save_job(
                    replace(
                        job,
                        status=BackgroundJobStatus.RETRY_SCHEDULED,
                        next_attempt_at=now + timedelta(seconds=delay),
                        failure_code=error.code,
                        failure_message_safe=error.message,
                    )
                )
            else:
                self.automation.save_job(
                    replace(
                        job,
                        status=BackgroundJobStatus.FAILED,
                        completed_at=now,
                        failure_code=error.code,
                        failure_message_safe=error.message,
                    )
                )
                await self._fail_check(job, error)
            self._delivery(job, failed=error.code)
            return
        self.automation.save_job(
            replace(
                job,
                status=BackgroundJobStatus.SUCCEEDED,
                completed_at=datetime.now(UTC),
                failure_code=None,
                failure_message_safe=None,
            )
        )
        self._delivery(job)

    def _handler(self, job: BackgroundJob) -> Callable[[BackgroundJob], Awaitable[None]]:
        return {
            BackgroundJobType.REPOSITORY_SYNC: self._sync,
            BackgroundJobType.GITHUB_PUSH_SCAN: self._push,
            BackgroundJobType.GITHUB_PR_CONTRACT_CHECK: self._pull_request,
            BackgroundJobType.CONSUMER_IMPACT_ANALYSIS: self._consumer,
        }[job.job_type]

    async def _sync(self, job: BackgroundJob) -> None:
        installation = self._installation(job)
        principal = WorkspacePrincipal(job.workspace_id, system=True)
        repositories = await self.onboarding.sync(principal, installation.installation_id)
        for connection in repositories:
            if connection.installation_id != installation.installation_id or not connection.enabled:
                continue
            sha = await self.provider.resolve_commit(
                installation.github_installation_id, connection, connection.default_branch
            )
            await self.discovery.discover(installation, connection, sha)

    async def _push(self, job: BackgroundJob) -> None:
        installation, connection = self._authorized(job)
        sha = _payload_string(job, "after_sha")
        paths = [str(value) for value in job.payload_safe.get("changed_paths", [])]
        await self.discovery.discover(installation, connection, sha, paths=paths)

    async def _pull_request(self, job: BackgroundJob) -> None:
        installation, connection = self._authorized(job)
        base_sha = _payload_string(job, "base_sha")
        head_sha = _payload_string(job, "head_sha")
        pr_number = int(job.payload_safe["pull_request_number"])
        logical_key = f"provider-pr:{connection.connection_id}:{pr_number}"
        check = await self._set_check(
            job,
            installation.github_installation_id,
            connection,
            logical_key,
            head_sha,
            CheckRunStatus.IN_PROGRESS,
            "Analyzing contract compatibility…",
        )
        paths = await self.provider.changed_paths(
            installation.github_installation_id, connection, base_sha, head_sha
        )
        known = {
            item.path
            for item in self.automation.list_contracts(job.workspace_id, connection.connection_id)
            if item.enabled
        }
        contract_paths = [path for path in paths if path in known or is_contract_candidate(path)]
        comparisons: list[ComparisonResponse] = []
        for path in contract_paths:
            try:
                old = await self.provider.fetch_file(
                    installation.github_installation_id, connection, path, base_sha
                )
                new = await self.provider.fetch_file(
                    installation.github_installation_id, connection, path, head_sha
                )
            except DriftGuardError as exc:
                if exc.code == "github_file_not_found":
                    continue
                raise
            comparisons.append(
                self.pipeline.compare(
                    old_filename=PurePosixPath(path).name,
                    old_content=old,
                    new_filename=PurePosixPath(path).name,
                    new_content=new,
                )
            )
        await self.discovery.discover(installation, connection, head_sha, paths=contract_paths)
        summary, conclusion, analysis_id = _check_summary(comparisons)
        details_url = f"{self.frontend_url}/?analysis={analysis_id}" if analysis_id else None
        await self._set_check(
            job,
            installation.github_installation_id,
            connection,
            logical_key,
            head_sha,
            CheckRunStatus.COMPLETED,
            summary,
            conclusion,
            analysis_id,
            details_url,
            existing=check,
        )

    async def _consumer(self, job: BackgroundJob) -> None:
        installation, connection = self._authorized(job)
        analysis_id = _payload_string(job, "analysis_id")
        monitor_id = _payload_string(job, "monitor_id")
        head_sha = _payload_string(job, "head_sha")
        detail = self.pipeline.get_analysis(analysis_id)
        breaking = detail.comparison_summary.breaking_changes if detail.comparison_summary else 0
        impacted = detail.impact_summary.impacted_files if detail.impact_summary else 0
        total_matches = detail.impact_summary.total_matches if detail.impact_summary else 0
        if impacted:
            conclusion = CheckRunConclusion.ACTION_REQUIRED
        elif breaking:
            conclusion = CheckRunConclusion.NEUTRAL
        else:
            conclusion = CheckRunConclusion.SUCCESS
        summary = "\n".join(
            (
                "DriftGuard Consumer API Impact",
                f"Breaking changes: {breaking}",
                f"Impacted files: {impacted}",
                f"Source matches: {total_matches}",
                "Open DriftGuard for source evidence, migration guidance, and review.",
            )
        )
        await self._set_check(
            job,
            installation.github_installation_id,
            connection,
            f"consumer-monitor:{connection.connection_id}:{monitor_id}:{head_sha}",
            head_sha,
            CheckRunStatus.COMPLETED,
            summary,
            conclusion,
            analysis_id,
            f"{self.frontend_url}/?analysis={analysis_id}",
            name="DriftGuard Consumer API Impact",
        )

    async def _set_check(
        self,
        job: BackgroundJob,
        github_installation_id: int,
        connection,
        logical_key: str,
        head_sha: str,
        status: CheckRunStatus,
        summary: str,
        conclusion: CheckRunConclusion | None = None,
        analysis_id: str | None = None,
        details_url: str | None = None,
        *,
        existing: GitHubCheckRecord | None = None,
        name: str = "DriftGuard Contract Compatibility",
    ) -> GitHubCheckRecord:
        current = existing or self.automation.get_check_by_logical_key(
            job.workspace_id, logical_key
        )
        request = CheckRunRequest(
            name,
            head_sha,
            status,
            summary,
            details_url,
            conclusion,
        )
        now = datetime.now(UTC)
        if current and current.github_check_run_id:
            await self.provider.update_check(
                github_installation_id, connection, current.github_check_run_id, request
            )
            check_id = current.github_check_run_id
        else:
            check_id = await self.provider.create_check(github_installation_id, connection, request)
        record = GitHubCheckRecord(
            current.check_record_id if current else str(uuid4()),
            job.workspace_id,
            connection.connection_id,
            logical_key,
            head_sha,
            request.name,
            status,
            current.created_at if current else now,
            now,
            check_id,
            job.job_id,
            analysis_id,
            conclusion,
            details_url,
            summary,
        )
        return self.automation.upsert_check(record)

    async def _fail_check(self, job: BackgroundJob, error: DriftGuardError) -> None:
        if job.job_type is not BackgroundJobType.GITHUB_PR_CONTRACT_CHECK:
            return
        try:
            installation, connection = self._authorized(job)
            pr_number = int(job.payload_safe["pull_request_number"])
            await self._set_check(
                job,
                installation.github_installation_id,
                connection,
                f"provider-pr:{connection.connection_id}:{pr_number}",
                _payload_string(job, "head_sha"),
                CheckRunStatus.COMPLETED,
                f"DriftGuard could not complete the analysis ({error.code}).",
                CheckRunConclusion.FAILURE,
            )
        except Exception:
            logger.warning("Unable to publish failed Check Run job_id=%s", job.job_id)

    def _installation(self, job: BackgroundJob):
        installation_id = _payload_string(job, "installation_id")
        installation = self.workspaces.get_installation(installation_id)
        if installation is None or installation.workspace_id != job.workspace_id:
            raise _unauthorized()
        if installation.revoked_at:
            raise DriftGuardError(
                code="github_installation_revoked",
                message="The GitHub App installation has been revoked.",
                status_code=409,
            )
        return installation

    def _authorized(self, job: BackgroundJob):
        installation = self._installation(job)
        connection_id = _payload_string(job, "repository_connection_id")
        connection = self.workspaces.get_repository(connection_id)
        if (
            connection is None
            or connection.workspace_id != job.workspace_id
            or connection.installation_id != installation.installation_id
            or connection.removed_at
            or not connection.enabled
        ):
            raise _unauthorized()
        return installation, connection

    def _delivery(self, job: BackgroundJob, *, failed: str | None = None) -> None:
        delivery_id = job.payload_safe.get("delivery_id")
        if not isinstance(delivery_id, str):
            return
        delivery = self.automation.get_delivery_by_id(delivery_id)
        if delivery:
            self.automation.save_delivery(
                replace(
                    delivery,
                    status=(
                        WebhookDeliveryStatus.FAILED if failed else WebhookDeliveryStatus.PROCESSED
                    ),
                    processed_at=datetime.now(UTC),
                    failure_code=failed,
                )
            )

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            await self.run_once()
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.poll_seconds)
            except TimeoutError:
                continue


def _check_summary(
    comparisons: list[ComparisonResponse],
) -> tuple[str, CheckRunConclusion, str | None]:
    breaking = sum(item.summary.breaking_changes for item in comparisons)
    potential = sum(item.summary.potentially_breaking_changes for item in comparisons)
    non_breaking = sum(item.summary.non_breaking_changes for item in comparisons)
    contract_types = sorted({item.new_contract.contract_type.value.title() for item in comparisons})
    lines = [
        "DriftGuard API Compatibility",
        f"Contract type: {', '.join(contract_types) if contract_types else 'None detected'}",
        f"Breaking changes: {breaking}",
        f"Potentially breaking changes: {potential}",
        f"Non-breaking changes: {non_breaking}",
    ]
    changes = [change for item in comparisons for change in item.changes]
    for change in changes[:10]:
        prefix = "✗" if change.category is ChangeCategory.BREAKING else "⚠"
        operation = change.operation_identifier or f"{change.method} {change.path}".strip()
        lines.append(f"{prefix} {operation or 'Contract change'}: {change.explanation}")
    if not comparisons:
        lines.append("No changed, valid supported contract was detected in this pull request.")
    if breaking:
        conclusion = CheckRunConclusion.ACTION_REQUIRED
    elif potential:
        conclusion = CheckRunConclusion.NEUTRAL
    else:
        conclusion = CheckRunConclusion.SUCCESS
    analysis_id = next(
        (item.analysis_id for item in reversed(comparisons) if item.analysis_id), None
    )
    return "\n".join(lines), conclusion, analysis_id


def _payload_string(job: BackgroundJob, name: str) -> str:
    value = job.payload_safe.get(name)
    if not isinstance(value, str) or not value:
        raise DriftGuardError(
            code="job_failed", message="The automation job payload is invalid.", status_code=400
        )
    return value


def _safe_error(exc: Exception) -> DriftGuardError:
    if isinstance(exc, DriftGuardError):
        return exc
    return DriftGuardError(
        code="job_failed",
        message="The automation job could not be completed safely.",
        status_code=500,
    )


def _unauthorized() -> DriftGuardError:
    return DriftGuardError(
        code="repository_not_authorized",
        message="The repository is no longer authorized for automation.",
        status_code=403,
    )
