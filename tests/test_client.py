"""Tests for client.py — HTTP helpers, auth, and environment switching."""

import base64
import importlib
import time

import pytest
import httpx
from unittest.mock import patch, MagicMock

import client


# ---------------------------------------------------------------------------
# omit()
# ---------------------------------------------------------------------------

class TestOmit:
    def test_removes_specified_keys(self):
        assert client.omit({"a": 1, "b": 2, "c": 3}, "b") == {"a": 1, "c": 3}

    def test_removes_multiple_keys(self):
        result = client.omit({"id": "x", "ticker": "y", "quantity": 1}, "id", "ticker")
        assert result == {"quantity": 1}

    def test_strips_none_values(self):
        assert client.omit({"a": 1, "b": None, "c": 0}) == {"a": 1, "c": 0}

    def test_empty_dict(self):
        assert client.omit({}) == {}

    def test_false_not_stripped(self):
        assert client.omit({"enabled": False, "x": None}) == {"enabled": False}

    def test_zero_not_stripped(self):
        assert client.omit({"quantity": 0}) == {"quantity": 0}

    def test_negative_quantity_kept(self):
        """Sell orders use a negative quantity — must not be stripped."""
        assert client.omit({"quantity": -10.5}) == {"quantity": -10.5}


# ---------------------------------------------------------------------------
# _as_bool()
# ---------------------------------------------------------------------------

class TestAsBool:
    @pytest.mark.parametrize("value", ["true", "True", "1", "yes", "on", True])
    def test_truthy(self, value):
        assert client._as_bool(value) is True

    @pytest.mark.parametrize("value", ["false", "False", "0", "no", "", "anything", False])
    def test_falsy(self, value):
        assert client._as_bool(value) is False


# ---------------------------------------------------------------------------
# Environment switching + auth header (re-import with patched env)
# ---------------------------------------------------------------------------

def _reload_client(env: dict):
    with patch.dict("os.environ", env, clear=True):
        # No /config/config.json in the test image, so env vars are used.
        return importlib.reload(client)


class TestEnvironmentAndAuth:
    def test_demo_is_default(self):
        c = _reload_client({"TRADING212_API_KEY": "k", "TRADING212_API_SECRET": "s"})
        assert c.LIVE is False
        assert c.BASE_URL == "https://demo.trading212.com/api/v0"

    def test_live_when_flag_true(self):
        c = _reload_client({
            "TRADING212_API_KEY": "k",
            "TRADING212_API_SECRET": "s",
            "TRADING212_LIVE": "true",
        })
        assert c.LIVE is True
        assert c.BASE_URL == "https://live.trading212.com/api/v0"

    def test_basic_auth_header(self):
        c = _reload_client({"TRADING212_API_KEY": "mykey", "TRADING212_API_SECRET": "mysecret"})
        expected = "Basic " + base64.b64encode(b"mykey:mysecret").decode()
        assert c._auth_header() == expected

    @classmethod
    def teardown_class(cls):
        # Restore module to a clean default state for other test modules.
        importlib.reload(client)


# ---------------------------------------------------------------------------
# api()
# ---------------------------------------------------------------------------

def _mock_response(json_data=None, status=200, content=b"{}"):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.content = content
    if json_data is not None:
        resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


class TestApi:
    def test_get_returns_json(self):
        mock_resp = _mock_response(json_data={"data": [1, 2]}, content=b'{"data":[1,2]}')
        with patch("client._make_client") as mk:
            mk.return_value.__enter__.return_value.request.return_value = mock_resp
            assert client.api("GET", "/equity/positions") == {"data": [1, 2]}

    def test_empty_response_returns_success(self):
        mock_resp = _mock_response(content=b"")
        with patch("client._make_client") as mk:
            mk.return_value.__enter__.return_value.request.return_value = mock_resp
            assert client.api("DELETE", "/equity/orders/1") == {"status": "success"}

    def test_passes_params(self):
        mock_resp = _mock_response(json_data={}, content=b"{}")
        with patch("client._make_client") as mk:
            req = mk.return_value.__enter__.return_value.request
            req.return_value = mock_resp
            client.api("GET", "/equity/history/orders", params={"limit": 10, "cursor": None})
        assert req.call_args.kwargs["params"] == {"limit": 10}

    def test_passes_body(self):
        mock_resp = _mock_response(json_data={"id": 5}, content=b'{"id":5}')
        with patch("client._make_client") as mk:
            req = mk.return_value.__enter__.return_value.request
            req.return_value = mock_resp
            client.api("POST", "/equity/orders/market", body={"ticker": "AAPL_US_EQ", "quantity": 1})
        assert req.call_args.kwargs["json"] == {"ticker": "AAPL_US_EQ", "quantity": 1}

    def test_raises_on_http_error(self):
        mock_resp = _mock_response(status=401)
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Unauthorized", request=MagicMock(), response=mock_resp
        )
        with patch("client._make_client") as mk:
            mk.return_value.__enter__.return_value.request.return_value = mock_resp
            with pytest.raises(httpx.HTTPStatusError):
                client.api("GET", "/equity/account/summary")

    def test_null_params_become_none(self):
        mock_resp = _mock_response(json_data={}, content=b"{}")
        with patch("client._make_client") as mk:
            req = mk.return_value.__enter__.return_value.request
            req.return_value = mock_resp
            client.api("GET", "/equity/history/orders", params={"cursor": None})
        assert req.call_args.kwargs["params"] is None


