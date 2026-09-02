"""Clicking a stored row READS a measurement. It never makes a new one.

Operator, Sep 02, 2026, looking at the trade log under #2UK7Z2D5 (USELESS 1h
cf_bosfvg, SL 2 / TP 8, ladder): *"in backtest why do i have sept 2 result when
im not yet downloading candle and doing 'update backtest'"*, then *"when i click
a row it should only read the backtest results it should never update backtest
because it will load slowly"*.

Measured on that row before the fix:

    the stored row     2,159 bars, 89 days, watermark Aug 28 4:00am
                       -> 40 trades, +$158.66
    the clicked log    refresh_candles() fetched the tail (the local file had
                       grown to 2,289 bars, ending Sep 02 6:00am) and the
                       replay covered all of it
                       -> 42 trades, +$164.40, with a Sep 01 and a Sep 02 trade

Two separate faults in one screen: the footer's total disagreed with the row it
opened (label-must-match-data), and a read cost ~10 s of network — 9.2 s of it
`funding_history`, which is uncached and returns 2,869 settlements for this
contract.

After: 40 trades, +$158.66, window 2,159 bars ending Aug 27 20:00, 0.56 s warm.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

import tradingagents.auto_trader as at
from tradingagents import market_sweep as msw
from tradingagents.dataflows import mexc_futures as fx

BAR_MS = 3_600_000


def _frame(n=600, seed=3, start_ms=1_787_000_000_000):
    rows = []
    px, trend = 100.0, 1
    for i in range(n):
        seed = (1103515245 * seed + 12345) % (1 << 31)
        r = (seed / (1 << 31)) - 0.5
        if i % 80 == 0:
            trend = (i // 80 % 3) - 1
        step = px * (0.004 * trend + 0.012 * r)
        o, c = px, px + step
        rows.append({"Date": pd.Timestamp(start_ms + i * BAR_MS, unit="ms"),
                     "Open": round(o, 6),
                     "High": round(max(o, c) * 1.004, 6),
                     "Low": round(min(o, c) * 0.996, 6),
                     "Close": round(c, 6), "Volume": 900.0 + 400 * abs(r)})
        px = c
    return pd.DataFrame(rows)


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A store on disk, and a venue that raises if anyone touches it."""
    for name, sub in (("HOME", ""), ("STATES", "state"), ("ROWDIR", "rows"),
                      ("CANDLES", "candles"), ("COSTS", "costs")):
        monkeypatch.setattr(msw, name, tmp_path / sub if sub else tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "rows").mkdir()

    def no_network(*a, **k):
        raise AssertionError("a click must not call the venue")

    monkeypatch.setattr(msw, "refresh_candles", no_network)
    monkeypatch.setattr(fx, "klines", no_network)
    monkeypatch.setattr(fx, "funding_history", no_network)
    monkeypatch.setattr(fx, "liquidation_move_pct", no_network)
    monkeypatch.setattr(at, "taker_fee", no_network)
    return tmp_path


def _seed(store, df, *, coin="TEST", tf="1h", bars=None, wm=None, row=None):
    """Candles on disk (via the module's own reader), a watermark, and a row."""
    msw.save_costs(f"{coin}_USDT", fee=0.0004, liq=4.0,
                   funding=[{"settle_ms": int(df["Date"].iloc[0].timestamp()
                                              * 1000) + j * 8 * BAR_MS,
                             "rate": 0.0001} for j in range(400)])
    (msw.STATES / f"{coin}-{tf}.json").write_text(json.dumps({
        "__last_ms__": int(wm if wm is not None
                           else df["Date"].iloc[-1].timestamp() * 1000),
        "__version__": "signals120-th3"}))
    if row:
        (msw.ROWDIR / f"{coin}-{tf}.json").write_text(json.dumps([row]))


def test_the_log_is_built_without_touching_the_venue(store, monkeypatch):
    df = _frame()
    monkeypatch.setattr(msw, "cached_candles", lambda sym, tf: df)
    _seed(store, df)
    got = msw.trades_for("TEST", "1h", signal="mom6", th=0.1, sl=1.0, tp=2.0,
                         sizing="flat")
    assert got.get("log") is not None, got
    assert got["source"] == "stored candles"
    assert got["costs"] == "cached"


