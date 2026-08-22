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
def _offline_clock(monkeypatch):
    """preflight() checks the clock, which reached MEXC over the real network in
    every preflight test. They passed only because a failed check is treated as
    inconclusive — passing for the wrong reason, and flaky offline."""
    from tradingagents.dataflows import mexc_futures as _fx
    monkeypatch.setattr(_fx, "clock_skew_ms", lambda: 0)


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
    with patch.object(mexc, "_klines", return_value=_DAILY), pytest.raises(NoMarketDataError):
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
    with patch.object(mexc, "_klines", return_value=[]), pytest.raises(NoMarketDataError):
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


def test_volume_floor_never_hides_a_fresh_coin(monkeypatch, tmp_path):
    """GPUBSC case: 20 minutes old, $2.7k volume, default $50k floor.

    The floor exists to bury old dead pairs; a newborn has had no time to
    accumulate volume, so coins younger than FRESH_VOLUME_EXEMPT_HOURS are
    always shown.
    """
    _screen_patches(
        monkeypatch, tmp_path,
        ages={"NEWUSDT": 1, "DUSTUSDT": 1, "OLDUSDT": 3},
        first_dates={"NEWUSDT": _ms_ago(days=9),
                     "DUSTUSDT": _ms_ago(hours=0.34)},   # ~20 minutes old
    )
    result = mexc.screen_new_listings(min_quote_volume=50_000.0)
    assert {c.symbol for c in result.coins} == {"NEWUSDT", "DUSTUSDT"}
    assert result.hidden_by_volume == 0


def test_volume_floor_still_hides_old_dust(monkeypatch, tmp_path):
    _screen_patches(
        monkeypatch, tmp_path,
        ages={"NEWUSDT": 1, "DUSTUSDT": 1, "OLDUSDT": 3},
        first_dates={"NEWUSDT": _ms_ago(days=9),
                     "DUSTUSDT": _ms_ago(days=8)},       # well past the exemption
    )
    result = mexc.screen_new_listings(min_quote_volume=50_000.0)
    assert [c.symbol for c in result.coins] == ["NEWUSDT"]
    assert result.hidden_by_volume == 1


def test_merge_new_listings_injects_into_the_cache(monkeypatch, tmp_path):
    """A just-opened coin joins the cached sweep without a full rescan."""
    _screen_patches(
        monkeypatch, tmp_path,
        ages={"NEWUSDT": 1, "DUSTUSDT": 1, "OLDUSDT": 3},
        first_dates={"NEWUSDT": _ms_ago(days=9), "DUSTUSDT": _ms_ago(days=8)},
    )
    mexc.screen_new_listings(min_quote_volume=0.0)       # seed the cache

    monkeypatch.setattr(mexc, "fetch_24h_tickers", lambda: {
        "FRESHUSDT": {"price": 0.02, "quote_volume": 2_700.0, "change_pct": 299.0}})
    added = mexc.merge_new_listings([{
        "symbol": "FRESHUSDT", "base": "FRESH", "name": "Fresh Coin",
        "contract": "0xf", "first_open_ms": _ms_ago(hours=0.3),
        "listed_date": mexc._ms_to_date(_ms_ago(hours=0.3))}])
    assert added == 1

    result = mexc.cached_listings(min_quote_volume=50_000.0)
    by_symbol = {c.symbol: c for c in result.coins}
    assert "FRESHUSDT" in by_symbol                       # visible despite $2.7k
    assert by_symbol["FRESHUSDT"].quote_volume == pytest.approx(2_700.0)
    # merging the same coin again is a no-op
    assert mexc.merge_new_listings([{
        "symbol": "FRESHUSDT", "base": "FRESH", "name": "Fresh Coin",
        "contract": "0xf", "first_open_ms": _ms_ago(hours=0.3),
        "listed_date": mexc._ms_to_date(_ms_ago(hours=0.3))}]) == 0


# ===================== edge-proxy block vs missing key scope =================
# MEXC's edge proxy refuses the futures ORDER paths for requests whose
# User-Agent identifies a scripted client, answering with an HTML "Access
# Denied" and HTTP 403 before the API sees the request. That is indistinguishable
# from a permission failure unless it is detected explicitly, and it cost a long
# debugging session spent looking at key settings that were already correct.
import io
import json as _json
import urllib.error

