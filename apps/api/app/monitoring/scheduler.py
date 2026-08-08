"""Process-local scheduler for due API monitors."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from apps.api.app.monitoring.service import MonitorCheckService
from apps.api.app.ports.monitor_repository import ApiMonitorRepository


class MonitorScheduler:
    def __init__(
        self,
        repository: ApiMonitorRepository,
        check_service: MonitorCheckService,
        *,
        enabled: bool,
        poll_seconds: float,
    ) -> None:
        self.repository = repository
        self.check_service = check_service
        self.enabled = enabled
        self.poll_seconds = poll_seconds
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if not self.enabled or self._task is not None:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(), name="driftguard-monitor-scheduler")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop_event.set()
        await self._task
        self._task = None

    async def run_once(self, *, now: datetime | None = None) -> None:
        for monitor in self.repository.list_due(now or datetime.now(UTC)):
            try:
                await self.check_service.check(monitor.monitor_id)
            except Exception:
                continue

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            await self.run_once()
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.poll_seconds,
                )
            except TimeoutError:
                continue
