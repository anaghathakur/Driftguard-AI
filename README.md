# DriftGuard AI

DriftGuard AI detects API contract drift, connects changes to likely source-code usage,
classifies change risk with explainable local models, and keeps a local analysis history.

## Current milestone

Milestone 4 adds explainable local risk classification to the durable analysis pipeline from
Milestone 3. It includes:

- safe extension and size validation;
- OpenAPI structure validation with local `$ref` resolution;
- normalized operations, parameters, request fields, responses, authentication, enums, and descriptions;
- deterministic change classification independent of an AI provider;
- structured FastAPI error responses;
- in-memory ZIP scanning with path traversal, link, encryption, archive size,
  decompressed size, file count, per-file size, and compression-ratio defenses;
- source allowlisting and generated/dependency directory exclusions;
- deterministic matching by OpenAPI `operationId`, path template, and HTTP method;
- local SQLite persistence behind an application repository interface;
- injected persistence and pipeline services;
- UTC analysis, pipeline-stage, completion, and failure timestamps;
- SHA-256 file hashes and byte-level duplicate-request fingerprints;
- transactional result writes and foreign-key cascade deletion;
- safe persisted failures without tracebacks, archives, or complete source files;
- analysis history, detail, change, match, pipeline, and deletion endpoints;
- deterministic per-change feature generation with a versioned feature schema;
- a transparent rule-based risk score with human-readable reasons;
- a reproducible, fixed-seed synthetic training dataset generator;
- held-out Logistic Regression and Random Forest comparison;
- a versioned, checksum-validated Joblib model and JSON metadata;
- model probabilities and local feature drivers alongside the rule baseline;
- safe deterministic fallback when the artifact is missing, invalid, or incompatible;
- transactional risk-prediction persistence and risk-query endpoints;
- a recorded `classify_risk` pipeline stage;
- focused unit and API tests.

Gemini, BigQuery, Docker, automatic code fixes, and the web dashboard are intentionally not implemented yet.

## Run locally

From the repository root on Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".\apps\api[dev]"
.\.venv\Scripts\python.exe -m uvicorn apps.api.app.main:app --reload
```

The database is created automatically at `data/driftguard.sqlite3`. Override the location
with `DRIFTGUARD_DATABASE_PATH`; all supported settings are listed in `.env.example`.

Open `http://127.0.0.1:8000/docs` and use `POST /api/v1/specifications/compare`, or run the included payment demo:

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/specifications/compare `
  -F "old_spec=@sample-data/specifications/payments-old.yaml" `
  -F "new_spec=@sample-data/specifications/payments-new.yaml"
```

For repository-aware analysis, first create the demo ZIP:

```powershell
Compress-Archive -Path ".\sample-data\repositories\payment-client\*" `
  -DestinationPath "$env:TEMP\payment-client.zip" -Force
```

Then use `POST /api/v1/impact/analyze` in Swagger with:

- `old_spec`: `sample-data/specifications/payments-old.yaml`
- `new_spec`: `sample-data/specifications/payments-new.yaml`
- `repository`: `$env:TEMP\payment-client.zip`

To analyze a public GitHub repository without creating a ZIP, use
`POST /api/v1/impact/analyze/github` with:

- `old_spec`: `sample-data/specifications/payments-old.yaml`
- `new_spec`: `sample-data/specifications/payments-new.yaml`
- `repository_url`: an HTTPS URL such as `https://github.com/owner/repository`
- `ref`: an optional branch, tag, or commit SHA; omit it to use the default branch

GitHub acquisition accepts only `github.com` repository URLs, validates the archive redirect
against `codeload.github.com`, and enforces the configured request timeout and archive byte limit.
The downloaded ZIP remains in memory and passes through the same secure repository scanner as an
uploaded ZIP.

The response includes `analysis_id` and `duplicate`. Use the ID with:

- `GET /api/v1/analyses`
- `GET /api/v1/analyses/{analysis_id}`
- `GET /api/v1/analyses/{analysis_id}/changes`
- `GET /api/v1/analyses/{analysis_id}/matches`
- `GET /api/v1/analyses/{analysis_id}/pipeline`
- `GET /api/v1/analyses/{analysis_id}/risks`
- `GET /api/v1/analyses/{analysis_id}/risks/{change_id}`
- `DELETE /api/v1/analyses/{analysis_id}`

Use `GET /api/v1/risk/model` to inspect the active model version, artifact checksum,
candidate metrics, or deterministic fallback status.

