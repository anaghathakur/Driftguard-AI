# DriftGuard AI strict free-tier deployment audit

Audit date: 2026-11-09. This is a no-deployment, no-apply audit. It does not
contain credentials, tokens, private keys, secret values, or billing-account
identifiers.

## Decision

There is **no credible ₹0 public Cloud Run beta** for the current project.
Cloud Run can remain within its free allowance in `asia-south1`, but that is a
usage allowance rather than a spending cap. More importantly,
`driftguard-db` is a named Firestore database and named databases receive no
Firestore free quota. The existing Mumbai Terraform state bucket is also
outside the Cloud Storage Always Free regions.

The default Terraform profile therefore creates no application resources. The only
credible no-new-GCP-resource beta is a local, invite-only pilot: run the
backend and frontend on operator-controlled hardware with the local SQLite
development storage, and use GitHub public-repository analysis only. A static
site can be hosted separately for a landing page, but it cannot provide the
authenticated DriftGuard product without a backend.

Do not represent the Cloud Run option as free. It is a potentially-free,
approval-required option after a capped pilot establishes actual usage.

## Current inventory

| Item | Observed state | Charge assessment |
| --- | --- | --- |
| Firestore | Existing `driftguard-db`; Native, Mumbai, PESSIMISTIC, deletion protection disabled | Existing named database. No creation cost from this audit, but every application read/write/storage use is billable. |
| Terraform state | Existing `gs://driftguard-ai-tfstate`, 2,398 bytes at audit time | Existing Standard bucket in Mumbai. It has uniform bucket-level access, public-access prevention, versioning, ten-version lifecycle rule, and the platform's seven-day soft-delete policy. It is tiny but not covered by Cloud Storage Always Free in Mumbai. |
| Terraform state | Only `google_firestore_database.primary` is in the remote state | Imported successfully; database is unchanged. |
| Cloud Run services/jobs | None | No current Cloud Run charge. |
| Cloud Scheduler | No jobs | No current Scheduler charge. |
| Artifact Registry | No repositories | No current Registry storage charge. |
| Secret Manager | No secrets or secret versions | No current Secret Manager charge. |
| Firestore composite indexes / TTL | No composite indexes observed; no Terraform-managed TTL applied | No new index/TTL cost introduced. |
| CI | GitHub Actions only; test/build Docker images are built on GitHub-hosted runners | No Cloud Build configuration or Cloud Build execution in this repository workflow. GitHub-hosted runner quotas are governed by the GitHub account, not this GCP project. |

The audit also found enabled APIs beyond DriftGuard's needs (for example,
BigQuery-related APIs). Enabling an API alone normally does not create a
billable resource, but this audit does not disable any API because doing so can
affect unrelated work.

The linked billing account is open and project billing is enabled. The Google
Cloud CLI exposes that status but not a reliable Free Trial credit balance or
remaining-credit consumption figure, and no billing export is configured for
this project. Treat any console-displayed trial credit as temporary credit, not
as a ₹0 cost guarantee.

## Mumbai free-tier verification and cost risks

| Service | Mumbai free allowance | Limitation / idle behavior | Strict-profile decision |
| --- | --- | --- | --- |
| Cloud Run service | Mumbai (`asia-south1`) is a Tier 1 region. Request-based services receive 180,000 vCPU-seconds, 360,000 GiB-seconds, and 2 million requests/month free. | Free allowance is shared by billing account and excess usage is charged. `min_instance_count = 0` avoids an idle minimum-instance charge, but public traffic, cold starts, requests, and outbound transfer remain variable. | Do not create without explicit approval. |
| Cloud Run job | Mumbai gets 240,000 vCPU-seconds and 450,000 GiB-seconds/month free for jobs. | Jobs are charged while running. The prior configuration would run two 1-vCPU/1-GiB jobs every minute: 86,400 executions/month. This can exceed free usage based on runtime. | Removed. |
| Cloud Scheduler | First three jobs per billing account/month are free; then $0.10/job/31 days. | Free count is billing-account-wide; executions can trigger billable Cloud Run jobs. | Removed. |
| Firestore named database | None. Firestore permits one free database per project, but named databases do not qualify. | Reads, writes, deletes, index entries, storage, network, and TTL deletes are usage billed. No strict GCP spending cap exists. | Preserve existing database unchanged; do not route a public beta to it under the ₹0 requirement. |
| Cloud Storage | Always Free includes 5 GB-month storage, 5,000 Class A operations, and 50,000 Class B operations only in `us-west1`, `us-central1`, and `us-east1`. | The existing state bucket is in Mumbai, so its storage and operations are not covered. Versioning/soft delete can retain additional bytes. | Existing unavoidable tiny cost risk; create no further buckets. |
| Artifact Registry | First 0.5 GiB-month is free per billing account. | Image storage beyond the allowance and cross-location/Internet transfer can charge. | Removed. |
| Secret Manager | Six active secret versions, 10,000 access operations, and three rotation notifications per billing account/month are free. | A seventh active version or excess accesses become billable; an app revision can access several versions. | Removed until a paid/potentially-free Cloud Run option is separately approved. |

