"""Room strategies settle every exit by the minute, as Stored strategies do.

The operator, Oct 21, 2026, told that Stored strategies (Backtest v2) settle
a trade minute by minute while Room strategies — the nightly replay
(`.github/scripts/replay_shard.py`) whose trades the Room strategies table
re-measures — settled it candle by candle: *"then you should fix room
strategy"*. An exit candle that touched BOTH the target and the stop was a
loss by rule there, whatever happened first (ARKM 1h mom6: 45 of 359 trades).

The replay now asks the ENGINE's own minute rule
(`auto_trader.settle_in_minutes`, through `fast_grid.walk(settle=)`), so the
first test runs both over one random price path and demands the same trade,
the same exit minute and the same dollars, every time.

Every clock here is ONE timeline: the minutes sit inside the candles they
belong to, and the candles are built FROM the minutes (RCA-2026-09-12-A).
"""
from __future__ import annotations

import bisect
import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tradingagents import auto_trader as at, fast_grid as fg

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".github" / "scripts"
H0 = 1_789_516_800_000            # Sep 16, 2026 00:00 UTC, on the hour
KEY = "t_room_minutes_1h"


def _path(n_hours: int, seed: int, step: float = 0.0012):
    """Minutes of a random walk and the hour candles built from them."""
    rng = np.random.default_rng(seed)
    n = n_hours * 60
    px = 100.0 * np.exp(np.cumsum(rng.normal(0, step, n)))
    opens_m = np.r_[100.0, px[:-1]]
    hi_m = np.maximum(opens_m, px) * (1 + np.abs(rng.normal(0, step / 3, n)))
    lo_m = np.minimum(opens_m, px) * (1 - np.abs(rng.normal(0, step / 3, n)))
    t_m = H0 + np.arange(n, dtype="int64") * 60_000
    hours = pd.DataFrame({
        "Date": pd.to_datetime(H0 + np.arange(n_hours) * 3_600_000, unit="ms"),
        "Open": opens_m[::60], "High": hi_m.reshape(-1, 60).max(1),
        "Low": lo_m.reshape(-1, 60).min(1), "Close": px[59::60],
        "Volume": np.full(n_hours, 1000.0)})
    return hours, (t_m, hi_m, lo_m)


@pytest.fixture
def spec():
    at.STRATEGY_SPECS[KEY] = {"interval": "Min60", "bar_seconds": 3600,
                              "tp": .006, "sl": .004, "threshold": .003}
    yield
    at.STRATEGY_SPECS.pop(KEY, None)


