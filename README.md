# DriftGuard AI

DriftGuard AI detects API contract drift and connects those changes to likely source-code usage.

## Current milestone

Milestone 2 accepts two OpenAPI 3.x JSON or YAML files and a repository ZIP. It returns the deterministic contract comparison from Milestone 1 together with repository scan metadata and per-change source matches. It includes:

- safe extension and size validation;
- OpenAPI structure validation with local `$ref` resolution;
- normalized operations, parameters, request fields, responses, authentication, enums, and descriptions;
- deterministic change classification independent of an AI provider;
- structured FastAPI error responses;
- in-memory ZIP scanning with path traversal, link, encryption, archive size,
  decompressed size, file count, per-file size, and compression-ratio defenses;
- source allowlisting and generated/dependency directory exclusions;
- deterministic matching by OpenAPI `operationId`, path template, and HTTP method;
- focused unit and API tests.

ML risk prediction, Gemini, persistence, BigQuery, Docker, and the web dashboard are intentionally not implemented yet.

## Run locally

From the repository root on Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".\apps\api[dev]"
.\.venv\Scripts\python.exe -m uvicorn apps.api.app.main:app --reload
```

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

## Verify

```powershell
.\.venv\Scripts\python.exe -m pytest -c apps/api/pyproject.toml apps/api/tests
.\.venv\Scripts\python.exe -m ruff check --config apps/api/pyproject.toml apps/api
```

## Architecture direction

The MVP is a modular monolith. FastAPI routes depend on application services; deterministic contract and impact logic remains separate from persistence and external providers. Future repository, ML, AI, analytics, and storage adapters will sit behind interfaces so the local application remains usable without cloud credentials or paid services.

The Milestone 2 flow is:

```text
OpenAPI uploads -> validation/parser -> normalized contracts -> deterministic differ
repository ZIP -> guarded in-memory source scan -> operation matcher -> combined response
```

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
- The service is synchronous and does not persist comparisons yet.
- No ML claim is made in this milestone; the future initial classifier will be explicitly documented as synthetic-data risk ranking.
