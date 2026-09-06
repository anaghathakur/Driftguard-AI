import { useCallback, useEffect, useState } from "react";

import {
  getWorkspaceMembers,
  removeWorkspaceMember,
  updateWorkspaceMemberRole,
  type AuthStatus,
  type WorkspaceMember,
  type WorkspaceRole,
} from "../lib/api";

type TeamPageProps = {
  auth: AuthStatus;
  onLogout: () => Promise<void>;
};

const roles: WorkspaceRole[] = ["owner", "admin", "developer", "viewer"];

export function TeamPage({ auth, onLogout }: TeamPageProps) {
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyUserId, setBusyUserId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const activeRole = auth.workspace?.role ?? "owner";
  const activeWorkspaceId = auth.workspace?.id;
  const canManage = activeRole === "owner" || activeRole === "admin";

  const refresh = useCallback(async () => {
    if (auth.mode === "local" || !activeWorkspaceId) {
      setMembers([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      setMembers(await getWorkspaceMembers());
      setError(null);
    } catch (reason) {
      setError(message(reason, "Workspace members could not be loaded."));
    } finally {
      setLoading(false);
    }
  }, [activeWorkspaceId, auth.mode]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function changeRole(member: WorkspaceMember, role: WorkspaceRole) {
    setBusyUserId(member.user_id);
    setError(null);
    try {
      await updateWorkspaceMemberRole(member.user_id, role);
      await refresh();
    } catch (reason) {
      setError(message(reason, "The member role could not be changed."));
    } finally {
      setBusyUserId(null);
    }
  }

  async function remove(member: WorkspaceMember) {
    if (!window.confirm(`Remove ${member.github_login} from this workspace?`)) return;
    setBusyUserId(member.user_id);
    setError(null);
    try {
      await removeWorkspaceMember(member.user_id);
      await refresh();
    } catch (reason) {
      setError(message(reason, "The member could not be removed."));
    } finally {
      setBusyUserId(null);
    }
  }

  return (
    <section>
      <header className="page-header">
        <div>
          <p className="page-eyebrow">Workspace access</p>
          <h1 className="page-title">Team &amp; Profile</h1>
          <p className="page-subtitle">
            Review the active workspace, member roles, and your authenticated identity.
          </p>
        </div>
      </header>

      <div className="team-layout">
        <section className="panel team-members-panel">
          <div className="panel-header">
            <h2 className="panel-title">{auth.workspace?.name ?? "Local Workspace"} members</h2>
            <p className="panel-copy">
              Roles are enforced by the API. A workspace must always retain an owner.
            </p>
          </div>
          {error && <div role="alert" className="inline-alert inline-alert-danger">{error}</div>}
          {auth.mode === "local" ? (
            <div className="empty-state">
              <strong>Local workspace mode</strong>
              <span>Team membership is available after GitHub authentication is enabled.</span>
            </div>
          ) : loading ? (
            <div role="status" className="empty-state">Loading workspace members…</div>
          ) : members.length === 0 ? (
            <div className="empty-state">No members were returned for this workspace.</div>
          ) : (
            <div className="data-table-wrap">
              <table className="data-table team-table">
                <thead><tr><th>Member</th><th>Role</th><th>Joined</th><th>Actions</th></tr></thead>
                <tbody>
                  {members.map((member) => {
                    const adminProtected = activeRole === "admin" && (member.role === "owner" || member.role === "admin");
                    return (
                      <tr key={member.user_id}>
                        <td>
                          <strong>{member.github_display_name ?? member.github_login}</strong>
                          <small>@{member.github_login}{member.user_id === auth.user?.id ? " · You" : ""}</small>
                        </td>
                        <td>
                          {canManage && !adminProtected ? (
                            <select
                              aria-label={`Role for ${member.github_login}`}
                              value={member.role}
                              disabled={busyUserId === member.user_id}
                              onChange={(event) => void changeRole(member, event.target.value as WorkspaceRole)}
                            >
                              {roles
                                .filter((role) => activeRole === "owner" || (role !== "owner" && role !== "admin"))
                                .map((role) => <option key={role} value={role}>{roleLabel(role)}</option>)}
                            </select>
                          ) : <span className="status-badge status-neutral">{roleLabel(member.role)}</span>}
                        </td>
                        <td>{new Date(member.joined_at).toLocaleDateString()}</td>
                        <td className="table-action">
                          <button
                            type="button"
                            className="button-quiet team-remove"
                            disabled={!canManage || adminProtected || busyUserId === member.user_id}
                            title={!canManage ? "Only owners and admins can remove members." : undefined}
                            onClick={() => void remove(member)}
                          >
                            Remove
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {auth.mode === "github" && (
            <p className="team-note">
              Invitation onboarding is not enabled yet. This page only displays and manages real persisted memberships.
            </p>
          )}
        </section>

        <aside className="panel profile-panel">
          <div className="panel-header"><h2 className="panel-title">Your profile</h2></div>
          <div className="profile-content">
            <div className="profile-avatar" aria-hidden="true">
              {auth.user?.avatar_url ? <img src={auth.user.avatar_url} alt="" /> : initials(auth.user?.github_login ?? "Local")}
            </div>
            <div>
              <strong>{auth.user?.github_display_name ?? auth.user?.github_login ?? "Local workspace"}</strong>
              {auth.user && <p>@{auth.user.github_login}</p>}
            </div>
            <dl className="profile-details">
              <div><dt>Active workspace</dt><dd>{auth.workspace?.name ?? "Local Workspace"}</dd></div>
              <div><dt>Workspace role</dt><dd>{roleLabel(activeRole)}</dd></div>
              <div><dt>Authentication</dt><dd>{auth.mode === "github" ? auth.user?.auth_provider ?? "GitHub" : "Local development"}</dd></div>
              <div><dt>Email</dt><dd>{auth.user?.email ?? "Not provided"}</dd></div>
            </dl>
            <p className="team-note">Profile editing and workspace invitations are not available yet.</p>
            {auth.mode === "github" && (
              <button type="button" className="button-secondary" onClick={() => void onLogout()}>
                Sign out
              </button>
            )}
          </div>
        </aside>
      </div>
    </section>
  );
}

function roleLabel(role: WorkspaceRole) {
  return role.charAt(0).toUpperCase() + role.slice(1);
}

function initials(value: string) {
  return value.slice(0, 2).toUpperCase();
}

function message(reason: unknown, fallback: string) {
  return reason instanceof Error ? reason.message : fallback;
}
