from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.app.auth.middleware import WorkspaceContextMiddleware
from apps.api.app.auth.provider import MockGitHubOAuthProvider
from apps.api.app.auth.service import AuthService
from apps.api.app.core.config import Settings
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.core.workspace_context import WorkspacePrincipal
from apps.api.app.domain.workspace import User, Workspace, WorkspaceMembership, WorkspaceRole
from apps.api.app.github.installations import (
    GitHubRepositoryInfo,
    MockGitHubInstallationProvider,
)
from apps.api.app.github.service import GitHubOnboardingService
from apps.api.app.infrastructure.sqlite_workspace_repository import SQLiteWorkspaceRepository
from apps.api.app.repository.github_source import GitHubRepositoryArchive


def _auth(tmp_path) -> tuple[SQLiteWorkspaceRepository, AuthService]:
    repository = SQLiteWorkspaceRepository(tmp_path / "security.sqlite3")
    repository.initialize()
    return repository, AuthService(
        repository,
        MockGitHubOAuthProvider(),
        callback_url="http://testserver/api/v1/auth/github/callback",
        frontend_url="http://localhost:5173",
        session_ttl_hours=1,
        session_secret="test-session-secret-that-is-long-enough",
    )


def _app(settings: Settings, auth: AuthService) -> FastAPI:
    app = FastAPI()
    app.add_middleware(WorkspaceContextMiddleware, settings=settings, auth_service=auth)

    @app.get("/api/v1/protected")
    def protected() -> dict[str, bool]:
        return {"ok": True}

    return app


def _workspace(repository: SQLiteWorkspaceRepository) -> tuple[User, Workspace]:
    now = datetime.now(UTC)
    user = repository.upsert_user(User("user", 10, "engineer", "Engineer", None, now, now))
    workspace = Workspace("workspace", "Engineering", "engineering", now, now)
    repository.create_workspace(
        workspace,
        WorkspaceMembership(
            "membership", workspace.workspace_id, user.user_id, WorkspaceRole.OWNER, now
        ),
    )
    return user, workspace


def _archive() -> GitHubRepositoryArchive:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("repo/src/client.py", "requests.post('/payments')\n")
    return GitHubRepositoryArchive(
        owner="engineering",
        repository="private-api",
        ref="main",
        filename="private-api.zip",
        content=output.getvalue(),
        commit_sha="a" * 40,
    )


def test_local_mode_allows_existing_anonymous_flow(tmp_path) -> None:
    _repository, auth = _auth(tmp_path)
    with TestClient(_app(Settings(auth_mode="local"), auth)) as client:
        assert client.get("/api/v1/protected").status_code == 200


def test_github_mode_requires_auth_and_rejects_invalid_session(tmp_path) -> None:
    _repository, auth = _auth(tmp_path)
    settings = Settings(
        auth_mode="github",
        session_secret="test-session-secret-that-is-long-enough",
        github_oauth_provider="mock",
    )
    with TestClient(_app(settings, auth)) as client:
        response = client.get("/api/v1/protected")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "auth_required"
        client.cookies.set(settings.session_cookie_name, "invalid")
        response = client.get("/api/v1/protected")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_session"


def test_csrf_is_required_for_authenticated_mutations(tmp_path) -> None:
    repository, auth = _auth(tmp_path)
    user, workspace = _workspace(repository)
    now = datetime.now(UTC)
    from apps.api.app.domain.workspace import AuthSession

    raw_session = "opaque-session"
    raw_csrf = "csrf-value"
    repository.save_session(
        AuthSession(
            auth._hash(raw_session),
            user.user_id,
            workspace.workspace_id,
            auth._hash(raw_csrf),
            now,
            now + timedelta(hours=1),
        )
    )
    settings = Settings(
        auth_mode="github",
        session_secret="test-session-secret-that-is-long-enough",
        github_oauth_provider="mock",
    )
    app = _app(settings, auth)

    @app.post("/api/v1/protected")
    def mutate() -> dict[str, bool]:
        return {"ok": True}

    with TestClient(app) as client:
        client.cookies.set(settings.session_cookie_name, raw_session)
        assert client.post("/api/v1/protected").status_code == 403
        assert (
            client.post("/api/v1/protected", headers={"X-CSRF-Token": raw_csrf}).status_code == 200
        )


def test_private_repository_fetch_requires_provider_authorization() -> None:
    provider = MockGitHubInstallationProvider()
    provider.repositories[1] = [
        GitHubRepositoryInfo(
            99,
            "engineering",
            "private-api",
            "engineering/private-api",
            "main",
            True,
            "https://github.com/engineering/private-api",
        )
    ]
    provider.archives[99] = _archive()
    fetched = asyncio.run(provider.fetch_repository(1, 99, None))
    assert fetched.commit_sha == "a" * 40
    with pytest.raises(DriftGuardError) as error:
        asyncio.run(provider.fetch_repository(1, 100, None))
    assert error.value.code == "repository_not_authorized"


def test_repository_sync_tracks_rename_and_revoked_installation(tmp_path) -> None:
    repository, auth = _auth(tmp_path)
    user, workspace = _workspace(repository)
    principal = WorkspacePrincipal(
        workspace.workspace_id, user.user_id, user.github_login, role=WorkspaceRole.OWNER
    )
    provider = MockGitHubInstallationProvider()
    provider.repositories[1] = [
        GitHubRepositoryInfo(
            99,
            "engineering",
            "api",
            "engineering/api",
            "main",
            True,
            "https://github.com/engineering/api",
        )
    ]
    service = GitHubOnboardingService(repository, provider, auth)
    installation = asyncio.run(service.connect(principal, 1))
    first = asyncio.run(service.sync(principal, installation.installation_id))[0]
    provider.repositories[1] = [
        GitHubRepositoryInfo(
            99,
            "engineering",
            "renamed",
            "engineering/renamed",
            "trunk",
            True,
            "https://github.com/engineering/renamed",
        )
    ]
    renamed = asyncio.run(service.sync(principal, installation.installation_id))[0]
    assert renamed.connection_id == first.connection_id
    assert renamed.full_name == "engineering/renamed"
    assert renamed.default_branch == "trunk"

    repository.upsert_installation(replace(installation, revoked_at=datetime.now(UTC)))
    with pytest.raises(DriftGuardError) as error:
        asyncio.run(service.sync(principal, installation.installation_id))
    assert error.value.code == "github_installation_revoked"
