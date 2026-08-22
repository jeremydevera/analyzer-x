"""The one-pass grid core must reproduce backtest_strategy TO THE CENT.

Six engine runs become two walks plus scaling; every shortcut in that sentence
is an assumption about the engine (sizing never moves an exit, the first half
is a prefix, the ladder's rungs survive re-marking). Each is only safe while
these tests hold the derivation against the real engine, combination by
combination, on data rough enough to hit every exit path — TP, SL, LIQ, END,
funding both signs, wins and losing streaks.
"""
import random

import pandas as pd
import pytest

from tradingagents import auto_trader as at, fast_grid as fg


def _frame(n=900, seed=7):
    rng = random.Random(seed)
    o, h, l, c, t = [], [], [], [], []
    px = 100.0
    ts0 = 1_700_000_000_000
    for i in range(n):
        op = px
        px = px * (1 + rng.gauss(0, 0.01))
        hi = max(op, px) * (1 + abs(rng.gauss(0, 0.004)))
        lo = min(op, px) * (1 - abs(rng.gauss(0, 0.004)))
        if i % 97 == 0:                     # occasional violent bar -> LIQ
            hi *= 1.06
            lo *= 0.94
        o.append(op)
        h.append(hi)
        l.append(lo)
        c.append(px)
        t.append(ts0 + i * 3_600_000)
    return pd.DataFrame({"Date": pd.to_datetime(t, unit="ms"),
                         "Open": o, "High": h, "Low": l, "Close": c,
                         "Volume": [1000.0] * n})


def _dirs(n, seed=11, every=9):
    rng = random.Random(seed)
    out = [0] * n
    for i in range(20, n, every):
        out[i] = rng.choice([1, -1, 0])
    return out


def _funding(n_bars, seed=3):
    rng = random.Random(seed)
    ts0 = 1_700_000_000_000
    return [{"settle_ms": ts0 + k * 4 * 3_600_000,
             "rate": rng.choice([0.0001, -0.0002, 0.0005, -0.001])}
            for k in range(n_bars // 4 + 2)]


BARRIERS = [(0.01, 0.02), (0.02, 0.01), (0.005, 0.04), (0.03, 0.03),
            (0.06, 0.02),               # SL beyond the 4.5% liq -> LIQ fires
            (0.002, 0.002), (0.04, 0.08)]


def _engine(df, dirs, *, tp, sl, sizing, liq, fund):
    key = "mom6_fastgrid_test"
    at.STRATEGY_SPECS[key] = {"interval": "Min60", "bar_seconds": 3600,
                              "tp": tp, "sl": sl, "threshold": 0.003}
    try:
        return at.backtest_strategy(
            key, df, 5.0, fee=0.0004, sizing=sizing, dirs=dirs, tp=tp, sl=sl,
            liq_move_pct=liq, funding=fund, keep_log=False)
    finally:
        at.STRATEGY_SPECS.pop(key, None)


def _fast(df, dirs, *, tp, sl, liq, fund):
    ms = df["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
    f_ms, f_rate = [], []
    for f in sorted(fund or [], key=lambda d: d["settle_ms"]):
        f_ms.append(int(f["settle_ms"]))
        f_rate.append(float(f["rate"]))
    f_cum = [0.0]
    for r in f_rate:
        f_cum.append(f_cum[-1] + r)
    mo = df["Date"].to_numpy().astype("datetime64[M]")
    labels = {}
    mo_idx = []
    order = []
    for v in mo:
        if v not in labels:
            labels[v] = len(order)
            order.append(str(v)[:7])
        mo_idx.append(labels[v])
    opens = [float(x) for x in df["Open"]]
    high = [float(x) for x in df["High"]]
    low = [float(x) for x in df["Low"]]
    close = [float(x) for x in df["Close"]]
    didx = [k for k, v in enumerate(dirs) if v]
    return fg.combo_six(
        didx, dirs, opens, high, low, close, tp=tp, sl=sl,
        liq=None if liq is None else abs(liq) / 100.0, half=len(df) // 2,
        base=5.0, lev=at.LEVERAGE, fee=0.0004 + 0.0003,
        ladder=at.ladder_margin, mo_idx=mo_idx, mo_labels=order,
        f_ms=f_ms, f_cum=f_cum, bar_ms=ms)


KEYS = ("trades", "wins", "losses", "profit", "worst_trade", "max_dd",
        "monthly", "months_green", "months_total", "liqs", "funding_total")


@pytest.mark.parametrize("tp,sl", [(t, s) for s, t in BARRIERS])
@pytest.mark.parametrize("sizing", ["flat", "martingale"])
@pytest.mark.parametrize("funded", [True, False])
def test_full_run_matches_engine(tp, sl, sizing, funded):
    df = _frame()
    dirs = _dirs(len(df))
    fund = _funding(len(df)) if funded else []
    liq = 4.5
    want = _engine(df, dirs, tp=tp, sl=sl, sizing=sizing, liq=liq, fund=fund)
    got = _fast(df, dirs, tp=tp, sl=sl, liq=liq, fund=fund)[sizing]["full"]
    for k in KEYS:
        assert got[k] == want[k], (k, got[k], want[k])


@pytest.mark.parametrize("tp,sl", [(t, s) for s, t in BARRIERS])
@pytest.mark.parametrize("sizing", ["flat", "martingale"])
def test_halves_match_engine(tp, sl, sizing):
    df = _frame(seed=23)
    dirs = _dirs(len(df), seed=29, every=7)
    fund = _funding(len(df))
    liq = 4.5
    half = len(df) // 2
    got = _fast(df, dirs, tp=tp, sl=sl, liq=liq, fund=fund)[sizing]
    a = _engine(df.iloc[:half], dirs[:half], tp=tp, sl=sl, sizing=sizing,
                liq=liq, fund=fund)
    b = _engine(df.iloc[half:], dirs[half:], tp=tp, sl=sl, sizing=sizing,
                liq=liq, fund=fund)
    for k in KEYS:
        assert got["h1"][k] == a[k], ("h1", k, got["h1"][k], a[k])
        assert got["h2"][k] == b[k], ("h2", k, got["h2"][k], b[k])


def test_no_liq_and_no_funding_still_match():
    df = _frame(seed=41)
    dirs = _dirs(len(df), seed=43)
    want = _engine(df, dirs, tp=0.02, sl=0.01, sizing="martingale",
                   liq=None, fund=[])
    got = _fast(df, dirs, tp=0.02, sl=0.01, liq=None, fund=[])
    assert got["martingale"]["full"]["profit"] == want["profit"]
    assert got["martingale"]["full"]["trades"] == want["trades"]


def test_boundary_open_trade_is_marked_like_the_engine():
    """A trade open across the half boundary must END-mark at the boundary
    bar in h1 — force one with a huge TP/SL so nothing exits early."""
    df = _frame(seed=57, n=400)
    dirs = [0] * len(df)
    dirs[190] = 1                       # opens at bar 191, half is 200
    fund = _funding(len(df))
    for sizing in ("flat", "martingale"):
        a = _engine(df.iloc[:200], dirs[:200], tp=5.0, sl=5.0,
                    sizing=sizing, liq=None, fund=fund)
        got = _fast(df, dirs, tp=5.0, sl=5.0, liq=None,
                    fund=fund)[sizing]["h1"]
        for k in KEYS:
            assert got[k] == a[k], (sizing, k, got[k], a[k])
