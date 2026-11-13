# Existing Terraform state bucket

`gs://driftguard-ai-tfstate` already exists and is the remote state backend.
This module now reads and verifies that existing bucket only; it must not be
applied to create or change infrastructure.

Initialize the main stack with the existing bucket and state prefix:

```powershell
terraform -chdir=infra/gcp init -reconfigure `
  -backend-config="bucket=driftguard-ai-tfstate" `
  -backend-config="prefix=driftguard/production"
```

The bucket is outside the strict no-additional-cost application profile. Its
Mumbai storage is not covered by Cloud Storage Always Free, so even its very
small state object can create a tiny usage charge.
