from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from io import BytesIO
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from apps.api.app.auth.provider import MockGitHubOAuthProvider
from apps.api.app.auth.service import AuthService
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.core.workspace_context import (
    LOCAL_WORKSPACE_ID,
    WorkspacePrincipal,
    workspace_scope,
)
from apps.api.app.domain.analysis import AnalysisKind, AnalysisSubmission
from apps.api.app.domain.monitor import ApiMonitor
from apps.api.app.domain.workspace import User, Workspace, WorkspaceMembership, WorkspaceRole
from apps.api.app.github.installations import (
    GitHubRepositoryInfo,
    MockGitHubInstallationProvider,
)
from apps.api.app.github.service import GitHubOnboardingService
from apps.api.app.infrastructure.sqlite_analysis_repository import SQLiteAnalysisRepository
from apps.api.app.infrastructure.sqlite_monitor_repository import SQLiteMonitorRepository
from apps.api.app.infrastructure.sqlite_workspace_repository import SQLiteWorkspaceRepository
from apps.api.app.patches.provider import MockPatchGenerationProvider
from apps.api.app.patches.service import PatchProposalService
from apps.api.app.pull_requests.provider import MockGitHubWriteProvider
from apps.api.app.pull_requests.service import PullRequestWorkflowService
from apps.api.app.repository.github_source import GitHubRepositorySource
from apps.api.app.repository.scanner import RepositoryArchiveScanner
from apps.api.app.validation.provider import MockTestPlanProvider
from apps.api.app.validation.service import PatchValidationService


def _platform(tmp_path):
    repository = SQLiteWorkspaceRepository(tmp_path / "phase16.sqlite3")
    repository.initialize()
    return repository


def _auth(repository) -> AuthService:
    return AuthService(
        repository,
        MockGitHubOAuthProvider(),
        callback_url="http://testserver/api/v1/auth/github/callback",
        frontend_url="http://localhost:5173",
        session_ttl_hours=1,
        session_secret="test-session-secret-that-is-long-enough",
    )


def _team(repository, name: str) -> tuple[User, Workspace]:
    now = datetime.now(UTC)
    user = repository.upsert_user(
        User(str(uuid4()), uuid4().int & (2**31 - 1), name.lower(), name, None, now, now)
    )
    workspace = Workspace(str(uuid4()), name, f"{name.lower()}-{uuid4().hex[:6]}", now, now)
    repository.create_workspace(
        workspace,
        WorkspaceMembership(
            str(uuid4()), workspace.workspace_id, user.user_id, WorkspaceRole.OWNER, now
        ),
    )
    return user, workspace


def _submission(fingerprint: str) -> AnalysisSubmission:
    now = datetime.now(UTC)
    return AnalysisSubmission(
        kind=AnalysisKind.COMPARISON,
        request_fingerprint=fingerprint,
        old_filename="old.json",
        new_filename="new.json",
        repository_filename=None,
        old_file_sha256="a" * 64,
        new_file_sha256="b" * 64,
        repository_file_sha256=None,
        created_at=now,
    )


def _monitor(monitor_id: str) -> ApiMonitor:
    now = datetime.now(UTC)
    return ApiMonitor(
        monitor_id=monitor_id,
        name="Payments",
        specification_url="https://example.com/openapi.json",
        repository_url="https://github.com/example/payments",
        repository_ref="main",
        check_interval_minutes=60,
        enabled=True,
        baseline_filename="openapi.json",
        baseline_content=b"{}",
        baseline_sha256="a" * 64,
        baseline_observed_at=now,
        created_at=now,
        updated_at=now,
    )


