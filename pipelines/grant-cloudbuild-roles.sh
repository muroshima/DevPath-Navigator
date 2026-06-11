#!/usr/bin/env bash
# One-time setup: grant the Cloud Build service account the roles it needs
# to run pipelines/cloudbuild.retrain.yaml (BQ writes, Cloud Run deploy,
# actAs on the agent runtime SA).

set -euo pipefail

PROJECT="${GCP_PROJECT:-ai-agent-hackathon-499013}"
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format="value(projectNumber)")
CB_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
# Note: newer Cloud Build runs default to the Compute Engine default SA.
# If your build logs show <project-number>@cloudbuild.gserviceaccount.com
# instead, re-run with CB_SA overridden.
CB_SA="${CB_SA_OVERRIDE:-$CB_SA}"
AGENT_SA="devpath-agent-sa@${PROJECT}.iam.gserviceaccount.com"

echo "Granting roles to $CB_SA on project $PROJECT…"
for role in \
  roles/bigquery.dataEditor \
  roles/bigquery.jobUser \
  roles/run.developer \
  roles/artifactregistry.writer \
  roles/logging.logWriter \
  roles/storage.objectViewer; do
  echo "--- $role"
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:$CB_SA" --role="$role" --condition=None --quiet >/dev/null
done

echo "--- roles/iam.serviceAccountUser on $AGENT_SA"
gcloud iam service-accounts add-iam-policy-binding "$AGENT_SA" \
  --member="serviceAccount:$CB_SA" --role=roles/iam.serviceAccountUser \
  --project="$PROJECT" --quiet >/dev/null

echo "Done."
