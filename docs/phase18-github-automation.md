# Phase 18: GitHub-native automation

DriftGuard is a GitHub App that detects breaking OpenAPI changes, traces their impact through Python, JavaScript, and TypeScript repositories, and prepares human-reviewed migrations.

The hosted dashboard remains the configuration and investigation surface. GitHub Check Runs are the notification and review surface. Existing manual comparison, ZIP, public GitHub, connected repository, patch, validation, report, monitor, and explicit Pull Request workflows remain available.

## Architecture

```text
GitHub webhook
  -> raw-body HMAC-SHA256 verification
  -> durable delivery record (unique GitHub delivery ID)
  -> durable workspace-scoped job
  -> fast HTTP acknowledgement
  -> database-polling worker
  -> installation/repository reauthorization
  -> immutable commit snapshot analysis
  -> reconciled GitHub Check Run
  -> trusted link to the persisted DriftGuard analysis
```

Webhook bodies are parsed only after signature verification. Tokens, secrets, raw private source, and credentials are never stored in delivery/job records. Jobs retain only server-resolvable installation, repository, commit, PR, monitor, delivery, and analysis identifiers.

SQLite uses additive tables for deliveries, jobs, contracts, dependency evidence, and Check identities. Job claiming uses an immediate transaction so a local database-backed worker can survive process restarts without a process-memory queue. Transient GitHub timeouts, availability errors, and rate limits use bounded exponential retry scheduling; revoked installations, unauthorized repositories, and invalid contracts fail permanently.

## GitHub App configuration

Webhook URL:

```text
https://YOUR_API_HOST/api/v1/github/webhooks
```

Subscribe only to:

- `installation`
- `installation_repositories`
- `push`
- `pull_request`
- `ping` (optional diagnostics)

Repository permissions:

- Metadata: read
- Contents: read
- Checks: read and write
- Pull requests: read and write (only for the existing explicit, validated PR workflow)

The webhook secret belongs only on the API server. The frontend must never receive it. The GitHub App private key must remain server-side and readable only by the API/worker runtime.

## Environment

```text
DRIFTGUARD_GITHUB_WEBHOOK_SECRET=<strong random secret shared with GitHub>
DRIFTGUARD_MAX_WEBHOOK_BYTES=2097152
DRIFTGUARD_GITHUB_CHECK_PROVIDER=mock
DRIFTGUARD_AUTOMATION_WORKER_ENABLED=false
DRIFTGUARD_AUTOMATION_WORKER_POLL_SECONDS=5
DRIFTGUARD_AUTOMATION_MAX_RETRIES=3
DRIFTGUARD_AUTOMATION_RETRY_BASE_SECONDS=15
DRIFTGUARD_MAX_CHECK_ANNOTATIONS=50
```

Set the Check provider to `github_app` and enable the worker in hosted deployments after configuring `DRIFTGUARD_GITHUB_APP_ID`, `DRIFTGUARD_GITHUB_APP_PRIVATE_KEY_PATH`, the trusted `DRIFTGUARD_FRONTEND_URL`, and the webhook secret. Run only one process-local SQLite worker. A future external worker can implement the same durable job boundary.

## Event behavior

- Installation and repository-access events queue repository synchronization. Removal/revocation disables access but preserves history.
- Push events use changed paths first. Source-only/README pushes are acknowledged without an expensive job. Known/configured contracts, likely OpenAPI paths, and dependency metadata are relevant.
- PR `opened`, `synchronize`, `reopened`, and `ready_for_review` events persist immutable base/head SHAs. The worker compares only changed, valid OpenAPI contracts.
- Duplicate `X-GitHub-Delivery` values return a successful duplicate response and produce no second job, analysis, Check, or write.

Contract discovery checks common OpenAPI/Swagger names and likely `api`, `docs`, `spec`, `specs`, `openapi`, and `contracts` directories, then validates candidates with the existing OpenAPI 3.x parser. Users can select a path manually; the server rejects traversal and verifies the path within the authorized immutable tree.

## Check conclusions

- No breaking or potentially breaking contract changes: `success`
- Potentially breaking provider changes: `neutral`
- Breaking provider contract changes: `action_required`
- Consumer changes with exact impacted code: `action_required`
- Analysis infrastructure/system failure: `failure`

Provider checks never claim consumer impact unless a consumer repository was actually analyzed. Check summaries are bounded and link only to `DRIFTGUARD_FRONTEND_URL` plus a server-created analysis ID. Exact high-confidence source locations may become annotations; fuzzy/wrapper/transitive findings remain summary-only. The current provider compatibility flow does not invent contract-line annotations.

## Local mock acceptance

Use `DRIFTGUARD_GITHUB_CHECK_PROVIDER=mock` and keep the write provider as `mock`. The deterministic provider stores snapshots and Check transitions in memory and performs no live mutation. Tests cover signed/tampered/missing webhooks, duplicate delivery suppression, irrelevant/relevant pushes, immutable PR base/head analysis, breaking conclusions, Check reconciliation, durable restart behavior, bounded retry, and revoked installation rejection.

For a real App, deliver a signed PR webhook that changes a valid OpenAPI file, confirm the job transitions from queued to completed, and confirm one `DriftGuard Contract Compatibility` Check is updated on the PR. No automatic merge, deployment, patch, or PR creation occurs.

## Current limitations

- Contract automation supports OpenAPI 3.x only; the boundary is protocol-neutral but GraphQL and Protobuf are intentionally deferred.
- Source impact remains Python, JavaScript, and TypeScript.
- SQLite is the production-ready Phase 18 job store in this increment; Firestore remains supported for existing analyses, monitors, identity, and workspace data but the automation worker must use SQLite until a transactional Firestore job-claim adapter is completed.
- GitHub Compare responses are bounded to GitHub's returned changed-file page; very large PR pagination is a future hardening item.
- Requested-action buttons in Checks are deferred. Patch generation and PR creation keep the dashboard's validation and explicit confirmation gates.
