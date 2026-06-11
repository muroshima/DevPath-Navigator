# GCP APIs that the project depends on. `disable_on_destroy = false` keeps
# the API enabled if this resource is removed — disabling APIs underneath
# live services is destructive and you almost never want it automated.

locals {
  enabled_services = [
    "run.googleapis.com",
    "bigquery.googleapis.com",
    "aiplatform.googleapis.com",
    "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
  ]
}

resource "google_project_service" "this" {
  for_each           = toset(local.enabled_services)
  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}
