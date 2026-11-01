"""Authentication: stand-in for the Bank's identity provider (OIDC-like).

Issues and validates signed JWT access tokens. In production replace
``login`` with an OIDC redirect to the real IdP and keep ``verify_token``
validating the IdP's JWKS-signed tokens.
"""
from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..config import settings


def _hash(pw: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100_000).hex()


# Demo customer directory (would live in the IdP). customer_id links to core banking.
_USERS: dict[str, dict] = {
    "alice": {"salt": "s1", "pw": _hash("alice123", "s1"), "customer_id": "CUST001", "name": "Alice Sharma",
              "roles": ["customer"], "mfa": True},
    "bob": {"salt": "s2", "pw": _hash("bob123", "s2"), "customer_id": "CUST002", "name": "Bob Mehta",
            "roles": ["customer"], "mfa": False},
    "agent_ops": {"salt": "s3", "pw": _hash("ops123", "s3"), "customer_id": None, "name": "Ops Viewer",
                  "roles": ["ops"], "mfa": True},
}


@dataclass
class Principal:
    user_id: str
    customer_id: str | None
    name: str
    roles: list[str]
    mfa: bool  # authentication assurance level (acr) - used for step-up checks
    token_id: str


def login(username: str, password: str) -> str:
    u = _USERS.get(username)
    if not u or not hmac.compare_digest(u["pw"], _hash(password, u["salt"])):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    now = int(time.time())
    claims = {
        "iss": settings.jwt_issuer,
        "sub": username,
        "aud": "banking-assistant",
        "iat": now,
        "exp": now + settings.jwt_ttl_seconds,
        "jti": uuid.uuid4().hex,
        "customer_id": u["customer_id"],
        "name": u["name"],
        "roles": u["roles"],
        "acr": "mfa" if u["mfa"] else "pwd",
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256")


def verify_token(token: str) -> Principal:
    try:
        c = jwt.decode(
            token, settings.jwt_secret, algorithms=["HS256"], audience="banking-assistant", issuer=settings.jwt_issuer
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {exc}") from exc
    return Principal(c["sub"], c.get("customer_id"), c.get("name", ""), c.get("roles", []), c.get("acr") == "mfa", c["jti"])


_bearer = HTTPBearer(auto_error=False)


def current_principal(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> Principal:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    return verify_token(creds.credentials)
