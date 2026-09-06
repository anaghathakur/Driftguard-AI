import "../landing.css";

export function OnboardingPage({
  workspaceName,
  onConnectGitHub,
  onAnalyzeSpecification,
  onContinue,
}: {
  workspaceName: string;
  onConnectGitHub: () => void;
  onAnalyzeSpecification: () => void;
  onContinue: () => void;
}) {
  return (
    <main className="onboarding-page">
      <section className="onboarding-card">
        <div className="onboarding-brand"><span>DG</span><strong>DriftGuard AI</strong></div>
        <p className="landing-kicker">Workspace ready</p>
        <h1>Welcome to DriftGuard.</h1>
        <p>
          <strong>{workspaceName}</strong> has been created and isolated for your account.
          Choose the fastest way to your first real result.
        </p>
        <div className="onboarding-choices">
          <button type="button" onClick={onConnectGitHub}>
            <span aria-hidden="true">01</span>
            <strong>Connect GitHub</strong>
            <small>Authorize repositories through the DriftGuard GitHub App.</small>
          </button>
          <button type="button" onClick={onAnalyzeSpecification}>
            <span aria-hidden="true">02</span>
            <strong>Analyze API specifications</strong>
            <small>Upload real current and new OpenAPI or GraphQL contracts.</small>
          </button>
        </div>
        <button className="button-quiet onboarding-skip" type="button" onClick={onContinue}>
          Continue to empty dashboard
        </button>
      </section>
    </main>
  );
}
