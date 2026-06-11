"""Tool: locate_user — place the user on the career-cluster map."""

from __future__ import annotations

from collections import Counter

from google.cloud import bigquery

from agent.state import get_state
from agent.tools._common import build_steps, embed_user, vector_search

K_NEIGHBORS = 10


def locate_user(
    steps_roles: list[list[str]],
    steps_role_years: list[list[float]],
    steps_tech: list[list[str]],
    steps_seniority: list[str],
) -> dict:
    """Place a user on the 2D career-cluster map based on their trajectory.

    The user's trajectory is embedded with the same Word2Vec / time-decay
    function used for the corpus. The k nearest corpus employees in embedding
    space vote (by inverse-distance weight) on the user's cluster, and their
    UMAP coordinates are averaged to produce the user's 2D position.

    The trajectory is described by FOUR parallel lists, one entry per step
    (oldest first). For step i:
      steps_roles[i]       = list of role names the user held in this step
                             (e.g. ["backend"] for one role, or
                             ["backend", "tech_lead"] for a multi-role step)
      steps_role_years[i]  = list of years parallel to steps_roles[i]
                             (e.g. [4.0] or [4.0, 1.5])
      steps_tech[i]        = list of tech tokens used in this step
                             (taxonomy form: "lang.python", "infra.kubernetes")
      steps_seniority[i]   = the step's seniority level
                             (one of "junior" / "mid" / "senior" / "staff" / "manager")

    All four lists must have the same length. Within each step,
    steps_roles[i] and steps_role_years[i] must be the same length.

    Returns:
        A dict with the user's cluster_id, the cluster's dominant archetype,
        archetype purity, cluster size, user's UMAP coordinates (x, y), and
        the top-5 nearest neighbor employees (employee_id, archetype,
        distance). If embedding fails (no known tokens), an "error" key
        is returned.
    """
    steps = build_steps(steps_roles, steps_role_years, steps_tech, steps_seniority)
    if steps is None:
        return {"error": "Parallel arrays steps_roles / steps_role_years / steps_tech / steps_seniority must align."}

    vec = embed_user(steps)
    if vec is None:
        return {"error": "Could not embed trajectory — no tokens matched the taxonomy vocabulary."}

    neighbors = vector_search(vec, top_k=K_NEIGHBORS)
    if not neighbors:
        return {"error": "Embeddings table returned no neighbors."}

    weights = [1.0 / (0.01 + n.distance) for n in neighbors]
    total_w = sum(weights)
    avg_x = sum(n.x * w for n, w in zip(neighbors, weights, strict=True)) / total_w
    avg_y = sum(n.y * w for n, w in zip(neighbors, weights, strict=True)) / total_w

    cluster_votes: Counter[int] = Counter()
    for n, w in zip(neighbors, weights, strict=True):
        cluster_votes[int(n.cluster_id)] += w
    cluster_id, _ = cluster_votes.most_common(1)[0]

    state = get_state()
    cluster_sql = f"""
    SELECT dominant_archetype, archetype_purity, size, centroid_x, centroid_y
    FROM `{state.project}.{state.dataset}.clusters`
    WHERE cluster_id = @cid
    """
    cluster_rows = list(state.bq_client.query(
        cluster_sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("cid", "INT64", int(cluster_id))]
        ),
    ).result())
    cluster_meta = cluster_rows[0] if cluster_rows else None

    return {
        "cluster_id": int(cluster_id),
        "dominant_archetype": cluster_meta.dominant_archetype if cluster_meta else None,
        "archetype_purity": float(cluster_meta.archetype_purity) if cluster_meta else None,
        "cluster_size": int(cluster_meta.size) if cluster_meta else None,
        "user_x": float(avg_x),
        "user_y": float(avg_y),
        "cluster_centroid": {
            "x": float(cluster_meta.centroid_x) if cluster_meta else None,
            "y": float(cluster_meta.centroid_y) if cluster_meta else None,
        } if cluster_meta else None,
        "nearest_neighbors": [
            {
                "employee_id": n.employee_id,
                "archetype": n.archetype,
                "cluster_id": int(n.cluster_id),
                "distance": float(n.distance),
            }
            for n in neighbors[:5]
        ],
    }
