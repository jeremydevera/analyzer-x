"""Unit tests for the MEXC dataflow (no network — every HTTP call is patched)."""

from unittest.mock import patch

import pandas as pd

import pytest

from tradingagents.dataflows import interface, mexc
from tradingagents.dataflows.config import get_config, set_config
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
    assert rows[0] == {"symbol": "CATEUSDT", "base": "CATE", "name": "Catestein",
                       "contract": "0xabc", "first_open_ms": None}


def test_fetch_usdt_symbols_carries_first_open_ms():
    """MEXC reports the listing instant directly; no kline probing needed."""
    info = {"symbols": [dict(_EXCHANGE_INFO["symbols"][0], firstOpenTime=1784505600000)]}
    with patch.object(mexc, "_get", return_value=info):
        rows = mexc.fetch_usdt_symbols()
    assert rows[0]["first_open_ms"] == 1784505600000


def test_fetch_usdt_symbols_tolerates_a_missing_first_open_time():
    """65 of 2129 symbols omit the field; they fall back to the kline probe."""
    with patch.object(mexc, "_get", return_value=_EXCHANGE_INFO):
        rows = mexc.fetch_usdt_symbols()
    assert rows[0]["first_open_ms"] is None


def test_poll_new_listings_reports_symbols_not_seen_before():
    info = {"symbols": [
        {"symbol": "OLDUSDT", "baseAsset": "OLD", "quoteAsset": "USDT",
         "isSpotTradingAllowed": True, "fullName": "Old", "contractAddress": "",
         "firstOpenTime": _ms_ago(days=5)},
        {"symbol": "FRESHUSDT", "baseAsset": "FRESH", "quoteAsset": "USDT",
         "isSpotTradingAllowed": True, "fullName": "Fresh Coin", "contractAddress": "",
         "firstOpenTime": _ms_ago(hours=1)},
    ]}
    with patch.object(mexc, "_get", return_value=info) as get:
        found, seen = mexc.poll_new_listings({"OLDUSDT"}, now_ms=_NOW_MS)
    assert get.call_count == 1                       # exactly one request
    assert [c["symbol"] for c in found] == ["FRESHUSDT"]
    assert found[0]["name"] == "Fresh Coin"
    assert found[0]["age_hours"] == pytest.approx(1.0)
    assert seen == {"OLDUSDT", "FRESHUSDT"}


def test_poll_new_listings_first_call_seeds_without_alerting():
    """An empty known-set must not announce all 1600 coins as new."""
    with patch.object(mexc, "_get", return_value=_EXCHANGE_INFO):
        found, seen = mexc.poll_new_listings(set(), now_ms=_NOW_MS)
    assert found == []
    assert seen == {"CATEUSDT", "BTCUSDT"}


def test_poll_new_listings_ignores_coins_older_than_the_alert_window():
    info = {"symbols": [
        {"symbol": "STALEUSDT", "baseAsset": "STALE", "quoteAsset": "USDT",
         "isSpotTradingAllowed": True, "fullName": "Stale", "contractAddress": "",
         "firstOpenTime": _ms_ago(days=40)},
    ]}
    with patch.object(mexc, "_get", return_value=info):
        found, seen = mexc.poll_new_listings({"SOMETHINGELSE"}, now_ms=_NOW_MS,
                                             max_age_hours=48)
    assert found == []                                # unseen, but far too old
    assert "STALEUSDT" in seen


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


_HOUR_MS = 3_600_000


def test_first_trade_ms_uses_the_earliest_hourly_candle():
    """Hourly candles give the hour precision an "age < 1 day" filter needs."""
    rows = [_kline(1784505600000 + i * _HOUR_MS) for i in range(30)]
    with patch.object(mexc, "_klines", return_value=rows) as kl:
        assert mexc.first_trade_ms("CATEUSDT") == 1784505600000
    assert kl.call_args[0][1] == "60m"


