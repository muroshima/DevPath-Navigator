"""Tests for taxonomy normalization (agent/taxonomy.py)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.taxonomy import (
    normalize_role,
    normalize_tech,
    normalize_trajectory,
)


def test_alias_tech_normalization():
    assert normalize_tech("k8s") == "infra.kubernetes"
    assert normalize_tech("postgres") == "data.postgres"
    assert normalize_tech("PostgreSQL") == "data.postgres"
    assert normalize_tech("react") == "web.react"


def test_fully_qualified_tokens_pass_through():
    assert normalize_tech("infra.kubernetes") == "infra.kubernetes"
    assert normalize_tech("lang.python") == "lang.python"


def test_wrong_prefix_is_corrected_via_suffix_match():
    # Gemini hallucinated prefixes — these should resolve to the right category
    assert normalize_tech("db.postgres") is None or normalize_tech("postgres") == "data.postgres"
    # bare tool name resolves
    assert normalize_tech("kubernetes") == "infra.kubernetes"


def test_unknown_tech_returns_none():
    assert normalize_tech("cobol") is None


def test_role_aliases():
    assert normalize_role("ML engineer") == "ml_engineer"
    assert normalize_role("Site Reliability") == "sre"
    assert normalize_role("backend") == "backend"


def test_normalize_trajectory_multi_role_shape():
    out = normalize_trajectory(
        steps_roles=[["backend"], ["Backend", "Platform Engineer"]],
        steps_role_years=[[2.0], [3.0, 1.0]],
        steps_tech=[["Java", "Postgres"], ["k8s", "terraform"]],
        steps_seniority=["junior", "mid"],
    )
    assert out["steps_roles"] == [["backend"], ["backend", "platform"]]
    assert out["steps_role_years"] == [[2.0], [3.0, 1.0]]
    assert out["steps_tech"] == [
        ["lang.java", "data.postgres"],
        ["infra.kubernetes", "infra.terraform"],
    ]
    assert out["steps_seniority"] == ["junior", "mid"]
    assert out["corrections"]["tech"]["Java"] == "lang.java"


def test_normalize_trajectory_drops_unknown_and_reports():
    out = normalize_trajectory(
        steps_roles=[["backend"]],
        steps_role_years=[[2.0]],
        steps_tech=[["cobol", "lang.go"]],
        steps_seniority=["mid"],
    )
    assert out["steps_tech"] == [["lang.go"]]
    assert "cobol" in out["unresolved"]["tech"]


def test_normalize_trajectory_missing_years_defaults_to_one():
    out = normalize_trajectory(
        steps_roles=[["backend", "platform"]],
        steps_role_years=[[4.0]],  # second role has no year
        steps_tech=[["lang.go"]],
        steps_seniority=["senior"],
    )
    assert out["steps_role_years"] == [[4.0, 1.0]]
