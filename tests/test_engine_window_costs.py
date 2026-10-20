"""The engine's recent windows carry the round trips their trades paid
(auto_trader.backtest_strategy, Oct 20, 2026).

Why: the Pro Trader research chooses a setting on the days BEFORE the month
it is judged on, and "does it pay 2:1 after fees" must read the fees of those
days too — the whole window's average (`rt_paid`) includes the judged month
(code review, Oct 20, 2026). So each window also sums what its trades paid,
and nothing else in the result moves."""
from __future__ import annotations

import math
import random

import pandas as pd
import pytest

from tradingagents import auto_trader as at


def _df(n=3000, seed=11):
    rnd = random.Random(seed)
    px, rows = 100.0, []
    t0 = pd.Timestamp("2026-06-01")
    for i in range(n):
        op = px
        cl = op * math.exp(rnd.gauss(0, 0.006))
        rows.append({"Date": t0 + pd.Timedelta(hours=i), "Open": op,
                     "High": max(op, cl) * (1 + abs(rnd.gauss(0, 0.002))),
                     "Low": min(op, cl) * (1 - abs(rnd.gauss(0, 0.002))),
                     "Close": cl, "Volume": 1000.0})
        px = cl
    return pd.DataFrame(rows)


KEY = "pt_rand_s0r0_gh_1h"


@pytest.fixture(autouse=True)
def _spec(monkeypatch):
    # the measuring code registers each grid key before it asks the engine
    monkeypatch.setitem(at.STRATEGY_SPECS, KEY, {"interval": "Min60", "bar_seconds": 3600,
                                                 "tp": .02, "sl": .01, "threshold": .003})


def _run(df, dirs, **kw):
    return at.backtest_strategy(KEY, df, 5.0, fee=0.00075, slippage=0.0004,
                                sizing="flat", dirs=dirs, tp=0.02, sl=0.008, keep_log=False,
                                start_at=300, **kw)


def test_each_window_sums_the_round_trips_its_trades_paid():
    df = _df()
    rnd = random.Random(3)
    dirs = [0] * 300 + [rnd.choice((0, 0, 0, 0, 1, -1)) for _ in range(len(df) - 300)]
    end = int(df["Date"].iloc[-1].timestamp() * 1000)
    wins = {d: end - d * 86_400_000 for d in (30, 60)}
    r = _run(df, dirs, recent_windows=wins)
    # no minute book here: every trade pays the flat round trip, 2 x (fee +
    # slippage) = 2 x 0.115% (auto_trader: fee = fee + slippage)
    rt = 2 * (0.00075 + 0.0004) * 100
    for d in (30, 60):
        got = r["recents"][d]
        assert got["trades"] > 0
        assert got["rt_sum"] == pytest.approx(rt * got["trades"], rel=1e-6)
    assert r["recents"][60]["rt_sum"] > r["recents"][30]["rt_sum"]


def test_nothing_else_in_the_result_moves():
    df = _df(n=1500, seed=4)
    rnd = random.Random(8)
    dirs = [0] * 300 + [rnd.choice((0, 0, 0, 1, -1)) for _ in range(len(df) - 300)]
    end = int(df["Date"].iloc[-1].timestamp() * 1000)
    plain = _run(df, dirs)
    windowed = _run(df, dirs, recent_windows={30: end - 30 * 86_400_000})
    windowed.pop("recents")
    for k in ("trades", "wins", "losses", "profit", "worst_streak", "max_dd", "monthly"):
        assert windowed[k] == plain[k], k
