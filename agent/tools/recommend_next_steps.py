"""Tool: recommend_next_steps — propose 2-3 plausible next moves with grounding examples."""

from __future__ import annotations

from collections import Counter

from google.cloud import bigquery

from agent.state import get_state
from agent.tools._common import build_steps, embed_user, primary_role


def _summarize_trajectory(traj: list[dict]) -> str:
    """Render a trajectory as 'backend(4y) → ml_engineer(2y) → platform'.

    Picks the primary (longest-years) role per step. Years are rounded to
    one decimal but trailing '.0' is stripped so '4y' looks cleaner than
    '4.0y'. The final step's years are omitted since it represents the
    move the user is being recommended to make — its tenure isn't known.
    """
    parts: list[str] = []
    for i, step in enumerate(traj):
        roles = step.get("roles") or []
        if not roles:
            continue
        # roles here is a list of {role, years} dicts (mirrored from BQ struct)
        best: dict | None = None
        best_years = -1.0
        for entry in roles:
            r = entry.get("role") if isinstance(entry, dict) else getattr(entry, "role", None)
            y = float(entry.get("years") or 0) if isinstance(entry, dict) else float(getattr(entry, "years", 0) or 0)
            if r and y > best_years:
                best = {"role": r, "years": y}
                best_years = y
        if best is None:
            continue
        role = best["role"]
        # Last step is the recommended move — its years are post-hoc and
        # carry no meaning for the recommendation, so just show the role.
        if i == len(traj) - 1:
            parts.append(role)
        else:
            years = round(best["years"], 1)
            parts.append(f"{role}({years:g}y)")
    return " → ".join(parts) if parts else ""


def recommend_next_steps(
    steps_roles: list[list[str]],
    steps_role_years: list[list[float]],
    steps_tech: list[list[str]],
    steps_seniority: list[str],
    k_neighbors: int = 20,
) -> dict:
    """Suggest 2-3 candidate next career steps grounded in similar engineers' actual moves.

    Logic: find the k nearest engineers in embedding space, look at the step
    immediately AFTER the user's last step (or the neighbor's final step if
    they didn't go further), then group those next-step primary roles + new
    tech tokens and return the most common patterns. Each recommendation
    surfaces 2-3 representative trajectories so the agent can describe the
    cohort by what they actually did, not by opaque employee_ids.

    Input shape: same FOUR parallel lists as locate_user / find_similar_trajectories.

    Returns:
        `recommendations` — list of {next_role, support_count, common_new_tech,
        representative_trajectories} entries, sorted by support count, top 3.
        Each entry in `representative_trajectories` is
        {employee_id, trajectory: "backend(4y) → ml(2y) → platform"}.
    """
    state = get_state()
    steps = build_steps(steps_roles, steps_role_years, steps_tech, steps_seniority)
    if steps is None:
        return {"error": "Parallel arrays must align (length + per-step roles/years)."}

    vec = embed_user(steps)
    if vec is None:
        return {"error": "Could not embed trajectory."}

    sql = f"""
    WITH neighbors AS (
      SELECT base.employee_id, distance
      FROM VECTOR_SEARCH(
        TABLE `{state.project}.{state.dataset}.embeddings`,
        'vector',
        (SELECT @qv AS vector),
        top_k => @k,
        distance_type => 'COSINE'
      )
    )
    SELECT n.employee_id, n.distance, t.step, t.roles, t.tech_stack
    FROM neighbors n
    JOIN `{state.project}.{state.dataset}.trajectories` t
      USING (employee_id)
    ORDER BY n.distance, t.step
    """
    rows = list(state.bq_client.query(
        sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("qv", "FLOAT64", vec.tolist()),
                bigquery.ScalarQueryParameter("k", "INT64", int(k_neighbors)),
            ]
        ),
    ).result())

    by_emp: dict[str, list[dict]] = {}
    for r in rows:
        # Convert roles to plain dicts so _summarize_trajectory can read them
        # uniformly later (BQ Row members are not dicts by default).
        roles = [
            {"role": rr["role"], "years": float(rr["years"])}
            for rr in (r.roles or [])
        ]
        by_emp.setdefault(r.employee_id, []).append({
            "step": int(r.step),
            "roles": roles,
            "tech_stack": list(r.tech_stack or []),
        })

    user_n_steps = len(steps)
    user_tech_set: set[str] = set()
    for st in steps_tech:
        for t in st or []:
            user_tech_set.add(t)

    rec_role_counts: Counter[str] = Counter()
    rec_reps_by_role: dict[str, list[dict]] = {}
    rec_new_tech_by_role: dict[str, Counter[str]] = {}

    for emp, traj in by_emp.items():
        traj.sort(key=lambda s: s["step"])
        if not traj:
            continue
        # Build the trajectory the recommendation cites: the user's already-
        # walked path PLUS the neighbor's next step. We slice the neighbor's
        # trajectory to (user_n_steps + 1) so the summary ends at the move
        # being recommended, rather than continuing into the neighbor's
        # further career.
        next_step_idx = user_n_steps if user_n_steps < len(traj) else len(traj) - 1
        next_step = traj[next_step_idx]
        next_role = primary_role(next_step["roles"])
        if not next_role:
            continue
        rec_role_counts[next_role] += 1
        cohort_traj = traj[: next_step_idx + 1]
        rec_reps_by_role.setdefault(next_role, []).append({
            "employee_id": emp,
            "trajectory": _summarize_trajectory(cohort_traj),
        })
        rec_new_tech_by_role.setdefault(next_role, Counter())
        for t in next_step["tech_stack"]:
            if t not in user_tech_set:
                rec_new_tech_by_role[next_role][t] += 1

    recommendations = []
    for role, count in rec_role_counts.most_common(5):
        recommendations.append({
            "next_role": role,
            "support_count": count,
            "common_new_tech": [
                {"tech": t, "count": c}
                for t, c in rec_new_tech_by_role.get(role, Counter()).most_common(5)
            ],
            "representative_trajectories": rec_reps_by_role.get(role, [])[:3],
        })

    return {"recommendations": recommendations[:3]}
