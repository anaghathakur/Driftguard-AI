"""Monitor configuration and check orchestration services."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from time import perf_counter
from uuid import uuid4

from apps.api.app.auth.authorization import Permission, authorize
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.domain.analysis import RepositorySourceType
from apps.api.app.domain.monitor import (
    ApiMonitor,
    MonitorCheckRecord,
    MonitorCheckStatus,
)
from apps.api.app.monitoring.github_file_source import GitHubFileContractSource
from apps.api.app.monitoring.specification_source import (
    OpenApiSpecificationSource,
)
from apps.api.app.ports.monitor_repository import ApiMonitorRepository
from apps.api.app.repository.github_source import (
    GitHubRepositorySource,
    parse_github_repository_url,
    validate_github_ref,
)
from apps.api.app.schemas.monitor import (
    MonitorCheckResponse,
    MonitorCreateRequest,
    MonitorResponse,
    MonitorUpdateRequest,
)
from apps.api.app.services.analysis_pipeline import AnalysisPipelineService

Clock = Callable[[], datetime]
ConsumerDispatcher = Callable[[ApiMonitor, str, str], Awaitable[None]]
logger = logging.getLogger("driftguard.monitoring")


class ApiMonitorService:
    def __init__(
        self,
        repository: ApiMonitorRepository,
        specification_source: OpenApiSpecificationSource,
        github_file_source: GitHubFileContractSource | None = None,
        *,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self.repository = repository
        self.specification_source = specification_source
        self.github_file_source = github_file_source
        self.clock = clock

    async def create(self, request: MonitorCreateRequest) -> MonitorResponse:
        authorize(Permission.MANAGE_MONITORS)
        repository_url, repository_ref = _validated_repository(
            request.repository_url,
            request.repository_ref,
        )
        if request.source_type.value == "github_file":
            source = self._require_github_file_source()
            fetched = await source.fetch(
                request.repository_connection_id or "",
                request.source_path or "",
                request.repository_ref,
            )
            specification = fetched.specification
            repository_url = fetched.repository.html_url
            # Keep the user-selected ref (or None for the repository default
            # branch) as the subscription target. The resolved commit is used
            # only as immutable evidence for a particular analysis; persisting
            # it here would silently pin future checks to the original baseline.
            repository_ref = request.repository_ref
        else:
            specification = await self.specification_source.fetch(request.specification_url or "")
        now = self.clock()
        monitor = ApiMonitor(
            monitor_id=str(uuid4()),
            name=request.name.strip(),
            specification_url=(request.specification_url or "").strip(),
            repository_url=repository_url,
            repository_ref=repository_ref,
            check_interval_minutes=request.check_interval_minutes,
            enabled=request.enabled,
            baseline_filename=specification.filename,
            baseline_content=specification.content,
            baseline_sha256=specification.sha256,
            baseline_observed_at=now,
            created_at=now,
            updated_at=now,
            source_type=request.source_type,
            source_path=request.source_path,
            repository_connection_id=request.repository_connection_id,
            contract_type=specification.contract_type,
        )
        self.repository.create(monitor)
        return monitor_response(monitor)

    def list(self) -> list[MonitorResponse]:
        authorize(Permission.READ_MONITORS)
        return [monitor_response(monitor) for monitor in self.repository.list()]

    def get(self, monitor_id: str) -> MonitorResponse:
        return monitor_response(self.require(monitor_id))

    async def update(
        self,
        monitor_id: str,
        request: MonitorUpdateRequest,
    ) -> MonitorResponse:
        authorize(Permission.MANAGE_MONITORS)
        monitor = self.require(monitor_id)
        updates: dict[str, object] = {"updated_at": self.clock()}
        fields = request.model_fields_set

        if "name" in fields:
            updates["name"] = request.name.strip() if request.name else ""
        if "repository_url" in fields or "repository_ref" in fields:
            repository_url, repository_ref = _validated_repository(
                request.repository_url or monitor.repository_url,
                request.repository_ref if "repository_ref" in fields else monitor.repository_ref,
            )
            updates["repository_url"] = repository_url
            updates["repository_ref"] = repository_ref
        if "check_interval_minutes" in fields:
            updates["check_interval_minutes"] = request.check_interval_minutes
        if "enabled" in fields:
            updates["enabled"] = request.enabled
        if "specification_url" in fields:
            specification_url = request.specification_url or ""
            specification = await self.specification_source.fetch(specification_url)
            observed_at = self.clock()
            updates.update(
                {
                    "specification_url": specification_url.strip(),
                    "baseline_filename": specification.filename,
                    "baseline_content": specification.content,
                    "baseline_sha256": specification.sha256,
                    "baseline_observed_at": observed_at,
                    "last_checked_at": None,
                    "last_changed_at": None,
                    "last_successful_analysis_id": None,
                    "last_check_status": None,
                    "last_error_code": None,
                    "last_error_message": None,
                }
            )

        updated = replace(monitor, **updates)
        self.repository.save(updated)
        return monitor_response(updated)

    def delete(self, monitor_id: str) -> None:
        authorize(Permission.MANAGE_MONITORS)
        if not self.repository.delete(monitor_id):
            _monitor_not_found()

    def require(self, monitor_id: str) -> ApiMonitor:
        authorize(Permission.READ_MONITORS)
        monitor = self.repository.get(monitor_id)
        if monitor is None:
            _monitor_not_found()
        return monitor

    def _require_github_file_source(self) -> GitHubFileContractSource:
        if self.github_file_source is None:
            raise DriftGuardError(
                code="github_contract_source_not_configured",
                message="GitHub contract-file subscriptions are not configured.",
                status_code=503,
            )
        return self.github_file_source


class MonitorCheckService:
    def __init__(
        self,
        repository: ApiMonitorRepository,
        specification_source: OpenApiSpecificationSource,
        github_source: GitHubRepositorySource,
        analysis_pipeline: AnalysisPipelineService,
        github_file_source: GitHubFileContractSource | None = None,
        *,
        clock: Clock = lambda: datetime.now(UTC),
        check_lease_seconds: int = 15 * 60,
        consumer_dispatcher: ConsumerDispatcher | None = None,
    ) -> None:
        self.repository = repository
        self.specification_source = specification_source
        self.github_source = github_source
        self.analysis_pipeline = analysis_pipeline
        self.github_file_source = github_file_source
        self.clock = clock
        self.check_lease_seconds = check_lease_seconds
        self._active: set[str] = set()
        self.consumer_dispatcher = consumer_dispatcher
        self._active_guard = asyncio.Lock()

    async def check(self, monitor_id: str) -> MonitorCheckResponse:
        authorize(Permission.RUN_MONITOR_CHECKS)
        await self._claim(monitor_id)
        try:
            return await self._check_claimed(monitor_id)
        finally:
            async with self._active_guard:
                self._active.discard(monitor_id)

    def list_checks(self, monitor_id: str) -> list[MonitorCheckResponse]:
        authorize(Permission.READ_MONITORS)
        if self.repository.get(monitor_id) is None:
            _monitor_not_found()
        return [check_response(check) for check in self.repository.list_checks(monitor_id)]

    async def _claim(self, monitor_id: str) -> None:
        async with self._active_guard:
            if monitor_id in self._active:
                raise DriftGuardError(
                    code="monitor_check_in_progress",
                    message="This API monitor is already being checked.",
                    status_code=409,
                )
            self._active.add(monitor_id)

    async def _check_claimed(self, monitor_id: str) -> MonitorCheckResponse:
        checked_at = self.clock()
        monitor = self.repository.claim_check(
            monitor_id,
            now=checked_at,
            lease_expires_at=checked_at + timedelta(seconds=self.check_lease_seconds),
        )
        if monitor is None:
            if self.repository.get(monitor_id) is None:
                _monitor_not_found()
            raise DriftGuardError(
                code="monitor_check_in_progress",
                message="This API monitor is already being checked.",
                status_code=409,
            )
        started_clock = perf_counter()
        check = MonitorCheckRecord(
            check_id=str(uuid4()),
            monitor_id=monitor.monitor_id,
            status=MonitorCheckStatus.CHECKING,
            checked_at=checked_at,
            completed_at=None,
            duration_ms=None,
            previous_spec_hash=monitor.baseline_sha256,
            observed_spec_hash=None,
            analysis_id=None,
            error_code=None,
            error_message=None,
        )
        checking_monitor = replace(
            monitor,
            updated_at=checked_at,
            last_check_status=MonitorCheckStatus.CHECKING,
            last_error_code=None,
            last_error_message=None,
        )
        self.repository.start_check(checking_monitor, check)
        observed_hash: str | None = None

        try:
            github_file = None
            if monitor.source_type.value == "github_file":
                if self.github_file_source is None:
                    raise DriftGuardError(
                        code="github_contract_source_not_configured",
                        message="GitHub contract-file subscriptions are not configured.",
                        status_code=503,
                    )
                github_file = await self.github_file_source.fetch(
                    monitor.repository_connection_id or "",
                    monitor.source_path or "",
                    monitor.repository_ref,
                )
                specification = github_file.specification
            else:
                specification = await self.specification_source.fetch(monitor.specification_url)
            observed_hash = specification.sha256
            completed_at = self.clock()
            if specification.sha256 == monitor.baseline_sha256:
                finished_check = replace(
                    check,
                    status=MonitorCheckStatus.UNCHANGED,
                    completed_at=completed_at,
                    duration_ms=_duration_ms(started_clock),
                    observed_spec_hash=specification.sha256,
                )
                finished_monitor = replace(
                    monitor,
                    updated_at=completed_at,
                    last_checked_at=completed_at,
                    last_check_status=MonitorCheckStatus.UNCHANGED,
                    last_error_code=None,
                    last_error_message=None,
                    check_lease_expires_at=None,
                )
                self.repository.finish_check(finished_monitor, finished_check)
                return check_response(finished_check)

            if github_file is not None:
                archive = await self.github_file_source.fetch_repository(
                    github_file.repository,
                    github_file.commit_sha,
                )
                analysis = self.analysis_pipeline.analyze_impact(
                    old_filename=monitor.baseline_filename,
                    old_content=monitor.baseline_content,
                    new_filename=specification.filename,
                    new_content=specification.content,
                    repository_filename=archive.filename,
                    repository_content=archive.content,
                    repository_source_type=RepositorySourceType.GITHUB,
                    repository_url=github_file.repository.html_url,
                    repository_ref=archive.ref,
                    repository_commit_sha=archive.commit_sha,
                )
                commit_sha = archive.commit_sha
            elif monitor.repository_url:
                archive = await self.github_source.fetch(
                    monitor.repository_url,
                    ref=monitor.repository_ref,
                )
                analysis = self.analysis_pipeline.analyze_impact(
                    old_filename=monitor.baseline_filename,
                    old_content=monitor.baseline_content,
                    new_filename=specification.filename,
                    new_content=specification.content,
                    repository_filename=archive.filename,
                    repository_content=archive.content,
                    repository_source_type=RepositorySourceType.GITHUB,
                    repository_url=monitor.repository_url,
                    repository_ref=archive.ref,
                    repository_commit_sha=archive.commit_sha,
                )
                commit_sha = archive.commit_sha
            else:
                # A subscription may be useful as contract intelligence before a
                # consumer repository is connected. Preserve the durable analysis,
                # but do not fabricate source impact or a patch.
                analysis = self.analysis_pipeline.compare(
                    old_filename=monitor.baseline_filename,
                    old_content=monitor.baseline_content,
                    new_filename=specification.filename,
                    new_content=specification.content,
                )
                commit_sha = ""
            completed_at = self.clock()
            finished_check = replace(
                check,
                status=MonitorCheckStatus.CHANGED,
                completed_at=completed_at,
                duration_ms=_duration_ms(started_clock),
                observed_spec_hash=specification.sha256,
                analysis_id=analysis.analysis_id,
            )
            finished_monitor = replace(
                monitor,
                baseline_filename=specification.filename,
                baseline_content=specification.content,
                baseline_sha256=specification.sha256,
                baseline_observed_at=completed_at,
                updated_at=completed_at,
                last_checked_at=completed_at,
                last_changed_at=completed_at,
                last_successful_analysis_id=analysis.analysis_id,
                last_check_status=MonitorCheckStatus.CHANGED,
                last_error_code=None,
                last_error_message=None,
                contract_type=specification.contract_type,
                check_lease_expires_at=None,
            )
            self.repository.finish_check(finished_monitor, finished_check)
            if self.consumer_dispatcher and finished_monitor.repository_url and commit_sha:
                try:
                    await self.consumer_dispatcher(
                        finished_monitor, analysis.analysis_id, commit_sha
                    )
                except Exception as dispatch_error:
                    logger.warning(
                        "Consumer automation dispatch failed monitor_id=%s error_code=%s",
                        monitor.monitor_id,
                        getattr(dispatch_error, "code", "unexpected_error"),
                    )
            return check_response(finished_check)
        except Exception as exc:
            error = _safe_error(exc)
            completed_at = self.clock()
            failed_check = replace(
                check,
                status=MonitorCheckStatus.FAILED,
                completed_at=completed_at,
                duration_ms=_duration_ms(started_clock),
                observed_spec_hash=observed_hash,
                error_code=error.code,
                error_message=error.message,
            )
            failed_monitor = replace(
                monitor,
                updated_at=completed_at,
                last_checked_at=completed_at,
                last_check_status=MonitorCheckStatus.FAILED,
                last_error_code=error.code,
                last_error_message=error.message,
                check_lease_expires_at=None,
            )
            self.repository.finish_check(failed_monitor, failed_check)
            raise error from exc


def monitor_response(monitor: ApiMonitor) -> MonitorResponse:
    values = {field: getattr(monitor, field) for field in MonitorResponse.model_fields}
    values["repository_url"] = monitor.repository_url or None
    values["specification_url"] = monitor.specification_url or None
    return MonitorResponse(**values)


def check_response(check: MonitorCheckRecord) -> MonitorCheckResponse:
    return MonitorCheckResponse.model_validate(check, from_attributes=True)


def _validated_repository(url: str | None, ref: str | None) -> tuple[str, str | None]:
    if not url:
        return "", None
    parsed = parse_github_repository_url(url)
    normalized_url = f"https://github.com/{parsed.owner}/{parsed.repository}"
    return normalized_url, validate_github_ref(ref)


def _safe_error(exc: Exception) -> DriftGuardError:
    if isinstance(exc, DriftGuardError):
        return exc
    return DriftGuardError(
        code="monitor_check_failed",
        message="The API monitor check could not be completed safely.",
        status_code=500,
    )


def _duration_ms(started_clock: float) -> int:
    return max(0, int((perf_counter() - started_clock) * 1000))


def _monitor_not_found() -> None:
    raise DriftGuardError(
        code="monitor_not_found",
        message="The requested API monitor does not exist.",
        status_code=404,
    )
