from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from apps.api.app.api.routes.auth import _development_auth_enabled
from apps.api.app.auth.authorization import Permission, authorize, can
from apps.api.app.auth.middleware import _audit_action, _resource
from apps.api.app.auth.provider import MockGitHubOAuthProvider
from apps.api.app.auth.service import AuthService
from apps.api.app.core.config import settings, validate_security_settings
from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.core.workspace_context import (
    WorkspacePrincipal,
    current_workspace_id,
    workspace_scope,
)
from apps.api.app.domain.monitor import ApiMonitor
from apps.api.app.domain.workspace import (
    AuthSession,
    User,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)
from apps.api.app.infrastructure.sqlite_analysis_repository import SQLiteAnalysisRepository
from apps.api.app.infrastructure.sqlite_monitor_repository import SQLiteMonitorRepository
from apps.api.app.infrastructure.sqlite_workspace_repository import SQLiteWorkspaceRepository
from apps.api.app.monitoring.scheduler import MonitorScheduler

NOW = datetime(2026, 8, 31, tzinfo=UTC)


def _auth(repository: SQLiteWorkspaceRepository) -> AuthService:
    return AuthService(
        repository,
        MockGitHubOAuthProvider(),
        callback_url="http://testserver/api/v1/auth/github/callback",
        frontend_url="http://localhost:5173",
        session_ttl_hours=24,
        session_secret="phase20-test-secret",
    )


def _user(repository: SQLiteWorkspaceRepository, login: str, github_id: int) -> User:
    return repository.upsert_user(
        User(
            user_id=str(uuid4()),
            github_user_id=github_id,
            github_login=login,
            github_display_name=login.title(),
            avatar_url=None,
            created_at=NOW,
            updated_at=NOW,
            external_subject=str(github_id),
        )
    )


def _team(repository: SQLiteWorkspaceRepository):
    owner = _user(repository, "owner", 1)
    workspace = Workspace("workspace-a", "Alpha", "alpha", NOW, NOW, owner.user_id)
    owner_membership = WorkspaceMembership(
        "membership-owner", workspace.workspace_id, owner.user_id, WorkspaceRole.OWNER, NOW
    )
    repository.create_workspace(workspace, owner_membership)
    return owner, workspace


def _member(
    repository: SQLiteWorkspaceRepository,
    workspace: Workspace,
    role: WorkspaceRole,
    github_id: int,
) -> tuple[User, WorkspaceMembership]:
    user = _user(repository, f"user-{github_id}", github_id)
    membership = repository.save_membership(
        WorkspaceMembership(str(uuid4()), workspace.workspace_id, user.user_id, role, NOW)
    )
    return user, membership


def _principal(user: User, workspace: Workspace, role: WorkspaceRole) -> WorkspacePrincipal:
    return WorkspacePrincipal(
        workspace.workspace_id,
        user.user_id,
        user.github_login,
        role=role,
    )


def test_role_permission_matrix_is_explicit_and_fail_closed() -> None:
    assert can(WorkspaceRole.VIEWER, Permission.READ_ANALYSES)
    assert not can(WorkspaceRole.VIEWER, Permission.RUN_ANALYSES)
    assert can(WorkspaceRole.DEVELOPER, Permission.GENERATE_PATCH)
    assert can(WorkspaceRole.DEVELOPER, Permission.CREATE_PULL_REQUEST)
    assert not can(WorkspaceRole.DEVELOPER, Permission.MANAGE_MEMBERS)
    assert not can(WorkspaceRole.DEVELOPER, Permission.MANAGE_ORGANIZATION)
    assert not can(WorkspaceRole.VIEWER, Permission.VALIDATE_PATCH)
    assert not can(WorkspaceRole.VIEWER, Permission.CREATE_PULL_REQUEST)
    assert can(WorkspaceRole.ADMIN, Permission.MANAGE_MEMBERS)
    assert not can(WorkspaceRole.ADMIN, Permission.MANAGE_ORGANIZATION)
    assert can(WorkspaceRole.OWNER, Permission.MANAGE_ORGANIZATION)

    with pytest.raises(DriftGuardError) as missing_role:
        authorize(Permission.READ_ANALYSES, WorkspacePrincipal("workspace", "user"))
    assert missing_role.value.code == "auth_required"

    with pytest.raises(DriftGuardError) as viewer_write:
        authorize(
            Permission.GENERATE_PATCH,
            WorkspacePrincipal("workspace", "viewer", role=WorkspaceRole.VIEWER),
        )
    assert viewer_write.value.code == "permission_denied"


