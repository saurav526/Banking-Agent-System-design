"""
Edge Gateway & Traffic Security Middleware Module
==================================================

Serves as the perimeter defensive layer and ASGI middleware (built on Starlette)
for ingress traffic control, DoS mitigation, rate limiting, and web application
firewall (WAF) rule enforcement.

In production architectures, these capabilities typically run on cloud edges
(Cloud Armor, AWS WAF, Apigee); this in-app implementation guarantees identical
zero-trust guardrails when running standalone or in development.

Key Defenses & Responsibilities:
--------------------------------
1. Route Whitelisting (API Gateway):
   - Restricts external reachability strictly to exposed prefixes (`PUBLIC_ROUTES`),
     returning 404 Not Found for undeclared endpoints.

2. DDoS Load Shedding & Concurrency Limiting:
   - Uses an asyncio semaphore (`_inflight`) to bound parallel active requests.
   - Rejects excess traffic with HTTP 503 ("Server busy") and `Retry-After` headers.

3. Volumetric & Token Bucket Rate Limiting:
   - Keyed per client IP (`ip:<host>`) and per authenticated user (`user:<sub>`).
   - Extracts unverified JWT subjects via Bearer token inspection specifically for
     rate-limiting buckets, returning HTTP 429 when depleted.

4. Anti-DoS Payload Constraints:
   - Rejects oversized requests based on `Content-Length` headers and inspects
     actual streamed body bytes against `settings.max_body_bytes` (HTTP 413).

5. Web Application Firewall (WAF) Inspection:
   - Evaluates URL query parameters and request bodies (POST, PUT, PATCH)
     against threat detection heuristics (`inspect`), halting exploits with HTTP 403.

6. Security Headers & Telemetry:
   - Injects standard security response headers (HSTS, CSP, X-Frame-Options, etc.).
   - Appends trace identifiers (`X-Request-ID`) and streams latency/status metrics
     to `request_stats` and `tracer`.
"""
from __future__ import annotations

import asyncio
import time
import uuid

import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ..config import settings
from ..observability.metrics import request_stats
from ..observability.tracer import tracer
from .rate_limit import TokenBucketLimiter
from .waf import inspect

limiter = TokenBucketLimiter(settings.rate_limit_per_minute, settings.rate_limit_burst)
_inflight = asyncio.Semaphore(settings.max_concurrent_requests)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'",
    "Cache-Control": "no-store",
}

# API gateway route table: only these prefixes are exposed publicly.
PUBLIC_ROUTES = ("/api/", "/health", "/ui", "/docs", "/openapi.json")


def _subject(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        try:  # signature is verified later by the auth layer; here only for rate-limit keying
            return jwt.decode(auth[7:], options={"verify_signature": False}).get("sub")
        except jwt.PyJWTError:
            return None
    return None


class EdgeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        status = 500
        try:
            resp = await self._guard(request)
            if resp is None:
                # DDoS protection: bounded concurrency (load shedding)
                if _inflight.locked():
                    resp = JSONResponse({"detail": "Server busy, retry shortly"}, 503, headers={"Retry-After": "2"})
                else:
                    async with _inflight:
                        resp = await call_next(request)
            status = resp.status_code
            resp.headers["X-Request-ID"] = request_id
            for k, v in SECURITY_HEADERS.items():
                resp.headers.setdefault(k, v)
            return resp
        finally:
            request_stats.record(status, (time.perf_counter() - start) * 1000)

    async def _guard(self, request: Request) -> Response | None:
        path = request.url.path
        ip = request.client.host if request.client else "unknown"

        # API gateway: route allow-list
        if path != "/" and not path.startswith(PUBLIC_ROUTES):
            return JSONResponse({"detail": "Not found"}, 404)

        # Request size limit (anti-DoS)
        clen = int(request.headers.get("content-length") or 0)
        if clen > settings.max_body_bytes:
            tracer.event("security", "body_too_large", ip=ip, size=clen)
            return JSONResponse({"detail": "Payload too large"}, 413)

        # Rate limits (per IP and per user)
        if path.startswith("/api/"):
            for key in filter(None, [f"ip:{ip}", f"user:{_subject(request)}" if _subject(request) else None]):
                ok, retry = limiter.allow(key)
                if not ok:
                    tracer.event("security", "rate_limited", key=key)
                    return JSONResponse({"detail": "Too many requests"}, 429, headers={"Retry-After": str(retry)})

        # WAF: query string + body
        body = b""
        if request.method in ("POST", "PUT", "PATCH"):
            body = await request.body()
            if len(body) > settings.max_body_bytes:
                return JSONResponse({"detail": "Payload too large"}, 413)
        rule = inspect(request.url.query) or inspect(body.decode("utf-8", "ignore"))
        if rule:
            tracer.event("security", "waf_block", rule=rule, ip=ip, path=path)
            return JSONResponse({"detail": f"Request blocked by WAF ({rule})"}, 403)
        return None
