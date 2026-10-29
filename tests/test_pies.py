"""PIE tools — the PieRequest body and the allocation checks around it.

The API takes every PieRequest field at the top level of the body. Sending a
name on its own comes back as 400 "instrumentShares is required", and tucking
the allocation inside another object as 400 "Invalid payload", so these tests
pin the shape rather than trusting the schema to stay right.
"""

import pytest
from unittest.mock import patch

import tools
from tools import pies

TOOLS_BY_NAME = {t.name: t for t in pies.TOOLS}

PIE_REQUEST_FIELDS = {
    "name", "instrumentShares", "icon", "dividendCashAction", "goal", "endDate",
}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class TestPieRequestSchema:
    @pytest.mark.parametrize("tool_name", ["create_pie", "update_pie"])
    def test_exposes_every_pie_request_field(self, tool_name):
        props = set(TOOLS_BY_NAME[tool_name].input_schema["properties"])
        assert PIE_REQUEST_FIELDS <= props

    def test_create_takes_no_other_fields(self):
        props = set(TOOLS_BY_NAME["create_pie"].input_schema["properties"])
        assert props == PIE_REQUEST_FIELDS

    def test_update_takes_the_pie_id_and_nothing_else_extra(self):
        props = set(TOOLS_BY_NAME["update_pie"].input_schema["properties"])
        assert props == PIE_REQUEST_FIELDS | {"id"}

    @pytest.mark.parametrize("tool_name", ["create_pie", "update_pie"])
    def test_allocation_is_required(self, tool_name):
        """The scheduled sync waits on this before it writes anything."""
        required = TOOLS_BY_NAME[tool_name].input_schema["required"]
        assert "instrumentShares" in required

    @pytest.mark.parametrize("tool_name", ["create_pie", "update_pie"])
    def test_allocation_is_a_ticker_to_number_map(self, tool_name):
        prop = TOOLS_BY_NAME[tool_name].input_schema["properties"]["instrumentShares"]
        assert prop["type"] == "object"
        assert prop["additionalProperties"] == {"type": "number"}

    @pytest.mark.parametrize("tool_name", ["create_pie", "update_pie"])
    def test_dividend_action_is_constrained(self, tool_name):
        prop = TOOLS_BY_NAME[tool_name].input_schema["properties"]["dividendCashAction"]
        assert prop["enum"] == ["REINVEST", "TO_ACCOUNT_CASH"]

    def test_the_goals_object_is_gone(self):
        """`goals` was never a PieRequest field; the spec has a numeric `goal`."""
        props = TOOLS_BY_NAME["update_pie"].input_schema["properties"]
        assert "goals" not in props
        assert props["goal"]["type"] == "number"

    def test_initial_amount_is_gone(self):
        """Not a PieRequest field either — the create endpoint ignores it."""
        assert "initialAmountInvestmentCurrency" not in (
            TOOLS_BY_NAME["create_pie"].input_schema["properties"]
        )

    def test_update_warns_that_the_body_replaces_settings(self):
        assert "get_pie" in TOOLS_BY_NAME["update_pie"].description


# ---------------------------------------------------------------------------
# Body construction
# ---------------------------------------------------------------------------

HALF_AND_HALF = {"AAPL_US_EQ": 0.5, "MSFT_US_EQ": 0.5}


class TestUpdateBody:
    def test_allocation_goes_to_the_top_level(self):
        with patch("tools.pies.api") as m:
            tools.dispatch("update_pie", {"id": 10171983, "instrumentShares": HALF_AND_HALF})
            body = m.call_args.kwargs["body"]
            assert body == {"instrumentShares": HALF_AND_HALF}

    def test_every_field_goes_to_the_top_level(self):
        with patch("tools.pies.api") as m:
            tools.dispatch("update_pie", {
                "id": 10171983,
                "name": "Fundamental Pie",
                "instrumentShares": HALF_AND_HALF,
                "icon": "Fire",
                "dividendCashAction": "REINVEST",
                "goal": 25000,
                "endDate": "2030-01-01T00:00:00Z",
            })
            m.assert_called_once_with(
                "POST", "/equity/pies/10171983",
                body={
                    "name": "Fundamental Pie",
                    "instrumentShares": HALF_AND_HALF,
                    "icon": "Fire",
                    "dividendCashAction": "REINVEST",
                    "goal": 25000,
                    "endDate": "2030-01-01T00:00:00Z",
                },
            )

    def test_the_id_stays_in_the_path(self):
        with patch("tools.pies.api") as m:
            tools.dispatch("update_pie", {"id": 10171983, "instrumentShares": HALF_AND_HALF})
            args, kwargs = m.call_args
            assert args == ("POST", "/equity/pies/10171983")
            assert "id" not in kwargs["body"]

    def test_the_arguments_are_left_alone(self):
        """Dispatch reads the id out of the body rather than popping it."""
        a = {"id": 10171983, "instrumentShares": HALF_AND_HALF}
        with patch("tools.pies.api"):
            tools.dispatch("update_pie", a)
        assert a["id"] == 10171983

    def test_unset_fields_are_dropped(self):
        with patch("tools.pies.api") as m:
            tools.dispatch("update_pie", {
                "id": 10171983,
                "instrumentShares": HALF_AND_HALF,
                "icon": None,
                "goal": None,
            })
            assert m.call_args.kwargs["body"] == {"instrumentShares": HALF_AND_HALF}


