# infra — Terraform for DevPath Navigator

**English** &nbsp;|&nbsp; [日本語](./README.ja.md)

Codifies the GCP environment the live demo runs on so the repo can be
re-stood-up in a fresh project without re-discovering manual `gcloud`
incantations.

**Managed by Terraform**
- The 12 GCP APIs that have to be enabled before anything works
  (Cloud Run, BigQuery, Vertex AI, Cloud Build, Artifact Registry,
  Secret Manager, Storage, IAM, IAM Credentials, Cloud Resource Manager,
  Logging, Monitoring)
- The agent runtime service account `devpath-agent-sa`, its three
  project-level roles (`aiplatform.user`, `bigquery.jobUser`,
  `logging.logWriter`), its dataset-scoped `bigquery.dataViewer` on
  `devpath`, and the `iam.serviceAccountUser` binding for the deployer
  (optional — only created when `deployer_principal` is set)
- BigQuery dataset `devpath` in `asia-northeast1`
- Cloud Run services `devpath-agent` and `devpath-frontend`, including
  their env vars, runtime SA wiring, and public-invoker IAM binding

**Intentionally NOT managed by Terraform**
- BigQuery table schemas — they live in `data-gen/load_to_bq.py`,
  `embedding/umap_cluster.py`, and `eval/store.py` so they evolve with
  the code rather than via plan/apply cycles
- The synthetic data itself — `data-gen/generate.py` is the source of
  truth
- Container images — built/pushed by `gcloud run deploy --source .`;
  Terraform only owns the service shell

## Quick start (fresh project)

```bash
cd infra
terraform init
terraform plan -out=plan.out
terraform apply plan.out
```

For first-time deploy, the `agent_image` / `frontend_image` variables
default to the Artifact Registry path that `gcloud run deploy --source .`
populates; after the first build, point them at the immutable SHA-pinned
image to lock in.

## Adopting the existing live demo (state import)

If you want Terraform to take over the resources already running, import
each one into state before the first `apply`:

```bash
cd infra
terraform init

PROJECT=ai-agent-hackathon-499013
REGION=asia-northeast1

# 1) API services
for svc in run bigquery aiplatform cloudbuild artifactregistry secretmanager \
           storage iam iamcredentials cloudresourcemanager logging monitoring; do
  terraform import "google_project_service.this[\"$svc.googleapis.com\"]" \
    "$PROJECT/$svc.googleapis.com"
done

# 2) Service account + project-level role bindings
terraform import google_service_account.agent \
  "projects/$PROJECT/serviceAccounts/devpath-agent-sa@$PROJECT.iam.gserviceaccount.com"

for role in roles/aiplatform.user roles/bigquery.jobUser roles/logging.logWriter; do
  terraform import "google_project_iam_member.agent_runtime_project_roles[\"$role\"]" \
    "$PROJECT $role serviceAccount:devpath-agent-sa@$PROJECT.iam.gserviceaccount.com"
done

# 3) Dataset-scoped bigquery.dataViewer (must come AFTER the dataset import in step 4 below
#    if you do them out of order — easier to just defer this line to the end)

# Optional: only run this if you set `deployer_principal` in terraform.tfvars.
# Without it, the count = 0 in iam.tf skips this resource entirely, so this
# import is unnecessary. Replace <deployer_principal> with the exact same value
# you put in tfvars (e.g. `user:foo@example.com` or `serviceAccount:builder@…`).
#
# DEPLOYER='user:foo@example.com'
# terraform import 'google_service_account_iam_member.deployer_act_as_agent[0]' \
#   "projects/$PROJECT/serviceAccounts/devpath-agent-sa@$PROJECT.iam.gserviceaccount.com roles/iam.serviceAccountUser $DEPLOYER"

# 4) BigQuery dataset
terraform import google_bigquery_dataset.devpath "projects/$PROJECT/datasets/devpath"

# 5) Dataset-scoped bigquery.dataViewer (deferred from step 3 above)
terraform import google_bigquery_dataset_iam_member.agent_devpath_reader \
  "projects/$PROJECT/datasets/devpath roles/bigquery.dataViewer serviceAccount:devpath-agent-sa@$PROJECT.iam.gserviceaccount.com"

# 6) Cloud Run services + public invoker bindings
terraform import google_cloud_run_v2_service.agent \
  "projects/$PROJECT/locations/$REGION/services/devpath-agent"
terraform import google_cloud_run_v2_service.frontend \
  "projects/$PROJECT/locations/$REGION/services/devpath-frontend"

terraform import "google_cloud_run_v2_service_iam_member.agent_public" \
  "projects/$PROJECT/locations/$REGION/services/devpath-agent roles/run.invoker allUsers"
terraform import "google_cloud_run_v2_service_iam_member.frontend_public" \
  "projects/$PROJECT/locations/$REGION/services/devpath-frontend roles/run.invoker allUsers"

# Verify the import didn't introduce unintended changes:
terraform plan
```

The first `terraform plan` after import will almost certainly want to
re-write a few container env vars or labels — review carefully before
applying. The `agent_image` variable in particular needs to be set to
the currently-running image SHA (see
`gcloud run services describe devpath-agent --format="value(spec.template.spec.containers[0].image)"`).

## Backend

State lives locally for the hackathon. Switch to GCS before sharing:

```hcl
# versions.tf
backend "gcs" {
  bucket = "devpath-tfstate"
  prefix = "infra"
}
```

```bash
gcloud storage buckets create gs://devpath-tfstate --location=asia-northeast1
terraform init -migrate-state
```
