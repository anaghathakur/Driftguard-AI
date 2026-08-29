import "../analysis.css";
import type { Dispatch, SetStateAction } from "react";

export type AnalysisMode = "comparison" | "impact";
export type RepositorySourceMode = "upload" | "github" | "connected";

type NewAnalysisPageProps = {
  mode: AnalysisMode;
  setMode: Dispatch<SetStateAction<AnalysisMode>>;
  oldSpec: File | null;
  setOldSpec: Dispatch<SetStateAction<File | null>>;
  newSpec: File | null;
  setNewSpec: Dispatch<SetStateAction<File | null>>;
  repository: File | null;
  setRepository: Dispatch<SetStateAction<File | null>>;
  repositorySource: RepositorySourceMode;
  setRepositorySource: Dispatch<SetStateAction<RepositorySourceMode>>;
  connectedRepositories: Array<{ id: string; full_name: string; private: boolean }>;
  connectedRepositoryId: string;
  setConnectedRepositoryId: (id: string) => void;
  repositoryUrl: string;
  setRepositoryUrl: Dispatch<SetStateAction<string>>;
  repositoryRef: string;
  setRepositoryRef: Dispatch<SetStateAction<string>>;
  isAnalyzing: boolean;
  analysisError: string | null;
  canAnalyze: boolean;
  analysisRequirement: string;
  analysisProgress: string;
  onAnalyze: () => void;
};

const pipelineStages = [
  ["Validating specifications", "OpenAPI 3.x and local references"],
  ["Detecting contract changes", "Breaking and compatible changes"],
  ["Scanning repository", "Static source analysis when provided"],
  ["Building dependency graph", "Direct, wrapper, and transitive callers"],
  ["Calculating migration risk", "ML scoring with deterministic fallback"],
] as const;

