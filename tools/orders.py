"""
Equity orders

Endpoints:
  GET    /api/v0/equity/orders              — list active orders
  GET    /api/v0/equity/orders/{id}         — get a specific order
  DELETE /api/v0/equity/orders/{id}         — cancel an order
  POST   /api/v0/equity/orders/market       — place a market order
  POST   /api/v0/equity/orders/limit        — place a limit order
  POST   /api/v0/equity/orders/stop         — place a stop order
  POST   /api/v0/equity/orders/stop_limit   — place a stop-limit order

Convention: a positive quantity buys, a negative quantity sells (e.g. -10.5).
Orders execute only in the account's main currency.
"""

from typing import Any
import mcp.types as types
from client import api, omit

TOOLS = [
    types.Tool(
        name="list_orders",
        description="List all active (pending) orders. Rate limit 1 req/5s.",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    types.Tool(
        name="get_order",
        description="Get a specific pending order by its ID. Rate limit 1 req/1s.",
        inputSchema={
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "Order ID"},
            },
            "required": ["id"],
        },
    ),
    types.Tool(
        name="cancel_order",
        description="Cancel a pending order by its ID. Rate limit 50 req/min.",
        inputSchema={
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "Order ID"},
            },
            "required": ["id"],
        },
    ),
    types.Tool(
        name="place_market_order",
        description=(
            "Place a market order for immediate execution. Positive quantity buys, "
            "negative sells. Subject to price slippage. Rate limit 50 req/min."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "ticker":        {"type": "string",  "description": "Instrument ticker, e.g. AAPL_US_EQ"},
                "quantity":      {"type": "number",  "description": "Share quantity; positive = buy, negative = sell"},
                "extendedHours": {"type": "boolean", "description": "Allow execution during extended trading hours"},
            },
            "required": ["ticker", "quantity"],
        },
    ),
    types.Tool(
        name="place_limit_order",
        description=(
            "Place a limit order that executes at limitPrice or better. Positive "
            "quantity buys, negative sells. Rate limit 1 req/2s."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "ticker":       {"type": "string", "description": "Instrument ticker, e.g. AAPL_US_EQ"},
                "quantity":     {"type": "number", "description": "Share quantity; positive = buy, negative = sell"},
                "limitPrice":   {"type": "number", "description": "Limit price"},
                "timeValidity": {"type": "string", "enum": ["DAY", "GOOD_TILL_CANCEL"], "description": "Order time validity"},
            },
            "required": ["ticker", "quantity", "limitPrice"],
        },
    ),
    types.Tool(
        name="place_stop_order",
        description=(
            "Place a stop order, triggered into a market order when the Last Traded "
            "Price reaches stopPrice. Rate limit 1 req/2s."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "ticker":       {"type": "string", "description": "Instrument ticker, e.g. AAPL_US_EQ"},
                "quantity":     {"type": "number", "description": "Share quantity; positive = buy, negative = sell"},
                "stopPrice":    {"type": "number", "description": "Trigger price"},
                "timeValidity": {"type": "string", "enum": ["DAY", "GOOD_TILL_CANCEL"], "description": "Order time validity"},
            },
            "required": ["ticker", "quantity", "stopPrice"],
        },
    ),
    types.Tool(
        name="place_stop_limit_order",
        description=(
            "Place a stop-limit order: triggers at stopPrice, then places a limit "
            "order at limitPrice. Rate limit 1 req/2s."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "ticker":       {"type": "string", "description": "Instrument ticker, e.g. AAPL_US_EQ"},
                "quantity":     {"type": "number", "description": "Share quantity; positive = buy, negative = sell"},
                "stopPrice":    {"type": "number", "description": "Trigger price"},
                "limitPrice":   {"type": "number", "description": "Limit price applied after trigger"},
                "timeValidity": {"type": "string", "enum": ["DAY", "GOOD_TILL_CANCEL"], "description": "Order time validity"},
            },
            "required": ["ticker", "quantity", "stopPrice", "limitPrice"],
        },
    ),
]

TOOL_NAMES = {t.name for t in TOOLS}


def dispatch(name: str, a: dict) -> Any:
    if name == "list_orders":
        return api("GET", "/equity/orders")

    elif name == "get_order":
        return api("GET", f"/equity/orders/{a['id']}")

    elif name == "cancel_order":
        return api("DELETE", f"/equity/orders/{a['id']}")

    elif name == "place_market_order":
        return api("POST", "/equity/orders/market", body=omit(a))

    elif name == "place_limit_order":
        return api("POST", "/equity/orders/limit", body=omit(a))

    elif name == "place_stop_order":
        return api("POST", "/equity/orders/stop", body=omit(a))

    elif name == "place_stop_limit_order":
        return api("POST", "/equity/orders/stop_limit", body=omit(a))
