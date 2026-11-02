output "api_url" {
  value       = google_cloud_run_v2_service.api.uri
  description = "Cloud Run API URL; map a custom HTTPS domain before public launch."
}

output "web_url" {
  value       = google_cloud_run_v2_service.web.uri
  description = "Cloud Run frontend URL; map a custom HTTPS domain before public launch."
}

output "artifact_registry" {
  value       = google_artifact_registry_repository.images.name
  description = "Artifact Registry repository for immutable API and web images."
}
