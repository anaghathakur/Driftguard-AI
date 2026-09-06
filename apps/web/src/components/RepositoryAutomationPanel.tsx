import { useCallback, useEffect, useState } from "react";
import "../automation.css";
import {
  configureRepositoryContract,
  discoverRepositoryContracts,
  getRepositoryAutomation,
  setRepositoryContractEnabled,
  type RepositoryAutomation,
} from "../lib/automationApi";
import type { RepositoryConnection } from "../lib/api";

export function RepositoryAutomationPanel({
  repository,
  canManage,
  canAnalyze,
  onClose,
}: {
  repository: RepositoryConnection;
  canManage: boolean;
  canAnalyze: boolean;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<RepositoryAutomation | null>(null);
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      setDetail(await getRepositoryAutomation(repository.id));
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Automation status is unavailable.");
    }
  }, [repository.id]);

  useEffect(() => { void load(); }, [load]);

  async function configure() {
    if (!canManage || !path.trim()) return;
    setBusy(true);
    try {
      await configureRepositoryContract(repository.id, path.trim());
      setPath("");
      await load();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Contract configuration failed.");
    } finally { setBusy(false); }
  }

  async function discover() {
    if (!canAnalyze) return;
    setBusy(true);
    try {
      await discoverRepositoryContracts(repository.id);
      await load();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Contract discovery failed.");
    } finally { setBusy(false); }
  }

  return (
    <section className="panel repository-automation" aria-label={`${repository.full_name} automation`}>
      <div className="panel-header automation-panel-header">
        <div><p className="page-eyebrow">Repository automation</p><h2 className="panel-title">{repository.full_name}</h2></div>
        <button type="button" className="button-quiet" onClick={onClose}>Close</button>
      </div>
      {error && <div role="alert" className="inline-alert inline-alert-danger">{error}</div>}
      {!detail ? <div className="empty-state">Loading automation state…</div> : <>
        <div className="automation-status-grid">
          <span><small>GitHub App</small><strong>{repository.removed ? "Reconnect required" : "Connected"}</strong></span>
          <span><small>Automation</small><strong>{detail.automation_enabled ? "Enabled" : "Disabled"}</strong></span>
          <span><small>Contracts</small><strong>{detail.contracts.filter((item) => item.enabled).length} monitored</strong></span>
          <span><small>Latest check</small><strong>{detail.checks[0]?.status.replaceAll("_", " ") ?? "No activity"}</strong></span>
        </div>
        <div className="automation-actions">
          <button type="button" className="button-primary" disabled={!canAnalyze || busy || !detail.automation_enabled} title={!canAnalyze ? "Viewer access is read-only." : undefined} onClick={() => void discover()}>{busy ? "Scanning snapshot…" : "Discover contracts"}</button>
        </div>
        <div className="contract-config">
          <label htmlFor={`contract-path-${repository.id}`}>Contract path</label>
          <div><input id={`contract-path-${repository.id}`} value={path} disabled={!canManage} onChange={(event) => setPath(event.target.value)} placeholder="openapi.yaml or graphql/schema.graphql" /><button type="button" className="button-secondary" disabled={!canManage || busy || !path.trim()} title={!canManage ? "Only owners and admins can configure contracts." : undefined} onClick={() => void configure()}>Configure contract</button></div>
          <small>The path is verified against an immutable authorized repository snapshot.</small>
          <small>Discovery uses the current commit. Breaking-change analysis still requires two contract versions; Pull Request automation compares base and head commits automatically.</small>
        </div>
        <div className="compact-list">
          <h3>Discovered contracts</h3>
          {detail.contracts.length === 0 ? <p className="muted-copy">No valid OpenAPI or GraphQL contract has been discovered yet.</p> : detail.contracts.map((contract) => (
            <div key={contract.contract_id} className="compact-list-row">
              <span><strong><code>{contract.path}</code></strong><small>{contract.title} · {contract.contract_kind === "graphql" ? "GraphQL SDL" : `OpenAPI ${contract.version}`}{contract.manually_configured ? " · Manually configured" : ""}</small></span>
              <button type="button" className="button-quiet" disabled={!canManage || busy} onClick={async () => { setBusy(true); try { await setRepositoryContractEnabled(repository.id, contract.contract_id, !contract.enabled); await load(); } finally { setBusy(false); } }}>{contract.enabled ? "Disable" : "Enable"}</button>
            </div>
          ))}
        </div>
        <div className="compact-list">
          <h3>Consumer dependencies</h3>
          {detail.dependencies.length === 0 ? <p className="muted-copy">No confirmed API dependency associations.</p> : detail.dependencies.map((dependency) => <div key={dependency.dependency_id} className="compact-list-row"><span><strong>{dependency.evidence_type.replaceAll("_", " ")}</strong><small>{Math.round(dependency.confidence * 100)}% confidence · {dependency.confirmed ? "Confirmed" : "Needs confirmation"}</small></span></div>)}
        </div>
      </>}
    </section>
  );
}
