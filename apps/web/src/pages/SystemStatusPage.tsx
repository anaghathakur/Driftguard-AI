import { MetricCard } from "../components/MetricCard";
import { StatusBadge } from "../components/StatusBadge";
import type { MigrationProviderStatus, ReadinessStatus } from "../lib/api";

export function SystemStatusPage({
  backendError,
  providerStatus,
  readiness,
}: {
  backendError: boolean;
  providerStatus: MigrationProviderStatus | null;
  readiness: ReadinessStatus | null;
}) {
  const engineReady = !backendError && readiness?.checks.analysis_engine !== "unavailable";

  return (
    <section>
      <header className="page-header">
        <div>
          <p className="page-eyebrow">Runtime capabilities</p>
          <h1 className="page-title">System Status</h1>
          <p className="page-subtitle">Live provider availability from DriftGuard’s readiness and provider endpoints.</p>
        </div>
        <StatusBadge tone={backendError ? "danger" : readiness?.status === "ready" ? "success" : "warning"}>
          {backendError ? "Unavailable" : readiness?.status === "ready" ? "Ready" : "Checking"}
        </StatusBadge>
      </header>

      <div className="status-grid">
        <MetricCard label="Analysis Engine" value={backendError ? "Unavailable" : engineReady ? "Ready" : "Checking"} detail="OpenAPI comparison and repository impact" tone={backendError ? "danger" : "success"} />
        <MetricCard label="Risk Classifier" value={providerValue(readiness?.checks.risk_classifier, backendError)} detail="Versioned model with deterministic fallback" />
        <MetricCard label="Migration Provider" value={providerStatus?.active_provider ?? (backendError ? "Unavailable" : "Checking")} detail={providerStatus?.provider_model ?? "Provider status pending"} />
        <MetricCard label="Patch Provider" value={providerValue(readiness?.checks.patch_provider, backendError)} detail="Bounded review-only structured edits" />
        <MetricCard label="Test Plan Provider" value={providerValue(readiness?.checks.test_plan_provider, backendError)} detail="Static discovery; tests are not executed" />
        <MetricCard label="GitHub Write Provider" value={providerValue(readiness?.checks.github_write_provider, backendError)} detail="Explicit confirmation; no automatic merge" />
      </div>

      {readiness && readiness.issues.length > 0 && (
        <div role="status" className="inline-alert inline-alert-danger status-issues">
          <strong>Readiness issues</strong>
          <ul>{readiness.issues.map((issue) => <li key={issue}>{issue}</li>)}</ul>
        </div>
      )}
    </section>
  );
}

function providerValue(value: string | undefined, backendError: boolean) {
  if (backendError) return "Unavailable";
  if (!value) return "Checking";
  return value.replaceAll("_", " ");
}
