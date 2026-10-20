"""THE CHECK RUN, shared by the research searches (Oct 20, 2026).

A search keeps sums; a results table needs every row's trades (the click), its
worst losing run and its months (CLAUDE.md kit items 6 and B). So the chosen
settings are measured AGAIN with every trade kept, by the same function as the
search (`sweep_shard.run_pair` through `backtest_strategy`) asked for one
setting at one stop/target; the trade log the engine already writes is
captured on its way out, never a second walk of the exits.

Used by `cpw_shard.py` (Crypto-Predictor, Oct 19, 2026) and `pro_shard.py`
(Pro Trader, Oct 20, 2026). Import it after the caller has set RES/MODE and
imported `sweep_shard`.
"""
from __future__ import annotations

import io
import json

import sweep_shard as ss

import tradingagents.auto_trader as at
from tradingagents import backtest_report as br


def barrier_of(tf: str, sl: float, tp: float):
    """The grid's OWN floats for a stop/target given in percent
    (br.pairs_for) — a pair re-derived from its percent could differ in the
    last bit and decide a touch the search decided the other way. None when
    the grid does not measure it."""
    hit = [b for b in br.pairs_for(tf)
           if round(b[0] * 100, 4) == round(float(sl), 4)
           and round(b[1] * 100, 4) == round(float(tp), 4)]
    return hit[0] if hit else None


def parse_configs(text: str, spec_for, family: str) -> list:
    """'name:tf:sl:tp,...' (stop and target in percent) -> one dict each.
    `spec_for` is the family's own name parser: anything that is not one of
    its settings, a timeframe the search measures or a stop/target it
    measured is refused by name."""
    out = []
    for part in [p for p in str(text).split(",") if p.strip()]:
        name, tf, sl, tp = part.strip().split(":")
        spec = spec_for(name)
        if spec is None or spec["name"] != name:
            raise ValueError(f"{part}: not a {family} setting")
        if tf not in br.BARRIERS:
            raise ValueError(f"{part}: not a timeframe the search measures")
        b = barrier_of(tf, sl, tp)
        if b is None:
            raise ValueError(f"{part}: not a stop/target the search measured on {tf}")
        out.append({"key": f"{name}:{tf}:{sl}:{tp}", "name": name, "tf": tf,
                    "sl": float(sl), "tp": float(tp), "barrier": b})
    return out


def compact_trades(log: list, df, bs: int, fee: float | None = None) -> list:
    """The engine's trade log as [entry ms, exit ms, side, why, profit, cost].
    The exit is on the ENGINE'S OWN CLOCK — the minute the minutes settled it,
    else the open of the bar it closed in — so a trade falls in the same test
    month here as in the engine's window counts; the entry is the entry bar's
    open (the exit less `held_s`, which the engine counts from that open,
    floored to the minute). `cost` is the trade's whole round trip in percent
    of the position — both fees (`fee`, a fraction) and both fills, as the
    engine charged it (`pnl = (move - 2 x fee - cost in - cost out) x
    notional`) — whenever the engine ran with a minute book (a minute with no
    reading pays the coin's usual cost, so a cost here does not mean the
    book priced that very minute); None without a book."""
    ts = df["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
    out = []
    for e in log:
        xb = int(e["exit_bar"])
        xm = e.get("exit_minute_ms")
        exit_ms = int(xm) if xm is not None else int(ts[xb])
        entry_ms = (exit_ms - int(e.get("held_s") or 0) * 1000) // 60_000 * 60_000
        c_in, c_out = e.get("cost in %"), e.get("cost out %")
        cost = (round(2 * float(fee) * 100 + float(c_in) + float(c_out), 5)
                if fee is not None and c_in is not None and c_out is not None else None)
        out.append([entry_ms, exit_ms, 1 if e["side"] == "LONG" else -1,
                    str(e["why"]), round(float(e["pnl $"]), 2), cost])
    return out


def verify_pair(sym: str, tf: str, df, prefetched: dict, cfgs: list,
                done: int = 0, total: int = 0, window=None) -> list:
    """Each config of this timeframe on one coin: its row and its trades.
    `window(df) -> (dfw, warm)` is the measured window (the shard's own by
    default). A config that made no trade has no line (as the search wrote
    no row)."""
    _iv, bs, _cap = br.TFS[tf]
    dfw, warm = (window or ss.window)(df)
    lines = []
    for cfg in cfgs:
        logs: list = []
        engine = at.backtest_strategy

        def keep(*a, _engine=engine, _logs=logs, **kw):
            kw["keep_log"] = True
            r = _engine(*a, **kw)
            _logs.append(r.get("log") or [])
            return r

        buf = io.StringIO()
        saved = (ss.window, br.pairs_for, at.backtest_strategy)
        ss.window = lambda _df: (dfw, warm)
        br.pairs_for = lambda _tf, _b=cfg["barrier"]: [_b]
        at.backtest_strategy = keep
        try:
            ss.run_pair(sym, tf, buf, i=done, n=total, signals=[cfg["name"]],
                        learned={**prefetched, "df": df})
        finally:
            ss.window, br.pairs_for, at.backtest_strategy = saved
        rows = [json.loads(x) for x in buf.getvalue().splitlines() if x.strip()]
        rows = [r for r in rows if r.get("signal") == cfg["name"]]
        if not rows or not logs:
            continue
        lines.append({"cfg": cfg["key"], "coin": sym.replace("_USDT", ""), "tf": tf,
                      "row": rows[0],
                      "trades": compact_trades(logs[-1], dfw, bs, prefetched.get("fee"))})
    return lines
