# Runtime service account for the Cloud Run agent. Cloud Run uses this SA's
# identity to call Vertex AI Gemini and BigQuery at request time.
resource "google_service_account" "agent" {
  project      = var.project_id
  account_id   = "devpath-agent-sa"
  display_name = "DevPath Navigator agent runtime"
  description  = "Runtime SA for the Cloud Run agent service (Gemini + BigQuery)."

  depends_on = [google_project_service.this]
}

# Project-level roles. BigQuery dataViewer is intentionally NOT here — we
# scope read access to the single devpath dataset below. jobUser is
# project-level because BigQuery does not expose a dataset-scoped equivalent
# (a query job is owned by the project, not the dataset it touches).
locals {
  agent_runtime_project_roles = [
    "roles/aiplatform.user", # invoke Gemini via Vertex
    "roles/bigquery.jobUser", # run queries (BQ requires project scope)
    "roles/logging.logWriter", # structured logs from the container
  ]
}

resource "google_project_iam_member" "agent_runtime_project_roles" {
  for_each = toset(local.agent_runtime_project_roles)
  project  = var.project_id
  role     = each.key
  member   = "serviceAccount:${google_service_account.agent.email}"
}

# Dataset-scoped read access. If the project ever grows to host other
# datasets, the agent SA cannot see them.
resource "google_bigquery_dataset_iam_member" "agent_devpath_reader" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.devpath.dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.agent.email}"
}

# Whoever runs `gcloud run deploy --service-account <agent SA>` needs to be
# able to act as the runtime SA. For a single-developer hackathon repo this
# is a person; in a real setup it'd be a CI builder SA. We only create the
# binding if a principal was supplied — keeping the default empty stops the
# repo from leaking any real identity.
resource "google_service_account_iam_member" "deployer_act_as_agent" {
  count = var.deployer_principal == "" ? 0 : 1

  service_account_id = google_service_account.agent.name
  role               = "roles/iam.serviceAccountUser"
  member             = var.deployer_principal
}
