import "../monitors.css";

import { MonitorPanel } from "../MonitorPanel";
import type { ApiMonitor } from "../lib/api";

export function MonitorsPage({
  onViewAnalysis,
  onMonitorsChanged,
}: {
  onViewAnalysis: (analysisId: string) => void;
  onMonitorsChanged: (monitors: ApiMonitor[]) => void;
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
      <MonitorPanel onViewAnalysis={onViewAnalysis} onMonitorsChanged={onMonitorsChanged} />
    </section>
  );
}
