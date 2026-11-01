"""Minimal Model Context Protocol (MCP) implementation.

Implements the MCP JSON-RPC 2.0 methods used by agents:
``initialize``, ``tools/list`` and ``tools/call`` - served over Streamable
HTTP (POST /mcp) or invoked in-process. Each server is a separate unit that
can be deployed independently (see ``python -m banking_agent.mcp.serve``).

Security: callers must present the shared service secret and the
authenticated customer context (``X-Customer-Id``) which is injected by the
platform - never chosen by the LLM - so servers enforce data ownership as
defence-in-depth.
"""
from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import FastAPI, Header, HTTPException, Request

from ..config import settings

PROTOCOL_VERSION = "2025-06-18"


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    fn: Callable[..., Any]
    is_write: bool = False

    def spec(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": {"readOnlyHint": not self.is_write, "destructiveHint": False},
        }


class ToolError(Exception):
    pass


class MCPServer:
    def __init__(self, name: str, version: str = "1.0.0") -> None:
        self.name = name
        self.version = version
        self.tools: dict[str, Tool] = {}

    def tool(self, description: str, schema: dict, is_write: bool = False):
        def deco(fn):
            self.tools[fn.__name__] = Tool(fn.__name__, description, {"type": "object", **schema}, fn, is_write)
            return fn

        return deco

    # ---- JSON-RPC dispatch ----
    async def handle(self, req: dict, customer_id: str | None) -> dict:
        rid, method, params = req.get("id"), req.get("method"), req.get("params") or {}
        try:
            if method == "initialize":
                result = {
                    "protocolVersion": PROTOCOL_VERSION,
                    "serverInfo": {"name": self.name, "version": self.version},
                    "capabilities": {"tools": {"listChanged": False}},
                }
            elif method == "tools/list":
                result = {"tools": [t.spec() for t in self.tools.values()]}
            elif method == "tools/call":
                result = await self._call(params.get("name"), params.get("arguments") or {}, customer_id)
            else:
                return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Unknown method {method}"}}
        except Exception as exc:  # noqa: BLE001
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32603, "message": str(exc)}}
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    async def _call(self, name: str, args: dict, customer_id: str | None) -> dict:
        tool = self.tools.get(name)
        if tool is None:
            raise ToolError(f"Unknown tool {name}")
        if not customer_id:
            raise ToolError("Missing customer context")
        _validate(tool.input_schema, args)
        try:
            out = tool.fn(customer_id=customer_id, **args)
            if inspect.isawaitable(out):
                out = await out
            return {"content": [{"type": "text", "text": json.dumps(out, default=str)}],
                    "structuredContent": out, "isError": False}
        except ToolError as exc:
            return {"content": [{"type": "text", "text": str(exc)}], "isError": True}

    # ---- network transport ----
    def asgi_app(self) -> FastAPI:
        app = FastAPI(title=f"MCP: {self.name}")

        @app.post("/mcp")
        async def mcp_endpoint(
            request: Request,
            x_mcp_secret: str = Header(default=""),
            x_customer_id: str | None = Header(default=None),
        ):
            if x_mcp_secret != settings.mcp_shared_secret:
                raise HTTPException(401, "Invalid MCP credentials")
            return await self.handle(await request.json(), x_customer_id)

        @app.get("/health")
        async def health():
            return {"server": self.name, "tools": list(self.tools)}

        return app


def _validate(schema: dict, args: dict) -> None:
    props = schema.get("properties", {})
    for req in schema.get("required", []):
        if req not in args or args[req] in (None, ""):
            raise ToolError(f"Missing required argument '{req}'")
    for k, v in list(args.items()):
        if k not in props:
            raise ToolError(f"Unexpected argument '{k}'")
        t = props[k].get("type")
        if t == "integer":
            try:
                args[k] = int(v)
            except (TypeError, ValueError) as exc:
                raise ToolError(f"Argument '{k}' must be an integer") from exc
        elif t == "string" and not isinstance(v, str):
            args[k] = str(v)
        if "enum" in props[k] and args[k] not in props[k]["enum"]:
            raise ToolError(f"Argument '{k}' must be one of {props[k]['enum']}")
        if "maxLength" in props[k] and len(str(args[k])) > props[k]["maxLength"]:
            raise ToolError(f"Argument '{k}' too long")
