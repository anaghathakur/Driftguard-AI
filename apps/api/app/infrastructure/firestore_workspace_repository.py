"""Firestore identity/workspace persistence adapter."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from google.cloud import firestore

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


class FirestoreWorkspaceRepository(WorkspaceRepository):
    def __init__(
        self, *, project_id: str | None = None, database_id: str = "(default)", client=None
    ):
        self.client = client or firestore.Client(project=project_id, database=database_id)

    def initialize(self) -> None:
        now = datetime.now(UTC)
        ref = self.client.collection("workspaces").document(LOCAL_WORKSPACE_ID)
        if not ref.get().exists:
            ref.set(
                _workspace_data(
                    Workspace(
                        LOCAL_WORKSPACE_ID, LOCAL_WORKSPACE_NAME, LOCAL_WORKSPACE_SLUG, now, now
                    )
                )
            )

    def upsert_user(self, user: User) -> User:
        query = (
            self.client.collection("users")
            .where("github_user_id", "==", user.github_user_id)
            .limit(1)
        )
        found = next(iter(query.stream()), None)
        if found:
            existing = _user(found.to_dict() or {})
            user = User(
                existing.user_id,
                user.github_user_id,
                user.github_login,
                user.github_display_name,
                user.avatar_url,
                existing.created_at,
                user.updated_at,
                user.external_auth_provider,
                user.external_subject,
                user.email,
            )
        self.client.collection("users").document(user.user_id).set(_user_data(user))
        return user

    def get_user(self, user_id: str) -> User | None:
        return _get(self.client.collection("users").document(user_id), _user)

    def get_user_by_github_id(self, github_user_id: int) -> User | None:
        found = next(
            iter(
                self.client.collection("users")
                .where("github_user_id", "==", github_user_id)
                .limit(1)
                .stream()
            ),
            None,
        )
        return _user(found.to_dict() or {}) if found else None

    def get_user_by_external_identity(self, provider: str, subject: str) -> User | None:
        found = next(
            iter(
                self.client.collection("users")
                .where("auth_provider", "==", provider)
                .where("external_subject", "==", subject)
                .limit(1)
                .stream()
            ),
            None,
        )
        if found:
            return _user(found.to_dict() or {})
        if provider == "github" and subject.isdigit():
            return self.get_user_by_github_id(int(subject))
        return None

    def create_workspace(self, workspace: Workspace, membership: WorkspaceMembership) -> None:
        batch = self.client.batch()
        batch.create(
            self.client.collection("workspaces").document(workspace.workspace_id),
            _workspace_data(workspace),
        )
        batch.create(
            self.client.collection("workspace_memberships").document(membership.membership_id),
            _membership_data(membership),
        )
        batch.commit()

    def ensure_workspace(
        self, workspace: Workspace, membership: WorkspaceMembership
    ) -> bool:
        workspace_ref = self.client.collection("workspaces").document(workspace.workspace_id)
        membership_ref = self.client.collection("workspace_memberships").document(
            membership.membership_id
        )
        created = not workspace_ref.get().exists
        batch = self.client.batch()
        batch.set(workspace_ref, _workspace_data(workspace), merge=True)
        batch.set(membership_ref, _membership_data(membership), merge=True)
        batch.commit()
        return created

    def get_workspace(self, workspace_id: str) -> Workspace | None:
        return _get(self.client.collection("workspaces").document(workspace_id), _workspace)

    def list_memberships(self, user_id: str) -> list[tuple[WorkspaceMembership, Workspace]]:
        result = []
        for item in (
            self.client.collection("workspace_memberships").where("user_id", "==", user_id).stream()
        ):
            membership = _membership(item.to_dict() or {})
            workspace = self.get_workspace(membership.workspace_id)
            if workspace:
                result.append((membership, workspace))
        return sorted(result, key=lambda value: value[0].created_at)

    def get_membership(self, user_id: str, workspace_id: str) -> WorkspaceMembership | None:
        query = (
            self.client.collection("workspace_memberships")
            .where("user_id", "==", user_id)
            .where("workspace_id", "==", workspace_id)
            .limit(1)
        )
        found = next(iter(query.stream()), None)
        return _membership(found.to_dict() or {}) if found else None

    def list_workspace_members(self, workspace_id: str) -> list[tuple[WorkspaceMembership, User]]:
        result = []
        for item in (
            self.client.collection("workspace_memberships")
            .where("workspace_id", "==", workspace_id)
            .stream()
        ):
            membership = _membership(item.to_dict() or {})
            user = self.get_user(membership.user_id)
            if user:
                result.append((membership, user))
        return sorted(result, key=lambda value: value[0].created_at)

    def save_membership(self, membership: WorkspaceMembership) -> WorkspaceMembership:
        query = (
            self.client.collection("workspace_memberships")
            .where("workspace_id", "==", membership.workspace_id)
            .where("user_id", "==", membership.user_id)
            .limit(1)
        )
        found = next(iter(query.stream()), None)
        if found:
            membership = replace(membership, membership_id=found.id)
            found.reference.set(_membership_data(membership))
        else:
            self.client.collection("workspace_memberships").document(membership.membership_id).set(
                _membership_data(membership)
            )
        return membership

    def delete_membership(self, user_id: str, workspace_id: str) -> bool:
        query = (
            self.client.collection("workspace_memberships")
            .where("workspace_id", "==", workspace_id)
            .where("user_id", "==", user_id)
            .limit(1)
        )
        found = next(iter(query.stream()), None)
        if found is None:
            return False
        found.reference.delete()
        return True

    def count_members_by_role(self, workspace_id: str, role: WorkspaceRole) -> int:
        return sum(
            membership.role == role
            for membership, _user_value in self.list_workspace_members(workspace_id)
        )

    def save_session(self, session: AuthSession) -> None:
        self.client.collection("auth_sessions").document(session.session_hash).set(
            _session_data(session)
        )

    def get_session(self, session_hash: str) -> AuthSession | None:
        return _get(self.client.collection("auth_sessions").document(session_hash), _session)

    def update_session_workspace(self, session_hash: str, workspace_id: str) -> None:
        self.client.collection("auth_sessions").document(session_hash).update(
            {"active_workspace_id": workspace_id}
        )

    def delete_session(self, session_hash: str) -> None:
        self.client.collection("auth_sessions").document(session_hash).delete()

    def save_oauth_state(self, state: OAuthState) -> None:
        self.client.collection("oauth_states").document(state.state_hash).set(_state_data(state))

    def consume_oauth_state(self, state_hash: str) -> OAuthState | None:
        ref = self.client.collection("oauth_states").document(state_hash)
        snapshot = ref.get()
        ref.delete()
        return _state(snapshot.to_dict() or {}) if snapshot.exists else None

    def upsert_installation(self, installation: GitHubInstallation) -> GitHubInstallation:
        query = (
            self.client.collection("github_installations")
            .where("github_installation_id", "==", installation.github_installation_id)
            .limit(1)
        )
        found = next(iter(query.stream()), None)
        if found:
            existing = _installation(found.to_dict() or {})
            installation = replace(
                installation,
                installation_id=existing.installation_id,
                workspace_id=existing.workspace_id,
                created_at=existing.created_at,
            )
        ref = (
            found.reference
            if found
            else self.client.collection("github_installations").document(
                installation.installation_id
            )
        )
        ref.set(_installation_data(installation))
        return installation

    def get_installation(self, installation_id: str) -> GitHubInstallation | None:
        return _get(
            self.client.collection("github_installations").document(installation_id), _installation
        )

    def get_installation_by_github_id(
        self, github_installation_id: int
    ) -> GitHubInstallation | None:
        found = next(
            iter(
                self.client.collection("github_installations")
                .where("github_installation_id", "==", github_installation_id)
                .limit(1)
                .stream()
            ),
            None,
        )
        return _installation(found.to_dict() or {}) if found else None

    def list_installations(self, workspace_id: str) -> list[GitHubInstallation]:
        return [
            _installation(item.to_dict() or {})
            for item in self.client.collection("github_installations")
            .where("workspace_id", "==", workspace_id)
            .stream()
        ]

    def upsert_repository(self, repository: RepositoryConnection) -> RepositoryConnection:
        query = (
            self.client.collection("repository_connections")
            .where("workspace_id", "==", repository.workspace_id)
            .where("github_repository_id", "==", repository.github_repository_id)
            .limit(1)
        )
        found = next(iter(query.stream()), None)
        ref = (
            found.reference
            if found
            else self.client.collection("repository_connections").document(repository.connection_id)
        )
        if found:
            repository = replace(repository, connection_id=found.id)
        ref.set(_repository_data(repository))
        return repository

    def get_repository(self, connection_id: str) -> RepositoryConnection | None:
        return _get(
            self.client.collection("repository_connections").document(connection_id), _repository
        )

    def get_repository_by_github_id(
        self, workspace_id: str, github_repository_id: int
    ) -> RepositoryConnection | None:
        found = next(
            iter(
                self.client.collection("repository_connections")
                .where("workspace_id", "==", workspace_id)
                .where("github_repository_id", "==", github_repository_id)
                .limit(1)
                .stream()
            ),
            None,
        )
        return _repository(found.to_dict() or {}) if found else None

    def list_repositories(self, workspace_id: str) -> list[RepositoryConnection]:
        values = [
            _repository(item.to_dict() or {})
            for item in self.client.collection("repository_connections")
            .where("workspace_id", "==", workspace_id)
            .stream()
        ]
        return sorted(
            (item for item in values if item.removed_at is None), key=lambda item: item.full_name
        )

    def save_audit_event(self, event: AuditEvent) -> None:
        self.client.collection("audit_events").document(event.event_id).set(_audit_data(event))

    def list_audit_events(self, workspace_id: str, limit: int = 100) -> list[AuditEvent]:
        query = (
            self.client.collection("audit_events")
            .where("workspace_id", "==", workspace_id)
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        return [_audit(item.to_dict() or {}) for item in query.stream()]


def _get(ref, mapper):
    snapshot = ref.get()
    return mapper(snapshot.to_dict() or {}) if snapshot.exists else None


def _user_data(v):
    return {
        "user_id": v.user_id,
        "github_user_id": v.github_user_id,
        "github_login": v.github_login,
        "github_display_name": v.github_display_name,
        "auth_provider": v.external_auth_provider,
        "external_subject": v.external_subject or str(v.github_user_id),
        "email": v.email,
        "avatar_url": v.avatar_url,
        "created_at": v.created_at,
        "updated_at": v.updated_at,
    }


def _workspace_data(v):
    return {
        "workspace_id": v.workspace_id,
        "name": v.name,
        "created_by_user_id": v.created_by_user_id,
        "slug": v.slug,
        "created_at": v.created_at,
        "updated_at": v.updated_at,
    }


def _membership_data(v):
    return {
        "membership_id": v.membership_id,
        "workspace_id": v.workspace_id,
        "user_id": v.user_id,
        "role": v.role.value,
        "created_at": v.created_at,
    }


def _session_data(v):
    return {
        "session_hash": v.session_hash,
        "user_id": v.user_id,
        "active_workspace_id": v.active_workspace_id,
        "csrf_hash": v.csrf_hash,
        "created_at": v.created_at,
        "expires_at": v.expires_at,
    }


def _state_data(v):
    return {
        "state_hash": v.state_hash,
        "return_to": v.return_to,
        "created_at": v.created_at,
        "expires_at": v.expires_at,
    }


def _installation_data(v):
    return {
        "installation_id": v.installation_id,
        "workspace_id": v.workspace_id,
        "github_installation_id": v.github_installation_id,
        "github_account_id": v.github_account_id,
        "github_account_login": v.github_account_login,
        "account_type": v.account_type,
        "created_at": v.created_at,
        "updated_at": v.updated_at,
        "revoked_at": v.revoked_at,
    }


def _repository_data(v):
    return {name: getattr(v, name) for name in v.__dataclass_fields__}


def _audit_data(v):
    return {name: getattr(v, name) for name in v.__dataclass_fields__}


def _user(d):
    return User(
        d["user_id"],
        int(d["github_user_id"]),
        d["github_login"],
        d.get("github_display_name"),
        d.get("auth_provider", "github"),
        d.get("external_subject", str(d["github_user_id"])),
        d.get("email"),
        d.get("avatar_url"),
        d["created_at"],
        d["updated_at"],
    )


def _workspace(d):
    return Workspace(
        d["workspace_id"],
        d["name"],
        d["slug"],
        d["created_at"],
        d["updated_at"],
        d.get("created_by_user_id"),
    )


def _membership(d):
    return WorkspaceMembership(
        d["membership_id"],
        d["workspace_id"],
        d["user_id"],
        WorkspaceRole.DEVELOPER if d["role"] == "member" else WorkspaceRole(d["role"]),
        d["created_at"],
    )


def _session(d):
    return AuthSession(
        d["session_hash"],
        d["user_id"],
        d.get("active_workspace_id"),
        d["csrf_hash"],
        d["created_at"],
        d["expires_at"],
    )


def _state(d):
    return OAuthState(d["state_hash"], d["return_to"], d["created_at"], d["expires_at"])


def _installation(d):
    return GitHubInstallation(
        d["installation_id"],
        d["workspace_id"],
        int(d["github_installation_id"]),
        int(d["github_account_id"]),
        d["github_account_login"],
        d["account_type"],
        d["created_at"],
        d["updated_at"],
        d.get("revoked_at"),
    )


def _repository(d):
    return RepositoryConnection(**d)


def _audit(d):
    return AuditEvent(**d)