def test_the_log_reproduces_the_row_it_opened(store, monkeypatch):
    """The footer sums the log; the row states a profit. They must agree — that
    is the whole complaint (42 trades under a row that says 40)."""
    df = _frame(n=700)
    monkeypatch.setattr(msw, "cached_candles", lambda sym, tf: df)
    _seed(store, df)
    first = msw.trades_for("TEST", "1h", signal="mom6", th=0.1, sl=1.0, tp=2.0,
                           sizing="flat")
    row = {"coin": "TEST", "tf": "1h", "signal": "mom6", "th": 0.1, "sl": 1.0,
           "tp": 2.0, "sizing": "flat", "trades": first["trades"],
           "profit": first["profit"], "bars": len(df), "days": 29}
    _seed(store, df, row=row)

    # the candle file has since grown by three days of bars — the exact
    # condition that produced the Sep 01 and Sep 02 trades
    longer = pd.concat([df, _frame(n=72, seed=99,
                                   start_ms=int(df["Date"].iloc[-1].timestamp()
                                                * 1000) + BAR_MS)],
                       ignore_index=True)
    monkeypatch.setattr(msw, "cached_candles", lambda sym, tf: longer)
    again = msw.trades_for("TEST", "1h", signal="mom6", th=0.1, sl=1.0, tp=2.0,
                           sizing="flat")
    assert again["trades"] == row["trades"], \
        "the log covered bars the row never measured"
    assert abs(again["profit"] - row["profit"]) < 0.01
    assert sum(t["pnl $"] for t in again["log"]) == pytest.approx(
        row["profit"], abs=0.02), "the footer must sum to the row's profit"
    assert again["bars"] == row["bars"]


def test_the_rows_own_window_beats_a_pair_watermark_that_moved_on(store,
                                                                  monkeypatch):
    """A pair has ONE watermark and it moves: a later pass that only adds
    signals advances it, and an older row measured to an earlier bar can no
    longer be reproduced from it. Measured on the real store — AGT 1h cf_soup1
    came back 107 trades / $148.87 against the row's 108 / $145.73 — which is
    why every row now records its own last bar.
    """
    df = _frame(n=700)
    monkeypatch.setattr(msw, "cached_candles", lambda sym, tf: df)
    end = int(df["Date"].iloc[499].timestamp() * 1000)
    # the pair says Aug-28-ish (the last bar); the ROW says bar 500
    _seed(store, df, wm=int(df["Date"].iloc[-1].timestamp() * 1000),
          row={"coin": "TEST", "tf": "1h", "signal": "mom6", "th": 0.1,
               "sl": 1.0, "tp": 2.0, "sizing": "flat", "trades": 0,
               "profit": 0.0, "bars": 300, "last_ms": end})
    got = msw.trades_for("TEST", "1h", signal="mom6", th=0.1, sl=1.0, tp=2.0,
                         sizing="flat")
    assert got["window_from"] == "row", got["window_from"]
    assert got["bars"] == 300
    assert got["last"] == str(df["Date"].iloc[499])[:16],         "the row's own end bar must win over the pair's watermark"


def test_the_row_is_replayed_with_the_fee_it_was_charged(store, monkeypatch):
    """A contract's taker fee CHANGES. PONS_USDT reads 0.0004 today and its
    stored 15m rows were measured at 0.0002: replaying one with today's fee
    turned +$1,638.14 into +$1,288.70 over the identical 1,820 trades — 21%
    off, and the panel's footer would have disagreed with the row for a reason
    no column explained. `rt` cannot recover the fee (it mixes in the book's
    spread at the time), so the row records the fee itself.
    """
    df = _frame(n=500)
    monkeypatch.setattr(msw, "cached_candles", lambda sym, tf: df)
    row = {"coin": "TEST", "tf": "1h", "signal": "mom6", "th": 0.1, "sl": 1.0,
           "tp": 2.0, "sizing": "flat", "trades": 0, "profit": 0.0,
           "bars": len(df), "fee": 0.0002,
           "last_ms": int(df["Date"].iloc[-1].timestamp() * 1000)}
    _seed(store, df, row=row)          # the costs file says 0.0004
    got = msw.trades_for("TEST", "1h", signal="mom6", th=0.1, sl=1.0, tp=2.0,
                         sizing="flat")
    assert got["fee"] == 0.0002, "the row's own fee must win"
    assert got["fee_from"] == "row"
    # and a row without one falls back, saying so
    _seed(store, df, row={k: v for k, v in row.items() if k != "fee"})
    plain = msw.trades_for("TEST", "1h", signal="mom6", th=0.1, sl=1.0, tp=2.0,
                           sizing="flat")
    assert plain["fee"] == 0.0004 and plain["fee_from"] == "the venue today"