import pytest

from tradingagents.dataflows import mexc_futures as fx

AKAMAI_DENY = (
    b"<HTML><HEAD>\n<TITLE>Access Denied</TITLE>\n</HEAD><BODY>\n"
    b"<H1>Access Denied</H1>\nYou don't have permission to access "
    b'"http://contract.mexc.com/api/v1/private/order/submit" on this server.'
)


def _keys(monkeypatch):
    monkeypatch.setenv("MEXC_API_KEY", "k" * 18)
    monkeypatch.setenv("MEXC_API_SECRET", "s" * 32)


def _http_error(code, body):
    def raiser(*a, **k):
        raise urllib.error.HTTPError("u", code, "err", {}, io.BytesIO(body))
    return raiser


def _ok(payload):
    class R:
        def read(self): return _json.dumps(payload).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False
    return lambda *a, **k: R()


def test_html_403_is_an_edge_block_not_a_permission_error(monkeypatch):
    _keys(monkeypatch)
    monkeypatch.setattr(fx.urllib.request, "urlopen",
                        _http_error(403, AKAMAI_DENY))
    with pytest.raises(fx.MexcFuturesEdgeBlocked) as exc:
        fx._request("POST", "/api/v1/private/order/submit", body={"vol": 1})
    assert "User-Agent" in exc.value.remedy
    # It must NOT be catchable as a key-scope problem: that conflation is the
    # bug this test exists to prevent.
    assert not isinstance(exc.value, fx.MexcFuturesForbidden)


def test_a_real_json_403_is_an_auth_failure_not_a_missing_scope(monkeypatch):
    """The edge-block branch must not swallow genuine 403 JSON — but a 403 is a
    CREDENTIAL problem, not a scope problem.

    This assertion was originally MexcFuturesForbidden. That was wrong: MEXC
    returns 403 for a bad signature, a stale clock, or a source IP outside the
    allowlist, none of which any permission checkbox fixes. Because preflight
    derived a scope name from the code, the UI printed "missing permission
    scopes: code None" and the branch naming the real cause was unreachable.
    """
    _keys(monkeypatch)
    monkeypatch.setattr(fx.urllib.request, "urlopen", _http_error(
        403, b'{"success":false,"code":403,"message":"no permission"}'))
    with pytest.raises(fx.MexcFuturesAuthFailed) as exc:
        fx._request("GET", "/api/v1/private/account/assets")
    assert "allowlist" in exc.value.remedy and "clock" in exc.value.remedy
    assert not isinstance(exc.value, fx.MexcFuturesForbidden)


def test_only_a_named_scope_reaches_missing_scopes(monkeypatch):
    """preflight must never invent a scope name out of a status code."""
    _keys(monkeypatch)
    monkeypatch.setattr(fx, "open_positions", lambda s=None: [])
    monkeypatch.setattr(fx, "write_probe", lambda: {"reached": True})

    def bad_sig():
        raise fx.MexcFuturesAuthFailed("code 2011: signature error", code=2011)

    monkeypatch.setattr(fx, "usdt_equity", bad_sig)
    # order_permission is True here, so preflight goes on to probe the stop
    # endpoint — a live call unless stubbed.
    monkeypatch.setattr(fx, "stop_probe", lambda: {"permitted": True,
                                                   "reason": "stubbed"})
    rep = fx.preflight("SPX500_USDT")
    assert rep["missing_scopes"] == [], "a signature error is not a scope"
    assert rep["auth_failed"] is True
    assert rep["ready"] is False
    assert any("allowlist" in r for r in rep["remedies"])


def test_a_scope_code_still_names_its_scope(monkeypatch):
    _keys(monkeypatch)
    monkeypatch.setattr(fx.urllib.request, "urlopen", _ok(
        {"success": False, "code": 704, "message": "enable write"}))
    with pytest.raises(fx.MexcFuturesForbidden) as exc:
        fx._request("POST", "/api/v1/private/order/cancel", body=[1])
    assert exc.value.scope == "trading information write"
    assert not isinstance(exc.value, fx.MexcFuturesAuthFailed)


