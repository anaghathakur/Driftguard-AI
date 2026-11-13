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
  onSwitchMode,
}: {
  signup?: boolean;
  githubConfigured: boolean;
  developmentContent?: ReactNode;
  googleConfigured: boolean;
  message?: string | null;
  onHome: () => void;
  onRetry?: () => void;
  onSwitchMode?: () => void;
}) {
  const returnTo = window.location.origin + "/app";
  const title = signup ? "Create your DriftGuard account" : "Sign in to DriftGuard";
  const actionLabel = signup ? "Create account" : "Welcome back";
  return (
    <main className="auth-page auth-page-product">
      <section className="auth-layout" aria-label={title}>
        <aside className="auth-product-panel">
          <button type="button" className="brand auth-brand auth-brand-button" onClick={onHome}>
            <span aria-hidden="true" className="brand-mark">DG</span>
            <span><strong>DriftGuard AI</strong><small>API change intelligence</small></span>
          </button>
          <div className="auth-product-copy">
            <p className="page-eyebrow">Controlled change intelligence</p>
            <h2>Know what breaks before production does.</h2>
            <p>Trace API contract drift through your codebase, then prepare a bounded fix for human review.</p>
          </div>
          <ul className="auth-trust-list">
            <li><span aria-hidden="true">01</span><div><strong>Workspace isolation</strong><small>Your analyses and repositories stay scoped to your team.</small></div></li>
            <li><span aria-hidden="true">02</span><div><strong>Least-privilege GitHub access</strong><small>Repository authorization happens through the DriftGuard GitHub App, never a personal access token.</small></div></li>
            <li><span aria-hidden="true">03</span><div><strong>Human review stays in control</strong><small>DriftGuard proposes changes; it does not merge or deploy them automatically.</small></div></li>
          </ul>
          <p className="auth-product-footnote">Built for engineering teams that treat API changes as production work.</p>
        </aside>

        <section className="auth-card">
          <div className="auth-card-heading">
            <p className="page-eyebrow">{actionLabel}</p>
            <h1>{title}</h1>
            <p>Use your engineering identity to enter your workspace. GitHub App permissions are requested separately when you connect repositories.</p>
          </div>

          {message && (
            <div role="status" className="auth-service-notice">
              <span aria-hidden="true" className="auth-notice-icon">!</span>
              <div>
                <strong>Authentication service unavailable</strong>
                <p>{message}</p>
              </div>
            </div>
          )}
          {onRetry && (
            <button className="button-secondary auth-retry" type="button" onClick={onRetry}>
              Retry connection
            </button>
          )}

          <div className="auth-provider-list" aria-label="Authentication providers">
            <button
              className="auth-provider auth-provider-google"
              type="button"
              disabled
              title={googleConfigured ? "Google OAuth is not available in this release." : "Google OAuth is not configured."}
            >
              <span className="auth-provider-icon auth-provider-icon-google" aria-hidden="true">G</span>
              <span>Continue with Google</span>
              <small>Not configured</small>
            </button>
            {githubConfigured ? (
              <a className="auth-provider auth-provider-github" href={githubSignInUrl(undefined, returnTo)}>
                <GitHubMark />
                <span>Continue with GitHub</span>
              </a>
            ) : (
              <button className="auth-provider auth-provider-github" type="button" disabled title="GitHub OAuth credentials are not configured.">
                <GitHubMark />
                <span>Continue with GitHub</span>
                <small>Not configured</small>
              </button>
            )}
          </div>

          {developmentContent && <div className="auth-development-panel">{developmentContent}</div>}

          <div className="auth-switch-row">
            <span>{signup ? "Already have a DriftGuard account?" : "New to DriftGuard?"}</span>
            <button type="button" className="button-quiet" onClick={onSwitchMode}>
              {signup ? "Sign in" : "Create account"}
            </button>
          </div>
          <p className="auth-terms">By continuing, you agree to use connected repositories only with your team's authorization.</p>
        </section>
      </section>
    </main>
  );
}

function GitHubMark() {
  return (
    <svg className="auth-provider-icon" aria-hidden="true" viewBox="0 0 16 16" fill="currentColor">
      <path d="M8 0C3.58 0 0 3.67 0 8.2c0 3.62 2.29 6.69 5.47 7.77.4.08.55-.18.55-.4 0-.2-.01-.86-.01-1.56-2.23.5-2.7-.97-2.7-.97-.36-.95-.89-1.2-.89-1.2-.73-.51.06-.5.06-.5.81.06 1.24.85 1.24.85.72 1.27 1.89.9 2.35.69.07-.54.28-.9.51-1.11-1.78-.21-3.65-.92-3.65-4.08 0-.9.31-1.63.83-2.21-.08-.21-.36-1.05.08-2.19 0 0 .68-.22 2.2.84A7.45 7.45 0 0 1 8 3.78c.68 0 1.37.1 2.01.28 1.52-1.06 2.2-.84 2.2-.84.44 1.14.16 1.98.08 2.19.51.58.83 1.31.83 2.21 0 3.17-1.88 3.86-3.67 4.07.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .22.14.48.55.4A8.2 8.2 0 0 0 16 8.2C16 3.67 12.42 0 8 0Z" />
    </svg>
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
