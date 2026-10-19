"""A stock token's candle where nothing traded is not bought, unless the app's
own book of that minute says practice could (operator, Oct 18, 2026: "Do your
reaseach first on what is best fix and fix for moving forward").

Measured before building, over every 15-minute decision since the app began
recording its own book (Oct 16, 2026 6:15am - Oct 18, 2026 2:30am) at which
Gate's record was fresh: practice's rule on the APP's book is the answer key,
the same rule on Gate's RECORD the backtest. On the room's four stock tokens
(XIECHUANG, HUT, CCTC, YONGDING) the backtest agreed 79.9% of the time;
skipping a stock token's dead candle, 97.7% - 90.0% over 36 coins against
87.4%. Practice entered none of those candles at a stop of 0.2% or less on
those coins, and 28-61% of crypto's, so crypto is left alone; a guard on how
far a recorded price sits from what traded added nothing (90.0% at 1%, 88.5%
at 0.25%). XIECHUANG 15m rsi2 SL 0.1% TP 3% (#CK42WZCP): 27 of its 33 trades
were bought on Sep 28, 2026 between 2:45am and 9:15am at the record's ask
36.07, which stood still for 514 minutes (12:42am-9:15am) while 46 of the 49
15m candles to noon printed no trade; under the rule it makes none, as
practice made none.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tradingagents import auto_trader as at
from tradingagents.book_history import SOURCES

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
# ONE TIMELINE: the candles, the signal and the book reading share these.
T0 = 1791504000           # Oct 09, 2026 00:00 UTC
H = 3600
KEY = next(iter(at.STRATEGY_SPECS))


def frame(dead: bool = True):
    """30 hourly bars; the signal fires on bar 5 and the entry is bar 6's open.
    `dead`: bar 5, the signal candle, printed no trade."""
    n = 30
    o, hi, lo = [100.0] * n, [100.2] * n, [99.8] * n
    hi[8], lo[8] = 101.5, 98.5            # the 1% target is touched in bar 8
    vol = [1.0] * n
    if dead:
        vol[5] = 0.0
    return pd.DataFrame({"Date": pd.to_datetime([T0 + H * k for k in range(n)], unit="s"),
                         "Open": o, "High": hi, "Low": lo, "Close": o, "Volume": vol})


def run(df, **kw):
    dirs = [0] * 30
    dirs[5] = 1
    return at.backtest_strategy(KEY, df, 5.0, fee=0.00075, slippage=0.0003,
                                sizing="flat", dirs=dirs, tp=0.01, sl=0.01,
                                keep_log=True, **kw)


def book(source: str = "full", at_t: int = T0 + 6 * H):
    """One cheap reading at the entry minute, inside the chase limit."""
    return {"t": np.asarray([at_t], dtype="int64"),
            "bid": np.asarray([100.04], dtype="float64"),
            "ask": np.asarray([100.05], dtype="float64"),
            "spread": np.asarray([0.0001], dtype="float32"),
            "buy": np.asarray([0.0001], dtype="float32"),
            "sell": np.asarray([0.0001], dtype="float32"),
            "exhausted": np.asarray([False]),
            "source": np.asarray([SOURCES[source]], dtype="int8")}


def test_a_stock_tokens_dead_candle_is_not_bought_off_gates_record():
    r = run(frame(), book=book(), closed_skip=True)
    assert r["trades"] == 0 and r["closed_skip"] == 1
    assert r["gate_blocked"] == 0 and r["chase_skip"] == 0


def test_no_reading_at_all_is_not_a_reason_to_buy_either():
    """No book at the entry minute is still not the app's: practice would
    have read a wide live book there (2.326% on XIECHUANG, Oct 17, 2026)."""
    r = run(frame(), book=book(at_t=T0), closed_skip=True)       # hours too old
    assert r["trades"] == 0 and r["closed_skip"] == 1


def test_the_apps_own_book_decides_like_practice():
    """Since Oct 16, 2026 6:14am the app records the book the runner reads:
    where it exists, it decides, and this rule stands aside."""
    r = run(frame(), book=book("app"), closed_skip=True)
    assert r["trades"] == 1 and r["closed_skip"] == 0


def test_an_app_book_of_an_earlier_minute_is_not_the_entry_minutes():
    """The app missed the entry minute: its book of two minutes before says
    nothing about the minute practice would have read (the chase guard's
    CHASE_READING_MAX_AGE_S), so the dead candle is still not bought."""
    r = run(frame(), book=book("app", at_t=T0 + 6 * H - 120), closed_skip=True)
    assert r["trades"] == 0 and r["closed_skip"] == 1


def test_candles_without_their_volume_run_no_rule_and_say_so():
    """No `Volume` column: the rule cannot see a dead candle, so it does not
    run, and the result carries no `closed_skip` count - the key a row is
    stamped by, so no row claims a rule its walk never applied."""
    r = run(frame().drop(columns=["Volume"]), book=book(), closed_skip=True)
    assert r["trades"] == 1 and "closed_skip" not in r


def test_a_candle_that_traded_is_bought_as_before():
    r = run(frame(dead=False), book=book(), closed_skip=True)
    assert r["trades"] == 1 and r["closed_skip"] == 0


def test_the_rule_off_is_the_engine_of_before():
    a, b = run(frame(), book=book()), run(frame(), book=book(), closed_skip=False)
    assert a == b and a["trades"] == 1 and "closed_skip" not in a
    # and with no book (MEXC, v1) the rule has nothing to stand in for
    assert run(frame(), closed_skip=True) == run(frame())


def test_a_candle_the_room_really_took_is_never_refused():
    """Backtest a room keeps every candle the room entered (`keep`)."""
    signal_open_ms = (T0 + 5 * H) * 1000
    r = run(frame(), book=book(), closed_skip=True, keep=lambda ms: ms == signal_open_ms)
    assert r["trades"] == 1 and r["closed_skip"] == 0


def test_one_rule_for_the_engine_and_the_replay():
    rec = {"t": 0, "age_s": 0, "bid": 100.04, "ask": 100.05, "spread": 0.0001,
           "buy": 0.0001, "sell": 0.0001, "exhausted": False, "source": SOURCES["full"]}
    app = {**rec, "source": SOURCES["app"]}
    assert at.closed_market(rec, stock=True, signal_volume=0.0) is True
    assert at.closed_market(None, stock=True, signal_volume=0) is True
    assert at.closed_market(app, stock=True, signal_volume=0.0) is False
    assert at.closed_market(rec, stock=False, signal_volume=0.0) is False
    assert at.closed_market(rec, stock=True, signal_volume=3.0) is False
    assert at.closed_market(rec, stock=True, signal_volume=None) is False
    kw = dict(side=1, signal_close=100.0, tp=0.01, sl=0.01, fee=0.00075, hold_s=3600,
              liq=None, fund_day=0.0)
    assert at.entry_refusal(rec, closed=True, **kw)[0] == "closed_skip"
    assert at.entry_refusal(rec, **kw)[0] == ""


def test_the_rule_is_for_stock_tokens_on_gate(monkeypatch):
    from tradingagents import market_sweep as msw, venue

    monkeypatch.setattr(venue, "kind", lambda s: "stocks" if s.startswith("XIECHUANG") else "crypto")
    monkeypatch.setattr(venue, "current", lambda: "gate")
    assert msw.closed_rule("XIECHUANG_USDT") is True
    assert msw.closed_rule("BTC_USDT") is False
    monkeypatch.setattr(venue, "current", lambda: "mexc")
    assert msw.closed_rule("XIECHUANG_USDT") is False


def _flat(rel: str) -> str:
    return " ".join((ROOT / rel).read_text(encoding="utf-8").split())


def test_every_measuring_path_asks_it_and_every_row_says_so():
    """GitHub's measure and UPDATE THIS BACKTEST pass the rule and stamp the
    rows they write; the readers follow a row's stamp (a row measured before
    keeps adding up to its own trade list until it is measured again); the
    room replay asks the same function."""
    stamp = '"closed_skipped": int(r["closed_skip"])} if _closed and "closed_skip" in r else {}'
    shard = _flat(".github/scripts/sweep_shard.py")
    assert "closed_skip=_closed" in shard and stamp in shard
    sweep = _flat("tradingagents/market_sweep.py")
    assert "closed_skip=_closed" in sweep and stamp in sweep
    assert 'closed_skip=(bool(the_row.get("closed_skip"))' in sweep, "the trade list follows the row"
    assert 'closed_skip=bool(r.get("closed_skip")) and closed_rule(sym)' in sweep, "and so does the window"
    r30 = _flat("tradingagents/rolling30.py")
    assert '_cs = bool(row.get("closed_skip")) and _msw.closed_rule(' in r30, "and the DEMO 30-day figure"
    assert "closed_skip=_cs" in r30
    replay = _flat(".github/scripts/replay_shard.py")
    assert "closed=at.closed_market( r, stock=_stock," in replay
    assert "signal_volume=vol[i] if vol is not None else None" in replay


def test_the_row_index_keeps_the_stamp_as_a_number():
    """1 or NULL, as `reenter` is: the last-N-days window reads it off the
    index row, never the text '0' (which would read as true)."""
    from tradingagents import rows_index as ri

    assert "closed_skip" in ri.COLS and "closed_skip" in ri._INTEGER
    assert ("closed_skip", "INTEGER") in ri.LATE_COLUMNS
    assert ri._values({"id": "A", "closed_skip": True}, "X-1h")[ri.COLS.index("closed_skip")] is True
    assert ri._values({"id": "A"}, "X-1h")[ri.COLS.index("closed_skip")] is None


# ---- the readers follow the ROW's stamp (the `reenter` rule's shape) -------
from tests.test_the_demo_column_reads_the_last_30_days import NOW, SLOT, home  # noqa: E402,F401
from tests.test_v2_reads_from_its_own_store import H0, v2  # noqa: E402,F401  (fixtures)
from tradingagents import market_sweep as msw  # noqa: E402


def _spy(monkeypatch):
    seen: list = []
    real = at.backtest_strategy

    def spy(*a, **k):
        seen.append(k.get("closed_skip"))
        return real(*a, **k)

    monkeypatch.setattr(at, "backtest_strategy", spy)
    return seen


def _stamp(store, on: bool) -> None:
    import json

    p = store.home / "rows" / "XPIN-1h.json"
    rows = json.loads(p.read_text())
    for r in rows:
        r.pop("closed_skip", None)
        if on:
            r["closed_skip"] = True
    p.write_text(json.dumps(rows))


def test_a_rows_trade_list_follows_the_rule_it_was_measured_with(v2, monkeypatch):  # noqa: F811
    """A row measured before the rule keeps adding up to its own trade list
    until it is measured again; a walk up to today takes today's rule."""
    seen = _spy(monkeypatch)
    monkeypatch.setattr(msw, "closed_rule", lambda sym: True)     # a Gate stock token
    kw = {"signal": "ote", "th": 0.0, "sl": 3.0, "tp": 1.0, "sizing": "flat", "store": v2}
    assert msw.trades_for("XPIN", "1h", **kw).get("log") and seen == [False]
    _stamp(v2, True)
    seen.clear()
    msw.trades_for("XPIN", "1h", **kw)
    assert seen == [True], "measured under the rule: its list is too"
    _stamp(v2, False)
    seen.clear()
    msw.trades_for("XPIN", "1h", whole=True, **kw)
    assert seen == [True], "a replay up to today is a fresh walk: today's rule"
    _stamp(v2, True)
    monkeypatch.setattr(msw, "closed_rule", lambda sym: False)    # crypto, or MEXC
    seen.clear()
    msw.trades_for("XPIN", "1h", **kw)
    assert seen == [False], "a stamp never turns the rule on where it does not apply"