Submitting the exact same file bytes again returns the stored result with `duplicate: true`
and does not create another analysis. The fingerprint includes the analysis-pipeline version, so
resubmitting a Milestone 3 request creates a new Milestone 4 analysis with risk predictions.

## Verify

```powershell
.\.venv\Scripts\python.exe -m pytest -c apps/api/pyproject.toml apps/api/tests
.\.venv\Scripts\python.exe -m ruff check --config apps/api/pyproject.toml apps/api
```

## Train the local risk model

The committed `v1.0.0` artifact is reproducible from generated synthetic data:

```powershell
.\.venv\Scripts\python.exe -m apps.api.app.risk.training
```

Defaults are 4,000 samples, seed `42`, a stratified 75/25 split, and output under
`apps/api/models/risk/v1.0.0`. Metadata records the dataset hash, artifact hash, split,
feature schema, and training-library versions. The current held-out synthetic metrics are:

| Candidate | Accuracy | Balanced accuracy | Macro-F1 |
| --- | ---: | ---: | ---: |
| Logistic Regression | 0.908000 | 0.906750 | 0.904413 |
| Random Forest | 0.888000 | 0.886599 | 0.883029 |

Logistic Regression is selected by macro-F1. These metrics describe generated synthetic labels
only; they are not evidence of production accuracy or business impact.

## Architecture direction

The MVP is a modular monolith. FastAPI routes receive the analysis pipeline through dependency
injection. The pipeline uses an `AnalysisRepository` port; SQLite is the current local adapter.
Deterministic contract and impact logic remains independent of persistence and external providers.

The Milestone 4 flow is:

```text
uploads -> SHA-256 hashes + request fingerprint -> create or find analysis
       -> recorded validation/comparison/scan/match stages
       -> deterministic features -> model prediction or rule fallback
       -> transactional changes + limited matches + risk predictions + metadata write
       -> stored response or safe persisted failure
```

SQLite contains six related application tables:

- `analyses` owns metadata, hashes, fingerprints, summaries, and lifecycle timestamps;
- `analysis_changes` belongs to an analysis;
- `repository_matches` belongs to a persisted change;
- `risk_predictions` belongs to a persisted change and stores features, scores, explanations,
  model provenance, and probabilities;
- `pipeline_stages` belongs to an analysis;
- `analysis_failures` belongs to an analysis.

All child rows are deleted through foreign-key cascades when an analysis is deleted.

## Current limitations

- Only OpenAPI 3.x is accepted.
- Only local JSON Pointer `$ref` values are resolved; remote references are rejected.
- Schema comparison currently focuses on object properties relevant to the MVP, including nested properties represented as dotted paths.
- Repository input supports uploaded ZIPs and public GitHub repositories. Private repositories,
  GitHub authentication/App installation, and remote Git cloning are not included.
- Matching is deterministic and lexical. It recognizes literal/templated paths, nearby HTTP
  methods, and operation IDs, but does not build language ASTs or resolve runtime URL construction.
- Server route declarations can look like client usage and may be reported as matches.
- UTF-8 source files in the configured extension allowlist are scanned; binary, non-UTF-8,
  dependency, generated, oversized, and unsupported files are skipped or rejected as appropriate.
- Matches are capped at 100 locations per contract change.
- Duplicate detection is byte-based. Repacking identical source files can change ZIP metadata
  and therefore produces a different repository hash and fingerprint.
- Failed duplicate submissions replay the stored safe error; delete the failed analysis before
  intentionally retrying the exact same bytes.
- SQLite schema initialization is automatic, but migrations and multi-database support are not
  included yet.
- The API has no authentication or multi-tenant isolation and is intended for trusted local use.
- Analysis execution is synchronous; SQLite is appropriate for this local milestone, not a
  horizontally scaled deployment.
- Risk-model labels are synthetic and encode the initial engineering risk policy. Real-world
  calibration, drift monitoring, and outcome-based validation are not implemented yet.
- Historical analyses created before Milestone 4 are retained but are not backfilled; their risk
  endpoints return an empty list until the inputs are resubmitted under the versioned pipeline.
- Joblib artifacts can execute Python during loading. DriftGuard loads only the configured local
  artifact, verifies its SHA-256 against metadata, and must never be pointed at an untrusted file.
- A failed model load is cached for the process lifetime; install or replace the artifact and
  restart the API to activate it.
- Risk classification ranks engineering review priority; it must not be treated as an autonomous
  approval or deployment decision.
