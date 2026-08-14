variable "project_id" {
  type        = string
  description = "GCP project id."
}

variable "region" {
  type        = string
  description = "Region for Cloud Run, Artifact Registry, Firestore, Scheduler."
  default     = "us-central1"
}

variable "image" {
  type        = string
  description = "Full image ref for the pipeline (must be pushed before apply/execute), e.g. us-central1-docker.pkg.dev/PROJECT/paper-prism/paper-prism:latest"
}

variable "gemini_api_key" {
  type        = string
  description = "AI Studio Gemini API key (stored in Secret Manager)."
  sensitive   = true
}

variable "alert_email" {
  type        = string
  description = "Email address for run-failure alerts."
}

# --- Interest profiles (the product; PRD §3.1) ---
variable "profile_aiml" {
  type        = string
  description = "AI/ML interest profile paragraph."
}

variable "profile_nlp" {
  type        = string
  description = "NLP interest profile paragraph."
}

variable "profile_cv" {
  type        = string
  description = "Computer Vision interest profile paragraph."
}

# --- Tunables ---
variable "gemini_model" {
  type    = string
  default = "gemini-2.5-flash"
}

variable "schedule" {
  type        = string
  default     = "0 9 * * 1" # Mondays 09:00
  description = "Cron schedule for the weekly run."
}

variable "time_zone" {
  type    = string
  default = "Etc/UTC"
}

variable "window_days" {
  type    = number
  default = 7
}

variable "top_k" {
  type    = number
  default = 3
}

variable "retention_days" {
  type        = number
  default     = 45
  description = "Firestore records older than this are auto-deleted via TTL (writes expire_at = run_date + retention_days)."
}

# --- Firebase Hosting is optional in Terraform (many teams manage it via the
#     firebase CLI). Off by default; see hosting.tf / README. ---
variable "enable_firebase_hosting" {
  type    = bool
  default = false
}

variable "hosting_site_id" {
  type    = string
  default = ""
}
