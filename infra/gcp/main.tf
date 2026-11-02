locals {
  name_prefix = "driftguard-${var.environment}"
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
    "gemini-api-key",
  ])
  job_environment = {
    DRIFTGUARD_ENVIRONMENT                       = "production"
    DRIFTGUARD_AUTH_MODE                         = "github"
    DRIFTGUARD_STORAGE_BACKEND                   = "firestore"
    DRIFTGUARD_FIRESTORE_PROJECT_ID              = var.project_id
    DRIFTGUARD_FIRESTORE_DATABASE_ID             = var.firestore_database_id
    DRIFTGUARD_SECURE_COOKIES                    = "true"
    DRIFTGUARD_SESSION_COOKIE_SAME_SITE          = "none"
    DRIFTGUARD_FRONTEND_URL                      = var.frontend_url
    DRIFTGUARD_CORS_ALLOWED_ORIGINS              = var.cors_allowed_origins
    DRIFTGUARD_GITHUB_OAUTH_PROVIDER             = "github"
    DRIFTGUARD_GITHUB_OAUTH_CALLBACK_URL         = var.github_oauth_callback_url
    DRIFTGUARD_GITHUB_APP_INSTALL_URL            = var.github_app_install_url
    DRIFTGUARD_BETA_ALLOWED_GITHUB_LOGINS        = var.beta_allowed_github_logins
    DRIFTGUARD_REMOTE_SPECIFICATION_URLS_ENABLED = "false"
    DRIFTGUARD_RATE_LIMIT_ENABLED                = "true"
    DRIFTGUARD_GITHUB_WRITE_PROVIDER             = "github_app"
    DRIFTGUARD_GITHUB_CHECK_PROVIDER             = "github_app"
    DRIFTGUARD_MONITOR_SCHEDULER_ENABLED         = "false"
    DRIFTGUARD_AUTOMATION_WORKER_ENABLED         = "false"
    DRIFTGUARD_VALIDATION_EXECUTION_PROVIDER     = "disabled"
    DRIFTGUARD_GITHUB_APP_PRIVATE_KEY_PATH       = "/var/run/secrets/github-app/private-key.pem"
  }
  secret_environment = {
    DRIFTGUARD_SESSION_SECRET             = "driftguard-session-secret"
    DRIFTGUARD_GITHUB_OAUTH_CLIENT_ID     = "github-oauth-client-id"
    DRIFTGUARD_GITHUB_OAUTH_CLIENT_SECRET = "github-oauth-client-secret"
    DRIFTGUARD_GITHUB_APP_ID              = "github-app-id"
    DRIFTGUARD_GITHUB_WEBHOOK_SECRET      = "github-webhook-secret"
  }
}

