"""Unit tests for the MEXC dataflow (no network — every HTTP call is patched)."""

from unittest.mock import patch

import pytest

from tradingagents.dataflows import mexc
from tradingagents.dataflows.errors import NoMarketDataError
from tradingagents.dataflows.stockstats_utils import INDICATOR_DESCRIPTIONS
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


# --- Listing-age detection -------------------------------------------------


def _kline(open_ms):
    """One MEXC kline row: [openTime, o, h, l, c, vol, closeTime, quoteVol]."""
    return [open_ms, "1.0", "2.0", "0.5", "1.5", "100.0", open_ms + 86_400_000, "150.0"]


def test_monthly_candle_count_reports_row_count():
    with patch.object(mexc, "_get", return_value=[_kline(1), _kline(2)]):
        assert mexc.monthly_candle_count("CATEUSDT") == 2


def test_is_recent_listing_accepts_fewer_than_three_monthly_candles():
    assert mexc.is_recent_listing_candidate(1) is True
    assert mexc.is_recent_listing_candidate(2) is True
    assert mexc.is_recent_listing_candidate(3) is False


def test_first_trade_date_uses_the_earliest_daily_candle():
    # 1783036800000 == 2026-07-03T00:00:00Z
    with patch.object(mexc, "_get", return_value=[_kline(1783036800000),
                                                  _kline(1783123200000)]):
        assert mexc.first_trade_date("CATEUSDT") == "2026-07-03"


def test_first_trade_date_returns_none_when_history_is_saturated():
    """500 daily rows means the true first trade is older than the window."""
    rows = [_kline(1783036800000 + i * 86_400_000) for i in range(500)]
    with patch.object(mexc, "_get", return_value=rows):
        assert mexc.first_trade_date("BTCUSDT") is None


def test_first_trade_date_returns_none_when_no_candles():
    with patch.object(mexc, "_get", return_value=[]):
        assert mexc.first_trade_date("GHOSTUSDT") is None


@pytest.mark.parametrize("listed,today,expected_age,within", [
    ("2026-07-29", "2026-07-29", 0, True),
    ("2026-06-29", "2026-07-29", 30, True),    # exactly 30 days -> inside
    ("2026-06-28", "2026-07-29", 31, False),   # 31 days -> outside
])
def test_age_days_and_window_boundary(listed, today, expected_age, within):
    age = mexc.age_days(listed, today)
    assert age == expected_age
    assert (age <= mexc.WINDOW_DAYS) is within


# --- The screener sweep ----------------------------------------------------


def _screen_patches(monkeypatch, tmp_path, *, ages, first_dates):
    """Patch the three network stages of the sweep and point the cache at tmp_path."""
    monkeypatch.setattr(mexc, "fetch_usdt_symbols", lambda: [
        {"symbol": s, "base": s[:-4], "name": f"{s[:-4]} Coin", "contract": ""}
        for s in ages
    ])
    monkeypatch.setattr(mexc, "fetch_24h_tickers", lambda: {
        "NEWUSDT": {"price": 1.0, "quote_volume": 200_000.0, "change_pct": 12.0},
        "DUSTUSDT": {"price": 0.1, "quote_volume": 1_000.0, "change_pct": 5.0},
        "OLDUSDT": {"price": 9.0, "quote_volume": 900_000.0, "change_pct": 1.0},
    })
    monkeypatch.setattr(mexc, "monthly_candle_count", lambda s: ages[s])
    monkeypatch.setattr(mexc, "first_trade_date", lambda s: first_dates.get(s))
    monkeypatch.setattr(mexc, "_cache_dir", lambda: str(tmp_path))
    monkeypatch.setattr(mexc, "_THROTTLE_SLEEP", 0.0)


def test_screen_returns_only_recent_liquid_coins(monkeypatch, tmp_path):
    _screen_patches(
        monkeypatch, tmp_path,
        ages={"NEWUSDT": 1, "DUSTUSDT": 1, "OLDUSDT": 3},
        first_dates={"NEWUSDT": "2026-07-20", "DUSTUSDT": "2026-07-21"},
    )
    result = mexc.screen_new_listings(today="2026-07-29", min_quote_volume=50_000.0)

    assert [c.symbol for c in result.coins] == ["NEWUSDT"]
    coin = result.coins[0]
    assert coin.listed_date == "2026-07-20"
    assert coin.age_days == 9
    assert coin.quote_volume == pytest.approx(200_000.0)
    assert coin.change_pct == pytest.approx(12.0)
    assert result.scanned == 3
    assert result.hidden_by_volume == 1


