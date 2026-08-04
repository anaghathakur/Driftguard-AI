# DriftGuard AI

DriftGuard AI detects API contract drift and, in later milestones, will connect those changes to repository usage and migration guidance.

## Current milestone

The first verified vertical slice accepts two OpenAPI 3.x JSON or YAML files and returns a deterministic, structured comparison. It includes:

- safe extension and size validation;
- OpenAPI structure validation with local `$ref` resolution;
- normalized operations, parameters, request fields, responses, authentication, enums, and descriptions;
- deterministic change classification independent of an AI provider;
- structured FastAPI error responses;
- focused unit and API tests.

Repository scanning, ML risk prediction, Gemini, persistence, BigQuery, Docker, and the web dashboard are intentionally not implemented yet.

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

## Verify

```powershell
.\.venv\Scripts\python.exe -m pytest -c apps/api/pyproject.toml apps/api/tests
.\.venv\Scripts\python.exe -m ruff check --config apps/api/pyproject.toml apps/api
```

## Architecture direction

The MVP is a modular monolith. FastAPI routes depend on application services; deterministic contract and impact logic remains separate from persistence and external providers. Future repository, ML, AI, analytics, and storage adapters will sit behind interfaces so the local application remains usable without cloud credentials or paid services.

The current flow is:

```text
multipart upload -> validation/parser -> normalized contract -> deterministic differ -> response
```

## Current limitations

- Only OpenAPI 3.x is accepted.
- Only local JSON Pointer `$ref` values are resolved; remote references are rejected.
- Schema comparison currently focuses on object properties relevant to the MVP, including nested properties represented as dotted paths.
- The service is synchronous and does not persist comparisons yet.
- No ML claim is made in this milestone; the future initial classifier will be explicitly documented as synthetic-data risk ranking.
