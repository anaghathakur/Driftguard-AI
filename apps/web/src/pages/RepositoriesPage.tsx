import { useState } from "react";
import "../workspace.css";
import { RepositoryAutomationPanel } from "../components/RepositoryAutomationPanel";
import type { GitHubInstallation, RepositoryConnection } from "../lib/api";

export function RepositoriesPage({
  installations,
  repositories,
  loading,
  error,
  installUrl,
  developmentMode,
  canManage,
  canAnalyze,
  onConnectMock,
  onSync,
  onToggle,
  onAnalyze,
}: {
  installations: GitHubInstallation[];
  repositories: RepositoryConnection[];
  loading: boolean;
  error: string | null;
  installUrl: string | null;
  developmentMode: boolean;
  canManage: boolean;
  canAnalyze: boolean;
  onConnectMock: () => void;
  onSync: (installationId: string) => void;
  onToggle: (repository: RepositoryConnection) => void;
  onAnalyze: (repository: RepositoryConnection) => void;
}) {
  const [selectedRepository, setSelectedRepository] = useState<RepositoryConnection | null>(null);
  return (
    <section className="repositories-page">
      <header className="page-header repository-header">
        <div>
          <p className="page-eyebrow">GitHub App</p>
          <h1 className="page-title">Repositories</h1>
          <p className="page-subtitle">DriftGuard only accesses repositories authorized through your workspace&apos;s GitHub App installation.</p>
        </div>
        {canManage && installUrl ? <a className="button-primary" href={installUrl}>Install DriftGuard GitHub App</a> : developmentMode ? <button type="button" className="button-secondary" disabled={!canManage} title={!canManage ? "Only owners and admins can connect installations." : undefined} onClick={onConnectMock}>Connect development installation</button> : <span className="status-badge status-warning">{canManage ? "GitHub App install URL not configured" : "Read-only repository access"}</span>}
      </header>

      <section className="panel onboarding-strip" aria-label="GitHub onboarding steps">
        {[
          ["1", "Install GitHub App"], ["2", "Choose account"], ["3", "Select repositories"], ["4", "Finish setup"],
        ].map(([step, label]) => <div key={step}><span>{step}</span><strong>{label}</strong></div>)}
      </section>

      {error && <div role="alert" className="inline-alert inline-alert-danger">{error}</div>}
      {installations.length > 0 && (
        <div className="installation-actions">
          {installations.map((installation) => (
            <div className="panel installation-card" key={installation.id}>
              <span><strong>{installation.account_login}</strong><small>{installation.account_type} · Installation {installation.github_installation_id}</small></span>
              <button type="button" className="button-secondary" disabled={!canManage || loading || installation.revoked} title={!canManage ? "Only owners and admins can synchronize repositories." : undefined} onClick={() => onSync(installation.id)}>Refresh repositories</button>
            </div>
          ))}
        </div>
      )}

      <section className="panel repository-list-panel">
        <div className="panel-header"><h2 className="panel-title">Authorized repositories</h2><p className="panel-copy">Disabling a repository stops DriftGuard use locally; it does not uninstall the GitHub App.</p></div>
        {loading ? <div className="empty-state">Synchronizing repository metadata…</div> : repositories.length === 0 ? <div className="empty-state">No authorized repositories are connected yet.</div> : (
          <div className="table-scroll"><table className="data-table repository-table"><thead><tr><th>Repository</th><th>Visibility</th><th>Default branch</th><th>Account</th><th>Status</th><th>Last synchronized</th><th>Actions</th></tr></thead><tbody>
            {repositories.map((repository) => <tr key={repository.id}><td><strong>{repository.full_name}</strong></td><td>{repository.private ? "Private" : "Public"}</td><td><code>{repository.default_branch}</code></td><td>{repository.owner}</td><td><span className={`status-badge ${repository.enabled && !repository.removed ? "status-success" : "status-neutral"}`}>{repository.removed ? "Access removed" : repository.enabled ? "Enabled" : "Disabled"}</span></td><td>{new Date(repository.last_synced_at).toLocaleString()}</td><td><div className="table-actions"><button type="button" className="button-quiet" disabled={!canAnalyze || !repository.enabled || repository.removed} title="Compare two API contract versions and trace their impact through this repository." onClick={() => onAnalyze(repository)}>Impact analysis</button><button type="button" className="button-quiet" disabled={repository.removed} onClick={() => setSelectedRepository(repository)}>Configure</button><button type="button" className="button-quiet" disabled={!canManage || repository.removed} onClick={() => onToggle(repository)}>{repository.enabled ? "Disable" : "Enable"}</button></div></td></tr>)}
          </tbody></table></div>
        )}
      </section>
      {selectedRepository && <RepositoryAutomationPanel repository={selectedRepository} canManage={canManage} canAnalyze={canAnalyze} onClose={() => setSelectedRepository(null)} />}
    </section>
  );
}
