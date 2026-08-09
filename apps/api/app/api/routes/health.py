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

    ready = not issues
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ready" if ready else "not_ready",
        "checks": {
            "storage": settings.storage_backend,
            "analysis_engine": "ready",
            "risk_classifier": "model_with_deterministic_fallback",
            "migration_provider": settings.ai_provider,
            "patch_provider": settings.ai_provider,
            "test_plan_provider": settings.test_plan_provider,
            "github_write_provider": settings.github_write_provider,
            "monitor_scheduler": (
                "process_local_enabled"
                if settings.monitor_scheduler_enabled
                else "disabled"
            ),
        },
        "issues": issues,
    }

