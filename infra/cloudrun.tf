# Cloud Run services. We use the v2 API (google_cloud_run_v2_service) which
# matches what `gcloud run deploy` produces. Both services are public for
# the hackathon demo; tighten ingress before any non-demo use.

# Public-invoker IAM binding shared by both services.
locals {
  public_invoker = "allUsers"
}

# --- Agent ---------------------------------------------------------------

resource "google_cloud_run_v2_service" "agent" {
  project  = var.project_id
  name     = var.agent_service_name
  location = var.region

  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account = google_service_account.agent.email
    timeout         = "300s"

    # max=2 caps worst-case Gemini fan-out under attack while still allowing
    # one fresh instance to warm up while another is busy. max_instance_request_concurrency
    # = 8 keeps per-instance load light enough that the 2-vCPU container
    # isn't competing with itself for the BigQuery client / Gemini SDK.
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
    max_instance_request_concurrency = 8

    containers {
      image = var.agent_image

      resources {
        limits = {
          cpu    = "2"
          memory = "2Gi"
        }
        startup_cpu_boost = true
      }

      ports {
        container_port = 8080
      }

      env {
        name  = "GCP_PROJECT"
        value = var.project_id
      }
      env {
        name  = "BQ_LOCATION"
        value = var.region
      }
      env {
        name  = "BQ_DATASET"
        value = var.bq_dataset_id
      }
      env {
        name  = "VERTEX_LOCATION"
        value = var.vertex_region
      }
      env {
        name  = "GEMINI_MODEL"
        value = var.gemini_model
      }
      env {
        name  = "AGENT_BATCHES"
        value = var.agent_batches
      }
      env {
        name  = "GOOGLE_GENAI_USE_VERTEXAI"
        value = "true"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GOOGLE_CLOUD_LOCATION"
        value = var.vertex_region
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  depends_on = [
    google_project_service.this,
    google_project_iam_member.agent_runtime_project_roles,
    google_bigquery_dataset_iam_member.agent_devpath_reader,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "agent_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.agent.name
  role     = "roles/run.invoker"
  member   = local.public_invoker
}

# --- Frontend ------------------------------------------------------------

resource "google_cloud_run_v2_service" "frontend" {
  project  = var.project_id
  name     = var.frontend_service_name
  location = var.region

  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    timeout = "120s"

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
    max_instance_request_concurrency = 20

    containers {
      image = var.frontend_image

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
        startup_cpu_boost = true
      }

      ports {
        container_port = 8080
      }

      env {
        name  = "AGENT_URL"
        value = google_cloud_run_v2_service.agent.uri
      }
      env {
        name  = "NODE_ENV"
        value = "production"
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  depends_on = [google_project_service.this]
}

resource "google_cloud_run_v2_service_iam_member" "frontend_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.frontend.name
  role     = "roles/run.invoker"
  member   = local.public_invoker
}
