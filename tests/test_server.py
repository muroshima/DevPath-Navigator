"""Tests for `agent.server` helpers — the pieces of server.py that don't
need a FastAPI app or an initialised ADK runner.

`resolve_cors_config` is pulled out as a pure function so we can drive it
with synthetic env dicts; that's how we verify the Cloud Run fail-closed
behaviour without booting the app.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.server import resolve_cors_config


def test_cors_wildcard_locally_when_env_unset():
    """No env vars at all → wildcard for local dev convenience.
    `allow_credentials` MUST be False with wildcard (CORS spec)."""
    origins, allow_credentials = resolve_cors_config(env={})
    assert origins == ["*"]
    assert allow_credentials is False


def test_cors_fail_closed_on_cloud_run_when_origins_unset():
    """K_SERVICE present + AGENT_ALLOWED_ORIGINS absent must raise so the
    service refuses to start. Serving wildcard CORS on a public,
    unauthenticated endpoint would let any origin spend Gemini quota /
    BQ cost on the project's bill."""
    with pytest.raises(RuntimeError, match="AGENT_ALLOWED_ORIGINS must be set"):
        resolve_cors_config(env={"K_SERVICE": "devpath-agent"})


def test_cors_uses_explicit_allowlist_when_provided_on_cloud_run():
    """Cloud Run + explicit allowlist → credentials allowed, origins
    parsed from the comma-separated list with whitespace stripped."""
    origins, allow_credentials = resolve_cors_config(env={
        "K_SERVICE": "devpath-agent",
        "AGENT_ALLOWED_ORIGINS": "https://devpath.example.com, https://other.example.com",
    })
    assert origins == ["https://devpath.example.com", "https://other.example.com"]
    assert allow_credentials is True


def test_cors_explicit_allowlist_locally_also_enables_credentials():
    """Explicit list always enables credentials, regardless of K_SERVICE."""
    origins, allow_credentials = resolve_cors_config(env={
        "AGENT_ALLOWED_ORIGINS": "http://localhost:3000",
    })
    assert origins == ["http://localhost:3000"]
    assert allow_credentials is True


def test_cors_empty_allowlist_falls_back_to_default():
    """Whitespace-only AGENT_ALLOWED_ORIGINS is treated as 'unset' so the
    K_SERVICE gate applies the same way as a missing env var."""
    origins, allow_credentials = resolve_cors_config(env={
        "AGENT_ALLOWED_ORIGINS": "   ",
    })
    assert origins == ["*"]
    assert allow_credentials is False
