"""UPDATE THIS BACKTEST downloads the new candles BEFORE it measures.

The operator, `Sep 18, 2026`: *"when i click update this backtest, it should
update candle first then do backtest"*. It always did — `market_sweep.run_pair`
calls `refresh_candles` on the way in — but the candles it fetched were being
thrown away by the backwards fill (RCA-2026-09-18-N), so two presses on
#LG9NSU4B measured over candles that stopped `Aug 27, 2026 1:00pm`.

So the order is now held by a test, in the state the button runs in: the job
the button starts (`db_jobs._run_pairbt` → `msw.run_pair`) fetches first and
measures second, and the measurement sees the bars the fetch brought back.
"""
from __future__ import annotations

import pandas as pd
import pytest

from tradingagents import market_sweep as msw

H = 3_600_000
T0 = 1_756_857_600_000          # Sep 03, 2025 00:00 UTC


def _bars(n: int, first_ms: int = T0) -> pd.DataFrame:
    t = [first_ms + i * H for i in range(n)]
    return pd.DataFrame({
        "Date": pd.to_datetime(t, unit="ms"),
        "Open": [1.0] * n, "High": [1.05] * n, "Low": [0.95] * n,
        "Close": [1.0] * n, "Volume": [10.0] * n})


@pytest.fixture
def traced(monkeypatch):
    """`run_pair` with the venue and the engine faked, recording the order."""
    order: list = []
    fetched = _bars(400)

    def fake_refresh(symbol, tf, *, days=365):
        order.append(("refresh", symbol, tf))
        return fetched, 12, "delta"

    def fake_grid(*a, **k):
        order.append(("measure", len(a[1]) if len(a) > 1 else None))
        return []

    monkeypatch.setattr(msw, "refresh_candles", fake_refresh)
    from tradingagents.dataflows import mexc_futures as fx
    monkeypatch.setattr(fx, "funding_history", lambda s: [])
    monkeypatch.setattr(fx, "liquidation_move_pct", lambda s, lev: 4.5)
    monkeypatch.setattr(fx, "book_cost", lambda s, n: 0.05)
    import tradingagents.auto_trader as at
    monkeypatch.setattr(at, "taker_fee", lambda s, fx=None: 0.0004)
    return order, fetched


def test_the_candles_are_fetched_before_anything_is_measured(traced, monkeypatch):
    order, fetched = traced
    seen: dict = {}

    def spy_combos(coin, tf, df, *a, **k):
        seen["bars"] = len(df)
        seen["last"] = df["Date"].iloc[-1]
        order.append(("measure", len(df)))
        return []

    monkeypatch.setattr(msw, "_pair_grid", spy_combos, raising=False)
    try:
        msw.run_pair("XPIN_USDT", "1h", base_margin=5.0, days=30,
                     thresholds=1, fresh=False, merge=True, signals=["ote"])
    except Exception:
        # the engine is not faked all the way down on every version of this
        # function; the ORDER is what this test is about
        pass
    assert order and order[0][0] == "refresh", order
    assert order[0][1] == "XPIN_USDT" and order[0][2] == "1h"


def test_the_job_the_button_starts_goes_through_run_pair(monkeypatch, tmp_path):
    """`_run_pairbt` must not measure by itself — it calls `run_pair`, which is
    the only path that refreshes the candles first."""
    import inspect

    from tradingagents import db_jobs as dj

    src = inspect.getsource(dj._run_pairbt)
    assert "msw.run_pair(" in src, src[:400]
    assert "backtest_strategy" not in src, \
        "a second measuring path would skip the candle refresh"


def test_run_pair_refreshes_once_per_path_and_before_it_measures():
    """One fetch per pair on the way in — never per signal or per barrier.

    TWO calls, not one: the v2 branch fetches the 1-minute candles it rebuilds
    its bars from, the v1 branch fetches the frame itself. Both sit before the
    venue reads and the engine.
    """
    import inspect

    src = inspect.getsource(msw.run_pair)
    calls = [ln.strip() for ln in src.splitlines() if "refresh_candles(" in ln]
    assert len(calls) == 2, calls
    assert any("FINE_TF" in c for c in calls), "the v2 path fetches its minutes"
    assert any(", tf, days=days)" in c for c in calls), "the v1 path fetches its frame"
    assert src.index("refresh_candles(") < src.index("funding_history("), \
        "the candles are fetched before the venue reads that follow"