def test_first_trade_ms_falls_back_to_daily_when_hourly_is_saturated():
    """A saturated hourly window only proves the coin is older than ~20 days."""
    hourly = [_kline(1784505600000 + i * _HOUR_MS) for i in range(500)]
    daily = [_kline(1780000000000 + i * 86_400_000) for i in range(40)]

    def by_interval(symbol, interval, limit):
        return hourly if interval == "60m" else daily

    with patch.object(mexc, "_klines", side_effect=by_interval):
        assert mexc.first_trade_ms("CATEUSDT") == 1780000000000


def test_first_trade_ms_returns_none_when_both_probes_are_saturated():
    def saturated(symbol, interval, limit):
        step = _HOUR_MS if interval == "60m" else 86_400_000
        return [_kline(1780000000000 + i * step) for i in range(limit)]

    with patch.object(mexc, "_klines", side_effect=saturated):
        assert mexc.first_trade_ms("BTCUSDT") is None


def test_first_trade_ms_returns_none_when_there_are_no_candles():
    with patch.object(mexc, "_klines", return_value=[]):
        assert mexc.first_trade_ms("GHOSTUSDT") is None


@pytest.mark.parametrize("listed_ms,now_ms,expected", [
    (0, 5 * _HOUR_MS, 5.0),
    (0, 36 * _HOUR_MS, 36.0),
    (0, 0, 0.0),
])
def test_age_hours(listed_ms, now_ms, expected):
    assert mexc.age_hours(listed_ms, now_ms) == pytest.approx(expected)


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


@pytest.mark.parametrize("listed,today,expected_age", [
    ("2026-07-29", "2026-07-29", 0),
    ("2026-06-29", "2026-07-29", 30),
    ("2026-06-28", "2026-07-29", 31),
])
def test_age_days_between_dates(listed, today, expected_age):
    """Date arithmetic only — range membership is the age-filter's job now."""
    assert mexc.age_days(listed, today) == expected_age


# --- The screener sweep ----------------------------------------------------


_NOW_MS = 1785000000000          # fixed "now" so ages are deterministic
_DAY_MS = 86_400_000


def _ms_ago(**kw):
    """Epoch ms for a moment in the past, e.g. _ms_ago(days=9)."""
    hours = kw.get("hours", 0) + kw.get("days", 0) * 24 + kw.get("weeks", 0) * 168
    return _NOW_MS - int(hours * _HOUR_MS)


def _screen_patches(monkeypatch, tmp_path, *, ages, first_dates):
    """Patch the three network stages of the sweep and point the cache at tmp_path.

    ``first_dates`` maps symbol -> epoch ms of first trade (or None).
    """
    # first_open_ms mirrors what MEXC now reports in the symbol record; symbols
    # mapped to None fall through to the kline probe.
    monkeypatch.setattr(mexc, "fetch_usdt_symbols", lambda: [
        {"symbol": s, "base": s[:-4], "name": f"{s[:-4]} Coin", "contract": "",
         "first_open_ms": first_dates.get(s)}
        for s in ages
    ])
    monkeypatch.setattr(mexc, "fetch_24h_tickers", lambda: {
        "NEWUSDT": {"price": 1.0, "quote_volume": 200_000.0, "change_pct": 12.0},
        "DUSTUSDT": {"price": 0.1, "quote_volume": 1_000.0, "change_pct": 5.0},
        "OLDUSDT": {"price": 9.0, "quote_volume": 900_000.0, "change_pct": 1.0},
    })
    monkeypatch.setattr(mexc, "monthly_candle_count", lambda s: ages[s])
    monkeypatch.setattr(mexc, "first_trade_ms", lambda s: first_dates.get(s))
    monkeypatch.setattr(mexc, "_cache_dir", lambda: str(tmp_path))
    monkeypatch.setattr(mexc, "_THROTTLE_SLEEP", 0.0)
    monkeypatch.setattr(mexc, "_now_ms", lambda: _NOW_MS)


