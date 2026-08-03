"""Tests for ratelimit.py — route keys, window enforcement, and FIFO ordering.

A fake clock stands in for time.monotonic/time.sleep, so windows that take a
minute of wall time are exercised instantly and the assertions are exact.
"""

import threading
import time

import pytest

import ratelimit


class FakeClock:
    """Monotonic clock that only advances when someone sleeps."""

    def __init__(self):
        self.t = 1000.0
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.t += seconds


def _limiter(limits, clock=None, margin=0):
    """Limiter on a fake clock. margin defaults to 0 so window maths reads exactly."""
    clock = clock or FakeClock()
    return ratelimit.RateLimiter(
        limits=limits, margin=margin, now=clock.now, sleep=clock.sleep
    ), clock


# ---------------------------------------------------------------------------
# route_key()
# ---------------------------------------------------------------------------

class TestRouteKey:
    def test_uppercases_method(self):
        assert ratelimit.route_key("get", "/equity/orders")[0] == "GET"

    def test_normalises_numeric_id(self):
        assert ratelimit.route_key("GET", "/equity/orders/123") == ("GET", "/equity/orders/{id}")

    def test_normalises_id_mid_path(self):
        assert ratelimit.route_key("POST", "/equity/pies/42/duplicate") == (
            "POST", "/equity/pies/{id}/duplicate"
        )

    def test_leaves_word_segments_alone(self):
        assert ratelimit.route_key("POST", "/equity/orders/stop_limit") == (
            "POST", "/equity/orders/stop_limit"
        )

    def test_strips_query_and_trailing_slash(self):
        assert ratelimit.route_key("GET", "/equity/positions/?ticker=AAPL_US_EQ") == (
            "GET", "/equity/positions"
        )


# ---------------------------------------------------------------------------
# Limits table
# ---------------------------------------------------------------------------

class TestLimits:
    @pytest.mark.parametrize("key,expected", [
        (("GET", "/equity/account/summary"), (1, 5)),
        (("GET", "/equity/metadata/instruments"), (1, 50)),
        (("POST", "/equity/orders/market"), (50, 60)),
        (("GET", "/equity/history/orders"), (6, 60)),
    ])
    def test_documented_limits(self, key, expected):
        assert ratelimit.LIMITS[key] == expected

    def test_unknown_route_gets_conservative_default(self):
        limiter, _ = _limiter({})
        assert limiter.limit_for(("GET", "/equity/something/new")) == ratelimit.DEFAULT_LIMIT

    def test_every_route_the_tools_call_has_an_explicit_limit(self):
        """No shipped tool may fall through to DEFAULT_LIMIT."""
        called = [
            ("GET", "/equity/account/summary"),
            ("GET", "/equity/positions"),
            ("GET", "/equity/metadata/exchanges"),
            ("GET", "/equity/metadata/instruments"),
            ("GET", "/equity/orders"),
            ("GET", "/equity/orders/1"),
            ("DELETE", "/equity/orders/1"),
            ("POST", "/equity/orders/market"),
            ("POST", "/equity/orders/limit"),
            ("POST", "/equity/orders/stop"),
            ("POST", "/equity/orders/stop_limit"),
            ("GET", "/equity/history/orders"),
            ("GET", "/equity/history/dividends"),
            ("GET", "/equity/history/transactions"),
            ("GET", "/equity/history/exports"),
            ("POST", "/equity/history/exports"),
        ]
        missing = [c for c in called if ratelimit.route_key(*c) not in ratelimit.LIMITS]
        assert missing == []


# ---------------------------------------------------------------------------
# Window enforcement
# ---------------------------------------------------------------------------

class TestWindow:
    def test_first_call_does_not_wait(self):
        limiter, clock = _limiter({("GET", "/x"): (1, 5)})
        assert limiter.acquire("GET", "/x") == 0
        assert clock.slept == []

    def test_second_call_waits_out_the_period(self):
        limiter, clock = _limiter({("GET", "/x"): (1, 5)})
        limiter.acquire("GET", "/x")
        assert limiter.acquire("GET", "/x") == 5
        assert clock.slept == [5]

    def test_burst_then_wait(self):
        """6 req / 60s allows six immediately, then waits on the oldest."""
        limiter, clock = _limiter({("GET", "/x"): (6, 60)})
        for _ in range(6):
            assert limiter.acquire("GET", "/x") == 0
        assert limiter.acquire("GET", "/x") == 60
        assert clock.slept == [60]

    def test_window_slides(self):
        limiter, clock = _limiter({("GET", "/x"): (2, 10)})
        limiter.acquire("GET", "/x")
        limiter.acquire("GET", "/x")
        limiter.acquire("GET", "/x")   # waits 10, evicting the first
        clock.slept.clear()
        # One slot freed, so the next call goes straight through.
        assert limiter.acquire("GET", "/x") == 0

    def test_routes_are_independent(self):
        limiter, clock = _limiter({("GET", "/x"): (1, 50), ("GET", "/y"): (1, 50)})
        limiter.acquire("GET", "/x")
        assert limiter.acquire("GET", "/y") == 0
        assert clock.slept == []

    def test_methods_are_independent(self):
        limiter, _ = _limiter({("GET", "/x"): (1, 50), ("POST", "/x"): (1, 50)})
        limiter.acquire("GET", "/x")
        assert limiter.acquire("POST", "/x") == 0

    def test_ids_share_one_bucket(self):
        limiter, _ = _limiter({("GET", "/equity/orders/{id}"): (1, 1)})
        limiter.acquire("GET", "/equity/orders/1")
        assert limiter.acquire("GET", "/equity/orders/2") == 1


