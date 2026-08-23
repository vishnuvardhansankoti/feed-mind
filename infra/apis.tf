locals {
  services = [
    "run.googleapis.com",
    "cloudscheduler.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "firestore.googleapis.com",
    # The job publishes a "run finished" message (pipeline/src/paper_prism/events.py).
    # The topic itself belongs to the consumer, feed-mind-summarizer.
    "pubsub.googleapis.com",
    "cloudbuild.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "iam.googleapis.com",
  ]
}

resource "google_project_service" "enabled" {
  for_each = toset(local.services)
  service  = each.value

  disable_on_destroy = false
}