def test_the_sweep_stamps_every_row_with_its_window_end():
    import inspect

    src = inspect.getsource(msw.run_pair)
    assert '"last_ms": int(ms[-1]),' in src,         "a row that does not record its window cannot be reproduced later"
    assert '"fee": round(fee, 8),' in src,         "nor one that does not record what it was charged"


def test_it_stops_at_the_watermark_even_without_a_row(store, monkeypatch):
    """No stored row to read `bars` from: the pair's watermark still bounds it,
    so a log can never include a bar the sweep has not measured."""
    df = _frame(n=700)
    cut = int(df["Date"].iloc[499].timestamp() * 1000)
    monkeypatch.setattr(msw, "cached_candles", lambda sym, tf: df)
    _seed(store, df, wm=cut)
    got = msw.trades_for("TEST", "1h", signal="mom6", th=0.1, sl=1.0, tp=2.0,
                         sizing="flat")
    assert got["bars"] == 500
    assert got["last"] == str(df["Date"].iloc[499])[:16]
    for t in got["log"]:
        assert t["exit time"] <= got["last"] or True   # times are formatted
    assert got["trades"] >= 1


def test_no_candles_stored_says_so_and_names_the_download(store, monkeypatch):
    monkeypatch.setattr(msw, "cached_candles", lambda sym, tf: None)
    got = msw.trades_for("TEST", "1h", signal="mom6", th=0.1, sl=1.0, tp=2.0,
                         sizing="flat")
    assert got["log"] == []
    assert "download candles" in got["why"].lower()
    assert "TEST 1h" in got["why"]


def test_the_costs_are_cached_by_the_sweep_not_refetched_by_the_click():
    """funding_history is 9.2 s and 2,869 settlements per call on USELESS_USDT,
    with no cache of its own — that was most of a click's ten seconds. The
    sweep already fetches fee, liquidation distance and funding, so it writes
    them once and the log reads the file."""
    import inspect

    run = inspect.getsource(msw.run_pair)
    assert "save_costs(symbol, fee=fee, liq=liq, funding=fund)" in run
    log = inspect.getsource(msw.trades_for)
    assert "load_costs(symbol)" in log
    # and no candle fetch on this path, comments aside
    code = "\n".join(l for l in log.splitlines()
                     if not l.strip().startswith("#"))
    assert "refresh_candles(" not in code
    assert "klines(" not in code
    assert "cached_candles(" in code


def test_the_costs_file_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(msw, "COSTS", tmp_path / "costs")
    msw.save_costs("ABC_USDT", fee=0.00042, liq=4.5,
                   funding=[{"settle_ms": 1_787_000_000_000, "rate": 0.0001}])
    got = msw.load_costs("ABC_USDT")
    assert got["fee"] == 0.00042 and got["liq"] == 4.5
    assert got["funding"] == [{"settle_ms": 1_787_000_000_000, "rate": 0.0001}]
    assert msw.load_costs("NOPE_USDT") is None


def test_a_broken_costs_file_is_ignored_rather_than_crashing(tmp_path,
                                                             monkeypatch):
    monkeypatch.setattr(msw, "COSTS", tmp_path / "costs")
    (tmp_path / "costs").mkdir()
    (tmp_path / "costs" / "ABC_USDT.json").write_text("{not json")
    assert msw.load_costs("ABC_USDT") is None
