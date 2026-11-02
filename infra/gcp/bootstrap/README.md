# Terraform state bootstrap

This isolated configuration creates the Google Cloud Storage bucket used by
the main DriftGuard Terraform state backend. It deliberately has no remote
backend because it is the one-time bootstrap step.

After a reviewed bootstrap apply, initialize the parent configuration using
the returned bucket name and an environment-specific state prefix:

    terraform -chdir=infra/gcp init \
      -backend-config="bucket=YOUR_STATE_BUCKET" \
      -backend-config="prefix=driftguard/production"

The bucket enforces uniform bucket-level access, public-access prevention,
versioning, and retains the ten newest state versions. Do not put secrets in
Terraform state or in tfvars files.
