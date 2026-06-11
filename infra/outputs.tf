output "agent_url" {
  description = "Public URL of the Cloud Run agent service."
  value       = google_cloud_run_v2_service.agent.uri
}

output "frontend_url" {
  description = "Public URL of the Next.js frontend."
  value       = google_cloud_run_v2_service.frontend.uri
}

output "agent_sa_email" {
  description = "Email of the runtime SA used by both Cloud Run services that talk to Vertex / BigQuery."
  value       = google_service_account.agent.email
}

output "bq_dataset" {
  description = "Fully-qualified BigQuery dataset id (`<project>.<dataset>`)."
  value       = "${var.project_id}.${var.bq_dataset_id}"
}
