# DriftGuard AI

DriftGuard AI detects API contract drift, connects changes to likely source-code usage,
and keeps a local analysis history.

## Current milestone

Milestone 3 adds a durable, structured analysis pipeline around the deterministic comparison
and impact capabilities from Milestones 1 and 2. It includes:

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
- focused unit and API tests.

ML risk prediction, Gemini, BigQuery, Docker, and the web dashboard are intentionally not implemented yet.

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

The response includes `analysis_id` and `duplicate`. Use the ID with:

- `GET /api/v1/analyses`
- `GET /api/v1/analyses/{analysis_id}`
- `GET /api/v1/analyses/{analysis_id}/changes`
- `GET /api/v1/analyses/{analysis_id}/matches`
- `GET /api/v1/analyses/{analysis_id}/pipeline`
- `DELETE /api/v1/analyses/{analysis_id}`

Submitting the exact same file bytes again returns the stored result with `duplicate: true`
and does not create another analysis.

## Verify

```powershell
.\.venv\Scripts\python.exe -m pytest -c apps/api/pyproject.toml apps/api/tests
.\.venv\Scripts\python.exe -m ruff check --config apps/api/pyproject.toml apps/api
```

## Architecture direction

The MVP is a modular monolith. FastAPI routes receive the analysis pipeline through dependency
injection. The pipeline uses an `AnalysisRepository` port; SQLite is the current local adapter.
Deterministic contract and impact logic remains independent of persistence and external providers.

The Milestone 3 flow is:

```text
uploads -> SHA-256 hashes + request fingerprint -> create or find analysis
       -> recorded validation/comparison/scan/match stages
       -> transactional changes + limited matches + metadata write
       -> stored response or safe persisted failure
```

SQLite contains five related application tables:

- `analyses` owns metadata, hashes, fingerprints, summaries, and lifecycle timestamps;
- `analysis_changes` belongs to an analysis;
- `repository_matches` belongs to a persisted change;
- `pipeline_stages` belongs to an analysis;
- `analysis_failures` belongs to an analysis.

All child rows are deleted through foreign-key cascades when an analysis is deleted.

## Current limitations

- Only OpenAPI 3.x is accepted.
- Only local JSON Pointer `$ref` values are resolved; remote references are rejected.
- Schema comparison currently focuses on object properties relevant to the MVP, including nested properties represented as dotted paths.
- Repository input is ZIP-only; remote Git cloning and provider integrations are not included.
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
- No ML claim is made in this milestone; the future initial classifier will be explicitly documented as synthetic-data risk ranking.
