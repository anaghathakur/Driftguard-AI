"""Distributed, fail-closed fixed-window limits for public and expensive routes."""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from google.cloud import firestore
from starlette.middleware.base import BaseHTTPMiddleware

from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.core.workspace_context import current_principal


@dataclass(frozen=True, slots=True)
class RateLimit:
    name: str
    maximum: int
    window_seconds: int


class RateLimiter(Protocol):
    async def check(self, bucket: str, limit: RateLimit) -> None: ...


class NoopRateLimiter:
    async def check(self, bucket: str, limit: RateLimit) -> None:
        del bucket, limit


class FirestoreRateLimiter:
    """Uses one transactional document per opaque bucket and fixed time window."""

    def __init__(self, *, project_id: str | None, database_id: str, client=None) -> None:
        self.client = client or firestore.Client(project=project_id, database=database_id)

    async def check(self, bucket: str, limit: RateLimit) -> None:
        now = int(time.time())
        try:
            allowed, retry_after = await asyncio.to_thread(
                self._consume, bucket, limit, now
            )
        except Exception as exc:
            raise DriftGuardError(
                code="rate_limit_unavailable",
                message="The request safety service is temporarily unavailable.",
                status_code=503,
            ) from exc
        if not allowed:
            raise DriftGuardError(
                code="rate_limit_exceeded",
                message="Too many requests. Please wait before trying again.",
                status_code=429,
                details={"retry_after_seconds": retry_after},
            )

    def _consume(
        self, bucket: str, limit: RateLimit, now: int
    ) -> tuple[bool, int]:
        window_start = now - (now % limit.window_seconds)
        document_id = hashlib.sha256(bucket.encode("utf-8")).hexdigest()
        reference = self.client.collection("rate_limits").document(document_id)
        transaction = self.client.transaction()

        @firestore.transactional
        def consume(transaction):
            snapshot = reference.get(transaction=transaction)
            data = snapshot.to_dict() if snapshot.exists else {}
            count = int(data.get("count", 0)) if data.get("window_start") == window_start else 0
            if count >= limit.maximum:
                return False, max(1, window_start + limit.window_seconds - now)
            transaction.set(
                reference,
                {
                    "count": count + 1,
                    "window_start": window_start,
                    "expires_at": datetime.fromtimestamp(
                        window_start + (2 * limit.window_seconds), tz=UTC
                    ),
                    "limit_name": limit.name,
                },
            )
            return True, 0

        return consume(transaction)


class DistributedRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, limiter: RateLimiter) -> None:
        super().__init__(app)
        self.limiter = limiter

    async def dispatch(self, request: Request, call_next) -> Response:
        limit = _limit_for(request)
        if limit is None:
            return await call_next(request)
        try:
            await self.limiter.check(_bucket_for(request, limit), limit)
        except DriftGuardError as exc:
            response = JSONResponse(
                status_code=exc.status_code,
                content={
                    "error": {
                        "code": exc.code,
                        "message": exc.message,
                        "details": exc.details,
                    }
                },
            )
            if exc.status_code == 429:
                response.headers["Retry-After"] = str(
                    exc.details.get("retry_after_seconds", 1)
                )
            return response
        return await call_next(request)


def _limit_for(request: Request) -> RateLimit | None:
    path = request.url.path
    if path == "/api/v1/auth/github/start":
        return RateLimit("oauth_start", 20, 600)
    if path == "/api/v1/github/webhooks":
        return RateLimit("github_webhook", 120, 60)
    if request.method != "POST":
        return None
    if path in {
        "/api/v1/impact/analyze",
        "/api/v1/impact/analyze/github",
        "/api/v1/impact/analyze/connected",
        "/api/v1/specifications/compare",
        "/api/v1/contracts/compare",
    }:
        return RateLimit("analysis", 10, 600)
    if path == "/api/v1/monitors" or path.endswith("/check"):
        return RateLimit("monitor", 12, 600)
    if path.endswith("/patches") or path.endswith("/validations") or path.endswith("/pull-request"):
        return RateLimit("remediation", 20, 600)
    return None


def _bucket_for(request: Request, limit: RateLimit) -> str:
    if limit.name in {"oauth_start", "github_webhook"}:
        client_host = request.client.host if request.client else "unknown"
        return f"{limit.name}:client:{client_host}"
    principal = current_principal()
    client_host = request.client.host if request.client else "unknown"
    actor = principal.user_id or client_host
    return f"{limit.name}:workspace:{principal.workspace_id}:actor:{actor}"
