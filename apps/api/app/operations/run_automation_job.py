"""Run one bounded durable-automation pass for Cloud Run Jobs."""

from __future__ import annotations

import asyncio
import logging

from apps.api.app.core.config import settings, validate_security_settings
from apps.api.app.core.dependencies import get_automation_worker
from apps.api.app.operations.bootstrap import initialize_stores

logger = logging.getLogger("driftguard.operations.automation")


async def run() -> int:
    validate_security_settings(settings)
    initialize_stores()
    processed = await get_automation_worker().run_once()
    logger.info("Automation job completed processed_jobs=%s", processed)
    return processed


if __name__ == "__main__":
    asyncio.run(run())
