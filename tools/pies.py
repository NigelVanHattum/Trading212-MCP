"""
Pies management (DEPRECATED upstream)

Trading212 marks the Pies API as deprecated: it still works, but will not be
further supported or updated. Endpoints:

  GET    /api/v0/equity/pies                  — list all account pies
  POST   /api/v0/equity/pies                  — create a pie (PieRequest)
  GET    /api/v0/equity/pies/{id}             — get a specific pie
  POST   /api/v0/equity/pies/{id}             — update a pie (PieRequest)
  DELETE /api/v0/equity/pies/{id}             — delete a pie
  POST   /api/v0/equity/pies/{id}/duplicate   — duplicate a pie (DuplicateBucketRequest)
"""

from typing import Any
import mcp.types as types
from client import api, omit

DEPRECATED = " Note: the Trading212 Pies API is deprecated (still operational, no further updates)."

_ID = {
    "type": "integer",
    "description": "Pie ID (int64)",
}

# PieRequest fields, per the official Trading212 OpenAPI spec.
_PIE_FIELDS = {
    "name": {
        "type": "string",
        "description": "Pie name",
    },
    "instrumentShares": {
        "type": "object",
        "additionalProperties": {"type": "number"},
        "description": (
            "Target allocation: map of instrument ticker to weight, weights summing to 1. "
            'Example: {"AAPL_US_EQ": 0.5, "MSFT_US_EQ": 0.5}'
        ),
    },
    "dividendCashAction": {
        "type": "string",
        "enum": ["REINVEST", "TO_ACCOUNT_CASH"],
        "description": "What to do with dividends",
    },
    "goal": {
        "type": "number",
        "description": "Total desired value of the pie in account currency",
    },
    "endDate": {
        "type": "string",
        "format": "date-time",
        "description": "Target date for the goal (ISO 8601 date-time)",
    },
    "icon": {
        "type": "string",
        "description": "Pie icon identifier",
    },
}

TOOLS = [
    types.Tool(
        name="list_pies",
        description="List all pies in the account with cash, progress and result. Rate limit 1 req/30s." + DEPRECATED,
        input_schema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="create_pie",
        description=(
            "Create a new pie. Provide name and instrumentShares (ticker -> weight); optionally "
            "dividendCashAction, goal, endDate and icon. Rate limit 1 req/5s." + DEPRECATED
        ),
        input_schema={
            "type": "object",
            "properties": dict(_PIE_FIELDS),
            "required": ["name", "instrumentShares"],
        },
    ),
    types.Tool(
        name="get_pie",
        description="Get a pie by ID including instruments and settings. Rate limit 1 req/5s." + DEPRECATED,
        input_schema={
            "type": "object",
            "properties": {"id": _ID},
            "required": ["id"],
        },
    ),
    types.Tool(
        name="update_pie",
        description=(
            "Update a pie. Pass only the fields to change (name, instrumentShares, "
            "dividendCashAction, goal, endDate, icon). Rate limit 1 req/5s." + DEPRECATED
        ),
        input_schema={
            "type": "object",
            "properties": {"id": _ID, **_PIE_FIELDS},
            "required": ["id"],
        },
    ),
    types.Tool(
        name="delete_pie",
        description="Delete a pie by ID. Rate limit 1 req/5s." + DEPRECATED,
        input_schema={
            "type": "object",
            "properties": {"id": _ID},
            "required": ["id"],
        },
    ),
    types.Tool(
        name="duplicate_pie",
        description=(
            "Duplicate an existing pie, optionally with a new name and icon. Rate limit 1 req/5s."
            + DEPRECATED
        ),
        input_schema={
            "type": "object",
            "properties": {
                "id": _ID,
                "name": {"type": "string", "description": "Name for the duplicate (optional)"},
                "icon": {"type": "string", "description": "Icon for the duplicate (optional)"},
            },
            "required": ["id"],
        },
    ),
]

TOOL_NAMES = {t.name for t in TOOLS}

_PIE_KEYS = tuple(_PIE_FIELDS)


def _pick(a: dict, keys: tuple) -> dict:
    """Only forward known fields, dropping None values."""
    return omit({k: a.get(k) for k in keys})


def dispatch(name: str, a: dict) -> Any:
    if name == "list_pies":
        return api("GET", "/equity/pies")

    elif name == "create_pie":
        return api("POST", "/equity/pies", body=_pick(a, _PIE_KEYS))

    elif name == "get_pie":
        return api("GET", f"/equity/pies/{a['id']}")

    elif name == "update_pie":
        return api("POST", f"/equity/pies/{a['id']}", body=_pick(a, _PIE_KEYS))

    elif name == "delete_pie":
        return api("DELETE", f"/equity/pies/{a['id']}")

    elif name == "duplicate_pie":
        return api("POST", f"/equity/pies/{a['id']}/duplicate", body=_pick(a, ("name", "icon")))
