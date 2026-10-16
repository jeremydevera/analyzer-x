"""UPDATE THIS BACKTEST on Gate measures the nightly run's 30 days, never the
span of this PC's minute folder (RCA-2026-10-15-B).

The press sized its window from this PC's own 1-minute candle file
(`candle_index()["SYM-1m"]`): on MEXC that file held the 30 days of minutes
MEXC sells, so it was right by accident. On Gate the runners fetch their own
minutes and this PC's file holds about a day, so every press measured ONE
day and merged those rows over the shard's 30-day rows under the same ids.
Oct 15, 2026 7:06-7:10pm: QNTX 15m willr14 (50 rows) and stoch14 (30), ALAB
15m fvg (21) and part of ANKR 30m fade15 went from 29 days and ~80-160
trades to 0 days and ~11-16 trades.
"""
from __future__ import annotations

import pytest

from tradingagents import cloud_sweep as cs, db_jobs as dj, market_sweep as msw

DAY = 86_400_000
WATERMARK = 1_792_105_200_000          # Oct 15, 2026 7:00pm


@pytest.fixture
def press(monkeypatch):
    got = {}

    def run_pair(sym, tf, **kw):
        got.update(sym=sym, tf=tf, **kw)
        return {"rows": [], "why": "no new bars"}

    monkeypatch.setattr(msw, "run_pair", run_pair)
    monkeypatch.setattr(msw, "candle_index", lambda scan=False: {
        "QNTX_USDT-1m": {"first_ms": 1_792_000_000_000,
                         "last_ms": 1_792_000_000_000 + DAY}})     # a day of minutes
    # the pair's last measured candle, the same before and after the press
    monkeypatch.setattr(msw, "pair_watermark", lambda *a, **k: WATERMARK)
    # the table write answers at once (a missing pair file made it retry
    # three times, 20 s apart: 60 s a test)
    from tradingagents import rows_index as ri
    monkeypatch.setattr(ri, "index_pair", lambda *a, **k: 0)
    return got


def test_on_gate_a_v2_press_measures_the_nightly_window(press, monkeypatch):
    monkeypatch.setattr(msw, "FINE_TF", "1m")
    monkeypatch.setattr(msw, "_gate_v2", lambda: True)
    dj._run_pairbt({"coin": "QNTX_USDT", "tf": "15m", "signal": "willr14"},
                   kind="pairbt_v2")
    assert press["days"] == cs.SWEEP_DAYS == 30


def test_off_gate_the_press_keeps_its_span(press, monkeypatch):
    """MEXC's v2 and v1 are unchanged: the pair's own span."""
    monkeypatch.setattr(msw, "FINE_TF", "1m")
    monkeypatch.setattr(msw, "_gate_v2", lambda: False)
    dj._run_pairbt({"coin": "QNTX_USDT", "tf": "15m", "signal": "willr14"},
                   kind="pairbt_v2")
    assert press["days"] == 1


# --- "already current" is said only when nothing was measured --------------
def _said():
    import json

    return json.loads(dj.FILES["pairbt_v2"]["progress"].read_text(encoding="utf-8"))


def test_a_press_that_measured_never_says_it_was_already_current(press, monkeypatch):
    """ANKR 30m fade15, Oct 15, 2026 7:23pm: the press re-measured 300 rows
    over 30 days (they had been one-day rows, RCA-2026-10-15-B) and printed
    "300 row(s), 234 indexed · no new bars — it was already current"; the
    row's own panel would have read "Already up to date". The label came
    from the last measured candle staying put, not from whether anything was
    measured (RCA-2026-10-15-H)."""
    monkeypatch.setattr(msw, "FINE_TF", "1m")
    monkeypatch.setattr(msw, "_gate_v2", lambda: True)
    monkeypatch.setattr(msw, "run_pair",
                        lambda sym, tf, **kw: {"rows": [{}] * 300, "days": 29})
    dj._run_pairbt({"coin": "ANKR_USDT", "tf": "30m", "signal": "fade15"},
                   kind="pairbt_v2")
    st = _said()
    assert st["already_current"] is False, st
    assert "no new bars" not in st["note"] and "already current" not in st["note"]


def test_a_press_with_no_new_bars_still_says_so(press, monkeypatch):
    monkeypatch.setattr(msw, "FINE_TF", "1m")
    monkeypatch.setattr(msw, "_gate_v2", lambda: True)
    monkeypatch.setattr(msw, "run_pair", lambda sym, tf, **kw: {
        "rows": [{}] * 50, "why": "no new bars", "new_bars": 0})
    dj._run_pairbt({"coin": "QNTX_USDT", "tf": "15m", "signal": "willr14"},
                   kind="pairbt_v2")
    st = _said()
    assert st["already_current"] is True
    assert "no new bars — it was already current" in st["note"]
