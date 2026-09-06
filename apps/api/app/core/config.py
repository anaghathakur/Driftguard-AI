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
            raise RuntimeError(f"{name} must contain comma-separated HTTP(S) origins without paths")
        if origin not in origins:
            origins.append(origin)

    if not origins:
        raise RuntimeError(f"{name} must contain at least one origin")
    return tuple(origins)


@dataclass(frozen=True, slots=True)
class Settings:
    deployment_environment: str = os.getenv("DRIFTGUARD_ENVIRONMENT", "development").strip().lower()
    app_name: str = "DriftGuard AI"
    api_prefix: str = "/api/v1"

    auth_mode: str = os.getenv("DRIFTGUARD_AUTH_MODE", "local").strip().lower()
    session_secret: str = os.getenv("DRIFTGUARD_SESSION_SECRET", "").strip()
    session_cookie_name: str = os.getenv(
        "DRIFTGUARD_SESSION_COOKIE_NAME", "driftguard_session"
    ).strip()
    session_ttl_hours: int = _positive_int("DRIFTGUARD_SESSION_TTL_HOURS", 24 * 7)
    secure_cookies: bool = _boolean("DRIFTGUARD_SECURE_COOKIES", False)
    github_oauth_provider: str = (
        os.getenv("DRIFTGUARD_GITHUB_OAUTH_PROVIDER", "github").strip().lower()
    )
    github_oauth_client_id: str = os.getenv("DRIFTGUARD_GITHUB_OAUTH_CLIENT_ID", "").strip()
    github_oauth_client_secret: str = os.getenv("DRIFTGUARD_GITHUB_OAUTH_CLIENT_SECRET", "").strip()
    github_oauth_callback_url: str = os.getenv(
        "DRIFTGUARD_GITHUB_OAUTH_CALLBACK_URL",
        "http://127.0.0.1:8000/api/v1/auth/github/callback",
    ).strip()
    frontend_url: str = (
        os.getenv("DRIFTGUARD_FRONTEND_URL", "http://localhost:5173").strip().rstrip("/")
    )
    github_app_install_url: str = os.getenv("DRIFTGUARD_GITHUB_APP_INSTALL_URL", "").strip()

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
            "deterministic",
        )
        .strip()
        .lower()
    )

    migration_provider: str = (
        os.getenv(
            "DRIFTGUARD_MIGRATION_PROVIDER",
            (
                "gemini"
                if os.getenv("DRIFTGUARD_AI_PROVIDER", "").strip().lower() == "gemini"
                else "deterministic"
            ),
        )
        .strip()
        .lower()
    )

    patch_provider: str = (
        os.getenv(
            "DRIFTGUARD_PATCH_PROVIDER",
            (
                "gemini"
                if os.getenv("DRIFTGUARD_AI_PROVIDER", "").strip().lower() == "gemini"
                else "deterministic"
            ),
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

    max_graphql_document_bytes: int = _positive_int(
        "DRIFTGUARD_MAX_GRAPHQL_DOCUMENT_BYTES",
        5 * 1024 * 1024,
    )
    max_graphql_ast_nodes: int = _positive_int(
        "DRIFTGUARD_MAX_GRAPHQL_AST_NODES",
        100_000,
    )
    max_graphql_changes: int = _positive_int(
        "DRIFTGUARD_MAX_GRAPHQL_CHANGES",
        1_000,
    )
    max_graphql_query_documents: int = _positive_int(
        "DRIFTGUARD_MAX_GRAPHQL_QUERY_DOCUMENTS",
        500,
    )
    max_repository_archive_bytes: int = _positive_int(
        "DRIFTGUARD_MAX_REPOSITORY_ARCHIVE_BYTES",
        20 * 1024 * 1024,
    )

    max_repository_files: int = _positive_int(
        "DRIFTGUARD_MAX_REPOSITORY_FILES",
        10_000,
    )

    max_repository_file_bytes: int = _positive_int(
        "DRIFTGUARD_MAX_REPOSITORY_FILE_BYTES",
        2 * 1024 * 1024,
    )

    max_repository_uncompressed_bytes: int = _positive_int(
        "DRIFTGUARD_MAX_REPOSITORY_UNCOMPRESSED_BYTES",
        50 * 1024 * 1024,
    )

    max_repository_compression_ratio: int = _positive_int(
        "DRIFTGUARD_MAX_REPOSITORY_COMPRESSION_RATIO",
        100,
    )

    max_repository_tree_entries: int = _positive_int(
        "DRIFTGUARD_MAX_REPOSITORY_TREE_ENTRIES", 20_000
    )
    max_repository_source_files: int = _positive_int(
        "DRIFTGUARD_MAX_REPOSITORY_SOURCE_FILES", 7_500
    )
    max_repository_source_file_bytes: int = _positive_int(
        "DRIFTGUARD_MAX_REPOSITORY_SOURCE_FILE_BYTES", 2 * 1024 * 1024
    )
    max_repository_source_bytes: int = _positive_int(
        "DRIFTGUARD_MAX_REPOSITORY_SOURCE_BYTES", 25 * 1024 * 1024
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
            "deterministic",
        )
        .strip()
        .lower()
    )

    validation_execution_provider: str = (
        os.getenv("DRIFTGUARD_VALIDATION_EXECUTION_PROVIDER", "disabled").strip().lower()
    )

    validation_command_timeout_seconds: float = _positive_float(
        "DRIFTGUARD_VALIDATION_COMMAND_TIMEOUT_SECONDS",
        60.0,
    )

    validation_output_max_bytes: int = _positive_int(
        "DRIFTGUARD_VALIDATION_OUTPUT_MAX_BYTES",
        100_000,
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

    github_webhook_secret: str = os.getenv("DRIFTGUARD_GITHUB_WEBHOOK_SECRET", "").strip()
    max_webhook_bytes: int = _positive_int("DRIFTGUARD_MAX_WEBHOOK_BYTES", 2 * 1024 * 1024)
    automation_worker_enabled: bool = _boolean("DRIFTGUARD_AUTOMATION_WORKER_ENABLED", False)
    automation_worker_poll_seconds: float = _positive_float(
        "DRIFTGUARD_AUTOMATION_WORKER_POLL_SECONDS", 5.0
    )
    automation_max_retries: int = _non_negative_int("DRIFTGUARD_AUTOMATION_MAX_RETRIES", 3)
    automation_retry_base_seconds: float = _positive_float(
        "DRIFTGUARD_AUTOMATION_RETRY_BASE_SECONDS", 15.0
    )
    github_check_provider: str = (
        os.getenv("DRIFTGUARD_GITHUB_CHECK_PROVIDER", "mock").strip().lower()
    )
    max_check_annotations: int = _positive_int("DRIFTGUARD_MAX_CHECK_ANNOTATIONS", 50)


settings = Settings()


def validate_security_settings(value: Settings) -> None:
    if value.deployment_environment not in {"development", "test", "production"}:
        raise RuntimeError("DRIFTGUARD_ENVIRONMENT must be 'development', 'test', or 'production'")
    if value.auth_mode not in {"local", "github"}:
        raise RuntimeError("DRIFTGUARD_AUTH_MODE must be 'local' or 'github'")
    if value.github_oauth_provider not in {"github", "mock"}:
        raise RuntimeError("DRIFTGUARD_GITHUB_OAUTH_PROVIDER must be 'github' or 'mock'")
    if value.deployment_environment != "production":
        return
    problems: list[str] = []
    if value.auth_mode != "github":
        problems.append("production requires DRIFTGUARD_AUTH_MODE=github")
    if value.github_oauth_provider != "github":
        problems.append("production prohibits the mock OAuth provider")
    if value.migration_provider == "mock":
        problems.append("production prohibits the mock migration provider")
    if value.patch_provider == "mock":
        problems.append("production prohibits the mock patch provider")
    if value.test_plan_provider == "mock":
        problems.append("production prohibits the mock test-plan provider")
    if value.github_write_provider == "mock":
        problems.append("production prohibits the mock GitHub write provider")
    if value.github_check_provider == "mock":
        problems.append("production prohibits the mock GitHub Check provider")
    if value.validation_execution_provider == "local":
        problems.append("production prohibits the process-local validation runner")
    if len(value.session_secret) < 32:
        problems.append("DRIFTGUARD_SESSION_SECRET must contain at least 32 characters")
    if not value.secure_cookies:
        problems.append("production requires DRIFTGUARD_SECURE_COOKIES=true")
    if not value.github_oauth_client_id or not value.github_oauth_client_secret:
        problems.append("production GitHub OAuth credentials are required")
    callback = urlsplit(value.github_oauth_callback_url)
    if callback.scheme != "https" or not callback.netloc:
        problems.append("production OAuth callback URL must use HTTPS")
    frontend = urlsplit(value.frontend_url)
    if frontend.scheme != "https" or not frontend.netloc:
        problems.append("production frontend URL must use HTTPS")
    if problems:
        raise RuntimeError("Unsafe production authentication configuration: " + "; ".join(problems))
