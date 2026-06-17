"""FastAPI server hosting the DevPath Navigator agent.

Exposes:
  GET  /health          — readiness probe
  POST /chat            — single-turn or multi-turn chat
                          Body: {"user_id": str, "session_id": str?, "message": str}

Vertex AI authentication uses Application Default Credentials. On Cloud Run,
that is the runtime service account; locally it's the user's ADC.

Environment variables read at startup:
  GCP_PROJECT             — BigQuery / Vertex project
  BQ_LOCATION             — BigQuery region (default asia-northeast1)
  BQ_DATASET              — BigQuery dataset (default devpath)
  VERTEX_LOCATION         — Vertex AI region for Gemini (default us-central1)
  GEMINI_MODEL            — model id (default gemini-2.5-flash)
  AGENT_BATCHES           — comma-separated batch ids to train W2V on (default "initial")
  GOOGLE_GENAI_USE_VERTEXAI — set to "true" so ADK calls Vertex (auto-set here)
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from google.genai import types as genai_types
from pydantic import BaseModel, Field

from agent.rate_limit import TokenBucketLimiter, rate_limit_dependency

# --- Configure Vertex AI BEFORE importing the agent (ADK reads env on import).
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", os.environ.get("GCP_PROJECT", "ai-agent-hackathon-499013"))
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", os.environ.get("VERTEX_LOCATION", "us-central1"))

from google.adk.runners import InMemoryRunner  # noqa: E402

from agent.agent import build_agent  # noqa: E402
from agent.state import build_state, set_state  # noqa: E402

APP_NAME = "devpath"

# Configure the project's logger once at import time. Cloud Run captures stdout
# at INFO level by default; structured logs (JSON-ish key=value pairs in the
# message) survive Cloud Logging's auto-parsing better than bare prose.
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("devpath.server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    start = time.monotonic()
    logger.info("startup: building app state")
    state = build_state()
    set_state(state)
    app.state.agent = build_agent()
    app.state.runner = InMemoryRunner(agent=app.state.agent, app_name=APP_NAME)
    logger.info("startup complete in %.1fs", time.monotonic() - start)
    yield


app = FastAPI(title="DevPath Navigator", lifespan=lifespan)

def resolve_cors_config(env: dict[str, str] | None = None) -> tuple[list[str], bool]:
    """Resolve CORS origins + credentials flag from environment.

    Production traffic flows through the Next.js frontend (which proxies
    via /api/*), so the browser only sees one origin. Direct calls from a
    browser to this service are blocked unless the origin is in
    AGENT_ALLOWED_ORIGINS (comma-separated).

    On Cloud Run (K_SERVICE is set) we refuse to return wildcard CORS:
    the service is public and unauthenticated, so `*` would let any web
    page issue cross-origin POSTs to /chat from a visitor's browser,
    burning Gemini quota and BQ cost on the project's bill. Fail-closed
    beats serving `*` to a public URL.

    Pulled into a function (rather than module-load-time toplevel code)
    so tests can drive it without reloading the module.
    """
    e = os.environ if env is None else env
    raw = e.get("AGENT_ALLOWED_ORIGINS", "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()], True
    if e.get("K_SERVICE"):
        raise RuntimeError(
            "AGENT_ALLOWED_ORIGINS must be set when running on Cloud Run "
            "(K_SERVICE is set). Refusing to start with wildcard CORS on a "
            "public unauthenticated endpoint."
        )
    # CORS forbids credentials with wildcard, so allow_credentials=False.
    return ["*"], False


_allow_origins, _allow_credentials = resolve_cors_config()

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Rate limits. /chat is the expensive one (each call fans out to Gemini
# plus several BQ queries via tools), so it's the strictest. /map and
# /eval-history are read-only and cached/aggregated, so they're looser.
# Limits are PER CLOUD RUN INSTANCE — at max-instances=3 the effective
# bucket per IP is 3× these numbers. Good enough for a demo; documented.
chat_limiter = TokenBucketLimiter(
    capacity=float(os.environ.get("RATE_LIMIT_CHAT_BURST", "5")),
    refill_per_second=float(os.environ.get("RATE_LIMIT_CHAT_PER_SECOND", "0.25")),  # 15/min steady
)
read_limiter = TokenBucketLimiter(
    capacity=float(os.environ.get("RATE_LIMIT_READ_BURST", "30")),
    refill_per_second=float(os.environ.get("RATE_LIMIT_READ_PER_SECOND", "2.0")),
)
require_chat_quota = rate_limit_dependency(chat_limiter)
require_read_quota = rate_limit_dependency(read_limiter)


MAX_USER_ID_LENGTH = 128
MAX_SESSION_ID_LENGTH = 128
MAX_MESSAGE_LENGTH = 4000

# Per-/chat fan-out caps. Without these, a single request can stream an
# unbounded number of Gemini turns + tool calls. We cap two numbers
# because they bound different surfaces:
#   * MAX_EVENTS_PER_CHAT  — total ADK events the runner streams. Even
#                            non-tool events cost wall-clock + tokens.
#   * MAX_TOOL_CALLS_PER_CHAT — function_call parts Gemini emits. Each
#                            tool invocation runs at least one BQ job
#                            (some run a nested Gemini call via
#                            `nlq_over_corpus`). This is the cost lever.
# Caps are intentionally generous for a normal answer flow (~3-5 tool
# calls) but bounded enough that a prompt-injection-driven fan-out
# can't keep growing cost without limit.
MAX_EVENTS_PER_CHAT = int(os.environ.get("AGENT_MAX_EVENTS", "24"))
MAX_TOOL_CALLS_PER_CHAT = int(os.environ.get("AGENT_MAX_TOOL_CALLS", "8"))


class ChatRequest(BaseModel):
    user_id: str = Field(
        ...,
        description="Stable identifier for the user (any string).",
        max_length=MAX_USER_ID_LENGTH,
        min_length=1,
    )
    message: str = Field(
        ...,
        description="Latest user message.",
        max_length=MAX_MESSAGE_LENGTH,
        min_length=1,
    )
    session_id: str | None = Field(
        default=None,
        description="Optional session id for multi-turn.",
        max_length=MAX_SESSION_ID_LENGTH,
    )


class ToolCall(BaseModel):
    name: str
    args: dict[str, Any] | None = None


class ToolResult(BaseModel):
    name: str
    response: dict[str, Any] | None = None


class ChatResponse(BaseModel):
    session_id: str
    response: str
    tool_calls: list[ToolCall]
    tool_results: list[ToolResult]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


class MapPoint(BaseModel):
    employee_id: str
    x: float
    y: float
    cluster_id: int
    archetype: str | None = None


class MapCluster(BaseModel):
    cluster_id: int
    size: int
    dominant_archetype: str | None
    archetype_purity: float | None
    centroid_x: float
    centroid_y: float


class MapResponse(BaseModel):
    points: list[MapPoint]
    clusters: list[MapCluster]


_MAP_CACHE: MapResponse | None = None


@app.get("/map", response_model=MapResponse, dependencies=[Depends(require_read_quota)])
def map_data() -> MapResponse:
    """Return all UMAP coordinates + cluster metadata for the frontend."""
    global _MAP_CACHE
    if _MAP_CACHE is not None:
        return _MAP_CACHE

    from agent.state import get_state
    state = get_state()
    coords_rows = list(state.bq_client.query(
        f"SELECT employee_id, x, y, cluster_id, archetype "
        f"FROM `{state.project}.{state.dataset}.umap_coords`"
    ).result())
    cluster_rows = list(state.bq_client.query(
        f"SELECT cluster_id, size, dominant_archetype, archetype_purity, centroid_x, centroid_y "
        f"FROM `{state.project}.{state.dataset}.clusters`"
    ).result())
    _MAP_CACHE = MapResponse(
        points=[
            MapPoint(
                employee_id=r.employee_id,
                x=float(r.x),
                y=float(r.y),
                cluster_id=int(r.cluster_id),
                archetype=r.archetype,
            )
            for r in coords_rows
        ],
        clusters=[
            MapCluster(
                cluster_id=int(r.cluster_id),
                size=int(r.size),
                dominant_archetype=r.dominant_archetype,
                archetype_purity=float(r.archetype_purity) if r.archetype_purity is not None else None,
                centroid_x=float(r.centroid_x),
                centroid_y=float(r.centroid_y),
            )
            for r in cluster_rows
        ],
    )
    return _MAP_CACHE


class EvalRunSummary(BaseModel):
    run_id: str
    run_at: str | None
    batches: list[str]
    recall_at_10: float
    n_clusters: int
    mean_archetype_purity: float
    archetypes_covered: list[str]
    vocab_size: int
    decision: str
    decision_reasons: list[str]


class EvalHistoryResponse(BaseModel):
    runs: list[EvalRunSummary]


@app.get(
    "/eval-history",
    response_model=EvalHistoryResponse,
    dependencies=[Depends(require_read_quota)],
)
def eval_history(limit: int = 50) -> EvalHistoryResponse:
    """Retraining evaluation history for the dashboard (newest first)."""
    from agent.state import get_state
    from eval.store import history

    state = get_state()
    rows = history(state.bq_client, state.dataset, limit=max(1, min(int(limit), 200)))
    return EvalHistoryResponse(runs=[EvalRunSummary(**r) for r in rows])


@app.post(
    "/chat",
    response_model=ChatResponse,
    dependencies=[Depends(require_chat_quota)],
)
async def chat(req: ChatRequest) -> ChatResponse:
    runner: InMemoryRunner = app.state.runner

    if req.session_id:
        session = await runner.session_service.get_session(
            app_name=APP_NAME, user_id=req.user_id, session_id=req.session_id
        )
        if session is None:
            session = await runner.session_service.create_session(
                app_name=APP_NAME, user_id=req.user_id
            )
    else:
        session = await runner.session_service.create_session(
            app_name=APP_NAME, user_id=req.user_id
        )

    content = genai_types.Content(role="user", parts=[genai_types.Part.from_text(text=req.message)])

    response_text = ""
    tool_calls: list[ToolCall] = []
    tool_results: list[ToolResult] = []
    event_count = 0
    tool_call_count = 0
    hit_cap: str | None = None  # set to a label when a fan-out cap is reached
    try:
        async for event in runner.run_async(
            user_id=req.user_id, session_id=session.id, new_message=content
        ):
            event_count += 1
            if event_count > MAX_EVENTS_PER_CHAT:
                hit_cap = f"event cap ({MAX_EVENTS_PER_CHAT})"
                break
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.function_call:
                        if tool_call_count >= MAX_TOOL_CALLS_PER_CHAT:
                            hit_cap = f"tool-call cap ({MAX_TOOL_CALLS_PER_CHAT})"
                            break
                        tool_call_count += 1
                        tool_calls.append(ToolCall(
                            name=part.function_call.name,
                            args=dict(part.function_call.args) if part.function_call.args else None,
                        ))
                    if part.function_response:
                        tool_results.append(ToolResult(
                            name=part.function_response.name,
                            response=dict(part.function_response.response)
                            if part.function_response.response else None,
                        ))
                if hit_cap:
                    break
            if event.is_final_response() and event.content and event.content.parts:
                for part in event.content.parts:
                    # Skip Gemini thinking parts — those are internal reasoning,
                    # not the user-facing reply. (Some SDK versions expose this
                    # as part.thought=True; defensively check for it.)
                    if getattr(part, "thought", False):
                        continue
                    if part.text:
                        response_text += part.text
        if hit_cap:
            logger.warning(
                "[chat] %s reached (events=%d tool_calls=%d user=%s session=%s)",
                hit_cap, event_count, tool_call_count, req.user_id, session.id,
            )
            if not response_text:
                response_text = (
                    "Sorry, I had to stop early because this conversation hit a "
                    "per-request safety cap. Try asking a more specific question."
                )
    except Exception as exc:
        # Don't leak the raw exception text to the caller — it might include
        # internal table names, SDK stack hints, or other reconnaissance gold.
        # Log the full thing locally with a short id, return only the id.
        incident_id = uuid.uuid4().hex[:8]
        logger.exception(
            "[chat] agent error (incident=%s, user=%s, session=%s): %s",
            incident_id, req.user_id, session.id, exc,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Agent encountered an internal error. (incident: {incident_id})",
        ) from exc

    return ChatResponse(
        session_id=session.id,
        response=response_text,
        tool_calls=tool_calls,
        tool_results=tool_results,
    )
