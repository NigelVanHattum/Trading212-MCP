"""
Account data

Endpoints:
  GET /api/v0/equity/account/summary   — cash & investment metrics
  GET /api/v0/equity/positions         — open positions, optionally one ticker
"""

from typing import Any
import mcp.types as types
from client import api, omit

TOOLS = [
    types.Tool(
        name="get_account_summary",
        description=(
            "Get a breakdown of the account's cash and investment metrics "
            "(free funds, invested capital, current value, P/L). Rate limit 1 req/5s."
        ),
        input_schema={
            "type": "object",
            "properties": {},
        },
    ),
    types.Tool(
        name="get_positions",
        description=(
            "Fetch open positions for the account, with quantity, average price, "
            "current price and profit/loss. Pass a ticker to fetch a single "
            "position instead of the whole portfolio. Rate limit 1 req/1s."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": (
                        "Optional Trading 212 instrument ID, e.g. AAPL_US_EQ. "
                        "Omit to return every open position."
                    ),
                },
            },
        },
    ),
]

TOOL_NAMES = {t.name for t in TOOLS}


def dispatch(name: str, a: dict) -> Any:
    if name == "get_account_summary":
        return api("GET", "/equity/account/summary")

    elif name == "get_positions":
        return api("GET", "/equity/positions", params=omit(a))
