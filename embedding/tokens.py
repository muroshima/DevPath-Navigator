"""Convert trajectory rows into ordered token sequences for Word2Vec training.

Schema v2: each step contains a list of `{role, years}` dicts instead of a
single role string. Role tokens are emitted once per integer year of
experience (clamped to [1, 10]) so engineers who spent longer in a role push
the embedding harder toward that role's vector — both at training time
(skip-gram sees the token in more contexts) and at inference time (the same
expansion is reused by `embed_trajectory`).

Token layout per step:
  [role_a × years_a, role_b × years_b, ...,
   tech_a, tech_b, ...,
   seniority]
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

MIN_YEAR_WEIGHT = 1
MAX_YEAR_WEIGHT = 10


def _year_weight(years: float | None) -> int:
    if years is None:
        return MIN_YEAR_WEIGHT
    return max(MIN_YEAR_WEIGHT, min(MAX_YEAR_WEIGHT, int(round(float(years)))))


def step_tokens(step: dict[str, Any]) -> list[str]:
    """All tokens belonging to a single step, with year-weighted role repetition."""
    tokens: list[str] = []
    roles = step.get("roles")
    if roles:
        for entry in roles:
            role = entry["role"]
            weight = _year_weight(entry.get("years"))
            tokens.extend([role] * weight)
    elif "role" in step:
        # Tolerate v1 data so callers can transition incrementally.
        tokens.append(step["role"])
    tokens.extend(step.get("tech_stack", []) or [])
    sen = step.get("seniority")
    if sen:
        tokens.append(sen)
    return tokens


def trajectory_tokens(steps: Iterable[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for step in steps:
        out.extend(step_tokens(step))
    return out


def group_trajectory_by_employee(
    rows: Iterable[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group raw trajectory rows by employee_id and sort by step index.

    For schema-v2 rows arriving from BigQuery as `Row` objects, the `roles`
    field comes back as a list of `Row`-like records; we normalize each step
    into a plain dict here so downstream code never has to deal with the BQ
    row type.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        step = dict(row)
        roles = step.get("roles")
        if roles:
            step["roles"] = [dict(r) if not isinstance(r, dict) else r for r in roles]
        grouped.setdefault(step["employee_id"], []).append(step)
    for steps in grouped.values():
        steps.sort(key=lambda r: r["step"])
    return grouped
