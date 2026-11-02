from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.app.core.security_headers import SecurityHeadersMiddleware


def _client(*, production: bool) -> TestClient:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, production=production)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return TestClient(app)


def test_security_headers_are_sent_without_reading_response_content() -> None:
    with _client(production=False) as client:
        response = client.get("/health")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert response.headers["permissions-policy"] == "camera=(), geolocation=(), microphone=()"
    assert "strict-transport-security" not in response.headers


def test_production_responses_include_hsts() -> None:
    with _client(production=True) as client:
        response = client.get("/health")

    assert response.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"