# --- Age-range filtering ---------------------------------------------------


def _range_fixture(monkeypatch, tmp_path):
    """Three in-window coins at 5 hours, 9 days, and 3 weeks old."""
    _screen_patches(
        monkeypatch, tmp_path,
        ages={"NEWUSDT": 1, "DUSTUSDT": 1, "OLDUSDT": 2},
        first_dates={"NEWUSDT": _ms_ago(hours=5),
                     "DUSTUSDT": _ms_ago(days=9),
                     "OLDUSDT": _ms_ago(weeks=3)},
    )


def test_range_defaults_include_everything_in_the_window(monkeypatch, tmp_path):
    _range_fixture(monkeypatch, tmp_path)
    result = mexc.screen_new_listings(min_quote_volume=0.0)
    assert {c.symbol for c in result.coins} == {"NEWUSDT", "DUSTUSDT", "OLDUSDT"}


def test_range_one_hour_to_one_week(monkeypatch, tmp_path):
    """The user's example: 1hr to 1 week keeps the 5-hour coin, drops the rest."""
    _range_fixture(monkeypatch, tmp_path)
    result = mexc.screen_new_listings(min_quote_volume=0.0,
                                      min_age_hours=1, max_age_hours=168)
    assert [c.symbol for c in result.coins] == ["NEWUSDT"]


def test_range_one_day_to_one_week(monkeypatch, tmp_path):
    """1d to 1 week excludes the 5-hour coin (too new) and the 3-week coin."""
    _range_fixture(monkeypatch, tmp_path)
    result = mexc.screen_new_listings(min_quote_volume=0.0,
                                      min_age_hours=24, max_age_hours=168)
    assert [c.symbol for c in result.coins] == []


def test_range_one_week_to_two_weeks(monkeypatch, tmp_path):
    _range_fixture(monkeypatch, tmp_path)
    result = mexc.screen_new_listings(min_quote_volume=0.0,
                                      min_age_hours=168, max_age_hours=336)
    assert [c.symbol for c in result.coins] == ["DUSTUSDT"]


def test_range_bounds_are_inclusive(monkeypatch, tmp_path):
    _range_fixture(monkeypatch, tmp_path)
    exact = mexc.screen_new_listings(min_quote_volume=0.0,
                                     min_age_hours=5, max_age_hours=5)
    assert [c.symbol for c in exact.coins] == ["NEWUSDT"]


def test_range_reports_how_many_it_hid(monkeypatch, tmp_path):
    _range_fixture(monkeypatch, tmp_path)
    result = mexc.screen_new_listings(min_quote_volume=0.0,
                                      min_age_hours=1, max_age_hours=168)
    assert result.hidden_by_age == 2


def test_age_hours_are_recomputed_from_the_cache_not_frozen(monkeypatch, tmp_path):
    """A cached sweep read an hour later must report an age an hour larger."""
    _range_fixture(monkeypatch, tmp_path)
    first = mexc.screen_new_listings(min_quote_volume=0.0)
    age_then = next(c for c in first.coins if c.symbol == "NEWUSDT").age_hours

    monkeypatch.setattr(mexc, "_now_ms", lambda: _NOW_MS + 2 * _HOUR_MS)
    later = mexc.cached_listings(min_quote_volume=0.0)
    age_now = next(c for c in later.coins if c.symbol == "NEWUSDT").age_hours
    assert age_now == pytest.approx(age_then + 2.0)


def test_cached_listings_applies_the_age_range(monkeypatch, tmp_path):
    _range_fixture(monkeypatch, tmp_path)
    mexc.screen_new_listings(min_quote_volume=0.0)
    result = mexc.cached_listings(min_quote_volume=0.0,
                                  min_age_hours=168, max_age_hours=336)
    assert [c.symbol for c in result.coins] == ["DUSTUSDT"]


