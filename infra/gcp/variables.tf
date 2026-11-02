variable "project_id" {
  type        = string
  description = "Existing Google Cloud project ID. Never commit a value here."
}

variable "region" {
  type        = string
  description = "Google Cloud region for Cloud Run resources."
  default     = "asia-south1"
}

variable "environment" {
  type        = string
  description = "Deployment environment label, normally production or staging."
  default     = "production"
}

variable "api_image" {
  type        = string
  description = "Immutable Artifact Registry API image digest or tag."
}

variable "web_image" {
  type        = string
  description = "Immutable Artifact Registry frontend image digest or tag."
}

variable "frontend_url" {
  type        = string
  description = "Public HTTPS frontend origin, without a trailing slash."
}

variable "github_oauth_callback_url" {
  type        = string
  description = "Public HTTPS GitHub OAuth callback URL."
}

variable "github_app_install_url" {
  type        = string
  description = "GitHub App installation URL."
}

variable "cors_allowed_origins" {
  type        = string
  description = "Comma-separated public browser origins."
}

variable "firestore_database_id" {
  type        = string
  description = "Existing Firestore Native database ID to use for DriftGuard."
  default     = "driftguard-db"
}

variable "firestore_location_id" {
  type        = string
  description = "Immutable Firestore Native database location."
  default     = "asia-south1"
}

variable "enable_firestore_deletion_protection" {
  type        = bool
  description = "Keep false for the initial existing-database import. Enable only through a separately reviewed plan."
  default     = false
}

variable "beta_allowed_github_logins" {
  type        = string
  description = "Comma-separated GitHub login allowlist for the controlled beta. This is not a secret."
}

variable "api_max_instances" {
  type        = number
  default     = 10
  description = "Cloud Run API maximum instance count."
}

variable "api_min_instances" {
  type        = number
  default     = 0
  description = "Cloud Run API minimum instance count. Zero avoids an idle beta baseline cost."
}
