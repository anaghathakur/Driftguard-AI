"""Public GitHub App webhook route; authentication is the verified HMAC signature."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response

from apps.api.app.core.config import settings
from apps.api.app.core.dependencies import get_github_webhook_service
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.github.webhooks import GitHubWebhookService

router = APIRouter(prefix="/github", tags=["GitHub automation"])
Service = Annotated[GitHubWebhookService, Depends(get_github_webhook_service)]


@router.post("/webhooks")
async def receive_github_webhook(
    request: Request,
    response: Response,
    service: Service,
    x_hub_signature_256: Annotated[str | None, Header()] = None,
    x_github_event: Annotated[str | None, Header()] = None,
    x_github_delivery: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    declared_length = request.headers.get("content-length")
    if declared_length:
        try:
            if int(declared_length) > settings.max_webhook_bytes:
                raise _too_large()
        except ValueError as exc:
            raise DriftGuardError(
                code="github_webhook_headers_invalid",
                message="The GitHub webhook Content-Length header is invalid.",
                status_code=400,
            ) from exc
    body = await request.body()
    if len(body) > settings.max_webhook_bytes:
        raise _too_large()
    status, result = service.accept(
        raw_body=body,
        signature=x_hub_signature_256,
        event_type=x_github_event,
        github_delivery_id=x_github_delivery,
    )
    response.status_code = status
    return result


def _too_large() -> DriftGuardError:
    return DriftGuardError(
        code="github_webhook_payload_too_large",
        message="The GitHub webhook payload exceeds the configured limit.",
        status_code=413,
    )
