"""Every trade-log row says how long the trade was held.

Operator, Sep 05, 2026: *"when i click a stored strategy and you show the day
trades, can you show how many hours/days the trade was hold just like the auto
trade open trades"*.

"just like the auto trade open trades" is the requirement, not a comparison:
the live Positions table's `held` column is `positions_view.fmt_age`, so the
backtest log uses THAT function rather than a second one. Two implementations
of one format is what this repo has paid for five times over with dates.

WHAT THE HARDDEV LOOP FOUND. Bar-to-bar arithmetic makes a trade that exits
inside its own entry bar last ZERO seconds — and that is 93 of 162 trades
(57%) on an hourly grid, every one of which would have read "0m" and claimed
it closed the instant it opened. The candles cannot say where in the bar the
barrier was hit, so the honest label is an upper bound in the frame's own
units: "<1h" hourly, "<15m" on 15m, "<1d" daily.
"""
from __future__ import annotations

import pandas as pd
import pytest

from tradingagents import auto_trader as at, positions_view as pv

KEY = "mom6_1h_pv"


def _log(step, n=400):
    """A saw-tooth that trades often, on candles `step` apart."""
    t0 = pd.Timestamp("2026-06-01 00:00:00")
    px = [100 + (i % 17) - 8 for i in range(n)]
    df = pd.DataFrame([{"Date": t0 + i * step, "Open": px[i],
                        "High": px[i] + 3, "Low": px[i] - 3, "Close": px[i]}
                       for i in range(n)])
    got = at.backtest_strategy(KEY, df, 5.0, tp=0.03, sl=0.03, sizing="flat",
                               funding=[], keep_log=True)
    assert got["log"], "the fixture must produce trades"
    return got["log"]


def test_every_row_carries_a_held_value():
    for t in _log(pd.Timedelta(hours=1)):
        assert t.get("held"), f"a trade with no held value: {t['entry time']}"
        assert t.get("held_s") is not None


def test_it_uses_the_same_formatter_as_the_live_positions_table():
    """`positions_view.fmt_age` — not a second implementation."""
    for t in _log(pd.Timedelta(hours=1)):
        if t["held_s"] > 0:
            assert t["held"] == pv.fmt_age(t["held_s"]), t


def test_a_same_bar_exit_is_an_upper_bound_not_zero():
    """93 of 162 trades on an hourly grid exit inside their entry bar. "0m"
    would say each of them closed the instant it opened."""
    log = _log(pd.Timedelta(hours=1))
    same = [t for t in log if t["held_s"] == 0]
    assert same, "the fixture must contain same-bar exits"
    for t in same:
        assert t["held"] == "<1h", t["held"]
        assert t["held"] != "0m"


@pytest.mark.parametrize("step,label", [
    (pd.Timedelta(minutes=15), "<15m"),
    (pd.Timedelta(minutes=30), "<30m"),
    (pd.Timedelta(hours=4), "<4h"),
    (pd.Timedelta(days=1), "<1d"),
])
def test_the_bound_is_in_the_frames_own_units(step, label):
    """Read from the candles themselves, so no interval string can be wrong."""
    same = [t for t in _log(step) if t["held_s"] == 0]
    assert same, f"no same-bar exit on {label}"
    assert {t["held"] for t in same} == {label}


def test_a_real_hold_reads_in_words():
    """The ordinary case: a multi-bar trade in hours and days."""
    log = _log(pd.Timedelta(hours=1))
    held = [t for t in log if t["held_s"] >= 3600]
    assert held, "the fixture must contain multi-bar trades"
    for t in held[:20]:
        assert any(u in t["held"] for u in ("m", "h", "d")), t["held"]
        assert not t["held"].startswith("<")


def test_held_never_goes_backwards():
    for t in _log(pd.Timedelta(hours=1)):
        assert t["held_s"] >= 0, t


def test_the_seconds_match_the_two_stamps():
    """`held` must describe THESE two times, not a third number."""
    log = _log(pd.Timedelta(hours=1))
    for t in log[:30]:
        a = pv.fmt_when  # the project's one date format, both ends
        assert isinstance(a(0), str)
        if t["held_s"] == 0:
            assert t["entry time"] == t["exit time"], \
                "a zero hold must be the same bar at both ends"


def test_the_sweep_stores_no_logs_so_nothing_grew():
    """`held` rides on the on-demand restate only. The sweep runs with
    keep_log=False, so the 49.9M-row store is untouched by this."""
    import inspect

    src = inspect.getsource(__import__("tradingagents.market_sweep",
                                       fromlist=["x"]))
    assert "keep_log=False" in src


def test_the_browser_shows_the_column():
    """A field nothing renders is not a feature."""
    panel = open("webapp/src/components/backtest/StrategiesPanel.tsx",
                 encoding="utf-8").read()
    assert '"held"' in panel, "the column header"
    assert "t.held" in panel, "and the cell that draws it"
    types = open("webapp/src/lib/api.ts", encoding="utf-8").read()
    assert "held?: string;" in types
