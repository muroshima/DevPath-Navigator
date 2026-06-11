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

# CORS — production traffic flows through the Next.js frontend (which
# proxies via /api/*), so the browser only sees one origin. Direct calls
# from a browser to this service are blocked unless the origin is in
# AGENT_ALLOWED_ORIGINS (comma-separated). For local dev that env var is
# empty, which keeps the previous wildcard behavior so curl + localhost
# clients still work.
_allow_origins_raw = os.environ.get("AGENT_ALLOWED_ORIGINS", "").strip()
if _allow_origins_raw:
    _allow_origins = [o.strip() for o in _allow_origins_raw.split(",") if o.strip()]
    _allow_credentials = True
else:
    _allow_origins = ["*"]
    _allow_credentials = False  # CORS forbids credentials with wildcard

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
    try:
        async for event in runner.run_async(
            user_id=req.user_id, session_id=session.id, new_message=content
        ):
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.function_call:
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
            if event.is_final_response() and event.content and event.content.parts:
                for part in event.content.parts:
                    # Skip Gemini thinking parts — those are internal reasoning,
                    # not the user-facing reply. (Some SDK versions expose this
                    # as part.thought=True; defensively check for it.)
                    if getattr(part, "thought", False):
                        continue
                    if part.text:
                        response_text += part.text
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
