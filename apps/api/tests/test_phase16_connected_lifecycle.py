from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.app.auth.provider import MockGitHubOAuthProvider
from apps.api.app.auth.service import AuthService
from apps.api.app.core.dependencies import (
    get_analysis_repository,
    get_github_installation_provider,
    get_github_onboarding_service,
    get_github_repository_source,
)
from apps.api.app.github.installations import (
    GitHubRepositoryInfo,
    MockGitHubInstallationProvider,
)
from apps.api.app.github.service import GitHubOnboardingService
from apps.api.app.github.source import ConnectedAwareGitHubRepositorySource
from apps.api.app.infrastructure.sqlite_analysis_repository import SQLiteAnalysisRepository
from apps.api.app.infrastructure.sqlite_workspace_repository import SQLiteWorkspaceRepository
from apps.api.app.main import app
from apps.api.app.repository.github_source import GitHubRepositoryArchive
from apps.api.tests.test_patches import archive_bytes, patch_specs


class CountingInstallationProvider(MockGitHubInstallationProvider):
    def __init__(self) -> None:
        super().__init__()
        self.fetches = 0

    async def fetch_repository(self, installation_id: int, repository_id: int, ref: str | None):
        self.fetches += 1
        return await super().fetch_repository(installation_id, repository_id, ref)


def test_connected_repository_analysis_refetches_private_snapshot_for_patch_and_validation(
    tmp_path, base_spec
) -> None:
    database = tmp_path / "connected-lifecycle.sqlite3"
    analyses = SQLiteAnalysisRepository(database)
    analyses.initialize()
    platform = SQLiteWorkspaceRepository(database)
    platform.initialize()
    auth = AuthService(
        platform,
        MockGitHubOAuthProvider(),
        callback_url="http://testserver/api/v1/auth/github/callback",
        frontend_url="http://localhost:5173",
        session_ttl_hours=1,
        session_secret="test-session-secret-that-is-long-enough",
    )
    provider = CountingInstallationProvider()
    provider.repositories[1] = [
        GitHubRepositoryInfo(
            99,
            "driftguard",
            "payments-private",
            "driftguard/payments-private",
            "main",
            True,
            "https://github.com/driftguard/payments-private",
        )
    ]
    project_root = Path(__file__).parents[3]
    source_root = project_root / "sample-data" / "repositories" / "payments-ready"
    files = {
        path.relative_to(source_root).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(source_root.rglob("*.py"))
    }
    provider.archives[99] = GitHubRepositoryArchive(
        owner="driftguard",
        repository="payments-private",
        ref="main",
        filename="payments-private.zip",
        content=archive_bytes(files),
        commit_sha="a" * 40,
    )
    onboarding = GitHubOnboardingService(platform, provider, auth)
    connected_source = ConnectedAwareGitHubRepositorySource(platform, provider)
    app.dependency_overrides[get_analysis_repository] = lambda: analyses
    app.dependency_overrides[get_github_installation_provider] = lambda: provider
    app.dependency_overrides[get_github_onboarding_service] = lambda: onboarding
    app.dependency_overrides[get_github_repository_source] = lambda: connected_source

    try:
        with TestClient(app) as client:
            installation = client.post(
                "/api/v1/github/installations", json={"github_installation_id": 1}
            )
            assert installation.status_code == 201, installation.text
            synchronized = client.post(
                f"/api/v1/github/installations/{installation.json()['id']}/sync"
            )
            assert synchronized.status_code == 200, synchronized.text
            repository = synchronized.json()[0]
            assert repository["private"] is True

            old, new = patch_specs(base_spec, deepcopy)
            analyzed = client.post(
                "/api/v1/impact/analyze/connected",
                files={
                    "old_spec": ("old.json", json.dumps(old), "application/json"),
                    "new_spec": ("new.json", json.dumps(new), "application/json"),
                },
                data={"repository_id": repository["id"], "ref": "main"},
            )
            assert analyzed.status_code == 200, analyzed.text
            result = analyzed.json()
            assert result["impact_summary"]["impacted_files"] >= 1
            assert any(impact["matches"] for impact in result["impacts"])

            unauthorized = client.post(
                "/api/v1/impact/analyze/connected",
                files={
                    "old_spec": ("old.json", json.dumps(old), "application/json"),
                    "new_spec": ("new.json", json.dumps(new), "application/json"),
                },
                data={"repository_id": "client-supplied-arbitrary-id"},
            )
            assert unauthorized.status_code == 403
            assert unauthorized.json()["error"]["code"] == "repository_not_authorized"

            analysis_id = result["analysis_id"]
            patch = client.post(f"/api/v1/analyses/{analysis_id}/patches")
            assert patch.status_code == 200, patch.text
            validated = client.post(
                f"/api/v1/analyses/{analysis_id}/patches/{patch.json()['patch_id']}/validations"
            )
            assert validated.status_code == 200, validated.text
            assert validated.json()["static_only"] is True
            assert client.get(f"/api/v1/analyses/{analysis_id}/report").status_code == 200
            assert client.get(f"/api/v1/analyses/{analysis_id}/report.pdf").content.startswith(
                b"%PDF-"
            )
            assert provider.fetches >= 3
    finally:
        app.dependency_overrides.clear()
