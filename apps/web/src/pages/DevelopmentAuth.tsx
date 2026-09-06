import { githubSignInUrl } from "../lib/api";

export default function DevelopmentAuth({
  standalone = false,
  onBack,
}: {
  standalone?: boolean;
  onBack?: () => void;
}) {
  const returnTo = window.location.origin + "/app";
  const content = (
    <>
      <p className="page-eyebrow">Development testing</p>
      {standalone && <h1>Tenant isolation identities</h1>}
      <small>These deterministic identities are isolated tenant-testing utilities and never contact GitHub.</small>
      <div className="auth-development-actions">
        <a className="button-primary auth-action" href={githubSignInUrl("primary", returnTo)}>
          Continue as development user A
        </a>
        <a className="button-secondary auth-action" href={githubSignInUrl("secondary", returnTo)}>
          Continue as development user B
        </a>
      </div>
      {standalone && onBack && <button type="button" className="button-quiet" onClick={onBack}>Back to sign in</button>}
    </>
  );
  if (!standalone) return <div className="development-auth-link">{content}</div>;
  return <main className="auth-page"><section className="auth-card development-auth-card">{content}</section></main>;
}
