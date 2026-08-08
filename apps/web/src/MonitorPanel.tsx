import {
  useCallback,
  useEffect,
  useState,
  type FormEvent,
} from "react";

import {
  checkMonitor,
  createMonitor,
  deleteMonitor,
  getMonitorChecks,
  getMonitors,
  updateMonitor,
  type ApiMonitor,
  type MonitorCheck,
} from "./lib/api";

type MonitorPanelProps = {
  onViewAnalysis: (analysisId: string) => void;
};

export function MonitorPanel({
  onViewAnalysis,
}: MonitorPanelProps) {
  const [monitors, setMonitors] = useState<ApiMonitor[]>([]);
  const [checks, setChecks] = useState<Record<string, MonitorCheck[]>>({});
  const [expandedMonitor, setExpandedMonitor] = useState<string | null>(null);
  const [busyMonitor, setBusyMonitor] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    name: "",
    specificationUrl: "",
    repositoryUrl: "",
    repositoryRef: "",
    interval: "60",
  });

  const refresh = useCallback(async () => {
    try {
      setMonitors(await getMonitors());
      setError(null);
    } catch (reason) {
      setError(message(reason, "API monitors could not be loaded."));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    setIsCreating(true);
    setError(null);
    try {
      await createMonitor({
        name: form.name,
        specification_url: form.specificationUrl,
        repository_url: form.repositoryUrl,
        repository_ref: form.repositoryRef || undefined,
        check_interval_minutes: Number(form.interval),
        enabled: true,
      });
      setForm({
        name: "",
        specificationUrl: "",
        repositoryUrl: "",
        repositoryRef: "",
        interval: "60",
      });
      await refresh();
    } catch (reason) {
      setError(message(reason, "The monitor could not be created."));
    } finally {
      setIsCreating(false);
    }
  }

  async function runAction(monitorId: string, action: () => Promise<void>) {
    setBusyMonitor(monitorId);
    setError(null);
    try {
      await action();
      await refresh();
    } catch (reason) {
      setError(message(reason, "The monitor action could not be completed."));
      await refresh();
    } finally {
      setBusyMonitor(null);
    }
  }

  async function toggleHistory(monitorId: string) {
    if (expandedMonitor === monitorId) {
      setExpandedMonitor(null);
      return;
    }
    setBusyMonitor(monitorId);
    try {
      const history = await getMonitorChecks(monitorId);
      setChecks((current) => ({
        ...current,
        [monitorId]: history,
      }));
      setExpandedMonitor(monitorId);
    } catch (reason) {
      setError(message(reason, "Monitor history could not be loaded."));
    } finally {
      setBusyMonitor(null);
    }
  }

  return (
    <section className="mt-8 rounded-2xl border border-violet-400/20 bg-white/5 p-6 shadow-xl shadow-violet-950/20 backdrop-blur-xl">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-violet-300">
          Automatic monitoring
        </p>
        <h3 className="mt-2 text-xl font-semibold text-white">API Monitors</h3>
        <p className="mt-1 text-sm text-slate-400">
          Remember an OpenAPI baseline and analyze configured GitHub code only when it changes.
        </p>
      </div>

      <form onSubmit={(event) => void handleCreate(event)} className="mt-6 grid gap-4 rounded-xl border border-white/10 bg-black/20 p-4 md:grid-cols-2">
        <MonitorInput label="Monitor name" value={form.name} placeholder="Stripe Payments API" disabled={isCreating} onChange={(value) => setForm({ ...form, name: value })} />
        <MonitorInput label="OpenAPI URL" value={form.specificationUrl} placeholder="https://example.com/openapi.json" disabled={isCreating} onChange={(value) => setForm({ ...form, specificationUrl: value })} />
        <MonitorInput label="GitHub repository" value={form.repositoryUrl} placeholder="https://github.com/company/payment-service" disabled={isCreating} onChange={(value) => setForm({ ...form, repositoryUrl: value })} />
        <MonitorInput label="Branch, tag, or ref (optional)" value={form.repositoryRef} placeholder="main" disabled={isCreating} onChange={(value) => setForm({ ...form, repositoryRef: value })} />
        <MonitorInput label="Check interval (minutes)" value={form.interval} type="number" placeholder="60" disabled={isCreating} onChange={(value) => setForm({ ...form, interval: value })} />
        <div className="flex items-end">
          <button type="submit" disabled={isCreating || !form.name || !form.specificationUrl || !form.repositoryUrl} className="w-full rounded-xl bg-gradient-to-r from-violet-400 to-cyan-400 px-5 py-3 text-sm font-semibold text-slate-950 disabled:cursor-not-allowed disabled:opacity-50">
            {isCreating ? "Establishing baseline..." : "Create monitor"}
          </button>
        </div>
      </form>

      {error && <div className="mt-5 rounded-xl border border-rose-400/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-200">{error}</div>}

      <div className="mt-6 space-y-4">
        {monitors.length === 0 ? (
          <div className="rounded-xl border border-dashed border-white/10 p-8 text-center text-sm text-slate-500">No API monitors configured.</div>
        ) : monitors.map((monitor) => (
          <article key={monitor.monitor_id} className="rounded-xl border border-white/10 bg-black/20 p-5">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h4 className="font-semibold text-white">{monitor.name}</h4>
                  <Status status={monitor.last_check_status} />
                  <span className={`rounded-full px-2 py-1 text-xs ${monitor.enabled ? "bg-emerald-400/10 text-emerald-300" : "bg-slate-400/10 text-slate-400"}`}>{monitor.enabled ? "Enabled" : "Disabled"}</span>
                </div>
                <p className="mt-2 break-all text-xs text-slate-400">{monitor.specification_url}</p>
                <p className="mt-1 break-all text-xs text-slate-500">{monitor.repository_url}{monitor.repository_ref ? ` · ${monitor.repository_ref}` : ""}</p>
                <div className="mt-3 flex flex-wrap gap-4 text-xs text-slate-500">
                  <span>Baseline: <code>{monitor.baseline_sha256.slice(0, 12)}</code></span>
                  <span>Every {monitor.check_interval_minutes} min</span>
                  <span>Last checked: {formatDate(monitor.last_checked_at)}</span>
                </div>
                {monitor.last_error_message && <p className="mt-3 text-sm text-rose-300">Check failed: {monitor.last_error_message}</p>}
              </div>

              <div className="flex flex-wrap gap-2">
                <Action disabled={busyMonitor === monitor.monitor_id} onClick={() => void runAction(monitor.monitor_id, async () => { await checkMonitor(monitor.monitor_id); })}>Check now</Action>
                <Action disabled={busyMonitor === monitor.monitor_id} onClick={() => void runAction(monitor.monitor_id, async () => { await updateMonitor(monitor.monitor_id, { enabled: !monitor.enabled }); })}>{monitor.enabled ? "Disable" : "Enable"}</Action>
                <Action disabled={busyMonitor === monitor.monitor_id} onClick={() => void toggleHistory(monitor.monitor_id)}>History</Action>
                {monitor.last_successful_analysis_id && <Action disabled={false} onClick={() => onViewAnalysis(monitor.last_successful_analysis_id as string)}>View analysis</Action>}
                <Action danger disabled={busyMonitor === monitor.monitor_id} onClick={() => { if (window.confirm(`Delete monitor “${monitor.name}”?`)) void runAction(monitor.monitor_id, async () => { await deleteMonitor(monitor.monitor_id); }); }}>Delete</Action>
              </div>
            </div>

            {expandedMonitor === monitor.monitor_id && (
              <div className="mt-4 border-t border-white/10 pt-4">
                {(checks[monitor.monitor_id] ?? []).length === 0 ? <p className="text-sm text-slate-500">No checks recorded.</p> : (
                  <div className="space-y-2">{checks[monitor.monitor_id].map((check) => (
                    <div key={check.check_id} className="flex flex-col gap-2 rounded-lg bg-white/[0.03] px-3 py-2 text-xs text-slate-400 sm:flex-row sm:items-center sm:justify-between">
                      <span>{formatDate(check.checked_at)} · {label(check.status)}</span>
                      <span>{check.duration_ms ?? 0} ms{check.analysis_id ? " · analysis created" : ""}</span>
                    </div>
                  ))}</div>
                )}
              </div>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}

function MonitorInput({ label, value, placeholder, type = "text", disabled, onChange }: { label: string; value: string; placeholder: string; type?: string; disabled: boolean; onChange: (value: string) => void }) {
  return <label className="block"><span className="text-sm font-semibold text-slate-200">{label}</span><input required={label.indexOf("optional") === -1} type={type} min={type === "number" ? 1 : undefined} max={type === "number" ? 10080 : undefined} value={value} placeholder={placeholder} disabled={disabled} onChange={(event) => onChange(event.target.value)} className="mt-2 w-full rounded-lg border border-white/10 bg-slate-950/80 px-3 py-2.5 text-sm text-slate-100 outline-none placeholder:text-slate-600 focus:border-violet-400/50 disabled:opacity-60" /></label>;
}

function Action({ children, onClick, disabled, danger = false }: { children: string; onClick: () => void; disabled: boolean; danger?: boolean }) {
  return <button type="button" onClick={onClick} disabled={disabled} className={`rounded-lg border px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50 ${danger ? "border-rose-400/20 text-rose-300 hover:bg-rose-400/10" : "border-cyan-400/20 text-cyan-200 hover:bg-cyan-400/10"}`}>{children}</button>;
}

function Status({ status }: { status: ApiMonitor["last_check_status"] }) {
  if (!status) return <span className="rounded-full bg-slate-400/10 px-2 py-1 text-xs text-slate-400">Baseline ready</span>;
  const color = status === "changed" ? "text-amber-300 bg-amber-400/10" : status === "failed" ? "text-rose-300 bg-rose-400/10" : status === "unchanged" ? "text-emerald-300 bg-emerald-400/10" : "text-cyan-300 bg-cyan-400/10";
  return <span className={`rounded-full px-2 py-1 text-xs ${color}`}>{label(status)}</span>;
}

function label(status: ApiMonitor["last_check_status"] | MonitorCheck["status"]) {
  if (status === "changed") return "API change detected";
  if (status === "unchanged") return "No API change detected";
  if (status === "failed") return "Check failed";
  return "Checking";
}

function formatDate(value: string | null) {
  return value ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "Never";
}

function message(reason: unknown, fallback: string) {
  return reason instanceof Error ? reason.message : fallback;
}
