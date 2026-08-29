import "../workspace.css";
import { githubSignInUrl } from "../lib/api";

export function SignInPage() {
  return (
    <main className="auth-page">
      <section className="auth-card">
        <div className="brand auth-brand">
          <span aria-hidden="true" className="brand-mark">DG</span>
          <span><strong>DriftGuard AI</strong><small>API change intelligence</small></span>
        </div>
        <p className="page-eyebrow">Team workspaces</p>
        <h1>Detect breaking API changes before they break production.</h1>
        <p>Connect your engineering workspace and authorize only the repositories DriftGuard should analyze.</p>
        <a className="button-primary auth-action" href={githubSignInUrl()}>
          Continue with GitHub
        </a>
        <small>Identity uses GitHub OAuth. Repository access uses the DriftGuard GitHub App—never a personal access token.</small>
      </section>
    </main>
  );
}

export function CreateWorkspacePage({
  name,
  error,
  busy,
  onNameChange,
  onSubmit,
}: {
  name: string;
  error: string | null;
  busy: boolean;
  onNameChange: (name: string) => void;
  onSubmit: () => void;
}) {
  return (
    <main className="auth-page">
      <section className="auth-card">
        <p className="page-eyebrow">Workspace setup</p>
        <h1>Create your workspace</h1>
        <p>Workspaces isolate analyses, monitors, repositories, patches, validations, and Pull Requests.</p>
        <label className="text-field" htmlFor="workspace-name">
          <span><strong>Workspace name</strong><em>Required</em></span>
          <small>Your engineering team or product group</small>
          <input id="workspace-name" value={name} placeholder="Acme Engineering" disabled={busy} onChange={(event) => onNameChange(event.target.value)} />
        </label>
        {error && <div role="alert" className="inline-alert inline-alert-danger">{error}</div>}
        <button type="button" className="button-primary auth-action" disabled={busy || name.trim().length < 2} onClick={onSubmit}>
          {busy ? "Creating…" : "Create workspace"}
        </button>
      </section>
    </main>
  );
}
