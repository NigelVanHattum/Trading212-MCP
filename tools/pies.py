"""
PIE (Portfolio Investment Engine) management

PIEs are automated portfolio builders/allocators. Endpoints allow creating,
managing, and duplicating PIE portfolios.

Endpoints:
  GET    /api/v0/equity/pies                  — list all account PIEs
  POST   /api/v0/equity/pies                  — create a new PIE
  GET    /api/v0/equity/pies/{id}             — get a specific PIE
  POST   /api/v0/equity/pies/{id}             — update a PIE
  DELETE /api/v0/equity/pies/{id}             — delete a PIE
  POST   /api/v0/equity/pies/{id}/duplicate   — duplicate a PIE

The spec marks all six endpoints deprecated: they still work, and there is no
replacement yet, but they will not be developed further.

Create and update both take a PieRequest body whose fields all sit at the top
level — instrumentShares above all, which the API rejects the request without.
The allocation is a ticker -> fraction map and the fractions have to add up
to 1. Neither endpoint patches: the body replaces the PIE's settings, so read
the PIE with get_pie first and resend whatever you mean to keep.
"""

from typing import Any
import mcp.types as types
from client import api, omit

# Appended to every tool below: the spec marks the whole Pies API deprecated,
# which callers should know before they build on it.
DEPRECATION_NOTE = (
    " Note: Trading 212 has deprecated the Pies API — still operational, "
    "no further updates."
)

# Allocations are usually percentages divided by 100, so leave room for the
# rounding that comes out of that rather than demanding an exact 1.
SHARE_SUM_TOLERANCE = 1e-6

# The PieRequest body, shared by create_pie and update_pie.
PIE_REQUEST_PROPERTIES = {
    "name": {
        "type": "string",
        "description": "PIE name/label",
    },
    "instrumentShares": {
        "type": "object",
        "description": (
            "Allocation as a ticker -> fraction map, e.g. "
            '{"AAPL_US_EQ": 0.5, "MSFT_US_EQ": 0.5}. Fractions must add up to 1.'
        ),
        "additionalProperties": {"type": "number"},
    },
    "icon": {
        "type": "string",
        "description": "Icon name shown next to the PIE in the Trading 212 app",
    },
    "dividendCashAction": {
        "type": "string",
        "enum": ["REINVEST", "TO_ACCOUNT_CASH"],
        "description": "What to do with dividends the PIE's holdings pay out",
    },
    "goal": {
        "type": "number",
        "description": "Total desired value of the PIE, in account currency",
    },
    "endDate": {
        "type": "string",
        "description": "Date the goal is aimed at, ISO 8601, e.g. 2030-01-01T00:00:00Z",
    },
}

TOOLS = [
    types.Tool(
        name="list_pies",
        description=(
            "List all PIE portfolios in the account. Returns details for each PIE "
            "including name, allocation, and current value. Rate limit 1 req/30s."
        ) + DEPRECATION_NOTE,
        input_schema={
            "type": "object",
            "properties": {},
        },
    ),
    types.Tool(
        name="create_pie",
        description=(
            "Create a new PIE portfolio. instrumentShares carries the allocation as "
            "a ticker -> fraction map adding up to 1; the API rejects the request "
            "without it. Returns the newly created PIE object with its ID. "
            "Rate limit 1 req/5s."
        ) + DEPRECATION_NOTE,
        input_schema={
            "type": "object",
            "properties": dict(PIE_REQUEST_PROPERTIES),
            "required": ["name", "instrumentShares"],
        },
    ),
    types.Tool(
        name="get_pie",
        description=(
            "Get details of a specific PIE portfolio by ID. Returns allocation, "
            "composition, and performance metrics. Rate limit 1 req/5s."
        ) + DEPRECATION_NOTE,
        input_schema={
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "PIE portfolio ID",
                },
            },
            "required": ["id"],
        },
    ),
    types.Tool(
        name="update_pie",
        description=(
            "Update a PIE portfolio's settings and allocation. instrumentShares is "
            "the allocation as a ticker -> fraction map adding up to 1, and the API "
            "rejects the request without it. The body replaces the PIE's settings "
            "rather than patching them, so read the PIE with get_pie first and "
            "resend the name, icon, dividendCashAction, goal and endDate you want "
            "to keep. Rate limit 1 req/5s."
        ) + DEPRECATION_NOTE,
        input_schema={
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "PIE portfolio ID",
                },
                **PIE_REQUEST_PROPERTIES,
            },
            "required": ["id", "instrumentShares"],
        },
    ),
    types.Tool(
        name="delete_pie",
        description=(
            "Delete a PIE portfolio from the account. The portfolio must be fully "
            "liquidated (no positions) before deletion. Rate limit 1 req/5s."
        ) + DEPRECATION_NOTE,
        input_schema={
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "PIE portfolio ID to delete",
                },
            },
            "required": ["id"],
        },
    ),
    types.Tool(
        name="duplicate_pie",
        description=(
            "Create a duplicate copy of an existing PIE portfolio with all its "
            "allocations and settings. Give the copy its own name and icon, or "
            "leave them off to inherit the source's. Rate limit 1 req/5s."
        ) + DEPRECATION_NOTE,
        input_schema={
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Source PIE portfolio ID to duplicate",
                },
                "name": {
                    "type": "string",
                    "description": "Name for the copy; inherits the source's when left off",
                },
                "icon": {
                    "type": "string",
                    "description": "Icon for the copy; inherits the source's when left off",
                },
            },
            "required": ["id"],
        },
    ),
]

TOOL_NAMES = {t.name for t in TOOLS}


def _check_shares(a: dict) -> None:
    """Reject an allocation the API would only hand back as a 400."""
    shares = a.get("instrumentShares")
    if not isinstance(shares, dict) or not shares:
        raise ValueError(
            "instrumentShares is required: a non-empty ticker -> fraction map, "
            'e.g. {"AAPL_US_EQ": 0.5, "MSFT_US_EQ": 0.5}'
        )

    bad = sorted(
        t for t, s in shares.items()
        if isinstance(s, bool) or not isinstance(s, (int, float)) or s <= 0
    )
    if bad:
        raise ValueError(
            f"instrumentShares values must be positive numbers; bad tickers: {bad}"
        )

    total = sum(shares.values())
    if abs(total - 1) > SHARE_SUM_TOLERANCE:
        raise ValueError(f"instrumentShares must sum to 1, got {total}")


def dispatch(name: str, a: dict) -> Any:
    if name == "list_pies":
        return api("GET", "/equity/pies")

    elif name == "create_pie":
        _check_shares(a)
        return api("POST", "/equity/pies", body=omit(a))

    elif name == "get_pie":
        return api("GET", f"/equity/pies/{a['id']}")

    elif name == "update_pie":
        _check_shares(a)
        return api("POST", f"/equity/pies/{a['id']}", body=omit(a, "id"))

    elif name == "delete_pie":
        return api("DELETE", f"/equity/pies/{a['id']}")

    elif name == "duplicate_pie":
        # DuplicateBucketRequest takes name and icon, and nothing else.
        body = omit({"name": a.get("name"), "icon": a.get("icon")})
        return api("POST", f"/equity/pies/{a['id']}/duplicate", body=body)
