"""Shared helpers for tool implementations."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np
from google.cloud import bigquery

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.state import get_state
from embedding.trajectory import embed_trajectory


def build_steps(
    steps_roles: list[list[str]],
    steps_role_years: list[list[float]],
    steps_tech: list[list[str]],
    steps_seniority: list[str],
) -> list[dict[str, Any]] | None:
    """Build step dicts from the 4 parallel arrays the tools expose to the LLM.

    Returns None if the arrays have inconsistent lengths or any step's
    roles/years sub-lists are mismatched. Callers convert that into a
    user-visible error in their own response shape.
    """
    if not (len(steps_roles) == len(steps_role_years) == len(steps_tech) == len(steps_seniority)):
        return None

    out: list[dict[str, Any]] = []
    for roles, years, tech, sen in zip(
        steps_roles, steps_role_years, steps_tech, steps_seniority, strict=True
    ):
        if len(roles) != len(years):
            return None
        out.append({
            "roles": [{"role": r, "years": float(y)} for r, y in zip(roles, years, strict=True)],
            "tech_stack": list(tech),
            "seniority": sen,
        })
    return out


def embed_user(steps: list[dict[str, Any]]) -> np.ndarray | None:
    """Embed a user trajectory using the running app's Word2Vec model."""
    state = get_state()
    return embed_trajectory(steps, state.vectors)


def vector_search(
    query_vector: np.ndarray,
    top_k: int,
) -> list[bigquery.Row]:
    state = get_state()
    sql = f"""
    SELECT
      base.employee_id      AS employee_id,
      base.batch_id         AS batch_id,
      coords.x              AS x,
      coords.y              AS y,
      coords.cluster_id     AS cluster_id,
      coords.archetype      AS archetype,
      distance
    FROM VECTOR_SEARCH(
      TABLE `{state.project}.{state.dataset}.embeddings`,
      'vector',
      (SELECT @query_vec AS vector),
      top_k => @k,
      distance_type => 'COSINE'
    )
    JOIN `{state.project}.{state.dataset}.umap_coords` AS coords
      ON base.employee_id = coords.employee_id
    ORDER BY distance
    """
    job = state.bq_client.query(
        sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("query_vec", "FLOAT64", query_vector.tolist()),
                bigquery.ScalarQueryParameter("k", "INT64", int(top_k)),
            ]
        ),
    )
    return list(job.result())


def primary_role(roles_field: Any) -> str | None:
    """Pull the primary (longest-years) role from a schema-v2 roles array.

    Returns None for malformed input. Tolerates tuples / BigQuery Row objects.
    """
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
            best_role = r
            best_years = y
    return best_role
