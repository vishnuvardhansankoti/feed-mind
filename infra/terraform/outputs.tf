output "artifact_registry_repo" {
  description = "Push the pipeline image here."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.repo.repository_id}"
}

output "job_name" {
  value = google_cloud_run_v2_job.pipeline.name
}

output "job_service_account" {
  value = google_service_account.job.email
}

output "scheduler_name" {
  value = google_cloud_scheduler_job.weekly.name
}

output "run_once_command" {
  description = "Smoke-test the pipeline end-to-end."
  value       = "gcloud run jobs execute ${google_cloud_run_v2_job.pipeline.name} --region ${var.region} --project ${var.project_id} --wait"
}
