"""The "last N days" window re-measures a Gate v2 row with the order book of
every minute, the way the row was measured (final review, Oct 10, 2026;
RCA-2026-10-10-H).

The stored v2 row refuses an entry the runner's cost check would refuse and
pays each trade its own minutes' fills (`backtest_strategy(book=)`). The
window re-ran the same row with no book at all, so the "last 30 days" figure
counted trades the row had refused — and the CSV and the page read it.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import numpy as np

from tests.test_trade_log_is_read_only import BAR_MS, _frame
from tradingagents import cost_store, market_sweep as msw


def test_a_v2_window_reads_the_book_up_to_the_rows_last_bar(tmp_path, monkeypatch):
    now_ms = int(time.time() * 1000) // BAR_MS * BAR_MS
    df = _frame(n=700, start_ms=now_ms - 700 * BAR_MS)
    last_ms = int(df["Date"].iloc[-1].timestamp() * 1000)
    store = SimpleNamespace(home=tmp_path, fine_tf="1m", candles=tmp_path / "c",
                            name="v2")
    for sub in ("state", "rows", "costs"):
        (tmp_path / sub).mkdir()
    monkeypatch.setattr(msw, "cached_candles", lambda *a, **k: df)
    monkeypatch.setattr(msw, "bars_from_1m", lambda m1, tf: df)
    msw.save_costs("TEST_USDT", fee=0.00075, liq=4.5, funding=[], root=str(tmp_path))
    monkeypatch.setenv("TA_VENUE", "gate")
    asked = []

    def book_for(sym, start_s, end_s, **k):
        asked.append((sym, end_s))
        t = np.arange(int(df["Date"].iloc[0].timestamp()), end_s + 1, 60, dtype="int64")
        n = len(t)
        return {"t": t, "bid": np.full(n, 99.0), "ask": np.full(n, 101.0),
                "spread": np.full(n, 0.03, "float32"), "buy": np.full(n, 0.015, "float32"),
                "sell": np.full(n, 0.015, "float32"), "exhausted": np.zeros(n, "bool"),
                "source": np.ones(n, "int8")}
    monkeypatch.setattr(cost_store, "book_for", book_for)
    row = {"coin": "TEST", "tf": "1h", "signal": "mom6", "th": 0.1, "sl": 1.0,
           "tp": 2.0, "sizing": "flat", "last_ms": last_ms, "base": 5.0, "fee": 0.00075}
    got = msw.window_rows([dict(row)], 10, store=store)
    assert asked == [("TEST_USDT", last_ms // 1000)]
    assert got["rows"][0].get("w_trades") == 0, \
        "a 3% gap on a 1% stop: every entry refused, as the row refused it"
    monkeypatch.setenv("TA_VENUE", "mexc")
    asked.clear()
    got = msw.window_rows([dict(row)], 10, store=store)
    assert asked == [] and got["rows"][0].get("w_trades", 0) > 0, "MEXC has no book"