def _zip(files: dict[str, bytes]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return output.getvalue()


def test_mock_oauth_creates_one_personal_workspace_and_reuses_it(tmp_path) -> None:
    repository = _platform(tmp_path)
    service = _auth(repository)
    authorization_url = service.begin("http://localhost:5173/repositories")
    state = parse_qs(urlsplit(authorization_url).query)["state"][0]

    session_token, csrf_token, return_to = asyncio.run(service.callback("mock-user", state))
    session, user, workspace = service.authenticate(session_token)

    assert return_to.endswith("/app/onboarding")
    assert workspace is not None
    service.verify_csrf(session, csrf_token)
    membership = repository.get_membership(user.user_id, workspace.workspace_id)
    assert membership is not None
    assert membership.role == WorkspaceRole.OWNER
    assert len(repository.list_memberships(user.user_id)) == 1

    repeat_url = service.begin("http://localhost:5173/repositories")
    repeat_state = parse_qs(urlsplit(repeat_url).query)["state"][0]
    repeat_token, _repeat_csrf, repeat_return_to = asyncio.run(
        service.callback("mock-user", repeat_state)
    )
    _repeat_session, repeat_user, repeat_workspace = service.authenticate(repeat_token)
    assert repeat_user.user_id == user.user_id
    assert repeat_workspace == workspace
    assert repeat_return_to.endswith("/repositories")
    assert len(repository.list_memberships(user.user_id)) == 1


def test_oauth_state_mismatch_and_invalid_session_are_rejected(tmp_path) -> None:
    service = _auth(_platform(tmp_path))
    with pytest.raises(DriftGuardError, match="state") as state_error:
        asyncio.run(service.callback("mock-user", "wrong-state"))
    assert state_error.value.code == "oauth_state_invalid"

    with pytest.raises(DriftGuardError) as session_error:
        service.authenticate("invalid-session")
    assert session_error.value.code == "invalid_session"


def test_workspace_switch_rejects_non_member(tmp_path) -> None:
    repository = _platform(tmp_path)
    service = _auth(repository)
    user_a, workspace_a = _team(repository, "Alpha")
    _user_b, workspace_b = _team(repository, "Beta")
    now = datetime.now(UTC)
    from apps.api.app.domain.workspace import AuthSession

    session = AuthSession("hash", user_a.user_id, workspace_a.workspace_id, "csrf", now, now)
    with pytest.raises(DriftGuardError) as error:
        service.switch_workspace(session, user_a, workspace_b.workspace_id)
    assert error.value.code == "workspace_access_denied"


def test_analysis_and_monitor_storage_are_isolated_by_workspace(tmp_path) -> None:
    database = tmp_path / "tenant.sqlite3"
    analyses = SQLiteAnalysisRepository(database)
    analyses.initialize()
    monitors = SQLiteMonitorRepository(database)
    monitors.initialize()
    _platform_repository = SQLiteWorkspaceRepository(database)
    _platform_repository.initialize()
    principal_a = WorkspacePrincipal("workspace-a", "user-a", "alpha", role=WorkspaceRole.OWNER)
    principal_b = WorkspacePrincipal("workspace-b", "user-b", "beta", role=WorkspaceRole.OWNER)

    with workspace_scope(principal_a):
        analysis_a = analyses.create_or_get(_submission("a" * 64)).analysis
        monitors.create(_monitor("monitor-a"))
    with workspace_scope(principal_b):
        analysis_b = analyses.create_or_get(_submission("b" * 64)).analysis
        monitors.create(_monitor("monitor-b"))
        assert analyses.get_analysis(analysis_a.analysis_id) is None
        assert monitors.get("monitor-a") is None
        assert [item.analysis_id for item in analyses.list_analyses(limit=10, offset=0)] == [
            analysis_b.analysis_id
        ]
    with workspace_scope(principal_a):
        assert analyses.get_analysis(analysis_a.analysis_id) is not None
        assert analyses.get_analysis(analysis_b.analysis_id) is None
        assert [item.monitor_id for item in monitors.list()] == ["monitor-a"]


def test_legacy_local_analysis_remains_accessible(tmp_path) -> None:
    database = tmp_path / "legacy.sqlite3"
    repository = SQLiteAnalysisRepository(database)
    repository.initialize()
    created = repository.create_or_get(_submission("c" * 64)).analysis
    SQLiteWorkspaceRepository(database).initialize()

    with workspace_scope(WorkspacePrincipal(LOCAL_WORKSPACE_ID, local=True)):
        assert repository.get_analysis(created.analysis_id) is not None
    with workspace_scope(
        WorkspacePrincipal("another-workspace", "user", "other", role=WorkspaceRole.OWNER)
    ):
        assert repository.get_analysis(created.analysis_id) is None


def test_repository_filtering_ignores_dependencies_and_never_executes_source() -> None:
    archive = _zip(
        {
            "repo/src/client.py": b"raise RuntimeError('must never execute')\n",
            "repo/src/client.ts": b"fetch('/payments')\n",
            "repo/node_modules/vendor.js": b"fetch('/payments')\n",
            "repo/dist/bundle.js": b"fetch('/payments')\n",
            "repo/image.png": b"\x89PNG\x00",
        }
    )
    result = RepositoryArchiveScanner().scan("repository.zip", archive)
    assert [item.path for item in result.files] == ["repo/src/client.py", "repo/src/client.ts"]
    assert result.skipped_reasons["ignored_path"] == 2
    assert result.skipped_reasons["ignored_artifact"] == 1


@pytest.mark.parametrize(
    ("scanner", "files", "code"),
    [
        (
            RepositoryArchiveScanner(max_file_bytes=3),
            {"repo/a.py": b"1234"},
            "repository_too_large",
        ),
        (
            RepositoryArchiveScanner(max_source_files=1),
            {"repo/a.py": b"1", "repo/b.py": b"2"},
            "repository_source_limit_exceeded",
        ),
        (
            RepositoryArchiveScanner(max_source_bytes=3),
            {"repo/a.py": b"12", "repo/b.py": b"34"},
            "repository_source_limit_exceeded",
        ),
    ],
)
def test_repository_source_limits_return_specific_errors(scanner, files, code) -> None:
    with pytest.raises(DriftGuardError) as error:
        scanner.scan("repository.zip", _zip(files))
    assert error.value.code == code


def test_installation_sync_uses_provider_metadata_and_workspace_authorization(tmp_path) -> None:
    repository = _platform(tmp_path)
    user, workspace = _team(repository, "Gamma")
    provider = MockGitHubInstallationProvider()
    provider.repositories[1] = [
        GitHubRepositoryInfo(
            99,
            "gamma",
            "private-api",
            "gamma/private-api",
            "trunk",
            True,
            "https://github.com/gamma/private-api",
        )
    ]
    service = GitHubOnboardingService(repository, provider, _auth(repository))
    principal = WorkspacePrincipal(
        workspace.workspace_id, user.user_id, user.github_login, role=WorkspaceRole.OWNER
    )
    installation = asyncio.run(service.connect(principal, 1))
    synchronized = asyncio.run(service.sync(principal, installation.installation_id))

    assert synchronized[0].github_repository_id == 99
    assert synchronized[0].private is True
    assert synchronized[0].default_branch == "trunk"
    assert service.require_repository(principal, synchronized[0].connection_id) == synchronized[0]
    with pytest.raises(DriftGuardError):
        service.require_repository(
            WorkspacePrincipal("another", "intruder", "intruder", role=WorkspaceRole.OWNER),
            synchronized[0].connection_id,
        )


def test_child_workflow_services_hide_cross_workspace_analysis_ids(tmp_path) -> None:
    database = tmp_path / "child-isolation.sqlite3"
    analyses = SQLiteAnalysisRepository(database)
    analyses.initialize()
    source = GitHubRepositorySource()
    patch_service = PatchProposalService(analyses, MockPatchGenerationProvider(), source)
    validation_service = PatchValidationService(analyses, MockTestPlanProvider(), source)
    pull_request_service = PullRequestWorkflowService(analyses, MockGitHubWriteProvider(), source)
    principal_a = WorkspacePrincipal("workspace-a", "user-a", "alpha", role=WorkspaceRole.OWNER)
    principal_b = WorkspacePrincipal("workspace-b", "user-b", "beta", role=WorkspaceRole.OWNER)

    with workspace_scope(principal_a):
        analysis_id = analyses.create_or_get(_submission("d" * 64)).analysis.analysis_id

    with workspace_scope(principal_b):
        for operation in (
            lambda: patch_service.list(analysis_id),
            lambda: validation_service.list(analysis_id, "patch-a"),
            lambda: pull_request_service.list(analysis_id),
        ):
            with pytest.raises(DriftGuardError) as error:
                operation()
            assert error.value.code == "analysis_not_found"
