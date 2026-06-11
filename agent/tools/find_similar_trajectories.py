"""Tool: find_similar_trajectories — return k engineers with similar career paths."""

from __future__ import annotations

from google.cloud import bigquery

from agent.state import get_state
from agent.tools._common import build_steps, embed_user

DEFAULT_K = 5
MAX_K = 20


def find_similar_trajectories(
    steps_roles: list[list[str]],
    steps_role_years: list[list[float]],
    steps_tech: list[list[str]],
    steps_seniority: list[str],
    k: int = DEFAULT_K,
) -> dict:
    """Return the k engineers in the corpus whose trajectories are most similar to the user.

    Use this tool when the user asks "who has done this before me?",
    "what did engineers similar to me do next?", or to gather grounding
    examples for a recommendation.

    Trajectory shape: same FOUR parallel lists used by locate_user.
      steps_roles[i]      — list of role names in step i
      steps_role_years[i] — list of years parallel to steps_roles[i]
      steps_tech[i]       — list of tech tokens in step i
      steps_seniority[i]  — seniority level in step i

    Args:
        k: number of neighbors to return (default 5, max 20).

    Returns:
        A list of similar engineers, each with their full trajectory (each
        step's roles + years + tech_stack + seniority) and the cosine
        distance from the user. The archetype label is included to help
        explain *why* the trajectory is similar.
    """
    steps = build_steps(steps_roles, steps_role_years, steps_tech, steps_seniority)
    if steps is None:
        return {"error": "Parallel arrays must align (length + per-step roles/years)."}

    k = max(1, min(int(k), MAX_K))
    vec = embed_user(steps)
    if vec is None:
        return {"error": "Could not embed trajectory."}

    state = get_state()
    sql = f"""
    WITH neighbors AS (
      SELECT base.employee_id, distance
      FROM VECTOR_SEARCH(
        TABLE `{state.project}.{state.dataset}.embeddings`,
        'vector',
        (SELECT @query_vec AS vector),
        top_k => @k,
        distance_type => 'COSINE'
      )
    )
    SELECT
      n.employee_id, n.distance, t.step, t.roles, t.tech_stack, t.seniority, t.archetype
    FROM neighbors n
    JOIN `{state.project}.{state.dataset}.trajectories` t
      USING (employee_id)
    ORDER BY n.distance, t.step
    """
    rows = list(state.bq_client.query(
        sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("query_vec", "FLOAT64", vec.tolist()),
                bigquery.ScalarQueryParameter("k", "INT64", k),
            ]
        ),
    ).result())

    grouped: dict[str, dict] = {}
    for r in rows:
        emp = r.employee_id
        if emp not in grouped:
            grouped[emp] = {
                "employee_id": emp,
                "distance": float(r.distance),
                "archetype": r.archetype,
                "trajectory": [],
            }
        grouped[emp]["trajectory"].append({
            "step": int(r.step),
            "roles": [{"role": rr["role"], "years": float(rr["years"])} for rr in (r.roles or [])],
            "tech_stack": list(r.tech_stack or []),
            "seniority": r.seniority,
        })

    return {"similar_trajectories": sorted(grouped.values(), key=lambda d: d["distance"])}
