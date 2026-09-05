locals {
  # Non-secret env for the job (profiles + tunables). The Gemini key is injected
  # separately from Secret Manager below.
  job_env = {
    SINK                   = "firestore"
    GOOGLE_CLOUD_PROJECT   = var.project_id
    FIRESTORE_DATABASE     = var.firestore_database
    CONTENT_READY_TOPIC    = var.content_ready_topic
    GEMINI_MODEL           = var.gemini_model
    WINDOW_DAYS            = tostring(var.window_days)
    TOP_K                  = tostring(var.top_k)
    RETENTION_DAYS         = tostring(var.retention_days)
    ARXIV_PAGE_SIZE        = "100"
    ARXIV_THROTTLE_SECONDS = "3"
    ARXIV_MAX_PAGES        = "10"
    PROFILE_AIML           = var.profile_aiml
    PROFILE_NLP            = var.profile_nlp
    PROFILE_CV             = var.profile_cv
  }
}

resource "google_cloud_run_v2_job" "pipeline" {
  name     = "paper-prism-job"
  location = var.region

  deletion_protection = false

  template {
    template {
      service_account = google_service_account.job.email
      max_retries     = 1
      timeout         = "900s"

      containers {
        image = var.image

        resources {
          limits = {
            cpu    = "2"
            memory = "2Gi"
          }
        }

        dynamic "env" {
          for_each = local.job_env
          content {
            name  = env.key
            value = env.value
          }
        }

        env {
          name = "GEMINI_API_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.gemini.secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }

  depends_on = [
    google_project_service.enabled,
    google_secret_manager_secret_iam_member.job_accessor,
  ]
}

# --- Cloud Scheduler triggers the job weekly, as the invoker SA ---
resource "google_cloud_run_v2_job_iam_member" "scheduler_invoker" {
  name     = google_cloud_run_v2_job.pipeline.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}

resource "google_cloud_scheduler_job" "weekly" {
  name      = "paper-prism-weekly"
  region    = var.region
  schedule  = var.schedule
  time_zone = var.time_zone

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.pipeline.name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler.email
    }
  }

  depends_on = [google_project_service.enabled]
}