export function NewAnalysisPage(props: NewAnalysisPageProps) {
  const {
    mode,
    setMode,
    oldSpec,
    setOldSpec,
    newSpec,
    setNewSpec,
    repository,
    setRepository,
    repositorySource,
    setRepositorySource,
    connectedRepositories,
    connectedRepositoryId,
    setConnectedRepositoryId,
    repositoryUrl,
    setRepositoryUrl,
    repositoryRef,
    setRepositoryRef,
    isAnalyzing,
    analysisError,
    canAnalyze,
    analysisRequirement,
    analysisProgress,
    onAnalyze,
  } = props;

  function selectRepositoryMode(nextMode: "none" | RepositorySourceMode) {
    if (nextMode === "none") {
      setMode("comparison");
      return;
    }
    setMode("impact");
    setRepositorySource(nextMode);
  }

  return (
    <section className="new-analysis-page">
      <header className="page-header">
        <div>
          <p className="page-eyebrow">New analysis</p>
          <h1 className="page-title">Analyze API Change</h1>
          <p className="page-subtitle">Compare two API contracts and optionally trace the change through a source repository.</p>
        </div>
      </header>

      <div className="analysis-layout">
        <div className="analysis-form-stack">
          <section className="panel analysis-section">
            <div className="analysis-section-heading">
              <span>1</span>
              <div><h2>API Contract</h2><p>JSON, YAML, and YML OpenAPI 3.x files are supported.</p></div>
            </div>
            <div className="contract-grid">
              <FileUpload
                id="current-contract"
                label="Current contract"
                description="The contract consumers use today"
                accept=".json,.yaml,.yml,application/json,application/yaml,text/yaml"
                file={oldSpec}
                disabled={isAnalyzing}
                onChange={setOldSpec}
              />
              <FileUpload
                id="new-contract"
                label="New contract"
                description="The proposed or newly released contract"
                accept=".json,.yaml,.yml,application/json,application/yaml,text/yaml"
                file={newSpec}
                disabled={isAnalyzing}
                onChange={setNewSpec}
              />
            </div>
          </section>

          <section className="panel analysis-section">
            <div className="analysis-section-heading">
              <span>2</span>
              <div><h2>Repository</h2><p>Optional. Add source to trace affected usages and dependency paths.</p></div>
            </div>

            <div role="group" aria-label="Repository source" className="segmented-control repository-mode-control">
              <Segment active={mode === "comparison"} disabled={isAnalyzing} onClick={() => selectRepositoryMode("none")}>No repository</Segment>
              <Segment active={mode === "impact" && repositorySource === "connected"} disabled={isAnalyzing || connectedRepositories.length === 0} onClick={() => selectRepositoryMode("connected")}>Connected repository</Segment>
              <Segment active={mode === "impact" && repositorySource === "github"} disabled={isAnalyzing} onClick={() => selectRepositoryMode("github")}>Public GitHub URL</Segment>
              <Segment active={mode === "impact" && repositorySource === "upload"} disabled={isAnalyzing} onClick={() => selectRepositoryMode("upload")}>Upload ZIP</Segment>
            </div>

            {mode === "comparison" && (
              <div className="repository-empty">
                DriftGuard will compare the contracts and generate risk and migration guidance without scanning source code.
              </div>
            )}

            {mode === "impact" && repositorySource === "connected" && (
              <label className="text-field" htmlFor="connected-repository">
                <span><strong>Connected repository</strong><em>Required</em></span>
                <small>Only enabled repositories authorized for this workspace are listed.</small>
                <select id="connected-repository" value={connectedRepositoryId} disabled={isAnalyzing} required onChange={(event) => setConnectedRepositoryId(event.target.value)}>
                  <option value="">Select repository</option>
                  {connectedRepositories.map((item) => <option key={item.id} value={item.id}>{item.full_name}{item.private ? " · Private" : " · Public"}</option>)}
                </select>
              </label>
            )}
            {mode === "impact" && repositorySource === "github" && (
              <div className="repository-fields">
                <TextField id="repository-url" type="url" label="Repository URL" help="Public github.com repository" value={repositoryUrl} placeholder="https://github.com/owner/repository" disabled={isAnalyzing} required onChange={setRepositoryUrl} />
                <TextField id="repository-ref" label="Branch / Tag / Ref" help="Optional; defaults to the repository default branch" value={repositoryRef} placeholder="main, v2.0.0, or commit SHA" disabled={isAnalyzing} onChange={setRepositoryRef} />
              </div>
            )}

            {mode === "impact" && repositorySource === "upload" && (
              <FileUpload id="repository-archive" label="Repository archive" description="Upload source as a ZIP archive" accept=".zip,application/zip" file={repository} disabled={isAnalyzing} onChange={setRepository} compact />
            )}

            <p className="security-note"><span aria-hidden="true">◇</span> Repository source is statically analyzed and never executed.</p>
          </section>

          {analysisError && <div role="alert" className="inline-alert inline-alert-danger analysis-error">{analysisError}</div>}

          <div className="analysis-submit-row">
            <p id="analysis-requirement" aria-live="polite">{isAnalyzing ? analysisProgress : analysisRequirement}</p>
            <button type="button" className="button-primary analysis-submit" disabled={!canAnalyze} aria-describedby="analysis-requirement" aria-busy={isAnalyzing} onClick={onAnalyze}>
              {isAnalyzing ? "Processing…" : "Analyze Changes"}
            </button>
          </div>
        </div>

        <aside className="panel pipeline-panel" aria-label="Analysis pipeline">
          <div className="panel-header">
            <div className="pipeline-title-row"><h2 className="panel-title">Analysis pipeline</h2><span className={`pipeline-state${isAnalyzing ? " is-processing" : ""}`}>{isAnalyzing ? "Processing" : "Ready"}</span></div>
            <p className="panel-copy">The API returns the completed analysis as one response. Stage labels below describe the bounded workflow, not streamed backend events.</p>
          </div>
          <ol className="pipeline-list">
            {pipelineStages.map(([label, detail], index) => {
              const skipped = mode === "comparison" && (index === 2 || index === 3);
              const state = skipped ? "Not required" : isAnalyzing ? (index === 0 ? "Processing" : "Queued") : "Pending";
              return (
                <li key={label} className={skipped ? "is-skipped" : ""}>
                  <span className="pipeline-marker">{index + 1}</span>
                  <span><strong>{label}</strong><small>{detail}</small></span>
                  <em>{state}</em>
                </li>
              );
            })}
          </ol>
        </aside>
      </div>
    </section>
  );
}

function Segment({ active, disabled, children, onClick }: { active: boolean; disabled: boolean; children: string; onClick: () => void }) {
  return <button type="button" aria-pressed={active} className={active ? "is-active" : ""} disabled={disabled} onClick={onClick}>{children}</button>;
}

function FileUpload({ id, label, description, accept, file, disabled, compact = false, onChange }: { id: string; label: string; description: string; accept: string; file: File | null; disabled: boolean; compact?: boolean; onChange: (file: File | null) => void }) {
  return (
    <label htmlFor={id} className={`file-upload${compact ? " file-upload-compact" : ""}${file ? " has-file" : ""}`}>
      <span aria-hidden="true" className="file-upload-icon">{file ? "✓" : "↑"}</span>
      <strong>{label}</strong>
      <span>{file ? file.name : description}</span>
      <small>{file ? `${formatBytes(file.size)} · Select a different file` : "Choose file"}</small>
      <input id={id} type="file" accept={accept} disabled={disabled} onChange={(event) => onChange(event.target.files?.[0] ?? null)} />
    </label>
  );
}

function TextField({ id, label, help, value, placeholder, disabled, required = false, type = "text", onChange }: { id: string; label: string; help: string; value: string; placeholder: string; disabled: boolean; required?: boolean; type?: string; onChange: (value: string) => void }) {
  return (
    <label htmlFor={id} className="text-field">
      <span><strong>{label}</strong>{required && <em>Required</em>}</span>
      <small>{help}</small>
      <input id={id} type={type} value={value} placeholder={placeholder} disabled={disabled} required={required} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
