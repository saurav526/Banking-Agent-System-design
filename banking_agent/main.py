"""
Application Assembly & REST API Layer Module
============================================

Serves as the primary entry point and HTTP delivery layer for the multi-agent
banking platform, assembling edge security, identity verification, session state,
and coordinator agent dispatch into a unified FastAPI application.

Architecture & Request Flow:
----------------------------
Client (Chat UI / API Consumer)
  │
  ▼
Edge Gateway Middleware (`EdgeMiddleware`)
  │  [DoS Shedding, Volumetric/Token-Bucket Rate Limiting, WAF Threat Checks]
  ▼
Authentication & Identity Provider (`identity_provider`)
  │  [JWT Bearer Validation, Caller Identity Extraction, Role Enforcement]
  ▼
FastAPI API Endpoints & Session Management
  │  [Input Validation via Pydantic, Session Ownership Isolation]
  ▼
Coordinator Agent (`coordinator.handle`)
  │  [Guardrails, Tokenisation/Vaulting, Intent Decomposition, MCP Tool Execution]
  ▼
Downstream MCP Tool Microservices & Core Banking Engine

Exposed Route Groups:
---------------------
1. User Interface & Health:
   - `GET /`: Serves the static web chat UI (`index.html`).
   - `GET /health`: Returns operational readiness, system version, and LLM backend status.

2. Authentication & Principal Context:
   - `POST /api/auth/login`: Validates credentials and issues signed JWT bearer tokens.
   - `GET /api/me`: Returns profile, role memberships, and MFA verification level for the caller.

3. Chat Turns & Session Lifecycle:
   - `POST /api/sessions`: Initializes a new user session.
   - `GET /api/sessions`: Lists all sessions owned by the authenticated caller.
   - `POST /api/chat`: Validates session ownership, creates or resumes sessions, and
     hands input to `coordinator.handle()`.
   - `GET /api/sessions/{session_id}/history`: Returns bounded recent dialogue turns.
   - `GET /api/sessions/{session_id}/state`: Retrieves inter-agent shared memory.
   - `GET /api/sessions/{session_id}/trace`: Exposes customer-facing agent execution traces.

4. Operations & Observability (`require_ops` Guarded):
   - `GET /api/admin/metrics`: Aggregates system host usage, event counters, and model health.
   - `GET /api/admin/traces`: Queries distributed spans and execution telemetry.
   - `GET /api/admin/costs`: Summarizes real-time LLM token usage and monetary spend.
   - `POST /api/admin/evals/run`: Triggers the automated multi-agent evaluation benchmark suite.
"""
from __future__ import annotations

from pathlib import Path

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

app = FastAPI(title="Banking Agentic System", version=__version__)
app.add_middleware(EdgeMiddleware)


class LoginIn(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=128)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None


def require_ops(p: Principal = Depends(current_principal)) -> Principal:
    if "ops" not in p.roles:
        raise HTTPException(403, "Ops role required")
    return p


def _own_session(session_id: str, p: Principal) -> None:
    if session_store.get_owner(session_id) != p.user_id:
        raise HTTPException(404, "Session not found")


# ---------------- UI ----------------
@app.get("/", include_in_schema=False)
def ui_root():
    return FileResponse(UI_DIR / "index.html")


@app.get("/health")
def health():
    return {"status": "ok", "version": __version__, "llm": llm_router.status()}


# ---------------- Authentication ----------------
@app.post("/api/auth/login")
def api_login(body: LoginIn):
    return {"access_token": login(body.username, body.password), "token_type": "bearer"}


@app.get("/api/me")
def me(p: Principal = Depends(current_principal)):
    return {"user_id": p.user_id, "name": p.name, "roles": p.roles, "mfa": p.mfa, "customer_id": p.customer_id}


# ---------------- Chat / sessions ----------------
@app.post("/api/sessions")
def new_session(p: Principal = Depends(current_principal)):
    return {"session_id": session_store.create_session(p.user_id)}


@app.get("/api/sessions")
def my_sessions(p: Principal = Depends(current_principal)):
    return session_store.list_sessions(p.user_id)


@app.post("/api/chat")
async def chat(body: ChatIn, p: Principal = Depends(current_principal)):
    sid = body.session_id
    if sid:
        _own_session(sid, p)
    else:
        sid = session_store.create_session(p.user_id)
    return await coordinator.handle(body.message, p, sid)


@app.get("/api/sessions/{session_id}/history")
def history(session_id: str, p: Principal = Depends(current_principal)):
    _own_session(session_id, p)
    return session_store.history(session_id, limit=100)


@app.get("/api/sessions/{session_id}/state")
def shared_state(session_id: str, p: Principal = Depends(current_principal)):
    _own_session(session_id, p)
    return session_store.get_state(session_id)


@app.get("/api/sessions/{session_id}/trace")
def session_trace(session_id: str, trace_id: str | None = None, p: Principal = Depends(current_principal)):
    """Lets the customer UI show how its own request flowed through the agents."""
    _own_session(session_id, p)
    keep = ("ts", "trace_id", "kind", "name", "status", "duration_ms", "provider", "model", "tools", "tool",
            "allowed", "reason", "agents", "server", "is_error", "input_tokens", "output_tokens", "usd", "tool_calls")
    return [{k: e[k] for k in keep if k in e} for e in tracer.recent(300, trace_id=trace_id, session_id=session_id)]


# ---------------- Ops: observability, cost, evals ----------------
@app.get("/api/admin/metrics")
def metrics(_: OpsPrincipal):
    return {
        "system": system_metrics(),
        "event_counters": tracer.counters,
        "llm": llm_router.status()
    }


@app.get("/api/admin/traces")
def traces(
    limit: int = 200,
    trace_id: str | None = None,
    _: OpsPrincipal = None
):
    return tracer.recent(min(limit, 1000), trace_id=trace_id)


@app.get("/api/admin/costs")
def costs(_: OpsPrincipal):
    return cost_tracker.summary()


@app.post("/api/admin/evals/run")
async def run_evals(_: OpsPrincipal):
    from .evals.suite import run_suite

    return await run_suite()
