# The database already exists and is imported into the remote Terraform state.
# It is always protected from destroy. Hosted-beta resources remain opt-in.
data "google_project" "current" {
  project_id = var.project_id
}

locals {
  name_prefix      = "driftguard-${var.environment}"
  api_service_name = "${local.name_prefix}-api"
  web_service_name = "${local.name_prefix}-web"
  api_service_url  = "https://${local.api_service_name}-${data.google_project.current.number}.${var.region}.run.app"
  web_service_url  = "https://${local.web_service_name}-${data.google_project.current.number}.${var.region}.run.app"
  labels = {
    application = "driftguard"
    environment = var.environment
    managed_by  = "terraform"
  }
  secret_names = toset([
    "driftguard-session-secret",
    "github-oauth-client-id",
    "github-oauth-client-secret",
    "github-app-id",
    "github-app-private-key",
    "github-webhook-secret",
  ])
}

resource "google_firestore_database" "primary" {
  project          = var.project_id
  name             = var.firestore_database_id
  location_id      = var.firestore_location_id
  type             = "FIRESTORE_NATIVE"
  concurrency_mode = "PESSIMISTIC"
  delete_protection_state = (
    var.enable_firestore_deletion_protection
    ? "DELETE_PROTECTION_ENABLED"
    : "DELETE_PROTECTION_DISABLED"
  )

  lifecycle {
    prevent_destroy = true
  }
}

# Stage 1 creates only the deployment foundation. These resources never contain
# secret values; operators add real Secret Manager versions separately.
resource "google_artifact_registry_repository" "images" {
  count = var.enable_hosted_beta_foundation ? 1 : 0

  location      = var.region
  repository_id = "driftguard"
  description   = "DriftGuard controlled-beta container images"
  format        = "DOCKER"
  labels        = local.labels
}

resource "google_service_account" "runtime" {
  count = var.enable_hosted_beta_foundation ? 1 : 0

  account_id   = "driftguard-runtime"
  display_name = "DriftGuard Cloud Run runtime"
}

resource "google_secret_manager_secret" "application" {
  for_each  = var.enable_hosted_beta_foundation ? local.secret_names : toset([])
  secret_id = each.value
  labels    = local.labels

  replication {
    auto {}
  }
}

# The runtime can access application data and only the six named secrets.
resource "google_project_iam_member" "runtime_firestore" {
  count = var.enable_hosted_beta_foundation ? 1 : 0

  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.runtime[0].email}"
}

resource "google_project_iam_member" "runtime_logging" {
  count = var.enable_hosted_beta_foundation ? 1 : 0

  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.runtime[0].email}"
}

resource "google_secret_manager_secret_iam_member" "runtime_access" {
  for_each = var.enable_hosted_beta_foundation ? local.secret_names : toset([])

  project   = var.project_id
  secret_id = google_secret_manager_secret.application[each.value].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime[0].email}"
}

