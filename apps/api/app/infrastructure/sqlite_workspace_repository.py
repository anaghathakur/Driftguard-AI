"""SQLite identity/workspace persistence with additive legacy-safe migrations."""
# ruff: noqa: E501

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from apps.api.app.core.workspace_context import (
    LOCAL_WORKSPACE_ID,
    LOCAL_WORKSPACE_NAME,
    LOCAL_WORKSPACE_SLUG,
)
from apps.api.app.domain.workspace import (
    AuditEvent,
    AuthSession,
    GitHubInstallation,
    OAuthState,
    RepositoryConnection,
    User,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)
from apps.api.app.ports.workspace_repository import WorkspaceRepository

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    github_user_id INTEGER NOT NULL UNIQUE,
    github_login TEXT NOT NULL,
    github_display_name TEXT,
    avatar_url TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workspaces (
    workspace_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workspace_memberships (
    membership_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('owner', 'member')),
    created_at TEXT NOT NULL,
    UNIQUE(workspace_id, user_id),
    FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS auth_sessions (
    session_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    active_workspace_id TEXT,
    csrf_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY(active_workspace_id) REFERENCES workspaces(workspace_id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS oauth_states (
    state_hash TEXT PRIMARY KEY,
    return_to TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS github_installations (
    installation_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    github_installation_id INTEGER NOT NULL UNIQUE,
    github_account_id INTEGER NOT NULL,
    github_account_login TEXT NOT NULL,
    account_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    revoked_at TEXT,
    FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS repository_connections (
    connection_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    installation_id TEXT NOT NULL,
    github_repository_id INTEGER NOT NULL,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    full_name TEXT NOT NULL,
    default_branch TEXT NOT NULL,
    private INTEGER NOT NULL CHECK(private IN (0, 1)),
    html_url TEXT NOT NULL,
    enabled INTEGER NOT NULL CHECK(enabled IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_synced_at TEXT NOT NULL,
    removed_at TEXT,
    UNIQUE(workspace_id, github_repository_id),
    FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    FOREIGN KEY(installation_id) REFERENCES github_installations(installation_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    workspace_id TEXT,
    user_id TEXT,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT,
    metadata_safe_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memberships_user ON workspace_memberships(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_installations_workspace ON github_installations(workspace_id);
CREATE INDEX IF NOT EXISTS idx_repositories_workspace ON repository_connections(workspace_id, full_name);
CREATE INDEX IF NOT EXISTS idx_audit_workspace ON audit_events(workspace_id, created_at DESC);
"""


class SQLiteWorkspaceRepository(WorkspaceRepository):
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        now = _iso(datetime.now(UTC))
        with self._transaction() as connection:
            connection.executescript(SCHEMA)
            connection.execute(
                """INSERT OR IGNORE INTO workspaces
                   (workspace_id, name, slug, created_at, updated_at) VALUES (?, ?, ?, ?, ?)""",
                (LOCAL_WORKSPACE_ID, LOCAL_WORKSPACE_NAME, LOCAL_WORKSPACE_SLUG, now, now),
            )
            _add_workspace_column(connection, "analyses")
            _add_workspace_column(connection, "api_monitors")

    def upsert_user(self, user: User) -> User:
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(github_user_id) DO UPDATE SET
                   github_login=excluded.github_login,
                   github_display_name=excluded.github_display_name,
                   avatar_url=excluded.avatar_url,
                   updated_at=excluded.updated_at""",
                _user_values(user),
            )
            row = connection.execute(
                "SELECT * FROM users WHERE github_user_id = ?", (user.github_user_id,)
            ).fetchone()
        return _user(row)

    def get_user(self, user_id: str) -> User | None:
        return self._one("SELECT * FROM users WHERE user_id = ?", (user_id,), _user)

    def get_user_by_github_id(self, github_user_id: int) -> User | None:
        return self._one("SELECT * FROM users WHERE github_user_id = ?", (github_user_id,), _user)

    def create_workspace(self, workspace: Workspace, membership: WorkspaceMembership) -> None:
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO workspaces VALUES (?, ?, ?, ?, ?)",
                (
                    workspace.workspace_id,
                    workspace.name,
                    workspace.slug,
                    _iso(workspace.created_at),
                    _iso(workspace.updated_at),
                ),
            )
            connection.execute(
                "INSERT INTO workspace_memberships VALUES (?, ?, ?, ?, ?)",
                (
                    membership.membership_id,
                    membership.workspace_id,
                    membership.user_id,
                    membership.role.value,
                    _iso(membership.created_at),
                ),
            )

    def get_workspace(self, workspace_id: str) -> Workspace | None:
        return self._one(
            "SELECT * FROM workspaces WHERE workspace_id = ?", (workspace_id,), _workspace
        )

    def list_memberships(self, user_id: str) -> list[tuple[WorkspaceMembership, Workspace]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT m.*, w.name, w.slug, w.created_at AS workspace_created_at,
                   w.updated_at AS workspace_updated_at FROM workspace_memberships m
                   JOIN workspaces w ON w.workspace_id = m.workspace_id
                   WHERE m.user_id = ? ORDER BY m.created_at""",
                (user_id,),
            ).fetchall()
        return [(_membership(row), _workspace_join(row)) for row in rows]

    def get_membership(self, user_id: str, workspace_id: str) -> WorkspaceMembership | None:
        return self._one(
            "SELECT * FROM workspace_memberships WHERE user_id = ? AND workspace_id = ?",
            (user_id, workspace_id),
            _membership,
        )

    def save_session(self, session: AuthSession) -> None:
        with self._transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO auth_sessions VALUES (?, ?, ?, ?, ?, ?)",
                (
                    session.session_hash,
                    session.user_id,
                    session.active_workspace_id,
                    session.csrf_hash,
                    _iso(session.created_at),
                    _iso(session.expires_at),
                ),
            )

    def get_session(self, session_hash: str) -> AuthSession | None:
        return self._one(
            "SELECT * FROM auth_sessions WHERE session_hash = ?", (session_hash,), _session
        )

    def update_session_workspace(self, session_hash: str, workspace_id: str) -> None:
        with self._transaction() as connection:
            connection.execute(
                "UPDATE auth_sessions SET active_workspace_id = ? WHERE session_hash = ?",
                (workspace_id, session_hash),
            )

    def delete_session(self, session_hash: str) -> None:
        with self._transaction() as connection:
            connection.execute("DELETE FROM auth_sessions WHERE session_hash = ?", (session_hash,))

    def save_oauth_state(self, state: OAuthState) -> None:
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO oauth_states VALUES (?, ?, ?, ?)",
                (state.state_hash, state.return_to, _iso(state.created_at), _iso(state.expires_at)),
            )

    def consume_oauth_state(self, state_hash: str) -> OAuthState | None:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM oauth_states WHERE state_hash = ?", (state_hash,)
            ).fetchone()
            connection.execute("DELETE FROM oauth_states WHERE state_hash = ?", (state_hash,))
        return _oauth_state(row) if row else None

    def upsert_installation(self, installation: GitHubInstallation) -> GitHubInstallation:
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO github_installations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(github_installation_id) DO UPDATE SET
                   github_account_id=excluded.github_account_id,
                   github_account_login=excluded.github_account_login,
                   account_type=excluded.account_type,
                   updated_at=excluded.updated_at,
                   revoked_at=excluded.revoked_at""",
                _installation_values(installation),
            )
            row = connection.execute(
                "SELECT * FROM github_installations WHERE github_installation_id = ?",
                (installation.github_installation_id,),
            ).fetchone()
        return _installation(row)

    def get_installation(self, installation_id: str) -> GitHubInstallation | None:
        return self._one(
            "SELECT * FROM github_installations WHERE installation_id = ?",
            (installation_id,),
            _installation,
        )

    def get_installation_by_github_id(
        self, github_installation_id: int
    ) -> GitHubInstallation | None:
        return self._one(
            "SELECT * FROM github_installations WHERE github_installation_id = ?",
            (github_installation_id,),
            _installation,
        )

    def list_installations(self, workspace_id: str) -> list[GitHubInstallation]:
        return self._many(
            "SELECT * FROM github_installations WHERE workspace_id = ? ORDER BY created_at",
            (workspace_id,),
            _installation,
        )

    def upsert_repository(self, repository: RepositoryConnection) -> RepositoryConnection:
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO repository_connections VALUES
                   (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(workspace_id, github_repository_id) DO UPDATE SET
                   installation_id=excluded.installation_id, owner=excluded.owner,
                   name=excluded.name, full_name=excluded.full_name,
                   default_branch=excluded.default_branch, private=excluded.private,
                   html_url=excluded.html_url, enabled=excluded.enabled,
                   updated_at=excluded.updated_at,
                   last_synced_at=excluded.last_synced_at, removed_at=excluded.removed_at""",
                _repository_values(repository),
            )
            row = connection.execute(
                """SELECT * FROM repository_connections
                   WHERE workspace_id = ? AND github_repository_id = ?""",
                (repository.workspace_id, repository.github_repository_id),
            ).fetchone()
        return _repository(row)

    def get_repository(self, connection_id: str) -> RepositoryConnection | None:
        return self._one(
            "SELECT * FROM repository_connections WHERE connection_id = ?",
            (connection_id,),
            _repository,
        )

    def get_repository_by_github_id(
        self, workspace_id: str, github_repository_id: int
    ) -> RepositoryConnection | None:
        return self._one(
            """SELECT * FROM repository_connections
               WHERE workspace_id = ? AND github_repository_id = ?""",
            (workspace_id, github_repository_id),
            _repository,
        )

    def list_repositories(self, workspace_id: str) -> list[RepositoryConnection]:
        return self._many(
            """SELECT * FROM repository_connections WHERE workspace_id = ?
               AND removed_at IS NULL ORDER BY full_name""",
            (workspace_id,),
            _repository,
        )

    def save_audit_event(self, event: AuditEvent) -> None:
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO audit_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event.event_id,
                    event.workspace_id,
                    event.user_id,
                    event.action,
                    event.resource_type,
                    event.resource_id,
                    json.dumps(event.metadata_safe, sort_keys=True, separators=(",", ":")),
                    _iso(event.created_at),
                ),
            )

    def list_audit_events(self, workspace_id: str, limit: int = 100) -> list[AuditEvent]:
        return self._many(
            """SELECT * FROM audit_events WHERE workspace_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (workspace_id, limit),
            _audit,
        )

    def _one(self, sql: str, values: tuple[object, ...], mapper):
        with self._connect() as connection:
            row = connection.execute(sql, values).fetchone()
        return mapper(row) if row else None

    def _many(self, sql: str, values: tuple[object, ...], mapper):
        with self._connect() as connection:
            rows = connection.execute(sql, values).fetchall()
        return [mapper(row) for row in rows]

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()


def _add_workspace_column(connection: sqlite3.Connection, table: str) -> None:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if not exists:
        return
    columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    if "workspace_id" not in columns:
        connection.execute(
            f"ALTER TABLE {table} ADD COLUMN workspace_id TEXT NOT NULL "
            f"DEFAULT '{LOCAL_WORKSPACE_ID}'"
        )
    connection.execute(
        f"UPDATE {table} SET workspace_id = ? WHERE workspace_id IS NULL OR workspace_id = ''",
        (LOCAL_WORKSPACE_ID,),
    )
    connection.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_workspace ON {table}(workspace_id)")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def _user_values(value: User) -> tuple[object, ...]:
    return (
        value.user_id,
        value.github_user_id,
        value.github_login,
        value.github_display_name,
        value.avatar_url,
        _iso(value.created_at),
        _iso(value.updated_at),
    )


def _user(row: sqlite3.Row) -> User:
    return User(
        row["user_id"],
        row["github_user_id"],
        row["github_login"],
        row["github_display_name"],
        row["avatar_url"],
        _dt(row["created_at"]),
        _dt(row["updated_at"]),
    )


def _workspace(row: sqlite3.Row) -> Workspace:
    return Workspace(
        row["workspace_id"],
        row["name"],
        row["slug"],
        _dt(row["created_at"]),
        _dt(row["updated_at"]),
    )


def _workspace_join(row: sqlite3.Row) -> Workspace:
    return Workspace(
        row["workspace_id"],
        row["name"],
        row["slug"],
        _dt(row["workspace_created_at"]),
        _dt(row["workspace_updated_at"]),
    )


def _membership(row: sqlite3.Row) -> WorkspaceMembership:
    return WorkspaceMembership(
        row["membership_id"],
        row["workspace_id"],
        row["user_id"],
        WorkspaceRole(row["role"]),
        _dt(row["created_at"]),
    )


def _session(row: sqlite3.Row) -> AuthSession:
    return AuthSession(
        row["session_hash"],
        row["user_id"],
        row["active_workspace_id"],
        row["csrf_hash"],
        _dt(row["created_at"]),
        _dt(row["expires_at"]),
    )


def _oauth_state(row: sqlite3.Row) -> OAuthState:
    return OAuthState(
        row["state_hash"], row["return_to"], _dt(row["created_at"]), _dt(row["expires_at"])
    )


def _installation_values(value: GitHubInstallation) -> tuple[object, ...]:
    return (
        value.installation_id,
        value.workspace_id,
        value.github_installation_id,
        value.github_account_id,
        value.github_account_login,
        value.account_type,
        _iso(value.created_at),
        _iso(value.updated_at),
        _iso(value.revoked_at),
    )


def _installation(row: sqlite3.Row) -> GitHubInstallation:
    return GitHubInstallation(
        row["installation_id"],
        row["workspace_id"],
        row["github_installation_id"],
        row["github_account_id"],
        row["github_account_login"],
        row["account_type"],
        _dt(row["created_at"]),
        _dt(row["updated_at"]),
        _dt(row["revoked_at"]),
    )


def _repository_values(value: RepositoryConnection) -> tuple[object, ...]:
    return (
        value.connection_id,
        value.workspace_id,
        value.installation_id,
        value.github_repository_id,
        value.owner,
        value.name,
        value.full_name,
        value.default_branch,
        int(value.private),
        value.html_url,
        int(value.enabled),
        _iso(value.created_at),
        _iso(value.updated_at),
        _iso(value.last_synced_at),
        _iso(value.removed_at),
    )


def _repository(row: sqlite3.Row) -> RepositoryConnection:
    return RepositoryConnection(
        row["connection_id"],
        row["workspace_id"],
        row["installation_id"],
        row["github_repository_id"],
        row["owner"],
        row["name"],
        row["full_name"],
        row["default_branch"],
        bool(row["private"]),
        row["html_url"],
        bool(row["enabled"]),
        _dt(row["created_at"]),
        _dt(row["updated_at"]),
        _dt(row["last_synced_at"]),
        _dt(row["removed_at"]),
    )


def _audit(row: sqlite3.Row) -> AuditEvent:
    return AuditEvent(
        row["event_id"],
        row["workspace_id"],
        row["user_id"],
        row["action"],
        row["resource_type"],
        row["resource_id"],
        json.loads(row["metadata_safe_json"]),
        _dt(row["created_at"]),
    )
