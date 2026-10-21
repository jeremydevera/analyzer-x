"""One GitHub machine of the PRO TRADER STORE run — the group "Oct 21".

The operator, Oct 20, 2026, after the Pro Trader research: *"okay deploy this
i want this new batch as group 'Oct 21'"* (pointing at the group filter of
Stored strategies, beside "Sep 25 Strat" and "Sep 27 ML").

Every Pro Trader setting (tradingagents/signals_pro.py, prefix pt_ — the
eight literature families, NEVER the random baseline, which is no strategy)
measured on every coin and timeframe exactly as a Backtest v2 row is: the
nightly grid's own function (`sweep_shard.run_pair`, rows only — no pair-done
marker, no saved position, no live post), Backtest v2's 30-day window with
300 bars of lead-in, every exit settled by the minute, every trade paying its
own minute's order book, funding, the 1-4 and 15-day counts the rooms judge
on. The stop/targets are the research's own (signals_pro.BARRIERS_PCT: every
one pays 2:1 after a 0.23% round trip).

Settings that give the SAME signals in the window are measured once and the
row written for each of them under its own name (the review of Oct 20, 2026
proved the engine trades only from the window's first bar, so the copies are
exact).

Outputs (artifacts): out/pro-rows-<N>.jsonl (Backtest v2 rows, res="1m"),
out/pro-store-report-<N>.json (every coin + timeframe attempted, with its row
count or the reason) — the report rewritten after every coin, and a pair's
rows written only once the whole pair is measured.
"""
# ruff: noqa: E402  (the imports must follow the RES/MODE/DAYS environment below)
from __future__ import annotations

import io
import json
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
# Backtest v2 exactly: minute-settled exits, a full measurement, its 30 days
os.environ["RES"] = "1m"
os.environ["MODE"] = "full"
os.environ.setdefault("DAYS", "30")

import check_run as cr
import numpy as np
import sweep_shard as ss

import tradingagents.auto_trader as at
from tradingagents import backtest_report as br, signals_pro as sp
from tradingagents.dataflows import exchange as fx

TFS = [t.strip() for t in (os.environ.get("TFS") or "15m,30m,1h,4h,1d").split(",")
       if t.strip() in br.BARRIERS]
NAMES = [n for n in sp.variants() if not sp.is_baseline(n)]
BARRIERS = {tf: [b for b in (cr.barrier_of(tf, sl, tp) for sl, tp in sp.BARRIERS_PCT[tf])
                 if b is not None] for tf in TFS}
ROWS_OUT = os.path.join("out", f"pro-rows-{ss.SHARD}.jsonl")
REPORT_OUT = os.path.join("out", f"pro-store-report-{ss.SHARD}.json")
USUAL_FILE = os.path.join(ROOT, "tradingagents", "learned", "usual_costs.json")
COIN_RETRIES = 2
PAIR_RETRIES = 2                 # a failed coin + timeframe is redone BY ITSELF
RETRY_CUTOFF_S = 4.8 * 3600      # no retry starts after this (runners die at 6 h)
T0 = time.time()


def usual_costs() -> dict:
    """coin -> the round trip (fraction) its Backtest v2 rows were charged:
    the seed the learned runs use, so a book read while a stock token's market
    is shut is a spike and never the price (backtest_report.charged_slippage)."""
    try:
        with open(USUAL_FILE, encoding="utf-8") as fh:
            return {str(k).upper(): float(v)
                    for k, v in (json.load(fh).get("rt") or {}).items()}
    except (OSError, ValueError):
        return {}


def charged(fee: float, fresh: float, usual_rt: float | None) -> float:
    """The usual one-side cost a trade with no minute reading pays: the one
    rule over this coin's readings (learn_shard.charged's rule)."""
    readings = [fresh]
    if usual_rt is not None:
        readings.insert(0, max(0.0, usual_rt / 2.0 - fee))
    return br.charged_slippage(readings)


def columns(df):
    o = [float(x) for x in df["Open"]]
    h = [float(x) for x in df["High"]]
    lo = [float(x) for x in df["Low"]]
    c = [float(x) for x in df["Close"]]
    v = [float(x) for x in df["Volume"]] if "Volume" in df.columns else [0.0] * len(c)
    ts = [int(x) for x in df["Date"].to_numpy().astype("datetime64[ms]").astype("int64")]
    return o, h, lo, c, v, ts


def groups_for(dfw, warm: int) -> dict:
    """{a representative setting: every setting with its signals} over the
    measured window; settings that never trade there are left out."""
    o, h, lo, c, v, ts = columns(dfw)
    by: dict = {}
    for name in NAMES:
        d = sp.dirs_for(sp.spec_for(name), o, h, lo, c, v, ts)
        if any(d[warm:]):
            by.setdefault(bytes(np.asarray(d[warm:], dtype=np.int8)), []).append(name)
    return {names[0]: names for names in by.values()}


