terraform {
  required_version = ">= 1.7"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.10, < 7.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = ">= 6.10, < 7.0"
    }
  }

  # The state lives locally by default so the repo is self-contained for the
  # hackathon submission. Switch to a GCS backend before any real shared use:
  #
  # backend "gcs" {
  #   bucket = "devpath-tfstate"
  #   prefix = "infra"
  # }
}
