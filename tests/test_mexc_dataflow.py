"""Unit tests for the MEXC dataflow (no network — every HTTP call is patched)."""

from unittest.mock import patch

import pytest

from tradingagents.dataflows import mexc
from tradingagents.dataflows.symbol_utils import from_mexc_symbol, to_mexc_symbol

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clear_host_cache():
    mexc.reset_host_cache()
    yield
    mexc.reset_host_cache()


def test_resolve_host_prefers_first_reachable():
    with patch.object(mexc, "_raw_get", return_value={}) as raw:
        assert mexc.resolve_host() == "api.mexc.fm"
    assert raw.call_count == 1


def test_resolve_host_falls_through_tls_block_to_next_host():
    """A blocked host fails TLS verification; the next candidate must be tried."""
    def fake(host, path, params=None, timeout=None):
        if host == "api.mexc.fm":
            raise mexc.MexcHostUnavailable("TLS: CERTIFICATE_VERIFY_FAILED")
        return {}

    with patch.object(mexc, "_raw_get", side_effect=fake):
        assert mexc.resolve_host() == "api.mexc.co"


def test_resolve_host_raises_when_all_hosts_blocked():
    with patch.object(mexc, "_raw_get", side_effect=mexc.MexcHostUnavailable("blocked")):
        with pytest.raises(mexc.MexcUnavailable) as exc:
            mexc.resolve_host()
    assert "MEXC_API_HOST" in str(exc.value)


def test_env_override_is_the_only_candidate(monkeypatch):
    monkeypatch.setenv("MEXC_API_HOST", "mexc.internal")
    with patch.object(mexc, "_raw_get", return_value={}) as raw:
        assert mexc.resolve_host() == "mexc.internal"
    assert raw.call_args[0][0] == "mexc.internal"


def test_resolved_host_is_cached_across_calls():
    with patch.object(mexc, "_raw_get", return_value={}) as raw:
        mexc.resolve_host()
        mexc.resolve_host()
    assert raw.call_count == 1


# --- Symbol mapping --------------------------------------------------------


@pytest.mark.parametrize("raw,expected", [
    ("CATE-USD", "CATEUSDT"),
    ("CATE-USDT", "CATEUSDT"),
    ("CATEUSDT", "CATEUSDT"),
    ("cate-usd", "CATEUSDT"),
    ("CATE", "CATEUSDT"),
    ("CATE-USDC", "CATEUSDC"),
])
def test_to_mexc_symbol(raw, expected):
    assert to_mexc_symbol(raw) == expected


@pytest.mark.parametrize("pair,expected", [
    ("CATEUSDT", "CATE-USD"),
    ("BTCUSDT", "BTC-USD"),
    ("WEIRD", "WEIRD"),
])
def test_from_mexc_symbol(pair, expected):
    assert from_mexc_symbol(pair) == expected


def test_mexc_symbol_round_trip():
    assert to_mexc_symbol(from_mexc_symbol("CATEUSDT")) == "CATEUSDT"


# --- Symbol universe and 24h ticker ---------------------------------------

_EXCHANGE_INFO = {
    "symbols": [
        {"symbol": "CATEUSDT", "baseAsset": "CATE", "quoteAsset": "USDT",
         "isSpotTradingAllowed": True, "fullName": "Catestein",
         "contractAddress": "0xabc"},
        {"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT",
         "isSpotTradingAllowed": True, "fullName": "Bitcoin", "contractAddress": ""},
        {"symbol": "ETHBTC", "baseAsset": "ETH", "quoteAsset": "BTC",
         "isSpotTradingAllowed": True, "fullName": "Ethereum", "contractAddress": ""},
        {"symbol": "HALTEDUSDT", "baseAsset": "HALTED", "quoteAsset": "USDT",
         "isSpotTradingAllowed": False, "fullName": "Halted", "contractAddress": ""},
    ]
}

_TICKER_24H = [
    {"symbol": "CATEUSDT", "lastPrice": "0.003782",
     "quoteVolume": "140981.74", "priceChangePercent": "-0.2379"},
    {"symbol": "BTCUSDT", "lastPrice": "64666.01",
     "quoteVolume": "409920994.69", "priceChangePercent": "0.0196"},
]


def test_fetch_usdt_symbols_keeps_only_tradable_usdt_pairs():
    with patch.object(mexc, "_get", return_value=_EXCHANGE_INFO):
        rows = mexc.fetch_usdt_symbols()
    assert [r["symbol"] for r in rows] == ["CATEUSDT", "BTCUSDT"]
    assert rows[0] == {"symbol": "CATEUSDT", "base": "CATE",
                       "name": "Catestein", "contract": "0xabc"}


def test_fetch_24h_tickers_converts_fraction_to_percent():
    """MEXC reports priceChangePercent as a fraction: 0.0196 means +1.96%."""
    with patch.object(mexc, "_get", return_value=_TICKER_24H):
        snap = mexc.fetch_24h_tickers()
    assert snap["BTCUSDT"]["change_pct"] == pytest.approx(1.96)
    assert snap["CATEUSDT"]["change_pct"] == pytest.approx(-23.79)
    assert snap["CATEUSDT"]["quote_volume"] == pytest.approx(140981.74)
    assert snap["CATEUSDT"]["price"] == pytest.approx(0.003782)


def test_fetch_24h_tickers_tolerates_missing_fields():
    with patch.object(mexc, "_get", return_value=[{"symbol": "XUSDT"}]):
        snap = mexc.fetch_24h_tickers()
    assert snap["XUSDT"] == {"price": 0.0, "quote_volume": 0.0, "change_pct": 0.0}
