"""One GitHub machine of the WATCHER REPLAY.

Operator, `Sep 28, 2026`: *"Lets say i deployed this on sept 1 / What is my
pnl overall / ... If there is no backtest yet then do backtest for aug"*, then
*"Then do the backtest replay so i know the pnl for every day to know if my
plan has relevenave"*.

Per claimed coin, per timeframe: the frame's own candles from 30 days before
the first daily check (`START`) to now, with 300 bars of warm-up in front;
the SAME costs a Backtest v2 row is charged (`learn_shard.charged` over the
coin's usual v2 cost and a fresh book read, fee, funding, liquidation); the
SAME signals (`auto_trader._dirs_for_backtest`) and the SAME fused walk
(`fast_grid.walk`) the market grid measures with, priced by the one
per-trade formula (`fast_grid.trade_pnl`).

THE BAR RULE, NOT THE MINUTES. MEXC sells about 30 days of 1-minute candles,
so August cannot be settled minute by minute; every exit here is the v1 bar
rule (both prices in one bar = the stop). Said on the results page.

ONLY WHAT COULD EVER BE SWITCHED ON IS WRITTEN. The watcher only arms TP
strictly wider than SL, a stop inside 80% of liquidation (STOP_LIQ_CEILING)
and a cost under 20% of the target (a row's `gate: ok`). Everything else is
skipped before its walk and never counted as tested. A combination that meets
the watcher's on-rule at ANY daily check (`watcher_replay`'s own `_Book.row`,
`watcher_policy.passes_on`) is written with its whole trade list; the rest are
counted, so the page can say how many combinations were tested.

Outputs (artifacts), rewritten after every coin:
  out/replay-<N>.jsonl         one line per combination that ever passed
  out/replay-report-<N>.json   counts, spans, failures by name
"""
# ruff: noqa: E402  (the imports must follow the RES/MODE environment below)
from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.environ["RES"] = ""          # the bar rule (see the docstring)
os.environ["MODE"] = "full"

import datetime as dt

import sweep_shard as ss
from learn_shard import charged, usual_costs

import tradingagents.auto_trader as at
from tradingagents import backtest_report as br
from tradingagents import fast_grid as fg
from tradingagents import watcher_policy as wp
from tradingagents import watcher_replay as wr
from tradingagents.dataflows import mexc_futures as fx

TFS = [t.strip() for t in (os.environ.get("TFS") or "15m,30m,1h,4h,1d").split(",")
       if t.strip() in br.BARRIERS]
START = (os.environ.get("START") or "2026-09-01").strip()
# WHICH GROUPS (the Stored strategies "group" filter): classic, preset, sep25
# (the learned formulas, one set per coin and timeframe) and sep27ml (the ML
# models). Operator, Sep 28, 2026: "did you used all group available?" / "i
# want all then". "all" is every one of them.
# NOT named GROUPS: that is a bash builtin (the user's unix groups), which a
# shell never passes on, so `GROUPS=sep25 python ...` silently measured all
# four groups when this was first tried on Sep 28, 2026.
GROUP_NAMES = ("classic", "preset", "sep25", "sep27ml")
GROUPS = tuple(g for g in GROUP_NAMES
               if (os.environ.get("REPLAY_GROUPS") or "all").strip() in ("all", "")
               or g in [x.strip() for x in os.environ.get("REPLAY_GROUPS", "").split(",")])
OUT = os.path.join("out", f"replay-{ss.SHARD}.jsonl")
REPORT_OUT = os.path.join("out", f"replay-report-{ss.SHARD}.json")
COIN_RETRIES = 2
WARMUP_BARS = ss.WARMUP_BARS
STOP_CEILING = at.STOP_LIQ_CEILING
GATE_OK = 0.20          # a row's `gate` is "ok" under this (sweep_shard's line)
CFG = dict(wp.DEFAULTS)


