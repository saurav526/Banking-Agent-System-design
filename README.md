# 🏦 Banking Agentic System

A working, runnable implementation of the multi-agent banking architecture:

```
User Interface (chat)
   └─► Edge Layer (WAF · DDoS · Rate limits · API Gateway) ──► Authentication (Bank IdP, JWT)
         └─► API
               └─► Coordinator Agent ──► Authorisation (RBAC, ownership, step-up MFA)
                     ├─► Accounts Agent     ─► Accounts MCP Server     ─► Balance Enquiry
                     ├─► Transaction Agent  ─► Transactions MCP Server ─► Transaction Details · Statement Request
                     └─► Service Agent      ─► Service MCP Server      ─► Change of Address · Chequebook · KYC Update
  Cross-cutting: PII Redaction · Agent Evaluation Suite · Self-hosted / Third-party LLM router ·
                 Session Store (history + inter-agent shared state) · Observability · Cost Tracker
```

## Quick start

```powershell
pip install -r requirements.txt
uvicorn banking_agent.main:app --reload
# open http://localhost:8000   (alice/alice123 · bob/bob123 · agent_ops/ops123)
```

Runs **fully offline** by default: a deterministic mock LLM speaks the same tool-calling protocol as a real model.
To use a real model, copy `.env.example` to `.env` and set:

| Mode | Settings |
|---|---|
| Self-hosted (Ollama/vLLM) | `LLM_DEFAULT_PROVIDER=self_hosted`, `SELF_HOSTED_BASE_URL`, `SELF_HOSTED_MODEL` |
| Third-party (OpenAI) | `LLM_DEFAULT_PROVIDER=third_party`, `OPENAI_API_KEY`, `THIRD_PARTY_MODEL` |

With `third_party` + `ROUTE_SENSITIVE_TO_SELF_HOSTED=true`, customer-data traffic goes to the self-hosted model first. If a provider fails, the router opens a circuit breaker and falls back to the next provider in the chain, with mock as the last resort.

## Component map

| Diagram box | Code |
|---|---|
| User Interface (chat) | `banking_agent/ui/index.html`: chat, live trace, shared state, ops dashboard |
| Edge Layer | `edge/gateway.py` (route allow-list, body limit, concurrency shedding, security headers), `edge/waf.py`, `edge/rate_limit.py` |
| Authentication | `auth/identity_provider.py`: JWT issue/verify (swap for real OIDC IdP) |
| API | `main.py` |
| Authorisation | `auth/authorization.py`: agent + tool policy, account ownership (anti-BOLA), MFA step-up for address/KYC |
| Coordinator Agent | `agents/coordinator.py`: guardrails, LLM routing, parallel multi-intent, synthesis, human-in-the-loop confirmation |
| Accounts / Transaction / Service Agents | `agents/domain.py`, `agents/base.py` (LLM tool-use loop) |
| MCP Servers | `mcp/protocol.py` (JSON-RPC `initialize`, `tools/list`, `tools/call`), `mcp/*_server.py`, `mcp/client.py` |
| Core banking (system of record) | `mcp/core_banking.py` (SQLite mock) |
| PII Redaction | `security/pii.py`: reversible tokenisation vault; LLMs only ever see `<ACCOUNT_1>`, `<PAN_1>`… |
| Self-hosted / Third-party LLM | `llm/openai_compat.py`, `llm/mock.py`, `llm/router.py` |
| Session Store | `session/store.py`: conversation history + inter-agent shared state |
| Observability | `observability/tracer.py` (prompts, agent/tool/LLM calls, authz, security → `data/traces.jsonl`), `observability/metrics.py` (CPU, memory, disk, latency) |
| Cost Tracker | `cost/tracker.py`: tokens & USD by model/agent/user/session + per-session budget |
| Agent Evaluation Suite | `evals/suite.py`: 16 golden multi-turn scenarios |

## Safety controls in the request path
1. WAF signatures (SQLi/XSS/traversal/cmd) and prompt-injection detection at the edge, checked again in the Coordinator
2. Per-IP and per-user token-bucket rate limits, payload size limit, bounded concurrency (load shedding)
3. JWT authentication, then authorisation on every agent hand-off and every tool call (deny by default)
4. Account ownership enforced twice: in the authoriser and inside the MCP servers (customer id is injected by the platform, never chosen by the LLM)
5. Write operations need an explicit **yes** from the customer and carry idempotency keys
6. PII is redacted before any LLM call. On the way out, full account and card numbers are masked to their last 4 digits

## Run independently deployed MCP servers
```powershell
python -m banking_agent.mcp.serve accounts       # :8101
python -m banking_agent.mcp.serve transactions   # :8102
python -m banking_agent.mcp.serve service        # :8103
$env:ACCOUNTS_MCP_URL="http://localhost:8101"; $env:TRANSACTIONS_MCP_URL="http://localhost:8102"; $env:SERVICE_MCP_URL="http://localhost:8103"
uvicorn banking_agent.main:app
```
Or run everything with `docker compose up` (add `--profile llm` to include Ollama).

## Tests & evaluation
```powershell
python -m pytest -q            # 17 integration tests (edge, auth, PII, HITL, MCP)
python -m banking_agent.evals  # agent evaluation suite: routing / tool / task / safety scores
```
Ops users can also run the eval suite from the UI (**Ops** tab) or with `POST /api/admin/evals/run`.

## Production swaps
SQLite → Postgres/Redis · in-app edge → Cloud Armor/AWS WAF + API Gateway · demo IdP → bank OIDC (JWKS) · JSONL traces → OpenTelemetry · mock core banking → real core banking APIs behind the MCP servers.
