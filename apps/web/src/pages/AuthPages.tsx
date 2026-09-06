import type { ReactNode } from "react";

import "../workspace.css";
import { githubSignInUrl } from "../lib/api";

export function SignInPage({
  signup = false,
  githubConfigured,
  developmentContent,
  googleConfigured,
  message,
  onHome,
  onRetry,
}: {
  signup?: boolean;
  githubConfigured: boolean;
  developmentContent?: ReactNode;
  googleConfigured: boolean;
  message?: string | null;
  onHome: () => void;
  onRetry?: () => void;
}) {
  const returnTo = window.location.origin + "/app";
  return (
    <main className="auth-page">
      <section className="auth-card">
        <button type="button" className="brand auth-brand auth-brand-button" onClick={onHome}>
          <span aria-hidden="true" className="brand-mark">DG</span>
          <span><strong>DriftGuard AI</strong><small>API change intelligence</small></span>
        </button>
        <p className="page-eyebrow">{signup ? "Create account" : "Welcome back"}</p>
        <h1>{signup ? "Create your DriftGuard account" : "Sign in to DriftGuard"}</h1>
        <p>Identity sign-in is separate from the GitHub App permissions used to access repositories.</p>
        {message && <div role="status" className="inline-alert">{message}</div>}
        {onRetry && (
          <button className="button-secondary auth-action" type="button" onClick={onRetry}>
            Retry connection
          </button>
        )}
        <div className="auth-provider-list">
          <button
            className="button-secondary auth-action"
            type="button"
            disabled
            title={googleConfigured ? "Google OAuth is not available in this release." : "Google OAuth is not configured."}
          >
            Continue with Google · Not configured
          </button>
          {githubConfigured ? (
            <a className="button-primary auth-action" href={githubSignInUrl(undefined, returnTo)}>
              Continue with GitHub
            </a>
          ) : (
            <button className="button-primary auth-action" type="button" disabled title="GitHub OAuth credentials are not configured.">
              Continue with GitHub · Not configured
            </button>
          )}
        </div>
        {developmentContent ?? (
          <small>Repository authorization happens later through the DriftGuard GitHub App—never a personal access token.</small>
        )}
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
