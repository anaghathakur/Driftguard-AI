# DriftGuard AI

DriftGuard AI detects API contract drift, connects changes to likely source-code usage,
classifies change risk with explainable local models, and keeps a local analysis history.

## Current milestone

Phase 13 adds patch validation and test intelligence to the existing OpenAPI comparison, deep
impact analysis, monitoring, ML risk, migration guidance, review-only patch proposals,
persistence, reporting, and React dashboard. DriftGuard can now compare a proposed patch with the
new contract, inspect deterministic caller problems, discover related tests, surface test gaps,
and recommend a bounded test plan without executing repository code or tests.

## Patch validation and test intelligence

Validation is an explicit developer action on a Phase 12 patch. GitHub-backed analyses securely
re-fetch through `GitHubRepositorySource`; ZIP-backed analyses require the original ZIP again.
The archive SHA-256 must match both the analysis and patch fingerprints. DriftGuard then ignores
the stored unified diff as an application mechanism and replays the persisted structured edits
through the trusted Phase 12 applicator into an in-memory source snapshot. Repository files are
never written.

Under validation profile `1.0.0`, DriftGuard re-runs the Phase 11 analyzer against that patched
snapshot and checks statically resolvable endpoint/method usage, required request fields, removed
request fields, modified signatures, resolved callers, and patch blast radius. Python uses AST
inspection; JavaScript and TypeScript use conservative static parsing. Dynamic payloads and
unresolved calls produce `UNKNOWN` or warnings, not false failures. A supported stale-value case
looks like this:

```text
POST /payments: email removed, customer_id required
        -> proposed payment-client patch
        -> contract checks pass
        -> checkout still passes order["email"] into customer_id
        -> NEEDS REVIEW
        -> recommend unit, integration, negative, and regression tests
```

Test discovery recognizes Python `test_*.py`, `*_test.py`, and `tests/`, plus JavaScript/
TypeScript `*.test.*`, `*.spec.*`, and `__tests__/`. Relevance is explainable and categorical:
`HIGH` for direct symbols/endpoints/fields, `MEDIUM` for impacted callers, and `LOW` for a weak
module or directory relationship. A discovered test is reported as related; DriftGuard never
claims runtime coverage. Missing tests for impacted symbols are explicit test gaps.

Readiness is deterministic and cannot be selected by an AI provider:

- `BLOCKED` means a definite static failure such as a missing required field, a removed field
  still sent, an incompatible caller, or an out-of-scope edit.
- `NEEDS_REVIEW` means meaningful uncertainty, stale-value propagation, or missing direct tests.
- `READY_FOR_REVIEW` means the bounded static checks found no blocking or meaningful unresolved
  migration issue. It does not mean safe to deploy.

The zero-cost mock test-plan provider derives contract, unit, integration, negative, and
regression recommendations from persisted changes and impact paths. Optional Gemini uses the same
configured key/model and receives only bounded secret-redacted structured context—not the whole
repository. Repository content remains hostile untrusted data, provider output is schema checked,
and the provider cannot execute tests, request secrets, modify readiness, or modify files.

Validation results persist as bounded `PatchValidationRun` records with findings, related tests,
gaps, test cases, snapshot/profile fingerprints, and provider provenance. SQLite uses a cascading
`patch_validation_runs` table; Firestore stores validations below the patch document. Repeated
identical validation requests reuse the same deterministic fingerprint, and deleting an analysis
removes its patches and validations. JSON/PDF reports and the existing patch-review UI include
the latest bounded validation intelligence.

Endpoints:

- `POST /api/v1/analyses/{analysis_id}/patches/{patch_id}/validations`
- `GET /api/v1/analyses/{analysis_id}/patches/{patch_id}/validations`
- `GET /api/v1/analyses/{analysis_id}/patches/{patch_id}/validations/{validation_id}`

Phase 13 limits are configurable:

```text
DRIFTGUARD_TEST_PLAN_PROVIDER=mock
DRIFTGUARD_MAX_VALIDATION_FINDINGS=100
DRIFTGUARD_MAX_RELATED_TESTS=50
DRIFTGUARD_MAX_TEST_PLAN_CASES=12
DRIFTGUARD_MAX_TEST_CONTEXT_BYTES=40000
```

