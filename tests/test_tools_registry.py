"""Tests for the tools registry — ALL_TOOLS completeness and dispatch routing."""

import pytest
from collections import Counter
from unittest.mock import patch

import tools
from tools import account, instruments, orders, history


# ---------------------------------------------------------------------------
# Registry integrity
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_total_tool_count(self):
        assert len(tools.ALL_TOOLS) == 16

    def test_no_duplicate_names(self):
        names = [t.name for t in tools.ALL_TOOLS]
        dupes = [n for n, c in Counter(names).items() if c > 1]
        assert dupes == [], f"Duplicate tool names: {dupes}"

    def test_all_tools_have_name_and_schema(self):
        for t in tools.ALL_TOOLS:
            assert t.name, "Tool missing name"
            assert t.inputSchema, f"Tool {t.name} missing inputSchema"

    def test_tool_names_sets_match_tools(self):
        for mod in [account, instruments, orders, history]:
            declared = {t.name for t in mod.TOOLS}
            assert mod.TOOL_NAMES == declared, f"{mod.__name__}: TOOL_NAMES mismatch"

    def test_dispatch_raises_for_unknown(self):
        with pytest.raises(ValueError, match="Unknown tool"):
            tools.dispatch("nonexistent_tool", {})

    @pytest.mark.parametrize("tool", tools.ALL_TOOLS)
    def test_required_fields_are_in_properties(self, tool):
        schema = tool.inputSchema
        required = schema.get("required", [])
        props = schema.get("properties", {})
        missing = [f for f in required if f not in props]
        assert not missing, f"{tool.name}: required fields not in properties: {missing}"


# ---------------------------------------------------------------------------
# Module tool counts
# ---------------------------------------------------------------------------

class TestModuleCounts:
    def test_account(self):     assert len(account.TOOLS) == 2
    def test_instruments(self): assert len(instruments.TOOLS) == 2
    def test_orders(self):      assert len(orders.TOOLS) == 7
    def test_history(self):     assert len(history.TOOLS) == 5


# ---------------------------------------------------------------------------
# Dispatch routing — verify each tool maps to the right method + path
# ---------------------------------------------------------------------------

class TestDispatchRouting:
    def test_get_account_summary(self):
        with patch("tools.account.api") as m:
            tools.dispatch("get_account_summary", {})
            m.assert_called_once_with("GET", "/equity/account/summary")

    def test_get_positions(self):
        with patch("tools.account.api") as m:
            tools.dispatch("get_positions", {})
            m.assert_called_once_with("GET", "/equity/positions")

    def test_place_market_order_body(self):
        with patch("tools.orders.api") as m:
            tools.dispatch("place_market_order", {"ticker": "AAPL_US_EQ", "quantity": -2})
            m.assert_called_once_with(
                "POST", "/equity/orders/market",
                body={"ticker": "AAPL_US_EQ", "quantity": -2},
            )

    def test_cancel_order_path(self):
        with patch("tools.orders.api") as m:
            tools.dispatch("cancel_order", {"id": 42})
            m.assert_called_once_with("DELETE", "/equity/orders/42")

    def test_list_instruments_params(self):
        with patch("tools.instruments.api") as m:
            tools.dispatch("list_instruments", {"limit": 50, "cursor": None})
            m.assert_called_once_with("GET", "/equity/metadata/instruments", params={"limit": 50})

    def test_request_export_builds_data_included(self):
        with patch("tools.history.api") as m:
            tools.dispatch("request_export", {
                "timeFrom": "2024-01-01T00:00:00Z",
                "timeTo": "2024-12-31T00:00:00Z",
                "includeOrders": False,
            })
            _, kwargs = m.call_args
            body = kwargs["body"]
            assert body["timeFrom"] == "2024-01-01T00:00:00Z"
            assert body["dataIncluded"]["includeOrders"] is False
            assert body["dataIncluded"]["includeDividends"] is True
