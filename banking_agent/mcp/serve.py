"""Run each MCP server as its own microservice.

    python -m banking_agent.mcp.serve accounts      # :8101
    python -m banking_agent.mcp.serve transactions  # :8102
    python -m banking_agent.mcp.serve service       # :8103

Then set ACCOUNTS_MCP_URL=http://localhost:8101 etc. for the main API.
"""
import sys

import uvicorn

from . import accounts_server, service_server, transactions_server

SERVERS = {
    "accounts": (accounts_server.server, 8101),
    "transactions": (transactions_server.server, 8102),
    "service": (service_server.server, 8103),
}

if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "accounts"
    srv, port = SERVERS[name]
    uvicorn.run(srv.asgi_app(), host="127.0.0.1", port=port)
