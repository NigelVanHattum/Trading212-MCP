"""
Instruments metadata

Endpoints:
  GET /api/v0/equity/metadata/exchanges    — accessible exchanges & schedules
  GET /api/v0/equity/metadata/instruments  — all tradable instruments

Neither endpoint takes any parameters: /instruments returns every tradable
instrument in one response — tens of thousands of them, far past what is useful
to hand an agent. So list_instruments fetches the full list once, caches it, and
searches it here. Callers filter by Trading 212 ID, ISIN, name or type and get
back a bounded page plus the total number of matches.

The upstream data refreshes roughly every 10 minutes and the endpoint allows
1 req/50s, so the cache both keeps responses fast and stops repeat searches from
queueing behind that limit.
"""

import re
import threading
import time
from typing import Any

import mcp.types as types
from client import api, omit

# Trading 212 refreshes this data every ~10 minutes.
CACHE_TTL = 600.0

DEFAULT_LIMIT = 20
MAX_LIMIT = 100

_cache_lock = threading.Lock()
_cache: dict[str, Any] = {"fetched_at": 0.0, "items": None}

TOOLS = [
    types.Tool(
        name="list_exchanges",
        description=(
            "List all accessible exchanges and their working schedules. "
            "Rate limit 1 req/30s."
        ),
        input_schema={
            "type": "object",
            "properties": {},
        },
    ),
    types.Tool(
        name="list_instruments",
        description=(
            "Search tradable instruments by Trading 212 ID, ISIN, name or type. "
            "Filters combine with AND; matches are ranked with the closest first. "
            "The full catalogue is tens of thousands of instruments, so results "
            "are capped — narrow the search rather than raising the limit. "
            "Returns the matching instruments plus the total number of matches. "
            "Rate limit 1 req/50s, but the catalogue is cached for 10 minutes, so "
            "repeat searches cost nothing."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "trading212Id": {
                    "type": "string",
                    "description": (
                        "Trading 212 instrument ID, e.g. 'AAPL_US_EQ'. Matches exact, "
                        "prefix ('AAPL') or substring. This is the value the order "
                        "tools take as their 'ticker' argument."
                    ),
                },
                "isin": {
                    "type": "string",
                    "description": "ISIN, e.g. 'US0378331005'. Exact match; case and spacing are ignored.",
                },
                "name": {
                    "type": "string",
                    "description": "Instrument name, e.g. 'Coca Cola'. Case-insensitive; punctuation is ignored and every word must appear, in any order.",
                },
                "type": {
                    "type": "string",
                    "enum": [
                        "CRYPTOCURRENCY", "ETF", "FOREX", "FUTURES", "INDEX",
                        "STOCK", "WARRANT", "CRYPTO", "CVR", "CORPACT",
                    ],
                    "description": "Restrict results to one instrument type.",
                },
                "limit": {
                    "type": "integer",
                    "description": f"Maximum instruments to return (default {DEFAULT_LIMIT}, max {MAX_LIMIT}).",
                },
            },
        },
    ),
]

TOOL_NAMES = {t.name for t in TOOLS}


def _all_instruments() -> list[dict]:
    """The full catalogue, refetched only once the cache has gone stale.

    The lock is held across the fetch on purpose: concurrent searches on a cold
    cache should wait for the one request rather than each queue up their own
    against a 1 req/50s endpoint.
    """
    with _cache_lock:
        age = time.monotonic() - _cache["fetched_at"]
        if _cache["items"] is None or age >= CACHE_TTL:
            _cache["items"] = api("GET", "/equity/metadata/instruments")
            _cache["fetched_at"] = time.monotonic()
        return _cache["items"]


_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")


def _normalise(text: str) -> str:
    """Lowercase, and reduce punctuation to single spaces.

    Instrument names carry punctuation an agent will not reproduce: the
    catalogue says 'Coca-Cola', a caller searches 'coca cola'. Normalising both
    sides makes the two the same string.
    """
    return _NON_ALPHANUMERIC.sub(" ", (text or "").lower()).strip()


def _bare(text: str) -> str:
    """Strip everything but letters and digits — for identifiers like ISINs."""
    return _NON_ALPHANUMERIC.sub("", (text or "").lower()).upper()


def _name_matches(name: str, query: str) -> bool:
    """True when every word of the query appears in the name, in any order."""
    haystack = _normalise(name)
    return all(token in haystack for token in query.split())


def _id_rank(instrument_id: str, query: str) -> int | None:
    """0 exact, 1 prefix, 2 substring, None for no match."""
    instrument_id = (instrument_id or "").upper()
    if instrument_id == query:
        return 0
    if instrument_id.startswith(query):
        return 1
    if query in instrument_id:
        return 2
    return None


def search(
    items: list[dict],
    trading212_id: str | None = None,
    isin: str | None = None,
    name: str | None = None,
    type_: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    """Filter the catalogue and return a bounded, ranked page of matches."""
    limit = max(1, min(int(limit), MAX_LIMIT))

    query_id = (trading212_id or "").strip().upper()
    query_isin = _bare(isin or "")
    query_name = _normalise(name or "")
    query_type = (type_ or "").strip().upper()

    ranked: list[tuple[int, dict]] = []
    for item in items:
        rank = 0

        if query_id:
            id_rank = _id_rank(item.get("ticker", ""), query_id)
            if id_rank is None:
                continue
            rank = id_rank

        if query_isin and _bare(item.get("isin", "")) != query_isin:
            continue

        if query_name and not _name_matches(item.get("name", ""), query_name):
            continue

        if query_type and (item.get("type") or "").upper() != query_type:
            continue

        ranked.append((rank, item))

    ranked.sort(key=lambda pair: (pair[0], (pair[1].get("ticker") or "")))
    page = [item for _, item in ranked[:limit]]

    return {
        "total": len(ranked),
        "returned": len(page),
        "limit": limit,
        "truncated": len(ranked) > len(page),
        "instruments": page,
    }


def dispatch(name: str, a: dict) -> Any:
    if name == "list_exchanges":
        return api("GET", "/equity/metadata/exchanges")

    elif name == "list_instruments":
        args = omit(a)
        return search(
            _all_instruments(),
            trading212_id=args.get("trading212Id"),
            isin=args.get("isin"),
            name=args.get("name"),
            type_=args.get("type"),
            limit=args.get("limit", DEFAULT_LIMIT),
        )