def test_age_days_still_available_for_display(monkeypatch, tmp_path):
    _range_fixture(monkeypatch, tmp_path)
    result = mexc.screen_new_listings(min_quote_volume=0.0)
    by_symbol = {c.symbol: c for c in result.coins}
    assert by_symbol["DUSTUSDT"].age_days == 9
    assert by_symbol["NEWUSDT"].age_days == 0


def test_screen_returns_only_recent_liquid_coins(monkeypatch, tmp_path):
    _screen_patches(
        monkeypatch, tmp_path,
        ages={"NEWUSDT": 1, "DUSTUSDT": 1, "OLDUSDT": 3},
        first_dates={"NEWUSDT": _ms_ago(days=9), "DUSTUSDT": _ms_ago(days=8)},
    )
    result = mexc.screen_new_listings(min_quote_volume=50_000.0)

    assert [c.symbol for c in result.coins] == ["NEWUSDT"]
    coin = result.coins[0]
    assert coin.listed_date == mexc._ms_to_date(_ms_ago(days=9))
    assert coin.age_days == 9
    assert coin.quote_volume == pytest.approx(200_000.0)
    assert coin.change_pct == pytest.approx(12.0)
    assert result.scanned == 3
    assert result.hidden_by_volume == 1


def test_screen_include_all_keeps_dust(monkeypatch, tmp_path):
    _screen_patches(
        monkeypatch, tmp_path,
        ages={"NEWUSDT": 1, "DUSTUSDT": 1, "OLDUSDT": 3},
        first_dates={"NEWUSDT": _ms_ago(days=9), "DUSTUSDT": _ms_ago(days=8)},
    )
    result = mexc.screen_new_listings(min_quote_volume=50_000.0,
                                      include_all=True)
    assert {c.symbol for c in result.coins} == {"NEWUSDT", "DUSTUSDT"}


def test_screen_sorts_newest_first(monkeypatch, tmp_path):
    _screen_patches(
        monkeypatch, tmp_path,
        ages={"NEWUSDT": 1, "DUSTUSDT": 1, "OLDUSDT": 3},
        first_dates={"NEWUSDT": _ms_ago(days=19), "DUSTUSDT": _ms_ago(days=4)},
    )
    result = mexc.screen_new_listings(min_quote_volume=0.0)
    assert [c.symbol for c in result.coins] == ["DUSTUSDT", "NEWUSDT"]


def test_screen_excludes_coins_outside_the_window(monkeypatch, tmp_path):
    _screen_patches(
        monkeypatch, tmp_path,
        ages={"NEWUSDT": 2, "DUSTUSDT": 1, "OLDUSDT": 3},
        first_dates={"NEWUSDT": _ms_ago(days=89), "DUSTUSDT": _ms_ago(days=4)},
    )
    result = mexc.screen_new_listings(min_quote_volume=0.0)
    assert [c.symbol for c in result.coins] == ["DUSTUSDT"]


def test_screen_counts_unresolved_symbols(monkeypatch, tmp_path):
    """A symbol whose probe keeps failing is reported, never silently dropped."""
    _screen_patches(monkeypatch, tmp_path,
                    ages={"NEWUSDT": 1, "DUSTUSDT": 1, "OLDUSDT": 3},
                    first_dates={"NEWUSDT": _ms_ago(days=9)})

    def boom(symbol):
        if symbol == "DUSTUSDT":
            raise mexc.MexcRateLimited("0")
        return {"NEWUSDT": 1, "OLDUSDT": 3}[symbol]

    monkeypatch.setattr(mexc, "monthly_candle_count", boom)

    result = mexc.screen_new_listings(min_quote_volume=0.0)
    assert result.unresolved == 1
    assert [c.symbol for c in result.coins] == ["NEWUSDT"]


