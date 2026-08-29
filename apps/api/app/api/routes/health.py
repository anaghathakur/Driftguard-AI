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
    if settings.ai_provider not in {"mock", "gemini"}:
        issues.append("The selected migration and patch provider is unsupported.")
    if settings.test_plan_provider not in {"mock", "gemini"}:
        issues.append("The selected test-plan provider is unsupported.")
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

    if settings.ai_provider == "gemini" and not settings.gemini_api_key:
        issues.append("Gemini is selected but its API key is not configured.")
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
            "risk_classifier": "model_with_deterministic_fallback",
            "migration_provider": settings.ai_provider,
            "patch_provider": settings.ai_provider,
            "test_plan_provider": settings.test_plan_provider,
            "github_write_provider": settings.github_write_provider,
            "monitor_scheduler": (
                "process_local_enabled" if settings.monitor_scheduler_enabled else "disabled"
            ),
        },
            "github_webhooks": (
                "ready" if settings.github_webhook_secret else "disabled"
            ),
            "background_jobs": "sqlite_durable",
            "automation_worker": (
                "process_local_enabled" if settings.automation_worker_enabled else "disabled"
            ),
            "github_checks": settings.github_check_provider,
            "automation_persistence": "sqlite_sidecar",
        "issues": issues,
    }
