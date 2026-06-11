"""Evaluation metrics for the embedding + clustering pipeline.

These are decision-grade metrics — they decide whether a retrained model gets
promoted to Cloud Run. The signal must be stable across runs, so everything
here is deterministic given the same BigQuery contents and the same seed.

Two metric families:

1. Recall@10 on next-step prediction (decision-grade):
   For each held-out employee, take their first (n-1) steps as input, embed
   with the *current* Word2Vec, and look up the top-10 nearest engineers in
   BigQuery's embeddings table (excluding the held-out themselves). The
   held-out's actual next step's role is the ground truth. Recall@10 is the
   fraction of held-out users whose true next role appears in the next-step
   roles of any of the 10 neighbors.

2. Cluster + corpus stats (descriptive):
   - n_clusters (excluding the -1 noise label)
   - mean_archetype_purity across real clusters
   - distinct archetypes covered by at least one cluster
   - vocab_size (number of distinct tokens the trained W2V knows)

The held-out set is built deterministically from a fixed seed and stratified
by archetype, so changes in held-out membership across runs don't muddy the
metric.
"""

from __future__ import annotations

import random
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gensim.models import KeyedVectors
from google.cloud import bigquery

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from embedding.trajectory import embed_trajectory

HELDOUT_PER_ARCHETYPE = 25
HELDOUT_SEED = 20260611


@dataclass
class EvalMetrics:
    recall_at_10: float
    n_clusters: int
    n_noise: int
    mean_archetype_purity: float
    archetypes_covered: list[str]
    vocab_size: int
    held_out_n: int


def _primary_role(roles_field: Any) -> str | None:
    """Pull the role with the most years from a schema-v2 roles array."""
    if not roles_field:
        return None
    best_role: str | None = None
    best_years = -1.0
    for entry in roles_field:
        if isinstance(entry, dict):
            r = entry.get("role")
            y = float(entry.get("years") or 0)
        else:
            r = getattr(entry, "role", None)
            y = float(getattr(entry, "years", 0) or 0)
        if r and y > best_years:
            best_role, best_years = r, y
    return best_role


def stratified_heldout(
    grouped: dict[str, list[dict[str, Any]]],
    n_per_archetype: int = HELDOUT_PER_ARCHETYPE,
    seed: int = HELDOUT_SEED,
) -> list[str]:
    """Pick a deterministic, archetype-stratified set of held-out employees."""
    by_archetype: dict[str, list[str]] = defaultdict(list)
    for emp, steps in grouped.items():
        if len(steps) < 2:
            continue
        archetype = steps[0].get("archetype", "")
        by_archetype[archetype].append(emp)

    rng = random.Random(seed)
    held: list[str] = []
    for emps in by_archetype.values():
        emps_sorted = sorted(emps)
        rng.shuffle(emps_sorted)
        held.extend(emps_sorted[:n_per_archetype])
    return held


def compute_recall_at_10(
    client: bigquery.Client,
    dataset: str,
    grouped: dict[str, list[dict[str, Any]]],
    vectors: KeyedVectors,
    held_out: list[str],
) -> float:
    """Recall@10 on next-role prediction (primary role per step).

    The neighbors are taken from the embeddings table via VECTOR_SEARCH;
    we ask for top_k=11 and then drop any row whose employee_id matches the
    held-out user (otherwise the user could trivially self-match).
    """
    if not held_out:
        return 0.0

    project = client.project
    sql = f"""
    WITH neighbors AS (
      SELECT base.employee_id, distance
      FROM VECTOR_SEARCH(
        TABLE `{project}.{dataset}.embeddings`,
        'vector',
        (SELECT @qv AS vector),
        top_k => 11,
        distance_type => 'COSINE'
      )
    )
    SELECT n.employee_id, n.distance, t.step, t.roles
    FROM neighbors n
    JOIN `{project}.{dataset}.trajectories` t
      USING (employee_id)
    ORDER BY n.distance, t.step
    """

    hits = 0
    for emp in held_out:
        steps = grouped[emp]
        if len(steps) < 2:
            continue
        truncated = steps[:-1]
        actual_next_role = _primary_role(steps[-1].get("roles"))
        if not actual_next_role:
            continue
        truncated_n = len(truncated)

        vec = embed_trajectory(truncated, vectors)
        if vec is None:
            continue

        job = client.query(
            sql,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ArrayQueryParameter("qv", "FLOAT64", vec.tolist()),
                ]
            ),
        )
        rows = list(job.result())

        by_emp: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in rows:
            if r.employee_id == emp:
                continue
            by_emp[r.employee_id].append({"step": int(r.step), "roles": list(r.roles or [])})
        top10 = list(by_emp.keys())[:10]

        predicted_next_roles: set[str] = set()
        for n_emp in top10:
            n_steps = sorted(by_emp[n_emp], key=lambda s: s["step"])
            if not n_steps:
                continue
            target = n_steps[truncated_n] if truncated_n < len(n_steps) else n_steps[-1]
            pr = _primary_role(target.get("roles"))
            if pr:
                predicted_next_roles.add(pr)

        if actual_next_role in predicted_next_roles:
            hits += 1

    return hits / len(held_out)


def compute_cluster_stats(
    client: bigquery.Client,
    dataset: str,
) -> dict[str, Any]:
    project = client.project
    cluster_rows = list(client.query(
        f"SELECT cluster_id, size, dominant_archetype, archetype_purity "
        f"FROM `{project}.{dataset}.clusters`"
    ).result())
    real = [r for r in cluster_rows if int(r.cluster_id) >= 0]
    n_clusters = len(real)
    n_noise = sum(int(r.size) for r in cluster_rows if int(r.cluster_id) < 0)
    mean_purity = (
        sum(float(r.archetype_purity or 0) for r in real) / n_clusters if n_clusters else 0.0
    )
    archetypes_covered = sorted({r.dominant_archetype for r in real if r.dominant_archetype})
    return {
        "n_clusters": n_clusters,
        "n_noise": n_noise,
        "mean_archetype_purity": mean_purity,
        "archetypes_covered": archetypes_covered,
    }


def compute_all(
    client: bigquery.Client,
    dataset: str,
    vectors: KeyedVectors,
    grouped: dict[str, list[dict[str, Any]]],
) -> EvalMetrics:
    held = stratified_heldout(grouped)
    recall = compute_recall_at_10(client, dataset, grouped, vectors, held)
    stats = compute_cluster_stats(client, dataset)
    return EvalMetrics(
        recall_at_10=recall,
        n_clusters=stats["n_clusters"],
        n_noise=stats["n_noise"],
        mean_archetype_purity=stats["mean_archetype_purity"],
        archetypes_covered=stats["archetypes_covered"],
        vocab_size=len(vectors),
        held_out_n=len(held),
    )