def test_screen_reads_fresh_cache_without_network(monkeypatch, tmp_path):
    _screen_patches(monkeypatch, tmp_path,
                    ages={"NEWUSDT": 1, "DUSTUSDT": 1, "OLDUSDT": 3},
                    first_dates={"NEWUSDT": _ms_ago(days=9), "DUSTUSDT": _ms_ago(days=8)})
    first = mexc.screen_new_listings(min_quote_volume=0.0)
    assert first.from_cache is False

    def explode():
        raise AssertionError("cache hit must not hit the network")

    monkeypatch.setattr(mexc, "fetch_usdt_symbols", explode)
    second = mexc.screen_new_listings(min_quote_volume=0.0)
    assert second.from_cache is True
    assert [c.symbol for c in second.coins] == [c.symbol for c in first.coins]


def test_screen_force_refresh_bypasses_cache(monkeypatch, tmp_path):
    _screen_patches(monkeypatch, tmp_path,
                    ages={"NEWUSDT": 1, "DUSTUSDT": 1, "OLDUSDT": 3},
                    first_dates={"NEWUSDT": _ms_ago(days=9), "DUSTUSDT": _ms_ago(days=8)})
    mexc.screen_new_listings(min_quote_volume=0.0)
    result = mexc.screen_new_listings(min_quote_volume=0.0,
                                      force_refresh=True)
    assert result.from_cache is False


def test_screen_serves_expired_cache_when_refresh_fails(monkeypatch, tmp_path):
    _screen_patches(monkeypatch, tmp_path,
                    ages={"NEWUSDT": 1, "DUSTUSDT": 1, "OLDUSDT": 3},
                    first_dates={"NEWUSDT": _ms_ago(days=9), "DUSTUSDT": _ms_ago(days=8)})
    mexc.screen_new_listings(min_quote_volume=0.0)

    def dead():
        raise mexc.MexcUnavailable("all hosts blocked")

    monkeypatch.setattr(mexc, "fetch_usdt_symbols", dead)
    result = mexc.screen_new_listings(min_quote_volume=0.0,
                                      force_refresh=True)
    assert result.from_cache is True
    assert result.stale is True


def test_cached_listings_returns_none_without_a_cache(monkeypatch, tmp_path):
    """The UI must be able to render instantly instead of sweeping on load."""
    monkeypatch.setattr(mexc, "_cache_dir", lambda: str(tmp_path))
    assert mexc.cached_listings() is None


def test_cached_listings_never_hits_the_network(monkeypatch, tmp_path):
    _screen_patches(monkeypatch, tmp_path,
                    ages={"NEWUSDT": 1, "DUSTUSDT": 1, "OLDUSDT": 3},
                    first_dates={"NEWUSDT": _ms_ago(days=9), "DUSTUSDT": _ms_ago(days=8)})
    mexc.screen_new_listings(min_quote_volume=0.0)

    def explode():
        raise AssertionError("cached_listings must not sweep")

    monkeypatch.setattr(mexc, "fetch_usdt_symbols", explode)
    result = mexc.cached_listings(min_quote_volume=0.0)
    assert result is not None
    assert result.from_cache is True
    assert result.stale is False
    assert [c.symbol for c in result.coins] == ["DUSTUSDT", "NEWUSDT"]


def test_cached_listings_flags_a_previous_day_as_stale(monkeypatch, tmp_path):
    _screen_patches(monkeypatch, tmp_path,
                    ages={"NEWUSDT": 1, "DUSTUSDT": 1, "OLDUSDT": 3},
                    first_dates={"NEWUSDT": _ms_ago(days=9), "DUSTUSDT": _ms_ago(days=8)})
    mexc.screen_new_listings(min_quote_volume=0.0)

    # Read it back a day later: new listings have appeared since, so the sweep
    # is stale even though the file is intact.
    monkeypatch.setattr(mexc, "_now_ms", lambda: _NOW_MS + 25 * _HOUR_MS)
    result = mexc.cached_listings(min_quote_volume=0.0)
    assert result is not None
    assert result.stale is True


