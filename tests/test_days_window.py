"""LAST N DAYS in Stored strategies — a re-measurement, not a sum.

Operator, Sep 02, 2026: *"can you add days textbox isntead of using past 1 month
only / if months is 0 then follow the days"*.

Why it cannot be read off the store: the sweep keeps one row per combination
plus its profit PER MONTH (`monthly[month] += pnl` and nothing else). A month
window sums from that; a DAY window cannot be derived from it at all, and
neither can trades, wins or win rate at any granularity. So each row's rules
are walked again over the last N days of that pair's own STORED candles.

Measured on the operator's store while building this: #2UK7Z2D5 (USELESS 1h
cf_bosfvg) is 40 trades and +$158.66 over its whole 89-day window, and 14
trades, +$55.10 and a 42.86% win rate over the last 30 days. Same row.

The cost is the signal computation, ~0.2-2 s per (coin, timeframe, signal,
threshold) group, so the request is capped in two places and SAYS which: a
50-row page spanning 50 coins took 30.0 s and came back as a bare HTTP 500
before the caps existed.
"""
from __future__ import annotations

import inspect

import pandas as pd
import pytest

import tradingagents.auto_trader as at
from tradingagents import market_sweep as msw
from tradingagents.dataflows import mexc_futures as fx

BAR_MS = 3_600_000


