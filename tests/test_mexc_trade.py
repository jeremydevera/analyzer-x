"""Signed MEXC trading client. No network, no real orders.

Every test here runs against a patched transport. Nothing in this file may place
an order — the live path is only ever exercised deliberately by the user.
"""

import hashlib
import hmac
from unittest.mock import patch

import pytest

from tradingagents.dataflows import mexc_trade

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    monkeypatch.setenv("MEXC_API_KEY", "test-key")
    monkeypatch.setenv("MEXC_API_SECRET", "test-secret")


# --- signing --------------------------------------------------------------


def test_signature_is_hmac_sha256_of_the_query_string():
    params = {"symbol": "XPLKUSDT", "side": "BUY", "timestamp": 1785000000000}
    query, signature = mexc_trade.sign(params, "test-secret")
    expected = hmac.new(b"test-secret", query.encode(), hashlib.sha256).hexdigest()
    assert signature == expected
    assert signature == signature.lower(), "MEXC accepts lowercase only"


def test_signing_preserves_parameter_order():
    """The signed string and the sent string must match exactly, order included."""
    params = {"b": "2", "a": "1", "timestamp": 1}
    query, _ = mexc_trade.sign(params, "s")
    assert query == "b=2&a=1&timestamp=1"


def test_signature_excludes_itself_from_the_signed_string():
    params = {"symbol": "X", "timestamp": 1, "signature": "stale"}
    query, _ = mexc_trade.sign(params, "s")
    assert "signature" not in query


def test_credentials_missing_is_reported_not_raised():
    with patch.dict("os.environ", {}, clear=True):
        assert mexc_trade.credentials() == (None, None)
        assert mexc_trade.has_credentials() is False


def test_credentials_present():
    assert mexc_trade.has_credentials() is True
    assert mexc_trade.credentials() == ("test-key", "test-secret")


# --- request plumbing -----------------------------------------------------


def test_signed_request_sends_the_key_header_and_signature():
    captured = {}

    def fake(method, url, headers, timeout):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = headers
        return {"ok": True}

    with patch.object(mexc_trade, "_send", side_effect=fake):
        mexc_trade._signed("GET", "/api/v3/account", {})
    assert captured["headers"]["X-MEXC-APIKEY"] == "test-key"
    assert "signature=" in captured["url"]
    assert "timestamp=" in captured["url"]


def test_signed_request_refuses_without_credentials():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(mexc_trade.MexcTradeError, match="credentials"):
            mexc_trade._signed("GET", "/api/v3/account", {})


def test_api_error_body_is_surfaced():
    import urllib.error

    err = urllib.error.HTTPError("u", 400, "Bad Request", {},
                                 __import__("io").BytesIO(
                                     b'{"code":700002,"msg":"Signature for this request is not valid."}'))
    with patch.object(mexc_trade, "_open", side_effect=err):
        with pytest.raises(mexc_trade.MexcTradeError) as exc:
            mexc_trade._signed("GET", "/api/v3/account", {})
    assert "700002" in str(exc.value) or "Signature" in str(exc.value)


# --- account --------------------------------------------------------------


def test_balances_returns_free_amounts_by_asset():
    payload = {"balances": [{"asset": "USDT", "free": "12.5", "locked": "0"},
                            {"asset": "XPLK", "free": "1000", "locked": "0"},
                            {"asset": "DUST", "free": "0", "locked": "0"}]}
    with patch.object(mexc_trade, "_signed", return_value=payload):
        balances = mexc_trade.balances()
    assert balances["USDT"] == pytest.approx(12.5)
    assert balances["XPLK"] == pytest.approx(1000.0)
    assert "DUST" not in balances, "zero balances are noise"


def test_usdt_balance_helper():
    with patch.object(mexc_trade, "balances", return_value={"USDT": 7.25}):
        assert mexc_trade.usdt_balance() == pytest.approx(7.25)


def test_usdt_balance_is_zero_when_absent():
    with patch.object(mexc_trade, "balances", return_value={}):
        assert mexc_trade.usdt_balance() == 0.0


# --- orders ---------------------------------------------------------------


def test_market_buy_spends_a_quote_amount():
    captured = {}

    def fake(method, path, params):
        captured.update(method=method, path=path, params=dict(params))
        return {"orderId": "1", "executedQty": "1234.5", "cummulativeQuoteQty": "3.0"}

    with patch.object(mexc_trade, "_signed", side_effect=fake):
        fill = mexc_trade.market_buy("XPLKUSDT", quote_usd=3.0)
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v3/order"
    assert captured["params"]["side"] == "BUY"
    assert captured["params"]["type"] == "MARKET"
    assert captured["params"]["quoteOrderQty"] == "3.0"
    assert fill["qty"] == pytest.approx(1234.5)
    assert fill["spent"] == pytest.approx(3.0)
    assert fill["price"] == pytest.approx(3.0 / 1234.5)


def test_market_buy_refuses_below_the_exchange_minimum():
    """MEXC rejects orders under 1 USDT; failing early costs no request."""
    with patch.object(mexc_trade, "_signed") as signed:
        with pytest.raises(mexc_trade.MexcTradeError, match="minimum"):
            mexc_trade.market_buy("XPLKUSDT", quote_usd=0.5)
    assert not signed.called


def test_market_buy_refuses_a_non_positive_amount():
    with pytest.raises(mexc_trade.MexcTradeError):
        mexc_trade.market_buy("XPLKUSDT", quote_usd=0)


def test_market_sell_sends_the_base_quantity():
    captured = {}

    def fake(method, path, params):
        captured.update(params=dict(params))
        return {"orderId": "2", "executedQty": "1234.5", "cummulativeQuoteQty": "4.5"}

    with patch.object(mexc_trade, "_signed", side_effect=fake):
        fill = mexc_trade.market_sell("XPLKUSDT", qty=1234.5)
    assert captured["params"]["side"] == "SELL"
    assert captured["params"]["type"] == "MARKET"
    assert captured["params"]["quantity"] == "1234.5"
    assert fill["received"] == pytest.approx(4.5)


def test_dry_run_places_nothing():
    """The safety valve: same call, no request, a clearly marked result."""
    with patch.object(mexc_trade, "_signed") as signed:
        fill = mexc_trade.market_buy("XPLKUSDT", quote_usd=3.0, dry_run=True)
    assert not signed.called
    assert fill["dry_run"] is True
    assert fill["spent"] == pytest.approx(3.0)


def test_dry_run_sell_places_nothing():
    with patch.object(mexc_trade, "_signed") as signed:
        fill = mexc_trade.market_sell("XPLKUSDT", qty=10.0, dry_run=True)
    assert not signed.called
    assert fill["dry_run"] is True