def test_cached_listings_applies_the_volume_floor(monkeypatch, tmp_path):
    _screen_patches(monkeypatch, tmp_path,
                    ages={"NEWUSDT": 1, "DUSTUSDT": 1, "OLDUSDT": 3},
                    first_dates={"NEWUSDT": _ms_ago(days=9), "DUSTUSDT": _ms_ago(days=8)})
    mexc.screen_new_listings(min_quote_volume=0.0)
    result = mexc.cached_listings(min_quote_volume=50_000.0)
    assert [c.symbol for c in result.coins] == ["NEWUSDT"]
    assert result.hidden_by_volume == 1


def test_screen_raises_when_blocked_and_no_cache(monkeypatch, tmp_path):
    _screen_patches(monkeypatch, tmp_path, ages={}, first_dates={})

    def dead():
        raise mexc.MexcUnavailable("all hosts blocked")

    monkeypatch.setattr(mexc, "fetch_usdt_symbols", dead)
    with pytest.raises(mexc.MexcUnavailable):
        mexc.screen_new_listings()


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


def test_intraday_ohlcv_builds_a_frame_with_minute_stamps():
    rows = [[1784505600000 + i * 60_000, "1.0", "1.2", "0.9", str(1.0 + i / 100),
             "10.0", 0, "0"] for i in range(5)]
    with patch.object(mexc, "_klines", return_value=rows) as kl:
        df = mexc.intraday_ohlcv("XPLK-USD", interval="1m", limit=5)
    assert kl.call_args[0][1] == "1m"
    assert list(df.columns) == ["Date", "Open", "High", "Low", "Close", "Volume"]
    assert len(df) == 5
    assert df["Close"].iloc[-1] == pytest.approx(1.04)
    # Minute bars must keep their time, not be flattened to a date.
    assert df["Date"].iloc[1] - df["Date"].iloc[0] == pd.Timedelta(minutes=1)


def test_intraday_ohlcv_raises_when_the_symbol_has_no_candles():
    with patch.object(mexc, "_klines", return_value=[]):
        with pytest.raises(NoMarketDataError):
            mexc.intraday_ohlcv("GHOST-USD")


def test_intraday_ohlcv_accepts_the_supported_intervals():
    rows = [[1784505600000, "1", "1", "1", "1", "1", 0, "0"]]
    for interval in ("1m", "5m", "15m", "60m", "4h", "1d"):
        with patch.object(mexc, "_klines", return_value=rows):
            assert len(mexc.intraday_ohlcv("X-USD", interval=interval)) == 1


def test_intraday_ohlcv_rejects_an_unsupported_interval():
    with pytest.raises(ValueError, match="interval"):
        mexc.intraday_ohlcv("X-USD", interval="7s")


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


# --- Vendor registration ---------------------------------------------------


def test_mexc_is_registered_for_price_and_indicator_methods():
    assert "mexc" in interface.VENDOR_METHODS["get_stock_data"]
    assert "mexc" in interface.VENDOR_METHODS["get_indicators"]
    assert "mexc" in interface.VENDOR_LIST


def test_route_to_vendor_uses_mexc_when_configured():
    set_config({"data_vendors": {"core_stock_apis": "mexc"}})
    try:
        with patch.object(mexc, "_klines", return_value=_DAILY):
            out = interface.route_to_vendor(
                "get_stock_data", "CATE-USD", "2026-07-20", "2026-07-22")
        assert "MEXC spot data" in out
    finally:
        set_config({"data_vendors": {"core_stock_apis": "yfinance"}})


def test_default_config_still_prefers_yfinance():
    """Stock runs must not be re-routed by this feature."""
    assert get_config()["data_vendors"]["core_stock_apis"] == "yfinance"
    assert get_config()["data_vendors"]["technical_indicators"] == "yfinance"


def test_include_twitter_defaults_off():
    assert get_config().get("include_twitter") is False