def _frame(n=900, seed=4, start_ms=1_786_000_000_000):
    rows = []
    px, trend = 100.0, 1
    for i in range(n):
        seed = (1103515245 * seed + 12345) % (1 << 31)
        r = (seed / (1 << 31)) - 0.5
        if i % 90 == 0:
            trend = (i // 90 % 3) - 1
        step = px * (0.004 * trend + 0.012 * r)
        o, c = px, px + step
        rows.append({"Date": pd.Timestamp(start_ms + i * BAR_MS, unit="ms"),
                     "Open": round(o, 6), "High": round(max(o, c) * 1.004, 6),
                     "Low": round(min(o, c) * 0.996, 6), "Close": round(c, 6),
                     "Volume": 900.0 + 400 * abs(r)})
        px = c
    return pd.DataFrame(rows)


@pytest.fixture
def offline(tmp_path, monkeypatch):
    """Stored candles and stored costs; the venue raises if anyone calls it."""
    df = _frame()
    monkeypatch.setattr(msw, "COSTS", tmp_path / "costs")
    monkeypatch.setattr(msw, "cached_candles", lambda sym, tf: df)
    msw._DIRS_CACHE.clear()

    def no_network(*a, **k):
        raise AssertionError("a days window must not call the venue")

    monkeypatch.setattr(msw, "refresh_candles", no_network)
    monkeypatch.setattr(fx, "klines", no_network)
    monkeypatch.setattr(fx, "funding_history", no_network)
    monkeypatch.setattr(fx, "liquidation_move_pct", no_network)
    monkeypatch.setattr(at, "taker_fee", no_network)
    for sym in ("A_USDT", "B_USDT", "C_USDT"):
        msw.save_costs(sym, fee=0.0004, liq=4.0, funding=[])
    return df


def _row(coin="A", signal="mom6", th=0.1, sl=1.0, tp=2.0, sizing="flat"):
    return {"id": f"{coin}{signal}", "coin": coin, "tf": "1h", "signal": signal,
            "th": th, "sl": sl, "tp": tp, "sizing": sizing, "base": 5.0,
            "trades": 0, "profit": 0.0}


def test_the_window_is_the_windows_own_figures(offline):
    rows = [_row()]
    got = msw.window_rows(rows, 10)
    r = got["rows"][0]
    for k in ("w_trades", "w_wins", "w_losses", "w_winrate", "w_profit",
              "w_dd", "w_streak", "w_streak_len", "w_days"):
        assert k in r, k
    assert r["restated"] is True
    assert 9.0 <= r["w_days"] <= 10.1, r["w_days"]
    assert got["first"] and got["last"] and got["first"] < got["last"]
    assert r["w_wins"] + r["w_losses"] == r["w_trades"]


def test_a_shorter_window_can_only_hold_fewer_trades(offline):
    long_ = msw.window_rows([_row()], 30)["rows"][0]
    short = msw.window_rows([_row()], 5)["rows"][0]
    assert short["w_trades"] <= long_["w_trades"]
    assert short["w_days"] < long_["w_days"]


def test_the_window_ends_where_the_ROW_was_measured(offline):
    """Not at the last candle on disk — at the last bar the row was measured
    over.

    The operator caught this within minutes of the feature shipping: PONS 15m
    has candles to Sep 02 while row #AG8FFTN3 was measured to Aug 26 04:15, and
    "last 1 day" reported 46 trades on Sep 01-02 — days that row has never been
    backtested over. Their words: *"i filtered to 1 day and it shows AG8FFTN3
    even it does not have trade for sept"*. With the end taken from the row, the
    same request is Aug 24 20:15 -> Aug 25 20:15, 48 trades, -$44.58.
    """
    df = offline
    ms = df["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
    # the row stops 5 days before the candles do
    end = int(ms[-1]) - 5 * msw.MS_PER_DAY
    row = dict(_row(), last_ms=end)
    got = msw.window_rows([row], 2)
    r = got["rows"][0]
    assert r["w_last"] <= str(pd.Timestamp(end, unit="ms"))[:16],         f"the window ran past the row's own measurement: {r['w_last']}"
    assert r["w_first"] < r["w_last"]
    assert 1.5 <= r["w_days"] <= 2.1, r["w_days"]
    # and a row WITHOUT its own stamp falls back to the pair's watermark
    plain = msw.window_rows([_row()], 2)["rows"][0]
    assert plain["w_last"] >= r["w_last"],         "the fallback must not be earlier than a row that names its end"


def test_zero_days_changes_nothing(offline):
    rows = [_row()]
    got = msw.window_rows(rows, 0)
    assert got["rows"] is rows
    assert "w_trades" not in rows[0], "0 must mean 'no window', not 'today'"


def test_too_many_pairs_is_refused_with_what_to_narrow(offline, monkeypatch):
    monkeypatch.setattr(msw, "WINDOW_GROUP_MAX", 2)
    rows = [_row(coin="A"), _row(coin="B"), _row(coin="C")]
    with pytest.raises(msw.WindowTooWide) as exc:
        msw.window_rows(rows, 10)
    said = str(exc.value)
    assert "coin" in said.lower() and "signal" in said.lower(), said
    assert "3" in said and "2" in said, "it must name both numbers"


def test_the_dirs_are_cached_so_paging_is_not_a_recomputation(offline):
    msw._DIRS_CACHE.clear()
    msw.window_rows([_row()], 10)
    assert len(msw._DIRS_CACHE) == 1
    before = list(msw._DIRS_CACHE)[0]
    msw.window_rows([_row(sl=2.0)], 10)      # same rule, different barrier
    assert list(msw._DIRS_CACHE) == [before], \
        "a second row of the same rule must reuse the computed signal"


def test_the_route_takes_days_and_months_wins(offline):
    from tradingagents import api

    src = inspect.getsource(api.strategies)
    assert "days" in inspect.signature(api.strategies).parameters
    assert "if days and not months:" in src, \
        'the operator\'s rule: "if months is 0 then follow the days"'
    assert "DAYS_ROW_MAX" in src, "the page has to be capped"
    assert "window_rows" in src


def test_the_route_refuses_a_page_it_cannot_restate():
    from tradingagents import api

    assert api.DAYS_ROW_MAX >= 10
    src = inspect.getsource(api.strategies)
    i = src.index("DAYS_ROW_MAX")
    assert "503" in src[i - 400:i + 400], \
        "too big a page must be refused with the reason, never half-restated"


def test_the_panel_has_the_box_and_says_which_window_it_shows():
    panel = open("webapp/src/components/backtest/StrategiesPanel.tsx",
                 encoding="utf-8").read()
    assert 'aria-label="Last N days"' in panel
    # the filters live in a modal now, one field per line (2026-09-03), so the
    # unit is the FIELD'S NAME rather than a `day(s)` suffix beside the box
    assert '<Field label="last days"' in panel
    # months wins, and the box says so by being disabled
    assert "disabled={months > 0}" in panel
    assert "applied.months ? undefined : (applied.days || undefined)" in panel
    # the caption names the window
    i = panel.index("const andLine")
    j = panel.index('].join(" AND ")', i)
    builder = panel[i:j]
    assert "last ${f.days} day" in builder, \
        "a re-measured table under a caption saying 'all history' is the 2026-08-14 failure"
    # and the header prints the window's REAL dates, from the payload
    assert "days_window" in panel and "re-measured" in panel
    api_ts = open("webapp/src/lib/api.ts", encoding="utf-8").read()
    assert 'p.set("days"' in api_ts
    assert "days_window?: string[]" in api_ts
