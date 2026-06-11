#!/usr/bin/env bash
# Generate the ml->genai drift batch and append it to BigQuery.
#
# The drift batch was reserved in data-gen/generate.py (BATCH_SPECS['drift'])
# specifically for this demo: 300 employees whose trajectories transition
# from ml_engineer to genai_engineer. The initial corpus does not contain
# any genai_engineer transitions, so injecting this batch is what creates
# the "before/after" gap the retraining loop is supposed to close.
#
# Usage:
#   pipelines/inject-drift.sh                  # generate + load + kick cloud retrain
#   pipelines/inject-drift.sh --skip-load      # only regenerate the JSONL
#   NO_CLOUD_RETRAIN=1 pipelines/inject-drift.sh  # load but don't trigger Cloud Build

set -euo pipefail

cd "$(dirname "$0")/.."

PROJECT="${GCP_PROJECT:-ai-agent-hackathon-499013}"
REGION="${GCP_REGION:-asia-northeast1}"

SKIP_LOAD=0
for arg in "$@"; do
  case "$arg" in
    --skip-load) SKIP_LOAD=1 ;;
    *) echo "unknown arg: $arg"; exit 2 ;;
  esac
done

echo "[drift] generating drift batch (300 employees, ml->genai)…"
uv run python data-gen/generate.py --batch drift

if [[ "$SKIP_LOAD" == "1" ]]; then
  echo "[drift] --skip-load set, stopping before BigQuery."
  exit 0
fi

echo "[drift] loading drift batch into BigQuery…"
uv run python data-gen/load_to_bq.py --batch drift

if [[ "${NO_CLOUD_RETRAIN:-0}" == "1" ]]; then
  echo "[drift] NO_CLOUD_RETRAIN=1 — data loaded; run pipelines/retrain.sh manually."
  exit 0
fi

echo "[drift] new data arrived — triggering Cloud Build retraining pipeline…"
gcloud builds submit \
  --config pipelines/cloudbuild.retrain.yaml \
  --project "$PROJECT" \
  --region "$REGION" \
  --substitutions _REGION="$REGION",_BATCHES="initial drift" \
  .

echo "[drift] done. Cloud Build ran retrain → evaluate → gate → (on pass) deploy."