def test_audit_history_is_workspace_scoped_and_monitor_actions_are_mapped(tmp_path) -> None:
    repository = SQLiteWorkspaceRepository(tmp_path / "audit.sqlite3")
    repository.initialize()
    service = _auth(repository)
    service.audit("workspace-a", "user-a", "analysis.created", "analysis", "analysis-a")
    service.audit("workspace-b", "user-b", "analysis.created", "analysis", "analysis-b")

    events_a = service.list_audit_events(
        WorkspacePrincipal("workspace-a", "user-a", role=WorkspaceRole.VIEWER)
    )
    events_b = service.list_audit_events(
        WorkspacePrincipal("workspace-b", "user-b", role=WorkspaceRole.VIEWER)
    )

    assert [event.resource_id for event in events_a] == ["analysis-a"]
    assert [event.resource_id for event in events_b] == ["analysis-b"]
    assert _audit_action("POST", "/api/v1/monitors") == "monitor.created"
    assert _audit_action("POST", "/api/v1/monitors/monitor-a/check") == "monitor.checked"
    assert _resource("/api/v1/monitors/monitor-a/check") == ("monitor", "monitor-a")


def test_membership_changes_prevent_escalation_and_preserve_last_owner(tmp_path) -> None:
    repository = SQLiteWorkspaceRepository(tmp_path / "members.sqlite3")
    repository.initialize()
    service = _auth(repository)
    owner, workspace = _team(repository)
    admin, _ = _member(repository, workspace, WorkspaceRole.ADMIN, 2)
    developer, _ = _member(repository, workspace, WorkspaceRole.DEVELOPER, 3)
    owner_principal = _principal(owner, workspace, WorkspaceRole.OWNER)
    admin_principal = _principal(admin, workspace, WorkspaceRole.ADMIN)

    with pytest.raises(DriftGuardError) as last_owner:
        service.change_member_role(owner_principal, owner.user_id, WorkspaceRole.ADMIN)
    assert last_owner.value.code == "last_owner_required"

    with pytest.raises(DriftGuardError) as escalation:
        service.change_member_role(admin_principal, developer.user_id, WorkspaceRole.ADMIN)
    assert escalation.value.code == "role_escalation_denied"

    with pytest.raises(DriftGuardError) as protected_owner:
        service.remove_member(admin_principal, owner.user_id)
    assert protected_owner.value.code == "role_escalation_denied"

    second_owner, _ = _member(repository, workspace, WorkspaceRole.OWNER, 4)
    updated = service.change_member_role(owner_principal, owner.user_id, WorkspaceRole.ADMIN)
    assert updated.role == WorkspaceRole.ADMIN
    service.remove_member(_principal(second_owner, workspace, WorkspaceRole.OWNER), admin.user_id)
    assert repository.get_membership(admin.user_id, workspace.workspace_id) is None
    assert any(
        event.action == "membership.removed"
        for event in service.list_audit_events(
            _principal(second_owner, workspace, WorkspaceRole.OWNER)
        )
    )


def test_session_principal_uses_persisted_active_workspace_role(tmp_path) -> None:
    repository = SQLiteWorkspaceRepository(tmp_path / "principal.sqlite3")
    repository.initialize()
    service = _auth(repository)
    owner, workspace = _team(repository)
    raw_session = "browser-session"
    session_now = datetime.now(UTC)
    repository.save_session(
        AuthSession(
            service._hash(raw_session),
            owner.user_id,
            workspace.workspace_id,
            service._hash("csrf"),
            session_now,
            session_now + timedelta(days=1),
        )
    )

    principal = service.principal(raw_session)
    assert principal.workspace_id == workspace.workspace_id
    assert principal.role == WorkspaceRole.OWNER

    repository.delete_membership(owner.user_id, workspace.workspace_id)
    with pytest.raises(DriftGuardError) as denied:
        service.principal(raw_session)
    assert denied.value.code == "workspace_access_denied"


def test_mock_oauth_can_create_two_isolated_development_users(tmp_path) -> None:
    repository = SQLiteWorkspaceRepository(tmp_path / "development-identities.sqlite3")
    repository.initialize()
    service = _auth(repository)

    primary_state = service.issue_state()
    primary_token, _primary_csrf, _ = asyncio.run(
        service.callback("mock-user", primary_state)
    )
    secondary_state = service.issue_state()
    secondary_token, _secondary_csrf, _ = asyncio.run(
        service.callback("mock-user-secondary", secondary_state)
    )

    _primary_session, primary, primary_workspace = service.authenticate(primary_token)
    _secondary_session, secondary, secondary_workspace = service.authenticate(
        secondary_token
    )

    assert primary.user_id != secondary.user_id
    assert primary.external_subject == "1"
    assert secondary.external_subject == "2"
    assert primary_workspace is not None
    assert secondary_workspace is not None
    assert primary_workspace.workspace_id != secondary_workspace.workspace_id
    assert repository.get_membership(
        primary.user_id, primary_workspace.workspace_id
    ).role == WorkspaceRole.OWNER
    assert repository.get_membership(
        secondary.user_id, secondary_workspace.workspace_id
    ).role == WorkspaceRole.OWNER
    assert "code=mock-user-secondary" in service.begin(identity_hint="secondary")


