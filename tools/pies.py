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
"""

from typing import Any
import mcp.types as types
from client import api, omit

TOOLS = [
    types.Tool(
        name="list_pies",
        description=(
            "List all PIE portfolios in the account. Returns details for each PIE "
            "including name, allocation, and current value. Rate limit 1 req/5s."
        ),
        input_schema={
            "type": "object",
            "properties": {},
        },
    ),
    types.Tool(
        name="create_pie",
        description=(
            "Create a new PIE portfolio with specified settings. Returns the newly "
            "created PIE object with its ID. Rate limit 50 req/min."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "PIE name/label",
                },
                "initialAmountInvestmentCurrency": {
                    "type": "number",
                    "description": "Initial investment amount in account currency",
                },
            },
            "required": ["name"],
        },
    ),
    types.Tool(
        name="get_pie",
        description=(
            "Get details of a specific PIE portfolio by ID. Returns allocation, "
            "composition, and performance metrics. Rate limit 1 req/1s."
        ),
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
            "Update a PIE portfolio settings or allocation. Pass the fields to update. "
            "Rate limit 50 req/min."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "PIE portfolio ID",
                },
                "name": {
                    "type": "string",
                    "description": "New PIE name (optional)",
                },
                "goals": {
                    "type": "object",
                    "description": "Update investment goals (optional)",
                },
            },
            "required": ["id"],
        },
    ),
    types.Tool(
        name="delete_pie",
        description=(
            "Delete a PIE portfolio from the account. The portfolio must be fully "
            "liquidated (no positions) before deletion. Rate limit 50 req/min."
        ),
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
            "allocations and settings. Rate limit 50 req/min."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Source PIE portfolio ID to duplicate",
                },
            },
            "required": ["id"],
        },
    ),
]

TOOL_NAMES = {t.name for t in TOOLS}


def dispatch(name: str, a: dict) -> Any:
    if name == "list_pies":
        return api("GET", "/equity/pies")

    elif name == "create_pie":
        return api("POST", "/equity/pies", body=omit(a))

    elif name == "get_pie":
        return api("GET", f"/equity/pies/{a['id']}")

    elif name == "update_pie":
        pie_id = a.pop("id")
        return api("POST", f"/equity/pies/{pie_id}", body=omit(a))

    elif name == "delete_pie":
        return api("DELETE", f"/equity/pies/{a['id']}")

    elif name == "duplicate_pie":
        return api("POST", f"/equity/pies/{a['id']}/duplicate", body={})
