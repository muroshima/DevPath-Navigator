"""In-memory per-IP token-bucket rate limiter.

This is a deliberately simple last-line-of-defense against bursts of
unauthenticated traffic against the public Cloud Run endpoint. The agent
service is `--allow-unauthenticated` for the demo, which means a stranger
could otherwise spend an arbitrary amount of Gemini quota and Cloud Run CPU
hours without any cap. The limiter caps per-IP traffic at a configurable
rate; Cloud Run can still scale out, but each instance enforces its own
ceiling, so the per-IP traffic seen by Gemini is bounded by
`rate × max_instances`.

Limitations (deliberate, documented):
- Per-instance memory, so the practical limit is rate × concurrent
  instances. With max-instances=3 that's 3× the configured rate. Good
  enough for the demo; switch to a centralized limiter (e.g. Memorystore
  for Redis) before any non-demo use.
- Identifies clients by X-Forwarded-For first hop (Cloud Run injects it),
  falling back to the socket address. A spoofed X-Forwarded-For could
  rotate identities, but Cloud Run's frontend overwrites that header on
  the inbound side, so spoofing only works from inside the VPC, which
  doesn't exist here.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import HTTPException, Request


@dataclass
class _Bucket:
    tokens: float
    last_refill: float


class TokenBucketLimiter:
    """Token bucket per identifier (typically remote IP)."""

    def __init__(self, capacity: float, refill_per_second: float) -> None:
        if capacity <= 0 or refill_per_second <= 0:
            raise ValueError("capacity and refill_per_second must be positive")
        self.capacity = float(capacity)
        self.refill_per_second = float(refill_per_second)
        self._buckets: dict[str, _Bucket] = defaultdict(
            lambda: _Bucket(tokens=self.capacity, last_refill=time.monotonic())
        )
        self._lock = threading.Lock()

    def allow(self, key: str) -> tuple[bool, float]:
        """Return (allowed, seconds_to_next_token)."""
        with self._lock:
            # Read `now` AFTER touching the bucket. The defaultdict factory
            # calls time.monotonic() when the bucket is first created; if
            # `now` were sampled before that call, `elapsed` could come out
            # slightly negative and the first request would be denied.
            b = self._buckets[key]
            now = time.monotonic()
            elapsed = max(0.0, now - b.last_refill)
            b.tokens = min(self.capacity, b.tokens + elapsed * self.refill_per_second)
            b.last_refill = now
            if b.tokens >= 1:
                b.tokens -= 1
                return True, 0.0
            return False, (1 - b.tokens) / self.refill_per_second


def client_identifier(request: Request) -> str:
    """Best-effort client identifier for rate-limit bucketing.

    Cloud Run rewrites the inbound X-Forwarded-For so the first hop is the
    original client IP; trust that on the public-facing demo. Locally and
    from clients that don't go through a proxy, fall back to the socket
    address. Treat missing identity as a single bucket — a hostile caller
    that strips all headers shares a quota with every other anonymous caller.
    """
    fwd = request.headers.get("x-forwarded-for") or ""
    if fwd:
        return fwd.split(",", 1)[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "anonymous"


def rate_limit_dependency(
    limiter: TokenBucketLimiter,
) -> Callable[[Request], None]:
    """Build a FastAPI dependency that enforces `limiter` on each request."""

    def _dep(request: Request) -> None:
        key = client_identifier(request)
        allowed, retry_after = limiter.allow(key)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Too many requests; this is a demo service. Please slow down.",
                headers={"Retry-After": str(max(1, int(round(retry_after))))},
            )

    return _dep