# ---------------------------------------------------------------------------
# Safety margin
# ---------------------------------------------------------------------------

class TestSafetyMargin:
    def test_margin_pads_every_wait(self):
        limiter, clock = _limiter({("GET", "/x"): (1, 5)}, margin=0.1)
        limiter.acquire("GET", "/x")
        assert limiter.acquire("GET", "/x") == pytest.approx(5.1)
        assert clock.slept == [pytest.approx(5.1)]

    def test_margin_not_applied_when_no_wait_is_needed(self):
        limiter, clock = _limiter({("GET", "/x"): (5, 5)}, margin=0.1)
        assert limiter.acquire("GET", "/x") == 0
        assert clock.slept == []

    def test_default_margin_is_applied(self):
        clock = FakeClock()
        limiter = ratelimit.RateLimiter(
            limits={("GET", "/x"): (1, 1)}, now=clock.now, sleep=clock.sleep
        )
        limiter.acquire("GET", "/x")
        assert limiter.acquire("GET", "/x") == pytest.approx(1 + ratelimit.SAFETY_MARGIN)


# ---------------------------------------------------------------------------
# 429 penalties
# ---------------------------------------------------------------------------

class TestPenalize:
    def test_penalty_delays_next_call(self):
        limiter, clock = _limiter({("GET", "/x"): (10, 1)})
        limiter.penalize("GET", "/x", 30)
        assert limiter.acquire("GET", "/x") == 30

    def test_penalty_is_per_route(self):
        limiter, _ = _limiter({("GET", "/x"): (10, 1), ("GET", "/y"): (10, 1)})
        limiter.penalize("GET", "/x", 30)
        assert limiter.acquire("GET", "/y") == 0

    def test_non_positive_penalty_ignored(self):
        limiter, clock = _limiter({("GET", "/x"): (10, 1)})
        limiter.penalize("GET", "/x", 0)
        assert limiter.acquire("GET", "/x") == 0


# ---------------------------------------------------------------------------
# Queueing
# ---------------------------------------------------------------------------

class TestQueue:
    def test_calls_execute_in_arrival_order(self):
        """Callers that pile up behind a waiting call come out in arrival order."""
        clock = FakeClock()
        lock = threading.Lock()
        gate = threading.Event()
        order = []

        def now():
            with lock:
                return clock.t

        def sleep(seconds):
            # Every waiting caller parks here until the test opens the gate,
            # which is what lets three of them queue up at once.
            gate.wait(5)
            with lock:
                clock.t += seconds

        limiter = ratelimit.RateLimiter(limits={("GET", "/x"): (1, 5)}, now=now, sleep=sleep)

        def enqueued(count):
            for _ in range(500):
                with limiter._cond:
                    if limiter._next_ticket == count:
                        return True
                time.sleep(0.002)
            return False

        # Fill the window so everyone after this has to wait.
        limiter.acquire("GET", "/x")
        order.append("first")

        threads = []
        for i, name in enumerate(("second", "third", "fourth"), start=2):
            t = threading.Thread(target=lambda n=name: (limiter.acquire("GET", "/x"), order.append(n)))
            t.start()
            threads.append(t)
            assert enqueued(i), f"{name} never reached the queue"

        gate.set()
        for t in threads:
            t.join(5)

        assert order == ["first", "second", "third", "fourth"]

    def test_concurrent_callers_never_exceed_the_limit(self):
        """Ten threads against a 2-per-window route yield exactly 2 slots per window."""
        clock = FakeClock()
        lock = threading.Lock()

        def now():
            with lock:
                return clock.t

        def sleep(seconds):
            with lock:
                clock.t += seconds

        limiter = ratelimit.RateLimiter(limits={("GET", "/x"): (2, 10)}, now=now, sleep=sleep)
        stamps = []

        def call():
            limiter.acquire("GET", "/x")
            with lock:
                stamps.append(clock.t)

        threads = [threading.Thread(target=call) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)

        assert len(stamps) == 10
        # No 10-second span may contain more than 2 calls.
        for i, stamp in enumerate(stamps):
            within = [s for s in stamps if stamp <= s < stamp + 10]
            assert len(within) <= 2, f"{len(within)} calls inside one window at t={stamp}"
