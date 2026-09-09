"""Continue a measured pair over NEW BARS ONLY, from a saved position.

Operator, 2026-09-09: *"if the last backtest was sep1 and i click update it
should run on github to update the gap which is sept 2 onwards simple as
that"*. Until now every GitHub run measured the whole window from scratch,
because a GitHub machine is wiped clean after each run and had nothing to
continue from. This module is the memory: a pair's per-combination resume
state, written by the run that measured it (`fast_grid.end_state`) and read by
the next run, which walks only the bars printed since.

The continuation itself is `auto_trader.backtest_strategy(resume=...)` — the
same engine, same call, that `market_sweep.run_pair` uses on this PC for
UPDATE. Nothing here re-implements a barrier or a ladder rung.

One thing the engine's resume forgets is the losing streak (its state has no
run_sum/run_len), so a run of losses that straddles the boundary would be
understated — the PC's own updates have that gap. The cloud state carries the
streak (`end_state`) and `fold_streak` continues it over the new trades.

FILE SHAPE — one gzip'd JSON per pair, the PC's own state layout plus meta:

    {"__last_ms__": 1788...,           # every bar up to here is tested
     "__first_ms__": 1757...,          # the pair's first measured bar
     "__bars__": 34598,                # bars measured so far
     "__signals__": ["cci20", ...],    # what this state has measured
     "__version__": "signals120-th3",  # market_sweep's fingerprint
     "__fee__": 0.0004,                # the taker fee the rows were charged
     "<signal>|<th>|<sl>|<tp>|<sizing>": {engine state + streak}, ...}
"""
from __future__ import annotations

import gzip
import json

ENGINE_KEYS = ("trades", "wins", "profit", "worst", "equity", "peak", "max_dd",
               "step", "monthly", "liqs", "funding_total", "open", "last_ms")
STREAK_KEYS = ("streak_sum", "streak_len", "worst_streak", "worst_streak_len")
META = ("__last_ms__", "__first_ms__", "__bars__", "__signals__",
        "__version__", "__fee__")


def pack(states: dict) -> bytes:
    """gzip'd JSON. 7,000 combinations per pair is ~1.4 MB of JSON and most
    of it repeats (step 0, open null, the same 13 month keys), so gzip takes
    it to a fraction — small enough for twenty machines to fetch every pair's
    state at the start of a run."""
    return gzip.compress(json.dumps(states, separators=(",", ":")).encode("utf-8"))


def unpack(blob: bytes) -> dict:
    return json.loads(gzip.decompress(blob).decode("utf-8"))


def fold_streak(prev: dict, pnls) -> dict:
    """Continue the losing streak carried in `prev` over the new trades' PnLs,
    in order. Returns the four streak fields for the new state."""
    run_sum = float(prev.get("streak_sum") or 0.0)
    run_len = int(prev.get("streak_len") or 0)
    worst = float(prev.get("worst_streak") or 0.0)
    worst_len = int(prev.get("worst_streak_len") or 0)
    for pnl in pnls:
        pnl = float(pnl)
        if pnl > 0:
            run_sum, run_len = 0.0, 0
        else:
            run_sum += pnl
            run_len += 1
            if run_sum < worst:
                worst, worst_len = run_sum, run_len
    return {"streak_sum": run_sum, "streak_len": run_len,
            "worst_streak": worst, "worst_streak_len": worst_len}


def continue_combo(key: str, frame, base: float, *, fee: float, sizing: str,
                   dirs, tp: float, sl: float, liq, funding, prev: dict,
                   start_at: int) -> tuple[dict, dict]:
    """One combination, continued over `frame` from `prev`.

    `frame` holds the new bars plus the lookback the signal rules need
    (market_sweep.CONTEXT_BARS); `start_at` is where the new bars begin. The
    engine is called exactly as market_sweep.run_pair calls it for a PC update
    — `fee` is the taker fee alone (the engine adds slippage itself), and
    `resume=prev` carries totals, ladder rung and any open trade.

    keep_log=True on purpose: a gap holds few trades, and their PnLs are what
    lets the streak continue exactly (the engine's resume drops it).

    Returns (result, new_state): `result` is the engine's report with
    `worst_streak`/`worst_streak_len` REPLACED by the continued streak;
    `new_state` is `result["state"]` plus the streak fields.
    """
    import tradingagents.auto_trader as at

    # THE BOUNDARY BAR. A signal on the last tested bar enters on the first
    # NEW bar — the previous run could not take it (no next bar) and the
    # engine's resume searches signals from `start_at` on, so it was lost:
    # 65 trades continued against 66 in one run (2026-09-09). Start the
    # search one bar early — unless a trade EXITED on that bar (the engine
    # resumes from exit+1, so that signal is unavailable in a full run too)
    # or a trade is still open across it (no signal is taken while open).
    # market_sweep.run_pair on this PC has the same gap; this is the cloud's.
    start = int(start_at)
    if start > 0 and not prev.get("open") and not prev.get("exit_at_last"):
        start -= 1
    r = at.backtest_strategy(key, frame, base, fee=fee, sizing=sizing,
                             dirs=dirs, tp=tp, sl=sl, liq_move_pct=liq,
                             funding=funding, keep_log=True,
                             resume=prev, start_at=start)
    streak = fold_streak(prev, (row["pnl $"] for row in r.get("log") or []))
    r = dict(r)
    r["worst_streak"] = round(streak["worst_streak"], 2)
    r["worst_streak_len"] = streak["worst_streak_len"]
    r.pop("log", None)
    new_state = dict(r["state"])
    new_state.update(streak)
    return r, new_state


def gap_frame(df, last_ms: int, lookback: int):
    """The slice a continuation walks: every bar newer than `last_ms`, plus
    `lookback` bars before the first of them. Returns (frame, start_at,
    new_bars); new_bars == 0 means nothing to do."""
    ms = df["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
    newer = [k for k, v in enumerate(ms) if int(v) > int(last_ms)]
    if not newer:
        return None, 0, 0
    start = newer[0]
    lo = max(0, start - int(lookback))
    return df.iloc[lo:].reset_index(drop=True), start - lo, len(df) - start
