variable "project_id" {
  type        = string
  description = "Existing Google Cloud project ID. Never commit a value here."
}

variable "region" {
  type        = string
  description = "Google Cloud region for the controlled beta."
  default     = "asia-south1"
}

variable "environment" {
  type        = string
  description = "Deployment environment label. The controlled beta uses production."
  default     = "production"
}

variable "firestore_database_id" {
  type        = string
  description = "Existing Firestore Native database ID."
  default     = "driftguard-db"
}

variable "firestore_location_id" {
  type        = string
  description = "Immutable location of the existing Firestore database."
  default     = "asia-south1"
}

variable "enable_firestore_deletion_protection" {
  type        = bool
  description = "Keep false until deletion protection is separately reviewed and approved."
  default     = false
}

variable "enable_hosted_beta_foundation" {
  type        = bool
  description = "Create Artifact Registry, the runtime identity, and empty Secret Manager containers. Defaults to false to preserve the no-new-resource profile."
  default     = false
}

variable "enable_runtime_services" {
  type        = bool
  description = "Create Cloud Run services only after images and real secret versions are available. Requires enable_hosted_beta_foundation."
  default     = false
}

variable "public_transport_enabled" {
  type        = bool
  description = "Allow unauthenticated transport to the public landing page, OAuth callback, and verified webhook endpoint. Product actions remain application-authenticated."
  default     = false
}

variable "api_image" {
  type        = string
  description = "Immutable Artifact Registry API image digest. Required only when runtime services are enabled."
  default     = ""
}

variable "web_image" {
  type        = string
  description = "Immutable Artifact Registry frontend image digest. Required only when runtime services are enabled."
  default     = ""
}

variable "github_app_install_url" {
  type        = string
  description = "GitHub App installation URL. Required only when runtime services are enabled."
  default     = ""
}

variable "beta_allowed_github_logins" {
  type        = string
  description = "Comma-separated GitHub login allowlist for the controlled beta. Required only when runtime services are enabled."
  default     = ""
}

variable "api_max_instances" {
  type        = number
  description = "Hard maximum Cloud Run API instance count for the controlled beta."
  default     = 1

  validation {
    condition     = var.api_max_instances == 1
    error_message = "The controlled beta intentionally permits only one API instance. Increase this only through a separately reviewed capacity and cost plan."
  }
}

variable "web_max_instances" {
  type        = number
  description = "Hard maximum Cloud Run frontend instance count for the controlled beta."
  default     = 1

  validation {
    condition     = var.web_max_instances == 1
    error_message = "The controlled beta intentionally permits only one frontend instance. Increase this only through a separately reviewed capacity and cost plan."
  }
}
