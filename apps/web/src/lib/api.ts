const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

export type MigrationProviderStatus = {
  configured_provider: string;
  active_provider: string;
  provider_model: string;
  available: boolean;
  prompt_version: string;
  schema_version: string;
  fallback_enabled: boolean;
  warning: string | null;
};

export type ApiChange = {
  change_id: string;
  change_type: string;
  path: string;
  method: string;
  subject: string | null;
  old_value?: unknown;
  new_value?: unknown;
  breaking: boolean;
  category: string;
  severity: string;
  explanation: string;
};

export type ComparisonSummary = {
  total_changes: number;
  breaking_changes: number;
  non_breaking_changes: number;
};

export type ComparisonResponse = {
  analysis_id: string;
  duplicate: boolean;
  summary: ComparisonSummary;
  changes: ApiChange[];
};

export type RepositoryScanSummary = {
  archive_sha256: string;
  archive_entries: number;
  scanned_files: number;
  scanned_bytes: number;
  skipped_files: number;
  skipped_reasons: Record<string, number>;
};

export type ImpactSummary = {
  total_changes: number;
  impacted_changes: number;
  impacted_files: number;
  total_matches: number;
};

export type RepositoryMatch = {
  file_path: string;
  line: number;
  column: number;
  match_kind: string;
  confidence: string;
  evidence: string;
};

export type ChangeImpact = {
  change_id: string;
  matches: RepositoryMatch[];
};

export type ImpactAnalysisResponse = {
  analysis_id: string;
  duplicate: boolean;
  comparison: ComparisonResponse;
  repository: RepositoryScanSummary;
  impact_summary: ImpactSummary;
  impacts: ChangeImpact[];
};

export type AnalysisHistoryItem = {
  analysis_id: string;
  kind: "comparison" | "impact";
  status: "pending" | "running" | "succeeded" | "failed";
  created_at: string;
  completed_at: string | null;
  total_changes: number;
  total_matches: number;
  failure: {
    code?: string;
    message: string;
  } | null;
};

export type PersistedMatch = RepositoryMatch & {
  change_id: string;
};

export type RiskDriver = {
  feature: string;
  value: number;
  influence: number;
  description: string;
};

export type RiskPrediction = {
  analysis_id: string | null;
  change_id: string;
  risk_level: "low" | "medium" | "high" | "critical";
  risk_score: number;
  prediction_source: string;
  model_name: string;
  model_version: string;
  baseline_level: string;
  baseline_score: number;
  class_probabilities: Record<string, number>;
  features: Record<string, number>;
  reasons: string[];
  top_drivers: RiskDriver[];
  fallback_reason: string | null;
  predicted_at: string;
};

export type MigrationRecommendation = {
  recommendation_id: string;
  analysis_id: string | null;
  change_id: string;
  summary: string;
  why_it_matters: string;
  affected_code_explanation: string;
  migration_steps: string[];
  suggested_tests: string[];
  code_example: string;
  assumptions: string[];
  warnings: string[];
  confidence: number;
  provider: string;
  provider_model: string;
  recommendation_source: string;
  provider_warning: string | null;
  redactions_applied: number;
  prompt_version: string;
  schema_version: string;
  generated_at: string;
};

export type AnalysisReportSummary = {
  total_changes: number;
  breaking_changes: number;
  potentially_breaking_changes: number;
  non_breaking_changes: number;
  repository_matches: number;
  impacted_files: number;
  risk_predictions: number;
  migration_recommendations: number;
};

export type AnalysisReport = {
  report_version: string;
  generated_at: string;
  analysis: Record<string, unknown>;
  summary: AnalysisReportSummary;
  changes: ApiChange[];
  matches: PersistedMatch[];
  risks: RiskPrediction[];
  migrations: MigrationRecommendation[];
  pipeline: Array<Record<string, unknown>>;
};

export async function getMigrationProviderStatus(): Promise<MigrationProviderStatus> {
  return requestJson<MigrationProviderStatus>(
    "/api/v1/migration/provider",
  );
}

