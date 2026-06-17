"""Process-wide agent state.

Holds a BigQuery client and a Word2Vec model trained from the BQ corpus at
startup. The trained model is small (~1MB for the current corpus) and stays
in memory for the lifetime of the process — Cloud Run gives us a fresh
container per revision, which gives us free model refresh on deploy.

When the retraining loop is wired up (Week 3), this will switch to loading
a versioned KeyedVectors artifact from GCS instead of training in-process.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from gensim.models import KeyedVectors, Word2Vec
from google.cloud import bigquery

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from embedding.tokens import group_trajectory_by_employee, trajectory_tokens
from embedding.train_w2v import W2V_PARAMS, load_trajectories

DEFAULT_PROJECT = os.environ.get("GCP_PROJECT", "ai-agent-hackathon-499013")
DEFAULT_LOCATION = os.environ.get("BQ_LOCATION", "asia-northeast1")
DEFAULT_DATASET = os.environ.get("BQ_DATASET", "devpath")
DEFAULT_BATCHES = tuple(os.environ.get("AGENT_BATCHES", "initial").split(","))

# Hard ceiling on bytes any single BigQuery job spawned via the shared
# client is allowed to scan. Applied as `default_query_job_config` so
# every tool inherits it — `nlq_over_corpus` previously set this
# per-query, but the hand-written queries in `explain_cluster`,
# `skill_gap_analysis`, `recommend_next_steps`, and
# `find_similar_trajectories` had no cap until this default landed.
# 100 MB is generous for a corpus that fits well under 10 MB and
# bounds the worst case if a future query slips past the regex
# validator or if a hand-written query develops an accidental
# cartesian join.
DEFAULT_MAX_BYTES_BILLED = 100 * 1024 * 1024  # 100 MB


@dataclass
class AppState:
    bq_client: bigquery.Client
    vectors: KeyedVectors
    project: str
    dataset: str
    location: str


def build_state(
    project: str = DEFAULT_PROJECT,
    dataset: str = DEFAULT_DATASET,
    location: str = DEFAULT_LOCATION,
    batches: tuple[str, ...] = DEFAULT_BATCHES,
) -> AppState:
    print(f"[state] BQ client project={project} location={location}", flush=True)
    client = bigquery.Client(
        project=project,
        location=location,
        default_query_job_config=bigquery.QueryJobConfig(
            maximum_bytes_billed=DEFAULT_MAX_BYTES_BILLED,
        ),
    )

    print(f"[state] loading trajectories from `{project}.{dataset}.trajectories` "
          f"batches={list(batches)}", flush=True)
    rows = load_trajectories(client, dataset, list(batches))
    if not rows:
        raise RuntimeError(f"No trajectories found for batches {batches}")

    grouped = group_trajectory_by_employee(rows)
    sentences = [trajectory_tokens(steps) for steps in grouped.values()]
    print(f"[state] training Word2Vec on {len(sentences)} sentences "
          f"({sum(len(s) for s in sentences)} tokens)", flush=True)
    model = Word2Vec(sentences=sentences, **W2V_PARAMS)
    print(f"[state] vocab={len(model.wv)} dim={model.wv.vector_size}", flush=True)

    return AppState(
        bq_client=client,
        vectors=model.wv,
        project=project,
        dataset=dataset,
        location=location,
    )


# Module-level singleton (set by server lifespan, read by tools)
_state: AppState | None = None


def set_state(state: AppState) -> None:
    global _state
    _state = state


def get_state() -> AppState:
    if _state is None:
        raise RuntimeError("AppState not initialized. Call set_state() during startup.")
    return _state
