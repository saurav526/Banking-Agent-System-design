"""MCP client used by the domain agents (in-process or Streamable HTTP)."""
from __future__ import annotations

import itertools
import json

import httpx

from ..config import settings
from ..observability.tracer import tracer
from ..security.pii import mask_for_logs
from .protocol import MCPServer

_ids = itertools.count(1)


class MCPClient:
    def __init__(self, server: MCPServer, url: str = "inprocess") -> None:
        self.server = server
        self.url = url
        self._tools_cache: list[dict] | None = None

    async def _rpc(self, method: str, params: dict | None, customer_id: str | None) -> dict:
        req = {"jsonrpc": "2.0", "id": next(_ids), "method": method, "params": params or {}}
        if self.url == "inprocess":
            resp = await self.server.handle(req, customer_id)
        else:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post(
                    self.url.rstrip("/") + "/mcp",
                    json=req,
                    headers={"x-mcp-secret": settings.mcp_shared_secret, "x-customer-id": customer_id or ""},
                )
                r.raise_for_status()
                resp = r.json()
        if "error" in resp:
            raise RuntimeError(resp["error"]["message"])
        return resp["result"]

    async def list_tools(self) -> list[dict]:
        if self._tools_cache is None:
            self._tools_cache = (await self._rpc("tools/list", None, None))["tools"]
        return self._tools_cache

    async def call_tool(self, name: str, arguments: dict, customer_id: str) -> dict:
        with tracer.span("tool_call", name, server=self.server.name,
                         arguments=mask_for_logs(json.dumps(arguments))) as span:
            result = await self._rpc("tools/call", {"name": name, "arguments": arguments}, customer_id)
            span["is_error"] = result.get("isError", False)
            return result

    def is_write(self, name: str) -> bool:
        t = self.server.tools.get(name)
        return bool(t and t.is_write)