This phase performs static validation only. It never imports repository modules, runs Python or
JavaScript, executes tests/builds/package managers/scripts, applies a patch to a repository,
creates Git branches or commits, pushes code, creates pull requests, or deploys anything.

## AI-assisted proposed patch generation

Patch generation is an explicit developer action on a completed repository-impact analysis. It is
grounded in the exact contract changes, Phase 11 symbols and evidence traces, persisted migration
recommendations, risk context, and a verified copy of the original repository snapshot.

Public GitHub analyses retain the safe repository URL/ref and re-fetch through the existing
bounded GitHub source. The fetched archive SHA-256 must equal the analyzed archive hash. Uploaded
ZIP analyses do not persist their archive and therefore require the developer to upload the exact
original ZIP again. A missing source returns `repository_source_required`; changed bytes return
`repository_snapshot_mismatch` and require a new analysis.

Providers return strict Pydantic-validated structured edits containing an exact original anchor,
replacement, reason, and related contract-change IDs. Providers cannot choose their own security
scope. Phase 12 restricts edits to direct impacted source files, rejects unsafe or unknown paths,
requires each original anchor to exist exactly once, rejects duplicate/overlapping edits, and
enforces file, edit, replacement, context, and diff limits. Transitive callers remain evidence but
are not modified when the direct API client is sufficient.

Validated edits are applied only to source strings held in memory. Python results must parse with
`ast.parse`; JavaScript and TypeScript use the safe Phase 11 delimiter/token validation. DriftGuard
then creates the unified diff with trusted standard-library code—the provider never controls diff
paths, hunk headers, or line metadata. No repository code, tests, builds, package tools, Git
commands, commits, branches, pushes, or pull requests are run.

The deterministic mock patch provider remains the zero-cost default and conservatively supports
removed request fields, newly required request fields, and clear removed-plus-required field
renames. Optional Gemini generation reuses the existing credentials, timeout, and model settings;
it receives bounded secret-redacted context with repository source explicitly labelled as hostile
untrusted data. Every Gemini result still passes the same trusted validation.

Patch proposals persist only bounded metadata, edits, validation results, provider/model/profile
provenance, warnings, and unified diff. Repository archives and source trees remain transient.
SQLite uses a cascading `patch_proposals` table; Firestore uses an analysis patch subcollection.
Repeated identical requests reuse a fingerprinted proposal under patch profile `1.0.0`.

The review workflow is available through:

- `POST /api/v1/analyses/{analysis_id}/patches` generates or reuses a proposal; attach the
  original `repository` ZIP for ZIP-backed analyses and omit it for GitHub-backed analyses.
- `GET /api/v1/analyses/{analysis_id}/patches` lists proposals.
- `GET /api/v1/analyses/{analysis_id}/patches/{patch_id}` returns full validation and diff detail.

The frontend displays validation checks, an escaped line-oriented diff, provider provenance, and
a prominent statement that no repository file was modified. JSON/PDF reports include bounded
proposal metadata and a diff excerpt. Monitoring does not generate patches automatically, but a
monitor-created analysis can request one manually.

Phase 12 limits are configurable:

```text
DRIFTGUARD_MAX_PATCH_FILES=5
DRIFTGUARD_MAX_PATCH_EDITS=20
DRIFTGUARD_MAX_PATCH_CONTEXT_BYTES=40000
DRIFTGUARD_MAX_PATCH_REPLACEMENT_BYTES=20000
DRIFTGUARD_MAX_PATCH_DIFF_BYTES=100000
```

## Deeper Code Impact Intelligence

DriftGuard performs deterministic static analysis for Python, JavaScript, and TypeScript source
files. It parses repository text once, indexes functions and methods, resolves local imports and
safe string expressions, builds a bounded call graph, and propagates API impact through callers.
For example:

```text
POST /payments
  -> payment_client.create_payment   direct API usage, depth 0
  -> checkout.checkout               wrapper caller, depth 1
  -> orders.submit_order             transitive caller, depth 2
```

Direct HTTP recognition covers common `requests`, `httpx`, client/session method calls, `fetch`,
Axios-style methods, and object-style client requests. Endpoint resolution is intentionally
limited to literals, local constant references, simple concatenation, and simple f-string/template
constants. Unknown expressions are not evaluated.

