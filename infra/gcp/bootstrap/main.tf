# The state bucket was created in the approved preparation stage. Treat it as
# existing infrastructure: this module only verifies it and never creates,
# changes, or deletes a bucket.
data "google_storage_bucket" "terraform_state" {
  name = var.state_bucket_name
}