@pytest.mark.parametrize("seed", [1, 7, 21])
def test_the_replay_and_the_backtest_settle_every_trade_the_same(spec, seed):
    hours, fine = _path(400, seed)
    n = len(hours)
    dirs = [0] * n
    for k in range(3, n - 2, 5):
        dirs[k] = 1 if (k // 5) % 2 else -1
    tp, sl, fee = 0.006, 0.004, 0.0005
    fund = [{"settle_ms": H0 + h * 3_600_000 + 1_800_000, "rate": 0.0001 * (1 if h % 16 else -3)}
            for h in range(0, n, 8)]
    eng = at.backtest_strategy(KEY, hours, 5.0, fee=0.0004, slippage=0.0001,
                               sizing="flat", dirs=dirs, tp=tp, sl=sl,
                               liq_move_pct=4.5, funding=fund, keep_log=True,
                               fine=fine, reenter=True)
    ts = [int(x) for x in hours["Date"].to_numpy().astype("datetime64[ms]").astype("int64")]
    f_ms = [f["settle_ms"] for f in fund]
    f_cum = [0.0]
    for f in fund:
        f_cum.append(f_cum[-1] + f["rate"])
    t_m, h_m, l_m = fine

    def settle(j, s, tp_px, sl_px, liq_px):
        return at.settle_in_minutes(t_m, h_m, l_m, ts[j], 3600, s, tp_px, sl_px,
                                    liq_px, liq=0.045, sl=sl)

    exits: list = []
    op, hi, lo, cl = (list(map(float, hours[c])) for c in ("Open", "High", "Low", "Close"))
    walked = fg.walk([k for k, v in enumerate(dirs) if v], dirs, op, hi, lo, cl,
                     tp=tp, sl=sl, liq=0.045, f_ms=f_ms, f_cum=f_cum, bar_ms=ts,
                     reenter=True, settle=settle, exit_at=exits)
    names = {fg.WHY_TP: "TP", fg.WHY_SL: "SL", fg.WHY_LIQ: "LIQ", fg.WHY_END: "END"}
    mine = [(names[w], m, round(fg.trade_pnl(o, w, ff, margin=5.0, lev=at.LEVERAGE, fee=fee), 2))
            for (_s, _e, _x, _side, o, w, ff), m in zip(walked, exits, strict=True)]
    theirs = [(r["why"], r["exit_minute_ms"], r["pnl $"]) for r in eng["log"]]
    assert len(mine) > 20, "the path must make enough trades to mean something"
    assert mine == theirs
    # and the minutes really decided some of them: candles that touched both
    by_candle = fg.walk([k for k, v in enumerate(dirs) if v], dirs, op, hi, lo, cl,
                        tp=tp, sl=sl, liq=0.045, f_ms=f_ms, f_cum=f_cum, bar_ms=ts,
                        reenter=True)
    assert [w for *_, w, _f in by_candle] != [w for *_, w, _f in walked] or seed != 1


def test_without_minutes_the_walk_is_the_walk_of_before():
    hours, _fine = _path(200, 3)
    dirs = [0] * len(hours)
    for k in range(2, len(hours) - 1, 4):
        dirs[k] = -1 if k % 8 else 1
    args = ([k for k, v in enumerate(dirs) if v], dirs,
            *(list(map(float, hours[c])) for c in ("Open", "High", "Low", "Close")))
    a = fg.walk(*args, tp=0.005, sl=0.004, liq=0.045, reenter=True)
    exits: list = []
    b = fg.walk(*args, tp=0.005, sl=0.004, liq=0.045, reenter=True,
                settle=lambda *x: None, exit_at=exits)
    assert a == b and set(exits) == {None}


# ------------------------------------------------- the replay machine itself
@pytest.fixture(autouse=True)
def _no_two_to_one_floor(monkeypatch):
    from tradingagents import watcher_policy as wp

    monkeypatch.setitem(wp.DEFAULTS, "min_pay", 0.0)


@pytest.fixture
def rs(monkeypatch):
    for k in ("GITHUB_TOKEN", "GITHUB_REPOSITORY", "COIN_LIST", "INGEST_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("START", "2026-09-01")
    monkeypatch.setenv("REPLAY_GROUPS", "classic,preset")
    monkeypatch.syspath_prepend(str(SCRIPTS))
    sp = importlib.util.spec_from_file_location("replay_shard_minutes", SCRIPTS / "replay_shard.py")
    mod = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(mod)
    monkeypatch.setattr(mod, "WRITE", mod.write_rule("wr=40,trades=1,tp=>,windows=30"))
    monkeypatch.setattr(mod, "WRITE_CFG", {**mod.CFG, "on_winrate": 40.0, "min_trades": 1,
                                           "tp_rule": ">", "min_pay": 0.0})
    yield mod
    sys.modules.pop("replay_shard_minutes", None)


START = dt.datetime(2026, 7, 20)
NOW = dt.datetime(2026, 9, 10)


def _both_world(rs, monkeypatch, tp_first: bool):
    """Flat at 100, a long signal every 6th hour; the hour after it touches
    BOTH a 1% target (101.1) and a 0.7% stop (99.2). Its minutes say which
    came first: minute 0 reaches one, minute 30 the other."""
    from tradingagents import backtest_report as br
    from tradingagents.dataflows import mexc_futures as mf

    n = int((NOW - START).total_seconds() // 3600)
    t0 = int(pd.Timestamp(START).value // 1_000_000)
    both = {k + 1 for k in range(0, n - 1, 6)}
    hours = pd.DataFrame({
        "Date": pd.to_datetime(t0 + np.arange(n, dtype="int64") * 3_600_000, unit="ms"),
        "Open": 100.0, "High": [101.1 if k in both else 100.0 for k in range(n)],
        "Low": [99.2 if k in both else 100.0 for k in range(n)], "Close": 100.0,
        "Volume": 1.0})
    t_m = t0 + np.arange(n * 60, dtype="int64") * 60_000
    h_m = np.full(n * 60, 100.0)
    l_m = np.full(n * 60, 100.0)
    for k in both:
        first, later = (k * 60, k * 60 + 30)
        if tp_first:
            h_m[first], l_m[later] = 101.1, 99.2
        else:
            l_m[first], h_m[later] = 99.2, 101.1
    monkeypatch.setattr(mf, "klines", lambda sym, iv, limit: hours.tail(limit))
    monkeypatch.setattr(at, "_closed_bars", lambda d, bs: d)
    monkeypatch.setattr(rs.time, "time", lambda: NOW.timestamp())
    monkeypatch.setattr(br, "SIGNALS", ["bb20"])
    # by the CLOCK, not the index: the replay cuts the frame before it asks
    monkeypatch.setattr(at, "_dirs_for_backtest",
                        lambda key, hi, *a, ts=None, **k: [
                            1 if ((int(t) - t0) // 3_600_000) % 6 == 0 else 0 for t in ts])
    monkeypatch.setattr(br, "pairs_for", lambda tf: [(0.007, 0.01)])
    cost = {"fee": 0.0002, "slip": 0.0001, "liq": 4.5, "fund": [], "rt": 0.0006,
            "fine": (t_m, h_m, l_m)}
    return cost, t0


def _replay(rs, cost):
    stats = {"pairs": 0, "tested": 0, "kept": 0, "short": [], "spans": {}}
    lines = rs.replay_pair("GPNSTOCK_USDT", "1h", cost, stats)
    return [json.loads(x) for x in lines], stats


def test_a_candle_that_touched_both_is_a_win_when_its_minutes_reached_the_target_first(rs, monkeypatch):
    cost, t0 = _both_world(rs, monkeypatch, tp_first=True)
    combos, stats = _replay(rs, cost)
    assert len(combos) == 1
    closed = [t for t in combos[0]["trades"] if t[3]]
    assert closed and all(t[2] > 0 for t in closed), "the target came first: every one wins"
    assert stats["settled_by_minute"] >= len(closed) and not stats.get("settled_by_candle")
    # stamped at the end of the minute it closed in (minute 0 of the entry
    # hour), never the end of the candle
    first = closed[0]
    assert first[1] == first[0] + 60_000


def test_the_same_candles_without_minutes_were_all_losses(rs, monkeypatch):
    cost, _t0 = _both_world(rs, monkeypatch, tp_first=True)
    cost["fine"] = None
    combos, stats = _replay(rs, cost)
    assert combos == [], "candle by candle every one is the stop: 0% never passes 40%"
    assert stats.get("settled_by_candle", 0) > 0 and not stats.get("settled_by_minute")


def test_a_stop_reached_first_is_still_a_loss(rs, monkeypatch):
    cost, _t0 = _both_world(rs, monkeypatch, tp_first=False)
    combos, stats = _replay(rs, cost)
    assert combos == [] and stats["settled_by_minute"] > 0


def test_each_coin_reads_its_minutes_once_over_the_whole_replay(rs, monkeypatch):
    """coin_costs fetches the minutes from before the first window to now —
    the replay's whole span — through the one v2 helper."""
    from tradingagents import backtest_report as br

    asked = []

    def fine_bars(sym, start_s, end_s=None, *, fx=None):
        asked.append((sym, start_s))
        return (np.array([1], dtype="int64"), np.array([1.0]), np.array([1.0]), 0)

    monkeypatch.setattr(br, "fine_bars", fine_bars)
    monkeypatch.setattr(rs.fx, "taker_fee", lambda *a, **k: 0.00075, raising=False)
    monkeypatch.setattr(rs.at, "taker_fee", lambda *a, **k: 0.00075)
    monkeypatch.setattr(rs.fx, "liquidation_move_pct", lambda *a, **k: 4.5, raising=False)
    monkeypatch.setattr(rs.fx, "funding_history", lambda *a, **k: [], raising=False)
    monkeypatch.setattr(rs.fx, "book_cost", lambda *a, **k: {"slippage": 0.0002}, raising=False)
    monkeypatch.setattr(rs._venue, "current", lambda: "mexc")
    got = rs.coin_costs("BTC_USDT", {})
    first_s = (rs.start_ms() - max(rs.WRITE["windows"]) * rs.wr.DAY_MS) // 1000 - 2 * 86400
    assert asked == [("BTC_USDT", first_s)] and got["fine"] is not None


def test_minutes_that_cannot_be_read_keep_the_candle_rule_and_say_so(rs, monkeypatch, capsys):
    from tradingagents import backtest_report as br

    def broken(*a, **k):
        raise TimeoutError("archive did not answer")

    monkeypatch.setattr(br, "fine_bars", broken)
    monkeypatch.setattr(rs.at, "taker_fee", lambda *a, **k: 0.00075)
    monkeypatch.setattr(rs.fx, "liquidation_move_pct", lambda *a, **k: 4.5, raising=False)
    monkeypatch.setattr(rs.fx, "funding_history", lambda *a, **k: [], raising=False)
    monkeypatch.setattr(rs.fx, "book_cost", lambda *a, **k: {"slippage": 0.0002}, raising=False)
    monkeypatch.setattr(rs._venue, "current", lambda: "mexc")
    got = rs.coin_costs("BTC_USDT", {})
    assert got["fine"] is None
    assert "settled by its candle" in capsys.readouterr().out


def test_the_engine_and_the_replay_share_one_minute_rule():
    """No second copy: the engine's closure and the replay both call it."""
    eng = (ROOT / "tradingagents" / "auto_trader.py").read_text(encoding="utf-8")
    rep = (SCRIPTS / "replay_shard.py").read_text(encoding="utf-8")
    i = eng.index("def _settle_fine(")
    assert "settle_in_minutes(" in eng[i:i + 600]
    assert "at.settle_in_minutes(" in rep
    assert ">= tp_px" not in rep and "<= sl_px" not in rep,         "the replay never compares a minute to a barrier by itself"


def test_funding_runs_to_the_exit_minute():
    """A stop at :28 does not pay a settlement at :30 (the engine's rule)."""
    hours = pd.DataFrame({"Open": [100.0, 100.0, 100.0], "High": [100.0, 100.0, 100.0],
                          "Low": [100.0, 99.0, 100.0], "Close": [100.0, 100.0, 100.0]})
    ts = [H0, H0 + 3_600_000, H0 + 7_200_000]
    f_ms = [H0 + 3_600_000 + 30 * 60_000]
    f_cum = [0.0, 0.01]
    args = ([0], [1, 0, 0], *(list(hours[c]) for c in ("Open", "High", "Low", "Close")))
    exits: list = []
    w = fg.walk(*args, tp=0.02, sl=0.005, liq=None, f_ms=f_ms, f_cum=f_cum, bar_ms=ts,
                settle=lambda j, s, a, b, c: ("SL", H0 + 3_600_000 + 28 * 60_000, 0),
                exit_at=exits)
    assert w[0][5] == fg.WHY_SL and w[0][6] == 0.0
    assert exits == [H0 + 3_600_000 + 28 * 60_000]
    by_candle = fg.walk(*args, tp=0.02, sl=0.005, liq=None, f_ms=f_ms, f_cum=f_cum, bar_ms=ts)
    assert by_candle[0][6] == 0.0, "the candle rule charges to the exit bar's open (as before)"
    assert bisect.bisect_right(f_ms, ts[1]) == 0
