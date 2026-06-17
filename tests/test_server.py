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

from agent.server import _parse_positive_int_env, resolve_cors_config


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


def test_cors_whitespace_only_allowlist_on_cloud_run_fails_closed():
    """Regression: a whitespace-only AGENT_ALLOWED_ORIGINS must NOT
    bypass the Cloud Run fail-closed behavior. After .strip() the value
    is empty, so the K_SERVICE gate must still fire."""
    with pytest.raises(RuntimeError, match="AGENT_ALLOWED_ORIGINS must be set"):
        resolve_cors_config(env={
            "K_SERVICE": "devpath-agent",
            "AGENT_ALLOWED_ORIGINS": "   ",
        })


def test_cors_literal_wildcard_in_allowlist_rejected():
    """`AGENT_ALLOWED_ORIGINS='*'` would otherwise be parsed as a 1-element
    allowlist with credentials=True, which is a CORS spec violation
    (wildcard + credentials is forbidden). Operator must omit the env
    var for wildcard, not list `*` explicitly."""
    with pytest.raises(RuntimeError, match="wildcard CORS"):
        resolve_cors_config(env={"AGENT_ALLOWED_ORIGINS": "*"})


def test_cors_wildcard_mixed_with_real_origins_also_rejected():
    """Same defensive guard for `*, https://x.example.com` — operator
    almost certainly meant the explicit origin and the `*` is a typo,
    but we can't tell which, so fail fast."""
    with pytest.raises(RuntimeError, match="wildcard CORS"):
        resolve_cors_config(env={
            "AGENT_ALLOWED_ORIGINS": "*, https://devpath.example.com",
        })


def test_cors_comma_only_allowlist_on_cloud_run_fails_closed():
    """`AGENT_ALLOWED_ORIGINS=','` would previously parse to an empty
    list but still set allow_credentials=True. Treat it as 'unset' so
    the K_SERVICE gate fires consistently."""
    with pytest.raises(RuntimeError, match="AGENT_ALLOWED_ORIGINS must be set"):
        resolve_cors_config(env={
            "K_SERVICE": "devpath-agent",
            "AGENT_ALLOWED_ORIGINS": ",,,",
        })


# -- Positive-int env parser ---------------------------------------------------


def test_parse_positive_int_env_returns_default_when_unset(monkeypatch):
    monkeypatch.delenv("FOO_BAR", raising=False)
    assert _parse_positive_int_env("FOO_BAR", 24) == 24


def test_parse_positive_int_env_returns_default_when_blank(monkeypatch):
    monkeypatch.setenv("FOO_BAR", "")
    assert _parse_positive_int_env("FOO_BAR", 24) == 24


def test_parse_positive_int_env_parses_valid_int(monkeypatch):
    monkeypatch.setenv("FOO_BAR", "42")
    assert _parse_positive_int_env("FOO_BAR", 24) == 42


def test_parse_positive_int_env_raises_on_garbage(monkeypatch):
    """Operator typo like `AGENT_MAX_EVENTS=24a` should produce a clear
    error pointing at the env var, not an opaque ValueError traceback."""
    monkeypatch.setenv("FOO_BAR", "24a")
    with pytest.raises(RuntimeError, match="FOO_BAR must be a positive integer"):
        _parse_positive_int_env("FOO_BAR", 24)


def test_parse_positive_int_env_raises_on_zero_or_negative(monkeypatch):
    """0 and negatives would silently disable the cap (or break the
    `if event_count > MAX` comparison logic) — reject them explicitly."""
    monkeypatch.setenv("FOO_BAR", "0")
    with pytest.raises(RuntimeError, match="FOO_BAR must be > 0"):
        _parse_positive_int_env("FOO_BAR", 24)
    monkeypatch.setenv("FOO_BAR", "-3")
    with pytest.raises(RuntimeError, match="FOO_BAR must be > 0"):
        _parse_positive_int_env("FOO_BAR", 24)


def test_parse_positive_int_env_strips_surrounding_whitespace(monkeypatch):
    """Copy/paste-induced whitespace in env values shouldn't fail
    closed. `AGENT_MAX_EVENTS="24 "` is a clear positive integer."""
    monkeypatch.setenv("FOO_BAR", "  24\n")
    assert _parse_positive_int_env("FOO_BAR", 1) == 24
