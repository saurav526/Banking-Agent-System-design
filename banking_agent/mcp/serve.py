"""
MCP Microservices Runner Module
===============================

Provides the standalone CLI entry point to run individual Model Context Protocol
(MCP) domain servers as isolated HTTP microservices via Uvicorn.

Service Topology & Default Port Mapping:
----------------------------------------
- accounts      -> :8101 (accounts_server.server)
- transactions  -> :8102 (transactions_server.server)
- service       -> :8103 (service_server.server)

Execution:
----------
Run an individual server directly from the command line:
    $ python -m banking_agent.mcp.serve accounts      # Port 8101
    $ python -m banking_agent.mcp.serve transactions  # Port 8102
    $ python -m banking_agent.mcp.serve service       # Port 8103

When running as standalone services, configure downstream agents or the core API
using environment variables pointing to their respective URLs (e.g.,
`ACCOUNTS_MCP_URL=http://localhost:8101`).
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