resource "google_project_service" "required" {
  for_each = toset([
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "cloudscheduler.googleapis.com",
    "firestore.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "serviceusage.googleapis.com",
  ])

  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "images" {
  location      = var.region
  repository_id = "driftguard"
  description   = "DriftGuard production container images"
  format        = "DOCKER"
  labels        = local.labels

  depends_on = [google_project_service.required]
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

  depends_on = [google_project_service.required]
}

resource "google_service_account" "runtime" {
  account_id   = "driftguard-runtime"
  display_name = "DriftGuard Cloud Run runtime"
}

resource "google_service_account" "scheduler" {
  account_id   = "driftguard-scheduler"
  display_name = "DriftGuard Cloud Scheduler job invoker"
}

resource "google_secret_manager_secret" "application" {
  for_each  = local.secret_names
  secret_id = each.value
  labels    = local.labels

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_project_iam_member" "runtime" {
  for_each = toset([
    "roles/datastore.user",
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
    "roles/secretmanager.secretAccessor",
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_cloud_run_v2_service" "api" {
  name     = "${local.name_prefix}-api"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"
  labels   = local.labels

  template {
    service_account = google_service_account.runtime.email

    scaling {
      min_instance_count = var.api_min_instances
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
        value = var.frontend_url
      }
      env {
        name  = "DRIFTGUARD_CORS_ALLOWED_ORIGINS"
        value = var.cors_allowed_origins
      }
      env {
        name  = "DRIFTGUARD_GITHUB_OAUTH_PROVIDER"
        value = "github"
      }
      env {
        name  = "DRIFTGUARD_GITHUB_OAUTH_CALLBACK_URL"
        value = var.github_oauth_callback_url
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
      env {
        name  = "DRIFTGUARD_GITHUB_APP_PRIVATE_KEY_PATH"
        value = "/var/run/secrets/github-app/private-key.pem"
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

  depends_on = [google_project_iam_member.runtime]
}

resource "google_cloud_run_v2_service" "web" {
  name     = "${local.name_prefix}-web"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"
  labels   = local.labels

  template {
    containers {
      image = var.web_image
      ports { container_port = 8080 }
      resources { limits = { cpu = "1", memory = "512Mi" } }
    }
  }
}

# Cloud Run transport is public for the landing page, OAuth callback, and
# browser API requests. DriftGuard itself still requires a verified GitHub
# session plus workspace authorization for every product operation.
resource "google_cloud_run_v2_service_iam_member" "api_public_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "web_public_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.web.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_job" "automation" {
  name     = "${local.name_prefix}-automation"
  location = var.region
  labels   = local.labels

  template {
    template {
      service_account = google_service_account.runtime.email
      max_retries     = 1
      timeout         = "900s"
      containers {
        image   = var.api_image
        command = ["python", "-m", "apps.api.app.operations.run_automation_job"]
        resources { limits = { cpu = "1", memory = "1Gi" } }

        dynamic "env" {
          for_each = local.job_environment
          content {
            name  = env.key
            value = env.value
          }
        }
        dynamic "env" {
          for_each = local.secret_environment
          content {
            name = env.key
            value_source {
              secret_key_ref {
                secret  = google_secret_manager_secret.application[env.value].secret_id
                version = "latest"
              }
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
  }
}

resource "google_cloud_run_v2_job" "monitors" {
  name     = "${local.name_prefix}-monitors"
  location = var.region
  labels   = local.labels

  template {
    template {
      service_account = google_service_account.runtime.email
      max_retries     = 1
      timeout         = "900s"
      containers {
        image   = var.api_image
        command = ["python", "-m", "apps.api.app.operations.run_monitor_job"]
        resources { limits = { cpu = "1", memory = "1Gi" } }

        dynamic "env" {
          for_each = local.job_environment
          content {
            name  = env.key
            value = env.value
          }
        }
        dynamic "env" {
          for_each = local.secret_environment
          content {
            name = env.key
            value_source {
              secret_key_ref {
                secret  = google_secret_manager_secret.application[env.value].secret_id
                version = "latest"
              }
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
  }
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_can_run_automation" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.automation.name
  role     = "roles/run.invoker"
  member   = format("serviceAccount:%s", google_service_account.scheduler.email)
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_can_run_monitors" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.monitors.name
  role     = "roles/run.invoker"
  member   = format("serviceAccount:%s", google_service_account.scheduler.email)
}

resource "google_firestore_index" "automation_jobs_by_status_created" {
  project     = var.project_id
  database    = var.firestore_database_id
  collection  = "automation_jobs"
  query_scope = "COLLECTION"

  fields {
    field_path = "status"
    order      = "ASCENDING"
  }
  fields {
    field_path = "created_at"
    order      = "ASCENDING"
  }

  depends_on = [google_firestore_database.primary]
}

resource "google_firestore_field" "rate_limits_expiry" {
  project    = var.project_id
  database   = var.firestore_database_id
  collection = "rate_limits"
  field      = "expires_at"

  ttl_config {}

  depends_on = [google_firestore_database.primary]
}

resource "google_firestore_index" "automation_jobs_by_status_next_attempt" {
  project     = var.project_id
  database    = var.firestore_database_id
  collection  = "automation_jobs"
  query_scope = "COLLECTION"

  fields {
    field_path = "status"
    order      = "ASCENDING"
  }
  fields {
    field_path = "next_attempt_at"
    order      = "ASCENDING"
  }

  depends_on = [google_firestore_database.primary]
}

resource "google_firestore_index" "automation_jobs_by_status_started" {
  project     = var.project_id
  database    = var.firestore_database_id
  collection  = "automation_jobs"
  query_scope = "COLLECTION"

  fields {
    field_path = "status"
    order      = "ASCENDING"
  }
  fields {
    field_path = "started_at"
    order      = "ASCENDING"
  }

  depends_on = [google_firestore_database.primary]
}

resource "google_firestore_index" "automation_jobs_by_workspace_created" {
  project     = var.project_id
  database    = var.firestore_database_id
  collection  = "automation_jobs"
  query_scope = "COLLECTION"

  fields {
    field_path = "workspace_id"
    order      = "ASCENDING"
  }
  fields {
    field_path = "created_at"
    order      = "DESCENDING"
  }

  depends_on = [google_firestore_database.primary]
}

resource "google_firestore_index" "automation_contracts_by_workspace_repository_path" {
  project     = var.project_id
  database    = var.firestore_database_id
  collection  = "automation_contracts"
  query_scope = "COLLECTION"

  fields {
    field_path = "workspace_id"
    order      = "ASCENDING"
  }
  fields {
    field_path = "repository_connection_id"
    order      = "ASCENDING"
  }
  fields {
    field_path = "path"
    order      = "ASCENDING"
  }

  depends_on = [google_firestore_database.primary]
}

resource "google_firestore_index" "automation_dependencies_by_workspace_repository" {
  project     = var.project_id
  database    = var.firestore_database_id
  collection  = "automation_dependencies"
  query_scope = "COLLECTION"

  fields {
    field_path = "workspace_id"
    order      = "ASCENDING"
  }
  fields {
    field_path = "repository_connection_id"
    order      = "ASCENDING"
  }

  depends_on = [google_firestore_database.primary]
}

resource "google_firestore_index" "automation_checks_by_workspace_repository_updated" {
  project     = var.project_id
  database    = var.firestore_database_id
  collection  = "automation_checks"
  query_scope = "COLLECTION"

  fields {
    field_path = "workspace_id"
    order      = "ASCENDING"
  }
  fields {
    field_path = "repository_connection_id"
    order      = "ASCENDING"
  }
  fields {
    field_path = "updated_at"
    order      = "DESCENDING"
  }

  depends_on = [google_firestore_database.primary]
}

resource "google_cloud_scheduler_job" "automation" {
  name        = "${local.name_prefix}-automation"
  description = "Invoke one durable DriftGuard automation pass"
  schedule    = "* * * * *"
  time_zone   = "Etc/UTC"
  region      = var.region

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.automation.name}:run"
    headers     = { "Content-Type" = "application/json" }
    body        = base64encode("{}")
    oauth_token { service_account_email = google_service_account.scheduler.email }
  }

  depends_on = [google_cloud_run_v2_job_iam_member.scheduler_can_run_automation]
}

resource "google_cloud_scheduler_job" "monitors" {
  name        = "${local.name_prefix}-monitors"
  description = "Invoke one DriftGuard contract-monitor pass"
  schedule    = "* * * * *"
  time_zone   = "Etc/UTC"
  region      = var.region

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.monitors.name}:run"
    headers     = { "Content-Type" = "application/json" }
    body        = base64encode("{}")
    oauth_token { service_account_email = google_service_account.scheduler.email }
  }

  depends_on = [google_cloud_run_v2_job_iam_member.scheduler_can_run_monitors]
}
