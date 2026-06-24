"""Tool modules for the Trading 212 MCP server."""

from . import (
    account,
    instruments,
    orders,
    history,
)

_MODULES = [
    account,
    instruments,
    orders,
    history,
]

# Aggregated tool list for MCP registration
ALL_TOOLS = [tool for mod in _MODULES for tool in mod.TOOLS]


def dispatch(name: str, args: dict):
    """Route tool call to the correct module dispatcher."""
    for mod in _MODULES:
        if name in mod.TOOL_NAMES:
            return mod.dispatch(name, args)
    raise ValueError(f"Unknown tool: {name}")
