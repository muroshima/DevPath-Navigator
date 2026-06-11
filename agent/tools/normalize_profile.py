"""Tool: normalize_profile — coerce free-form trajectory tokens into the taxonomy."""

from __future__ import annotations

from agent.taxonomy import normalize_trajectory


def normalize_profile(
    steps_roles: list[list[str]],
    steps_role_years: list[list[float]],
    steps_tech: list[list[str]],
    steps_seniority: list[str],
) -> dict:
    """Validate and normalize a trajectory against the taxonomy.

    Call this BEFORE locate_user / find_similar_trajectories /
    skill_gap_analysis / recommend_next_steps whenever the user's input uses
    free-form tech names (e.g. "Postgres", "K8s", "Vertex") or you are
    unsure if a token exists in the taxonomy.

    The tool maps common aliases ("postgres" → "data.postgres", "k8s" →
    "infra.kubernetes") and drops tokens that cannot be resolved. Pass the
    returned arrays straight to the next tool — never the user's raw strings.

    Trajectory input shape (FOUR parallel lists, one entry per step):
      steps_roles[i]       — role names for step i (free-form OK)
      steps_role_years[i]  — years parallel to steps_roles[i]
      steps_tech[i]        — tech tokens for step i (free-form OK)
      steps_seniority[i]   — seniority for step i (free-form OK)

    Returns:
        Normalized `steps_roles` / `steps_role_years` / `steps_tech` /
        `steps_seniority` plus `corrections` (per-category map
        original→normalized) and `unresolved` (tokens that could not be
        placed). Always pass the normalized arrays to the next tool.
    """
    return normalize_trajectory(steps_roles, steps_role_years, steps_tech, steps_seniority)
