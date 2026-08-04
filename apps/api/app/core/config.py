"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _positive_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str = "DriftGuard AI"
    api_prefix: str = "/api/v1"
    max_spec_file_bytes: int = _positive_int(
        "DRIFTGUARD_MAX_SPEC_FILE_BYTES", 5 * 1024 * 1024
    )


settings = Settings()