def test_requests_always_carry_a_user_agent_the_edge_accepts(monkeypatch):
    """A bare urllib/requests UA is refused by MEXC — assert we never send one."""
    _keys(monkeypatch)
    seen = {}

    def capture(req, *a, **k):
        seen["ua"] = req.get_header("User-agent")
        class R:
            def read(self): return b'{"success":true,"code":0,"data":[]}'
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return R()

    monkeypatch.setattr(fx.urllib.request, "urlopen", capture)
    fx._request("GET", "/api/v1/private/position/open_positions")
    ua = (seen["ua"] or "").lower()
    assert ua, "no User-Agent sent — the edge proxy blocks the order paths"
    assert "urllib" not in ua and "python-requests" not in ua


# ============================ the write probe ===============================
def test_write_probe_cancels_and_never_submits_an_order(monkeypatch):
    """The order-permission probe must not be able to open a position.

    The probe it replaced submitted a real order with vol=0 and trusted MEXC to
    reject it; during diagnosis an equivalent probe DID open four real long
    positions. This test pins the contract: cancel-only, no instrument, no size.
    """
    _keys(monkeypatch)
    calls = []

    def capture(req, *a, **k):
        calls.append((req.get_method(), req.full_url,
                      (req.data or b"").decode()))
        class R:
            def read(self):
                return (b'{"success":true,"code":0,"data":[{"orderId":1,'
                        b'"errorCode":2040,"errorMsg":"order not exist"}]}')
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return R()

    monkeypatch.setattr(fx.urllib.request, "urlopen", capture)
    assert fx.write_probe()["reached"] is True
    assert len(calls) == 1
    method, url, body = calls[0]
    assert method == "POST"
    assert url.endswith("/api/v1/private/order/cancel")
    assert "submit" not in url
    assert body == "[1]"
    for forbidden in ("symbol", "vol", "side", "leverage", "openType"):
        assert forbidden not in body, f"probe body describes a trade: {body}"


def test_preflight_all_pass_shape(monkeypatch):
    _keys(monkeypatch)
    monkeypatch.setattr(fx, "usdt_equity", lambda: 163.2)
    monkeypatch.setattr(fx, "open_positions", lambda s=None: [])
    monkeypatch.setattr(fx, "write_probe", lambda: {"reached": True})
    monkeypatch.setattr(fx, "stop_probe",
                        lambda: {"permitted": True, "reason": "ok"})
    rep = fx.preflight("SPX500_USDT")
    assert rep["ready"] is True
    assert rep["can_rest_stop"] is True
    assert rep["order_permission"] is True
    assert rep["edge_blocked"] is False
    assert rep["missing_scopes"] == []


def test_preflight_reports_edge_block_separately_from_scopes(monkeypatch):
    """An edge block must not be rendered as "your key lacks a scope"."""
    _keys(monkeypatch)
    monkeypatch.setattr(fx, "usdt_equity", lambda: 163.2)
    monkeypatch.setattr(fx, "open_positions", lambda s=None: [])

    def blocked():
        raise fx.MexcFuturesEdgeBlocked("/api/v1/private/order/cancel")

    monkeypatch.setattr(fx, "write_probe", blocked)
    rep = fx.preflight("SPX500_USDT")
    assert rep["ready"] is False
    assert rep["order_permission"] is False
    assert rep["edge_blocked"] is True
    assert rep["missing_scopes"] == [], "edge block is not a missing scope"
    assert any("User-Agent" in r for r in rep["remedies"])


# ======================= signing with a list body ===========================
def test_list_body_signs_the_exact_bytes_that_are_sent(monkeypatch):
    """order/cancel takes a JSON array; the signed string and the wire bytes
    must be identical or MEXC answers with a signature failure that looks like a
    permission problem."""
    _keys(monkeypatch)
    seen = {}

    def capture(req, *a, **k):
        seen["body"] = (req.data or b"").decode()
        seen["sig"] = req.get_header("Signature")
        seen["ts"] = req.get_header("Request-time")
        class R:
            def read(self): return b'{"success":true,"code":0,"data":[]}'
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return R()

    monkeypatch.setattr(fx.urllib.request, "urlopen", capture)
    fx._request("POST", "/api/v1/private/order/cancel", body=[1])
    expected = fx.sign("k" * 18, "s" * 32, seen["ts"], None, [1])
    assert seen["sig"] == expected
    assert seen["body"] == "[1]"


