"""Tool: explain_cluster — describe a cluster's archetype, members, and common patterns."""

from __future__ import annotations

from collections import Counter

from google.cloud import bigquery

from agent.state import get_state


def explain_cluster(cluster_id: int) -> dict:
    """Describe a single cluster on the career map.

    Use this tool when the user asks "what is cluster #N about?" or when
    you want to give the user context for the cluster they were placed in
    by locate_user.

    Args:
        cluster_id: integer cluster id (or -1 for the noise cluster).

    Returns:
        A dict with dominant archetype, archetype purity, cluster size,
        centroid, common roles per step index (counting each role in
        multi-role steps), and most-common tech tokens across all members.
    """
    state = get_state()
    cluster_id = int(cluster_id)

    meta_sql = f"""
    SELECT cluster_id, size, dominant_archetype, archetype_purity, centroid_x, centroid_y
    FROM `{state.project}.{state.dataset}.clusters`
    WHERE cluster_id = @cid
    """
    meta_rows = list(state.bq_client.query(
        meta_sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("cid", "INT64", cluster_id)]
        ),
    ).result())
    if not meta_rows:
        return {"error": f"cluster_id={cluster_id} not found"}
    meta = meta_rows[0]

    members_sql = f"""
    SELECT t.employee_id, t.step, t.roles, t.tech_stack, t.seniority
    FROM `{state.project}.{state.dataset}.trajectories` t
    JOIN `{state.project}.{state.dataset}.umap_coords` u
      USING (employee_id)
    WHERE u.cluster_id = @cid
    ORDER BY t.employee_id, t.step
    """
    rows = list(state.bq_client.query(
        members_sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("cid", "INT64", cluster_id)]
        ),
    ).result())

    role_by_step: dict[int, Counter[str]] = {}
    tech_counts: Counter[str] = Counter()
    seniority_counts: Counter[str] = Counter()
    for r in rows:
        step_idx = int(r.step)
        role_by_step.setdefault(step_idx, Counter())
        for entry in (r.roles or []):
            role_name = entry["role"] if isinstance(entry, dict) else getattr(entry, "role", None)
            if role_name:
                role_by_step[step_idx][role_name] += 1
        for t in (r.tech_stack or []):
            tech_counts[t] += 1
        if r.seniority:
            seniority_counts[r.seniority] += 1

    common_roles_per_step = {
        step: counter.most_common(3) for step, counter in sorted(role_by_step.items())
    }

    return {
        "cluster_id": cluster_id,
        "size": int(meta.size),
        "dominant_archetype": meta.dominant_archetype,
        "archetype_purity": float(meta.archetype_purity) if meta.archetype_purity is not None else None,
        "centroid": {"x": float(meta.centroid_x), "y": float(meta.centroid_y)},
        "common_roles_per_step": {
            str(step): [{"role": r, "count": c} for r, c in items]
            for step, items in common_roles_per_step.items()
        },
        "top_tech": [{"tech": t, "count": c} for t, c in tech_counts.most_common(10)],
        "seniority_distribution": [
            {"level": s, "count": c} for s, c in seniority_counts.most_common()
        ],
    }