# Stage 2 is enabled only after immutable images exist and every required
# secret has a real, manually provisioned version. There are no Jobs or
# Schedulers in this beta, so monitoring remains manual through Check now.
resource "google_cloud_run_v2_service" "api" {
  count = var.enable_runtime_services ? 1 : 0

  name     = local.api_service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"
  labels   = local.labels

  template {
    service_account                  = google_service_account.runtime[0].email
    timeout                          = "300s"
    max_instance_request_concurrency = 20

    scaling {
      min_instance_count = 0
      max_instance_count = var.api_max_instances
    }

    containers {
      image = var.api_image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
      }

      env {
        name  = "DRIFTGUARD_ENVIRONMENT"
        value = "production"
      }
      env {
        name  = "DRIFTGUARD_AUTH_MODE"
        value = "github"
      }
      env {
        name  = "DRIFTGUARD_STORAGE_BACKEND"
        value = "firestore"
      }
      env {
        name  = "DRIFTGUARD_FIRESTORE_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "DRIFTGUARD_FIRESTORE_DATABASE_ID"
        value = var.firestore_database_id
      }
      env {
        name  = "DRIFTGUARD_SECURE_COOKIES"
        value = "true"
      }
      env {
        name  = "DRIFTGUARD_SESSION_COOKIE_SAME_SITE"
        value = "none"
      }
      env {
        name  = "DRIFTGUARD_FRONTEND_URL"
        value = local.web_service_url
      }
      env {
        name  = "DRIFTGUARD_CORS_ALLOWED_ORIGINS"
        value = local.web_service_url
      }
      env {
        name  = "DRIFTGUARD_GITHUB_OAUTH_PROVIDER"
        value = "github"
      }
      env {
        name  = "DRIFTGUARD_GITHUB_OAUTH_CALLBACK_URL"
        value = "${local.api_service_url}/api/v1/auth/github/callback"
      }
      env {
        name  = "DRIFTGUARD_GITHUB_APP_INSTALL_URL"
        value = var.github_app_install_url
      }
      env {
        name  = "DRIFTGUARD_BETA_ALLOWED_GITHUB_LOGINS"
        value = var.beta_allowed_github_logins
      }
      env {
        name  = "DRIFTGUARD_REMOTE_SPECIFICATION_URLS_ENABLED"
        value = "false"
      }
      env {
        name  = "DRIFTGUARD_RATE_LIMIT_ENABLED"
        value = "true"
      }
      env {
        name  = "DRIFTGUARD_GITHUB_WRITE_PROVIDER"
        value = "github_app"
      }
      env {
        name  = "DRIFTGUARD_GITHUB_CHECK_PROVIDER"
        value = "github_app"
      }
      env {
        name  = "DRIFTGUARD_MONITOR_SCHEDULER_ENABLED"
        value = "false"
      }
      env {
        name  = "DRIFTGUARD_AUTOMATION_WORKER_ENABLED"
        value = "false"
      }
      env {
        name  = "DRIFTGUARD_VALIDATION_EXECUTION_PROVIDER"
        value = "disabled"
      }
      env {
        name  = "DRIFTGUARD_GITHUB_APP_PRIVATE_KEY_PATH"
        value = "/var/run/secrets/github-app/private-key.pem"
      }

      env {
        name = "DRIFTGUARD_SESSION_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.application["driftguard-session-secret"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "DRIFTGUARD_GITHUB_OAUTH_CLIENT_ID"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.application["github-oauth-client-id"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "DRIFTGUARD_GITHUB_OAUTH_CLIENT_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.application["github-oauth-client-secret"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "DRIFTGUARD_GITHUB_APP_ID"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.application["github-app-id"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "DRIFTGUARD_GITHUB_WEBHOOK_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.application["github-webhook-secret"].secret_id
            version = "latest"
          }
        }
      }

      volume_mounts {
        name       = "github-app-private-key"
        mount_path = "/var/run/secrets/github-app"
      }
    }

    volumes {
      name = "github-app-private-key"
      secret {
        secret = google_secret_manager_secret.application["github-app-private-key"].secret_id
        items {
          version = "latest"
          path    = "private-key.pem"
        }
      }
    }
  }

  lifecycle {
    precondition {
      condition     = var.enable_hosted_beta_foundation
      error_message = "Enable hosted-beta foundation before creating runtime services."
    }
    precondition {
      condition = alltrue([
        trimspace(var.api_image) != "",
        trimspace(var.github_app_install_url) != "",
        trimspace(var.beta_allowed_github_logins) != "",
      ])
      error_message = "Runtime services require an immutable API image, a GitHub App installation URL, and a beta allowlist."
    }
  }

  depends_on = [
    google_project_iam_member.runtime_firestore,
    google_project_iam_member.runtime_logging,
    google_secret_manager_secret_iam_member.runtime_access,
  ]
}

resource "google_cloud_run_v2_service" "web" {
  count = var.enable_runtime_services ? 1 : 0

  name     = local.web_service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"
  labels   = local.labels

  template {
    timeout                          = "60s"
    max_instance_request_concurrency = 80

    scaling {
      min_instance_count = 0
      max_instance_count = var.web_max_instances
    }

    containers {
      image = var.web_image

      ports {
        container_port = 8080
      }
      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }
  }

  lifecycle {
    precondition {
      condition     = var.enable_hosted_beta_foundation
      error_message = "Enable hosted-beta foundation before creating runtime services."
    }
    precondition {
      condition     = trimspace(var.web_image) != ""
      error_message = "Runtime services require an immutable frontend image."
    }
  }

  depends_on = [google_artifact_registry_repository.images]
}

# Cloud Run transport must be public for the landing page, GitHub OAuth callback,
# and HMAC-verified GitHub webhook delivery. Product actions are still protected
# by DriftGuard sessions, CSRF, workspace membership, and RBAC.
resource "google_cloud_run_v2_service_iam_member" "api_public_invoker" {
  count = var.enable_runtime_services && var.public_transport_enabled ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.api[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "web_public_invoker" {
  count = var.enable_runtime_services && var.public_transport_enabled ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.web[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
