"""Repository interface for API monitor state and check history."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

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
