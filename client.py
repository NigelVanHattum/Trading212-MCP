"""
HTTP client and configuration for the Trading 212 Public API.

Environment / live vs. paper:
  The API has two completely separate environments with separate credentials:
    - live  -> https://live.trading212.com/api/v0
    - demo  -> https://demo.trading212.com/api/v0   (paper money)
  TRADING212_LIVE selects which one. It defaults to false (the safer paper
  environment), so you must explicitly opt in to trade with real money.

Authentication:
  The Public API uses HTTP Basic auth: Base64("API_KEY:API_SECRET").

Config resolution order (first found wins):
  1. /config/config.json  — Docker volume mount (-v /host/path:/config:ro)
  2. Environment variables

Environment variables:
  TRADING212_API_KEY    - API key generated in the Trading 212 app
  TRADING212_API_SECRET - API secret shown once at key generation
  TRADING212_LIVE       - "true" for the live (real money) environment;
                          anything else uses the demo/paper environment
"""

import base64
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

import ratelimit


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes", "on")


def _load_config() -> dict:
    """Load config from Docker volume mount or environment variables."""
    config_file = Path("/config/config.json")
    if config_file.exists():
        try:
            return json.loads(config_file.read_text())
        except Exception:
            pass

    return {
        "api_key":    os.environ.get("TRADING212_API_KEY", ""),
        "api_secret": os.environ.get("TRADING212_API_SECRET", ""),
        "live":       _as_bool(os.environ.get("TRADING212_LIVE", "false")),
    }


_cfg = _load_config()

API_KEY    = _cfg.get("api_key", "")
API_SECRET = _cfg.get("api_secret", "")
LIVE       = _as_bool(_cfg.get("live", False))

BASE_URL = (
    "https://live.trading212.com/api/v0"
    if LIVE
    else "https://demo.trading212.com/api/v0"
)


# Shared by every tool call: one queue for the whole process, because the API
# applies its limits per account rather than per connection.
limiter = ratelimit.RateLimiter()


def _auth_header() -> str:
    """Build the Authorization header value (HTTP Basic auth)."""
    raw = f"{API_KEY}:{API_SECRET}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def _make_client() -> httpx.Client:
    return httpx.Client(
        base_url=BASE_URL,
        headers={
            "Authorization": _auth_header(),
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        timeout=30.0,
    )


def _retry_after(response: httpx.Response, fallback: float) -> float:
    """Seconds to wait after a 429, from the response headers."""
    try:
        headers = response.headers
        retry_after = headers.get("retry-after")
        if retry_after is not None:
            return max(0.0, float(retry_after))

        reset = headers.get("x-ratelimit-reset")
        if reset is not None:
            # Unix timestamp of the moment the window clears.
            return max(0.0, float(reset) - time.time())
    except (AttributeError, TypeError, ValueError):
        pass
    return fallback


def api(method: str, path: str, params: dict | None = None, body: dict | None = None) -> Any:
    """Execute an API request and return parsed JSON (or {"status": "success"} for empty responses).

    Calls are queued by the rate limiter and go out one at a time, in order, so
    the account's per-endpoint limits are never exceeded. A 429 slipping
    through anyway (another client sharing the account, say) holds the endpoint
    back and is retried once.
    """
    clean_params = {k: v for k, v in (params or {}).items() if v is not None} or None

    for attempt in (1, 2):
        limiter.acquire(method, path)
        with _make_client() as client:
            r = client.request(method=method, url=path, params=clean_params, json=body)

        if r.status_code == 429 and attempt == 1:
            # Fall back to the endpoint's own period when the response says nothing.
            _, period = limiter.limit_for(ratelimit.route_key(method, path))
            limiter.penalize(method, path, _retry_after(r, period))
            continue

        r.raise_for_status()
        return r.json() if r.content else {"status": "success"}


def omit(d: dict, *keys: str) -> dict:
    """Return dict without specified keys and without None values."""
    return {k: v for k, v in d.items() if k not in keys and v is not None}
