"""Process health and configuration readiness endpoints."""

from pathlib import Path

from fastapi import APIRouter, Response, status

from apps.api.app.core.config import settings

router = APIRouter(tags=["operations"])


@router.get(
    "/health",
    summary="Process health",
    description="Confirms that the DriftGuard API process can serve requests.",
)
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get(
    "/ready",
    summary="Configuration readiness",
    description=(
        "Checks selected local storage and provider configuration without contacting external "
        "services or exposing configuration values."
    ),
)
async def readiness(response: Response) -> dict[str, object]:
    issues: list[str] = []

    if settings.storage_backend not in {"sqlite", "firestore"}:
        issues.append("The selected storage backend is unsupported.")
    if settings.migration_provider not in {"deterministic", "mock", "gemini"}:
        issues.append("The selected migration provider is unsupported.")
    if settings.patch_provider not in {"deterministic", "mock", "gemini"}:
        issues.append("The selected patch provider is unsupported.")
    if settings.test_plan_provider not in {"deterministic", "mock", "gemini"}:
        issues.append("The selected test-plan provider is unsupported.")
    if settings.validation_execution_provider not in {"disabled", "local"}:
        issues.append("The selected validation execution provider is unsupported.")
    if settings.github_write_provider not in {"mock", "github_app"}:
        issues.append("The selected GitHub write provider is unsupported.")
    if settings.github_check_provider not in {"mock", "github_app"}:
        issues.append("The selected GitHub Check provider is unsupported.")
    if settings.automation_worker_enabled and not settings.github_webhook_secret:
        issues.append("GitHub automation is enabled but the webhook secret is not configured.")
    if settings.auth_mode not in {"local", "github"}:
        issues.append("The selected authentication mode is unsupported.")
    if settings.github_oauth_provider not in {"mock", "github"}:
        issues.append("The selected GitHub OAuth provider is unsupported.")
    if settings.auth_mode == "github":
        if len(settings.session_secret) < 32:
            issues.append(
                "GitHub authentication requires a session secret of at least 32 characters."
            )
        if settings.github_oauth_provider == "github" and (
            not settings.github_oauth_client_id or not settings.github_oauth_client_secret
        ):
            issues.append("GitHub authentication is enabled but OAuth credentials are incomplete.")
        if not settings.frontend_url.startswith(("http://", "https://")):
            issues.append("The configured frontend URL is invalid.")
        if not settings.github_oauth_callback_url.startswith(("http://", "https://")):
            issues.append("The configured GitHub OAuth callback URL is invalid.")

    if (
        settings.migration_provider == "gemini" or settings.patch_provider == "gemini"
    ) and not settings.gemini_api_key:
        issues.append("Gemini is selected for remediation but its API key is not configured.")
    if settings.test_plan_provider == "gemini" and not settings.gemini_api_key:
        issues.append("Gemini test planning is selected but its API key is not configured.")
    if settings.github_write_provider == "github_app":
        private_key = Path(settings.github_app_private_key_path)
        if not settings.github_app_id or not settings.github_app_private_key_path:
            issues.append("GitHub App writes are selected but App credentials are incomplete.")
        elif not private_key.is_file():
            issues.append("GitHub App writes are selected but the private-key file is unavailable.")
    if settings.github_check_provider == "github_app":
        private_key = Path(settings.github_app_private_key_path)
        if not settings.github_app_id or not private_key.is_file():
            issues.append("GitHub Check Runs are selected but App credentials are incomplete.")


    ready = not issues
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ready" if ready else "not_ready",
        "checks": {
            "storage": settings.storage_backend,
            "persistence": settings.storage_backend,
            "auth_provider": settings.auth_mode,
            "github_oauth": (
                settings.github_oauth_provider if settings.auth_mode == "github" else "not_required"
            ),
            "github_app": settings.github_write_provider,
            "analysis_engine": "ready",
            "risk_classifier": _risk_status(),
            "migration_provider": _remediation_status(settings.migration_provider),
            "patch_provider": _remediation_status(settings.patch_provider),
            "test_plan_provider": _test_provider_status(),
            "github_write_provider": _github_write_status(),
            "monitor_scheduler": (
                "process_local_enabled" if settings.monitor_scheduler_enabled else "disabled"
            ),
        },
            "github_webhooks": (
                "ready" if settings.github_webhook_secret else "disabled"
            ),
            "background_jobs": _automation_persistence_status(),
            "automation_worker": (
                "process_local_enabled" if settings.automation_worker_enabled else "disabled"
            ),
            "github_checks": settings.github_check_provider,
            "automation_persistence": _automation_persistence_status(),
        "issues": issues,
    }


def _risk_status() -> str:
    return (
        "ready"
        if Path(settings.risk_model_path).is_file()
        and Path(settings.risk_model_metadata_path).is_file()
        else "degraded"
    )


def _remediation_status(provider: str) -> str:
    if provider == "deterministic":
        return "ready"
    if provider == "gemini":
        return "ready" if settings.gemini_api_key else "not_configured"
    if provider == "mock":
        return (
            "mock_development_only"
            if settings.deployment_environment != "production"
            else "unavailable"
        )
    return "unavailable"


def _test_provider_status() -> str:
    if settings.validation_execution_provider == "local":
        return (
            "ready"
            if settings.deployment_environment in {"development", "test"}
            else "unavailable"
        )
    return "degraded"


def _github_write_status() -> str:
    if settings.github_write_provider == "github_app":
        private_key = Path(settings.github_app_private_key_path)
        signing_ready = False
        if settings.github_app_id and private_key.is_file():
            try:
                from google.auth.crypt import RSASigner

                RSASigner.from_string(private_key.read_bytes())
                signing_ready = True
            except Exception:
                signing_ready = False
        return (
            "ready"
            if signing_ready
            else "not_configured"
        )
    if settings.github_write_provider == "mock":
        return (
            "mock_development_only"
            if settings.deployment_environment != "production"
            else "unavailable"
        )
    return "unavailable"


def _automation_persistence_status() -> str:
    if settings.storage_backend == "firestore":
        return "firestore_durable"
    if settings.storage_backend == "sqlite":
        return "sqlite_single_instance"
    return "unavailable"
