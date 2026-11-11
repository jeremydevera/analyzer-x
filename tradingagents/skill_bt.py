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
* A STOP OR TARGET IS SETTLED BY THE MINUTE WHERE THE MINUTES ARE KNOWN (Nov 11, 2026, operator: "if i
  will be using 1m candle do you think it will be more precise" - "okay then change backtest and the
  practice rooms together, so they keep matching each other"). The signal still needs the CLOSED candle
  and an entry still fills at its close plus the gap; but once a trade is open, each later candle's
  minutes are walked in order (`auto_trader.settle_in_minutes`, Backtest v2's own rule) and the first
  minute that touched the stop or the target ends it, at that price plus the gap, funding charged up to
  that minute. Both in one minute is the stop, counted `unclear`. A candle the minutes do not cover (the
  exchange keeps them for a limited stretch: `MINUTE_DAYS`) keeps the old rule - the close decides -
  and is COUNTED (`tally`), never hidden. With `fine=None` every line below is the rule of before.
* a trade is $100 of coin (the app's $5 at 20x), not 95% of a $10,000 account, so its dollars read
  like every other row on the results page; the fee is the exchange's, 0.075% each way.
"""
from __future__ import annotations

import json
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


def _strategy(name: str):
    """The backtesting-trading-strategies skill's eight, or the other two skills' (skill_ta.py)."""
    from tradingagents import skill_ta

    return skill_ta.STRATEGIES.get(name) or ss.get_strategy(name)


def signals(df, name: str, params: dict) -> list:
    """The skill's signal at every candle, from the trailing `window(params)` candles; a strategy
    that works out every candle at once (`signals_all`, skill_ta.py) is asked for them in one go."""
    st = _strategy(name)
    if hasattr(st, "signals_all"):
        return st.signals_all(df, params)
    w = window(params)
    out = []
    for i in range(len(df)):
        if i < st.lookback:
            out.append(None)
            continue
        out.append(st.generate_signals(df.iloc[max(0, i - w + 1): i + 1], params))
    return out


class Funding:
    """A coin's funding settlements (`fx.funding_history`'s shape: `settle_ms`, `rate`), cumulated so
    `paid(a, b)` - the sum of the rates settled in (a, b] - is two bisects. A positive rate means the
    longs pay, so a long's cost is `+paid`, a short's is `-paid`."""

    def __init__(self, settlements: list[dict]):
        import bisect

        self._bisect = bisect.bisect_right
        rows = sorted(((int(s["settle_ms"]), float(s["rate"])) for s in settlements or []),
                      key=lambda r: r[0])
        self._at = [r[0] for r in rows]
        self._cum = [0.0]
        for _, rate in rows:
            self._cum.append(self._cum[-1] + rate)

    def paid(self, from_ms: int, to_ms: int) -> float:
        if to_ms <= from_ms or not self._at:
            return 0.0
        return self._cum[self._bisect(self._at, to_ms)] - self._cum[self._bisect(self._at, from_ms)]


MINUTE_DAYS = 120                 # how far back the minutes are read: Forecast v4 walks ~98 days
MINUTE_MS = 60_000


def fine_from_ms(day_ms: int) -> int:
    """Where the minutes begin for the run of the UTC day starting `day_ms`: MINUTE_DAYS days before
    it. The daily GitHub run and a follower warming a strategy up at that midnight both ask this, so
    a candle is settled by the minute on one side exactly when it is on the other."""
    return int(day_ms) - MINUTE_DAYS * 86_400_000


class Fine:
    """The minutes (or, over the exchange's hole, 5-minute bars) between `from_ms` and `to_ms`, as
    `settle_in_minutes` reads them: sorted opens in ms, highs, lows. A candle is settled by the minute
    only when it lies wholly inside [from_ms, to_ms] - anything else keeps the candle rule."""

    def __init__(self, opens, highs, lows, from_ms: int, to_ms: int):
        import numpy as np

        self.t = np.asarray(opens, dtype="int64")
        self.h = np.asarray(highs, dtype="float64")
        self.l = np.asarray(lows, dtype="float64")
        self.from_ms, self.to_ms = int(from_ms), int(to_ms)

    def covers(self, when_ms: int, bar_ms: int) -> bool:
        return self.from_ms <= int(when_ms) and int(when_ms) + int(bar_ms) <= self.to_ms

    def settle(self, when_ms: int, bar_ms: int, side: int, tp_px: float | None, sl_px: float):
        """`(why, minute_ms, unclear)` for the candle opening at `when_ms`, or None when no minute
        lies under it. `why` is "SL", "TP" or "NONE" (the minutes touched neither)."""
        from tradingagents.auto_trader import settle_in_minutes

        far = float("inf") if side == 1 else float("-inf")
        return settle_in_minutes(self.t, self.h, self.l, int(when_ms), int(bar_ms) // 1000, side,
                                 far if tp_px is None else tp_px, sl_px, None, liq=None, sl=0.0)


def read_fine(sym: str, from_ms: int, to_ms: int | None = None, *, minutes=None,
              now_s: float | None = None) -> "Fine":
    """The minutes of `sym` from `from_ms` to `to_ms` (default: now), the exchange's own
    (`fx.minutes`: the archive, 5-minute bars over its monthly hole, the last week from REST). The
    forming minute is dropped - it is not final. `minutes` is the reader and `now_s` the clock, for tests and for a pass that has one."""
    import time

    import numpy as np

    if minutes is None:
        from tradingagents.dataflows import exchange as fx

        minutes = fx.minutes
    now_s = int(time.time() if now_s is None else now_s)
    end_s = now_s if to_ms is None else min(now_s, int(to_ms) // 1000)
    start_s = int(from_ms) // 1000
    m = minutes(sym, start_s, end_s)
    if m is None or not len(m):
        return Fine([], [], [], from_ms, from_ms)
    t = m["Date"].to_numpy().astype("datetime64[s]").astype("int64")
    secs = m["Seconds"].to_numpy() if "Seconds" in m.columns else np.full(len(m), 60)
    keep = t + secs <= end_s
    t, secs = t[keep], secs[keep]
    if not len(t):
        return Fine([], [], [], from_ms, from_ms)
    hi = np.asarray(m["High"], dtype="float64")[keep]
    lo = np.asarray(m["Low"], dtype="float64")[keep]
    return Fine(t * 1000, hi, lo, int(from_ms), int((t[-1] + secs[-1]) * 1000))


def close_position(pos: dict, px: float, when_ms: int, *, why: str, stop: float, fee: float,
                   target: float | None = None, bar_ms: int = 0, funding: "Funding | None" = None,
                   at_ms: int | None = None) -> dict:
    """The trade a position becomes when it is closed at `px` on the candle opening at `when_ms`:
    net dollars on $100 after the fee both ways and, when `funding` is given, the funding settled
    between the entry fill and the exit fill (a candle's open + its length - or, for an exit the
    minutes settled, `at_ms`'s own minute: the trade then carries `at`, the minute it ended in)."""
    side = 1 if pos["dir"] == "long" else -1
    move = (px - pos["px"]) / pos["px"] * side
    pnl = NOTIONAL * move - NOTIONAL * fee - NOTIONAL * (px / pos["px"]) * fee
    trade = {"entry_ms": pos["t"], "exit_ms": when_ms, "side": side, "entry_px": pos["px"],
             "exit_px": px, "pnl": round(pnl, 4), "why": why, "stop": stop, "target": target}
    if at_ms is not None:
        trade["at"] = int(at_ms)
    if funding is not None:
        fill = pos.get("fill_ms", pos["t"] + bar_ms)
        end = when_ms + bar_ms if at_ms is None else int(at_ms) + MINUTE_MS
        fund = -side * funding.paid(fill, end) * NOTIONAL
        trade["fund"] = round(fund, 4)
        trade["pnl"] = round(pnl + fund, 4)
    return trade


def step(pos: dict | None, sig, *, close: float, when_ms: int, bar_ms: int, stop: float, fee: float,
         slip: float, target: float | None = None, funding: "Funding | None" = None,
         fine: "Fine | None" = None, tally: dict | None = None):
    """ONE candle of the skill's bar loop - stop, target, the strategy's own exit, close, then entry -
    so the backtest, the daily shard and a room following the strategy live run one set of rules.
    Returns `(position after, the trade it closed or None)`. A `None` signal (warm-up) changes nothing.
    `pos` is never changed in place; an opened position remembers its entry fill (`fill_ms`)."""
    if sig is None:
        return pos, None
    buy, sell = close * (1 + slip), close * (1 - slip)
    force = won = False
    trade = None
    if pos is not None and fine is not None:
        side = 1 if pos["dir"] == "long" else -1
        if fine.covers(when_ms, bar_ms):
            sl_px = pos["px"] * (1 - side * stop)
            tp_px = None if target is None else pos["px"] * (1 + side * target)
            got = fine.settle(when_ms, bar_ms, side, tp_px, sl_px)
            if got is not None and got[0] in ("SL", "TP"):
                why, minute, unclear = got
                px = (sl_px if why == "SL" else tp_px) * (1 - side * slip)
                trade = close_position(pos, px, when_ms, why=why, stop=stop, fee=fee, target=target,
                                       bar_ms=bar_ms, funding=funding, at_ms=minute)
                pos = None
                if tally is not None:
                    tally["minute"] = tally.get("minute", 0) + 1
                    tally["unclear"] = tally.get("unclear", 0) + int(unclear)
            elif tally is not None:
                # the minutes touched nothing ("NONE"), or none lies under the candle (None: the
                # candle rule below decides, as Backtest v2 keeps the bar rule)
                key = "minute" if got is not None else "candle"
                tally[key] = tally.get(key, 0) + 1
        elif tally is not None:
            tally["candle"] = tally.get("candle", 0) + 1
    if pos is not None:
        ret = (close - pos["px"]) / pos["px"] * (1 if pos["dir"] == "long" else -1)
        force = ret <= -stop
        won = target is not None and ret >= target
    mine = sig.exit and getattr(sig, "exit_dir", None) in (None, pos and pos["dir"])
    if pos is not None and (mine or force or won):
        why = "SL" if force else "TP" if won else "SIGNAL"
        trade = close_position(pos, sell if pos["dir"] == "long" else buy, when_ms, why=why, stop=stop,
                               fee=fee, target=target, bar_ms=bar_ms, funding=funding)
        pos = None
    if sig.entry and pos is None:
        pos = {"t": when_ms, "dir": sig.direction, "px": buy if sig.direction == "long" else sell,
               "fill_ms": when_ms + bar_ms}
    return pos, trade


def run(df, sigs: list, *, stop: float, fee: float, slip: float, target: float | None = None,
        funding: "Funding | None" = None, bar_ms: int = 0, fine: "Fine | None" = None,
        tally: dict | None = None):
    """`step()` over every candle: the trades closed, and the position still open (NOT closed)."""
    close = df["close"].to_numpy()
    when = _ms(df.index).tolist()
    trades, pos = [], None
    for i, sig in enumerate(sigs):
        pos, done = step(pos, sig, close=close[i], when_ms=when[i], bar_ms=bar_ms, stop=stop, fee=fee,
                         slip=slip, target=target, funding=funding, fine=fine, tally=tally)
        if done:
            trades.append(done)
    return trades, pos


def walk(df, sigs: list, *, stop: float, fee: float, slip: float, target: float | None = None,
         funding: "Funding | None" = None, bar_ms: int = 0, fine: "Fine | None" = None,
         tally: dict | None = None) -> list[dict]:
    """The skill's bar loop over precomputed signals: stop on the close, exit before entry, an open
    trade closed at the last candle. Each trade: entry/exit ms, side, net dollars on $100, its stop.
    `target` (skill_ta.py's 2x the stop) closes a trade whose close reached it, checked like the stop;
    a signal's `exit_dir` limits its exit to that side. Neither given = the skill's loop as before.
    `funding` (with `bar_ms`, the candle's length) adds each trade's funding as `fund`; without it a
    trade is exactly what it always was. The loop body is `step()`, shared with the skill rooms."""
    trades, pos = run(df, sigs, stop=stop, fee=fee, slip=slip, target=target, funding=funding, bar_ms=bar_ms,
                      fine=fine, tally=tally)
    if pos is not None:
        c = df["close"].to_numpy()[-1]
        trades.append(close_position(pos, c * (1 - slip) if pos["dir"] == "long" else c * (1 + slip),
                                     _ms(df.index).tolist()[-1], why="END", stop=stop, fee=fee,
                                     target=target, bar_ms=bar_ms, funding=funding))
    return trades


def signal_at(df, name: str, params: dict, bars: int):
    """The signal of `df`'s LAST candle, computed as the backtest computes it: a strategy that works
    out every candle at once reads the last `bars` candles; the others the trailing `window(params)`
    (None while the history is no longer than the strategy's lookback)."""
    st = _strategy(name)
    if hasattr(st, "signals_all"):
        return st.signals_all(df.tail(bars), params)[-1]
    if len(df) <= st.lookback:
        return None
    return st.generate_signals(df.tail(window(params)), params)


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


def pair(df, *, fee: float, slip: float, k: int | None = PER_PAIR, grid: dict | None = None,
         targets: dict | None = None) -> dict:
    """Every setting x stop of the skill on one coin-timeframe, chosen on the older SPLIT of the
    candles (by its expectancy there, MIN_OLDER+ trades, made money there) and judged on the rest;
    fewer than `k` that qualify are filled by the next best older expectancy, flagged `older_lost`.
    `grid`/`targets` run another skill's strategies (skill_ta.GRID, skill_ta.TARGETS: a target as a
    multiple of the stop, None = none); left out, the backtesting-trading-strategies skill's own.
    `k=None` keeps EVERY setting x stop (operator, Nov 05, 2026: "i dont want top 3 show me all"),
    the qualifying ones first, then every other one flagged `older_lost` - one with no trade too."""
    ms = _ms(df.index)
    split_ms = int(ms[int(len(df) * SPLIT)])
    combos = []
    for name, settings in (grid or GRID).items():
        r = (targets or {}).get(name)
        for params in settings:
            sigs = signals(df, name, params)
            for stop in STOPS:
                tg = round(stop * r, 6) if r else None
                tr = walk(df, sigs, stop=stop, fee=fee, slip=slip, target=tg)
                old = [t for t in tr if t["entry_ms"] < split_ms]
                new = [t for t in tr if t["entry_ms"] >= split_ms]
                combos.append({"strategy": name, "params": params, "stop": stop, "target": tg, "trades": tr,
                               "older": stats(old), "newer": stats(new)})
    newer = [c["newer"] for c in combos if c["newer"]["trades"]]
    n_tr = sum(s["trades"] for s in newer)
    bar = sum(s["profit"] for s in newer) / n_tr if n_tr else None
    ok = [c for c in combos if c["older"]["trades"] >= MIN_OLDER and c["older"]["profit"] > 0]
    ok.sort(key=lambda c: -c["older"]["expectancy"])
    if k is None:
        rest = [c for c in combos if c not in ok]
        rest.sort(key=lambda c: -(c["older"]["expectancy"] if c["older"]["trades"] else -1e9))
        picks = [{**c, "older_lost": False} for c in ok] + [{**c, "older_lost": True} for c in rest]
        return {"split_ms": split_ms, "bars": len(df), "combos": len(combos), "bar": bar, "picks": picks,
                "start_ms": int(ms[0]), "end_ms": int(ms[-1])}
    picks = [{**c, "older_lost": False} for c in ok[:k]]
    if len(picks) < k:
        rest = [c for c in combos if c not in ok and c["older"]["trades"] > 0]
        rest.sort(key=lambda c: -c["older"]["expectancy"])
        picks += [{**c, "older_lost": True} for c in rest[: k - len(picks)]]
    return {"split_ms": split_ms, "bars": len(df), "combos": len(combos), "bar": bar, "picks": picks,
            "start_ms": int(ms[0]), "end_ms": int(ms[-1])}


def measure(df, combos: list[dict], *, fee: float, slip: float, funding: "Funding | None" = None,
            bar_ms: int = 0, fine: "Fine | None" = None, tally: dict | None = None) -> list[dict]:
    """Walk each `{strategy, params, stop, target}` over `df`; the signals of one (strategy, params)
    are computed once however many stops use them. A trade is `[entry_ms, exit_ms, side, why, pnl]`,
    its pnl after the fee, the gap and (when `funding` is given) the funding it paid. A combo's
    `split_ms`, when it has one, rides along."""
    sig_of: dict = {}
    out = []
    for c in combos:
        key = (c["strategy"], json.dumps(c["params"], sort_keys=True))
        if key not in sig_of:
            sig_of[key] = signals(df, c["strategy"], c["params"])
        tr = walk(df, sig_of[key], stop=c["stop"], fee=fee, slip=slip, target=c.get("target"),
                  funding=funding, bar_ms=bar_ms, fine=fine, tally=tally)
        row = {"label": label(c), "strategy": c["strategy"], "params": c["params"], "stop": c["stop"],
               "target": c.get("target"), "older_lost": False,
               # a trade the minutes settled carries a sixth item: the minute it ended in
               "trades": [[t["entry_ms"], t["exit_ms"], t["side"], t["why"], t["pnl"]]
                          + ([t["at"]] if "at" in t else []) for t in tr]}
        if "split_ms" in c:
            row["split_ms"] = c["split_ms"]
        out.append(row)
    return out


def daily_combos(pinned: dict | None) -> list[dict]:
    """The daily run's strategies of one coin-timeframe: all 42 technical-analysis / backtesting-
    frameworks settings x stops (skill_ta.GRID, its targets), then ONLY the backtesting skill's picks
    pinned for that pair (`research/v4/bt_pinned.json`), each with the pair's original `split_ms`."""
    from tradingagents import skill_ta

    combos = []
    for name, settings in skill_ta.GRID.items():
        r = skill_ta.TARGETS.get(name)
        for params in settings:
            for stop in STOPS:
                combos.append({"strategy": name, "params": params, "stop": stop,
                               "target": round(stop * r, 6) if r else None})
    for p in (pinned or {}).get("picks", []):
        combos.append({"strategy": p["strategy"], "params": p["params"], "stop": p["stop"],
                       "target": p.get("target"), "split_ms": (pinned or {})["split_ms"]})
    return combos


def daily_line(coin: str, tf: str, df, pinned: dict | None, *, fee: float, slip: float,
               funding: "Funding | None", bar_ms: int, fine: "Fine | None" = None) -> dict:
    """One coin-timeframe of the daily run, in `skill_shard.line()`'s keys. The pinned picks keep
    their own (older) `split_ms`; the line's is where THIS frame's 70% falls, for the 42 new ones.
    With `fine`, a stop or target is settled by the minute where the minutes cover the candle; the line
    says how many candle-steps of an open trade were settled each way (`exits`: minute, candle,
    unclear - summed over every strategy of the line)."""
    ms = _ms(df.index)
    tally: dict = {}
    picks = measure(df, daily_combos(pinned), fee=fee, slip=slip, funding=funding, bar_ms=bar_ms,
                    fine=fine, tally=tally)
    out = {"coin": coin, "tf": tf, "fee": fee, "slip": slip, "bars": len(df), "combos": len(picks),
           "split_ms": int(ms[int(len(df) * SPLIT)]), "start_ms": int(ms[0]), "end_ms": int(ms[-1]),
           "bar": None, "picks": picks}
    if fine is not None:
        out["exits"] = {"minute": int(tally.get("minute", 0)), "candle": int(tally.get("candle", 0)),
                        "unclear": int(tally.get("unclear", 0)), "from_ms": fine.from_ms}
    return out


def label(c: dict) -> str:
    p = ",".join(f"{k}={v:g}" if isinstance(v, (int, float)) and not isinstance(v, bool) else f"{k}={v}"
                 for k, v in c["params"].items())
    tg = c.get("target")
    return f"{c['strategy']}({p}) stop {c['stop'] * 100:g}%" + (f" target {tg * 100:g}%" if tg else "")


def finite(x):
    return x if isinstance(x, (int, float)) and math.isfinite(x) else None
