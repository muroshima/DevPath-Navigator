variable "project_id" {
  description = "GCP project id for the hackathon environment."
  type        = string
  default     = "ai-agent-hackathon-499013"
}

variable "region" {
  description = "Cloud Run / BigQuery region. Used as the BQ dataset location and Cloud Run region."
  type        = string
  default     = "asia-northeast1"
}

variable "vertex_region" {
  description = "Vertex AI region for Gemini calls (split from BQ region because not all Gemini models ship in every region simultaneously)."
  type        = string
  default     = "us-central1"
}

variable "bq_dataset_id" {
  description = "BigQuery dataset where trajectories / embeddings / umap_coords / clusters / eval_results live."
  type        = string
  default     = "devpath"
}

variable "agent_service_name" {
  description = "Cloud Run service name for the agent (ADK + Gemini)."
  type        = string
  default     = "devpath-agent"
}

variable "frontend_service_name" {
  description = "Cloud Run service name for the Next.js frontend."
  type        = string
  default     = "devpath-frontend"
}

variable "agent_image" {
  description = <<EOT
Full container image reference for the agent. After the first deploy via
`gcloud run deploy --source .`, this is something like:
  asia-northeast1-docker.pkg.dev/<project>/cloud-run-source-deploy/<sha>

Override at apply time to roll forward. Leave at the placeholder if you
import an existing service into state.
EOT
  type    = string
  default = "asia-northeast1-docker.pkg.dev/ai-agent-hackathon-499013/cloud-run-source-deploy/devpath-agent:latest"
}

variable "frontend_image" {
  description = "Full container image reference for the frontend. Same shape as agent_image."
  type        = string
  default     = "asia-northeast1-docker.pkg.dev/ai-agent-hackathon-499013/cloud-run-source-deploy/devpath-frontend:latest"
}

variable "gemini_model" {
  description = "Gemini model id passed to the agent via env var."
  type        = string
  default     = "gemini-2.5-flash"
}

variable "agent_batches" {
  description = "Comma-separated batch ids the agent should train Word2Vec on at startup (e.g. \"initial\" or \"initial,drift\")."
  type        = string
  default     = "initial,drift"
}

variable "deployer_principal" {
  description = <<EOT
Principal that needs serviceAccountUser on the agent runtime SA to deploy
Cloud Run. Format: "user:foo@example.com" or "serviceAccount:builder@...".

No default — set this in terraform.tfvars (which is gitignored) so the
repository never carries a real identity. The corresponding IAM binding
is only created when this is non-empty (see iam.tf).
EOT
  type    = string
  default = ""
}
