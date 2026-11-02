"""Run one bounded subscription-monitor pass for Cloud Run Jobs."""

from __future__ import annotations

import asyncio
import logging

from apps.api.app.core.config import settings, validate_security_settings
from apps.api.app.core.dependencies import get_monitor_scheduler
from apps.api.app.operations.bootstrap import initialize_stores

logger = logging.getLogger("driftguard.operations.monitor")


async def run() -> None:
    validate_security_settings(settings)
    initialize_stores()
    await get_monitor_scheduler().run_once()
    logger.info("Monitor job completed")


if __name__ == "__main__":
    asyncio.run(run())