def test_dict_body_signing_is_unchanged_by_the_list_support():
    """sort_keys must still apply to dict bodies — the whole signature depends
    on it."""
    body = {"vol": 1, "symbol": "SPX500_USDT", "side": 1}
    assert fx._param_string(None, body) == \
        '{"side":1,"symbol":"SPX500_USDT","vol":1}'
    assert fx._param_string(None, [1, 2]) == "[1,2]"


# ============ exchange-resting stops (the point of the whole exercise) ======
def test_a_limit_take_profit_on_the_position_record_is_refused():
    """MEXC accepts it and attaches NOTHING.

    Verified against a real position: the request returned success and the
    resulting record read back `tp=None tpType=None`, with only the stop
    attached. A take-profit that silently does not exist is the worst failure
    available here, so this path refuses rather than lying. The target belongs in
    a resting limit close order.
    """
    with pytest.raises(fx.MexcFuturesError) as exc:
        fx.place_position_stop("SPX500_USDT", 1, 4, stop_loss_price=6944.0,
                               take_profit_price=7870.0,
                               take_profit_type=fx.SL_LIMIT)
    assert "silently ignores" in str(exc.value)
    assert "limit close order" in str(exc.value)


def test_a_market_take_profit_sends_only_the_trigger_price():
    b = fx.place_position_stop("SPX500_USDT", 1, 4, stop_loss_price=6944.0,
                               take_profit_price=7870.0,
                               take_profit_type=fx.SL_MARKET)["request"]
    assert b["takeProfitPrice"] == 7870.0
    assert "takeProfitOrderPrice" not in b


def test_a_market_stop_omits_the_order_price():
    b = fx.place_position_stop("SPX500_USDT", 1, 4,
                               stop_loss_price=6944.0)["request"]
    assert b["stopLossPrice"] == 6944.0
    assert b["stopLossType"] == fx.SL_MARKET
    assert "stopLossOrderPrice" not in b


def test_a_limit_stop_needs_both_prices():
    """Unlike the take-profit, a limit STOP requires the trigger AND the resting
    price — either alone answers 5001."""
    b = fx.place_position_stop("SPX500_USDT", 1, 4, stop_loss_price=6944.0,
                               stop_loss_type=fx.SL_LIMIT,
                               stop_loss_order_price=6940.0)["request"]
    assert b["stopLossPrice"] == 6944.0
    assert b["stopLossOrderPrice"] == 6940.0
    assert b["stopLossType"] == fx.SL_LIMIT


def test_the_position_record_carries_the_stop_at_market():
    """Default is a MARKET stop: getting out matters more than the price, and it
    is the only stop type MEXC actually attaches without a second price."""
    r = fx.place_position_stop("SPX500_USDT", 123, 4, stop_loss_price=6960.0)
    b = r["request"]
    assert r["dry_run"] is True, "must not reach the exchange by default"
    assert b["stopLossType"] == fx.SL_MARKET
    assert b["stopLossPrice"] == 6960.0
    assert "takeProfitPrice" not in b, "the target is a separate resting order"
    assert b["lossTrend"] == fx.TRIGGER_LAST, \
        "last price is the only basis that matches the backtest's candles"
    assert b["volType"] == fx.VOL_POSITION, "must cover the whole position"


def test_verify_bracket_requires_both_halves(monkeypatch):
    """The stop and the target live in different places, so both are read back.
    Either one missing means the position is not protected as intended."""
    monkeypatch.setattr(fx, "list_position_stops", lambda symbol=None: [
        {"positionId": "55", "errorCode": 0, "isFinished": 0, "state": 2}])
    monkeypatch.setattr(fx, "open_orders", lambda symbol=None: [
        {"orderId": "9", "side": fx.SIDE_CLOSE_LONG, "price": 7870.0}])
    v = fx.verify_bracket("SPX500_USDT", 55, 7870.0)
    assert v["stop_active"] and v["target_resting"] and v["protected"]
    assert v["target_order_id"] == "9"

    # target missing -> not protected, even though the stop is fine
    monkeypatch.setattr(fx, "open_orders", lambda symbol=None: [])
    v = fx.verify_bracket("SPX500_USDT", 55, 7870.0)
    assert v["stop_active"] is True and v["protected"] is False

    # a strategy with no target (buy and hold) needs only the stop
    assert fx.verify_bracket("SPX500_USDT", 55, None)["protected"] is True