def test_screen_include_all_keeps_dust(monkeypatch, tmp_path):
    _screen_patches(
        monkeypatch, tmp_path,
        ages={"NEWUSDT": 1, "DUSTUSDT": 1, "OLDUSDT": 3},
        first_dates={"NEWUSDT": "2026-07-20", "DUSTUSDT": "2026-07-21"},
    )
    result = mexc.screen_new_listings(today="2026-07-29", min_quote_volume=50_000.0,
                                      include_all=True)
    assert {c.symbol for c in result.coins} == {"NEWUSDT", "DUSTUSDT"}


def test_screen_sorts_newest_first(monkeypatch, tmp_path):
    _screen_patches(
        monkeypatch, tmp_path,
        ages={"NEWUSDT": 1, "DUSTUSDT": 1, "OLDUSDT": 3},
        first_dates={"NEWUSDT": "2026-07-10", "DUSTUSDT": "2026-07-25"},
    )
    result = mexc.screen_new_listings(today="2026-07-29", min_quote_volume=0.0)
    assert [c.symbol for c in result.coins] == ["DUSTUSDT", "NEWUSDT"]


def test_screen_excludes_coins_outside_the_window(monkeypatch, tmp_path):
    _screen_patches(
        monkeypatch, tmp_path,
        ages={"NEWUSDT": 2, "DUSTUSDT": 1, "OLDUSDT": 3},
        first_dates={"NEWUSDT": "2026-05-01", "DUSTUSDT": "2026-07-25"},
    )
    result = mexc.screen_new_listings(today="2026-07-29", min_quote_volume=0.0)
    assert [c.symbol for c in result.coins] == ["DUSTUSDT"]


def test_screen_counts_unresolved_symbols(monkeypatch, tmp_path):
    """A symbol whose probe keeps failing is reported, never silently dropped."""
    _screen_patches(monkeypatch, tmp_path,
                    ages={"NEWUSDT": 1, "DUSTUSDT": 1, "OLDUSDT": 3},
                    first_dates={"NEWUSDT": "2026-07-20"})

    def boom(symbol):
        if symbol == "DUSTUSDT":
            raise mexc.MexcRateLimited("0")
        return {"NEWUSDT": 1, "OLDUSDT": 3}[symbol]

    monkeypatch.setattr(mexc, "monthly_candle_count", boom)

    result = mexc.screen_new_listings(today="2026-07-29", min_quote_volume=0.0)
    assert result.unresolved == 1
    assert [c.symbol for c in result.coins] == ["NEWUSDT"]


def test_screen_reads_fresh_cache_without_network(monkeypatch, tmp_path):
    _screen_patches(monkeypatch, tmp_path,
                    ages={"NEWUSDT": 1, "DUSTUSDT": 1, "OLDUSDT": 3},
                    first_dates={"NEWUSDT": "2026-07-20", "DUSTUSDT": "2026-07-21"})
    first = mexc.screen_new_listings(today="2026-07-29", min_quote_volume=0.0)
    assert first.from_cache is False

    def explode():
        raise AssertionError("cache hit must not hit the network")

    monkeypatch.setattr(mexc, "fetch_usdt_symbols", explode)
    second = mexc.screen_new_listings(today="2026-07-29", min_quote_volume=0.0)
    assert second.from_cache is True
    assert [c.symbol for c in second.coins] == [c.symbol for c in first.coins]


def test_screen_force_refresh_bypasses_cache(monkeypatch, tmp_path):
    _screen_patches(monkeypatch, tmp_path,
                    ages={"NEWUSDT": 1, "DUSTUSDT": 1, "OLDUSDT": 3},
                    first_dates={"NEWUSDT": "2026-07-20", "DUSTUSDT": "2026-07-21"})
    mexc.screen_new_listings(today="2026-07-29", min_quote_volume=0.0)
    result = mexc.screen_new_listings(today="2026-07-29", min_quote_volume=0.0,
                                      force_refresh=True)
    assert result.from_cache is False


def test_screen_serves_expired_cache_when_refresh_fails(monkeypatch, tmp_path):
    _screen_patches(monkeypatch, tmp_path,
                    ages={"NEWUSDT": 1, "DUSTUSDT": 1, "OLDUSDT": 3},
                    first_dates={"NEWUSDT": "2026-07-20", "DUSTUSDT": "2026-07-21"})
    mexc.screen_new_listings(today="2026-07-29", min_quote_volume=0.0)

    def dead():
        raise mexc.MexcUnavailable("all hosts blocked")

    monkeypatch.setattr(mexc, "fetch_usdt_symbols", dead)
    result = mexc.screen_new_listings(today="2026-07-29", min_quote_volume=0.0,
                                      force_refresh=True)
    assert result.from_cache is True
    assert result.stale is True


