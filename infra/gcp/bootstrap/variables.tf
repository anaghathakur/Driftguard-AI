variable "project_id" {
  type        = string
  description = "Existing Google Cloud project ID. Never commit a value here."
}

variable "region" {
  type        = string
  description = "Google Cloud region for state storage."
  default     = "asia-south1"
}

variable "state_bucket_name" {
  type        = string
  description = "Globally unique GCS bucket name for versioned Terraform state."
}
