"""Central configuration (env-driven, see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    # --- Authentication (bank identity provider) ---
    jwt_secret: str = os.getenv("JWT_SECRET", "dev-only-change-me-please-32bytes!!")
    jwt_issuer: str = os.getenv("JWT_ISSUER", "https://idp.bank.local")
    jwt_ttl_seconds: int = int(os.getenv("JWT_TTL_SECONDS", "1800"))

    # --- Edge layer ---
    rate_limit_per_minute: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "30"))
    rate_limit_burst: int = int(os.getenv("RATE_LIMIT_BURST", "10"))
    max_body_bytes: int = int(os.getenv("MAX_BODY_BYTES", "16384"))
    max_concurrent_requests: int = int(os.getenv("MAX_CONCURRENT_REQUESTS", "100"))

    # --- LLMs ---
    # provider: "mock" (offline, deterministic), "self_hosted", "third_party"
    llm_default_provider: str = os.getenv("LLM_DEFAULT_PROVIDER", "mock")
    # PII-bearing traffic is forced to self-hosted model (if available) else redacted
    route_sensitive_to_self_hosted: bool = _bool("ROUTE_SENSITIVE_TO_SELF_HOSTED", True)

    self_hosted_base_url: str = os.getenv("SELF_HOSTED_BASE_URL", "http://localhost:11434/v1")
    self_hosted_model: str = os.getenv("SELF_HOSTED_MODEL", "llama3.1:8b")
    self_hosted_api_key: str = os.getenv("SELF_HOSTED_API_KEY", "ollama")

    third_party_base_url: str | None = os.getenv("THIRD_PARTY_BASE_URL") or None
    third_party_model: str = os.getenv("THIRD_PARTY_MODEL", "gpt-4o-mini")
    third_party_api_key: str | None = os.getenv("OPENAI_API_KEY") or None

    llm_timeout_seconds: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "30"))
    max_agent_steps: int = int(os.getenv("MAX_AGENT_STEPS", "5"))

    # --- MCP servers: "inprocess" or a base URL e.g. http://localhost:8101 ---
    accounts_mcp_url: str = os.getenv("ACCOUNTS_MCP_URL", "inprocess")
    transactions_mcp_url: str = os.getenv("TRANSACTIONS_MCP_URL", "inprocess")
    service_mcp_url: str = os.getenv("SERVICE_MCP_URL", "inprocess")
    mcp_shared_secret: str = os.getenv("MCP_SHARED_SECRET", "mcp-dev-secret")

    # --- Storage ---
    session_db: str = os.getenv("SESSION_DB", str(DATA_DIR / "sessions.db"))
    core_banking_db: str = os.getenv("CORE_BANKING_DB", str(DATA_DIR / "core_banking.db"))
    trace_log: str = os.getenv("TRACE_LOG", str(DATA_DIR / "traces.jsonl"))

    # --- Cost tracker: USD per 1M tokens (input, output) ---
    pricing: dict = field(
        default_factory=lambda: {
            "mock": (0.0, 0.0),
            "gpt-4o-mini": (0.15, 0.60),
            "gpt-4o": (2.50, 10.00),
            # self-hosted: amortised GPU cost estimate
            "self_hosted": (0.05, 0.05),
        }
    )
    session_budget_usd: float = float(os.getenv("SESSION_BUDGET_USD", "0.50"))


settings = Settings()
