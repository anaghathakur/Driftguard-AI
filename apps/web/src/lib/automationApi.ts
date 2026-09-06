import { requestJson } from "./api";

export type AutomationContract = {
  contract_id: string;
  contract_kind: "openapi" | "graphql";
  path: string;
  title: string;
  version: string;
  enabled: boolean;
  manually_configured: boolean;
  last_seen_commit: string;
  updated_at: string;
};

export type AutomationDependency = {
  dependency_id: string;
  evidence_type: string;
  confidence: number;
  confirmed: boolean;
  contract_id: string | null;
  monitor_id: string | null;
  source_path: string | null;
};

export type AutomationCheck = {
  check_record_id: string;
  status: string;
  conclusion: string | null;
  summary: string;
  analysis_id: string | null;
  updated_at: string;
};

export type RepositoryAutomation = {
  repository_id: string;
  automation_enabled: boolean;
  contracts: AutomationContract[];
  dependencies: AutomationDependency[];
  checks: AutomationCheck[];
};

export async function getRepositoryAutomation(id: string): Promise<RepositoryAutomation> {
  return requestJson<RepositoryAutomation>(`/api/v1/github/automation/repositories/${id}`);
}

export async function analyzeConnectedRepository(id: string): Promise<{ status: string }> {
  return requestJson<{ status: string }>(
    `/api/v1/github/automation/repositories/${id}/analyze`,
    { method: "POST" },
  );
}

export async function discoverRepositoryContracts(
  id: string,
): Promise<{ status: "completed"; commit_sha: string; contracts: AutomationContract[] }> {
  return requestJson(
    "/api/v1/github/automation/repositories/" + id + "/discover",
    { method: "POST" },
  );
}

export async function configureRepositoryContract(
  id: string,
  path: string,
): Promise<AutomationContract> {
  return requestJson<AutomationContract>(
    `/api/v1/github/automation/repositories/${id}/contracts`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    },
  );
}

export async function setRepositoryContractEnabled(
  repositoryId: string,
  contractId: string,
  enabled: boolean,
): Promise<AutomationContract> {
  return requestJson<AutomationContract>(
    `/api/v1/github/automation/repositories/${repositoryId}/contracts/${contractId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    },
  );
}
