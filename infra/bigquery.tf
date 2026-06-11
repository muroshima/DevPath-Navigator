# BigQuery dataset. Tables (trajectories / embeddings / umap_coords /
# clusters / eval_results) are created from Python code (data-gen/load_to_bq.py,
# embedding/umap_cluster.py, eval/store.py) so their schemas can evolve with
# the application without a Terraform plan/apply cycle.

resource "google_bigquery_dataset" "devpath" {
  project                    = var.project_id
  dataset_id                 = var.bq_dataset_id
  location                   = var.region
  description                = "DevPath Navigator — synthetic career trajectories, embeddings, UMAP coords, clusters, and eval_results."
  delete_contents_on_destroy = false

  depends_on = [google_project_service.this]
}
