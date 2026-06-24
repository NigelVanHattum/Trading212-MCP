"""
Historical items

Endpoints:
  GET  /api/v0/equity/history/orders        — historical order records
  GET  /api/v0/equity/history/dividends     — paid dividends
  GET  /api/v0/equity/history/transactions  — cash movements to/from account
  GET  /api/v0/equity/history/exports       — list generated CSV reports
  POST /api/v0/equity/history/exports       — request a CSV export (async)

The list endpoints are cursor-paginated (limit default 20, max 50).
"""

from typing import Any
import mcp.types as types
from client import api, omit

_PAGING = {
    "limit":  {"type": "integer", "description": "Page size (default 20, max 50)"},
    "cursor": {"type": "string",  "description": "Pagination cursor from a previous page"},
}

TOOLS = [
    types.Tool(
        name="get_historical_orders",
        description="Access historical order records. Rate limit 6 req/min.",
        inputSchema={
            "type": "object",
            "properties": {
                **_PAGING,
                "ticker": {"type": "string", "description": "Optional ticker filter, e.g. AAPL_US_EQ"},
            },
        },
    ),
    types.Tool(
        name="get_dividends",
        description="Retrieve paid dividends. Rate limit 6 req/min.",
        inputSchema={
            "type": "object",
            "properties": {
                **_PAGING,
                "ticker": {"type": "string", "description": "Optional ticker filter, e.g. AAPL_US_EQ"},
            },
        },
    ),
    types.Tool(
        name="get_transactions",
        description=(
            "Fetch cash movements to and from the account (deposits, withdrawals, "
            "fees). Rate limit 6 req/min."
        ),
        inputSchema={
            "type": "object",
            "properties": dict(_PAGING),
        },
    ),
    types.Tool(
        name="list_exports",
        description="List requested CSV reports and their generation status. Rate limit 1 req/min.",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    types.Tool(
        name="request_export",
        description=(
            "Request a CSV export of historical account data over a time window. "
            "Asynchronous — returns a reportId; poll list_exports for the download "
            "link. Rate limit 1 req/30s."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "timeFrom": {"type": "string", "description": "Start of window, ISO-8601 e.g. 2024-01-01T00:00:00Z"},
                "timeTo":   {"type": "string", "description": "End of window, ISO-8601 e.g. 2024-12-31T00:00:00Z"},
                "includeDividends":    {"type": "boolean", "description": "Include dividends in the export (default true)"},
                "includeInterest":     {"type": "boolean", "description": "Include interest in the export (default true)"},
                "includeOrders":       {"type": "boolean", "description": "Include orders in the export (default true)"},
                "includeTransactions": {"type": "boolean", "description": "Include transactions in the export (default true)"},
            },
            "required": ["timeFrom", "timeTo"],
        },
    ),
]

TOOL_NAMES = {t.name for t in TOOLS}


def dispatch(name: str, a: dict) -> Any:
    if name == "get_historical_orders":
        return api("GET", "/equity/history/orders", params=omit(a))

    elif name == "get_dividends":
        return api("GET", "/equity/history/dividends", params=omit(a))

    elif name == "get_transactions":
        return api("GET", "/equity/history/transactions", params=omit(a))

    elif name == "list_exports":
        return api("GET", "/equity/history/exports")

    elif name == "request_export":
        body = {
            "timeFrom": a["timeFrom"],
            "timeTo": a["timeTo"],
            "dataIncluded": {
                "includeDividends":    a.get("includeDividends", True),
                "includeInterest":     a.get("includeInterest", True),
                "includeOrders":       a.get("includeOrders", True),
                "includeTransactions": a.get("includeTransactions", True),
            },
        }
        return api("POST", "/equity/history/exports", body=body)
