import { MetricCard } from "../components/MetricCard";
import { StatusBadge } from "../components/StatusBadge";
import { WorkflowSteps } from "../components/WorkflowSteps";
import type {
  AnalysisHistoryItem,
  ApiMonitor,
  RepositoryConnection,
} from "../lib/api";

type OverviewPageProps = {
  analyses: AnalysisHistoryItem[];
  monitors: ApiMonitor[];
  repositories: RepositoryConnection[];
  isLoading: boolean;
  error: string | null;
  openingAnalysisId: string | null;
  onNavigateToAnalysis: () => void;
  onNavigateToMonitors: () => void;
  onNavigateToRepositories: () => void;
  onOpenAnalysis: (item: AnalysisHistoryItem) => void;
};

export function OverviewPage({
  analyses,
  monitors,
  repositories,
  isLoading,
  error,
  openingAnalysisId,
  onNavigateToAnalysis,
  onNavigateToMonitors,
  onNavigateToRepositories,
  onOpenAnalysis,
}: OverviewPageProps) {
  const recent = analyses.slice(0, 6);
  const activeMonitors = monitors.filter((monitor) => monitor.enabled).length;
  const detectedChanges = analyses.reduce((sum, item) => sum + item.total_changes, 0);
  const connectedRepositories = repositories.filter(
    (repository) => repository.enabled && !repository.removed,
  ).length;

  return (
    <div className="overview-page">
      <section className="overview-hero">
        <p className="page-eyebrow">API change intelligence</p>
        <h1 className="page-title">Detect breaking API changes before they break production.</h1>
        <p className="page-subtitle">
          Monitor API contracts, trace affected code, assess migration risk, and prepare validated fixes for human review.
        </p>
        <div className="overview-actions">
          <button type="button" className="button-primary" onClick={onNavigateToAnalysis}>Analyze API Change</button>
          <button type="button" className="button-secondary" onClick={onNavigateToMonitors}>Create Monitor</button>
        </div>
      </section>

      <WorkflowSteps />

      <section aria-label="Workspace metrics" className="overview-metrics">
        <MetricCard label="Saved analyses" value={analyses.length} detail="Persisted analysis records" />
        <MetricCard label="Active monitors" value={activeMonitors} detail={`${monitors.length} configured`} tone={activeMonitors > 0 ? "success" : "default"} />
        <MetricCard label="Detected changes" value={detectedChanges} detail="Across saved analyses" tone={detectedChanges > 0 ? "warning" : "default"} />
        <MetricCard label="Connected repositories" value={connectedRepositories} detail={repositories.length + " authorized"} />
      </section>

      <section className="panel overview-activity">
        <div className="panel-header overview-activity-header">
          <div>
            <h2 className="panel-title">Recent activity</h2>
            <p className="panel-copy">Real persisted analyses from this workspace.</p>
          </div>
          <StatusBadge tone="info">{analyses.length} total</StatusBadge>
        </div>

        {error && <div role="alert" className="inline-alert inline-alert-danger">{error}</div>}
        {!error && isLoading && recent.length === 0 && <div role="status" className="empty-state">Loading saved analyses…</div>}
        {!error && !isLoading && recent.length === 0 && (
          <div className="empty-state">
            <strong>No analyses yet</strong>
            <span>Connect a repository or compare real contract versions to create your first result.</span>
            <div className="empty-state-actions">
              <button type="button" className="button-primary" onClick={onNavigateToAnalysis}>Run first analysis</button>
              <button type="button" className="button-secondary" onClick={onNavigateToRepositories}>Connect repository</button>
            </div>
          </div>
        )}

        {recent.length > 0 && (
          <div className="data-table-wrap">
            <table className="data-table">
              <thead><tr><th>Analysis</th><th>Source</th><th>Changes</th><th>Matches</th><th>Status</th><th>Created</th><th><span className="sr-only">Action</span></th></tr></thead>
              <tbody>
                {recent.map((item) => (
                  <tr key={item.analysis_id}>
                    <td><code>{shortId(item.analysis_id)}</code></td>
                    <td>{item.kind === "impact" ? "Repository impact" : "Specification only"}</td>
                    <td>{item.total_changes}</td>
                    <td>{item.total_matches}</td>
                    <td><AnalysisStatus status={item.status} /></td>
                    <td>{formatDate(item.created_at)}</td>
                    <td className="table-action">
                      <button type="button" className="table-link" disabled={openingAnalysisId === item.analysis_id || item.status !== "succeeded"} onClick={() => onOpenAnalysis(item)}>
                        {openingAnalysisId === item.analysis_id ? "Opening…" : "Open Result"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function AnalysisStatus({ status }: { status: AnalysisHistoryItem["status"] }) {
  const tone = status === "succeeded" ? "success" : status === "failed" ? "danger" : "warning";
  return <StatusBadge tone={tone}>{status}</StatusBadge>;
}

function shortId(value: string) {
  return value.length > 14 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}
