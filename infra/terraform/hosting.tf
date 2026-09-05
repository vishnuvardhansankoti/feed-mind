# Firebase Hosting (optional). Terraform can create the Hosting *site*, but the
# static content (web/dist) is still uploaded with the firebase CLI
# (`firebase deploy --only hosting`) — Terraform does not push assets. Many teams
# manage Hosting entirely via the CLI, so this is off by default
# (enable_firebase_hosting = true to manage the site here).
#
# Requires the project to be Firebase-enabled (firebase.googleapis.com) and, on
# first use, a google_firebase_project registration (not managed here to keep the
# core stack provider-light).

resource "google_firebase_hosting_site" "site" {
  count    = var.enable_firebase_hosting ? 1 : 0
  provider = google-beta
  project  = var.project_id
  site_id  = var.hosting_site_id
}
