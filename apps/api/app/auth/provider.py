"""GitHub OAuth identity providers. Access tokens are used in memory and discarded."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from apps.api.app.core.exceptions import DriftGuardError


@dataclass(frozen=True, slots=True)
class GitHubIdentity:
    github_user_id: int
    login: str
    display_name: str | None
    avatar_url: str | None


class GitHubOAuthProvider(ABC):
    @abstractmethod
    def authorization_url(
        self,
        state: str,
        callback_url: str,
        identity_hint: str | None = None,
    ) -> str: ...

    @abstractmethod
    async def resolve_identity(self, code: str, callback_url: str) -> GitHubIdentity: ...


class MockGitHubOAuthProvider(GitHubOAuthProvider):
    def authorization_url(
        self,
        state: str,
        callback_url: str,
        identity_hint: str | None = None,
    ) -> str:
        del callback_url
        code = "mock-user-secondary" if identity_hint == "secondary" else "mock-user"
        return f"/api/v1/auth/github/callback?code={code}&state={state}"

    async def resolve_identity(self, code: str, callback_url: str) -> GitHubIdentity:
        del callback_url
        identities = {
            "mock-user": GitHubIdentity(
                1, "driftguard-dev", "DriftGuard Developer", None
            ),
            "mock-user-secondary": GitHubIdentity(
                2, "driftguard-reviewer", "DriftGuard Reviewer", None
            ),
        }
        identity = identities.get(code)
        if identity is None:
            raise DriftGuardError(
                code="github_oauth_failed",
                message="The development GitHub identity could not be verified.",
                status_code=401,
            )
        return identity


class RealGitHubOAuthProvider(GitHubOAuthProvider):
    def __init__(self, client_id: str, client_secret: str, timeout_seconds: float) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.timeout_seconds = timeout_seconds

    def authorization_url(
        self,
        state: str,
        callback_url: str,
        identity_hint: str | None = None,
    ) -> str:
        del identity_hint
        from urllib.parse import urlencode

        return "https://github.com/login/oauth/authorize?" + urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": callback_url,
                "scope": "read:user",
                "state": state,
            }
        )

    async def resolve_identity(self, code: str, callback_url: str) -> GitHubIdentity:
        if not self.client_id or not self.client_secret:
            raise DriftGuardError(
                code="github_oauth_not_configured",
                message="GitHub authentication is not configured.",
                status_code=503,
            )
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                token_response = await client.post(
                    "https://github.com/login/oauth/access_token",
                    headers={"Accept": "application/json"},
                    data={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "code": code,
                        "redirect_uri": callback_url,
                    },
                )
                token_response.raise_for_status()
                access_token = str(token_response.json().get("access_token", ""))
                if not access_token:
                    raise ValueError("missing access token")
                user_response = await client.get(
                    "https://api.github.com/user",
                    headers={
                        "Accept": "application/vnd.github+json",
                        "Authorization": f"Bearer {access_token}",
                        "User-Agent": "DriftGuard-AI/0.1",
                    },
                )
                user_response.raise_for_status()
                data = user_response.json()
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise DriftGuardError(
                code="github_oauth_failed",
                message="GitHub could not verify this sign-in request.",
                status_code=401,
            ) from exc
        return GitHubIdentity(
            github_user_id=int(data["id"]),
            login=str(data["login"]),
            display_name=str(data["name"]) if data.get("name") else None,
            avatar_url=str(data["avatar_url"]) if data.get("avatar_url") else None,
        )
