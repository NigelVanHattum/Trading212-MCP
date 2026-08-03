"""Tests for tools/instruments.py — catalogue search, ranking, caching."""

from unittest.mock import patch

import pytest

import tools
from tools import instruments

CATALOGUE = [
    {"ticker": "AAPL_US_EQ",  "name": "Apple",             "isin": "US0378331005", "type": "STOCK"},
    {"ticker": "AAPL_EQ",     "name": "Apple Inc",         "isin": "US0378331005", "type": "STOCK"},
    {"ticker": "AAPLl_EQ",    "name": "Apple CFD",         "isin": "US0378331005", "type": "CVR"},
    {"ticker": "MSFT_US_EQ",  "name": "Microsoft",         "isin": "US5949181045", "type": "STOCK"},
    {"ticker": "PINEAPPLE_EQ", "name": "Pineapple Energy", "isin": "US7231411057", "type": "STOCK"},
    {"ticker": "VUSA_EQ",     "name": "Vanguard S&P 500",  "isin": "IE00B3XXRP09", "type": "ETF"},
    {"ticker": "BTC_EQ",      "name": "Bitcoin",           "isin": "",             "type": "CRYPTOCURRENCY"},
]


@pytest.fixture(autouse=True)
def clear_cache():
    instruments._cache.update(fetched_at=0.0, items=None)
    yield
    instruments._cache.update(fetched_at=0.0, items=None)


def ids(result):
    return [i["ticker"] for i in result["instruments"]]


# ---------------------------------------------------------------------------
# search() — Trading 212 ID
# ---------------------------------------------------------------------------

class TestSearchById:
    def test_exact_match_ranks_first(self):
        result = instruments.search(CATALOGUE, trading212_id="AAPL_EQ")
        assert ids(result)[0] == "AAPL_EQ"

    def test_prefix_matches_all_listings(self):
        result = instruments.search(CATALOGUE, trading212_id="AAPL")
        assert ids(result) == ["AAPL_EQ", "AAPL_US_EQ", "AAPLl_EQ"]

    def test_exact_outranks_prefix(self):
        result = instruments.search(CATALOGUE, trading212_id="AAPLl_EQ")
        assert ids(result)[0] == "AAPLl_EQ"

    def test_substring_ranks_last(self):
        catalogue = CATALOGUE + [{"ticker": "XAAPL_EQ", "name": "Contains", "isin": "", "type": "STOCK"}]
        assert ids(instruments.search(catalogue, trading212_id="AAPL"))[-1] == "XAAPL_EQ"

    def test_case_insensitive(self):
        assert ids(instruments.search(CATALOGUE, trading212_id="aapl_us_eq")) == ["AAPL_US_EQ"]

    def test_whitespace_trimmed(self):
        assert ids(instruments.search(CATALOGUE, trading212_id="  MSFT_US_EQ ")) == ["MSFT_US_EQ"]

    def test_no_match_is_empty(self):
        result = instruments.search(CATALOGUE, trading212_id="NOPE")
        assert result["total"] == 0 and result["instruments"] == []


# ---------------------------------------------------------------------------
# search() — ISIN, name, type
# ---------------------------------------------------------------------------

class TestSearchByField:
    def test_isin_matches_every_listing(self):
        result = instruments.search(CATALOGUE, isin="US0378331005")
        assert result["total"] == 3

    def test_isin_is_case_insensitive(self):
        assert instruments.search(CATALOGUE, isin="ie00b3xxrp09")["total"] == 1

    def test_isin_is_exact_not_partial(self):
        assert instruments.search(CATALOGUE, isin="US03783")["total"] == 0

    def test_name_substring(self):
        assert ids(instruments.search(CATALOGUE, name="microsoft")) == ["MSFT_US_EQ"]

    def test_name_matches_mid_word(self):
        result = instruments.search(CATALOGUE, name="apple")
        assert set(ids(result)) == {"AAPL_US_EQ", "AAPL_EQ", "AAPLl_EQ", "PINEAPPLE_EQ"}

    def test_type_filter(self):
        assert ids(instruments.search(CATALOGUE, type_="ETF")) == ["VUSA_EQ"]

    def test_missing_fields_do_not_crash(self):
        assert instruments.search([{"ticker": "X_EQ"}], name="apple")["total"] == 0


# ---------------------------------------------------------------------------
# search() — combining and bounding
# ---------------------------------------------------------------------------

class TestSearchBehaviour:
    def test_filters_combine_with_and(self):
        result = instruments.search(CATALOGUE, isin="US0378331005", type_="CVR")
        assert ids(result) == ["AAPLl_EQ"]

    def test_no_filters_returns_a_bounded_page(self):
        result = instruments.search(CATALOGUE, limit=2)
        assert result["total"] == len(CATALOGUE)
        assert result["returned"] == 2
        assert result["truncated"] is True

    def test_limit_caps_results_but_total_is_honest(self):
        result = instruments.search(CATALOGUE, name="apple", limit=1)
        assert result["total"] == 4
        assert result["returned"] == 1

    def test_not_truncated_when_everything_fits(self):
        result = instruments.search(CATALOGUE, type_="ETF")
        assert result["truncated"] is False

    def test_limit_clamped_to_max(self):
        assert instruments.search(CATALOGUE, limit=10_000)["limit"] == instruments.MAX_LIMIT

    def test_limit_clamped_to_at_least_one(self):
        assert instruments.search(CATALOGUE, limit=0)["limit"] == 1

    def test_results_are_stable_across_calls(self):
        first = ids(instruments.search(CATALOGUE, name="apple"))
        assert first == ids(instruments.search(CATALOGUE, name="apple"))


# ---------------------------------------------------------------------------
# Catalogue caching
# ---------------------------------------------------------------------------

class TestCache:
    def test_catalogue_fetched_once_for_repeat_searches(self):
        with patch("tools.instruments.api", return_value=CATALOGUE) as m:
            tools.dispatch("list_instruments", {"trading212Id": "AAPL"})
            tools.dispatch("list_instruments", {"name": "microsoft"})
        assert m.call_count == 1

    def test_stale_cache_is_refetched(self):
        with patch("tools.instruments.api", return_value=CATALOGUE) as m:
            tools.dispatch("list_instruments", {})
            instruments._cache["fetched_at"] -= instruments.CACHE_TTL + 1
            tools.dispatch("list_instruments", {})
        assert m.call_count == 2

    def test_empty_catalogue_is_still_cached(self):
        """[] is a valid response and must not look like a cold cache."""
        with patch("tools.instruments.api", return_value=[]) as m:
            tools.dispatch("list_instruments", {})
            tools.dispatch("list_instruments", {})
        assert m.call_count == 1


# ---------------------------------------------------------------------------
# Dispatch wiring
# ---------------------------------------------------------------------------

class TestDispatch:
    def test_arguments_reach_the_search(self):
        with patch("tools.instruments.api", return_value=CATALOGUE):
            result = tools.dispatch("list_instruments", {
                "name": "apple", "type": "STOCK", "limit": 5,
            })
        assert set(ids(result)) == {"AAPL_US_EQ", "AAPL_EQ", "PINEAPPLE_EQ"}

    def test_defaults_to_default_limit(self):
        with patch("tools.instruments.api", return_value=CATALOGUE):
            assert tools.dispatch("list_instruments", {})["limit"] == instruments.DEFAULT_LIMIT

    def test_schema_advertises_the_search_fields(self):
        tool = next(t for t in instruments.TOOLS if t.name == "list_instruments")
        props = tool.input_schema["properties"]
        assert set(props) == {"trading212Id", "isin", "name", "type", "limit"}
        assert "ticker" not in props
