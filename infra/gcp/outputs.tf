output "api_service_url" {
  description = "Deterministic Cloud Run API URL. Use it for GitHub OAuth and webhook configuration before the service is created."
  value       = local.api_service_url
}

output "web_service_url" {
  description = "Deterministic Cloud Run frontend URL. Configure the frontend build to use the API URL."
  value       = local.web_service_url
}

output "artifact_registry_repository" {
  description = "Artifact Registry repository path after the hosted-beta foundation is created."
  value       = try(google_artifact_registry_repository.images[0].id, null)
}
