"""Minimal browser-facing security headers for API responses."""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class SecurityHeadersMiddleware:
    """Add defensive response headers without inspecting request or response bodies."""

    def __init__(self, app: ASGIApp, *, production: bool) -> None:
        self.app = app
        self.production = production

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower()
                    not in {
                        b"permissions-policy",
                        b"referrer-policy",
                        b"strict-transport-security",
                        b"x-content-type-options",
                        b"x-frame-options",
                    }
                ]
                headers.extend(
                    [
                        (b"permissions-policy", b"camera=(), geolocation=(), microphone=()"),
                        (b"referrer-policy", b"strict-origin-when-cross-origin"),
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                    ]
                )
                if self.production:
                    headers.append(
                        (
                            b"strict-transport-security",
                            b"max-age=31536000; includeSubDomains",
                        )
                    )
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_security_headers)