Each deep match retains its source location, language, enclosing symbol, impact depth, confidence,
and a bounded evidence trace. Exact resolved path plus HTTP method anchors are high confidence;
deterministically resolved local callers are medium confidence. Import resolution is local and
precision-oriented: ambiguous same-named functions are not connected.

Unsupported languages, dynamically constructed endpoints, and individual parser failures retain
the existing lexical matcher. Exact lexical/semantic duplicates are collapsed to the strongest
evidence, while transitive caller locations remain separate. Static-analysis summary metadata
reports supported files, parser failures, symbols, resolved call edges, direct anchors, and
transitive matches.

Repository code is never executed, imported, compiled, tested, or passed to Node/package tooling.
Only bounded source-text parsing is performed. Phase 11 is not whole-program analysis and does not
resolve package-manager graphs, runtime dependency injection, reflection, or arbitrary data flow.

Resource limits are configurable:

```text
DRIFTGUARD_MAX_CODE_SYMBOLS=10000
DRIFTGUARD_MAX_CODE_GRAPH_EDGES=25000
DRIFTGUARD_MAX_IMPACT_DEPTH=3
```

Global symbol/edge/anchor limit violations fail with a controlled error. Per-file parser failures
are reported and degraded to lexical matching. Cycles are bounded with shortest-depth visitation.
Identical Phase 11 inputs use pipeline profile `5.0.0`, preventing older shallow analyses from
being reused as duplicates.

An API monitor stores a bounded OpenAPI baseline plus its SHA-256 hash, the public GitHub
repository to inspect, and a check interval. Creation validates and stores the current contract as
the baseline without running an impact analysis. Later checks fetch and validate the URL again:

- identical bytes record `unchanged` and skip GitHub, ML, and migration work;
- changed bytes run the existing GitHub impact pipeline and link the resulting analysis;
- a successful changed check atomically advances the baseline;
- a failed check records a safe error and retains the old baseline for retry.

Repository archives and source files are never persisted or executed. Baseline OpenAPI bytes are
persisted because deterministic future comparison requires the original bounded document. Treat
monitor storage as sensitive if upstream contracts contain confidential examples or descriptions.

## Monitor API

- `POST /api/v1/monitors` creates a monitor and establishes its baseline.
- `GET /api/v1/monitors` lists monitor status.
- `GET /api/v1/monitors/{monitor_id}` returns monitor details.
- `PATCH /api/v1/monitors/{monitor_id}` updates configuration; changing the specification URL
  establishes a fresh baseline without analysis.
- `DELETE /api/v1/monitors/{monitor_id}` deletes the monitor and check history.
- `POST /api/v1/monitors/{monitor_id}/check` checks immediately.
- `GET /api/v1/monitors/{monitor_id}/checks` returns newest-first check history.

The dashboard's **API Monitors** area supports creation, enable/disable, Check now, history,
deletion, and opening the latest successful analysis.

## Remote OpenAPI security

Remote specifications are HTTPS-only, bounded by `DRIFTGUARD_MAX_SPEC_FILE_BYTES`, fetched with a
timeout and explicit redirect limit, and parsed through the existing OpenAPI validator. URLs with
credentials, ports, fragments, localhost/private/link-local/multicast/reserved destinations, and
cloud metadata destinations are rejected. Every redirect is revalidated and automatic redirect
following is disabled.

DNS is validated before each request, but the HTTP client subsequently performs its own DNS
resolution. A hostile authoritative DNS server could theoretically rebind between those steps.
Production deployment should add network-level egress controls or a pinned-address transport;
this MVP does not claim perfect DNS-rebinding resistance.

## Automatic scheduler

The zero-cost scheduler runs inside the FastAPI process. It checks enabled monitors whose interval
has elapsed, skips disabled/not-yet-due monitors, prevents overlapping checks within the process,
isolates monitor failures, and stops cleanly during application shutdown. It is disabled by
default so tests and local API startup are deterministic.

Enable it with:

```text
DRIFTGUARD_MONITOR_SCHEDULER_ENABLED=true
DRIFTGUARD_MONITOR_POLL_SECONDS=30
```

This scheduler is process-local. Multiple API workers can schedule the same monitor, so use one
worker when it is enabled. A future external scheduler/worker can call the same monitor check
service without changing the analysis pipeline.

## Run locally

