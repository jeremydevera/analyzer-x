"""THE backtesting-trading-strategies SKILL, RUN ON EVERY COIN x EVERY TIMEFRAME (Nov 05, 2026).

The operator: *"can you use these skills technical-analysis, backtesting-trading-strategies,
backtesting-framework / use all my existing data from v2 , v3 and generate me the best strateigioes
for all coins for all time frame"*. This runs that skill's OWN eight strategies (`vendor/btstrat`,
copied from the skill, MIT, Jeremy Longshore) with its own fill rule and its own trade statistics, on
the exchange's candles, the way the other two skills require:

* backtesting-frameworks: walk-forward - every setting is CHOSEN on the older 70% of the candles and
  JUDGED on the newest 30% it never saw; the choice is compared with the average setting of the same
  coin-timeframe on those same unseen days (the luck bar).
* technical-analysis: a stop on every trade (`STOPS`), 10+ trades on the older days before a setting
  can be chosen, every trade paying the exchange's fee both ways and the coin's usual gap.

What is the skill's, unchanged: the strategies' signals (`Strategy.generate_signals`), the bar loop
(signal on a candle's close, filled at that close plus the gap; a stop checked on the close; exit
before entry so a signal can flip), `calculate_trade_stats`. What differs, and why:

* `generate_signals` is handed the last `window(params)` candles, never every candle since the
  start: the skill re-reads the whole history at every candle (O(n^2), ~30 minutes a coin-timeframe
  here). Rolling averages read only their window, so their signals are identical; the two EWM
  strategies (ema_crossover, macd) differ by under 0.3% of a weight (tested).
* a trade is $100 of coin (the app's $5 at 20x), not 95% of a $10,000 account, so its dollars read
  like every other row on the results page; the fee is the exchange's, 0.075% each way.
"""
from __future__ import annotations

import math

from tradingagents.vendor.btstrat import metrics as sm
from tradingagents.vendor.btstrat import strategies as ss

NOTIONAL = 100.0
SPLIT = 0.70                      # older share of the candles: where a setting is chosen
MIN_OLDER = 10                    # technical-analysis: enough trades before a setting is chosen
STOPS = (0.015, 0.03)             # technical-analysis: every trade has a stop
PER_PAIR = 3
# three settings a strategy: the skill's own defaults first, then a faster and a slower one
GRID = {
    "sma_crossover": [{"fast_period": 20, "slow_period": 50}, {"fast_period": 10, "slow_period": 30},
                      {"fast_period": 50, "slow_period": 200}],
    "ema_crossover": [{"fast_period": 12, "slow_period": 26}, {"fast_period": 8, "slow_period": 21},
                      {"fast_period": 20, "slow_period": 50}],
    "rsi_reversal": [{"period": 14, "overbought": 70, "oversold": 30},
                     {"period": 7, "overbought": 80, "oversold": 20},
                     {"period": 21, "overbought": 65, "oversold": 35}],
    "macd": [{"fast": 12, "slow": 26, "signal": 9}, {"fast": 8, "slow": 21, "signal": 5},
             {"fast": 19, "slow": 39, "signal": 9}],
    "bollinger_bands": [{"period": 20, "std_dev": 2.0}, {"period": 20, "std_dev": 2.5},
                        {"period": 50, "std_dev": 2.0}],
    "breakout": [{"lookback": 20, "threshold": 0.0}, {"lookback": 50, "threshold": 0.0},
                 {"lookback": 20, "threshold": 0.5}],
    "mean_reversion": [{"period": 20, "z_threshold": 2.0}, {"period": 50, "z_threshold": 2.0},
                       {"period": 20, "z_threshold": 2.5}],
    "momentum": [{"period": 14, "threshold": 5.0}, {"period": 7, "threshold": 3.0},
                 {"period": 28, "threshold": 10.0}],
}


def _ms(index):
    """Candle times in ms, whatever unit the index holds: the exchange's frames arrive as
    datetime64[s] or [ms], and reading their raw integers as nanoseconds put every trade in 1970
    (caught on BTC before the first run, Nov 05, 2026)."""
    return index.as_unit("ms").asi8


def window(params: dict) -> int:
    """The candles a signal is computed over: three times the longest period, at least 300."""
    longest = max([int(v) for k, v in params.items() if k in
                   ("fast_period", "slow_period", "period", "slow", "signal", "lookback")] + [1])
    return max(300, 3 * longest + 5)


def signals(df, name: str, params: dict) -> list:
    """The skill's signal at every candle, from the trailing `window(params)` candles."""
    st = ss.get_strategy(name)
    w = window(params)
    out = []
    for i in range(len(df)):
        if i < st.lookback:
            out.append(None)
            continue
        out.append(st.generate_signals(df.iloc[max(0, i - w + 1): i + 1], params))
    return out