# ---------------------------------------------------------------------------
# api() rate limiting
# ---------------------------------------------------------------------------

def _headers(**kwargs):
    """Real header mapping — MagicMock's default .get() would hide parsing bugs."""
    return httpx.Headers({k.replace("_", "-"): v for k, v in kwargs.items()})


class TestApiRateLimiting:
    def test_acquires_before_the_request(self):
        mock_resp = _mock_response(json_data={}, content=b"{}")
        with patch("client._make_client") as mk, patch.object(client, "limiter") as lim:
            mk.return_value.__enter__.return_value.request.return_value = mock_resp
            client.api("GET", "/equity/positions")
        lim.acquire.assert_called_once_with("GET", "/equity/positions")

    def test_retries_once_after_429(self):
        throttled = _mock_response(status=429)
        throttled.headers = _headers(retry_after="7")
        ok = _mock_response(json_data={"ok": True}, content=b'{"ok":true}')

        with patch("client._make_client") as mk, patch.object(client, "limiter") as lim:
            lim.limit_for.return_value = (1, 5)
            req = mk.return_value.__enter__.return_value.request
            req.side_effect = [throttled, ok]
            assert client.api("GET", "/equity/positions") == {"ok": True}

        assert req.call_count == 2
        lim.penalize.assert_called_once_with("GET", "/equity/positions", 7.0)
        assert lim.acquire.call_count == 2

    def test_second_429_is_raised(self):
        throttled = _mock_response(status=429)
        throttled.headers = _headers(retry_after="1")
        throttled.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Too Many Requests", request=MagicMock(), response=throttled
        )
        with patch("client._make_client") as mk, patch.object(client, "limiter") as lim:
            lim.limit_for.return_value = (1, 5)
            mk.return_value.__enter__.return_value.request.return_value = throttled
            with pytest.raises(httpx.HTTPStatusError):
                client.api("GET", "/equity/positions")

    def test_no_penalty_on_success(self):
        mock_resp = _mock_response(json_data={}, content=b"{}")
        with patch("client._make_client") as mk, patch.object(client, "limiter") as lim:
            mk.return_value.__enter__.return_value.request.return_value = mock_resp
            client.api("GET", "/equity/positions")
        lim.penalize.assert_not_called()


class TestRetryAfter:
    def test_prefers_retry_after_header(self):
        resp = _mock_response(status=429)
        resp.headers = _headers(retry_after="12", x_ratelimit_reset="99999999999")
        assert client._retry_after(resp, fallback=5) == 12.0

    def test_falls_back_to_ratelimit_reset(self):
        resp = _mock_response(status=429)
        resp.headers = _headers(x_ratelimit_reset=str(int(time.time()) + 30))
        assert 28 <= client._retry_after(resp, fallback=5) <= 30

    def test_reset_in_the_past_is_zero(self):
        resp = _mock_response(status=429)
        resp.headers = _headers(x_ratelimit_reset="1")
        assert client._retry_after(resp, fallback=5) == 0.0

    def test_unparseable_header_uses_fallback(self):
        resp = _mock_response(status=429)
        resp.headers = _headers(retry_after="soon")
        assert client._retry_after(resp, fallback=5) == 5

    def test_no_headers_uses_fallback(self):
        resp = _mock_response(status=429)
        resp.headers = _headers()
        assert client._retry_after(resp, fallback=5) == 5
