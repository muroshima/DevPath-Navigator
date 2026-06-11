"""Tests for token expansion (year weighting) in embedding/tokens.py."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from embedding.tokens import step_tokens, trajectory_tokens


def test_role_repeated_per_year():
    step = {
        "roles": [{"role": "backend", "years": 3.0}],
        "tech_stack": ["lang.go"],
        "seniority": "mid",
    }
    tokens = step_tokens(step)
    assert tokens.count("backend") == 3
    assert tokens.count("lang.go") == 1
    assert tokens.count("mid") == 1


def test_years_rounding_and_clamping():
    # 0.4 years rounds to 0 → clamped to 1
    low = step_tokens({"roles": [{"role": "sre", "years": 0.4}], "tech_stack": [], "seniority": "junior"})
    assert low.count("sre") == 1
    # 25 years clamps to 10
    high = step_tokens({"roles": [{"role": "sre", "years": 25}], "tech_stack": [], "seniority": "staff"})
    assert high.count("sre") == 10


def test_multi_role_step_emits_both_roles():
    step = {
        "roles": [
            {"role": "backend", "years": 4.0},
            {"role": "platform", "years": 2.0},
        ],
        "tech_stack": ["infra.kubernetes"],
        "seniority": "senior",
    }
    tokens = step_tokens(step)
    assert tokens.count("backend") == 4
    assert tokens.count("platform") == 2


def test_v1_single_role_fallback():
    """Old-shape steps with a bare `role` key still tokenize (1 occurrence)."""
    tokens = step_tokens({"role": "frontend", "tech_stack": ["web.react"], "seniority": "mid"})
    assert tokens.count("frontend") == 1


def test_trajectory_tokens_preserves_step_order():
    steps = [
        {"roles": [{"role": "backend", "years": 1}], "tech_stack": [], "seniority": "junior"},
        {"roles": [{"role": "sre", "years": 1}], "tech_stack": [], "seniority": "mid"},
    ]
    tokens = trajectory_tokens(steps)
    assert tokens.index("backend") < tokens.index("sre")
