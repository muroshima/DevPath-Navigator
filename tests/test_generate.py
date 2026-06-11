"""Tests for the synthetic data generator (schema v2)."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "datagen_generate", REPO_ROOT / "data-gen" / "generate.py"
)
generate = importlib.util.module_from_spec(_spec)
# Register in sys.modules so dataclasses can look the module up by name when
# resolving forward references in @dataclass-decorated classes.
sys.modules["datagen_generate"] = generate
_spec.loader.exec_module(generate)


def test_initial_batch_is_deterministic():
    a = generate.generate_batch("initial")
    b = generate.generate_batch("initial")
    assert a == b


def test_initial_batch_employee_count():
    rows = generate.generate_batch("initial")
    employees = {r["employee_id"] for r in rows}
    assert len(employees) == 1200


def test_drift_batch_is_all_ml_to_genai():
    rows = generate.generate_batch("drift")
    archetypes = {r["archetype"] for r in rows}
    assert archetypes == {"ml_to_genai"}
    employees = {r["employee_id"] for r in rows}
    assert len(employees) == 300


def test_initial_batch_has_no_genai_role():
    """The drift demo depends on genai_engineer being absent from initial."""
    rows = generate.generate_batch("initial")
    roles = {
        entry["role"]
        for r in rows
        for entry in r["roles"]
    }
    assert "genai_engineer" not in roles


def test_steps_have_at_least_one_role_with_positive_years():
    rows = generate.generate_batch("initial")
    for r in rows:
        assert len(r["roles"]) >= 1
        for entry in r["roles"]:
            assert entry["years"] > 0


def test_multi_role_steps_exist_but_are_minority():
    rows = generate.generate_batch("initial")
    multi = sum(1 for r in rows if len(r["roles"]) > 1)
    ratio = multi / len(rows)
    assert 0.02 < ratio < 0.30, f"multi-role ratio {ratio:.3f} out of expected band"


def test_all_tokens_within_taxonomy():
    taxonomy = generate.load_taxonomy()
    valid_roles = set(taxonomy["roles"])
    valid_sen = set(taxonomy["seniority"])
    valid_tech = set(generate.all_tech_tokens(taxonomy))
    for batch in ("initial", "drift"):
        for r in generate.generate_batch(batch):
            for entry in r["roles"]:
                assert entry["role"] in valid_roles
            assert r["seniority"] in valid_sen
            for t in r["tech_stack"]:
                assert t in valid_tech


def test_archetype_distribution_roughly_matches_weights():
    rows = generate.generate_batch("initial")
    arch_per_emp = {r["employee_id"]: r["archetype"] for r in rows}
    counts = Counter(arch_per_emp.values())
    assert counts["backend_to_sre"] == 300
    assert counts["jobhopper"] == 216
