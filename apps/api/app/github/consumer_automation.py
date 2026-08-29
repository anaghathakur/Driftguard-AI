"""Bridge completed monitor impact analyses into durable consumer Check jobs."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from apps.api.app.core.workspace_context import current_workspace_id
from apps.api.app.domain.automation import (
    ApiDependency,
    BackgroundJob,
    BackgroundJobStatus,
    BackgroundJobType,
)
from apps.api.app.domain.monitor import ApiMonitor
from apps.api.app.ports.automation_repository import AutomationRepository
from apps.api.app.ports.workspace_repository import WorkspaceRepository
from apps.api.app.repository.github_source import parse_github_repository_url


class ConsumerAutomationDispatcher:
    def __init__(self, automation: AutomationRepository, workspaces: WorkspaceRepository) -> None:
        self.automation = automation
        self.workspaces = workspaces

    async def dispatch(self, monitor: ApiMonitor, analysis_id: str, commit_sha: str) -> None:
        workspace_id = current_workspace_id()
        parsed = parse_github_repository_url(monitor.repository_url)
        full_name = f"{parsed.owner}/{parsed.repository}".lower()
        connection = next(
            (
                item
                for item in self.workspaces.list_repositories(workspace_id)
                if item.full_name.lower() == full_name and item.enabled and item.removed_at is None
            ),
            None,
        )
        if connection is None:
            return
        installation = self.workspaces.get_installation(connection.installation_id)
        if installation is None or installation.revoked_at:
            return
        now = datetime.now(UTC)
        existing = next(
            (
                item
                for item in self.automation.list_dependencies(
                    workspace_id, connection.connection_id
                )
                if item.monitor_id == monitor.monitor_id
            ),
            None,
        )
        self.automation.save_dependency(
            ApiDependency(
                existing.dependency_id if existing else str(uuid4()),
                workspace_id,
                connection.connection_id,
                "monitor_repository_match",
                1.0,
                existing.created_at if existing else now,
                now,
                existing.contract_id if existing else None,
                monitor.monitor_id,
                None,
                True,
            )
        )
        self.automation.enqueue_job(
            BackgroundJob(
                str(uuid4()),
                workspace_id,
                BackgroundJobType.CONSUMER_IMPACT_ANALYSIS,
                BackgroundJobStatus.QUEUED,
                {
                    "installation_id": installation.installation_id,
                    "repository_connection_id": connection.connection_id,
                    "monitor_id": monitor.monitor_id,
                    "analysis_id": analysis_id,
                    "head_sha": commit_sha,
                },
                0,
                now,
            )
        )
