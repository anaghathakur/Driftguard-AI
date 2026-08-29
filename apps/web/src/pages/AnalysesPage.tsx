import "../analyses.css";
import { useState } from "react";

import { StatusBadge } from "../components/StatusBadge";
import type { AnalysisHistoryItem } from "../lib/api";

export function AnalysesPage({
  analyses,
  isLoading,
  error,
  openingAnalysisId,
  onRefresh,
  onOpen,
}: {
  analyses: AnalysisHistoryItem[];
  isLoading: boolean;
  error: string | null;
  openingAnalysisId: string | null;
  onRefresh: () => void;
  onOpen: (item: AnalysisHistoryItem) => void;
}) {
  const [filter, setFilter] = useState<"all" | AnalysisHistoryItem["kind"]>("all");
  const visible = analyses.filter((item) => filter === "all" || item.kind === filter);

  return (
    <section>
      <header className="page-header">
        <div>
          <p className="page-eyebrow">Persistence</p>
          <h1 className="page-title">Analyses</h1>
          <p className="page-subtitle">Reopen persisted comparisons and repository impact analyses without uploading files again.</p>
        </div>
        <button type="button" className="button-secondary" disabled={isLoading} onClick={onRefresh}>{isLoading ? "Refreshing…" : "Refresh"}</button>
      </header>

      <div className="analysis-list-toolbar">
        <div role="group" aria-label="Filter analyses" className="segmented-control analysis-filter">
          {(["all", "comparison", "impact"] as const).map((value) => (
            <button key={value} type="button" className={filter === value ? "is-active" : ""} aria-pressed={filter === value} onClick={() => setFilter(value)}>{value === "all" ? "All" : value === "impact" ? "Repository impact" : "Specification"}</button>
          ))}
        </div>
        <span>{visible.length} shown · {analyses.length} total</span>
      </div>

      <section className="panel analyses-table-panel">
        {error && <div role="alert" className="inline-alert inline-alert-danger">{error}</div>}
        {!error && isLoading && analyses.length === 0 && <div role="status" className="empty-state">Loading saved analyses…</div>}
        {!error && !isLoading && visible.length === 0 && <div className="empty-state"><strong>No matching analyses</strong><span>Complete an analysis or change the current filter.</span></div>}
        {visible.length > 0 && (
          <div className="data-table-wrap">
            <table className="data-table">
              <thead><tr><th>Type</th><th>Analysis</th><th>Source</th><th>Changes</th><th>Matches</th><th>Created</th><th>Status</th><th><span className="sr-only">Action</span></th></tr></thead>
              <tbody>{visible.map((item) => (
                <tr key={item.analysis_id}>
                  <td><StatusBadge tone="info">{item.kind}</StatusBadge></td>
                  <td><code>{shortId(item.analysis_id)}</code></td>
                  <td>{item.kind === "impact" ? "Repository impact" : "Specification only"}</td>
                  <td>{item.total_changes}</td>
                  <td>{item.total_matches}</td>
                  <td>{formatDate(item.created_at)}</td>
                  <td><AnalysisStatus status={item.status} /></td>
                  <td className="table-action"><button type="button" className="table-link" disabled={openingAnalysisId === item.analysis_id || item.status !== "succeeded"} onClick={() => onOpen(item)}>{openingAnalysisId === item.analysis_id ? "Opening…" : "Open Result"}</button></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </section>
    </section>
  );
}

function AnalysisStatus({ status }: { status: AnalysisHistoryItem["status"] }) {
  const tone = status === "succeeded" ? "success" : status === "failed" ? "danger" : "warning";
  return <StatusBadge tone={tone}>{status}</StatusBadge>;
}
function shortId(value: string) { return value.length > 14 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value; }
function formatDate(value: string) { return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)); }
