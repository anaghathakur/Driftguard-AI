const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export type ReadinessStatus = {
  status: "ready" | "not_ready";
  checks: {
    storage: string;
    analysis_engine: string;
    risk_classifier: string;
    migration_provider: string;
    patch_provider: string;
    test_plan_provider: string;
    github_write_provider: string;
    monitor_scheduler: string;
  };
  issues: string[];
};

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

export type ContractTypeSelection = "auto" | "openapi" | "graphql";
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
  contract_type?: "openapi" | "graphql";
  operation_kind?: string;
  operation_identifier?: string | null;
  contract_location?: string | null;
  old_type?: string | null;
  new_type?: string | null;
  old_required?: boolean | null;
  new_required?: boolean | null;
  metadata?: Record<string, unknown>;
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
  code_analysis?: {
    supported_files: number;
    parser_failures: number;
    parser_failure_files: string[];
    symbols_discovered: number;
    call_edges_resolved: number;
    direct_api_anchors: number;
    transitive_matches: number;
    max_impact_depth: number;
  } | null;
};

export async function getReadinessStatus(): Promise<ReadinessStatus> {
  return requestJson<ReadinessStatus>("/ready");
}

export type ImpactTraceStep = {
  file_path: string;
  symbol: string | null;
  relation: "direct_api_usage" | "calls";
  line: number;
  column: number;
  evidence: string;
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
  symbol?: string | null;
  language?: string | null;
  impact_depth?: number;
  analysis_kind?: "lexical" | "direct" | "wrapper" | "transitive";
  trace?: ImpactTraceStep[];
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

export type PatchValidationResult = {
  source_snapshot_verified: boolean;
  paths_safe: boolean;
  allowed_scope_verified: boolean;
  edit_anchors_verified: boolean;
  syntax_valid: boolean;
  limits_valid: boolean;
  warnings: string[];
};

export type PatchProposal = {
  patch_id: string;
  analysis_id: string;
  created_at: string;
  status: "validated";
  summary: string;
  provider: "mock" | "gemini" | "deterministic";
  provider_model: string;
  provider_mode: "deterministic_mock" | "evidence_based" | "external";
  patch_profile_version: string;
  source_repository_hash: string;
  request_fingerprint: string;
  files_changed: number;
  edit_count: number;
  validation: PatchValidationResult;
  warnings: string[];
  unified_diff: string;
  redactions_applied: number;
  files: Array<{
    file_path: string;
    language: string;
    related_symbol: string | null;
    edits: Array<{
      expected_original: string;
      replacement: string;
      reason: string;
      related_change_ids: string[];
    }>;
  }>;
};

export type PatchProposalListItem = Pick<
  PatchProposal,
  | "patch_id"
  | "analysis_id"
  | "created_at"
  | "status"
  | "summary"
  | "provider"
  | "provider_model"
  | "files_changed"
  | "edit_count"
>;

export type ValidationFinding = {
  check_id: string;
  category: string;
  status: "pass" | "warning" | "fail" | "unknown";
  severity: string;
  message: string;
  change_id: string | null;
  file_path: string | null;
  symbol: string | null;
  line: number | null;
  column: number | null;
  evidence: string | null;
};

export type PatchValidationRun = {
  validation_id: string;
  patch_id: string;
  analysis_id: string;
  created_at: string;
  validation_profile_version: string;
  readiness: "ready_for_review" | "needs_review" | "blocked";
  source_repository_hash: string;
  request_fingerprint: string;
  passed_count: number;
  warning_count: number;
  failed_count: number;
  unknown_count: number;
  contract_findings: ValidationFinding[];
  dependency_findings: ValidationFinding[];
  related_tests: Array<{
    file_path: string;
    language: string;
    relevance: "high" | "medium" | "low";
    reasons: string[];
    related_symbols: string[];
    related_changes: string[];
    lines: number[];
  }>;
  test_gaps: Array<{
    gap_id: string;
    message: string;
    symbol: string | null;
    file_path: string | null;
    impact_depth: number;
  }>;
  test_plan: {
    summary: string;
    cases: Array<{
      title: string;
      test_type: "unit" | "integration" | "regression" | "negative" | "contract";
      target: string;
      rationale: string;
      steps: string[];
      expected_result: string;
      priority: "high" | "medium" | "low";
    }>;
  };
  provider: "mock" | "gemini" | "deterministic";
  provider_model: string;
  provider_mode: "deterministic_mock" | "deterministic" | "external";
  warnings: string[];
  modified_files: string[];
  direct_impacted_files: string[];
  transitive_impacted_files: string[];
  unrelated_modified_files: string[];
  execution: {
    status: "passed" | "failed" | "partial" | "not_configured" | "blocked";
    ecosystem: string | null;
    commands: Array<{
      category: string;
      display_name: string;
      argv: string[];
      exit_code: number | null;
      timed_out: boolean;
      duration_ms: number;
      stdout_summary: string;
      stderr_summary: string;
      output_truncated: boolean;
    }>;
    checks: string[];
    duration_ms: number;
    isolated_temporary_copy: boolean;
    original_repository_unchanged: boolean;
    message: string;
  } | null;
  static_only: boolean;
};

export type PatchValidationListItem = Pick<
  PatchValidationRun,
  | "validation_id"
  | "patch_id"
  | "analysis_id"
  | "created_at"
  | "readiness"
  | "passed_count"
  | "warning_count"
  | "failed_count"
  | "unknown_count"
  | "provider"
  | "provider_model"
>;

export type PullRequestPreview = {
  repository_owner: string;
  repository_name: string;
  base_ref: string;
  base_commit_sha: string;
  branch_name: string;
  files_changed: number;
  edit_count: number;
  validation_readiness: "ready_for_review";
  tests_executed: boolean;
};

export type GitHubPullRequestRecord = {
  pr_record_id: string;
  analysis_id: string;
  patch_id: string;
  validation_id: string;
  repository_owner: string;
  repository_name: string;
  base_ref: string;
  base_commit_sha: string;
  branch_name: string;
  commit_sha: string | null;
  pull_request_number: number | null;
  pull_request_url: string | null;
  status: "preparing" | "created" | "failed";
  created_at: string;
  updated_at: string;
  provider: "mock" | "github_app";
  request_fingerprint: string;
  pull_request_profile_version: string;
  validation_readiness: "ready_for_review";
  files_changed: number;
  edit_count: number;
  modified_file_sha256: Record<string, string>;
  failure_code: string | null;
  failure_message: string | null;
  tests_executed: boolean;
};

export type PullRequestListItem = Pick<
  GitHubPullRequestRecord,
  | "pr_record_id"
  | "analysis_id"
  | "patch_id"
  | "validation_id"
  | "repository_owner"
  | "repository_name"
  | "branch_name"
  | "pull_request_number"
  | "pull_request_url"
  | "status"
  | "created_at"
  | "validation_readiness"
>;

export type AnalysisReportSummary = {
  total_changes: number;
  breaking_changes: number;
  potentially_breaking_changes: number;
  non_breaking_changes: number;
  repository_matches: number;
  impacted_files: number;
  direct_matches: number;
  transitive_matches: number;
  max_impact_depth: number;
  risk_predictions: number;
  migration_recommendations: number;
  patch_proposals: number;
  patch_validations: number;
  pull_requests: number;
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
  patches: PatchProposal[];
  patch_validations: PatchValidationRun[];
  pull_requests: GitHubPullRequestRecord[];
  pipeline: Array<Record<string, unknown>>;
};

export type MonitorCheckStatus =
  | "checking"
  | "unchanged"
  | "changed"
  | "failed";

export type ApiMonitor = {
  monitor_id: string;
  name: string;
  source_type: "http_url" | "github_file";
  specification_url: string | null;
  source_path: string | null;
  repository_connection_id: string | null;
  contract_type: "openapi" | "graphql" | null;
  repository_url: string | null;
  repository_ref: string | null;
  check_interval_minutes: number;
  enabled: boolean;
  baseline_filename: string;
  baseline_sha256: string;
  baseline_observed_at: string;
  created_at: string;
  updated_at: string;
  last_checked_at: string | null;
  last_changed_at: string | null;
  last_successful_analysis_id: string | null;
  last_check_status: MonitorCheckStatus | null;
  last_error_code: string | null;
  last_error_message: string | null;
};

export type MonitorCheck = {
  check_id: string;
  monitor_id: string;
  status: MonitorCheckStatus;
  checked_at: string;
  completed_at: string | null;
  duration_ms: number | null;
  previous_spec_hash: string;
  observed_spec_hash: string | null;
  analysis_id: string | null;
  error_code: string | null;
  error_message: string | null;
};

export type CreateMonitorInput = {
  name: string;
  source_type?: "http_url" | "github_file";
  specification_url?: string;
  source_path?: string;
  repository_connection_id?: string;
  repository_url?: string;
  repository_ref?: string;
  check_interval_minutes: number;
  enabled: boolean;
};

export async function getMigrationProviderStatus(): Promise<MigrationProviderStatus> {
  return requestJson<MigrationProviderStatus>(
    "/api/v1/migration/provider",
  );
}

export async function compareSpecifications(
  oldSpec: File,
  newSpec: File,
  contractType: ContractTypeSelection = "auto",
): Promise<ComparisonResponse> {
  const formData = new FormData();

  formData.append("old_contract", oldSpec);
  formData.append("new_contract", newSpec);
  formData.append("contract_type", contractType);

  return requestJson<ComparisonResponse>(
    "/api/v1/contracts/compare",
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
  contractType: ContractTypeSelection = "auto",
): Promise<ImpactAnalysisResponse> {
  const formData = new FormData();

  formData.append("old_spec", oldSpec);
  formData.append("new_spec", newSpec);
  formData.append("repository", repository);
  formData.append("contract_type", contractType);

  return requestJson<ImpactAnalysisResponse>(
    "/api/v1/impact/analyze",
    {
      method: "POST",
      body: formData,
    },
  );
}

export async function analyzeConnectedRepositoryImpact(
  oldSpec: File,
  newSpec: File,
  repositoryId: string,
  ref?: string,
  contractType: ContractTypeSelection = "auto",
): Promise<ImpactAnalysisResponse> {
  const formData = new FormData();
  formData.append("old_spec", oldSpec);
  formData.append("new_spec", newSpec);
  formData.append("repository_id", repositoryId);
  if (ref?.trim()) formData.append("ref", ref.trim());
  formData.append("contract_type", contractType);
  return requestJson<ImpactAnalysisResponse>("/api/v1/impact/analyze/connected", {
    method: "POST",
    body: formData,
  });
}

export async function analyzeGitHubRepositoryImpact(
  oldSpec: File,
  newSpec: File,
  repositoryUrl: string,
  ref?: string,
  contractType: ContractTypeSelection = "auto",
): Promise<ImpactAnalysisResponse> {
  const formData = new FormData();

  formData.append("old_spec", oldSpec);
  formData.append("new_spec", newSpec);
  formData.append("repository_url", repositoryUrl.trim());
  formData.append("contract_type", contractType);

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
    { credentials: "include" },
  );

  if (!response.ok) {
    throw new Error(await getErrorMessage(response));
  }

  return response.blob();
}

export async function generatePatchProposal(
  analysisId: string,
  repository?: File | null,
): Promise<PatchProposal> {
  const formData = new FormData();
  if (repository) {
    formData.append("repository", repository);
  }
  return requestJson<PatchProposal>(
    `/api/v1/analyses/${analysisId}/patches`,
    { method: "POST", body: formData },
  );
}

export async function getPatchProposals(
  analysisId: string,
): Promise<PatchProposalListItem[]> {
  return requestJson<PatchProposalListItem[]>(
    `/api/v1/analyses/${analysisId}/patches`,
  );
}

export async function getPatchProposal(
  analysisId: string,
  patchId: string,
): Promise<PatchProposal> {
  return requestJson<PatchProposal>(
    `/api/v1/analyses/${analysisId}/patches/${patchId}`,
  );
}

export async function validatePatchProposal(
  analysisId: string,
  patchId: string,
  repository?: File | null,
): Promise<PatchValidationRun> {
  const formData = new FormData();
  if (repository) formData.append("repository", repository);
  return requestJson<PatchValidationRun>(
    `/api/v1/analyses/${analysisId}/patches/${patchId}/validations`,
    { method: "POST", body: formData },
  );
}

export async function getPatchValidations(
  analysisId: string,
  patchId: string,
): Promise<PatchValidationListItem[]> {
  return requestJson<PatchValidationListItem[]>(
    `/api/v1/analyses/${analysisId}/patches/${patchId}/validations`,
  );
}

export async function getPatchValidation(
  analysisId: string,
  patchId: string,
  validationId: string,
): Promise<PatchValidationRun> {
  return requestJson<PatchValidationRun>(
    `/api/v1/analyses/${analysisId}/patches/${patchId}/validations/${validationId}`,
  );
}

export async function previewPullRequest(
  analysisId: string,
  patchId: string,
  validationId: string,
): Promise<PullRequestPreview> {
  return requestJson<PullRequestPreview>(
    `/api/v1/analyses/${analysisId}/patches/${patchId}/validations/${validationId}/pull-request/preview`,
  );
}

export async function createPullRequest(
  analysisId: string,
  patchId: string,
  validationId: string,
): Promise<GitHubPullRequestRecord> {
  return requestJson<GitHubPullRequestRecord>(
    `/api/v1/analyses/${analysisId}/patches/${patchId}/validations/${validationId}/pull-request`,
    { method: "POST" },
  );
}

export async function getPullRequests(
  analysisId: string,
): Promise<PullRequestListItem[]> {
  return requestJson<PullRequestListItem[]>(
    `/api/v1/analyses/${analysisId}/pull-requests`,
  );
}

export async function getPullRequest(
  analysisId: string,
  pullRequestRecordId: string,
): Promise<GitHubPullRequestRecord> {
  return requestJson<GitHubPullRequestRecord>(
    `/api/v1/analyses/${analysisId}/pull-requests/${pullRequestRecordId}`,
  );
}

export async function getMonitors(): Promise<ApiMonitor[]> {
  return requestJson<ApiMonitor[]>("/api/v1/monitors");
}

export async function createMonitor(
  input: CreateMonitorInput,
): Promise<ApiMonitor> {
  return requestJson<ApiMonitor>("/api/v1/monitors", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function updateMonitor(
  monitorId: string,
  input: Partial<CreateMonitorInput>,
): Promise<ApiMonitor> {
  return requestJson<ApiMonitor>(
    `/api/v1/monitors/${monitorId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
  );
}

export async function deleteMonitor(
  monitorId: string,
): Promise<void> {
  const response = await fetch(
    `${API_BASE_URL}/api/v1/monitors/${monitorId}`,
    {
      method: "DELETE",
      credentials: "include",
      headers: csrfToken ? { "X-CSRF-Token": csrfToken } : undefined,
    },
  );
  if (!response.ok) {
    throw new Error(await getErrorMessage(response));
  }
}

export async function checkMonitor(
  monitorId: string,
): Promise<MonitorCheck> {
  return requestJson<MonitorCheck>(
    `/api/v1/monitors/${monitorId}/check`,
    { method: "POST" },
  );
}

export async function getMonitorChecks(
  monitorId: string,
): Promise<MonitorCheck[]> {
  return requestJson<MonitorCheck[]>(
    `/api/v1/monitors/${monitorId}/checks`,
  );
}

export type WorkspaceRole = "owner" | "admin" | "developer" | "viewer";
export type WorkspaceSummary = { id: string; name: string; slug: string; role: WorkspaceRole };
export type WorkspaceMember = {
  user_id: string;
  github_login: string;
  github_display_name: string | null;
  avatar_url: string | null;
  email: string | null;
  role: WorkspaceRole;
  joined_at: string;
};
export type AuthStatus = {
  mode: "local" | "github";
  authenticated: boolean;
  development_auth: boolean;
  github_auth_configured: boolean;
  google_auth_configured: boolean;
  user: { id: string; github_login: string; github_display_name: string | null; avatar_url: string | null; auth_provider: string; email: string | null } | null;
  workspace: WorkspaceSummary | null;
  workspaces: WorkspaceSummary[];
  csrf_token: string | null;
};
export type GitHubInstallation = { id: string; github_installation_id: number; account_id: number; account_login: string; account_type: string; connected_at: string; revoked: boolean };
export type RepositoryConnection = { id: string; installation_id: string; github_repository_id: number; owner: string; name: string; full_name: string; default_branch: string; private: boolean; html_url: string; enabled: boolean; last_synced_at: string; removed: boolean };

let csrfToken: string | null = null;

export async function getAuthStatus(): Promise<AuthStatus> {
  const status = await requestJson<AuthStatus>("/api/v1/auth/status");
  csrfToken = status.csrf_token;
  return status;
}

export function githubSignInUrl(
  identity?: "primary" | "secondary",
  returnTo?: string,
): string {
  const query = new URLSearchParams();
  if (identity) query.set("identity", identity);
  if (returnTo) query.set("return_to", returnTo);
  const suffix = query.size ? "?" + query.toString() : "";
  return API_BASE_URL + "/api/v1/auth/github/start" + suffix;
}
export function githubInstallationStartUrl(): string {
  return `${API_BASE_URL}/api/v1/github/installations/start`;
}

export async function createWorkspace(name: string): Promise<WorkspaceSummary> {
  return requestJson<WorkspaceSummary>("/api/v1/auth/workspaces", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export async function switchWorkspace(workspaceId: string): Promise<WorkspaceSummary> {
  return requestJson<WorkspaceSummary>("/api/v1/auth/workspaces/switch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ workspace_id: workspaceId }),
  });
}

export async function getWorkspaceMembers(): Promise<WorkspaceMember[]> {
  return requestJson<WorkspaceMember[]>("/api/v1/auth/workspaces/current/members");
}

export async function updateWorkspaceMemberRole(
  userId: string,
  role: WorkspaceRole,
): Promise<WorkspaceMember> {
  return requestJson<WorkspaceMember>(
    `/api/v1/auth/workspaces/current/members/${userId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role }),
    },
  );
}

export async function removeWorkspaceMember(userId: string): Promise<void> {
  const response = await fetch(
    `${API_BASE_URL}/api/v1/auth/workspaces/current/members/${userId}`,
    {
      method: "DELETE",
      credentials: "include",
      headers: csrfToken ? { "X-CSRF-Token": csrfToken } : undefined,
    },
  );
  if (!response.ok) throw new Error(await getErrorMessage(response));
}

export async function logout(): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/v1/auth/logout`, {
    method: "POST",
    credentials: "include",
    headers: csrfToken ? { "X-CSRF-Token": csrfToken } : undefined,
  });
  if (!response.ok) throw new Error(await getErrorMessage(response));
  csrfToken = null;
}

export async function getGitHubInstallations(): Promise<GitHubInstallation[]> {
  return requestJson<GitHubInstallation[]>("/api/v1/github/installations");
}
export async function connectGitHubInstallation(githubInstallationId: number): Promise<GitHubInstallation> {
  return requestJson<GitHubInstallation>("/api/v1/github/installations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ github_installation_id: githubInstallationId }),
  });
}
export async function syncGitHubInstallation(installationId: string): Promise<RepositoryConnection[]> {
  return requestJson<RepositoryConnection[]>(`/api/v1/github/installations/${installationId}/sync`, { method: "POST" });
}
export async function getRepositoryConnections(): Promise<RepositoryConnection[]> {
  return requestJson<RepositoryConnection[]>("/api/v1/github/repositories");
}
export async function setRepositoryConnectionEnabled(id: string, enabled: boolean): Promise<RepositoryConnection> {
  return requestJson<RepositoryConnection>(`/api/v1/github/repositories/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
}
export async function requestJson<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const method = (options?.method ?? "GET").toUpperCase();
  const headers = new Headers(options?.headers);
  if (
    csrfToken &&
    method !== "GET" &&
    method !== "HEAD" &&
    method !== "OPTIONS"
  ) {
    headers.set("X-CSRF-Token", csrfToken);
  }
  let response: Response;
  try {
    response = await fetch(
      `${API_BASE_URL}${path}`,
      {
        ...options,
        credentials: "include",
        headers,
      },
    );
  } catch {
    throw new Error(
      "DriftGuard could not reach the API. Check that the service is running and try again.",
    );
  }

  if (!response.ok) {
    if (response.status === 401 && path !== "/api/v1/auth/status") {
      window.dispatchEvent(new Event("driftguard:session-expired"));
    }
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
