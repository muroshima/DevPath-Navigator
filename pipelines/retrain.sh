#!/usr/bin/env bash
# Retrain the embedding pipeline on whichever batches currently live in
# BigQuery, run the evaluation gate, and (on pass) redeploy the Cloud Run
# agent so it picks up the new corpus on its next cold start.
#
# Stages:
#   1. embedding/train_w2v.py    --batches $BATCHES
#   2. embedding/umap_cluster.py --batches $BATCHES   # overwrites BQ tables
#   3. embedding/plot.py                              # updates docs/cluster_map.png
#   4. eval/run.py               --batches $BATCHES   # records to eval_results, decides
#   5. on pass: gcloud run deploy devpath-agent       # new revision -> fresh W2V at boot
#   on fail: stop with non-zero exit; nothing is deployed
#
# Usage:
#   pipelines/retrain.sh                        # batches=initial,drift if drift exists, else initial
#   BATCHES="initial drift" pipelines/retrain.sh
#   SKIP_DEPLOY=1 pipelines/retrain.sh          # eval gate runs but skip Cloud Run deploy

set -euo pipefail

cd "$(dirname "$0")/.."

PROJECT="${GCP_PROJECT:-ai-agent-hackathon-499013}"
REGION="${GCP_REGION:-asia-northeast1}"
DATASET="${BQ_DATASET:-devpath}"
SA="${AGENT_SA:-devpath-agent-sa@${PROJECT}.iam.gserviceaccount.com}"
AGENT_URL="${AGENT_URL_OVERRIDE:-https://devpath-agent-430189693163.${REGION}.run.app}"

# Auto-detect batches: include "drift" iff its rows live in BigQuery.
if [[ -z "${BATCHES:-}" ]]; then
  drift_count=$(bq --project_id="$PROJECT" --location="$REGION" \
    query --use_legacy_sql=false --quiet --format=csv \
    "SELECT COUNT(*) FROM \`${PROJECT}.${DATASET}.trajectories\` WHERE batch_id = 'drift'" \
    2>/dev/null | tail -1)
  if [[ "${drift_count:-0}" -gt 0 ]]; then
    BATCHES="initial drift"
  else
    BATCHES="initial"
  fi
fi

echo "[retrain] project=$PROJECT region=$REGION dataset=$DATASET"
echo "[retrain] batches: $BATCHES"

echo "[retrain] (1/4) training Word2Vec…"
uv run python embedding/train_w2v.py --batches $BATCHES

echo "[retrain] (2/4) UMAP + HDBSCAN + BQ writeback…"
uv run python embedding/umap_cluster.py --batches $BATCHES

echo "[retrain] (3/4) refreshing docs/cluster_map.png…"
uv run python embedding/plot.py

echo "[retrain] (4/4) evaluating + gating…"
if ! uv run python eval/run.py --batches $BATCHES --notes "retrain.sh batches=${BATCHES// /,}"; then
  echo "[retrain] ❌ gate failed — Cloud Run deploy blocked. See eval_results for reasons." >&2
  exit 1
fi

if [[ "${SKIP_DEPLOY:-0}" == "1" ]]; then
  echo "[retrain] SKIP_DEPLOY=1; gate passed but skipping Cloud Run redeploy."
  exit 0
fi

# The agent container trains its Word2Vec from BigQuery at startup, so a
# retraining "deploy" doesn't need a new image — rolling a new revision with
# the same image (and the updated AGENT_BATCHES) makes the next cold start
# pick up the refreshed corpus. This keeps the retrain path fast and lets it
# run from Cloud Build without nested image builds.
echo "[retrain] gate passed; rolling a new Cloud Run revision…"
gcloud run services update devpath-agent \
  --region "$REGION" --project "$PROJECT" \
  --update-env-vars "AGENT_BATCHES=$(echo $BATCHES | tr ' ' ','),RETRAINED_AT=$(date -u +%Y%m%dT%H%M%SZ)" \
  --quiet

echo "[retrain] ✅ done. agent serving from $AGENT_URL"
