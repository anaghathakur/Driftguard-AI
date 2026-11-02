from __future__ import annotations

from fastapi import FastAPI

from apps.api.app.core.rate_limit import (
    RateLimit,
    _bucket_for,
    _limit_for,
)
from apps.api.app.core.workspace_context import WorkspacePrincipal, workspace_scope


def test_expensive_route_limit_is_workspace_scoped() -> None:
    app = FastAPI()
    request = _request(app, "/api/v1/impact/analyze")
    assert _limit_for(request) == RateLimit("analysis", 10, 600)

    with workspace_scope(WorkspacePrincipal("workspace-a", "user-a")):
        first = _bucket_for(request, RateLimit("analysis", 10, 600))
    with workspace_scope(WorkspacePrincipal("workspace-b", "user-a")):
        second = _bucket_for(request, RateLimit("analysis", 10, 600))

    assert first != second
    assert "user-a" in first
    assert "workspace-a" in first


def test_only_declared_routes_are_rate_limited() -> None:
    app = FastAPI()
    assert _limit_for(_request(app, "/api/v1/analyses", method="GET")) is None
    assert _limit_for(_request(app, "/api/v1/auth/github/start")) == RateLimit(
        "oauth_start", 20, 600
    )
    assert _limit_for(_request(app, "/api/v1/github/webhooks")) == RateLimit(
        "github_webhook", 120, 60
    )


def _request(app: FastAPI, path: str, method: str = "POST"):
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "client": ("198.51.100.1", 12345),
        "scheme": "https",
        "server": ("testserver", 443),
        "app": app,
    }
    from starlette.requests import Request

    return Request(scope)