def store_pair(sym: str, tf: str, pre: dict, done: int, total: int) -> tuple[list, dict]:
    """Every setting on one coin + timeframe: (row lines, report fields). The
    lines are returned only once the whole pair measured."""
    iv, bs, cap = br.TFS[tf]
    df = at._closed_bars(fx.klines(sym, iv, cap), bs)
    dfw, warm = ss.window(df)
    if len(dfw) - warm < br.min_bars(tf):
        return [], {"why": f"only {len(dfw) - warm} measurable bars"}
    reps = groups_for(dfw, warm)
    if not reps:
        return [], {"settings": len(NAMES), "distinct": 0, "rows": 0, "why": "no setting traded"}
    buf = io.StringIO()
    saved = (ss.window, br.pairs_for)
    # the window the groups were read on IS the window measured (window()
    # reads the clock), and the research's own stop/targets
    ss.window = lambda _df: (dfw, warm)
    br.pairs_for = lambda _tf, _b=tuple(BARRIERS[tf]): list(_b)
    try:
        ss.run_pair(sym, tf, buf, i=done, n=total, signals=list(reps),
                    learned={**pre, "df": df})
    finally:
        ss.window, br.pairs_for = saved
    lines = []
    for line in buf.getvalue().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("pair_done") or row.get("signal") not in reps:
            continue
        for name in reps[row["signal"]]:
            lines.append(json.dumps({**row, "signal": name}, separators=(",", ":")))
    return lines, {"settings": len(NAMES), "distinct": len(reps), "rows": len(lines),
                   "days": int((dfw["Date"].iloc[-1] - dfw["Date"].iloc[warm]).days),
                   "last": int(dfw["Date"].iloc[-1].timestamp())}


def late() -> bool:
    return time.time() - T0 > RETRY_CUTOFF_S


def store_coin(sym: str, out, report: list, usual: dict, done: int, total: int) -> int:
    """One coin's five frames; a frame that raises is redone BY ITSELF after
    the others (CLAUDE.md: a failed coin is redone alone), and named."""
    coin = sym.replace("_USDT", "")
    fee = at.taker_fee(sym, fx=fx)
    liq = fx.liquidation_move_pct(sym, at.LEVERAGE)
    fund = fx.funding_history(sym, since_ms=ss.funding_since_ms())
    book = fx.book_cost(sym, ss.BASE_MARGIN * at.LEVERAGE)
    fresh = float(book.get("slippage") or 0.0) or 0.0003
    pre = {"fee": fee, "liq": liq, "fund": fund, "slip": charged(fee, fresh, usual.get(coin)),
           "fine": ss.fine_bars(sym)}
    rows = 0
    pending = list(TFS)
    for attempt in range(PAIR_RETRIES + 1):
        again = []
        for tf in pending:
            t1 = time.time()
            entry = {"coin": coin, "tf": tf}
            try:
                lines, info = store_pair(sym, tf, pre, done, total)
                entry.update(info)
                if lines:
                    out.write("\n".join(lines) + "\n")
                    out.flush()
                    rows += len(lines)
            except Exception as exc:                           # noqa: BLE001
                entry["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
                ss.log(f"{coin} {tf}: FAILED (try {attempt + 1}) {entry['error']}")
                ss.log(traceback.format_exc()[-800:])
                if attempt < PAIR_RETRIES and not late():
                    again.append(tf)
                    continue
            entry["seconds"] = round(time.time() - t1, 1)
            if attempt:
                entry["tries"] = attempt + 1
            report.append(entry)
            ss.log(f"{coin} {tf}: {entry.get('distinct', 0)} distinct of {len(NAMES)}, "
                   f"{entry.get('rows', 0)} rows ({entry.get('why') or entry.get('error') or 'ok'}) "
                   f"in {entry['seconds']}s")
        if not again:
            break
        time.sleep(5 * (attempt + 1))
        pending = again
    return rows


def save_report(report: list) -> None:
    os.makedirs("out", exist_ok=True)
    tmp = REPORT_OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"report": report, "names": len(NAMES), "tfs": TFS, "days": ss.DAYS},
                  fh, separators=(",", ":"), default=str)
    os.replace(tmp, REPORT_OUT)


def main() -> int:
    os.makedirs("out", exist_ok=True)
    coins = ss.eligible()
    usual = usual_costs()
    ss.log(f"pro trader store run (Oct 21): {len(coins)} coin(s), timeframes {TFS}, "
           f"{len(NAMES)} settings, stop/targets {[len(BARRIERS[t]) for t in TFS]}, "
           f"{ss.DAYS} days")
    ss.report.board = len(coins)
    report: list = []
    failed: dict = {}
    total = done = 0
    with open(ROWS_OUT, "w", encoding="utf-8") as out:
        # ONE CLAIM AT A TIME, as the last coin finishes
        stream = ss.coin_stream(coins, T0)
        queue: list = []
        while True:
            sym = next(stream, None)
            if sym is None:
                if not queue or late():
                    for q in queue:
                        report.append({"coin": q.replace("_USDT", ""), "tf": "*",
                                       "error": "not redone: out of time"})
                    break
                sym = queue.pop(0)
            try:
                total += store_coin(sym, out, report, usual, done, len(coins))
                done += 1
            except Exception as exc:                           # noqa: BLE001
                n = failed.get(sym, 0) + 1
                failed[sym] = n
                ss.log(f"{sym}: FAILED ({type(exc).__name__}: {exc}) try {n}")
                if n <= COIN_RETRIES:
                    queue.append(sym)         # by itself, after the others
                else:
                    report.append({"coin": sym.replace("_USDT", ""), "tf": "*",
                                   "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
            save_report(report)
            ss.report("testing", done, len(coins), rows=total,
                      note=f"{sym.replace('_USDT', '')} done")
    save_report(report)
    ss.log(f"done: {done} coin(s), {total} row(s) in {(time.time() - T0) / 60:.0f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