def walk(df, sigs: list, *, stop: float, fee: float, slip: float) -> list[dict]:
    """The skill's bar loop over precomputed signals: stop on the close, exit before entry, an open
    trade closed at the last candle. Each trade: entry/exit ms, side, net dollars on $100, its stop."""
    close = df["close"].to_numpy()
    when = _ms(df.index).tolist()
    trades, pos = [], None

    def close_out(i, px):
        side = 1 if pos["dir"] == "long" else -1
        move = (px - pos["px"]) / pos["px"] * side
        pnl = NOTIONAL * move - NOTIONAL * fee - NOTIONAL * (px / pos["px"]) * fee
        trades.append({"entry_ms": pos["t"], "exit_ms": when[i], "side": side,
                       "entry_px": pos["px"], "exit_px": px, "pnl": round(pnl, 4),
                       "why": pos.get("why_out", "SIGNAL"), "stop": stop})

    for i, sig in enumerate(sigs):
        if sig is None:
            continue
        c = close[i]
        buy, sell = c * (1 + slip), c * (1 - slip)
        force = False
        if pos is not None:
            ret = (c - pos["px"]) / pos["px"] * (1 if pos["dir"] == "long" else -1)
            force = ret <= -stop
        if pos is not None and (sig.exit or force):
            pos["why_out"] = "SL" if force else "SIGNAL"
            close_out(i, sell if pos["dir"] == "long" else buy)
            pos = None
        if sig.entry and pos is None:
            pos = {"t": when[i], "dir": sig.direction, "px": buy if sig.direction == "long" else sell}
    if pos is not None:
        c = close[-1]
        pos["why_out"] = "END"
        close_out(len(close) - 1, c * (1 - slip) if pos["dir"] == "long" else c * (1 + slip))
    return trades


def stats(trades: list[dict]) -> dict:
    """The skill's own trade statistics over net dollars (`calculate_trade_stats`)."""
    import pandas as pd

    objs = []
    for t in trades:
        o = sm.Trade(entry_time=pd.Timestamp(t["entry_ms"], unit="ms"),
                     exit_time=pd.Timestamp(t["exit_ms"], unit="ms"), entry_price=t["entry_px"],
                     exit_price=t["exit_px"], direction="long" if t["side"] > 0 else "short",
                     size=NOTIONAL / t["entry_px"])
        o.pnl = t["pnl"]
        objs.append(o)
    s = sm.calculate_trade_stats(objs)
    return {"trades": s["total_trades"], "win_rate": s["win_rate"], "profit_factor": s["profit_factor"],
            "expectancy": s["expectancy"], "profit": round(sum(t["pnl"] for t in trades), 4)}


def pair(df, *, fee: float, slip: float, k: int = PER_PAIR) -> dict:
    """Every setting x stop of the skill on one coin-timeframe, chosen on the older SPLIT of the
    candles (by its expectancy there, MIN_OLDER+ trades, made money there) and judged on the rest;
    fewer than `k` that qualify are filled by the next best older expectancy, flagged `older_lost`."""
    ms = _ms(df.index)
    split_ms = int(ms[int(len(df) * SPLIT)])
    combos = []
    for name, settings in GRID.items():
        for params in settings:
            sigs = signals(df, name, params)
            for stop in STOPS:
                tr = walk(df, sigs, stop=stop, fee=fee, slip=slip)
                old = [t for t in tr if t["entry_ms"] < split_ms]
                new = [t for t in tr if t["entry_ms"] >= split_ms]
                combos.append({"strategy": name, "params": params, "stop": stop, "trades": tr,
                               "older": stats(old), "newer": stats(new)})
    newer = [c["newer"] for c in combos if c["newer"]["trades"]]
    n_tr = sum(s["trades"] for s in newer)
    bar = sum(s["profit"] for s in newer) / n_tr if n_tr else None
    ok = [c for c in combos if c["older"]["trades"] >= MIN_OLDER and c["older"]["profit"] > 0]
    ok.sort(key=lambda c: -c["older"]["expectancy"])
    picks = [{**c, "older_lost": False} for c in ok[:k]]
    if len(picks) < k:
        rest = [c for c in combos if c not in ok and c["older"]["trades"] > 0]
        rest.sort(key=lambda c: -c["older"]["expectancy"])
        picks += [{**c, "older_lost": True} for c in rest[: k - len(picks)]]
    return {"split_ms": split_ms, "bars": len(df), "combos": len(combos), "bar": bar, "picks": picks,
            "start_ms": int(ms[0]), "end_ms": int(ms[-1])}


def label(c: dict) -> str:
    p = ",".join(f"{k}={v:g}" if isinstance(v, (int, float)) and not isinstance(v, bool) else f"{k}={v}"
                 for k, v in c["params"].items())
    return f"{c['strategy']}({p}) stop {c['stop'] * 100:g}%"


def finite(x):
    return x if isinstance(x, (int, float)) and math.isfinite(x) else None
