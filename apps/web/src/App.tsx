import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";

import {
  analyzeConnectedRepositoryImpact,
  analyzeGitHubRepositoryImpact,
  analyzeRepositoryImpact,
  compareSpecifications,
  connectGitHubInstallation,
  createWorkspace,
  createPullRequest,
  generatePatchProposal,
  getAnalyses,
  getAuthStatus,
  logout,
  getGitHubInstallations,
  githubInstallationStartUrl,
  getAnalysisChanges,
  getAnalysisMatches,
  getAnalysisPdf,
  getAnalysisReport,
  getMigrationProviderStatus,
  getRepositoryConnections,
  getMigrationRecommendations,
  getMonitors,
  getPatchProposal,
  getPatchProposals,
  getPatchValidation,
  getPatchValidations,
  getReadinessStatus,
  getRiskPredictions,
  setRepositoryConnectionEnabled,
  switchWorkspace,
  syncGitHubInstallation,
  previewPullRequest,
  validatePatchProposal,
  type AnalysisHistoryItem,
  type AuthStatus,
  type GitHubInstallation,
  type ApiMonitor,
  type ApiChange,
  type ContractTypeSelection,
  type ComparisonResponse,
  type GitHubPullRequestRecord,
  type ImpactAnalysisResponse,
  type MigrationProviderStatus,
  type MigrationRecommendation,
  type PatchProposal,
  type PatchValidationRun,
  type PullRequestPreview,
  type ReadinessStatus,
  type PersistedMatch,
  type RepositoryConnection,
  type RepositoryMatch,
  type RiskPrediction,
} from "./lib/api";
import { AppShell, type AppPage } from "./components/AppShell";
import { OverviewPage } from "./pages/OverviewPage";
import { SystemStatusPage } from "./pages/SystemStatusPage";
import { NewAnalysisPage } from "./pages/NewAnalysisPage";
import { AnalysesPage } from "./pages/AnalysesPage";
import { MonitorsPage } from "./pages/MonitorsPage";
import {
  CreateWorkspacePage,
  SignInPage,
} from "./pages/AuthPages";
import { RepositoriesPage } from "./pages/RepositoriesPage";
import { TeamPage } from "./pages/TeamPage";
import { LandingPage } from "./pages/LandingPage";
import { OnboardingPage } from "./pages/OnboardingPage";
import {
  authenticationRedirectFor,
  developmentAuthAllowed,
} from "./lib/authRouting";
import "./result.css";

const DevelopmentAuth = import.meta.env.DEV
  ? lazy(() => import("./pages/DevelopmentAuth"))
  : null;

type AnalysisMode = "comparison" | "impact";
type RepositorySourceMode = "upload" | "github" | "connected";

const AUTH_SERVICE_UNREACHABLE =
  "DriftGuard could not reach the authentication service.";

type AnalysisResult =
  | {
      mode: "comparison";
      data: ComparisonResponse;
    }
  | {
      mode: "impact";
      data: ImpactAnalysisResponse;
    };

type AppProps = {
  initialAuthStatus?: AuthStatus | null;
  initialAuthResolved?: boolean;
};

