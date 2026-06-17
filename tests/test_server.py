"""Tests for `agent.server` helpers — the pieces of server.py that don't
need a FastAPI app or an initialised ADK runner.

`resolve_cors_config` is pulled out as a pure function so we can drive it
with synthetic env dicts; that's how we verify the Cloud Run fail-closed
behaviour without booting the app.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# `agent.server` runs `resolve_cors_config()` at import time. The only
# failure case we need to guard against is "K_SERVICE is set AND
# AGENT_ALLOWED_ORIGINS parses to an empty list" — that combination
# raises during the import and the whole test module fails to load on
# Cloud Run-style CI runners. Gate the mutation on K_SERVICE so we
# don't unnecessarily touch the process env in normal local runs.
#
# Tests pass explicit env dicts to `resolve_cors_config`, so the
# placeholder we install here doesn't affect their assertions.
if os.environ.get("K_SERVICE"):
    _raw_origins = os.environ.get("AGENT_ALLOWED_ORIGINS", "")
    if not any(o.strip() for o in _raw_origins.split(",")):
        os.environ["AGENT_ALLOWED_ORIGINS"] = "http://test-placeholder"

from agent.server import (  # noqa: E402
    ChatRequest,
    _consume_runner_events,
    _parse_positive_int_env,
    resolve_cors_config,
)


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
    """Whitespace-only AGENT_ALLOWED_ORIGINS is treated as 'unset' for
    the purposes of the local-dev wildcard fallback (no K_SERVICE
    here — see the next test for the Cloud Run gate combined with
    whitespace)."""
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


# -- Fan-out cap enforcement (_consume_runner_events) --------------------------


class _FakeFunctionCall:
    def __init__(self, name: str, args: dict | None = None):
        self.name = name
        self.args = args or {}


class _FakeFunctionResponse:
    def __init__(self, name: str, response: dict | None = None):
        self.name = name
        self.response = response or {}


class _FakePart:
    def __init__(
        self,
        function_call: _FakeFunctionCall | None = None,
        function_response: _FakeFunctionResponse | None = None,
        text: str | None = None,
        thought: bool = False,
    ):
        self.function_call = function_call
        self.function_response = function_response
        self.text = text
        self.thought = thought


class _FakeContent:
    def __init__(self, parts: list[_FakePart]):
        self.parts = parts


class _FakeEvent:
    def __init__(self, parts: list[_FakePart], *, final: bool = False):
        self.content = _FakeContent(parts) if parts else None
        self._final = final

    def is_final_response(self) -> bool:
        return self._final


async def _stream(events: list[_FakeEvent]):
    for e in events:
        yield e


def _run(coro):
    """Run an async coroutine to completion from a sync test."""
    import asyncio
    return asyncio.run(coro)


def test_consume_runner_events_stops_at_event_cap():
    """50 events streamed, cap is 3 → loop must break after the 4th
    iteration (because we increment-then-check)."""
    events = [_FakeEvent([_FakePart(text="x")], final=False) for _ in range(50)]
    text, calls, results, hit = _run(
        _consume_runner_events(_stream(events), max_events=3, max_tool_calls=8)
    )
    assert hit == "event cap (3)"
    # No tool calls, no final text — partial state OK
    assert calls == []
    assert results == []


def test_consume_runner_events_stops_at_tool_call_cap():
    """Stream emits 6 function_call parts but cap is 2 — only 2 should
    be recorded and `hit_cap` flags the tool-call cap."""
    events = [
        _FakeEvent([_FakePart(function_call=_FakeFunctionCall(f"t{i}"))])
        for i in range(6)
    ]
    text, calls, results, hit = _run(
        _consume_runner_events(_stream(events), max_events=24, max_tool_calls=2)
    )
    assert hit == "tool-call cap (2)"
    assert [c.name for c in calls] == ["t0", "t1"]


def test_consume_runner_events_collects_normal_response_under_cap():
    """A normal 3-tool flow + final text should fully complete with
    hit_cap=None and the final text concatenated."""
    events = [
        _FakeEvent([_FakePart(function_call=_FakeFunctionCall("locate_user"))]),
        _FakeEvent([
            _FakePart(function_response=_FakeFunctionResponse("locate_user", {"x": 1}))
        ]),
        _FakeEvent([_FakePart(function_call=_FakeFunctionCall("explain_cluster"))]),
        _FakeEvent([
            _FakePart(function_response=_FakeFunctionResponse("explain_cluster", {"y": 2}))
        ]),
        _FakeEvent([_FakePart(text="Final answer.")], final=True),
    ]
    text, calls, results, hit = _run(
        _consume_runner_events(_stream(events), max_events=24, max_tool_calls=8)
    )
    assert hit is None
    assert text == "Final answer."
    assert [c.name for c in calls] == ["locate_user", "explain_cluster"]
    assert [r.name for r in results] == ["locate_user", "explain_cluster"]


def test_consume_runner_events_skips_thinking_parts_in_final():
    """Gemini emits `thought=True` parts as internal reasoning — those
    must not be concatenated into the user-facing response."""
    events = [
        _FakeEvent(
            [
                _FakePart(text="HIDDEN reasoning", thought=True),
                _FakePart(text="Visible reply"),
            ],
            final=True,
        ),
    ]
    text, _, _, hit = _run(
        _consume_runner_events(_stream(events), max_events=24, max_tool_calls=8)
    )
    assert hit is None
    assert text == "Visible reply"
    assert "HIDDEN" not in text


# -- M1: ChatRequest log-injection guard ---------------------------------------


def test_chat_request_accepts_url_safe_user_id():
    """Realistic ids — random UUIDs / app-generated identifiers / our own
    `web-<random>` shape — must all pass."""
    for uid in ["web-abc123", "alice_42", "550e8400e29b41d4a716446655440000", "A-Z_0-9"]:
        req = ChatRequest(user_id=uid, message="hi")
        assert req.user_id == uid


def test_chat_request_rejects_newline_in_user_id():
    """The motivating bug: `user_id="alice\\nFATAL: fake"` would forge a
    log line in `logger.exception("[chat] ..., user=%s, ...", user_id)`.
    Pydantic must reject it at the validation boundary."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ChatRequest(user_id="alice\nFATAL: fake", message="hi")


def test_chat_request_rejects_carriage_return_in_user_id():
    """Some log forging exploits use `\\r` to overwrite the current line."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ChatRequest(user_id="alice\rinjected", message="hi")


def test_chat_request_rejects_whitespace_in_user_id():
    """Bare spaces are also outside the URL-safe id charset."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ChatRequest(user_id="alice bob", message="hi")


def test_chat_request_rejects_control_characters_in_user_id():
    """Null bytes and other control characters must be rejected for the
    same reason — they confuse log parsers and downstream consumers."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ChatRequest(user_id="alice\x00admin", message="hi")


def test_chat_request_rejects_newline_in_session_id():
    """`session_id` also flows into log lines and is also client-supplied —
    the same constraint applies."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ChatRequest(
            user_id="alice", session_id="sess\nFATAL: fake", message="hi"
        )


def test_chat_request_accepts_message_with_whitespace_and_newlines():
    """`message` is natural language — it CAN contain newlines, punctuation,
    and arbitrary unicode. Only the id fields are charset-restricted."""
    req = ChatRequest(
        user_id="alice",
        message="line 1\nline 2 with 'quotes' and 🤖 emoji",
    )
    assert "\n" in req.message
    assert "🤖" in req.message
