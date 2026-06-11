"""Tests for the retraining evaluation gate."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval.gate import RECALL_EPS, decide
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