export async function compareSpecifications(
  oldSpec: File,
  newSpec: File,
): Promise<ComparisonResponse> {
  const formData = new FormData();

  formData.append("old_spec", oldSpec);
  formData.append("new_spec", newSpec);

  return requestJson<ComparisonResponse>(
    "/api/v1/specifications/compare",
    {
      method: "POST",
      body: formData,
    },
  );
}

export async function analyzeRepositoryImpact(
  oldSpec: File,
  newSpec: File,
  repository: File,
): Promise<ImpactAnalysisResponse> {
  const formData = new FormData();

  formData.append("old_spec", oldSpec);
  formData.append("new_spec", newSpec);
  formData.append("repository", repository);

  return requestJson<ImpactAnalysisResponse>(
    "/api/v1/impact/analyze",
    {
      method: "POST",
      body: formData,
    },
  );
}

export async function analyzeGitHubRepositoryImpact(
  oldSpec: File,
  newSpec: File,
  repositoryUrl: string,
  ref?: string,
): Promise<ImpactAnalysisResponse> {
  const formData = new FormData();

  formData.append("old_spec", oldSpec);
  formData.append("new_spec", newSpec);
  formData.append("repository_url", repositoryUrl.trim());

  if (ref?.trim()) {
    formData.append("ref", ref.trim());
  }

  return requestJson<ImpactAnalysisResponse>(
    "/api/v1/impact/analyze/github",
    {
      method: "POST",
      body: formData,
    },
  );
}

export async function getAnalyses(): Promise<
  AnalysisHistoryItem[]
> {
  return requestJson<AnalysisHistoryItem[]>(
    "/api/v1/analyses",
  );
}

export async function getAnalysisChanges(
  analysisId: string,
): Promise<ApiChange[]> {
  return requestJson<ApiChange[]>(
    `/api/v1/analyses/${analysisId}/changes`,
  );
}

export async function getAnalysisMatches(
  analysisId: string,
): Promise<PersistedMatch[]> {
  return requestJson<PersistedMatch[]>(
    `/api/v1/analyses/${analysisId}/matches`,
  );
}

export async function getRiskPredictions(
  analysisId: string,
): Promise<RiskPrediction[]> {
  return requestJson<RiskPrediction[]>(
    `/api/v1/analyses/${analysisId}/risks`,
  );
}

export async function getMigrationRecommendations(
  analysisId: string,
): Promise<MigrationRecommendation[]> {
  return requestJson<MigrationRecommendation[]>(
    `/api/v1/analyses/${analysisId}/migrations`,
  );
}

export async function getAnalysisReport(
  analysisId: string,
): Promise<AnalysisReport> {
  return requestJson<AnalysisReport>(
    `/api/v1/analyses/${analysisId}/report`,
  );
}

export async function getAnalysisPdf(
  analysisId: string,
): Promise<Blob> {
  const response = await fetch(
    `${API_BASE_URL}/api/v1/analyses/${analysisId}/report.pdf`,
  );

  if (!response.ok) {
    throw new Error(await getErrorMessage(response));
  }

  return response.blob();
}

async function requestJson<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const response = await fetch(
    `${API_BASE_URL}${path}`,
    options,
  );

  if (!response.ok) {
    throw new Error(await getErrorMessage(response));
  }

  return response.json() as Promise<T>;
}

async function getErrorMessage(
  response: Response,
): Promise<string> {
  try {
    const body = (await response.json()) as {
      error?: {
        message?: string;
      };
      detail?:
        | string
        | {
            message?: string;
          };
      message?: string;
    };

    if (body.error?.message) {
      return body.error.message;
    }

    if (typeof body.detail === "string") {
      return body.detail;
    }

    if (
      typeof body.detail === "object" &&
      body.detail?.message
    ) {
      return body.detail.message;
    }

    if (body.message) {
      return body.message;
    }
  } catch {
    // The backend did not return a JSON error body.
  }

  return `Request failed with HTTP ${response.status}.`;
}
