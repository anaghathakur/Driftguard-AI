import "../landing.css";

type LandingPageProps = {
  authenticated: boolean;
  onGetStarted: () => void;
  onSignIn: () => void;
  onOpenApp: () => void;
};

export function LandingPage({
  authenticated,
  onGetStarted,
  onSignIn,
  onOpenApp,
}: LandingPageProps) {
  return (
    <main className="landing-page">
      <nav className="landing-nav" aria-label="Public navigation">
        <button className="landing-brand" type="button" onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}>
          <span aria-hidden="true">DG</span>
          <strong>DriftGuard AI</strong>
        </button>
        <div className="landing-links">
          <a href="#product">Product</a>
          <a href="#security">Security</a>
        </div>
        <div className="landing-auth-actions">
          {authenticated ? (
            <button className="button-secondary" type="button" onClick={onOpenApp}>Open dashboard</button>
          ) : (
            <>
              <button className="button-quiet" type="button" onClick={onSignIn}>Sign in</button>
              <button className="button-primary" type="button" onClick={onGetStarted}>Get started</button>
            </>
          )}
        </div>
      </nav>

      <section className="landing-hero">
        <div className="landing-hero-copy">
          <p className="landing-kicker">API change intelligence for engineering teams</p>
          <h1>Ship API changes<br />with confidence.</h1>
          <p>
            Detect breaking contract changes, trace their impact through source code,
            prepare bounded fixes, and validate them before human review.
          </p>
          <div className="landing-hero-actions">
            <button className="button-primary" type="button" onClick={authenticated ? onOpenApp : onGetStarted}>
              {authenticated ? "Open dashboard" : "Start for free"}
            </button>
            <a className="button-secondary" href="#product">See how it works</a>
          </div>
          <small>Repository source is statically analyzed and never executed.</small>
        </div>

        <div className="product-preview" aria-label="Illustrative DriftGuard workflow preview">
          <div className="preview-toolbar">
            <span><i /><i /><i /></span>
            <small>Illustrative product workflow</small>
          </div>
          <div className="preview-header">
            <span className="preview-method">POST</span>
            <code>/payments</code>
            <span className="status-badge status-danger">BREAKING</span>
          </div>
          <div className="preview-grid">
            <article>
              <small>Contract drift</small>
              <strong>Required field changed</strong>
              <p><del>email</del> → <ins>customer_id</ins></p>
            </article>
            <article>
              <small>Code impact</small>
              <strong>Dependency trace</strong>
              <p><code>payment_client</code> → <code>checkout</code></p>
            </article>
            <article>
              <small>Review boundary</small>
              <strong>Static validation</strong>
              <p>Human confirmation required before a Pull Request.</p>
            </article>
          </div>
        </div>
      </section>

      <section className="landing-product" id="product">
        <header>
          <p className="landing-kicker">One bounded workflow</p>
          <h2>From contract drift to reviewable change.</h2>
        </header>
        <div className="landing-feature-grid">
          {[
            ["01", "Detect", "Compare real OpenAPI or GraphQL contract versions."],
            ["02", "Understand", "Locate direct, wrapper, and transitive source usages."],
            ["03", "Prepare", "Generate migration guidance and bounded patch proposals."],
            ["04", "Validate", "Run static contract, caller, scope, and test-gap checks."],
          ].map(([number, title, copy]) => (
            <article key={number}>
              <span>{number}</span>
              <h3>{title}</h3>
              <p>{copy}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="landing-security" id="security">
        <div>
          <p className="landing-kicker">Designed for review, not autonomous deployment</p>
          <h2>Your repository remains under your control.</h2>
        </div>
        <ul>
          <li>GitHub OAuth identifies the developer; the GitHub App authorizes repositories.</li>
          <li>Repository files are analyzed statically and are never executed.</li>
          <li>Patches are proposals only—no force push, automatic merge, or deployment.</li>
          <li>Workspace membership and tenant isolation are enforced by the API.</li>
        </ul>
      </section>
    </main>
  );
}
