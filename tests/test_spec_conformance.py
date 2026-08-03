"""Tool schemas checked against the Trading 212 OpenAPI spec.

The parameters below are transcribed from https://docs.trading212.com/_bundle/api.yaml
(openapi 3.0.1, version v0). Three drifts had crept in unnoticed — a filter the
API offers but no tool exposed, a filter missing entirely, and a cursor typed as
a string where the spec says integer — so the expectations live here explicitly
rather than being re-derived from the code they are meant to check.

list_instruments is deliberately absent: its endpoint takes no parameters at
all, and its schema describes a client-side search instead. See tools/instruments.py.
"""

import pytest

import tools

# tool name -> {query parameter: JSON Schema type}, per the spec
SPEC_QUERY_PARAMS = {
    "get_account_summary":   {},
    "get_positions":         {"ticker": "string"},
    "list_exchanges":        {},
    "list_orders":           {},
    "get_historical_orders": {"cursor": "integer", "ticker": "string", "limit": "integer"},
    "get_dividends":         {"cursor": "integer", "ticker": "string", "limit": "integer"},
    "get_transactions":      {"cursor": "string",  "time": "string",   "limit": "integer"},
    "list_exports":          {},
}

TOOLS_BY_NAME = {t.name: t for t in tools.ALL_TOOLS}


@pytest.mark.parametrize("tool_name,expected", SPEC_QUERY_PARAMS.items())
def test_schema_matches_spec_parameters(tool_name, expected):
    props = TOOLS_BY_NAME[tool_name].input_schema.get("properties", {})
    assert set(props) == set(expected), f"{tool_name}: parameter set differs from the spec"
    for param, json_type in expected.items():
        assert props[param]["type"] == json_type, f"{tool_name}.{param}: wrong type"


class TestCursorTypes:
    """The three list endpoints do not agree on the cursor type."""

    @pytest.mark.parametrize("tool_name", ["get_historical_orders", "get_dividends"])
    def test_numeric_cursor(self, tool_name):
        assert TOOLS_BY_NAME[tool_name].input_schema["properties"]["cursor"]["type"] == "integer"

    def test_transactions_cursor_is_a_string(self):
        props = TOOLS_BY_NAME["get_transactions"].input_schema["properties"]
        assert props["cursor"]["type"] == "string"


class TestPositionsFilter:
    def test_ticker_is_optional(self):
        schema = TOOLS_BY_NAME["get_positions"].input_schema
        assert schema.get("required", []) == []

    def test_ticker_documented_with_an_example(self):
        prop = TOOLS_BY_NAME["get_positions"].input_schema["properties"]["ticker"]
        assert "AAPL_US_EQ" in prop["description"]
