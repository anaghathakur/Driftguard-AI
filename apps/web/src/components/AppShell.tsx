import type { ReactNode } from "react";

export type AppPage =
  | "overview"
  | "new-analysis"
  | "monitors"
  | "analyses"
  | "repositories"
  | "team"
  | "system-status"
  | "analysis-result";

type AppShellProps = {
  activePage: AppPage;
  backendReady: boolean | null;
  children: ReactNode;
  onNavigate: (page: AppPage) => void;
  workspaceLabel: string;
  userLabel?: string | null;
  workspaces?: Array<{ id: string; name: string }>;
  activeWorkspaceId?: string | null;
  onSwitchWorkspace?: (workspaceId: string) => void;
  roleLabel?: string | null;
  onLogout?: () => void;
};

const primaryItems: Array<{ page: AppPage; label: string; icon: IconName }> = [
  { page: "overview", label: "Overview", icon: "overview" },
  { page: "new-analysis", label: "New Analysis", icon: "analysis" },
  { page: "monitors", label: "API Monitors", icon: "monitor" },
  { page: "analyses", label: "Analyses", icon: "history" },
  { page: "repositories", label: "Repositories", icon: "repository" },
];

type IconName = "overview" | "analysis" | "monitor" | "history" | "repository" | "team" | "status";

export function AppShell({
  activePage,
  backendReady,
  children,
  onNavigate,
  workspaceLabel,
  userLabel,
  workspaces = [],
  activeWorkspaceId,
  onSwitchWorkspace,
  roleLabel,
  onLogout,
}: AppShellProps) {
  const navigationPage = activePage === "analysis-result" ? "analyses" : activePage;
  const statusLabel =
    backendReady === null
      ? "Checking system"
      : backendReady
        ? "System Ready"
        : "System Unavailable";

  return (
    <div className="app-shell">
      <header className="mobile-header">
        <Brand compact />
        <SystemIndicator ready={backendReady} label={statusLabel} compact />
      </header>

      <aside className="sidebar">
        <Brand />
        <nav aria-label="Primary navigation" className="sidebar-nav">
          {primaryItems.map((item) => (
            <NavigationButton
              key={item.page}
              active={navigationPage === item.page}
              icon={item.icon}
              label={item.label}
              onClick={() => onNavigate(item.page)}
            />
          ))}
        </nav>

        <div className="sidebar-system">
          <p className="sidebar-section-label">System</p>
          <NavigationButton
            active={navigationPage === "team"}
            icon="team"
            label="Team & Profile"
            onClick={() => onNavigate("team")}
          />
          <NavigationButton
            active={navigationPage === "system-status"}
            icon="status"
            label="System Status"
            onClick={() => onNavigate("system-status")}
          />
          <div className="workspace-status">
            <SystemIndicator ready={backendReady} label={statusLabel} />
            {userLabel && <small>{userLabel}</small>}
            {roleLabel && <small className="workspace-role">{roleLabel}</small>}
            {workspaces.length > 1 && onSwitchWorkspace ? (
              <select aria-label="Active workspace" value={activeWorkspaceId ?? ""} onChange={(event) => onSwitchWorkspace(event.target.value)}>
                {workspaces.map((workspace) => <option key={workspace.id} value={workspace.id}>{workspace.name}</option>)}
              </select>
            ) : <span>{workspaceLabel}</span>}
            {onLogout && <button type="button" className="sidebar-logout" onClick={onLogout}>Sign out</button>}
          </div>
        </div>
      </aside>

      <main className="app-main">{children}</main>

      <nav aria-label="Mobile navigation" className="mobile-nav">
        {primaryItems.map((item) => (
          <NavigationButton
            key={item.page}
            active={navigationPage === item.page}
            icon={item.icon}
            label={item.label.replace("API ", "")}
            onClick={() => onNavigate(item.page)}
            mobile
          />
        ))}
        <NavigationButton
          active={navigationPage === "system-status"}
          icon="status"
          label="Status"
          onClick={() => onNavigate("system-status")}
          mobile
        />
        <NavigationButton
          active={navigationPage === "team"}
          icon="team"
          label="Team"
          onClick={() => onNavigate("team")}
          mobile
        />
      </nav>
    </div>
  );
}

function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <div className={compact ? "brand brand-compact" : "brand"}>
      <span aria-hidden="true" className="brand-mark">DG</span>
      <span>
        <strong>DriftGuard AI</strong>
        {!compact && <small>API change intelligence</small>}
      </span>
    </div>
  );
}

function NavigationButton({
  active,
  icon,
  label,
  mobile = false,
  onClick,
}: {
  active: boolean;
  icon: IconName;
  label: string;
  mobile?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-current={active ? "page" : undefined}
      className={`${mobile ? "mobile-nav-item" : "sidebar-nav-item"}${active ? " is-active" : ""}`}
      onClick={onClick}
    >
      <Icon name={icon} />
      <span>{label}</span>
    </button>
  );
}

function SystemIndicator({
  ready,
  label,
  compact = false,
}: {
  ready: boolean | null;
  label: string;
  compact?: boolean;
}) {
  return (
    <span className={`system-indicator${ready === false ? " is-offline" : ""}`}>
      <span aria-hidden="true" className="system-dot" />
      {!compact && label}
      {compact && <span className="sr-only">{label}</span>}
    </span>
  );
}

function Icon({ name }: { name: IconName }) {
  const paths: Record<IconName, ReactNode> = {
    overview: <><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></>,
    analysis: <><path d="M4 19V5a2 2 0 0 1 2-2h8l6 6v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2Z"/><path d="M14 3v6h6M8 15h8M12 11v8"/></>,
    monitor: <><path d="M3 12h4l2-5 4 10 2-5h6"/><rect x="3" y="3" width="18" height="18" rx="3"/></>,
    repository: <><path d="M4 7h16v12H4z"/><path d="M8 7V5h8v2M8 12h8M8 16h5"/></>,
    team: <><circle cx="9" cy="8" r="3"/><circle cx="17" cy="9" r="2"/><path d="M3 20c0-4 2-6 6-6s6 2 6 6M15 15c3 0 5 1.5 5 4"/></>,
    history: <><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 7v5l3 2"/></>,
    status: <><circle cx="12" cy="12" r="9"/><path d="m8 12 2.5 2.5L16 9"/></>,
  };

  return (
    <svg aria-hidden="true" className="nav-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      {paths[name]}
    </svg>
  );
}
