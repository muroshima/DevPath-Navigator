"""Run the full evaluation: load corpus, embed, score, record, gate.

This is the single entry point invoked by the retraining pipeline. It is
also fine to run by hand from the repo root:

    uv run python eval/run.py --batches initial
    uv run python eval/run.py --batches initial drift

The script writes one row to BigQuery `devpath.eval_results` per invocation
and prints the gate's decision. Exit code 0 if decision is "pass" or
"baseline"; 1 if "fail".
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from gensim.models import KeyedVectors
from google.cloud import bigquery

from embedding.tokens import group_trajectory_by_employee
from embedding.train_w2v import DEFAULT_MODEL_PATH, load_trajectories
from eval.gate import decide
from eval.metrics import compute_all
from eval.store import EvalRecord, insert_record, latest_passing, now_utc

DEFAULT_PROJECT = os.environ.get("GCP_PROJECT", "ai-agent-hackathon-499013")
DEFAULT_LOCATION = os.environ.get("BQ_LOCATION", "asia-northeast1")
DEFAULT_DATASET = os.environ.get("BQ_DATASET", "devpath")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--batches", nargs="+", default=["initial"])
    ap.add_argument("--project", default=DEFAULT_PROJECT)
    ap.add_argument("--dataset", default=DEFAULT_DATASET)
    ap.add_argument("--location", default=DEFAULT_LOCATION)
    ap.add_argument("--model", type=Path, default=DEFAULT_MODEL_PATH)
    ap.add_argument("--notes", default=None)
    args = ap.parse_args()

    if not args.model.exists():
        print(f"ERROR: w2v model not found: {args.model}", file=sys.stderr)
        print("Hint: run `python embedding/train_w2v.py` first.", file=sys.stderr)
        return 1

    client = bigquery.Client(project=args.project, location=args.location)
    vectors: KeyedVectors = KeyedVectors.load(str(args.model))

    print(f"[eval] loading trajectories from BQ for batches={args.batches}")
    rows = load_trajectories(client, args.dataset, args.batches)
    grouped = group_trajectory_by_employee(rows)
    print(f"[eval] {len(grouped)} employees, {len(rows)} trajectory rows")

    metrics = compute_all(client, args.dataset, vectors, grouped)
    print("[eval] metrics:")
    for k, v in metrics.__dict__.items():
        print(f"  {k}: {v}")

    prev = latest_passing(client, args.dataset)
    if prev:
        print(f"[eval] comparing against prev run {prev.run_id} (decision={prev.decision})")
    else:
        print("[eval] no prior baseline; this run will be recorded as the baseline")

    dec = decide(metrics, prev)
    print(f"[eval] decision: {dec.decision}")
    for r in dec.reasons:
        print(f"  - {r}")

    record = EvalRecord(
        run_id=uuid.uuid4().hex[:12],
        run_at=now_utc(),
        batches=list(args.batches),
        recall_at_10=metrics.recall_at_10,
        n_clusters=metrics.n_clusters,
        n_noise=metrics.n_noise,
        mean_archetype_purity=metrics.mean_archetype_purity,
        archetypes_covered=metrics.archetypes_covered,
        vocab_size=metrics.vocab_size,
        held_out_n=metrics.held_out_n,
        decision=dec.decision,
        decision_reasons=dec.reasons,
        notes=args.notes,
        min_recall_per_archetype=metrics.min_recall_per_archetype,
    )
    insert_record(client, args.dataset, record)
    print(f"[eval] recorded run {record.run_id}")

    return 0 if dec.decision in ("pass", "baseline") else 1


if __name__ == "__main__":
    sys.exit(main())