def test_a_limit_stop_without_a_price_is_refused():
    with pytest.raises(fx.MexcFuturesError) as exc:
        fx.place_position_stop("SPX500_USDT", 1, 1, stop_loss_price=100.0,
                               stop_loss_type=fx.SL_LIMIT)
    assert "stop_loss_order_price" in str(exc.value)


def test_nonsense_sizes_and_prices_are_refused():
    for kw in ({"vol": 0}, {"vol": -3}):
        with pytest.raises(fx.MexcFuturesError):
            fx.place_position_stop("SPX500_USDT", 1, stop_loss_price=100.0, **kw)
    with pytest.raises(fx.MexcFuturesError):
        fx.place_position_stop("SPX500_USDT", 1, 1, stop_loss_price=0.0)


def test_a_stop_that_errored_is_not_protection():
    """Observed live: two of three real records on this account finished with
    errorCode 8912 and vol 0. MEXC accepting the request is not protection."""
    assert fx.stop_is_active({"errorCode": 0, "isFinished": 0, "state": 2})
    assert not fx.stop_is_active({"errorCode": 8912, "isFinished": 1, "state": 2})
    assert not fx.stop_is_active({"errorCode": 0, "isFinished": 1, "state": 3}), \
        "already triggered and finished is not still protecting"


def test_verify_reports_unprotected_when_every_record_failed(monkeypatch):
    monkeypatch.setattr(fx, "list_position_stops", lambda symbol=None: [
        {"positionId": "999", "errorCode": 8912, "isFinished": 1, "state": 2},
        {"positionId": "111", "errorCode": 0, "isFinished": 0, "state": 2},
    ])
    v = fx.verify_position_stop("SPX500_USDT", 999)
    assert v["protected"] is False
    assert v["error_codes"] == [8912]
    assert fx.verify_position_stop("SPX500_USDT", 111)["protected"] is True


def test_stop_probe_reads_a_validation_error_as_permitted(monkeypatch):
    """Rejecting a fake position id proves the endpoint authorised the key."""
    def boom(*a, **k):
        raise fx.MexcFuturesError("code 2009: Position is nonexistent or closed")
    monkeypatch.setattr(fx, "_request", boom)
    rep = fx.stop_probe()
    assert rep["permitted"] is True
    assert "2009" in rep["reason"]


def test_stop_probe_distinguishes_the_three_ways_it_can_be_blocked(monkeypatch):
    cases = [
        (fx.MexcFuturesEdgeBlocked("/api/v1/private/stoporder/place"), "edge proxy"),
        (fx.MexcFuturesForbidden("no", code=704, scope="trading information write",
                                 remedy="enable write"), "key scope"),
        (fx.MexcFuturesAuthFailed("code 2011: signature", code=2011), "credentials"),
    ]
    for err, expect in cases:
        def boom(*a, _e=err, **k):
            raise _e
        monkeypatch.setattr(fx, "_request", boom)
        rep = fx.stop_probe()
        assert rep["permitted"] is False
        assert rep["blocked_by"] == expect
        assert rep["remedy"], "a blocked probe must say what to do about it"


def test_stop_probe_never_names_an_instrument_it_could_open(monkeypatch):
    """The probe must not be able to create a position: no side, no order type,
    and a position id that cannot exist."""
    seen = {}
    monkeypatch.setattr(fx, "_request",
                        lambda m, p, **k: seen.update(method=m, path=p,
                                                      body=k.get("body")) or {})
    fx.stop_probe()
    assert seen["path"].endswith("/stoporder/place")
    assert seen["body"]["positionId"] == 1, "an id that cannot exist"
    for forbidden in ("side", "type", "openType", "leverage"):
        assert forbidden not in seen["body"]


