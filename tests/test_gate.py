"""Tests for the retraining evaluation gate."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval.gate import MIN_RECALL_EPS, RECALL_EPS, decide
from eval.metrics import EvalMetrics
from eval.store import EvalRecord


def _metrics(**overrides) -> EvalMetrics:
    base = dict(
        recall_at_10=0.80,
        n_clusters=12,
        n_noise=5,
        mean_archetype_purity=0.99,
        archetypes_covered=["a", "b", "c"],
        vocab_size=71,
        held_out_n=125,
        recall_per_archetype={"a": 0.80, "b": 0.80, "c": 0.80},
        min_recall_per_archetype=0.80,
    )
    base.update(overrides)
    return EvalMetrics(**base)


def _record(**overrides) -> EvalRecord:
    base = dict(
        run_id="prev123",
        run_at=datetime.now(UTC),
        batches=["initial"],
        recall_at_10=0.80,
        n_clusters=12,
        n_noise=5,
        mean_archetype_purity=0.99,
        archetypes_covered=["a", "b", "c"],
        vocab_size=71,
        held_out_n=125,
        decision="baseline",
        decision_reasons=[],
        min_recall_per_archetype=0.80,
    )
    base.update(overrides)
    return EvalRecord(**base)


def test_first_run_is_baseline():
    d = decide(_metrics(), None)
    assert d.decision == "baseline"


def test_equal_metrics_pass():
    d = decide(_metrics(), _record())
    assert d.decision == "pass"


def test_recall_drop_within_eps_passes():
    d = decide(_metrics(recall_at_10=0.80 - RECALL_EPS + 0.01), _record())
    assert d.decision == "pass"


def test_recall_drop_beyond_eps_fails():
    d = decide(_metrics(recall_at_10=0.80 - RECALL_EPS - 0.02), _record())
    assert d.decision == "fail"
    assert any("recall@10 dropped" in r for r in d.reasons)


def test_vocab_shrink_fails():
    d = decide(_metrics(vocab_size=70), _record())
    assert d.decision == "fail"


def test_lost_archetype_fails():
    d = decide(_metrics(archetypes_covered=["a", "b"]), _record())
    assert d.decision == "fail"
    assert any("archetypes lost" in r for r in d.reasons)


def test_new_archetype_noted_and_passes():
    d = decide(_metrics(archetypes_covered=["a", "b", "c", "d"]), _record())
    assert d.decision == "pass"
    assert any("new archetypes" in r for r in d.reasons)


def test_cluster_count_one_fewer_passes():
    d = decide(_metrics(n_clusters=11), _record())
    assert d.decision == "pass"


def test_cluster_count_two_fewer_fails():
    d = decide(_metrics(n_clusters=10), _record())
    assert d.decision == "fail"


# === per-archetype recall floor ===


def test_min_recall_per_archetype_within_eps_passes():
    """One cohort regressing slightly is within the per-archetype epsilon
    — the gate should not block this. (Per-archetype recall has only ~25
    held-out users per slice, so a single misprediction shifts the metric
    by 4 points; MIN_RECALL_EPS is intentionally wider than RECALL_EPS.)"""
    d = decide(
        _metrics(
            recall_per_archetype={"a": 0.80 - MIN_RECALL_EPS + 0.01, "b": 0.80, "c": 0.80},
            min_recall_per_archetype=0.80 - MIN_RECALL_EPS + 0.01,
        ),
        _record(),
    )
    assert d.decision == "pass"


def test_min_recall_per_archetype_beyond_eps_fails():
    """A 20-point drop on one cohort while the others stay put would slide
    aggregate recall by only ~7 points (still within RECALL_EPS=0.10) —
    aggregate-only gating would let this through. The per-archetype gate
    catches it. The reason text should also name the offending archetype."""
    d = decide(
        _metrics(
            # 'b' has tanked; 'a' and 'c' still healthy
            recall_at_10=0.80 - 0.07,
            recall_per_archetype={"a": 0.80, "b": 0.80 - MIN_RECALL_EPS - 0.05, "c": 0.80},
            min_recall_per_archetype=0.80 - MIN_RECALL_EPS - 0.05,
        ),
        _record(),
    )
    assert d.decision == "fail"
    assert any("min recall per archetype dropped" in r for r in d.reasons)
    assert any("worst: b" in r for r in d.reasons)


def test_legacy_prior_without_min_recall_skips_check():
    """A previous record from before this metric existed has
    `min_recall_per_archetype=None`. The gate must not synthesise a
    comparison from missing data — it skips the check and surfaces the
    "no prior baseline" status in the reasons."""
    legacy_prev = _record(min_recall_per_archetype=None)
    # Current run has a min that would have failed against any non-None
    # previous — but with previous=None, the gate must let it through on
    # this dimension.
    d = decide(
        _metrics(
            recall_per_archetype={"a": 0.40, "b": 0.80, "c": 0.80},
            min_recall_per_archetype=0.40,
        ),
        legacy_prev,
    )
    assert d.decision == "pass"
    assert any("no prior baseline" in r for r in d.reasons)
