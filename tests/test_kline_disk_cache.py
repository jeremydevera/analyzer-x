"""The disk kline cache: a daily sweep must fetch the missing TAIL, not
re-page a year, and a corrupt or missing cache must fall back to the full
paged fetch rather than break it."""

import pandas as pd
import pytest

from tradingagents.dataflows import mexc_futures as fx


def _frame(n, start_s=1_700_000_000, per=3600):
    ts = [start_s + i * per for i in range(n)]
    return pd.DataFrame({
        "Date": pd.to_datetime(ts, unit="s", utc=True).tz_localize(None),
        "Open": [1.0 + i for i in range(n)],
        "High": [1.5 + i for i in range(n)],
        "Low": [0.5 + i for i in range(n)],
        "Close": [1.2 + i for i in range(n)],
        "Volume": [10.0] * n,
    })


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(fx, "KLINE_DISK_DIR", tmp_path)
    fx._KLINE_CACHE.clear()
    yield
    fx._KLINE_CACHE.clear()


def test_first_fetch_pages_and_saves(monkeypatch):
    full = _frame(5000)
    calls = []

    def fake_page(symbol, interval, chunk, end_s):
        calls.append(chunk)
        upto = full[full["Date"] <= pd.Timestamp(end_s, unit="s")]
        return upto.tail(chunk).reset_index(drop=True)

    monkeypatch.setattr(fx, "_klines_page", fake_page)
    out = fx.klines("TEST_USDT", "Min60", 5000)
    assert len(out) == 5000
    assert len(calls) >= 3                      # paged, 2000 per request
    assert fx._kline_disk_path("TEST_USDT", "Min60").exists()


def test_second_fetch_reads_disk_and_gets_only_the_tail(monkeypatch):
    full = _frame(5000)
    fx._kline_disk_save("TEST_USDT", "Min60", full.iloc[:4900])
    calls = []

    def fake_page(symbol, interval, chunk, end_s):
        calls.append(chunk)
        upto = full[full["Date"] <= pd.Timestamp(end_s, unit="s")]
        return upto.tail(chunk).reset_index(drop=True)

    monkeypatch.setattr(fx, "_klines_page", fake_page)
    monkeypatch.setattr(fx.time, "time",
                        lambda: float(full["Date"].iloc[-1].timestamp()))
    out = fx.klines("TEST_USDT", "Min60", 5000)
    assert len(out) == 5000
    assert len(calls) == 1, "tail fetch should be one request, not a re-page"
    # the merged result must be the true series, no duplicates, no gaps
    assert list(out["Date"]) == list(full["Date"])
    assert out["Close"].iloc[-1] == full["Close"].iloc[-1]


def test_fresh_fetch_overwrites_the_possibly_forming_last_bar(monkeypatch):
    stale = _frame(4000)
    stale.loc[stale.index[-1], "Close"] = -99.0    # cached mid-bar value
    fx._kline_disk_save("TEST_USDT", "Min60", stale)
    full = _frame(4002)

    def fake_page(symbol, interval, chunk, end_s):
        upto = full[full["Date"] <= pd.Timestamp(end_s, unit="s")]
        return upto.tail(chunk).reset_index(drop=True)

    monkeypatch.setattr(fx, "_klines_page", fake_page)
    monkeypatch.setattr(fx.time, "time",
                        lambda: float(full["Date"].iloc[-1].timestamp()))
    out = fx.klines("TEST_USDT", "Min60", 4002)
    row = out[out["Date"] == stale["Date"].iloc[-1]]
    assert float(row["Close"].iloc[0]) != -99.0, \
        "the refetched copy of an overlapping bar must win"


def test_corrupt_cache_falls_back_to_full_fetch(monkeypatch):
    p = fx._kline_disk_path("TEST_USDT", "Min60")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"not gzip at all")
    full = _frame(3000)

    def fake_page(symbol, interval, chunk, end_s):
        upto = full[full["Date"] <= pd.Timestamp(end_s, unit="s")]
        return upto.tail(chunk).reset_index(drop=True)

    monkeypatch.setattr(fx, "_klines_page", fake_page)
    out = fx.klines("TEST_USDT", "Min60", 3000)
    assert len(out) == 3000


def test_small_requests_do_not_touch_the_disk_cache(monkeypatch):
    """The single-page path (charts, live runner) is untouched — it already
    has the in-memory TTL cache and must stay real-time."""
    seen = []
    monkeypatch.setattr(
        fx, "_get_public",
        lambda url: seen.append(url) or {"data": {
            "time": [1_700_000_000], "open": [1], "high": [1],
            "low": [1], "close": [1], "vol": [1]}})
    out = fx.klines("TEST_USDT", "Min60", 300)
    assert len(out) == 1
    assert not fx._kline_disk_path("TEST_USDT", "Min60").exists()