export function App({
  initialAuthStatus = null,
  initialAuthResolved = false,
}: AppProps = {}) {
  const [currentPath, setCurrentPath] = useState(window.location.pathname);
  const [activePage, setActivePage] = useState<AppPage>(() =>
    pageFromPath(window.location.pathname),
  );
  const [mode, setMode] =
    useState<AnalysisMode>("comparison");
  const [oldSpec, setOldSpec] =
    useState<File | null>(null);
  const [newSpec, setNewSpec] =
    useState<File | null>(null);
  const [contractType, setContractType] =
    useState<ContractTypeSelection>("auto");
  const [repository, setRepository] =
    useState<File | null>(null);
  const [repositorySource, setRepositorySource] =
    useState<RepositorySourceMode>("upload");
  const [connectedRepositoryId, setConnectedRepositoryId] = useState("");
  const [repositoryUrl, setRepositoryUrl] =
    useState("");
  const [repositoryRef, setRepositoryRef] =
    useState("");

  const [providerStatus, setProviderStatus] =
    useState<MigrationProviderStatus | null>(null);
  const [readiness, setReadiness] =
    useState<ReadinessStatus | null>(null);
  const [backendError, setBackendError] =
    useState(false);

  const [isAnalyzing, setIsAnalyzing] =
    useState(false);
  const [analysisError, setAnalysisError] =
    useState<string | null>(null);
  const [analysisResult, setAnalysisResult] =
    useState<AnalysisResult | null>(null);

  const [risks, setRisks] =
    useState<RiskPrediction[]>([]);
  const [migrations, setMigrations] =
    useState<MigrationRecommendation[]>([]);
  const [isLoadingInsights, setIsLoadingInsights] =
    useState(false);
  const [insightError, setInsightError] =
    useState<string | null>(null);

  const [history, setHistory] =
    useState<AnalysisHistoryItem[]>([]);
  const [isLoadingHistory, setIsLoadingHistory] =
    useState(false);
  const [historyError, setHistoryError] =
    useState<string | null>(null);
  const [openingAnalysisId, setOpeningAnalysisId] =
    useState<string | null>(null);
  const [monitors, setMonitors] = useState<ApiMonitor[]>([]);
const [authStatus, setAuthStatus] = useState<AuthStatus | null>(initialAuthStatus);
  const [isLoadingAuth, setIsLoadingAuth] = useState(!initialAuthResolved);
  const [authError, setAuthError] = useState<string | null>(null);
  const [authRefreshKey, setAuthRefreshKey] = useState(0);
  const [workspaceName, setWorkspaceName] = useState("");
  const [workspaceBusy, setWorkspaceBusy] = useState(false);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const [installations, setInstallations] = useState<GitHubInstallation[]>([]);
  const [connectedRepositories, setConnectedRepositories] = useState<RepositoryConnection[]>([]);
  const [repositoriesLoading, setRepositoriesLoading] = useState(false);
  const [repositoriesError, setRepositoriesError] = useState<string | null>(null);
  const activeWorkspaceId =
    authStatus?.workspace?.id ?? (authStatus?.mode === "local" ? "local" : null);
  const activeWorkspaceRef = useRef<string | null>(activeWorkspaceId);
  activeWorkspaceRef.current = activeWorkspaceId;

  const loadHistory = useCallback(async () => {
    const workspaceId = activeWorkspaceRef.current;
    setIsLoadingHistory(true);
    setHistoryError(null);

    try {
      const items = await getAnalyses();
      if (activeWorkspaceRef.current === workspaceId) setHistory(items);
    } catch (error) {
      if (activeWorkspaceRef.current !== workspaceId) return;
      setHistory([]);
      setHistoryError(
        error instanceof Error
          ? error.message
          : "Saved analyses could not be loaded.",
      );
    } finally {
      if (activeWorkspaceRef.current === workspaceId) setIsLoadingHistory(false);
    }
  }, []);

  const activeRole = authStatus?.workspace?.role ?? "owner";
  const localMode = authStatus?.mode === "local";
  const canRunAnalyses = localMode || activeRole !== "viewer";
  const canManageWorkspaceResources = localMode || activeRole === "owner" || activeRole === "admin";

  const canAnalyze =
    !isAnalyzing &&
    canRunAnalyses &&
    oldSpec !== null &&
    newSpec !== null &&
    (mode === "comparison" ||
      (repositorySource === "upload"
        ? repository !== null
        : repositorySource === "connected"
          ? connectedRepositoryId.length > 0
          : repositoryUrl.trim().length > 0));

  const analysisRequirement =
    !canRunAnalyses
      ? "Your Viewer role can inspect analyses but cannot run a new analysis."
      : oldSpec === null || newSpec === null
      ? "Select both contract files to continue."
      : mode === "impact" && repositorySource === "upload" && repository === null
        ? "Select the repository ZIP to continue."
        : mode === "impact" && repositorySource === "connected" && !connectedRepositoryId
          ? "Select an authorized connected repository to continue."
        : mode === "impact" &&
            repositorySource === "github" &&
            repositoryUrl.trim().length === 0
          ? "Enter the public GitHub repository URL to continue."
          : "Inputs ready for secure analysis.";

  const analysisProgress =
    mode === "comparison"
      ? "Analyzing API changes..."
      : repositorySource === "connected"
        ? "Fetching authorized source files through the GitHub App..."
        : repositorySource === "github"
          ? "Fetching and scanning the public GitHub repository..."
        : "Scanning repository and building the dependency graph...";

useEffect(() => {
    if (initialAuthResolved) return;
    let active = true;
    setIsLoadingAuth(true);
    setAuthError(null);
    void getAuthStatus()
      .then((status) => {
        if (active) {
          setAuthStatus(status);
          setAuthError(null);
        }
      })
      .catch(() => {
        if (active) {
          setAuthStatus(null);
          setAuthError(AUTH_SERVICE_UNREACHABLE);
        }
      })
      .finally(() => { if (active) setIsLoadingAuth(false); });
    return () => { active = false; };
  }, [authRefreshKey, initialAuthResolved]);

  useEffect(() => {
    function handlePopState() {
      setCurrentPath(window.location.pathname);
      setActivePage(pageFromPath(window.location.pathname));
    }
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(() => {
    function handleSessionExpired() {
      setAuthStatus((status) => status ? {
        ...status,
        authenticated: false,
        user: null,
        workspace: null,
        workspaces: [],
        csrf_token: null,
      } : status);
      setAnalysisResult(null);
      setHistory([]);
      setMonitors([]);
      setInstallations([]);
      setConnectedRepositories([]);
      setAuthError("Your session expired. Sign in again to continue.");
      window.history.replaceState({}, "", "/login");
      setCurrentPath("/login");
      setActivePage("overview");
    }
    window.addEventListener("driftguard:session-expired", handleSessionExpired);
    return () => window.removeEventListener("driftguard:session-expired", handleSessionExpired);
  }, []);

  useEffect(() => {
    const redirect = authenticationRedirectFor(
      currentPath,
      authStatus,
      isLoadingAuth,
    );
    if (!redirect || redirect === currentPath) return;
    window.history.replaceState({}, "", redirect);
    setCurrentPath(redirect);
    setActivePage(pageFromPath(redirect));
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, [authStatus, currentPath, isLoadingAuth]);

  const loadRepositories = useCallback(async () => {
    const workspaceId = activeWorkspaceRef.current;
    setRepositoriesLoading(true);
    setRepositoriesError(null);
    try {
      const [installationItems, repositoryItems] = await Promise.all([
        getGitHubInstallations(), getRepositoryConnections(),
      ]);
      if (activeWorkspaceRef.current === workspaceId) {
        setInstallations(installationItems);
        setConnectedRepositories(repositoryItems);
      }
    } catch (error) {
      if (activeWorkspaceRef.current !== workspaceId) return;
      setRepositoriesError(error instanceof Error ? error.message : "Repositories could not be loaded.");
    } finally {
      if (activeWorkspaceRef.current === workspaceId) setRepositoriesLoading(false);
    }
  }, []);

  const loadMonitors = useCallback(async () => {
    const workspaceId = activeWorkspaceRef.current;
    try {
      const items = await getMonitors();
      if (activeWorkspaceRef.current === workspaceId) setMonitors(items);
    } catch {
      if (activeWorkspaceRef.current === workspaceId) setMonitors([]);
    }
  }, []);

  useEffect(() => {
    let active = true;

    async function loadBackendStatus() {
      try {
        const [status, ready] = await Promise.all([
          getMigrationProviderStatus(),
          getReadinessStatus(),
        ]);

        if (active) {
          setProviderStatus(status);
          setReadiness(ready);
          setBackendError(false);
        }
      } catch {
        if (active) {
          setProviderStatus(null);
          setReadiness(null);
          setBackendError(true);
        }
      }
    }

    void loadBackendStatus();

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!activeWorkspaceId) {
      setHistory([]);
      setMonitors([]);
      setInstallations([]);
      setConnectedRepositories([]);
      return;
    }
    void loadHistory();
    void loadMonitors();
    void loadRepositories();
  }, [activeWorkspaceId, loadHistory, loadMonitors, loadRepositories]);

  async function loadInsights(
    analysisId: string,
  ) {
    setIsLoadingInsights(true);
    setInsightError(null);

    try {
      const [riskData, migrationData] =
        await Promise.all([
          getRiskPredictions(analysisId),
          getMigrationRecommendations(analysisId),
        ]);

      setRisks(riskData);
      setMigrations(migrationData);
    } catch (error) {
      setRisks([]);
      setMigrations([]);
      setInsightError(
        error instanceof Error
          ? error.message
          : "Risk and migration details could not be loaded.",
      );
    } finally {
      setIsLoadingInsights(false);
    }
  }

  async function handleAnalyze() {
    if (!oldSpec || !newSpec) {
      setAnalysisError(
        "Select both contract files.",
      );
      return;
    }

    if (
      mode === "impact" &&
      repositorySource === "upload" &&
      !repository
    ) {
      setAnalysisError(
        "Select a repository ZIP file for impact analysis.",
      );
      return;
    }

    if (
      mode === "impact" &&
      repositorySource === "connected" &&
      !connectedRepositoryId
    ) {
      setAnalysisError("Select an authorized connected repository for impact analysis.");
      return;
    }
    if (
      mode === "impact" &&
      repositorySource === "github" &&
      !repositoryUrl.trim()
    ) {
      setAnalysisError(
        "Enter a public GitHub repository URL for impact analysis.",
      );
      return;
    }

    setIsAnalyzing(true);
    setAnalysisError(null);
    setAnalysisResult(null);
    setRisks([]);
    setMigrations([]);
    setInsightError(null);

    try {
      if (mode === "comparison") {
        const data = await compareSpecifications(
          oldSpec,
          newSpec,
          contractType,
        );

        setAnalysisResult({
          mode: "comparison",
          data,
        });
        handleNavigate("analysis-result");

        await loadInsights(data.analysis_id);
        void loadHistory();
      } else {
        const data = repositorySource === "upload"
          ? await analyzeRepositoryImpact(oldSpec, newSpec, repository as File, contractType)
          : repositorySource === "connected"
            ? await analyzeConnectedRepositoryImpact(oldSpec, newSpec, connectedRepositoryId, repositoryRef, contractType)
            : await analyzeGitHubRepositoryImpact(oldSpec, newSpec, repositoryUrl, repositoryRef, contractType);

        setAnalysisResult({
          mode: "impact",
          data,
        });
        handleNavigate("analysis-result");

        await loadInsights(data.analysis_id);
        void loadHistory();
      }
    } catch (error) {
      setAnalysisError(
        error instanceof Error
          ? error.message
          : "The analysis could not be completed.",
      );
    } finally {
      setIsAnalyzing(false);
    }
  }

  async function handleOpenAnalysis(
    item: AnalysisHistoryItem,
  ) {
    setOpeningAnalysisId(item.analysis_id);
    setAnalysisError(null);
    setInsightError(null);
    setRisks([]);
    setMigrations([]);

    try {
      const [
        changes,
        riskData,
        migrationData,
        matches,
      ] = await Promise.all([
        getAnalysisChanges(item.analysis_id),
        getRiskPredictions(item.analysis_id),
        getMigrationRecommendations(item.analysis_id),
        getAnalysisMatches(item.analysis_id),
      ]);

      const comparisonData =
        buildSavedComparison(item, changes);

      if (item.kind === "impact") {
        setAnalysisResult({
          mode: "impact",
          data: buildSavedImpact(
            item,
            comparisonData,
            matches,
          ),
        });
      } else {
        setAnalysisResult({
          mode: "comparison",
          data: comparisonData,
        });
      }

      setRisks(riskData);
      setMigrations(migrationData);
      handleNavigate("analysis-result");

      window.setTimeout(() => {
        document
          .getElementById("analysis-result")
          ?.scrollIntoView({
            behavior: "smooth",
            block: "start",
          });
      }, 0);
    } catch (error) {
      setHistoryError(
        error instanceof Error
          ? error.message
          : "The saved analysis could not be opened.",
      );
    } finally {
      setOpeningAnalysisId(null);
    }
  }

  async function handleViewAnalysis(analysisId: string) {
    try {
      const currentHistory = await getAnalyses();
      setHistory(currentHistory);
      const item = currentHistory.find(
        (analysis) => analysis.analysis_id === analysisId,
      );
      if (!item) {
        throw new Error("The monitor analysis could not be found in history.");
      }
      await handleOpenAnalysis(item);
    } catch (error) {
      setHistoryError(
        error instanceof Error
          ? error.message
          : "The monitor analysis could not be opened.",
      );
    }
  }

  const comparison =
    analysisResult?.mode === "comparison"
      ? analysisResult.data
      : analysisResult?.data.comparison;

  const analysisId =
    analysisResult?.data.analysis_id ?? null;

  function handleNavigate(page: AppPage) {
    const path = pagePath(page);
    if (window.location.pathname !== path) window.history.pushState({}, "", path);
    setCurrentPath(path);
    setActivePage(page);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function navigateTo(path: string, replace = false) {
    if (replace) window.history.replaceState({}, "", path);
    else if (window.location.pathname !== path) window.history.pushState({}, "", path);
    setCurrentPath(path);
    setActivePage(pageFromPath(path));
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

async function handleCreateWorkspace() {
    setWorkspaceBusy(true); setWorkspaceError(null);
    try { await createWorkspace(workspaceName); setAuthStatus(await getAuthStatus()); }
    catch (error) { setWorkspaceError(error instanceof Error ? error.message : "Workspace could not be created."); }
    finally { setWorkspaceBusy(false); }
  }

  async function handleSwitchWorkspace(workspaceId: string) {
    activeWorkspaceRef.current = workspaceId;
    setAnalysisResult(null);
    setRisks([]);
    setMigrations([]);
    setHistory([]);
    setMonitors([]);
    setInstallations([]);
    setConnectedRepositories([]);
    setConnectedRepositoryId("");
    await switchWorkspace(workspaceId);
    setAuthStatus(await getAuthStatus());
    handleNavigate("overview");
  }


  async function handleLogout() {
    await logout();
    setAuthStatus(await getAuthStatus());
    setAnalysisResult(null);
    setHistory([]);
    setMonitors([]);
    navigateTo("/", true);
  }
  async function handleConnectDevelopmentInstallation() {
    setRepositoriesLoading(true); setRepositoriesError(null);
    try { await connectGitHubInstallation(1); await loadRepositories(); }
    catch (error) { setRepositoriesError(error instanceof Error ? error.message : "Installation could not be connected."); }
    finally { setRepositoriesLoading(false); }
  }

  async function handleSyncInstallation(installationId: string) {
    setRepositoriesLoading(true); setRepositoriesError(null);
    try { await syncGitHubInstallation(installationId); await loadRepositories(); }
    catch (error) { setRepositoriesError(error instanceof Error ? error.message : "Repositories could not be synchronized."); }
    finally { setRepositoriesLoading(false); }
  }

  async function handleToggleRepository(item: RepositoryConnection) {
    try { await setRepositoryConnectionEnabled(item.id, !item.enabled); await loadRepositories(); }
    catch (error) { setRepositoriesError(error instanceof Error ? error.message : "Repository state could not be updated."); }
  }

  const authenticated = Boolean(authStatus?.authenticated);
  const developmentAuthEnabled = developmentAuthAllowed(
    import.meta.env.DEV,
    authStatus,
  );
  const developmentContent = developmentAuthEnabled && DevelopmentAuth
    ? <Suspense fallback={<small>Loading development identities…</small>}><DevelopmentAuth /></Suspense>
    : undefined;
  const authPageProps = {
    githubConfigured: Boolean(authStatus?.github_auth_configured),
    googleConfigured: Boolean(authStatus?.google_auth_configured),
    developmentContent,
    message: authError,
    onRetry: authError === AUTH_SERVICE_UNREACHABLE
      ? () => setAuthRefreshKey((value) => value + 1)
      : undefined,
    onHome: () => navigateTo("/"),
  };

  if (currentPath === "/") {
    return (
      <LandingPage
        authenticated={authenticated}
        onGetStarted={() => navigateTo("/signup")}
        onSignIn={() => navigateTo("/login")}
        onOpenApp={() => navigateTo("/app")}
      />
    );
  }
  if (isLoadingAuth) {
    return <main className="auth-page"><div className="empty-state">Loading account…</div></main>;
  }
  if (currentPath === "/login" || currentPath === "/signup") {
    if (authenticated) {
      return <main className="auth-page"><div role="status" className="empty-state">Opening dashboard…</div></main>;
    }
    return <SignInPage {...authPageProps} signup={currentPath === "/signup"} />;
  }
  if (currentPath === "/dev/login") {
    if (developmentAuthEnabled && DevelopmentAuth) {
      return <Suspense fallback={<main className="auth-page"><div className="empty-state">Loading development identities…</div></main>}><DevelopmentAuth standalone onBack={() => navigateTo("/login")} /></Suspense>;
    }
    return <SignInPage {...authPageProps} message="Development identities are unavailable in this environment." />;
  }
  if (!currentPath.startsWith("/app")) {
    return (
      <LandingPage
        authenticated={authenticated}
        onGetStarted={() => navigateTo("/signup")}
        onSignIn={() => navigateTo("/login")}
        onOpenApp={() => navigateTo("/app")}
      />
    );
  }
  if (authStatus?.mode === "github" && !authStatus.authenticated) {
    return <SignInPage {...authPageProps} message="Sign in to access the DriftGuard application." />;
  }
  if (authStatus?.mode === "github" && !authStatus.workspace) return <CreateWorkspacePage name={workspaceName} error={workspaceError} busy={workspaceBusy} onNameChange={setWorkspaceName} onSubmit={() => void handleCreateWorkspace()} />;
  if (currentPath === "/app/onboarding") {
    return (
      <OnboardingPage
        workspaceName={authStatus?.workspace?.name ?? "Your workspace"}
        onConnectGitHub={() => handleNavigate("repositories")}
        onAnalyzeSpecification={() => handleNavigate("new-analysis")}
        onContinue={() => handleNavigate("overview")}
      />
    );
  }

  return (
    <AppShell
      activePage={activePage}
      backendReady={backendError ? false : readiness ? readiness.status === "ready" : null}
      onNavigate={handleNavigate}
      workspaceLabel={authStatus?.workspace?.name ?? "Local workspace"}
      userLabel={authStatus?.user?.github_display_name ?? authStatus?.user?.github_login}
      workspaces={authStatus?.workspaces ?? []}
      activeWorkspaceId={authStatus?.workspace?.id}
      onSwitchWorkspace={(id) => void handleSwitchWorkspace(id)}
      roleLabel={authStatus?.workspace?.role}
      onLogout={authStatus?.mode === "github" ? () => void handleLogout() : undefined}
    >
      <div id="dashboard" className="scroll-mt-6">
        {activePage === "overview" && (
          <OverviewPage
            analyses={history}
            monitors={monitors}
            repositories={connectedRepositories}
            isLoading={isLoadingHistory}
            error={historyError}
            openingAnalysisId={openingAnalysisId}
            onNavigateToAnalysis={() => handleNavigate("new-analysis")}
            onNavigateToMonitors={() => handleNavigate("monitors")}
            onNavigateToRepositories={() => handleNavigate("repositories")}
            onOpenAnalysis={(item) => void handleOpenAnalysis(item)}
          />
        )}
        {activePage === "new-analysis" && (
          <NewAnalysisPage
            mode={mode}
            setMode={setMode}
            oldSpec={oldSpec}
            setOldSpec={setOldSpec}
            newSpec={newSpec}
            setNewSpec={setNewSpec}
            repository={repository}
            contractType={contractType}
            setContractType={setContractType}
            setRepository={setRepository}
            repositorySource={repositorySource}
            setRepositorySource={setRepositorySource}
            connectedRepositories={connectedRepositories.filter((item) => item.enabled && !item.removed)}
            connectedRepositoryId={connectedRepositoryId}
            setConnectedRepositoryId={setConnectedRepositoryId}
            repositoryUrl={repositoryUrl}
            setRepositoryUrl={setRepositoryUrl}
            repositoryRef={repositoryRef}
            setRepositoryRef={setRepositoryRef}
            isAnalyzing={isAnalyzing}
            analysisError={analysisError}
            canAnalyze={canAnalyze}
            analysisRequirement={analysisRequirement}
            analysisProgress={analysisProgress}
            onAnalyze={() => void handleAnalyze()}
          />
        )}

        {activePage === "analysis-result" && analysisResult && comparison && (
          <AnalysisResultPanel
            result={analysisResult}
            comparison={comparison}
            analysisId={analysisId}
            canMutate={canRunAnalyses}
            risks={risks}
            migrations={migrations}
            isLoadingInsights={isLoadingInsights}
            insightError={insightError}
          />
        )}

        {activePage === "monitors" && <MonitorsPage
          onViewAnalysis={(monitorAnalysisId) =>
            void handleViewAnalysis(monitorAnalysisId)
          }
          onMonitorsChanged={setMonitors}
          canManage={canManageWorkspaceResources}
          canCheck={canRunAnalyses}
        />}

        {activePage === "analyses" && <AnalysesPage
          analyses={history}
          isLoading={isLoadingHistory}
          error={historyError}
          openingAnalysisId={openingAnalysisId}
          onRefresh={() => void loadHistory()}
          onOpen={(item) =>
            void handleOpenAnalysis(item)
          }
        />}

        {activePage === "repositories" && <RepositoriesPage
          installations={installations}
          repositories={connectedRepositories}
          loading={repositoriesLoading}
          error={repositoriesError}
          installUrl={readiness?.checks.github_write_provider === "github_app" ? githubInstallationStartUrl() : null}
          developmentMode={developmentAuthEnabled && readiness?.checks.github_write_provider === "mock"}
          canManage={canManageWorkspaceResources}
          canAnalyze={canRunAnalyses}
          onConnectMock={() => void handleConnectDevelopmentInstallation()}
          onSync={(id) => void handleSyncInstallation(id)}
          onToggle={(item) => void handleToggleRepository(item)}
          onAnalyze={(item) => { setMode("impact"); setRepositorySource("connected"); setConnectedRepositoryId(item.id); handleNavigate("new-analysis"); }}
        />}
        {activePage === "team" && authStatus && (
          <TeamPage
            key={authStatus.workspace?.id ?? authStatus.mode}
            auth={authStatus}
            onLogout={handleLogout}
          />
        )}
        {activePage === "system-status" && (
          <SystemStatusPage
            backendError={backendError}
            providerStatus={providerStatus}
            readiness={readiness}
          />
        )}
      </div>
    </AppShell>
  );
}

function buildSavedComparison(
  item: AnalysisHistoryItem,
  changes: ApiChange[],
): ComparisonResponse {
  const breakingChanges = changes.filter(
    (change) => change.breaking,
  ).length;

  return {
    analysis_id: item.analysis_id,
    duplicate: false,
    summary: {
      total_changes: changes.length,
      breaking_changes: breakingChanges,
      non_breaking_changes:
        changes.length - breakingChanges,
    },
    changes,
  };
}

function buildSavedImpact(
  item: AnalysisHistoryItem,
  comparison: ComparisonResponse,
  matches: PersistedMatch[],
): ImpactAnalysisResponse {
  const matchesByChange = new Map<
    string,
    PersistedMatch[]
  >();

  for (const change of comparison.changes) {
    matchesByChange.set(change.change_id, []);
  }

  for (const match of matches) {
    const existing =
      matchesByChange.get(match.change_id) ?? [];
    existing.push(match);
    matchesByChange.set(match.change_id, existing);
  }

  const impactedFiles = new Set(
    matches.map((match) => match.file_path),
  );
  const impactedChanges = new Set(
    matches.map((match) => match.change_id),
  );

  return {
    analysis_id: item.analysis_id,
    duplicate: false,
    comparison,
    repository: {
      archive_sha256: "",
      archive_entries: 0,
      scanned_files: impactedFiles.size,
      scanned_bytes: 0,
      skipped_files: 0,
      skipped_reasons: {},
    },
    impact_summary: {
      total_changes: comparison.summary.total_changes,
      impacted_changes: impactedChanges.size,
      impacted_files: impactedFiles.size,
      total_matches: matches.length,
    },
    impacts: comparison.changes.map((change) => ({
      change_id: change.change_id,
      matches:
        matchesByChange.get(change.change_id) ?? [],
    })),
  };
}

type AnalysisResultPanelProps = {
  result: AnalysisResult;
  comparison: ComparisonResponse;
  analysisId: string | null;
  canMutate: boolean;
  risks: RiskPrediction[];
  migrations: MigrationRecommendation[];
  isLoadingInsights: boolean;
  insightError: string | null;
};

function AnalysisResultPanel({
  result,
  comparison,
  analysisId,
  canMutate,
  risks,
  migrations,
  isLoadingInsights,
  insightError,
}: AnalysisResultPanelProps) {
  const impactSummary =
    result.mode === "impact"
      ? result.data.impact_summary
      : null;

  const repositoryMatches =
    result.mode === "impact"
      ? result.data.impacts.flatMap((impact) => impact.matches)
      : [];
  const directUsages = repositoryMatches.filter(
    (match) => (match.impact_depth ?? 0) === 0,
  ).length;
  const transitiveCallers = repositoryMatches.length - directUsages;
  const primaryChange = comparison.changes[0];
  const highestRisk = [...risks].sort((left, right) => right.risk_score - left.risk_score)[0];
  const resultTitle = primaryChange
    ? `${primaryChange.operation_identifier || `${primaryChange.method.toUpperCase()} ${primaryChange.path}`.trim()} migration`
    : "API contract analysis";
  const resultClassification = comparison.summary.breaking_changes > 0
    ? "BREAKING"
    : "NON-BREAKING";
  const [isDownloadingReport, setIsDownloadingReport] =
    useState(false);
  const [isDownloadingPdf, setIsDownloadingPdf] =
    useState(false);
  const [reportError, setReportError] =
    useState<string | null>(null);

  async function handleDownloadReport() {
    if (!analysisId || isDownloadingReport) {
      return;
    }

    setIsDownloadingReport(true);
    setReportError(null);

    try {
      const report =
        await getAnalysisReport(analysisId);
      const json = JSON.stringify(
        report,
        null,
        2,
      );
      const blob = new Blob([json], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");

      link.href = url;
      link.download =
        `driftguard-analysis-${analysisId}.json`;

      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      setReportError(
        error instanceof Error
          ? error.message
          : "The report could not be downloaded.",
      );
    } finally {
      setIsDownloadingReport(false);
    }
  }

  async function handleDownloadPdf() {
    if (!analysisId || isDownloadingPdf) {
      return;
    }

    setIsDownloadingPdf(true);
    setReportError(null);

    try {
      const blob = await getAnalysisPdf(analysisId);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");

      link.href = url;
      link.download =
        `driftguard-analysis-${analysisId}.pdf`;

      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      setReportError(
        error instanceof Error
          ? error.message
          : "The PDF report could not be downloaded.",
      );
    } finally {
      setIsDownloadingPdf(false);
    }
  }

  return (
    <section
      id="analysis-result"
      className="mt-8 scroll-mt-6 rounded-2xl border border-cyan-400/20 bg-white/5 p-6 shadow-xl shadow-cyan-950/20 backdrop-blur-xl"
    >
      <div className="result-header">
        <div>
          <div className="result-heading-badges">
            <span className={comparison.summary.breaking_changes > 0 ? "status-badge status-badge-danger" : "status-badge status-badge-success"}>{resultClassification}</span>
            {highestRisk && (
              <span className={`status-badge ${highestRisk.risk_level === "low" ? "status-badge-success" : highestRisk.risk_level === "medium" ? "status-badge-warning" : "status-badge-danger"}`}>
                {highestRisk.risk_level.toUpperCase()} RISK
              </span>
            )}
          </div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">
            {result.mode === "impact" ? "Repository impact analysis" : "Contract comparison"}
          </p>
          <h1 className="result-title">{resultTitle}</h1>
          <p className="result-source">
            <span>{result.mode === "impact" ? "Static repository analysis" : "No repository supplied"}</span>
            {analysisId && <code>{analysisId}</code>}
          </p>
        </div>

        {analysisId && (
          <div className="result-actions">
            <button
              type="button"
              onClick={handleDownloadReport}
              disabled={isDownloadingReport}
              className="button-secondary"
            >
              {isDownloadingReport
                ? "Preparing report..."
                : "Download JSON"}
            </button>

            <button
              type="button"
              onClick={handleDownloadPdf}
              disabled={isDownloadingPdf}
              className="button-secondary"
            >
              {isDownloadingPdf
                ? "Preparing PDF..."
                : "Download PDF"}
            </button>

            <code className="max-w-full truncate rounded-lg border border-white/10 bg-black/25 px-3 py-2 text-xs text-slate-400">
              {analysisId}
            </code>
          </div>
        )}
      </div>

      {reportError && (
        <div className="mt-5 rounded-xl border border-rose-400/20 bg-rose-400/10 p-4 text-sm text-rose-100">
          Report download failed: {reportError}
        </div>
      )}

      <div id="analysis-summary" className="result-summary-label">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">
          Summary
        </p>
      </div>
      <div className="result-metrics">
        <ResultMetric
          label="Breaking changes"
          value={comparison.summary.breaking_changes}
          danger={comparison.summary.breaking_changes > 0}
        />
        <ResultMetric
          label="Impacted files"
          value={impactSummary?.impacted_files ?? 0}
        />
        <ResultMetric
          label="Direct usages"
          value={directUsages}
        />
        <ResultMetric
          label="Transitive callers"
          value={transitiveCallers}
        />
      </div>

      {isLoadingInsights && (
        <div className="mt-6 rounded-xl border border-cyan-400/20 bg-cyan-400/10 p-4 text-sm text-cyan-100">
          Loading ML risk and migration guidance...
        </div>
      )}

      {insightError && (
        <div className="mt-6 rounded-xl border border-amber-400/20 bg-amber-400/10 p-4 text-sm text-amber-100">
          The comparison completed, but insights could not
          be loaded: {insightError}
        </div>
      )}

      <section id="change-intelligence" className="mt-8 scroll-mt-28">
        <div className="mb-4">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-emerald-300">
            API change · deep code impact · migration
          </p>
          <h4 className="mt-2 text-lg font-semibold text-white">
            Understand what changed and where it propagates
          </h4>
        </div>
        <div className="result-change-list">
        {comparison.changes.length === 0 ? (
          <div className="rounded-xl border border-emerald-400/20 bg-emerald-400/10 p-4 text-sm text-emerald-200">
            No API contract changes were detected.
          </div>
        ) : (
          comparison.changes.map((change) => {
            const matches =
              result.mode === "impact"
                ? result.data.impacts.find(
                    (impact) =>
                      impact.change_id ===
                      change.change_id,
                  )?.matches ?? []
                : undefined;

            return (
              <ChangeRow
                key={change.change_id}
                change={change}
                matches={matches}
                risk={risks.find(
                  (item) =>
                    item.change_id === change.change_id,
                )}
                migration={migrations.find(
                  (item) =>
                    item.change_id === change.change_id,
                )}
              />
            );
          })
        )}
        </div>
      </section>

      {result.mode === "impact" && analysisId && (
        <PatchProposalPanel analysisId={analysisId} canMutate={canMutate} />
      )}
    </section>
  );
}

function PatchProposalPanel({
  analysisId,
  canMutate,
}: {
  analysisId: string;
  canMutate: boolean;
}) {
  const [repositoryZip, setRepositoryZip] =
    useState<File | null>(null);
  const [proposal, setProposal] =
    useState<PatchProposal | null>(null);
  const [isGenerating, setIsGenerating] =
    useState(false);
  const [patchError, setPatchError] =
    useState<string | null>(null);
  const [validation, setValidation] =
    useState<PatchValidationRun | null>(null);
  const [isValidating, setIsValidating] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setProposal(null);
    setValidation(null);
    setPatchError(null);
    void getPatchProposals(analysisId)
      .then(async (items) => {
        if (!active || items.length === 0) return;
        const existing = await getPatchProposal(
          analysisId,
          items[0].patch_id,
        );
        if (active) setProposal(existing);
        const validations = await getPatchValidations(analysisId, existing.patch_id);
        if (!active || validations.length === 0) return;
        const detail = await getPatchValidation(
          analysisId,
          existing.patch_id,
          validations[0].validation_id,
        );
        if (active) setValidation(detail);
      })
      .catch(() => {
        // An absent proposal should not obscure a completed analysis.
      });
    return () => {
      active = false;
    };
  }, [analysisId]);

  async function handleGeneratePatch() {
    if (!canMutate || isGenerating) return;
    setIsGenerating(true);
    setPatchError(null);
    try {
      setProposal(
        await generatePatchProposal(
          analysisId,
          repositoryZip,
        ),
      );
    } catch (error) {
      setPatchError(
        error instanceof Error
          ? error.message
          : "No safe proposed patch could be generated.",
      );
    } finally {
      setIsGenerating(false);
    }
  }

  async function handleValidatePatch() {
    if (!canMutate || !proposal || isValidating) return;
    setIsValidating(true);
    setValidationError(null);
    try {
      setValidation(
        await validatePatchProposal(
          analysisId,
          proposal.patch_id,
          repositoryZip,
        ),
      );
    } catch (error) {
      setValidationError(
        error instanceof Error
          ? error.message
          : "The proposed patch could not be statically validated.",
      );
    } finally {
      setIsValidating(false);
    }
  }

  const validationChecks = proposal
    ? [
        ["Source snapshot verified", proposal.validation.source_snapshot_verified],
        ["Allowed files verified", proposal.validation.allowed_scope_verified],
        ["Edit anchors verified", proposal.validation.edit_anchors_verified],
        ["Syntax valid", proposal.validation.syntax_valid],
        ["Within safety limits", proposal.validation.limits_valid],
      ] as const
    : [];

  return (
    <section id="proposed-patch" className="mt-8 scroll-mt-28 rounded-xl border border-violet-400/20 bg-violet-400/5 p-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-violet-300">
            Proposed patch
          </p>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-300">
            GitHub analyses securely re-fetch their source. ZIP analyses require
            the exact original archive before DriftGuard can generate a review-only diff.
          </p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
          <label className="text-xs text-slate-400">
            Original ZIP, when required
            <input
              type="file"
              accept=".zip,application/zip"
              disabled={!canMutate || isGenerating}
              onChange={(event) =>
                setRepositoryZip(event.target.files?.[0] ?? null)
              }
              className="mt-1 block max-w-xs rounded-lg border border-white/10 bg-black/25 px-3 py-2 text-xs text-slate-300 file:mr-3 file:rounded file:border-0 file:bg-violet-400/15 file:px-2 file:py-1 file:text-violet-200"
            />
          </label>
          <button
            type="button"
            onClick={() => void handleGeneratePatch()}
            disabled={!canMutate || isGenerating}
            title={!canMutate ? "Viewer access is read-only." : undefined}
            className="rounded-lg bg-violet-400 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-violet-300 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isGenerating ? "Generating safely..." : "Generate proposed patch"}
          </button>
        </div>
      </div>

      {!canMutate && (
        <div className="mt-4 rounded-lg border border-amber-400/20 bg-amber-400/10 p-3 text-sm text-amber-100">
          Your Viewer role can inspect existing proposals and validation results, but cannot generate or validate patches.
        </div>
      )}

      {patchError && (
        <div role="alert" className="mt-4 rounded-lg border border-rose-400/20 bg-rose-400/10 p-3 text-sm text-rose-100">
          {patchError}
        </div>
      )}

      {!proposal && !patchError && (
        <div role="status" className="mt-4 rounded-lg border border-dashed border-white/10 bg-black/15 p-4 text-sm text-slate-400">
          {isGenerating
            ? "Generating a bounded proposed patch..."
            : "No patch proposal generated yet. Analysis results remain unchanged until you explicitly request one."}
        </div>
      )}

      {proposal && (
        <div className="mt-5 space-y-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <ImpactMetric label="Files changed" value={proposal.files_changed} />
            <ImpactMetric label="Structured edits" value={proposal.edit_count} />
            <ImpactMetric label="Status" value={proposal.status} />
          </div>
          <div className="rounded-lg border border-emerald-400/20 bg-emerald-400/10 p-4">
            <p className="font-semibold text-emerald-100">{proposal.summary}</p>
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              {validationChecks.map(([label, passed]) => (
                <p key={label} className="text-sm text-emerald-200">
                  {passed ? "✓" : "×"} {label}
                </p>
              ))}
            </div>
          </div>
          <div className="rounded-lg border border-amber-400/25 bg-amber-400/10 p-3 text-sm font-semibold text-amber-100">
            No repository files have been modified. This diff is for developer review only.
          </div>
          <div className="rounded-lg border border-cyan-400/20 bg-cyan-400/5 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">
                  Patch validation &amp; test intelligence
                </p>
                <p className="mt-1 text-xs text-slate-400">
                  Runs bounded static checks and executes only allowlisted project commands
                  when a validation runner is configured.
                </p>
              </div>
              <button
                type="button"
                onClick={() => void handleValidatePatch()}
                disabled={!canMutate || isValidating}
                title={!canMutate ? "Viewer access is read-only." : undefined}
                className="rounded-lg bg-cyan-300 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-cyan-200 disabled:opacity-60"
              >
                {isValidating ? "Validating statically..." : "Validate patch"}
              </button>
            </div>
            {validationError && (
              <p role="alert" className="mt-3 rounded border border-rose-400/20 bg-rose-400/10 p-3 text-sm text-rose-100">
                {validationError}
              </p>
            )}
            {validation && (
              <PatchValidationPanel
                key={validation.validation_id}
                analysisId={analysisId}
                patchId={proposal.patch_id}
                validation={validation}
                canCreatePullRequest={canMutate}
              />
            )}
          </div>
          <div className="patch-diff">
            <div className="border-b border-white/10 px-4 py-3 text-xs text-slate-400">
              Trusted unified diff · {proposal.provider} / {proposal.provider_model}
            </div>
            <pre className="max-h-[34rem] overflow-auto p-4 text-xs leading-5">
              {proposal.unified_diff.split("\n").map((line, index) => (
                <code
                  key={`${index}-${line}`}
                  className={`block whitespace-pre ${diffLineClass(line)}`}
                >
                  {line || " "}
                </code>
              ))}
            </pre>
          </div>
          {proposal.warnings.length > 0 && (
            <ul className="space-y-1 text-xs text-amber-200">
              {proposal.warnings.map((warning) => (
                <li key={warning}>• {warning}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

function PatchValidationPanel({
  analysisId,
  patchId,
  validation,
  canCreatePullRequest,
}: {
  analysisId: string;
  patchId: string;
  validation: PatchValidationRun;
  canCreatePullRequest: boolean;
}) {
  const [preview, setPreview] = useState<PullRequestPreview | null>(null);
  const [pullRequest, setPullRequest] =
    useState<GitHubPullRequestRecord | null>(null);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [pullRequestError, setPullRequestError] = useState<string | null>(null);
  const readinessLabel = validation.readiness.replaceAll("_", " ").toUpperCase();
  const readinessClass =
    validation.readiness === "ready_for_review"
      ? "text-emerald-200 border-emerald-400/25 bg-emerald-400/10"
      : validation.readiness === "blocked"
        ? "text-rose-200 border-rose-400/25 bg-rose-400/10"
        : "text-amber-100 border-amber-400/25 bg-amber-400/10";
  return (
    <div className="mt-4 space-y-4">
      <div className={`rounded-lg border p-4 ${readinessClass}`}>
        <p className="text-lg font-bold">{readinessLabel}</p>
        <p className="mt-1 text-xs">
          {validation.passed_count} passed · {validation.warning_count} warnings ·{" "}
          {validation.failed_count} failed · {validation.unknown_count} unknown
        </p>
      </div>
      {validation.execution && (
        <div className="rounded-lg border border-white/10 bg-black/20 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-semibold text-slate-100">Test &amp; build execution</p>
            <span className="rounded border border-white/15 px-2 py-1 text-[11px] font-semibold uppercase text-slate-300">
              {validation.execution.status.replaceAll("_", " ")}
            </span>
          </div>
          <p className="mt-2 text-xs leading-5 text-slate-400">
            {validation.execution.message}
          </p>
          {validation.execution.commands.length > 0 && (
            <div className="mt-3 space-y-2">
              {validation.execution.commands.map((command) => (
                <div key={`${command.category}-${command.display_name}`} className="rounded border border-white/10 bg-black/20 p-3 text-xs">
                  <p className="font-semibold text-slate-200">
                    {command.display_name} · {command.timed_out ? "timed out" : `exit ${command.exit_code}`}
                  </p>
                  <code className="mt-1 block overflow-x-auto whitespace-pre text-slate-500">
                    {command.argv.join(" ")}
                  </code>
                </div>
              ))}
            </div>
          )}
          <p className="mt-3 text-[11px] text-amber-200">
            {validation.execution.commands.length > 0
              ? "Commands ran in a disposable copy; runtime isolation is deployment-dependent."
              : "Static validation completed, but repository tests were not executed."}
          </p>
        </div>
      )}
      <div className="rounded-lg border border-violet-400/20 bg-violet-400/5 p-4">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-violet-300">
          GitHub pull request
        </p>
        {validation.readiness === "needs_review" && (
          <p className="mt-2 text-sm text-amber-100">
            Resolve validation warnings before creating a pull request.
          </p>
        )}
        {validation.readiness === "blocked" && (
          <p className="mt-2 text-sm text-rose-200">
            Patch is blocked and cannot create a pull request.
          </p>
        )}
        {validation.readiness === "ready_for_review" && !preview && !pullRequest && (
          <div className="mt-3">
            <p className="text-sm leading-6 text-slate-300">
              DriftGuard will reverify the exact repository snapshot and validated patch
              before any GitHub write.
            </p>
            <button
              type="button"
              onClick={() => {
                if (!canCreatePullRequest || isPreviewing) return;
                setIsPreviewing(true);
                setPullRequestError(null);
                void previewPullRequest(
                  analysisId,
                  patchId,
                  validation.validation_id,
                )
                  .then(setPreview)
                  .catch((error: unknown) => {
                    setPullRequestError(
                      error instanceof Error
                        ? error.message
                        : "The pull request could not be prepared safely.",
                    );
                  })
                  .finally(() => setIsPreviewing(false));
              }}
              disabled={!canCreatePullRequest || isPreviewing}
              title={!canCreatePullRequest ? "Viewer access is read-only." : undefined}
              className="mt-3 rounded-lg bg-violet-300 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-violet-200 disabled:cursor-wait disabled:opacity-60"
            >
              {isPreviewing ? "Reverifying source..." : "Preview Pull Request"}
            </button>
          </div>
        )}
        {preview && !pullRequest && (
          <div className="mt-4 rounded-lg border border-cyan-400/20 bg-black/20 p-4">
            <p className="font-semibold text-white">Create Pull Request?</p>
            <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
              <ConfirmationItem
                label="Repository"
                value={`${preview.repository_owner}/${preview.repository_name}`}
              />
              <ConfirmationItem
                label="Base"
                value={`${preview.base_ref} @ ${preview.base_commit_sha.slice(0, 12)}`}
              />
              <ConfirmationItem label="New branch" value={preview.branch_name} />
              <ConfirmationItem
                label="Patch"
                value={`${preview.files_changed} file · ${preview.edit_count} edits`}
              />
              <ConfirmationItem label="Validation" value="READY FOR REVIEW" />
              <ConfirmationItem
                label="Tests"
                value={preview.tests_executed ? "Executed in validation copy" : "Not executed"}
              />
            </dl>
            <div className="mt-4 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => {
                  if (!canCreatePullRequest || isCreating) return;
                  setIsCreating(true);
                  setPullRequestError(null);
                  void createPullRequest(
                    analysisId,
                    patchId,
                    validation.validation_id,
                  )
                    .then(setPullRequest)
                    .catch((error: unknown) => {
                      setPullRequestError(
                        error instanceof Error
                          ? error.message
                          : "GitHub could not create the pull request safely.",
                      );
                    })
                    .finally(() => setIsCreating(false));
                }}
                disabled={!canCreatePullRequest || isCreating}
                className="rounded-lg bg-cyan-300 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-cyan-200 disabled:cursor-wait disabled:opacity-60"
              >
                {isCreating ? "Creating review branch..." : "Create Pull Request"}
              </button>
              <button
                type="button"
                onClick={() => setPreview(null)}
                disabled={isCreating}
                className="rounded-lg border border-white/15 px-4 py-2 text-sm text-slate-300 transition hover:bg-white/5 disabled:opacity-60"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
        {pullRequest && (
          <div className="mt-4 rounded-lg border border-emerald-400/25 bg-emerald-400/10 p-4">
            <p className="font-semibold text-emerald-100">Pull Request Created</p>
            <p className="mt-2 text-sm text-emerald-200">
              PR #{pullRequest.pull_request_number} · {pullRequest.repository_owner}/
              {pullRequest.repository_name}
            </p>
            <p className="mt-1 break-all text-xs text-slate-300">
              Branch: {pullRequest.branch_name} · Commit: {pullRequest.commit_sha?.slice(0, 12)}
            </p>
            {pullRequest.pull_request_url && (
              <a
                href={pullRequest.pull_request_url}
                target="_blank"
                rel="noreferrer"
                className="mt-3 inline-flex text-sm font-semibold text-cyan-200 underline decoration-cyan-400/40 underline-offset-4 hover:text-cyan-100"
              >
                Open GitHub Pull Request
              </a>
            )}
            <p className="mt-3 text-xs leading-5 text-slate-300">
              DriftGuard created a review branch and pull request. It did not merge or
              deploy the change. {pullRequest.tests_executed
                ? "Allowlisted validation commands were executed before review."
                : "Repository tests were not executed."}
            </p>
          </div>
        )}
        {pullRequestError && (
          <p className="mt-3 rounded border border-rose-400/20 bg-rose-400/10 p-3 text-sm text-rose-100">
            {pullRequestError}
          </p>
        )}
      </div>
      <ValidationFindingGroup title="Contract Checks" findings={validation.contract_findings} />
      <ValidationFindingGroup title="Caller Consistency" findings={validation.dependency_findings.filter((finding) => finding.category !== "patch_scope")} />
      <ValidationFindingGroup title="Scope Validation" findings={validation.dependency_findings.filter((finding) => finding.category === "patch_scope")} />
      <div>
        <p className="text-sm font-semibold text-slate-100">
          Related tests · {validation.related_tests.length} discovered
        </p>
        <div className="mt-2 grid gap-2 md:grid-cols-2">
          {validation.related_tests.map((test) => (
            <div key={test.file_path} className="rounded border border-white/10 bg-black/20 p-3">
              <p className="break-all text-xs font-semibold text-cyan-100">{test.file_path}</p>
              <p className="mt-1 text-[11px] uppercase text-cyan-300">{test.relevance} relevance</p>
              <p className="mt-1 text-xs text-slate-400">{test.reasons.join(" ")}</p>
            </div>
          ))}
        </div>
      </div>
      {validation.test_gaps.length > 0 && (
        <div>
          <p className="text-sm font-semibold text-amber-100">Test gaps</p>
          <ul className="mt-2 space-y-1 text-xs text-amber-200">
            {validation.test_gaps.map((gap) => <li key={gap.gap_id}>⚠ {gap.message}</li>)}
          </ul>
        </div>
      )}
      <div>
        <p className="text-sm font-semibold text-slate-100">
          Recommended tests · {validation.test_plan.cases.length}
        </p>
        <div className="mt-2 grid gap-2 md:grid-cols-2">
          {validation.test_plan.cases.map((testCase) => (
            <div key={`${testCase.test_type}-${testCase.target}-${testCase.title}`} className="rounded border border-white/10 bg-black/20 p-3">
              <p className="text-[11px] font-semibold uppercase text-violet-300">{testCase.test_type} · {testCase.priority}</p>
              <p className="mt-1 text-sm font-semibold text-white">{testCase.title}</p>
              <p className="mt-1 break-all text-xs text-slate-400">{testCase.target}</p>
              <p className="mt-2 text-xs text-slate-300">{testCase.expected_result}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function ConfirmationItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
        {label}
      </dt>
      <dd className="mt-1 break-all text-slate-200">{value}</dd>
    </div>
  );
}

function ValidationFindingGroup({
  title,
  findings,
}: {
  title: string;
  findings: PatchValidationRun["contract_findings"];
}) {
  return (
    <div>
      <p className="text-sm font-semibold text-slate-100">{title}</p>
      <div className="mt-2 space-y-2">
        {findings.length === 0 && <p className="rounded border border-white/10 bg-black/20 p-3 text-xs text-slate-500">No findings returned for this group.</p>}
        {findings.map((finding) => (
          <div key={finding.check_id} className="rounded border border-white/10 bg-black/20 p-3 text-xs">
            <p className={finding.status === "fail" ? "text-rose-200" : finding.status === "pass" ? "text-emerald-200" : "text-amber-200"}>
              {finding.status.toUpperCase()} · {finding.message}
            </p>
            {finding.file_path && <p className="mt-1 break-all text-slate-500">{finding.file_path}{finding.line ? `:${finding.line}` : ""}</p>}
            {finding.evidence && <code className="mt-1 block break-all text-slate-400">{finding.evidence}</code>}
          </div>
        ))}
      </div>
    </div>
  );
}

function diffLineClass(line: string) {
  if (line.startsWith("+++") || line.startsWith("---")) return "text-cyan-300";
  if (line.startsWith("+")) return "bg-emerald-400/10 text-emerald-300";
  if (line.startsWith("-")) return "bg-rose-400/10 text-rose-300";
  if (line.startsWith("@@")) return "text-violet-300";
  return "text-slate-400";
}

type ResultMetricProps = {
  label: string;
  value: string | number;
  danger?: boolean;
};

function ResultMetric({
  label,
  value,
  danger = false,
}: ResultMetricProps) {
  return (
    <div className="rounded-xl border border-white/10 bg-black/20 p-4">
      <p className="text-xs uppercase tracking-wider text-slate-500">
        {label}
      </p>
      <p
        className={`mt-2 text-2xl font-semibold ${
          danger ? "text-rose-300" : "text-white"
        }`}
      >
        {value}
      </p>
    </div>
  );
}

type ChangeRowProps = {
  change: ApiChange;
  matches?: RepositoryMatch[];
  risk?: RiskPrediction;
  migration?: MigrationRecommendation;
};

function ChangeRow({
  change,
  matches,
  risk,
  migration,
}: ChangeRowProps) {
  return (
    <article className="change-card">
      <div className="change-card-header">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-md bg-cyan-400/10 px-2 py-1 text-xs font-semibold uppercase text-cyan-200">
                {change.contract_type === "graphql" ? "GraphQL" : change.method}
              </span>
              <code className="text-sm text-slate-200">
                {change.operation_identifier || change.path}
              </code>
            </div>

            <p className="mt-3 text-sm leading-6 text-slate-400">
              {change.explanation}
            </p>
          </div>

          <div className="flex gap-2">
            <span
              className={`rounded-full px-3 py-1 text-xs font-semibold ${
                change.breaking
                  ? "bg-rose-400/10 text-rose-300"
                  : "bg-emerald-400/10 text-emerald-300"
              }`}
            >
              {change.breaking
                ? "Breaking"
                : "Non-breaking"}
            </span>

            <span className="rounded-full bg-violet-400/10 px-3 py-1 text-xs font-semibold text-violet-300">
              {change.severity}
            </span>
          </div>
        </div>
      </div>
        {(change.old_value !== undefined || change.new_value !== undefined) && (
          <div className="change-before-after">
            <div className="change-value change-value-before">
              <span>Before</span>
              <pre>{formatChangeValue(change.old_value)}</pre>
            </div>
            <div className="change-value change-value-after">
              <span>After</span>
              <pre>{formatChangeValue(change.new_value)}</pre>
            </div>
          </div>
        )}

      {matches !== undefined && (
        <SourceMatchesPanel matches={matches} />
      )}

      {(risk || migration) && (
        <div className="result-insight-grid">
          {risk && <RiskPanel risk={risk} />}
          {migration && (
            <MigrationPanel migration={migration} />
          )}
        </div>
      )}
    </article>
  );
}

function formatChangeValue(value: unknown) {
  if (value === undefined) return "Not present";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}


function SourceMatchesPanel({
  matches,
}: {
  matches: RepositoryMatch[];
}) {
  const directMatches = matches.filter(
    (match) => (match.impact_depth ?? 0) === 0,
  ).length;
  const transitiveMatches = matches.length - directMatches;
  const maximumDepth = Math.max(
    0,
    ...matches.map((match) => match.impact_depth ?? 0),
  );

  return (
    <section className="impact-path">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-emerald-300">
            Impacted source files
          </p>
          <p className="mt-1 text-sm text-slate-400">
            {matches.length === 0
              ? "No matching API usage was found in the repository."
              : `${matches.length} repository match${
                  matches.length === 1 ? "" : "es"
                } found for this change.`}
          </p>
        </div>

        {matches.length > 0 && (
          <span className="w-fit rounded-full bg-emerald-400/10 px-3 py-1 text-xs font-semibold text-emerald-300">
            {matches.length}{" "}
            {matches.length === 1 ? "match" : "matches"}
          </span>
        )}
      </div>

      {matches.length > 0 && (
        <div className="impact-summary-grid">
          <ImpactMetric label="Direct usages" value={directMatches} />
          <ImpactMetric
            label="Transitive callers"
            value={transitiveMatches}
          />
          <ImpactMetric label="Maximum depth" value={maximumDepth} />
        </div>
      )}

      {matches.length > 0 && (
        <div className="mt-4 space-y-3">
          {matches.map((match, index) => (
            <article
              key={`${match.file_path}-${match.line}-${match.column}-${index}`}
              className="impact-match"
            >
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <code className="break-all text-sm font-semibold text-cyan-100">
                      {match.file_path}
                    </code>
                    <span className="rounded-md bg-white/5 px-2 py-1 text-xs text-slate-400">
                      Line {match.line}, column{" "}
                      {match.column}
                    </span>
                    {match.symbol && (
                      <code className="rounded-md bg-violet-400/10 px-2 py-1 text-xs text-violet-200">
                        {match.symbol}
                      </code>
                    )}
                  </div>
                </div>

                <div className="flex flex-wrap gap-2">
                  <span className="rounded-full bg-violet-400/10 px-3 py-1 text-xs font-semibold uppercase text-violet-200">
                    {impactLabel(match)}
                  </span>
                  <span className="rounded-full bg-cyan-400/10 px-3 py-1 text-xs font-semibold text-cyan-200">
                    {formatMatchKind(match.match_kind)}
                  </span>
                  <span
                    className={`rounded-full px-3 py-1 text-xs font-semibold uppercase ${matchConfidenceClass(
                      match.confidence,
                    )}`}
                  >
                    {match.confidence}
                  </span>
                </div>
              </div>

              <details className="impact-match-details">
                <summary>View evidence and dependency trace</summary>
              {(match.trace?.length ?? 0) > 0 && (
                <div className="impact-trace">
                  <p className="text-xs font-semibold uppercase tracking-wider text-violet-300">
                    Dependency chain
                  </p>
                  <div className="mt-3 space-y-2">
                    {match.trace?.map((step, stepIndex) => (
                      <div
                        key={`${step.file_path}-${step.line}-${stepIndex}`}
                        className="impact-trace-step"
                      >
                        <span className="text-violet-300">
                          {stepIndex === 0 ? "●" : "↳"}
                        </span>
                        <div className="min-w-0">
                          <code className="break-all text-cyan-100">
                            {step.symbol ?? step.file_path}
                          </code>
                          <span className="ml-2 text-slate-500">
                            {step.relation === "direct_api_usage"
                              ? "direct API usage"
                              : "calls dependency"}{" "}
                            · line {step.line}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div className="mt-4">
                <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                  Matching evidence
                </p>
                <pre className="mt-2 overflow-x-auto rounded-lg border border-white/10 bg-black/50 p-3 text-xs leading-6 text-emerald-100">
                  <code>{match.evidence}</code>
                </pre>
              </div>
              </details>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function ImpactMetric({
  label,
  value,
}: {
  label: string;
  value: number | string;
}) {
  return (
    <div className="rounded-lg border border-white/10 bg-black/20 px-3 py-2">
      <p className="text-[10px] uppercase tracking-wider text-slate-500">
        {label}
      </p>
      <p className="mt-1 text-lg font-semibold text-white">{value}</p>
    </div>
  );
}

function impactLabel(match: RepositoryMatch) {
  const depth = match.impact_depth ?? 0;
  if (depth === 0) return "Direct";
  if (depth === 1) return "Called by · depth 1";
  return `Transitive · depth ${depth}`;
}

function formatMatchKind(value: string) {
  return value
    .split("_")
    .map(
      (part) =>
        part.charAt(0).toUpperCase() +
        part.slice(1),
    )
    .join(" ");
}

function matchConfidenceClass(value: string) {
  if (value.toLowerCase() === "high") {
    return "bg-emerald-400/10 text-emerald-300";
  }

  if (value.toLowerCase() === "medium") {
    return "bg-amber-400/10 text-amber-300";
  }

  return "bg-slate-400/10 text-slate-300";
}

function RiskPanel({
  risk,
}: {
  risk: RiskPrediction;
}) {
  const roundedScore = Math.round(risk.risk_score);

  return (
    <section className="risk-panel bg-slate-950/90 p-5">
      <div className="flex items-start justify-between gap-4">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">
          Migration Risk
        </p>
        <span
          className={`rounded-full px-3 py-1 text-xs font-semibold uppercase ${riskLevelClass(
            risk.risk_level,
          )}`}
        >
          {risk.risk_level}
        </span>
      </div>
      <div
        className="risk-gauge"
        style={{
          "--risk-progress": `${Math.min(100, Math.max(0, roundedScore))}%`,
          color: risk.risk_level === "low" ? "var(--green)" : risk.risk_level === "medium" ? "var(--amber)" : "var(--red)",
        } as CSSProperties}
      >
        <div className="risk-gauge-fill" />
        <div className="risk-gauge-value"><strong>{roundedScore}</strong><small> / 100</small></div>
      </div>

      <p className="mt-3 text-xs text-slate-500">
        {risk.model_name} · {risk.model_version} ·{" "}
        {risk.prediction_source}
      </p>

      {risk.reasons.length > 0 && (
        <div className="mt-5">
          <h4 className="text-sm font-semibold text-slate-200">
            Why this is risky
          </h4>
          <ul className="mt-3 space-y-2">
            {risk.reasons.slice(0, 4).map((reason) => (
              <li
                key={reason}
                className="flex gap-2 text-sm leading-6 text-slate-400"
              >
                <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-cyan-300" />
                <span>{reason}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {risk.top_drivers.length > 0 && (
        <details className="risk-driver-details">
          <summary>Explain top risk drivers</summary>
          <div className="mt-3 space-y-2">
            {risk.top_drivers
              .slice(0, 3)
              .map((driver) => (
                <div
                  key={driver.feature}
                  className="rounded-lg border border-white/5 bg-white/[0.03] px-3 py-2"
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-xs font-medium text-slate-300">
                      {driver.feature}
                    </span>
                    <span className="text-xs text-violet-300">
                      {driver.influence.toFixed(2)}
                    </span>
                  </div>
                  <p className="mt-1 text-xs leading-5 text-slate-500">
                    {driver.description}
                  </p>
                </div>
              ))}
          </div>
        </details>
      )}
    </section>
  );
}

function MigrationPanel({
  migration,
}: {
  migration: MigrationRecommendation;
}) {
  return (
    <section className="bg-slate-950/90 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-violet-300">
            Migration plan
          </p>
          <h4 className="mt-2 text-base font-semibold text-white">
            {migration.summary}
          </h4>
        </div>

        <span className="rounded-full bg-violet-400/10 px-3 py-1 text-xs font-semibold uppercase text-violet-300">
          {Math.round(migration.confidence * 100)}%
          confidence
        </span>
      </div>

      <p className="mt-4 text-sm leading-6 text-slate-400">
        {migration.why_it_matters}
      </p>

      <div className="mt-5">
        <h5 className="text-sm font-semibold text-slate-200">
          Migration steps
        </h5>
        <ol className="mt-3 space-y-3">
          {migration.migration_steps.map(
            (step, index) => (
              <li
                key={`${index}-${step}`}
                className="flex gap-3 text-sm leading-6 text-slate-400"
              >
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-cyan-400/20 to-violet-400/20 text-xs font-semibold text-cyan-200">
                  {index + 1}
                </span>
                <span>{step}</span>
              </li>
            ),
          )}
        </ol>
      </div>

      {migration.suggested_tests.length > 0 && (
        <div className="mt-5">
          <h5 className="text-sm font-semibold text-slate-200">
            Suggested tests
          </h5>
          <ul className="mt-3 space-y-2">
            {migration.suggested_tests.map((test) => (
              <li
                key={test}
                className="flex gap-2 text-sm leading-6 text-slate-400"
              >
                <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-violet-300" />
                <span>{test}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {migration.code_example && (
        <div className="mt-5">
          <h5 className="text-sm font-semibold text-slate-200">
            Example
          </h5>
          <pre className="mt-3 overflow-x-auto rounded-lg border border-white/10 bg-black/40 p-3 text-xs leading-6 text-cyan-100">
            <code>{migration.code_example}</code>
          </pre>
        </div>
      )}

      <p className="mt-5 text-xs text-slate-500">
        Provider: {migration.provider} ·{" "}
        {migration.provider_model}
      </p>
    </section>
  );
}

function riskLevelClass(
  level: RiskPrediction["risk_level"],
) {
  if (level === "critical") {
    return "bg-rose-500/15 text-rose-200";
  }

  if (level === "high") {
    return "bg-orange-400/15 text-orange-200";
  }

  if (level === "medium") {
    return "bg-amber-400/15 text-amber-200";
  }

  return "bg-emerald-400/15 text-emerald-200";
}

const APP_PAGE_PATHS: Record<AppPage, string> = {
  overview: "/app",
  "new-analysis": "/app/new-analysis",
  monitors: "/app/monitors",
  analyses: "/app/analyses",
  repositories: "/app/repositories",
  team: "/app/team",
  "system-status": "/app/system-status",
  "analysis-result": "/app/analyses/result",
};

function pagePath(page: AppPage) {
  return APP_PAGE_PATHS[page];
}

function pageFromPath(path: string): AppPage {
  const match = (Object.entries(APP_PAGE_PATHS) as Array<[AppPage, string]>)
    .find(([page, candidate]) => page !== "analysis-result" && candidate === path);
  return match?.[0] ?? "overview";
}

export default App;

