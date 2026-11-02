# DriftGuard on Google Cloud

These Terraform files are a reviewable deployment blueprint. They do **not**
contain credentials, project values, secret versions, or an automatic apply
step.

## State bootstrap

Before a shared staging or production deployment, create the dedicated,
versioned GCS state bucket from infra/gcp/bootstrap using a separately
reviewed plan and apply. Then initialize this parent stack with that bucket
and an environment-specific state prefix. The parent stack must not use local
state for a shared environment.

## Target topology

- Cloud Run service: public FastAPI API
- Cloud Run service: public React frontend
- Cloud Run Jobs: one bounded automation pass and one bounded monitor pass
- Cloud Scheduler: invokes each job once per minute
- Firestore Native: tenant, analysis, subscription, and durable automation state
- Secret Manager: session, GitHub OAuth/App, webhook, and optional Gemini secrets
- Artifact Registry: immutable container images

Cloud Run public invocation defaults to disabled for the private bootstrap
revision. Turn public_transport_enabled on only in the final reviewed beta
revision, after GitHub OAuth, Secret Manager versions, and the frontend/API
origins are configured. Product routes remain protected by GitHub
authentication, the controlled-beta login allowlist, workspace authorization,
CSRF checks, and the distributed Firestore limiter. This is suitable only for
the restricted beta described here; a broader public launch should add an
external Application Load Balancer and Cloud Armor.

The controlled-beta default sets the API minimum instance count to zero to
avoid an idle Cloud Run baseline. Increase api_min_instances only after
accepting the associated recurring cost for lower cold-start latency.

The approved project already has the Firestore Native database
driftguard-db in asia-south1. Terraform and Cloud Run are configured to use
that database. During the later reviewed deployment, import it into Terraform
state rather than attempting a second create:

    terraform -chdir=infra/gcp import \
      google_firestore_database.primary \
      projects/driftguard-ai/databases/driftguard-db

The import command is documentation only and must not be run without separate
approval. Terraform intentionally declares PESSIMISTIC concurrency to match
the existing database. The initial import also keeps deletion protection
disabled so an initial reviewed deployment cannot change the existing database
unexpectedly. The enable_firestore_deletion_protection variable defaults to
false. Enabling it must be a separate reviewed plan, explicitly approved
before apply, after the import and initial deployment are complete.

The API intentionally has `DRIFTGUARD_MONITOR_SCHEDULER_ENABLED=false` and
`DRIFTGUARD_AUTOMATION_WORKER_ENABLED=false`. Cloud Run Jobs replace the
process-local loops.

## Required human-approved actions

Before any `terraform apply`, approve and perform these separately:

1. Select a billing-enabled GCP project and a production/staging domain.
2. Enable the listed APIs and create the resources with a reviewed Terraform plan.
3. Add secret **versions** directly to Secret Manager; never use `.tfvars` for secrets.
4. Configure GitHub OAuth callback and create/install the GitHub App with only
   required permissions: Contents read/write, Checks write, Pull Requests write,
   Metadata read, and webhook events.
5. Supply a non-empty beta_allowed_github_logins value. Only those GitHub
   accounts can establish production sessions.
6. Map custom HTTPS domains, configure Cloud Armor/rate limits, and constrain
   egress through VPC/Cloud NAT before exposing public remote-contract fetching.

## Required Google Cloud APIs

Do not enable these services until a reviewed plan and separate approval.

The main deployment stack manages:

- artifactregistry.googleapis.com
- cloudbuild.googleapis.com
- cloudresourcemanager.googleapis.com for project IAM bindings
- cloudscheduler.googleapis.com
- firestore.googleapis.com
- iam.googleapis.com for service accounts
- iamcredentials.googleapis.com for Cloud Scheduler OAuth invocation tokens
- logging.googleapis.com
- monitoring.googleapis.com
- run.googleapis.com
- secretmanager.googleapis.com
- serviceusage.googleapis.com

The isolated state-bootstrap stack additionally requires
storage.googleapis.com. Cloud Billing API is not required by the application
deployment, but is required separately to inspect or manage billing.

## Firestore indexes

Terraform creates the required composite indexes. They may take a few minutes
to become ready after an apply; do not enable scheduler jobs until that
completion is visible in the Google Cloud console.
It also configures a Firestore TTL policy for distributed rate-limit windows;
Firestore deletes those expired documents asynchronously.

| Collection | Fields |
| --- | --- |
| automation_jobs | status ASC, created_at ASC |
| `automation_jobs` | `status ASC`, `next_attempt_at ASC` |
| `automation_jobs` | `status ASC`, `started_at ASC` |
| `automation_jobs` | `workspace_id ASC`, `created_at DESC` |
| `automation_contracts` | `workspace_id ASC`, `repository_connection_id ASC`, `path ASC` |
| `automation_dependencies` | `workspace_id ASC`, `repository_connection_id ASC` |
| `automation_checks` | `workspace_id ASC`, `repository_connection_id ASC`, `updated_at DESC` |

Terraform must use a remote, versioned state backend outside this repository.
Run `terraform plan` first, review every resource/IAM change, then request a
separate approval before `terraform apply`.
