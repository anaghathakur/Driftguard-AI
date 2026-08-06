import {
  useCallback,
  useEffect,
  useState,
} from "react";

import {
  analyzeRepositoryImpact,
  compareSpecifications,
  getAnalyses,
  getAnalysisChanges,
  getAnalysisMatches,
  getMigrationProviderStatus,
  getMigrationRecommendations,
  getRiskPredictions,
  type AnalysisHistoryItem,
  type ApiChange,
  type ComparisonResponse,
  type ImpactAnalysisResponse,
  type MigrationProviderStatus,
  type MigrationRecommendation,
  type PersistedMatch,
  type RepositoryMatch,
  type RiskPrediction,
} from "./lib/api";

type AnalysisMode = "comparison" | "impact";

type AnalysisResult =
  | {
      mode: "comparison";
      data: ComparisonResponse;
    }
  | {
      mode: "impact";
      data: ImpactAnalysisResponse;
    };

function App() {
  const [mode, setMode] =
    useState<AnalysisMode>("comparison");
  const [oldSpec, setOldSpec] =
    useState<File | null>(null);
  const [newSpec, setNewSpec] =
    useState<File | null>(null);
  const [repository, setRepository] =
    useState<File | null>(null);

  const [providerStatus, setProviderStatus] =
    useState<MigrationProviderStatus | null>(null);
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

  const loadHistory = useCallback(async () => {
    setIsLoadingHistory(true);
    setHistoryError(null);

    try {
      setHistory(await getAnalyses());
    } catch (error) {
      setHistory([]);
      setHistoryError(
        error instanceof Error
          ? error.message
          : "Saved analyses could not be loaded.",
      );
    } finally {
      setIsLoadingHistory(false);
    }
  }, []);

  const canAnalyze =
    !isAnalyzing &&
    oldSpec !== null &&
    newSpec !== null &&
    (mode === "comparison" || repository !== null);

  useEffect(() => {
    let active = true;

    async function loadBackendStatus() {
      try {
        const status =
          await getMigrationProviderStatus();

        if (active) {
          setProviderStatus(status);
          setBackendError(false);
        }
      } catch {
        if (active) {
          setProviderStatus(null);
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
    void loadHistory();
  }, [loadHistory]);

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
        "Select both OpenAPI specification files.",
      );
      return;
    }

    if (mode === "impact" && !repository) {
      setAnalysisError(
        "Select a repository ZIP file for impact analysis.",
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
        );

        setAnalysisResult({
          mode: "comparison",
          data,
        });

        await loadInsights(data.analysis_id);
        void loadHistory();
      } else {
        const data = await analyzeRepositoryImpact(
          oldSpec,
          newSpec,
          repository as File,
        );

        setAnalysisResult({
          mode: "impact",
          data,
        });

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

  const comparison =
    analysisResult?.mode === "comparison"
      ? analysisResult.data
      : analysisResult?.data.comparison;

  const analysisId =
    analysisResult?.data.analysis_id ?? null;

  return (
    <div className="min-h-screen text-slate-100">
      <header className="border-b border-white/10 bg-black/30 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-cyan-400 to-violet-500 font-bold text-slate-950 shadow-lg shadow-cyan-500/20">
              DG
            </div>

            <div>
              <h1 className="text-lg font-semibold text-white">
                DriftGuard AI
              </h1>
              <p className="text-xs text-slate-400">
                API change intelligence platform
              </p>
            </div>
          </div>

          <BackendBadge
            backendError={backendError}
            providerStatus={providerStatus}
          />
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-6 py-10">
        <section className="mb-10 max-w-3xl">
          <p className="mb-3 text-sm font-semibold uppercase tracking-[0.24em] text-cyan-300">
            API contract analysis
          </p>

          <h2 className="text-4xl font-bold tracking-tight text-white md:text-5xl">
            Find breaking API changes before they reach
            production.
          </h2>

          <p className="mt-5 max-w-2xl text-lg leading-8 text-slate-400">
            Compare OpenAPI specifications, discover
            impacted source files, calculate migration
            risk, and generate actionable recommendations.
          </p>
        </section>

        <section className="grid gap-6 lg:grid-cols-[1fr_340px]">
          <div className="rounded-2xl border border-white/10 bg-white/5 p-6 shadow-2xl shadow-black/30 backdrop-blur-xl">
            <div className="mb-6">
              <h3 className="text-xl font-semibold text-white">
                Start a new analysis
              </h3>
              <p className="mt-1 text-sm text-slate-400">
                Choose the analysis type and upload your
                files.
              </p>
            </div>

            <div className="mb-7 grid grid-cols-2 gap-3 rounded-xl border border-white/5 bg-black/25 p-1.5">
              <ModeButton
                active={mode === "comparison"}
                onClick={() =>
                  setMode("comparison")
                }
              >
                Specification comparison
              </ModeButton>

              <ModeButton
                active={mode === "impact"}
                onClick={() => setMode("impact")}
              >
                Repository impact
              </ModeButton>
            </div>

            <div className="grid gap-5 md:grid-cols-2">
              <FileField
                label="Old OpenAPI specification"
                description="Current or previously released contract"
                accept=".json,.yaml,.yml"
                file={oldSpec}
                onChange={setOldSpec}
              />

              <FileField
                label="New OpenAPI specification"
                description="Proposed or updated contract"
                accept=".json,.yaml,.yml"
                file={newSpec}
                onChange={setNewSpec}
              />
            </div>

            {mode === "impact" && (
              <div className="mt-5">
                <FileField
                  label="Repository archive"
                  description="Upload the source repository as a ZIP file"
                  accept=".zip"
                  file={repository}
                  onChange={setRepository}
                />
              </div>
            )}

            {analysisError && (
              <div className="mt-5 rounded-xl border border-rose-400/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-200">
                {analysisError}
              </div>
            )}

            <div className="mt-7 flex flex-col gap-3 border-t border-white/10 pt-6 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-sm text-slate-500">
                Files are processed locally by your
                DriftGuard backend.
              </p>

              <button
                type="button"
                disabled={!canAnalyze}
                onClick={() => void handleAnalyze()}
                className="rounded-xl bg-gradient-to-r from-cyan-400 to-violet-500 px-6 py-3 text-sm font-semibold text-slate-950 transition hover:scale-[1.01] disabled:cursor-not-allowed disabled:bg-none disabled:bg-slate-700 disabled:text-slate-400"
              >
                {isAnalyzing
                  ? "Analyzing..."
                  : "Analyze changes"}
              </button>
            </div>
          </div>

          <aside className="space-y-5">
            <MetricCard
              label="Analysis engine"
              value={
                backendError ? "Offline" : "Ready"
              }
              detail="OpenAPI comparison and impact scanning"
            />

            <MetricCard
              label="Risk classifier"
              value="ML enabled"
              detail="Explainable risk prediction"
            />

            <MetricCard
              label="Migration provider"
              value={
                providerStatus
                  ? providerStatus.active_provider.toUpperCase()
                  : backendError
                    ? "Unavailable"
                    : "Checking"
              }
              detail={
                providerStatus
                  ? providerStatus.provider_model
                  : "Waiting for backend connection"
              }
            />
          </aside>
        </section>

        {analysisResult && comparison && (
          <AnalysisResultPanel
            result={analysisResult}
            comparison={comparison}
            analysisId={analysisId}
            risks={risks}
            migrations={migrations}
            isLoadingInsights={isLoadingInsights}
            insightError={insightError}
          />
        )}

        <RecentAnalyses
          analyses={history}
          isLoading={isLoadingHistory}
          error={historyError}
          openingAnalysisId={openingAnalysisId}
          onRefresh={() => void loadHistory()}
          onOpen={(item) =>
            void handleOpenAnalysis(item)
          }
        />
      </main>
    </div>
  );
}

type RecentAnalysesProps = {
  analyses: AnalysisHistoryItem[];
  isLoading: boolean;
  error: string | null;
  openingAnalysisId: string | null;
  onRefresh: () => void;
  onOpen: (item: AnalysisHistoryItem) => void;
};

function RecentAnalyses({
  analyses,
  isLoading,
  error,
  openingAnalysisId,
  onRefresh,
  onOpen,
}: RecentAnalysesProps) {
  return (
    <section className="mt-8 rounded-2xl border border-white/10 bg-white/5 p-6 shadow-xl shadow-black/20 backdrop-blur-xl">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h3 className="text-lg font-semibold text-white">
            Recent analyses
          </h3>
          <p className="mt-1 text-sm text-slate-400">
            Reopen a saved analysis without uploading the
            files again.
          </p>
        </div>

        <button
          type="button"
          onClick={onRefresh}
          disabled={isLoading}
          className="rounded-lg border border-cyan-400/20 bg-cyan-400/5 px-4 py-2 text-sm font-medium text-cyan-200 transition hover:border-cyan-300/40 hover:bg-cyan-400/10 disabled:cursor-wait disabled:opacity-60"
        >
          {isLoading ? "Refreshing..." : "Refresh"}
        </button>
      </div>

      {error && (
        <div className="mt-5 rounded-xl border border-rose-400/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-200">
          {error}
        </div>
      )}

      {!error && isLoading && analyses.length === 0 && (
        <div className="mt-8 flex min-h-36 items-center justify-center rounded-xl border border-dashed border-white/10 bg-black/20">
          <p className="text-sm text-cyan-200">
            Loading saved analyses...
          </p>
        </div>
      )}

      {!error && !isLoading && analyses.length === 0 && (
        <div className="mt-8 flex min-h-36 items-center justify-center rounded-xl border border-dashed border-white/10 bg-black/20">
          <div className="text-center">
            <p className="font-medium text-slate-200">
              No saved analyses
            </p>
            <p className="mt-1 text-sm text-slate-500">
              Complete a comparison or repository impact
              analysis to create history.
            </p>
          </div>
        </div>
      )}

      {analyses.length > 0 && (
        <div className="mt-6 space-y-3">
          {analyses.map((item) => {
            const isOpening =
              openingAnalysisId === item.analysis_id;

            return (
              <article
                key={item.analysis_id}
                className="rounded-xl border border-white/10 bg-black/20 p-4 transition hover:border-cyan-400/30 hover:bg-white/[0.03]"
              >
                <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded-full bg-cyan-400/10 px-3 py-1 text-xs font-semibold uppercase text-cyan-200">
                        {item.kind}
                      </span>
                      <StatusBadge status={item.status} />
                      <span className="text-xs text-slate-500">
                        {formatDate(item.created_at)}
                      </span>
                    </div>

                    <code className="mt-3 block truncate text-xs text-slate-400">
                      {item.analysis_id}
                    </code>
                  </div>

                  <div className="flex flex-wrap items-center gap-3">
                    <HistoryMetric
                      label="Changes"
                      value={item.total_changes}
                    />
                    <HistoryMetric
                      label="Matches"
                      value={item.total_matches}
                    />

                    <button
                      type="button"
                      onClick={() => onOpen(item)}
                      disabled={
                        isOpening ||
                        item.status !== "succeeded"
                      }
                      className="rounded-lg bg-gradient-to-r from-cyan-400 to-violet-500 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:scale-[1.01] disabled:cursor-not-allowed disabled:bg-none disabled:bg-slate-700 disabled:text-slate-400"
                    >
                      {isOpening
                        ? "Opening..."
                        : "Open result"}
                    </button>
                  </div>
                </div>

                {item.failure && (
                  <p className="mt-3 text-sm text-rose-300">
                    {item.failure.message}
                  </p>
                )}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}

function HistoryMetric({
  label,
  value,
}: {
  label: string;
  value: number;
}) {
  return (
    <div className="min-w-20 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-center">
      <p className="text-[10px] uppercase tracking-wider text-slate-500">
        {label}
      </p>
      <p className="mt-1 text-sm font-semibold text-white">
        {value}
      </p>
    </div>
  );
}

function StatusBadge({
  status,
}: {
  status: AnalysisHistoryItem["status"];
}) {
  const className =
    status === "succeeded"
      ? "bg-emerald-400/10 text-emerald-300"
      : status === "failed"
        ? "bg-rose-400/10 text-rose-300"
        : "bg-amber-400/10 text-amber-300";

  return (
    <span
      className={`rounded-full px-3 py-1 text-xs font-semibold uppercase ${className}`}
    >
      {status}
    </span>
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

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

type BackendBadgeProps = {
  backendError: boolean;
  providerStatus: MigrationProviderStatus | null;
};

function BackendBadge({
  backendError,
  providerStatus,
}: BackendBadgeProps) {
  return (
    <div
      className={`flex items-center gap-2 rounded-full border px-3 py-1.5 ${
        backendError
          ? "border-rose-400/20 bg-rose-400/10"
          : "border-cyan-400/20 bg-cyan-400/10"
      }`}
    >
      <span
        className={`h-2 w-2 rounded-full ${
          backendError
            ? "bg-rose-400 shadow-[0_0_10px_rgba(251,113,133,0.9)]"
            : "bg-cyan-300 shadow-[0_0_10px_rgba(103,232,249,0.9)]"
        }`}
      />

      <span
        className={`text-xs font-medium ${
          backendError
            ? "text-rose-300"
            : "text-cyan-200"
        }`}
      >
        {backendError
          ? "Backend offline"
          : providerStatus
            ? "Backend ready"
            : "Checking backend"}
      </span>
    </div>
  );
}

type ModeButtonProps = {
  active: boolean;
  onClick: () => void;
  children: string;
};

function ModeButton({
  active,
  onClick,
  children,
}: ModeButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-lg px-4 py-3 text-sm font-medium transition ${
        active
          ? "bg-gradient-to-r from-cyan-400 to-violet-500 text-slate-950 shadow-lg shadow-cyan-500/20"
          : "text-slate-400 hover:bg-white/5 hover:text-white"
      }`}
    >
      {children}
    </button>
  );
}

type FileFieldProps = {
  label: string;
  description: string;
  accept: string;
  file: File | null;
  onChange: (file: File | null) => void;
};

function FileField({
  label,
  description,
  accept,
  file,
  onChange,
}: FileFieldProps) {
  return (
    <label className="block rounded-xl border border-white/10 bg-black/20 p-4 transition hover:border-cyan-400/40 hover:bg-white/[0.03]">
      <span className="block text-sm font-semibold text-slate-100">
        {label}
      </span>

      <span className="mt-1 block text-xs leading-5 text-slate-500">
        {description}
      </span>

      <input
        type="file"
        accept={accept}
        onChange={(event) =>
          onChange(
            event.target.files?.[0] ?? null,
          )
        }
        className="mt-4 block w-full text-sm text-slate-400 file:mr-4 file:rounded-lg file:border-0 file:bg-gradient-to-r file:from-cyan-400/15 file:to-violet-500/15 file:px-4 file:py-2 file:text-sm file:font-semibold file:text-cyan-200 hover:file:from-cyan-400/20 hover:file:to-violet-500/20"
      />

      {file && (
        <span className="mt-3 block truncate rounded-lg border border-emerald-400/10 bg-emerald-400/10 px-3 py-2 text-xs text-emerald-300">
          Selected: {file.name}
        </span>
      )}
    </label>
  );
}

type MetricCardProps = {
  label: string;
  value: string;
  detail: string;
};

function MetricCard({
  label,
  value,
  detail,
}: MetricCardProps) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 p-5 shadow-lg shadow-black/20 backdrop-blur-xl">
      <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
        {label}
      </p>
      <p className="mt-3 text-xl font-semibold text-white">
        {value}
      </p>
      <p className="mt-2 text-sm leading-6 text-slate-400">
        {detail}
      </p>
    </div>
  );
}

type AnalysisResultPanelProps = {
  result: AnalysisResult;
  comparison: ComparisonResponse;
  analysisId: string | null;
  risks: RiskPrediction[];
  migrations: MigrationRecommendation[];
  isLoadingInsights: boolean;
  insightError: string | null;
};

function AnalysisResultPanel({
  result,
  comparison,
  analysisId,
  risks,
  migrations,
  isLoadingInsights,
  insightError,
}: AnalysisResultPanelProps) {
  const impactSummary =
    result.mode === "impact"
      ? result.data.impact_summary
      : null;

  return (
    <section
      id="analysis-result"
      className="mt-8 scroll-mt-6 rounded-2xl border border-cyan-400/20 bg-white/5 p-6 shadow-xl shadow-cyan-950/20 backdrop-blur-xl"
    >
      <div className="flex flex-col gap-3 border-b border-white/10 pb-5 md:flex-row md:items-center md:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">
            Analysis completed
          </p>
          <h3 className="mt-2 text-xl font-semibold text-white">
            {result.mode === "impact"
              ? "Repository impact result"
              : "Specification comparison result"}
          </h3>
        </div>

        {analysisId && (
          <code className="max-w-full truncate rounded-lg border border-white/10 bg-black/25 px-3 py-2 text-xs text-slate-400">
            {analysisId}
          </code>
        )}
      </div>

      <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <ResultMetric
          label="Total changes"
          value={comparison.summary.total_changes}
        />
        <ResultMetric
          label="Breaking changes"
          value={comparison.summary.breaking_changes}
          danger={
            comparison.summary.breaking_changes > 0
          }
        />
        <ResultMetric
          label="Non-breaking"
          value={
            comparison.summary.non_breaking_changes
          }
        />
        <ResultMetric
          label={
            impactSummary
              ? "Impacted files"
              : "Duplicate result"
          }
          value={
            impactSummary
              ? impactSummary.impacted_files
              : comparison.duplicate
                ? "Yes"
                : "No"
          }
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

      <div className="mt-6 space-y-5">
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
  );
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
    <article className="overflow-hidden rounded-xl border border-white/10 bg-black/20">
      <div className="p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-md bg-cyan-400/10 px-2 py-1 text-xs font-semibold uppercase text-cyan-200">
                {change.method}
              </span>
              <code className="text-sm text-slate-200">
                {change.path}
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

      {matches !== undefined && (
        <SourceMatchesPanel matches={matches} />
      )}

      {(risk || migration) && (
        <div className="grid gap-px border-t border-white/10 bg-white/10 lg:grid-cols-2">
          {risk && <RiskPanel risk={risk} />}
          {migration && (
            <MigrationPanel migration={migration} />
          )}
        </div>
      )}
    </article>
  );
}

function SourceMatchesPanel({
  matches,
}: {
  matches: RepositoryMatch[];
}) {
  return (
    <section className="border-t border-white/10 bg-slate-950/70 p-5">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-emerald-300">
            Impacted source files
          </p>
          <p className="mt-1 text-sm text-slate-400">
            {matches.length === 0
              ? "No matching API usage was found in the uploaded repository."
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
        <div className="mt-4 space-y-3">
          {matches.map((match, index) => (
            <article
              key={`${match.file_path}-${match.line}-${match.column}-${index}`}
              className="rounded-xl border border-white/10 bg-black/30 p-4"
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
                  </div>
                </div>

                <div className="flex flex-wrap gap-2">
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

              <div className="mt-4">
                <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                  Matching evidence
                </p>
                <pre className="mt-2 overflow-x-auto rounded-lg border border-white/10 bg-black/50 p-3 text-xs leading-6 text-emerald-100">
                  <code>{match.evidence}</code>
                </pre>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
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
    <section className="bg-slate-950/90 p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">
            ML risk prediction
          </p>
          <p className="mt-2 text-2xl font-semibold text-white">
            {roundedScore}
            <span className="text-sm text-slate-500">
              /100
            </span>
          </p>
        </div>

        <span
          className={`rounded-full px-3 py-1 text-xs font-semibold uppercase ${riskLevelClass(
            risk.risk_level,
          )}`}
        >
          {risk.risk_level}
        </span>
      </div>

      <div className="mt-4 h-2 overflow-hidden rounded-full bg-white/10">
        <div
          className="h-full rounded-full bg-gradient-to-r from-cyan-400 via-violet-400 to-rose-400"
          style={{
            width: `${Math.min(
              100,
              Math.max(0, roundedScore),
            )}%`,
          }}
        />
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
        <div className="mt-5">
          <h4 className="text-sm font-semibold text-slate-200">
            Top risk drivers
          </h4>
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
        </div>
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

export default App;