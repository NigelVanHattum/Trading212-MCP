"""
Client-side rate limiting for the Trading 212 Public API.

Every endpoint publishes its own limit (see LIMITS below) and the limits are
enforced *per account*, not per API key or per IP — so a burst from this server
counts against the same budget as anything else the account is doing, and one
endpoint tripping a 429 is an account-wide problem.

Strategy: a single queue. Calls are executed one at a time, in the order they
arrived, and each waits out its own endpoint's window before going through.
That does mean a caller waiting on a slow endpoint (list_instruments is
1 req / 50s) holds up everything behind it, which is the trade-off the queue
buys us: no bookkeeping, no way for two calls to race the same window. This
server handles a handful of calls at a time, so head-of-line blocking is
cheaper than the alternative.

Each endpoint's window is a sliding one: a limit of 6 req / 1m allows a burst
of 6 followed by a wait until the oldest of those six is a minute old, which is
how the API itself describes the behaviour.
"""

import re
import threading
import time
from collections import deque

# (METHOD, normalised path) -> (requests, period in seconds)
# Sourced from the endpoint reference at https://docs.trading212.com/api
LIMITS: dict[tuple[str, str], tuple[int, float]] = {
    ("GET",    "/equity/account/summary"):      (1, 5),
    ("GET",    "/equity/positions"):            (1, 1),

    ("GET",    "/equity/metadata/exchanges"):   (1, 30),
    ("GET",    "/equity/metadata/instruments"): (1, 50),

    ("GET",    "/equity/orders"):               (1, 5),
    ("GET",    "/equity/orders/{id}"):          (1, 1),
    ("DELETE", "/equity/orders/{id}"):          (50, 60),
    ("POST",   "/equity/orders/market"):        (50, 60),
    ("POST",   "/equity/orders/limit"):         (1, 2),
    ("POST",   "/equity/orders/stop"):          (1, 2),
    ("POST",   "/equity/orders/stop_limit"):    (1, 2),

    ("GET",    "/equity/history/orders"):       (6, 60),
    ("GET",    "/equity/history/dividends"):    (6, 60),
    ("GET",    "/equity/history/transactions"): (6, 60),
    ("GET",    "/equity/history/exports"):      (1, 60),
    ("POST",   "/equity/history/exports"):      (1, 30),

    ("GET",    "/equity/pies"):                 (1, 30),
    ("POST",   "/equity/pies"):                 (1, 5),
    ("GET",    "/equity/pies/{id}"):            (1, 5),
    ("POST",   "/equity/pies/{id}"):            (1, 5),
    ("DELETE", "/equity/pies/{id}"):            (1, 5),
    ("POST",   "/equity/pies/{id}/duplicate"):  (1, 5),
}

# Applied to any route missing from LIMITS — the slowest limit the API
# documents for a read endpoint, so a new tool cannot outrun its budget before
# anyone notices the table is stale.
DEFAULT_LIMIT: tuple[int, float] = (1, 50)

# Windows are measured by the API at *its* end. We time ours from the moment a
# request is handed to httpx, so connection setup on the earlier call can make
# two requests land closer together than we spaced them — measured at 0.97s
# apart on a 1 req/s endpoint. Pad every wait to keep that jitter on the safe
# side of the limit.
SAFETY_MARGIN = 0.1

_ID_SEGMENT = re.compile(r"/\d+(?=/|$)")


def route_key(method: str, path: str) -> tuple[str, str]:
    """Normalise a request into a LIMITS key: /equity/orders/123 -> .../{id}."""
    path = path.split("?", 1)[0].rstrip("/") or "/"
    return method.upper(), _ID_SEGMENT.sub("/{id}", path)


class RateLimiter:
    """FIFO queue that releases one call at a time, within each route's limit.

    now/sleep are injectable so tests do not have to spend real seconds.
    """

    def __init__(self, limits=None, default=DEFAULT_LIMIT, margin=SAFETY_MARGIN,
                 now=time.monotonic, sleep=time.sleep):
        self._limits = LIMITS if limits is None else limits
        self._default = default
        self._margin = margin
        self._now = now
        self._sleep = sleep

        self._cond = threading.Condition()
        self._next_ticket = 0
        self._now_serving = 0

        self._history: dict[tuple[str, str], deque[float]] = {}
        self._blocked_until: dict[tuple[str, str], float] = {}

    def limit_for(self, key: tuple[str, str]) -> tuple[int, float]:
        return self._limits.get(key, self._default)

    def acquire(self, method: str, path: str) -> float:
        """Block until this call may go out. Returns how long it waited."""
        key = route_key(method, path)
        count, period = self.limit_for(key)

        with self._cond:
            ticket = self._next_ticket
            self._next_ticket += 1
            while self._now_serving != ticket:
                self._cond.wait()

        waited = 0.0
        try:
            history = self._history.setdefault(key, deque())
            while True:
                now = self._now()

                # Drop timestamps that have aged out of the window.
                while history and now - history[0] >= period:
                    history.popleft()

                delay = 0.0
                if len(history) >= count:
                    delay = max(delay, history[0] + period - now)

                blocked_until = self._blocked_until.get(key, 0.0)
                if blocked_until > now:
                    delay = max(delay, blocked_until - now)

                if delay <= 0:
                    history.append(now)
                    return waited

                self._sleep(delay + self._margin)
                waited += delay + self._margin
        finally:
            with self._cond:
                self._now_serving += 1
                self._cond.notify_all()

    def penalize(self, method: str, path: str, seconds: float) -> None:
        """Hold a route back for `seconds` — used when the API returns a 429."""
        if seconds <= 0:
            return
        key = route_key(method, path)
        self._blocked_until[key] = self._now() + seconds