def test_ready_requires_being_able_to_rest_a_stop(monkeypatch):
    """A key that can place orders but cannot rest a stop is not ready: the
    whole point of the exchange-side stop is that it survives this process
    dying, and discovering it is unavailable mid-trade is too late."""
    _keys(monkeypatch)
    monkeypatch.setattr(fx, "usdt_equity", lambda: 163.2)
    monkeypatch.setattr(fx, "open_positions", lambda s=None: [])
    monkeypatch.setattr(fx, "write_probe", lambda: {"reached": True})
    monkeypatch.setattr(fx, "stop_probe", lambda: {
        "permitted": False, "blocked_by": "key scope",
        "reason": "code 704", "remedy": "enable Trading information / Write"})
    rep = fx.preflight("SPX500_USDT")
    assert rep["order_permission"] is True, "orders are fine"
    assert rep["can_rest_stop"] is False
    assert rep["ready"] is False, "but it is not ready to trade"
    assert any("Write" in r for r in rep["remedies"])


# ============ kline cache ===================================================
def test_klines_are_cached_for_half_a_bar(monkeypatch):
    """A bot racing 7 lanes issued 480 kline requests an hour, each for 400
    candles, and this account has already been told "code 510: Requests are too
    frequent". Candles cannot change inside half a bar, so re-fetching faster is
    pure waste."""
    fx.clear_kline_cache()
    calls = []
    payload = {"data": {"time": [1, 2, 3], "open": [1, 1, 1], "high": [2, 2, 2],
                        "low": [0.5, 0.5, 0.5], "close": [1.5, 1.5, 1.5],
                        "vol": [1, 1, 1]}}
    monkeypatch.setattr(fx, "_get_public",
                        lambda url: calls.append(url) or payload)
    a = fx.klines("SPX500_USDT", "Min60", 10)
    b = fx.klines("SPX500_USDT", "Min60", 10)
    assert len(calls) == 1, "the second call must be served from the cache"
    assert list(a["Close"]) == list(b["Close"])

    # a different interval or limit is a different series
    fx.klines("SPX500_USDT", "Min5", 10)
    fx.klines("SPX500_USDT", "Min60", 20)
    assert len(calls) == 3


def test_a_cached_frame_cannot_be_poisoned_by_its_caller(monkeypatch):
    """Handing out the cached object would let one caller's edit corrupt every
    later read."""
    fx.clear_kline_cache()
    payload = {"data": {"time": [1, 2], "open": [1, 1], "high": [2, 2],
                        "low": [0.5, 0.5], "close": [1.5, 1.5], "vol": [1, 1]}}
    monkeypatch.setattr(fx, "_get_public", lambda url: payload)
    first = fx.klines("SPX500_USDT", "Min60", 10)
    first.loc[0, "Close"] = 999.0
    assert fx.klines("SPX500_USDT", "Min60", 10)["Close"].iloc[0] == 1.5


def test_the_cache_expires(monkeypatch):
    fx.clear_kline_cache()
    calls = []
    payload = {"data": {"time": [1], "open": [1], "high": [2], "low": [0.5],
                        "close": [1.5], "vol": [1]}}
    monkeypatch.setattr(fx, "_get_public",
                        lambda url: calls.append(url) or payload)
    monkeypatch.setattr(fx.time, "time", lambda: 1000.0)
    fx.klines("SPX500_USDT", "Min1", 10)
    monkeypatch.setattr(fx.time, "time", lambda: 1000.0 + 31)   # TTL is 30s
    fx.klines("SPX500_USDT", "Min1", 10)
    assert len(calls) == 2


def test_the_cache_never_holds_a_chart_stale_for_long():
    """The UI charts share klines(). A 12-hour TTL on Day1 bars would render a
    chart half a day old under a caption claiming it was the last price."""
    assert fx._KLINE_TTL_CAP == 300
    for interval, ttl in fx._KLINE_TTL.items():
        assert ttl <= fx._KLINE_TTL_CAP, interval


# ============ kline paging ==================================================
def test_klines_pages_past_the_exchange_ceiling(monkeypatch):
    """MEXC serves at most 2001 candles per request, silently. Asking for 5000 gave
    2001 and a backtest that quietly covered a quarter of the requested history."""
    import pandas as pd

    fx.clear_kline_cache()
    calls = []

    def fake_page(symbol, interval, limit, end):
        calls.append((limit, end))
        # 2000 candles ending at `end`, one per minute
        times = [end - 60 * i for i in range(limit)][::-1]
        return pd.DataFrame({
            "Date": pd.to_datetime(times, unit="s", utc=True).tz_localize(None),
            "Open": [1.0] * limit, "High": [1.0] * limit, "Low": [1.0] * limit,
            "Close": [1.0] * limit, "Volume": [0.0] * limit})

    monkeypatch.setattr(fx, "_klines_page", fake_page)
    out = fx.klines("SPX500_USDT", "Min1", 5000)
    assert len(calls) == 3, f"5000 needs three pages, made {len(calls)}"
    assert len(out) == 5000
    assert out["Date"].is_monotonic_increasing, "pages must be stitched in order"
    assert out["Date"].duplicated().sum() == 0, "overlaps must be dropped"


