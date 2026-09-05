# Observability / alerting (PRD §9a). The pipeline logs the phrase
# "RUN COMPLETED WITH FAILURES" whenever any lens was skipped or failed
# (best-effort semantics). A log-based counter + alert policy emails on it.

resource "google_logging_metric" "run_failures" {
  name   = "paper_prism_run_failures"
  filter = <<-EOT
    resource.type="cloud_run_job"
    resource.labels.job_name="${google_cloud_run_v2_job.pipeline.name}"
    "RUN COMPLETED WITH FAILURES"
  EOT

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }

  depends_on = [google_project_service.enabled]
}

resource "google_monitoring_notification_channel" "email" {
  display_name = "paper-prism alerts"
  type         = "email"

  labels = {
    email_address = var.alert_email
  }

  depends_on = [google_project_service.enabled]
}

resource "google_monitoring_alert_policy" "run_failures" {
  display_name = "paper-prism run failures"
  combiner     = "OR"

  conditions {
    display_name = "Pipeline reported per-lens failures"

    condition_threshold {
      filter          = "resource.type=\"cloud_run_job\" AND metric.type=\"logging.googleapis.com/user/${google_logging_metric.run_failures.name}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period   = "3600s"
        per_series_aligner = "ALIGN_COUNT"
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.id]

  alert_strategy {
    auto_close = "1800s"
  }

  documentation {
    content = "paper-prism logged RUN COMPLETED WITH FAILURES: at least one lens was skipped or failed in the latest run. Check Cloud Run job logs and the run_status document in Firestore."
  }
}
