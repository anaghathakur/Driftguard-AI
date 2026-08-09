"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit


def _positive_int(
    name: str,
    default: int,
) -> int:
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


def _non_negative_int(
    name: str,
    default: int,
) -> int:
    raw_value = os.getenv(name)

    if raw_value is None:
        return default

    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc

    if value < 0:
        raise RuntimeError(f"{name} must be zero or greater")

    return value


def _positive_float(
    name: str,
    default: float,
) -> float:
    raw_value = os.getenv(name)

    if raw_value is None:
        return default

    try:
        value = float(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number") from exc

    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero")

    return value


def _boolean(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be a boolean")


def _origins(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    origins: list[str] = []
    for value in raw_value.split(","):
        origin = value.strip().rstrip("/")
        if not origin:
            continue
        parsed = urlsplit(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise RuntimeError(
                f"{name} must contain comma-separated HTTP(S) origins without paths"
            )
        if origin not in origins:
            origins.append(origin)

    if not origins:
        raise RuntimeError(f"{name} must contain at least one origin")
    return tuple(origins)


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str = "DriftGuard AI"
    api_prefix: str = "/api/v1"

    cors_allowed_origins: tuple[str, ...] = _origins(
        "DRIFTGUARD_CORS_ALLOWED_ORIGINS",
        (
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ),
    )

    storage_backend: str = (
        os.getenv(
            "DRIFTGUARD_STORAGE_BACKEND",
            "sqlite",
        )
        .strip()
        .lower()
    )

    firestore_project_id: str = os.getenv(
        "DRIFTGUARD_FIRESTORE_PROJECT_ID",
        "",
    ).strip()

    firestore_database_id: str = os.getenv(
        "DRIFTGUARD_FIRESTORE_DATABASE_ID",
        "(default)",
    ).strip()

    database_path: str = os.getenv(
        "DRIFTGUARD_DATABASE_PATH",
        "data/driftguard.sqlite3",
    )

    risk_model_path: str = os.getenv(
        "DRIFTGUARD_RISK_MODEL_PATH",
        "apps/api/models/risk/v1.0.0/risk_model.joblib",
    )

    risk_model_metadata_path: str = os.getenv(
        "DRIFTGUARD_RISK_MODEL_METADATA_PATH",
        "apps/api/models/risk/v1.0.0/metadata.json",
    )

    ai_provider: str = (
        os.getenv(
            "DRIFTGUARD_AI_PROVIDER",
            "mock",
        )
        .strip()
        .lower()
    )

    gemini_api_key: str = os.getenv(
        "DRIFTGUARD_GEMINI_API_KEY",
        "",
    ).strip()

    gemini_model: str = os.getenv(
        "DRIFTGUARD_GEMINI_MODEL",
        "gemini-3.6-flash",
    ).strip()

    ai_timeout_seconds: float = _positive_float(
        "DRIFTGUARD_AI_TIMEOUT_SECONDS",
        20.0,
    )

    github_timeout_seconds: float = _positive_float(
        "DRIFTGUARD_GITHUB_TIMEOUT_SECONDS",
        20.0,
    )

    remote_spec_timeout_seconds: float = _positive_float(
        "DRIFTGUARD_REMOTE_SPEC_TIMEOUT_SECONDS",
        20.0,
    )

    remote_spec_max_redirects: int = _positive_int(
        "DRIFTGUARD_REMOTE_SPEC_MAX_REDIRECTS",
        3,
    )

    monitor_scheduler_enabled: bool = _boolean(
        "DRIFTGUARD_MONITOR_SCHEDULER_ENABLED",
        False,
    )

    monitor_poll_seconds: float = _positive_float(
        "DRIFTGUARD_MONITOR_POLL_SECONDS",
        30.0,
    )

    ai_max_retries: int = _non_negative_int(
        "DRIFTGUARD_AI_MAX_RETRIES",
        1,
    )

    ai_prompt_version: str = os.getenv(
        "DRIFTGUARD_AI_PROMPT_VERSION",
        "migration-prompt-v1",
    ).strip()

    ai_schema_version: str = os.getenv(
        "DRIFTGUARD_AI_SCHEMA_VERSION",
        "migration-schema-v1",
    ).strip()

    max_spec_file_bytes: int = _positive_int(
        "DRIFTGUARD_MAX_SPEC_FILE_BYTES",
        5 * 1024 * 1024,
    )

    max_repository_archive_bytes: int = _positive_int(
        "DRIFTGUARD_MAX_REPOSITORY_ARCHIVE_BYTES",
        20 * 1024 * 1024,
    )

    max_repository_files: int = _positive_int(
        "DRIFTGUARD_MAX_REPOSITORY_FILES",
        2_000,
    )

    max_repository_file_bytes: int = _positive_int(
        "DRIFTGUARD_MAX_REPOSITORY_FILE_BYTES",
        1024 * 1024,
    )

    max_repository_uncompressed_bytes: int = _positive_int(
        "DRIFTGUARD_MAX_REPOSITORY_UNCOMPRESSED_BYTES",
        50 * 1024 * 1024,
    )

    max_repository_compression_ratio: int = _positive_int(
        "DRIFTGUARD_MAX_REPOSITORY_COMPRESSION_RATIO",
        100,
    )

    max_code_symbols: int = _positive_int(
        "DRIFTGUARD_MAX_CODE_SYMBOLS",
        10_000,
    )

    max_code_graph_edges: int = _positive_int(
        "DRIFTGUARD_MAX_CODE_GRAPH_EDGES",
        25_000,
    )

    max_impact_depth: int = _positive_int(
        "DRIFTGUARD_MAX_IMPACT_DEPTH",
        3,
    )

    max_patch_files: int = _positive_int(
        "DRIFTGUARD_MAX_PATCH_FILES",
        5,
    )

    max_patch_edits: int = _positive_int(
        "DRIFTGUARD_MAX_PATCH_EDITS",
        20,
    )

    max_patch_context_bytes: int = _positive_int(
        "DRIFTGUARD_MAX_PATCH_CONTEXT_BYTES",
        40_000,
    )

    max_patch_replacement_bytes: int = _positive_int(
        "DRIFTGUARD_MAX_PATCH_REPLACEMENT_BYTES",
        20_000,
    )

    max_patch_diff_bytes: int = _positive_int(
        "DRIFTGUARD_MAX_PATCH_DIFF_BYTES",
        100_000,
    )

    test_plan_provider: str = (
        os.getenv(
            "DRIFTGUARD_TEST_PLAN_PROVIDER",
            "mock",
        )
        .strip()
        .lower()
    )

    max_validation_findings: int = _positive_int(
        "DRIFTGUARD_MAX_VALIDATION_FINDINGS",
        100,
    )

    max_related_tests: int = _positive_int(
        "DRIFTGUARD_MAX_RELATED_TESTS",
        50,
    )

    max_test_plan_cases: int = _positive_int(
        "DRIFTGUARD_MAX_TEST_PLAN_CASES",
        12,
    )

    max_test_context_bytes: int = _positive_int(
        "DRIFTGUARD_MAX_TEST_CONTEXT_BYTES",
        40_000,
    )

    github_write_provider: str = (
        os.getenv(
            "DRIFTGUARD_GITHUB_WRITE_PROVIDER",
            "mock",
        )
        .strip()
        .lower()
    )

    github_app_id: str = os.getenv(
        "DRIFTGUARD_GITHUB_APP_ID",
        "",
    ).strip()

    github_app_private_key_path: str = os.getenv(
        "DRIFTGUARD_GITHUB_APP_PRIVATE_KEY_PATH",
        "",
    ).strip()

    max_pull_request_body_bytes: int = _positive_int(
        "DRIFTGUARD_MAX_PULL_REQUEST_BODY_BYTES",
        20_000,
    )

    max_pull_request_modified_bytes: int = _positive_int(
        "DRIFTGUARD_MAX_PULL_REQUEST_MODIFIED_BYTES",
        1024 * 1024,
    )


settings = Settings()
