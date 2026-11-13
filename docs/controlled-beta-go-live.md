# Controlled beta go-live checklist

This checklist separates manual account work from the later, explicitly
approved infrastructure deployment. It does not authorize a Terraform apply.

## Account responsibilities

| Action | Account |
| --- | --- |
| Create and manage Cloud Billing budgets/spend caps | `anaghathakur1429@gmail.com` (active Free Trial billing account administrator) |
| Terraform, Cloud Run, Artifact Registry, Firestore, Secret Manager, and IAM | `anagha.thakur14@gmail.com` (owner of `driftguard-ai`) |
| GitHub App and dedicated PR test repository | GitHub organization/repository administrator |

The project must remain `driftguard-ai`. Do not transfer it between accounts.

## Mandatory cost controls before any hosted beta

1. In the billing-account owner's console, create a monthly **Cloud Run spend
   cap** scoped to `driftguard-ai` and Cloud Run. This is still required before
   any hosted deployment.
2. An all-services **alerts-only** project budget at ₹500/month is now in
   place. It should alert at ₹250, ₹400, and ₹500; it does not stop billing.
3. Record the current remaining Free Trial credit in the billing console.
4. Keep the existing Mumbai state bucket and named Firestore database in mind:
   neither has an Always Free guarantee in this configuration.

Cloud Run spend caps are monthly, service-scoped controls. They pause Cloud
Run when enforced, but do not cap Firestore or Cloud Storage and can have a
small reporting/enforcement delay.

## Manual GitHub prerequisites

Create a dedicated test repository. Do not use a customer or production
repository for the first live test.

Create a GitHub App with only:

- Repository contents: read and write
- Pull requests: read and write
- Checks: write
- Metadata: read

Configure these real backend routes after a public backend URL exists:

- OAuth callback: `https://API_HOST/api/v1/auth/github/callback`
- Webhook: `https://API_HOST/api/v1/github/webhooks`

Store the App ID, private key, OAuth client credentials, webhook secret, and a
high-entropy session secret in Secret Manager. Never commit them or paste them
into Terraform variables, Git, or chat.

## Hosted beta architecture for separate approval

- Two request-based Cloud Run services with minimum instances set to zero:
  API and frontend.
- One Artifact Registry repository for immutable images.
- One runtime service account with only Firestore, secret-access, and logging
  permissions it needs.
- Six initial Secret Manager versions only.
- GitHub Actions OIDC image delivery, avoiding Cloud Build.
- Existing `driftguard-db`, with no database replacement or deletion-protection
  change.

Do not add Cloud Scheduler, Cloud Run Jobs, automatic monitoring, automation
workers, Cloud NAT, VPC connectors, Cloud Armor, or a load balancer to the
first beta.

## Live PR proof sequence

1. Analyze a deliberate breaking contract against the dedicated test
   repository.
2. Generate a bounded patch and review the diff.
3. Run static validation until the patch reports `READY_FOR_REVIEW`.
4. Open the PR preview, verify base commit and changed files.
5. Use the second explicit confirmation to create a draft PR.
6. Confirm the GitHub PR URL, branch, and diff in GitHub.
7. Do not merge automatically.

## Required approvals

Before the hosted-beta Terraform is reintroduced and applied, approve all of
the following as one plan:

- Cloud Run services, Artifact Registry, runtime deployment identity, required
  IAM, and six Secret Manager versions.
- Public Cloud Run transport for the landing page, OAuth callback, webhook, and
  authenticated browser API calls.
- A Cloud Run monthly spend cap of the chosen amount and an all-services alert
  budget.
- GitHub Actions OIDC deployment identity and repository workflow changes.
- The exact Terraform plan after the above local configuration is prepared.