def write_rule(text: str) -> dict:
    """WHICH COMBINATIONS ARE WRITTEN: the watcher's own on-rule by default,
    or a looser one for the criteria research (operator, Sep 28, 2026: "can
    you research whats the best criteria for promotion and demotion"), e.g.
    `wr=70,trades=10,tp=>=,windows=14|30`. A rule tried later can only
    choose from combinations that were written, so the research writes
    everything its loosest rule could ever pick, under every window it tries."""
    rule = {"wr": float(CFG["on_winrate"]), "trades": int(CFG["min_trades"]),
            "tp": str(CFG["tp_rule"]), "windows": [int(CFG["window_days"])]}
    for part in (text or "").split(","):
        if "=" not in part:
            continue
        k, v = (x.strip() for x in part.split("=", 1))
        if k == "wr":
            rule["wr"] = float(v)
        elif k == "trades":
            rule["trades"] = int(v)
        elif k == "tp" and v in (">", ">="):
            rule["tp"] = v
        elif k == "windows":
            rule["windows"] = sorted({int(x) for x in v.split("|") if x.strip()})
    return rule


WRITE = write_rule(os.environ.get("REPLAY_WRITE", ""))
WRITE_CFG = {**CFG, "on_winrate": WRITE["wr"], "min_trades": WRITE["trades"],
             "tp_rule": WRITE["tp"]}


def start_ms() -> int:
    """The first daily check: local midnight of START on this machine, whose
    TZ the workflow sets to the operator's own (America/New_York)."""
    y, m, d = (int(x) for x in START.split("-"))
    return int(dt.datetime(y, m, d).timestamp() * 1000)


def checks(end_ms: int) -> list[int]:
    return wr.local_midnights(start_ms(), end_ms)


def bars_needed(tf: str, now_ms: int) -> int:
    """Enough of the frame for 30 days before the first check, to now, plus
    the warm-up — never a year of 15m bars nobody reads."""
    _iv, bs, cap = br.TFS[tf]
    span = (now_ms - (start_ms() - max(WRITE["windows"]) * wr.DAY_MS)) / 1000
    return min(cap, int(span / bs) + WARMUP_BARS + 50)


def group_of(sig: str) -> str:
    """The Stored strategies group a signal belongs to, by the one definition
    the row index filters with (rows_index.GROUP_PREFIXES)."""
    from tradingagents import rows_index as ri

    for g, prefixes in ri.GROUP_PREFIXES.items():
        if str(sig).startswith(tuple(prefixes)):
            return g
    return "classic"


def signals_for(coin: str, tf: str) -> list[str]:
    """This pair's rules in the asked groups: the shared registry, plus the
    learned formulas and ML models that belong to THIS coin and timeframe."""
    from tradingagents import signals_learned as sl, signals_ml as sm

    out = [s for s in br.SIGNALS if group_of(s) in GROUPS]
    if "sep25" in GROUPS:
        out += sl.for_pair(coin, tf)
    if "sep27ml" in GROUPS:
        out += sm.for_pair(coin, tf)
    return out


