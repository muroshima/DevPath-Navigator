"""Trajectory → vector embedding.

Public interface used by both training (per-employee corpus vectors) and
inference (the agent's locate_user / find_similar_trajectories tools), so
they stay in the same vector space.

The new step shape carries multiple `{role, years}` entries. Token
repetition based on years is handled inside `step_tokens`, so both training
and inference receive role tokens proportionally to tenure without any
explicit per-token weighting code here.

When RQ-VAE replaces Word2Vec, only the body of this function changes; the
callers don't need to know.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from gensim.models import KeyedVectors

from embedding.tokens import step_tokens

DEFAULT_DECAY = 0.3


def embed_trajectory(
    steps: list[dict[str, Any]],
    vectors: KeyedVectors,
    decay: float = DEFAULT_DECAY,
) -> np.ndarray | None:
    """Embed a trajectory as the time-decayed mean of step vectors.

    Per-step:
      vec(step) = mean(vectors[t] for t in step_tokens(step) if t in vocab)

    Across steps:
      most recent step weight 1.0; step k from the end weighted exp(-decay·k).

    Returns None if no tokens in the trajectory match the vocabulary —
    callers should treat that as "could not embed this user".
    """
    if not steps:
        return None

    n = len(steps)
    step_vecs: list[np.ndarray] = []
    step_weights: list[float] = []
    for k, step in enumerate(steps):
        tokens = [t for t in step_tokens(step) if t in vectors]
        if not tokens:
            continue
        step_vec = np.mean([vectors[t] for t in tokens], axis=0)
        weight = float(np.exp(-decay * (n - 1 - k)))
        step_vecs.append(step_vec)
        step_weights.append(weight)

    if not step_vecs:
        return None

    weights = np.asarray(step_weights, dtype=np.float64)
    matrix = np.stack(step_vecs).astype(np.float64)
    vec = (matrix * weights[:, None]).sum(axis=0) / weights.sum()
    return vec.astype(np.float32)
