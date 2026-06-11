"""Train a Word2Vec model on synthetic trajectory token sequences.

Reads trajectories from BigQuery (the table written by data-gen/load_to_bq.py),
flattens each employee into a single sentence, and trains a skip-gram
Word2Vec model. The trained KeyedVectors are saved to data/embeddings/w2v.kv
for later steps in the pipeline.

Usage:
    python embedding/train_w2v.py --batches initial
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from gensim.models import Word2Vec
from google.cloud import bigquery

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from embedding.tokens import group_trajectory_by_employee, trajectory_tokens

DEFAULT_PROJECT = os.environ.get("GCP_PROJECT", "ai-agent-hackathon-499013")
DEFAULT_LOCATION = os.environ.get("BQ_LOCATION", "asia-northeast1")
DEFAULT_DATASET = os.environ.get("BQ_DATASET", "devpath")

OUTPUT_DIR = REPO_ROOT / "data" / "embeddings"
DEFAULT_MODEL_PATH = OUTPUT_DIR / "w2v.kv"

# Hyperparameters — small dataset (~1.2k employees, ~50-token vocab), so we
# train for many epochs to converge.
W2V_PARAMS = dict(
    vector_size=128,
    window=5,
    min_count=1,
    sg=1,                # skip-gram
    negative=5,
    epochs=60,
    workers=1,           # single-thread for bit-identical training across machines
    seed=20260610,
)


def load_trajectories(
    client: bigquery.Client,
    dataset: str,
    batches: list[str],
) -> list[dict]:
    sql = f"""
    SELECT employee_id, step, roles, tech_stack, seniority, archetype, batch_id
    FROM `{client.project}.{dataset}.trajectories`
    WHERE batch_id IN UNNEST(@batches)
    ORDER BY employee_id, step
    """
    job = client.query(
        sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ArrayQueryParameter("batches", "STRING", batches)]
        ),
    )
    return [dict(row) for row in job.result()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--batches", nargs="+", default=["initial"],
                    help="Batch ids to train on (default: initial)")
    ap.add_argument("--project", default=DEFAULT_PROJECT)
    ap.add_argument("--dataset", default=DEFAULT_DATASET)
    ap.add_argument("--location", default=DEFAULT_LOCATION)
    ap.add_argument("--output", type=Path, default=DEFAULT_MODEL_PATH)
    args = ap.parse_args()

    client = bigquery.Client(project=args.project, location=args.location)
    rows = load_trajectories(client, args.dataset, args.batches)
    if not rows:
        print("ERROR: no trajectory rows returned from BQ", file=sys.stderr)
        return 1

    grouped = group_trajectory_by_employee(rows)
    sentences = [trajectory_tokens(steps) for steps in grouped.values()]
    print(f"Training Word2Vec on {len(sentences)} employee sentences "
          f"({sum(len(s) for s in sentences)} tokens, "
          f"{len(set(t for s in sentences for t in s))} unique)")

    model = Word2Vec(sentences=sentences, **W2V_PARAMS)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    model.wv.save(str(args.output))
    print(f"Saved KeyedVectors to {args.output}")
    print(f"  vocab size: {len(model.wv)}")
    print(f"  vector_size: {model.wv.vector_size}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