def test_development_identities_are_exposed_only_in_development() -> None:
    development = replace(
        settings,
        deployment_environment="development",
        github_oauth_provider="mock",
    )
    test = replace(
        settings,
        deployment_environment="test",
        github_oauth_provider="mock",
    )
    production = replace(
        settings,
        deployment_environment="production",
        github_oauth_provider="mock",
    )

    assert _development_auth_enabled(development)
    assert not _development_auth_enabled(test)
    assert not _development_auth_enabled(production)


def test_legacy_member_role_is_additively_migrated_to_developer(tmp_path) -> None:
    database = tmp_path / "legacy-workspace.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE users (
                user_id TEXT PRIMARY KEY, github_user_id INTEGER NOT NULL UNIQUE,
                github_login TEXT NOT NULL, github_display_name TEXT, avatar_url TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE workspaces (
                workspace_id TEXT PRIMARY KEY, name TEXT NOT NULL, slug TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE workspace_memberships (
                membership_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
                user_id TEXT NOT NULL, role TEXT NOT NULL CHECK (role IN ('owner', 'member')),
                created_at TEXT NOT NULL, UNIQUE(workspace_id, user_id)
            );
            """
        )
        timestamp = NOW.isoformat()
        connection.execute(
            "INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("legacy-user", 9, "legacy", None, None, timestamp, timestamp),
        )
        connection.execute(
            "INSERT INTO workspaces VALUES (?, ?, ?, ?, ?)",
            ("legacy-workspace", "Legacy", "legacy", timestamp, timestamp),
        )
        connection.execute(
            "INSERT INTO workspace_memberships VALUES (?, ?, ?, ?, ?)",
            ("legacy-membership", "legacy-workspace", "legacy-user", "member", timestamp),
        )

    repository = SQLiteWorkspaceRepository(database)
    repository.initialize()
    membership = repository.get_membership("legacy-user", "legacy-workspace")
    user = repository.get_user("legacy-user")
    assert membership is not None and membership.role == WorkspaceRole.DEVELOPER
    assert user is not None and user.external_subject == "9"
    assert repository.get_workspace("legacy-workspace") is not None


def test_production_auth_configuration_rejects_local_and_mock_modes() -> None:
    unsafe = replace(
        settings,
        deployment_environment="production",
        auth_mode="local",
        github_oauth_provider="mock",
        secure_cookies=False,
        session_secret="short",
    )
    with pytest.raises(RuntimeError, match="Unsafe production authentication configuration"):
        validate_security_settings(unsafe)


def test_production_configuration_rejects_mock_product_providers() -> None:
    production = replace(
        settings,
        deployment_environment="production",
        auth_mode="github",
        github_oauth_provider="github",
        github_oauth_client_id="client-id",
        github_oauth_client_secret="client-secret",
        github_oauth_callback_url="https://api.driftguard.example/api/v1/auth/github/callback",
        frontend_url="https://driftguard.example",
        secure_cookies=True,
        session_secret="a-production-session-secret-with-32-characters",
        ai_provider="gemini",
        migration_provider="gemini",
        patch_provider="gemini",
        test_plan_provider="gemini",
        github_write_provider="github_app",
        github_check_provider="github_app",
    )
    validate_security_settings(production)

    for field in (
        "migration_provider",
        "patch_provider",
        "test_plan_provider",
        "github_write_provider",
        "github_check_provider",
    ):
        with pytest.raises(RuntimeError, match=r"prohibits.*mock"):
            validate_security_settings(replace(production, **{field: "mock"}))


def _monitor(monitor_id: str) -> ApiMonitor:
    return ApiMonitor(
        monitor_id=monitor_id,
        name=monitor_id,
        specification_url="https://example.com/openapi.json",
        repository_url="https://github.com/example/repo",
        repository_ref=None,
        check_interval_minutes=5,
        enabled=True,
        baseline_filename="openapi.json",
        baseline_content=b"{}",
        baseline_sha256="a" * 64,
        baseline_observed_at=NOW - timedelta(hours=1),
        created_at=NOW - timedelta(hours=1),
        updated_at=NOW - timedelta(hours=1),
    )


def test_scheduler_carries_persisted_workspace_context(tmp_path) -> None:
    database = tmp_path / "scheduler.sqlite3"
    SQLiteAnalysisRepository(database).initialize()
    repository = SQLiteMonitorRepository(database)
    repository.initialize()
    for workspace_id, monitor_id in (("workspace-a", "monitor-a"), ("workspace-b", "monitor-b")):
        with workspace_scope(WorkspacePrincipal(workspace_id, system=True)):
            repository.create(_monitor(monitor_id))

    calls: list[tuple[str, str]] = []

    class CheckService:
        async def check(self, monitor_id: str) -> None:
            calls.append((current_workspace_id(), monitor_id))

    scheduler = MonitorScheduler(repository, CheckService(), enabled=True, poll_seconds=60)
    asyncio.run(scheduler.run_once(now=NOW))
    assert set(calls) == {
        ("workspace-a", "monitor-a"),
        ("workspace-b", "monitor-b"),
    }
