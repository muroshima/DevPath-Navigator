"""Tests for the in-memory token-bucket limiter."""

from __future__ import annotations

import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest

from agent.rate_limit import TokenBucketLimiter


def test_burst_then_refill():
    lim = TokenBucketLimiter(capacity=3, refill_per_second=1.0)
    # Three immediate calls all pass (burst)
    for _ in range(3):
        assert lim.allow("ip1")[0] is True
    # Fourth is denied
    allowed, retry_after = lim.allow("ip1")
    assert allowed is False
    assert retry_after > 0
    # After enough wall time, the bucket refills
    time.sleep(1.1)
    assert lim.allow("ip1")[0] is True


def test_buckets_are_per_key():
    lim = TokenBucketLimiter(capacity=1, refill_per_second=0.5)
    assert lim.allow("ip1")[0] is True
    # Same key — should now be empty
    assert lim.allow("ip1")[0] is False
    # Different key — independent bucket
    assert lim.allow("ip2")[0] is True


def test_invalid_construction():
    with pytest.raises(ValueError):
        TokenBucketLimiter(capacity=0, refill_per_second=1.0)
    with pytest.raises(ValueError):
        TokenBucketLimiter(capacity=1, refill_per_second=-1.0)
