"""
Instruments metadata

Endpoints:
  GET /api/v0/equity/metadata/exchanges    — accessible exchanges & schedules
  GET /api/v0/equity/metadata/instruments  — all tradable instruments

Both are cursor-paginated (limit default 20, max 50) and the data refreshes
roughly every 10 minutes.
"""

from typing import Any
import mcp.types as types
from client import api, omit

TOOLS = [
    types.Tool(
        name="list_exchanges",
        description=(
            "List all accessible exchanges and their working schedules. "
            "Rate limit 1 req/30s."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "limit":  {"type": "integer", "description": "Page size (default 20, max 50)"},
                "cursor": {"type": "string",  "description": "Pagination cursor from a previous page"},
            },
        },
    ),
    types.Tool(
        name="list_instruments",
        description=(
            "List all tradable instruments and their details (ticker, name, type, "
            "currencyCode, isin). Tickers look like 'AAPL_US_EQ'. Rate limit 1 req/50s."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "limit":  {"type": "integer", "description": "Page size (default 20, max 50)"},
                "cursor": {"type": "string",  "description": "Pagination cursor from a previous page"},
            },
        },
    ),
]

TOOL_NAMES = {t.name for t in TOOLS}


def dispatch(name: str, a: dict) -> Any:
    if name == "list_exchanges":
        return api("GET", "/equity/metadata/exchanges", params=omit(a))

    elif name == "list_instruments":
        return api("GET", "/equity/metadata/instruments", params=omit(a))