def replay_pair(sym: str, tf: str, cost: dict, stats: dict) -> list[str]:
    """Every combination of one pair that could pass, as JSON lines."""
    iv, bs, _cap = br.TFS[tf]
    sigs = signals_for(sym.replace("_USDT", ""), tf)
    if not sigs:
        return []                  # nothing of the asked groups on this pair
    now_ms = int(time.time() * 1000)
    df = at._closed_bars(fx.klines(sym, iv, bars_needed(tf, now_ms)), bs)
    first = start_ms() - max(WRITE["windows"]) * wr.DAY_MS
    ts_all = df["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
    measured = int((ts_all >= first).sum())
    if measured < br.min_bars(tf):
        stats["short"].append(f"{sym.replace('_USDT', '')} {tf}: {measured} bars")
        return []
    warm = min(WARMUP_BARS, len(df) - measured)
    df = df.iloc[len(df) - measured - warm:].reset_index(drop=True)
    hi = [float(x) for x in df["High"]]
    lo = [float(x) for x in df["Low"]]
    cl = [float(x) for x in df["Close"]]
    op = [float(x) for x in df["Open"]]
    vol = [float(x) for x in df["Volume"]] if "Volume" in df.columns else None
    ts = [int(x) for x in df["Date"].to_numpy().astype("datetime64[ms]").astype("int64")]
    fund = cost["fund"]
    f_ms, f_rate = [], []
    for f_ in sorted(fund or [], key=lambda d: d["settle_ms"]):
        f_ms.append(int(f_["settle_ms"]))
        f_rate.append(float(f_["rate"]))
    f_cum = [0.0]
    for r_ in f_rate:
        f_cum.append(f_cum[-1] + r_)
    liq, rt, fee = cost["liq"], cost["rt"], cost["fee"] + cost["slip"]
    end = ts[-1] + bs * 1000
    cks = checks(end)
    coin = sym.replace("_USDT", "")
    lines: list[str] = []
    for sig in sigs:
        key = f"{sig}_rp_{tf}"
        ths = br.THRESHOLDS[tf] if sig in br.THRESH_SIGNALS else [None]
        for th in ths:
            at.STRATEGY_SPECS[key] = {"interval": iv, "bar_seconds": bs,
                                      "tp": .02, "sl": .01,
                                      "threshold": .003 if th is None else th}
            try:
                dk = "rsi14_1h" if sig == "rsi14" else key
                dirs = at._dirs_for_backtest(dk, hi, lo, cl, opens=op,
                                             volume=vol, funding=fund, ts=ts)
            except Exception:                                  # noqa: BLE001
                at.STRATEGY_SPECS.pop(key, None)
                continue
            at.STRATEGY_SPECS.pop(key, None)
            thp = 0.0 if th is None else round(th * 100, 3)
            dirs_idx = [k for k, v in enumerate(dirs) if v and k >= warm]
            for (sl, tp) in br.pairs_for(tf):
                if not (tp > sl if WRITE["tp"] == ">" else tp >= sl):
                    continue                      # the operator's TP > SL
                if liq is not None and sl * 100 >= STOP_CEILING * abs(liq):
                    continue                      # a stop past the wall
                if rt / tp >= GATE_OK:
                    continue                      # its gate would not be ok
                stats["tested"] += 1
                if not dirs_idx:
                    continue
                walked = fg.walk(dirs_idx, dirs, op, hi, lo, cl, tp=tp, sl=sl,
                                 liq=None if liq is None else abs(liq) / 100.0,
                                 f_ms=f_ms, f_cum=f_cum, bar_ms=ts)
                if len(walked) < WRITE["trades"]:
                    continue
                trades = [[ts[e], ts[x] + bs * 1000,
                           round(fg.trade_pnl(o, w, ff, margin=ss.BASE_MARGIN,
                                              lev=at.LEVERAGE, fee=fee), 4),
                           int(w != fg.WHY_END)]
                          for (_s, e, x, _side, o, w, ff) in walked]
                combo = {"id": br.row_code(coin, tf, sig, thp, round(sl * 100, 3),
                                           round(tp * 100, 3), "flat", res="1m"),
                         "coin": coin, "tf": tf, "signal": sig, "th": thp,
                         "sl": round(sl * 100, 3), "tp": round(tp * 100, 3),
                         "gate": "ok", "cost_of_tp": round(rt / tp * 100, 1),
                         "group": group_of(sig),
                         "trades": trades}
                book = wr._Book(combo)
                if not any((r := book.row(c, w * wr.DAY_MS)) is not None
                           and not wp.passes_on(r, WRITE_CFG)
                           for w in WRITE["windows"] for c in cks):
                    continue
                stats["kept"] += 1
                lines.append(json.dumps(combo, separators=(",", ":")) + "\n")
    stats["pairs"] += 1
    stats["spans"][f"{coin} {tf}"] = [ts[warm], end]
    return lines


def coin_costs(sym: str, usual: dict) -> dict:
    """The costs a Backtest v2 row of this coin is charged — read ONCE."""
    coin = sym.replace("_USDT", "")
    fee = at.taker_fee(sym, fx=fx)
    liq = fx.liquidation_move_pct(sym, at.LEVERAGE)
    fund = fx.funding_history(sym)
    book = fx.book_cost(sym, ss.BASE_MARGIN * at.LEVERAGE)
    fresh = float(book.get("slippage") or 0.0) or 0.0003
    slip, _readings = charged(fee, fresh, usual.get(coin))
    return {"fee": fee, "liq": liq, "fund": fund, "slip": slip,
            "rt": br.round_trip_cost(fee, {"slippage": slip})}


PASSES = 3


def board_passes(coins, t0):
    """Every coin this machine claims, over up to PASSES walks of the board.

    One walk is not enough when coins are FAST. On run 36488093731 (the
    learned formulas only, Sep 28, 2026) a coin took seconds, GitHub left
    claims unanswered, `coin_stream` skipped each one ("claim of GPNSTOCK_USDT
    got no answer — skipping it, not stopping"), and every machine had
    already walked past it: 261 of 1,067 coins were claimed by nobody,
    196 of them coins with learned formulas. A later walk sees the board as
    it is THEN and claims only what is still untaken, so a coin somebody
    measured is never claimed twice. Without a board (local runs) one walk is
    the whole static slice, so there is nothing to repeat."""
    for n in range(PASSES):
        got = 0
        for sym in ss.coin_stream(coins, t0):
            got += 1
            yield sym
        if got == 0 or not ss.board.enabled:
            return
        ss.log(f"pass {n + 1} of the board claimed {got} coin(s); walking it again")


def _save(stats: dict) -> None:
    tmp = REPORT_OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(stats, fh, separators=(",", ":"))
    os.replace(tmp, REPORT_OUT)


def main() -> int:
    t0 = time.time()
    os.makedirs("out", exist_ok=True)
    coins = ss.eligible()
    usual = usual_costs()
    stats = {"start": START, "tz": os.environ.get("TZ", ""), "tfs": TFS,
             "groups": list(GROUPS), "write": WRITE,
             "cfg": CFG, "coins_board": len(coins), "coins_done": 0,
             "pairs": 0, "tested": 0, "kept": 0, "short": [], "failed": {},
             "spans": {}}
    ss.log(f"watcher replay from {START}: {len(coins)} coin(s), {TFS}")
    ss.report.board = len(coins)
    failed: dict = {}
    with open(OUT, "w", encoding="utf-8") as out:
        stream = board_passes(coins, t0)
        queue: list = []
        while True:
            sym = next(stream, None)
            if sym is None:
                if not queue:
                    break
                sym = queue.pop(0)
            before = {k: stats[k] for k in ("pairs", "tested", "kept")}
            before_short, before_spans = list(stats["short"]), dict(stats["spans"])
            try:
                cost = coin_costs(sym, usual)
                lines: list[str] = []
                for tf in TFS:
                    lines += replay_pair(sym, tf, cost, stats)
                out.write("".join(lines))       # a coin lands whole or not at all
                out.flush()
                stats["coins_done"] += 1
                stats["failed"].pop(sym, None)
            except Exception as exc:                           # noqa: BLE001
                stats.update(before)               # nothing of it counted
                stats["short"], stats["spans"] = before_short, before_spans
                n = failed.get(sym, 0) + 1
                failed[sym] = n
                ss.log(f"{sym}: FAILED ({type(exc).__name__}: {exc}) try {n}")
                if n <= COIN_RETRIES:
                    queue.append(sym)
                else:
                    stats["failed"][sym] = f"{type(exc).__name__}: {str(exc)[:200]}"
            _save(stats)
            ss.report("testing", stats["coins_done"], len(coins),
                      rows=stats["kept"],
                      note=f"{sym.replace('_USDT', '')}: {stats['kept']:,} "
                           f"passing of {stats['tested']:,} tested")
    _save(stats)
    ss.log(f"done: {stats['coins_done']} coin(s), {stats['tested']:,} tested, "
           f"{stats['kept']:,} could pass, in {(time.time() - t0) / 60:.0f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