def test_a_rows_days_window_follows_its_own_stamp(v2, monkeypatch):  # noqa: F811
    import time as _time

    seen = _spy(monkeypatch)
    monkeypatch.setattr(msw, "closed_rule", lambda sym: True)
    monkeypatch.setattr(_time, "time", lambda: (H0 + 5 * 86_400_000) / 1000)
    row = {"id": "X", "coin": "XPIN", "tf": "1h", "signal": "ote", "th": 0.0,
           "sl": 3.0, "tp": 1.0, "sizing": "flat", "base": 5.0, "trades": 1,
           "profit": 0.9, "last_ms": H0 + 69 * 3_600_000}
    got = msw.window_rows([dict(row), {**row, "closed_skip": 1}], 10, store=v2)
    assert all(r.get("restated") is True for r in got["rows"])
    assert seen == [False, True], "each row its own rule (the index stores 1 or NULL)"


def test_the_demo_figure_is_walked_under_its_rows_stamp(home, monkeypatch):  # noqa: F811
    """The DEMO 30-day figure the watchers switch rows off by rebuilds the
    row's backtest: a stamped row's dead candles are skipped there too, and
    the record says which rule it was walked under."""
    from tradingagents import backtest_report as br, rolling30 as r30
    from tradingagents.dataflows import gate_futures as gf

    monkeypatch.setenv("TA_VENUE", "gate")
    n, bar = 400, 900
    t0 = int(NOW) - n * bar
    df = pd.DataFrame({"Date": pd.to_datetime([t0 + bar * k for k in range(n)], unit="s"),
                       "Open": [100.0] * n, "High": [100.5] * n, "Low": [99.5] * n,
                       "Close": [100.0] * n, "Volume": [1.0] * n})
    wm = (t0 + bar * (n - 1)) * 1000
    ident = {"key": "prank_15m_sl15tp15", "tf": "15m", "sym": "FASTSTOCK_USDT",
             "tp": 1.5, "sl": 1.2, "res": "1m", "coin": "FASTSTOCK", "store": None}
    monkeypatch.setattr(r30, "_identity", lambda settings, slot: ident)
    monkeypatch.setattr(gf, "klines", lambda *a, **k: df)
    monkeypatch.setattr(gf, "funding_history", lambda *a, **k: [])
    monkeypatch.setattr(gf, "liquidation_move_pct", lambda *a, **k: 4.5)
    monkeypatch.setattr(br, "fine_bars", lambda *a, **k: (np.zeros(0, "int64"),
                                                          np.zeros(0), np.zeros(0), 0))
    monkeypatch.setattr(at, "_dirs_for_backtest", lambda *a, **k: [0] * n)
    monkeypatch.setattr(msw, "closed_rule", lambda sym: sym == "FASTSTOCK_USDT")
    seen = _spy(monkeypatch)
    for stamp, want in (({}, False), ({"closed_skip": True}, True)):
        row = {"trades": 0, "wins": 0, "profit": 0.0, "bars": 300, "fee": 0.00075, **stamp}
        monkeypatch.setattr(r30, "_stored", lambda i, row=row: (row, wm))
        seen.clear()
        rec = r30.rebuild(SLOT, {})
        assert seen == [want] and rec["closed_skip"] is want


def test_a_saved_room_backtest_is_not_served_across_the_rule():
    """Backtest a room keeps each range's answer; one saved before the rule
    holds stock-token trades practice could never have made, so the tag of a
    saved answer moved on (room_replay.RESULT_TAG: "bumped when a saved
    replay would answer differently for the same range")."""
    from tradingagents import room_replay as rr

    assert rr.RESULT_TAG == "r5"