def test_paging_stops_when_the_history_runs_out(monkeypatch):
    """A young contract has less history than the window; the loop must end rather
    than request the same page forever."""
    import pandas as pd

    fx.clear_kline_cache()
    calls = []

    def short_page(symbol, interval, limit, end):
        calls.append(end)
        if len(calls) > 1:
            return None                      # nothing older exists
        times = [end - 60 * i for i in range(500)][::-1]
        return pd.DataFrame({
            "Date": pd.to_datetime(times, unit="s", utc=True).tz_localize(None),
            "Open": [1.0] * 500, "High": [1.0] * 500, "Low": [1.0] * 500,
            "Close": [1.0] * 500, "Volume": [0.0] * 500})

    monkeypatch.setattr(fx, "_klines_page", short_page)
    out = fx.klines("SPX500_USDT", "Min1", 5000)
    assert len(out) == 500
    assert len(calls) <= 2, "must not spin on an exhausted history"


def test_a_small_request_does_not_page(monkeypatch):
    fx.clear_kline_cache()
    pages = []
    monkeypatch.setattr(fx, "_klines_page",
                        lambda *a, **k: pages.append(1) or None)
    payload = {"data": {"time": [1, 2], "open": [1, 1], "high": [2, 2],
                        "low": [0.5, 0.5], "close": [1.5, 1.5], "vol": [1, 1]}}
    monkeypatch.setattr(fx, "_get_public", lambda url: payload)
    fx.klines("SPX500_USDT", "Min5", 300)
    assert pages == [], "300 bars is one plain request, no paging"



def test_contract_spec_refuses_an_empty_payload(monkeypatch):
    """MEXC answers a rate limit with HTTP 200 and no `data` key. The old code
    returned {} and callers read contractSize as 0.0 — which is not a size, it
    is a missing reply. Cost: on 2026-08-18 19:00 an ALICE entry died with
    `cannot size ALICE_USDT: contractSize=0.0` in both books, while ALICE's
    real contract size is 0.1."""
    fx.clear_spec_cache()
    monkeypatch.setattr(fx, "_get_public", lambda url, **kw: {
        "code": 510, "message": "Requests are too frequent, please try again later"})
    with pytest.raises(fx.MexcFuturesError) as e:
        fx.contract_spec("ALICE_USDT")
    assert "carried no data" in str(e.value)
    assert "510" in str(e.value), "say WHY it was empty"
    fx.clear_spec_cache()


def test_contract_spec_is_cached_so_a_rate_limit_cannot_empty_it(monkeypatch):
    """Contract size and tick never move during a session. One read per hour
    keeps a 510 from erasing a spec that was already read successfully."""
    fx.clear_spec_cache()
    calls = []

    def _one(url, **kw):
        calls.append(url)
        return {"code": 0, "data": {"symbol": "ALICE_USDT",
                                    "contractSize": 0.1}}

    monkeypatch.setattr(fx, "_get_public", _one)
    assert fx.contract_spec("ALICE_USDT")["contractSize"] == 0.1
    assert fx.contract_spec("ALICE_USDT")["contractSize"] == 0.1
    assert len(calls) == 1, "the second read should come from the cache"
    fx.clear_spec_cache()


def test_a_spec_with_no_symbol_is_not_a_spec(monkeypatch):
    """A partial payload is the same failure wearing different clothes."""
    fx.clear_spec_cache()
    monkeypatch.setattr(fx, "_get_public",
                        lambda url, **kw: {"code": 0, "data": {"contractSize": 0}})
    with pytest.raises(fx.MexcFuturesError):
        fx.contract_spec("ALICE_USDT")
    fx.clear_spec_cache()
