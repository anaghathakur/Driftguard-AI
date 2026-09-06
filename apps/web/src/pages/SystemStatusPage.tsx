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
        <CapabilityCard label="Risk Classifier" status={readiness?.checks.risk_classifier} backendError={backendError} detail="Versioned model with deterministic fallback" />
        <CapabilityCard label="Migration Provider" status={readiness?.checks.migration_provider} backendError={backendError} detail={providerStatus ? `${providerStatus.active_provider} · ${providerStatus.provider_model}` : "Provider status pending"} />
        <CapabilityCard label="Patch Provider" status={readiness?.checks.patch_provider} backendError={backendError} detail="Evidence-gated bounded structured edits" />
        <CapabilityCard label="Test Provider" status={readiness?.checks.test_plan_provider} backendError={backendError} detail="Static discovery plus allowlisted execution when configured" />
        <CapabilityCard label="GitHub Write Provider" status={readiness?.checks.github_write_provider} backendError={backendError} detail="GitHub App; explicit confirmation; no automatic merge" />
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

function CapabilityCard({
  label,
  status,
  backendError,
  detail,
}: {
  label: string;
  status: string | undefined;
  backendError: boolean;
  detail: string;
}) {
  const normalized = backendError ? "unavailable" : status;
  const tone = normalized === "ready"
    ? "success"
    : normalized === "unavailable"
      ? "danger"
      : "warning";
  return (
    <MetricCard
      label={label}
      value={providerValue(status, backendError)}
      detail={detail}
      tone={tone}
    />
  );
}
