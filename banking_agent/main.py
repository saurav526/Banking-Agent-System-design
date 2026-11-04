"""
Application Assembly & REST API Layer Module
============================================

Serves as the primary entry point and HTTP delivery layer for the multi-agent
banking platform.

Architecture:
Client
  -> Edge Middleware
  -> Authentication
  -> FastAPI Endpoints
  -> Session Management
  -> Coordinator Agent
  -> MCP Tools and Banking Engine
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import __version__
from .agents.coordinator import coordinator
from .auth.identity_provider import Principal, current_principal, login
from .cost.tracker import cost_tracker
from .edge.gateway import EdgeMiddleware
from .llm.router import llm_router
from .observability.metrics import system_metrics
from .observability.tracer import tracer
from .session.store import session_store


UI_DIR = Path(__file__).parent / "ui"

app = FastAPI(
    title="Banking Agentic System",
    version=__version__,
)

app.add_middleware(EdgeMiddleware)


class LoginIn(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=128)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None


# ---------------- Authentication Dependencies ----------------

CurrentPrincipal = Annotated[
    Principal,
    Depends(current_principal),
]


def require_ops(p: CurrentPrincipal) -> Principal:
    if "ops" not in p.roles:
        raise HTTPException(
            status_code=403,
            detail="Ops role required",
        )

    return p


OpsPrincipal = Annotated[
    Principal,
    Depends(require_ops),
]


def _own_session(session_id: str, p: Principal) -> None:
    if session_store.get_owner(session_id) != p.user_id:
        raise HTTPException(
            status_code=404,
            detail="Session not found",
        )


# ---------------- User Interface ----------------

@app.get("/", include_in_schema=False)
def ui_root():
    return FileResponse(UI_DIR / "index.html")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": __version__,
        "llm": llm_router.status(),
    }


# ---------------- Authentication ----------------

@app.post("/api/auth/login")
def api_login(body: LoginIn):
    return {
        "access_token": login(body.username, body.password),
        "token_type": "bearer",
    }


@app.get("/api/me")
def me(p: CurrentPrincipal):
    return {
        "user_id": p.user_id,
        "name": p.name,
        "roles": p.roles,
        "mfa": p.mfa,
        "customer_id": p.customer_id,
    }


# ---------------- Chat and Sessions ----------------

@app.post("/api/sessions")
def new_session(p: CurrentPrincipal):
    return {
        "session_id": session_store.create_session(p.user_id),
    }


@app.get("/api/sessions")
def my_sessions(p: CurrentPrincipal):
    return session_store.list_sessions(p.user_id)


@app.post("/api/chat")
async def chat(
    body: ChatIn,
    p: CurrentPrincipal,
):
    sid = body.session_id

    if sid:
        _own_session(sid, p)
    else:
        sid = session_store.create_session(p.user_id)

    return await coordinator.handle(
        body.message,
        p,
        sid,
    )


@app.get("/api/sessions/{session_id}/history")
def history(
    session_id: str,
    p: CurrentPrincipal,
):
    _own_session(session_id, p)

    return session_store.history(
        session_id,
        limit=100,
    )


@app.get("/api/sessions/{session_id}/state")
def shared_state(
    session_id: str,
    p: CurrentPrincipal,
):
    _own_session(session_id, p)

    return session_store.get_state(session_id)


@app.get("/api/sessions/{session_id}/trace")
def session_trace(
    session_id: str,
    p: CurrentPrincipal,
    trace_id: str | None = None,
):
    _own_session(session_id, p)

    keep = (
        "ts",
        "trace_id",
        "kind",
        "name",
        "status",
        "duration_ms",
        "provider",
        "model",
        "tools",
        "tool",
        "allowed",
        "reason",
        "agents",
        "server",
        "is_error",
        "input_tokens",
        "output_tokens",
        "usd",
        "tool_calls",
    )

    events = tracer.recent(
        300,
        trace_id=trace_id,
        session_id=session_id,
    )

    return [
        {
            key: event[key]
            for key in keep
            if key in event
        }
        for event in events
    ]


# ---------------- Operations and Observability ----------------

@app.get("/api/admin/metrics")
def metrics(_: OpsPrincipal):
    return {
        "system": system_metrics(),
        "event_counters": tracer.counters,
        "llm": llm_router.status(),
    }


@app.get("/api/admin/traces")
def traces(
    _: OpsPrincipal,
    limit: int = 200,
    trace_id: str | None = None,
):
    return tracer.recent(
        min(max(limit, 1), 1000),
        trace_id=trace_id,
    )


@app.get("/api/admin/costs")
def costs(_: OpsPrincipal):
    return cost_tracker.summary()


@app.post("/api/admin/evals/run")
async def run_evals(_: OpsPrincipal):
    from .evals.suite import run_suite

    return await run_suite()