From the repository root on Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".\apps\api[dev]"
.\.venv\Scripts\python.exe -m uvicorn apps.api.app.main:app --reload
```

The database is created automatically at `data/driftguard.sqlite3`. Override the location
with `DRIFTGUARD_DATABASE_PATH`; all supported settings are listed in `.env.example`.

For zero-cost local monitoring, leave the mock migration provider enabled, create a monitor in the
dashboard, and either use **Check now** or enable the process-local scheduler. No paid queue,
Redis, cloud scheduler, or GitHub service is required.

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
- `GET /api/v1/analyses/{analysis_id}/patches`
- `GET /api/v1/analyses/{analysis_id}/patches/{patch_id}`
- `POST /api/v1/analyses/{analysis_id}/patches`
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

The MVP is a modular monolith. FastAPI routes receive analysis and monitoring services through
dependency injection. Separate repository ports have SQLite local-default and Firestore adapters.
Deterministic contract and impact logic remains independent of scheduling and repository
acquisition.

The Phase 12 monitoring and manual patch flow is:

```text
create monitor -> secure OpenAPI fetch -> validate -> persist bounded V1 baseline
scheduled/manual check -> secure fetch -> compare SHA-256
  unchanged -> record check only
  changed -> GitHub impact pipeline -> semantic code graph + lexical fallback
          -> ML + migration -> persist analysis -> atomically store check + V2
          -> developer explicitly requests snapshot-verified proposed patch
  failed -> safe check history error -> retain V1 for retry
```

SQLite contains the existing analysis tables plus two monitoring tables:

- `analyses` owns metadata, hashes, fingerprints, summaries, and lifecycle timestamps;
- `analysis_changes` belongs to an analysis;
- `repository_matches` belongs to a persisted change;
- `risk_predictions` belongs to a persisted change and stores features, scores, explanations,
  model provenance, and probabilities;
- `pipeline_stages` belongs to an analysis;
- `analysis_failures` belongs to an analysis.
- `patch_proposals` belongs to an analysis and stores bounded review-only proposal data.
- `api_monitors` stores configuration, bounded baseline content, hashes, and latest status;
- `monitor_checks` stores newest-first unchanged, changed, and failed check history.

Firestore stores the same monitor records and splits bounded baseline bytes into subdocuments to
stay below its per-document size limit. Repository archives remain transient on both backends.

## Current limitations

- Only OpenAPI 3.x is accepted.
- Only local JSON Pointer `$ref` values are resolved; remote references are rejected.
- Schema comparison currently focuses on object properties relevant to the MVP, including nested properties represented as dotted paths.
- Repository input supports uploaded ZIPs and public GitHub repositories. Private repositories,
  GitHub authentication/App installation, and remote Git cloning are not included.
- Remote OpenAPI monitoring requires a publicly reachable HTTPS endpoint; private/internal API
  endpoints are intentionally rejected by SSRF controls.
- The process-local scheduler is suitable for a single-worker MVP, not distributed scheduling.
- Pre-request DNS validation has a residual DNS-rebinding window; production should also enforce
  network-level egress restrictions.
- Matching is deterministic and lexical. It recognizes literal/templated paths, nearby HTTP
  methods, and operation IDs for all scanned extensions. Python, JavaScript, and TypeScript add
  bounded semantic analysis, but runtime URL construction and external package graphs remain
  unresolved.
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
  calibration and outcome-based validation are not implemented yet.
- Historical analyses created before Milestone 4 are retained but are not backfilled; their risk
  endpoints return an empty list until the inputs are resubmitted under the versioned pipeline.
- Joblib artifacts can execute Python during loading. DriftGuard loads only the configured local
  artifact, verifies its SHA-256 against metadata, and must never be pointed at an untrusted file.
- A failed model load is cached for the process lifetime; install or replace the artifact and
  restart the API to activate it.
- Risk classification ranks engineering review priority; it must not be treated as an autonomous
  approval or deployment decision.
- Patch generation is intentionally conservative and currently supports only Python,
  JavaScript, and TypeScript files with exact textual edit anchors. Complex refactors, dynamic
  data flow, external package graphs, formatting, semantic type checking, and repository tests
  remain outside static validation.
- A validated proposal is not proof that the application compiles, passes tests, or behaves
  correctly. Developers must review and apply it manually. Automatic patch application, Git
  commits, branches, pushes, and pull requests are not implemented.