def test_screen_raises_when_blocked_and_no_cache(monkeypatch, tmp_path):
    _screen_patches(monkeypatch, tmp_path, ages={}, first_dates={})

    def dead():
        raise mexc.MexcUnavailable("all hosts blocked")

    monkeypatch.setattr(mexc, "fetch_usdt_symbols", dead)
    with pytest.raises(mexc.MexcUnavailable):
        mexc.screen_new_listings(today="2026-07-29")


# --- OHLCV and the get_stock_data vendor ----------------------------------

_DAILY = [
    # 2026-07-20 .. 2026-07-22 (openTime, o, h, l, c, vol, closeTime, quoteVol)
    [1784505600000, "0.0015", "0.0160", "0.0015", "0.0044", "45918439.28",
     1784592000000, "269034.26"],
    [1784592000000, "0.0044", "0.0068", "0.0027", "0.0033", "38783978.54",
     1784678400000, "160393.56"],
    [1784678400000, "0.0033", "0.0046", "0.0032", "0.0040", "11649426.35",
     1784764800000, "45362.14"],
]


def test_daily_fixture_covers_the_expected_dates():
    """Guard the fixture itself: these epochs must be 2026-07-20..22."""
    assert [mexc._ms_to_date(r[0]) for r in _DAILY] == [
        "2026-07-20", "2026-07-21", "2026-07-22"]


def test_get_mexc_ohlcv_builds_a_typed_frame():
    with patch.object(mexc, "_klines", return_value=_DAILY):
        df = mexc.get_mexc_ohlcv("CATE-USD", "2026-07-20", "2026-07-22")
    assert list(df.columns) == ["Date", "Open", "High", "Low", "Close", "Volume"]
    assert len(df) == 3
    assert df["Close"].iloc[-1] == pytest.approx(0.0040)
    assert str(df["Date"].iloc[0].date()) == "2026-07-20"


def test_get_mexc_ohlcv_filters_to_the_requested_range():
    with patch.object(mexc, "_klines", return_value=_DAILY):
        df = mexc.get_mexc_ohlcv("CATE-USD", "2026-07-21", "2026-07-21")
    assert len(df) == 1
    assert str(df["Date"].iloc[0].date()) == "2026-07-21"


def test_get_mexc_ohlcv_raises_no_market_data_when_empty():
    with patch.object(mexc, "_klines", return_value=[]):
        with pytest.raises(NoMarketDataError) as exc:
            mexc.get_mexc_ohlcv("GHOST-USD", "2026-07-01", "2026-07-29")
    assert exc.value.canonical == "GHOSTUSDT"


def test_get_mexc_ohlcv_raises_when_range_excludes_all_rows():
    with patch.object(mexc, "_klines", return_value=_DAILY):
        with pytest.raises(NoMarketDataError):
            mexc.get_mexc_ohlcv("CATE-USD", "2026-01-01", "2026-01-31")


def test_get_mexc_stock_data_returns_annotated_csv():
    with patch.object(mexc, "_klines", return_value=_DAILY):
        out = mexc.get_mexc_stock_data("CATE-USD", "2026-07-20", "2026-07-22")
    lines = out.splitlines()
    assert lines[0].startswith("# MEXC spot data for CATEUSDT (from CATE-USD)")
    assert "# Total records: 3" in out
    header = next(ln for ln in lines if ln.startswith("Date,"))
    assert header == "Date,Open,High,Low,Close,Volume"


# --- Indicators ------------------------------------------------------------


def test_indicator_descriptions_are_shared_and_populated():
    for key in ("close_50_sma", "rsi", "macd", "atr", "vwma", "boll_ub"):
        assert key in INDICATOR_DESCRIPTIONS
        assert len(INDICATOR_DESCRIPTIONS[key]) > 20


def test_get_mexc_indicators_reports_values_per_date():
    # 80 consecutive daily candles ending 2026-10-07, so rsi has enough input.
    start_ms = 1784505600000
    rows = [
        [start_ms + i * 86_400_000, "1.0", "1.2", "0.9",
         str(1.0 + i / 100), "1000.0", 0, "0"]
        for i in range(80)
    ]
    last_date = mexc._ms_to_date(rows[-1][0])
    with patch.object(mexc, "_klines", return_value=rows):
        out = mexc.get_mexc_indicators("CATE-USD", "rsi", last_date, 3)
    assert "## rsi values" in out
    assert out.count(last_date[:8]) >= 3          # several dates in that month
    assert INDICATOR_DESCRIPTIONS["rsi"] in out


def test_get_mexc_indicators_rejects_unknown_indicator():
    with pytest.raises(ValueError, match="not supported"):
        mexc.get_mexc_indicators("CATE-USD", "not_an_indicator", "2026-07-29", 3)