class TestCreateBody:
    def test_every_field_goes_to_the_top_level(self):
        with patch("tools.pies.api") as m:
            tools.dispatch("create_pie", {
                "name": "Fundamental Pie",
                "instrumentShares": HALF_AND_HALF,
                "icon": "Fire",
                "dividendCashAction": "TO_ACCOUNT_CASH",
                "goal": 25000,
                "endDate": "2030-01-01T00:00:00Z",
            })
            m.assert_called_once_with(
                "POST", "/equity/pies",
                body={
                    "name": "Fundamental Pie",
                    "instrumentShares": HALF_AND_HALF,
                    "icon": "Fire",
                    "dividendCashAction": "TO_ACCOUNT_CASH",
                    "goal": 25000,
                    "endDate": "2030-01-01T00:00:00Z",
                },
            )


# ---------------------------------------------------------------------------
# Allocation checks — caught here rather than spent on a 400
# ---------------------------------------------------------------------------

class TestAllocationChecks:
    @pytest.mark.parametrize("tool_name,args", [
        ("create_pie", {"name": "Fundamental Pie"}),
        ("update_pie", {"id": 10171983, "name": "Fundamental Pie"}),
    ])
    def test_missing_allocation_is_refused(self, tool_name, args):
        with patch("tools.pies.api") as m:
            with pytest.raises(ValueError, match="instrumentShares is required"):
                tools.dispatch(tool_name, args)
        m.assert_not_called()

    @pytest.mark.parametrize("shares", [{}, [], "AAPL_US_EQ", None])
    def test_an_allocation_that_is_not_a_map_is_refused(self, shares):
        with pytest.raises(ValueError, match="instrumentShares is required"):
            tools.dispatch("update_pie", {"id": 10171983, "instrumentShares": shares})

    def test_an_allocation_that_does_not_add_up_is_refused(self):
        with pytest.raises(ValueError, match="must sum to 1"):
            tools.dispatch("update_pie", {
                "id": 10171983,
                "instrumentShares": {"AAPL_US_EQ": 0.5, "MSFT_US_EQ": 0.3},
            })

    @pytest.mark.parametrize("value", [0, -0.5, "0.5", True])
    def test_a_share_that_is_not_a_positive_number_is_refused(self, value):
        with pytest.raises(ValueError, match="positive numbers"):
            tools.dispatch("update_pie", {
                "id": 10171983,
                "instrumentShares": {"AAPL_US_EQ": value, "MSFT_US_EQ": 0.5},
            })

    def test_rounding_from_thirds_is_accepted(self):
        thirds = {"A_US_EQ": 0.333333, "B_US_EQ": 0.333333, "C_US_EQ": 0.333334}
        with patch("tools.pies.api") as m:
            tools.dispatch("update_pie", {"id": 10171983, "instrumentShares": thirds})
        m.assert_called_once()

    def test_a_single_instrument_at_full_weight_is_accepted(self):
        with patch("tools.pies.api") as m:
            tools.dispatch("update_pie", {"id": 10171983, "instrumentShares": {"AAPL_US_EQ": 1}})
        m.assert_called_once()

    def test_reads_are_not_checked(self):
        with patch("tools.pies.api") as m:
            tools.dispatch("get_pie", {"id": 10171983})
        m.assert_called_once_with("GET", "/equity/pies/10171983")


# ---------------------------------------------------------------------------
# Duplication — DuplicateBucketRequest is {name, icon}
# ---------------------------------------------------------------------------

class TestDuplicate:
    def test_the_copy_can_be_named(self):
        with patch("tools.pies.api") as m:
            tools.dispatch("duplicate_pie", {
                "id": 10171983, "name": "Fundamental Pie v2", "icon": "Fire",
            })
            m.assert_called_once_with(
                "POST", "/equity/pies/10171983/duplicate",
                body={"name": "Fundamental Pie v2", "icon": "Fire"},
            )

    def test_an_unnamed_copy_sends_an_empty_body(self):
        """Inherits the source's name and icon."""
        with patch("tools.pies.api") as m:
            tools.dispatch("duplicate_pie", {"id": 10171983})
            m.assert_called_once_with("POST", "/equity/pies/10171983/duplicate", body={})

    def test_nothing_else_is_forwarded(self):
        with patch("tools.pies.api") as m:
            tools.dispatch("duplicate_pie", {
                "id": 10171983,
                "name": "Fundamental Pie v2",
                "instrumentShares": {"AAPL_US_EQ": 1.0},
                "goal": 25000,
            })
            assert m.call_args.kwargs["body"] == {"name": "Fundamental Pie v2"}

    def test_the_schema_offers_both_and_requires_neither(self):
        schema = TOOLS_BY_NAME["duplicate_pie"].input_schema
        assert set(schema["properties"]) == {"id", "name", "icon"}
        assert schema["required"] == ["id"]


# ---------------------------------------------------------------------------
# Upstream deprecation
# ---------------------------------------------------------------------------

class TestDeprecationNote:
    @pytest.mark.parametrize("tool", pies.TOOLS, ids=lambda t: t.name)
    def test_every_pie_tool_says_so(self, tool):
        """The spec marks all six endpoints deprecated."""
        assert tool.description.endswith(pies.DEPRECATION_NOTE)
