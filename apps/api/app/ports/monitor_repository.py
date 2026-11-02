"""Repository interface for API monitor state and check history."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import replace
from datetime import datetime

from apps.api.app.core.workspace_context import current_workspace_id
from apps.api.app.domain.monitor import ApiMonitor, MonitorCheckRecord


class ApiMonitorRepository(ABC):
    @abstractmethod
    def initialize(self) -> None:
        """Initialize monitor storage."""

    @abstractmethod
    def create(self, monitor: ApiMonitor) -> None:
        """Persist a new monitor."""

    @abstractmethod
    def save(self, monitor: ApiMonitor) -> None:
        """Persist monitor configuration and state."""

    @abstractmethod
    def get(self, monitor_id: str) -> ApiMonitor | None:
        """Return one monitor."""

    @abstractmethod
    def list(self) -> list[ApiMonitor]:
        """Return monitors newest first."""

    @abstractmethod
    def list_due(self, now: datetime) -> list[ApiMonitor]:
        """Return enabled monitors whose interval has elapsed."""

    def list_due_all(self, now: datetime) -> list[tuple[str, ApiMonitor]]:
        """Return due monitors paired with their trusted persisted workspace."""

        return [(current_workspace_id(), monitor) for monitor in self.list_due(now)]

    def claim_check(
        self,
        monitor_id: str,
        *,
        now: datetime,
        lease_expires_at: datetime,
    ) -> ApiMonitor | None:
        """Claim a monitor check or return None when another worker owns its lease.

        Concrete durable repositories must override this with an atomic operation.
        The fallback keeps lightweight in-memory test repositories compatible.
        """

        monitor = self.get(monitor_id)
        if monitor is None or (
            monitor.check_lease_expires_at is not None
            and monitor.check_lease_expires_at > now
        ):
            return None
        claimed = replace(monitor, check_lease_expires_at=lease_expires_at)
        self.save(claimed)
        return claimed

    @abstractmethod
    def delete(self, monitor_id: str) -> bool:
        """Delete a monitor and its check history."""

    @abstractmethod
    def start_check(self, monitor: ApiMonitor, check: MonitorCheckRecord) -> None:
        """Atomically record a running check and monitor state."""

    @abstractmethod
    def finish_check(self, monitor: ApiMonitor, check: MonitorCheckRecord) -> None:
        """Atomically finalize a check and monitor state."""

    @abstractmethod
    def list_checks(self, monitor_id: str) -> list[MonitorCheckRecord]:
        """Return newest-first check history."""
