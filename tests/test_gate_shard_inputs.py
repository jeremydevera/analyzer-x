"""What a GitHub shard asks the exchange for, under Gate (phase 3, Oct 10, 2026).

* Minutes for v2 come from `fx.minutes` — Gate's archive, then 5-minute bars
  over the current month's hole, then REST minutes (spec D10). Under MEXC the
  same call is the old 44,000-minute read.
* Funding: Gate serves ~30 days a page. A read with no window covers the
  last FUNDING_DEFAULT_DAYS (200: the longest backtest window is 180) and is
  kept for half an hour per coin — the shard measures five timeframes of one
  coin back to back, and twenty other callers ask for "all of it".
"""
import json
import time
import urllib.parse

import pandas as pd
import pytest

from tradingagents.dataflows import gate_futures as gf
from tradingagents.dataflows import mexc_futures as mf

SHARD = open(".github/scripts/sweep_shard.py", encoding="utf-8").read()


def test_the_v2_shard_asks_for_minutes_through_the_door():
    import inspect

    from tradingagents import backtest_report as br

    assert "br.fine_bars(sym," in SHARD
    assert 'fx.klines(sym, iv1, cap1)' not in SHARD, "the 44,000-minute read is gone"
    assert "fx.minutes(" in inspect.getsource(br.fine_bars)


def test_fine_bars_drops_the_forming_minute_and_counts_five_minute_bars(monkeypatch):
    from tradingagents import backtest_report as br

    now = int(time.time()) // 60 * 60
    frame = pd.DataFrame({
        "Date": pd.to_datetime([now - 600, now - 300, now - 120, now - 60, now], unit="s"),
        "High": [2.0, 3.0, 4.0, 5.0, 6.0], "Low": [1.0] * 5,
        "Seconds": [300, 60, 60, 60, 60]})

    class Fx:
        def minutes(self, s, a, b):
            return frame
    t, hi, lo, n5 = br.fine_bars("X_USDT", now - 900, fx=Fx())
    assert list(t // 1000) == [now - 600, now - 300, now - 120, now - 60],         "the minute still forming is not final"
    assert n5 == 1 and list(hi) == [2.0, 3.0, 4.0, 5.0]


def test_the_shard_asks_funding_for_its_window():
    assert SHARD.count("fx.funding_history(sym, since_ms=") >= 2, \
        "both the full path and the continuation"


def test_mexc_minutes_are_the_old_read(monkeypatch):
    frame = pd.DataFrame({"Date": pd.to_datetime([60 * k for k in range(10)], unit="s"),
                          "Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.5,
                          "Volume": 1.0})
    asked = []
    monkeypatch.setattr(mf, "klines", lambda s, iv, n: asked.append((s, iv, n)) or frame)
    m = mf.minutes("BTC_USDT", 120, 420)
    assert asked == [("BTC_USDT", "Min1", 44_000)]
    assert list(m["Seconds"].unique()) == [60]
    assert [int(x.timestamp()) for x in m["Date"]] == [120, 180, 240, 300, 360, 420]


@pytest.fixture
def gate(monkeypatch, tmp_path):
    monkeypatch.setenv("TA_VENUE", "gate")
    monkeypatch.setattr(gf, "PUBLIC_PAUSE_PATH", tmp_path / "pause.json")
    monkeypatch.setattr(gf, "_retry_sleep", lambda s: None)
    monkeypatch.setattr(gf, "contract_spec", lambda s: {"funding_interval_h": 8})
    gf._FUND_CACHE.clear()
    pages = []
    now = int(time.time())

    def fake(url):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        top = int(q.get("to") or now)
        pages.append(top)
        return 200, json.dumps([{"r": "0.0001", "t": top - 28800 * i}
                                for i in range(90)]).encode()
    monkeypatch.setattr(gf, "_fetch", fake)
    yield pages
    gf._FUND_CACHE.clear()


def test_a_read_with_no_window_covers_the_default_days_only(gate):
    h = gf.funding_history("BTC_USDT")
    reach_days = (time.time() * 1000 - h[0]["settle_ms"]) / 86_400_000
    assert gf.FUNDING_DEFAULT_DAYS <= reach_days < gf.FUNDING_DEFAULT_DAYS + 31
    assert len(gate) <= gf.FUNDING_DEFAULT_DAYS // 30 + 2


def test_the_same_coin_is_read_once_per_half_hour(gate):
    gf.funding_history("BTC_USDT")
    n = len(gate)
    gf.funding_history("BTC_USDT")
    gf.funding_history("BTC_USDT", since_ms=int((time.time() - 40 * 86400) * 1000))
    assert len(gate) == n, "a narrower ask is answered from the read already made"
    gf.funding_history("BTC_USDT", since_ms=int((time.time() - 400 * 86400) * 1000))
    assert len(gate) > n, "a wider ask reads further back"


def test_the_v2_engine_call_pays_each_minutes_book():
    """Phase 4: every v2 trade pays its own minute's order book and is refused
    where the runner would refuse it; the row says how many were refused and
    how many had no reading."""
    assert "book=book, book_hold_s=bs * at.FUNDING_HOLD_BARS," in SHARD
    assert '"gate_blocked": int(r.get("gate_blocked", 0))' in SHARD
    assert '"cost_unmeasured": int(r.get("cost_unmeasured", 0))' in SHARD
    assert "book = cost_book(sym)" in SHARD