Official sources: [Cloud Run pricing](https://cloud.google.com/run/pricing),
[Cloud Scheduler pricing](https://cloud.google.com/scheduler/pricing),
[Firestore pricing](https://cloud.google.com/firestore/pricing), [Cloud Storage
pricing](https://cloud.google.com/storage/pricing), [Artifact Registry
pricing](https://cloud.google.com/artifact-registry/pricing), and [Secret
Manager pricing](https://cloud.google.com/secret-manager/pricing).

## Resources excluded from the controlled-beta deployment

The original plan proposed 41 additions. The staged controlled-beta profile
continues to exclude the recurring or unnecessary resources below:

- Two Cloud Run Jobs (automation and monitoring) and both job invoker IAM
  bindings.
- Two every-minute Cloud Scheduler jobs.
- A scheduler service account and broad project-level secret-access role.
- Seven Firestore composite indexes and one rate-limit TTL policy.
- Twelve Terraform API-service resources.

The minimal profile may later create one Artifact Registry repository, one
runtime service account, six empty secret containers, precise per-secret IAM
members, and two zero-minimum Cloud Run services only after a new reviewed
plan. None of these resources exists today. The existing Firestore database
resource remains present with `prevent_destroy`.

The product retains the manual `POST /api/v1/monitors/{monitor_id}/check`
workflow, surfaced as **Check now** in the UI. It does not require the removed
scheduled monitor worker. Durable automation, scheduled monitoring, and their
query indexes are deferred until their recurring-cost model is approved.

## Smallest viable beta architecture

### Strict ₹0 additional-GCP-resource pilot

1. Run the backend and frontend locally or on an operator-owned development
   computer.
2. Use the existing local SQLite development mode; do not configure production
   Firestore for this pilot.
3. Use public GitHub repository analysis and uploaded contracts/ZIP archives.
4. Ask pilot users to use the operator-hosted session only while supervised, or
   run the repository locally with their own sample data.
5. Keep scheduled monitors, automatic contract polling, autonomous patch jobs,
   and public GitHub App production callbacks out of scope.

This is a functional engineering pilot, not an always-on public SaaS launch.

### Later controlled Cloud Run beta — approval required

Cloud Run API with `min_instance_count = 0`, no Scheduler, no Jobs, no load
balancer, no Cloud Armor, no VPC connector, and no Cloud NAT is the cheapest
hosted path. It remains **potentially free, not guaranteed free**, because of
unbounded request, egress, Firestore named-database, and state-bucket usage.

## Cost expectations

| Scenario | Expected additional monthly GCP cost | Can it be strictly capped? |
| --- | --- | --- |
| Strict Terraform profile | ₹0 for new resources: it plans no adds/changes/destroys. | Yes for newly proposed resources because none are created. Existing bucket/database usage remains outside this guarantee. |
| Existing state bucket only | Nonzero but extremely small at 2,398 bytes; storage and operations in Mumbai are billable. | No. It can grow with Terraform state versions and soft-deleted objects. |
| Local pilot using SQLite | ₹0 additional GCP application cost. | Yes, provided no Cloud Run/Firestore application activity is introduced. |
| Public Cloud Run beta | Cannot be honestly estimated as ₹0. It may stay inside Cloud Run free allowances at low traffic, but named Firestore usage and egress can charge from the first application use. | No. Budgets alert; they do not stop services or guarantee a cap. |

## Exact local deployment steps

1. Keep the remote state bucket and existing Firestore database unchanged.
2. Use the strict profile only for verification:

   ```powershell
   terraform -chdir=infra/gcp init -reconfigure `
     -backend-config="bucket=driftguard-ai-tfstate" `
     -backend-config="prefix=driftguard/production"
   terraform -chdir=infra/gcp plan -var="project_id=driftguard-ai"
   ```

3. Expect `0 to add, 0 to change, 0 to destroy`.
4. For the ₹0 pilot, start the application locally using the repository's
   documented local-development commands and keep production Firebase/Firestore
   configuration disabled.
5. Do not run `terraform apply` merely because the plan is a no-op; the
   imported Firestore state is already correct.

## Actions requiring explicit approval

- Any Cloud Run service, job, Scheduler job, Artifact Registry repository,
  Secret Manager version, service account, IAM binding, index, or TTL policy.
- Public Cloud Run invocation or custom-domain exposure.
- Writing application data to `driftguard-db` for public users.
- Any Cloud Build execution, image publish, GitHub App production credential,
  or external hosted backend.
- Any database-protection change, state migration, state-bucket change, or
  deletion of existing resources.
- Any architecture that relies on a budget alert as a spending cap.

## Default Terraform plan

The default profile is expected to produce:

```text
Plan: 0 to add, 0 to change, 0 to destroy.
```

It manages only the imported existing Firestore resource and preserves its
current Native type, `asia-south1` location, PESSIMISTIC concurrency, and
disabled deletion protection. The final local plan result is recorded in the
release handoff after validation.
