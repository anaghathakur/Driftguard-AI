import "../monitors.css";

import { MonitorPanel } from "../MonitorPanel";
import type { ApiMonitor } from "../lib/api";

export function MonitorsPage({
  onViewAnalysis,
  onMonitorsChanged,
  canManage,
  canCheck,
}: {
  onViewAnalysis: (analysisId: string) => void;
  onMonitorsChanged: (monitors: ApiMonitor[]) => void;
  canManage: boolean;
  canCheck: boolean;
}) {
  return (
    <section>
      <header className="page-header">
        <div>
          <p className="page-eyebrow">Contract drift</p>
          <h1 className="page-title">API Monitors</h1>
          <p className="page-subtitle">Monitor API contracts and automatically detect drift.</p>
        </div>
      </header>
      <MonitorPanel onViewAnalysis={onViewAnalysis} onMonitorsChanged={onMonitorsChanged} canManage={canManage} canCheck={canCheck} />
      {(!canManage || !canCheck) && <div className="inline-alert">Your {canCheck ? "Developer" : "Viewer"} permissions are enforced by the API. Some monitor actions may be unavailable.</div>}
    </section>
  );
}
