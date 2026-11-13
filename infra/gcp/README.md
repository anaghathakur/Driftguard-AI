# DriftGuard controlled-beta Terraform

This stack protects the imported existing Firestore database
`driftguard-db`. It has two deliberate, opt-in deployment stages.

## Default: no new resources

With the example values unchanged, Terraform manages only the existing
Firestore database and should produce no infrastructure changes. This remains
the safe default:

```powershell
terraform -chdir=infra/gcp plan -var="project_id=driftguard-ai"
```

Never enable deletion protection in this stack without a separately reviewed
plan. The database is protected from destruction with `prevent_destroy`.

## Stage 1: hosted-beta foundation

After a reviewed cloud-write approval, set `enable_hosted_beta_foundation` to
`true`. It creates only:

- one Artifact Registry Docker repository;
- one Cloud Run runtime service account;
- six empty Secret Manager containers; and
- the minimum Firestore, logging, and per-secret access bindings for that
  runtime account.

It creates no Cloud Run service, Scheduler job, Cloud Run Job, Firestore index,
TTL policy, VPC connector, NAT, load balancer, or Cloud Armor resource.

Secret values are never Terraform variables. Add real versions directly to
Secret Manager only after creating the GitHub OAuth App and GitHub App. Do not
put private keys, client secrets, session secrets, or webhook secrets in Git.

## Stage 2: runtime services

After immutable images and all real secret versions exist, enable
`enable_runtime_services`. It creates a request-based API service and frontend
service, both with zero minimum instances and a hard maximum of one instance.

The API is production-configured to use Firestore, secure cookies, GitHub OAuth,
the GitHub App, the persisted rate limiter, and an explicit GitHub-login beta
allowlist. Arbitrary remote contract URLs, scheduled monitors, automation
workers, and runtime test execution stay disabled.

Terraform deterministically derives the frontend URL, API URL, CORS origin, and
OAuth callback from the fixed service names, project number, and region. Use the
`api_service_url` output plus `/api/v1/auth/github/callback` for GitHub OAuth,
and the same API URL plus `/api/v1/github/webhooks` for the GitHub App webhook.

Do not enable `public_transport_enabled` until these derived URLs, the GitHub
App installation URL, real Secret Manager versions, and the allowlist have been
reviewed. Public transport is necessary for
the landing page, OAuth callback, and signed webhook delivery; application
middleware still protects all product operations.

See [the controlled-beta checklist](../../docs/controlled-beta-go-live.md) and
[the free-tier audit](../../FREE_TIER_DEPLOYMENT_PLAN.md) before any apply.
