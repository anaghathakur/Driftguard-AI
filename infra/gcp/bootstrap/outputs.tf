output "state_bucket_name" {
  value       = google_storage_bucket.terraform_state.name
  description = "Use this value as the main stack's GCS backend bucket."
}
