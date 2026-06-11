"""Decide whether a retrained model is allowed to ship.

The gate compares the current run against the latest *previously-passing*
record. The first ever run has no prior to compare against and is marked as
the baseline (decision = "baseline"); from then on every run is judged
against the most recent pass/baseline.

Pass criteria (all must hold):
- recall_at_10 >= prev.recall_at_10 - RECALL_EPS
- vocab_size  >= prev.vocab_size           (no token loss)
- All archetypes_covered from prev are still covered by current
- n_clusters >= prev.n_clusters - 1        (allow one fewer cluster — UMAP
                                            stochasticity is real even with
                                            a fixed seed across different
                                            corpus sizes)

RECALL_EPS is 0.10. It is intentionally wider than the textbook 0.05
because the held-out set is rebuilt every run from the *current* set of
archetypes (stratified). When a new archetype joins the corpus (e.g. the
drift batch adds ml_to_genai), the new held-outs are by construction the
ones with the shallowest trajectories and therefore the hardest to predict
from a truncated view, which pulls global recall down even when nothing has
actually regressed for the existing archetypes. Past 0.10 is where we want
the gate to actually fire.

When the current run introduces a new archetype (e.g. drift batch adds
ml_to_genai), that's surfaced in the reasons as a positive signal but is
NOT a pass requirement on its own — the design's "まわす" story is that the
gate accepts genuine improvement and rejects degradation, both regardless
of the source.
"""

from __future__ import annotations

from dataclasses import dataclass

from eval.metrics import EvalMetrics
from eval.store import EvalRecord

RECALL_EPS = 0.10


@dataclass
class Decision:
    decision: str          # "baseline" | "pass" | "fail"
    reasons: list[str]


def decide(current: EvalMetrics, previous: EvalRecord | None) -> Decision:
    if previous is None:
        return Decision(
            decision="baseline",
            reasons=[
                f"baseline run (no prior); recall@10 = {current.recall_at_10:.3f}",
                f"clusters: {current.n_clusters}, vocab: {current.vocab_size}",
                f"archetypes covered: {', '.join(current.archetypes_covered)}",
            ],
        )

    reasons: list[str] = []
    failed = False

    # Recall floor
    if current.recall_at_10 + 1e-9 < previous.recall_at_10 - RECALL_EPS:
        failed = True
        reasons.append(
            f"recall@10 dropped: {current.recall_at_10:.3f} < "
            f"{previous.recall_at_10:.3f} - {RECALL_EPS}"
        )
    else:
        reasons.append(
            f"recall@10 ok: {current.recall_at_10:.3f} vs prev {previous.recall_at_10:.3f}"
        )

    # No vocab loss
    if current.vocab_size < previous.vocab_size:
        failed = True
        reasons.append(
            f"vocab shrank: {current.vocab_size} < {previous.vocab_size}"
        )
    else:
        reasons.append(
            f"vocab ok: {current.vocab_size} >= prev {previous.vocab_size}"
        )

    # No archetype loss
    prev_arch = set(previous.archetypes_covered)
    cur_arch = set(current.archetypes_covered)
    lost = sorted(prev_arch - cur_arch)
    if lost:
        failed = True
        reasons.append(f"archetypes lost from clusters: {lost}")
    new_arch = sorted(cur_arch - prev_arch)
    if new_arch:
        reasons.append(f"new archetypes appeared: {new_arch}")

    # Cluster count tolerance
    if current.n_clusters < previous.n_clusters - 1:
        failed = True
        reasons.append(
            f"cluster count dropped >1: {current.n_clusters} < {previous.n_clusters}"
        )
    else:
        reasons.append(
            f"cluster count ok: {current.n_clusters} (prev {previous.n_clusters})"
        )

    return Decision(decision="fail" if failed else "pass", reasons=reasons)
