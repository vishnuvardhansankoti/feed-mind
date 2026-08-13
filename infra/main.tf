# --- Artifact Registry (holds the ONNX-slim pipeline image) ---
resource "google_artifact_registry_repository" "repo" {
  location      = var.region
  repository_id = "paper-prism"
  format        = "DOCKER"
  description   = "paper-prism pipeline images"

  depends_on = [google_project_service.enabled]
}

# --- Firestore (native mode) + the one composite index the UI needs ---
resource "google_firestore_database" "db" {
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"

  depends_on = [google_project_service.enabled]
}

resource "google_firestore_index" "runs_category_date" {
  collection = "runs"
  database   = google_firestore_database.db.name

  fields {
    field_path = "category"
    order      = "ASCENDING"
  }
  fields {
    field_path = "run_date"
    order      = "DESCENDING"
  }
}

# --- Service accounts (least privilege; PRD §5 / §9c) ---
resource "google_service_account" "job" {
  account_id   = "paper-prism-job"
  display_name = "paper-prism pipeline job"
}

resource "google_service_account" "scheduler" {
  account_id   = "paper-prism-scheduler"
  display_name = "paper-prism scheduler invoker"
}

# Job SA may write Firestore, nothing else at project scope.
resource "google_project_iam_member" "job_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.job.email}"
}

# --- Gemini secret + accessor bound to the job SA only ---
resource "google_secret_manager_secret" "gemini" {
  secret_id = "gemini-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret_version" "gemini" {
  secret      = google_secret_manager_secret.gemini.id
  secret_data = var.gemini_api_key
}

resource "google_secret_manager_secret_iam_member" "job_accessor" {
  secret_id = google_secret_manager_secret.gemini.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.job.email}"
}
