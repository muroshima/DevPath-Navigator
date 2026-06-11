"""Tool: skill_gap_analysis — what does the target cluster have that the user doesn't?"""

from __future__ import annotations

from collections import Counter

from google.cloud import bigquery

from agent.state import get_state


def skill_gap_analysis(
    user_tech_stack: list[list[str]],
    user_steps_roles: list[list[str]],
    target_cluster_id: int,
) -> dict:
    """Compare the user's profile to a target cluster and surface the gap.

    Call this after locate_user when the user expresses a goal (e.g. "I want
    to move to SRE", "I want to become a GenAI engineer"): map the goal to a
    target cluster (via nlq_over_corpus or explain_cluster) and call this
    tool with that cluster_id to see which tech tokens, roles, and seniority
    levels distinguish the target cohort.

    Args:
        user_tech_stack: list of tech-token lists, one per user step
            (use normalize_profile output, not raw strings).
        user_steps_roles: list of role-name lists, one per user step
            (use the same shape as locate_user's steps_roles input).
        target_cluster_id: cluster id the user wants to move toward.

    Returns:
        `missing_tech` (tokens common in the target cluster but absent from
        the user, sorted by target prevalence), `top_target_roles` (roles
        the target cluster occupies most frequently across all steps), and
        `seniority_distribution` of the target cohort.
    """
    state = get_state()
    target_cluster_id = int(target_cluster_id)

    user_tech_set: set[str] = set()
    for step in user_tech_stack:
        for t in step or []:
            user_tech_set.add(t)
    user_role_set: set[str] = set()
    for step_roles in user_steps_roles:
        for r in step_roles or []:
            user_role_set.add(r)

    sql = f"""
    SELECT t.roles, t.tech_stack, t.seniority
    FROM `{state.project}.{state.dataset}.trajectories` t
    JOIN `{state.project}.{state.dataset}.umap_coords` u
      USING (employee_id)
    WHERE u.cluster_id = @cid
    """
    rows = list(state.bq_client.query(
        sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("cid", "INT64", target_cluster_id)]
        ),
    ).result())
    if not rows:
        return {"error": f"cluster_id={target_cluster_id} not found or empty"}

    target_tech_counts: Counter[str] = Counter()
    target_role_counts: Counter[str] = Counter()
    target_seniority_counts: Counter[str] = Counter()
    total_steps = 0
    for r in rows:
        total_steps += 1
        for t in (r.tech_stack or []):
            target_tech_counts[t] += 1
        # Count *each* role in a multi-role step
        for entry in (r.roles or []):
            role_name = entry["role"] if isinstance(entry, dict) else getattr(entry, "role", None)
            if role_name:
                target_role_counts[role_name] += 1
        if r.seniority:
            target_seniority_counts[r.seniority] += 1

    missing_tech = [
        {"tech": t, "target_prevalence": c / total_steps, "target_count": c}
        for t, c in target_tech_counts.most_common()
        if t not in user_tech_set
    ][:15]

    missing_roles = [
        {"role": r, "target_count": c}
        for r, c in target_role_counts.most_common()
        if r not in user_role_set
    ]

    return {
        "target_cluster_id": target_cluster_id,
        "missing_tech": missing_tech,
        "missing_roles": missing_roles,
        "top_target_roles": [
            {"role": r, "count": c} for r, c in target_role_counts.most_common(5)
        ],
        "seniority_distribution": [
            {"level": s, "count": c} for s, c in target_seniority_counts.most_common()
        ],
    }
