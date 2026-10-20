"""One GitHub machine of the CRYPTO-PREDICTOR switch search (Oct 19, 2026).

The operator: "use the strategy and switches and come up with best combination
for all coins", then "use the best combination and see what's setting will
win", and "One run first". So: the seven entry rules of
github.com/jeremydevera/Crypto-Predictor-Web (tradingagents/signals_cpw.py)
with every combination of their main switches — 528 settings — on every coin
and timeframe, each measured like a Backtest v2 row by `sweep_shard.run_pair`
(the same function as the nightly grid: Gate's own candles, exits settled on
the finest bars, every trade paying its own minute's order book, TP strictly
above SL, the stop inside 80% of liquidation).

Per pair, settings that produce the SAME signals in the measured window are
the same strategy there: each distinct signal set is measured once and its
numbers credited to every setting that produced it.

Outputs (artifacts), rewritten after every coin so a machine stopped at the
6-hour limit still hands over what it finished:
* out/rows-<N>.jsonl — v2 rows, the best CPW_KEEP of each strategy per pair
  (by profit, among rows the Backtest v2 list would show: TP > SL and a win
  paying two losses after fees), for Stored strategies' "Crypto-Predictor"
  group;
* out/cpw-<N>.npz — per setting x timeframe x stop/target: pairs that traded,
  pairs in profit, trades, wins, profit — once over every row and once over
  the rows the list would show — the evidence for "which setting wins";
* out/cpw-report-<N>.json — per pair: settings, distinct signal sets, rows,
  seconds, or the error.
"""
# ruff: noqa: E402  (the imports must follow the RES/MODE environment below)
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
os.environ["RES"] = "1m"
os.environ["MODE"] = "full"

import numpy as np  # noqa: E402
import sweep_shard as ss  # noqa: E402

import tradingagents.auto_trader as at  # noqa: E402
from tradingagents import backtest_report as br, signals_cpw as cp  # noqa: E402
from tradingagents.dataflows import exchange as fx  # noqa: E402

TFS = [t.strip() for t in (os.environ.get("TFS") or "15m,30m,1h,4h,1d").split(",")
       if t.strip() in br.BARRIERS]
KEEP = int(os.environ.get("CPW_KEEP") or 5)
NAMES = cp.variants()
NAME_IX = {n: k for k, n in enumerate(NAMES)}
BARRIERS = {tf: [(round(sl, 6), round(tp, 6)) for (sl, tp) in br.pairs_for(tf) if tp > sl]
            for tf in TFS}
SUMMARY_OUT = os.path.join("out", f"cpw-{ss.SHARD}.npz")
REPORT_OUT = os.path.join("out", f"cpw-report-{ss.SHARD}.json")
COIN_RETRIES = 2
# per cell: pairs traded, pairs in profit, trades, wins, profit — all rows,
# then the same five over the rows the Backtest v2 list would show
FIELDS = ("pairs", "pairs_up", "trades", "wins", "profit",
          "l_pairs", "l_pairs_up", "l_trades", "l_wins", "l_profit")


class Summary:
    """setting x timeframe x stop/target sums, one array per timeframe."""

    def __init__(self):
        self.a = {tf: np.zeros((len(NAMES), len(BARRIERS[tf]), len(FIELDS)))
                  for tf in TFS}
        self.bix = {tf: {b: k for k, b in enumerate(BARRIERS[tf])} for tf in TFS}

    def add(self, tf: str, name: str, row: dict, listed: bool) -> None:
        k = self.bix[tf].get((round(float(row["sl"]) / 100, 6), round(float(row["tp"]) / 100, 6)))
        if k is None:
            k = _nearest(self.bix[tf], float(row["sl"]) / 100, float(row["tp"]) / 100)
        cell = self.a[tf][NAME_IX[name], k]
        prof = float(row.get("profit") or 0)
        vals = (1, 1 if prof > 0 else 0, int(row.get("trades") or 0),
                int(row.get("wins") or 0), prof)
        cell[:5] += vals
        if listed:
            cell[5:] += vals

    def save(self) -> None:
        os.makedirs("out", exist_ok=True)
        tmp = SUMMARY_OUT + ".tmp.npz"
        np.savez_compressed(
            tmp, names=np.array(NAMES), fields=np.array(FIELDS),
            **{f"tf_{tf}": self.a[tf] for tf in TFS},
            **{f"barriers_{tf}": np.array(BARRIERS[tf]) for tf in TFS})
        os.replace(tmp, SUMMARY_OUT)


def _nearest(bix: dict, sl: float, tp: float) -> int:
    best = min(bix, key=lambda b: abs(b[0] - sl) + abs(b[1] - tp))
    return bix[best]


def _listed(row: dict) -> bool:
    """Would the Backtest v2 list show this row (TP > SL and a win paying
    two losses after fees) — the one rule the list files rows by."""
    try:
        return bool(br.index_keeps(row))
    except Exception:                                          # noqa: BLE001
        return False


def groups_for(df, warm: int) -> dict:
    """{signals in the window: [setting names]} for one frame — settings that
    never trade in the window are left out."""
    o = [float(x) for x in df["Open"]]
    h = [float(x) for x in df["High"]]
    lo = [float(x) for x in df["Low"]]
    c = [float(x) for x in df["Close"]]
    v = [float(x) for x in df["Volume"]] if "Volume" in df.columns else [0.0] * len(c)
    ts = list(df["Date"].to_numpy().astype("datetime64[ms]").astype("int64"))
    out: dict = {}
    for name in NAMES:
        d = cp.dirs_for(cp.spec_for(name), o, h, lo, c, v, ts)
        key = tuple(d[warm:])
        if any(key):
            out.setdefault(key, []).append(name)
    return out


def cpw_pair(sym: str, tf: str, out, summary: Summary, prefetched: dict,
             done: int, total: int, rows_so_far: int) -> dict:
    iv, bs, cap = br.TFS[tf]
    df = at._closed_bars(fx.klines(sym, iv, cap), bs)
    dfw, warm = ss.window(df)
    if len(dfw) - warm < br.min_bars(tf):
        return {"why": f"only {len(dfw) - warm} measurable bars"}
    groups = groups_for(dfw, warm)
    reps = {names[0]: names for names in groups.values()}
    if not reps:
        return {"settings": len(NAMES), "distinct": 0, "rows": 0, "why": "no setting traded"}
    buf = io.StringIO()
    orig = ss.window
    # the window run_pair cuts is the one the settings were grouped on,
    # never a second read of the clock a bar later
    ss.window = lambda _df: (dfw, warm)
    try:
        ss.run_pair(sym, tf, buf, i=done, n=total, rows_so_far=rows_so_far,
                    signals=list(reps), learned={**prefetched, "df": df})
    finally:
        ss.window = orig
    best: dict = {}                     # strategy -> [(profit, row)]
    n_rows = 0
    for line in buf.getvalue().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        rep = row.get("signal")
        if rep not in reps:
            continue
        listed = _listed(row)
        for name in reps[rep]:
            summary.add(tf, name, row, listed)
            if listed:
                st = name.split("_")[1]
                best.setdefault(st, []).append((float(row.get("profit") or 0), name, row))
        n_rows += 1
    kept = 0
    for items in best.values():
        items.sort(key=lambda x: -x[0])
        for _p, name, row in items[:KEEP]:
            out.write(json.dumps({**row, "signal": name}, separators=(",", ":")) + "\n")
            kept += 1
    out.flush()
    return {"settings": len(NAMES), "distinct": len(reps), "rows": n_rows, "kept": kept}


def cpw_coin(sym: str, out, summary: Summary, report: list, done: int, total: int,
             rows_so_far: int) -> int:
    coin = sym.replace("_USDT", "")
    fee = at.taker_fee(sym, fx=fx)
    liq = fx.liquidation_move_pct(sym, at.LEVERAGE)
    fund = fx.funding_history(sym)
    book = fx.book_cost(sym, ss.BASE_MARGIN * at.LEVERAGE)
    slip = br.charged_slippage([float(book.get("slippage") or 0.0) or 0.0003])
    _t, _h, _l, _n5 = br.fine_bars(sym, int(time.time()) - 31 * 86400, fx=fx)
    prefetched = {"fee": fee, "liq": liq, "fund": fund, "slip": slip, "fine": (_t, _h, _l)}
    kept = 0
    for tf in TFS:
        t0 = time.time()
        entry = {"coin": coin, "tf": tf}
        try:
            entry.update(cpw_pair(sym, tf, out, summary, prefetched, done, total,
                                  rows_so_far + kept))
            kept += int(entry.get("kept") or 0)
        except Exception as exc:                               # noqa: BLE001
            entry["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            ss.log(f"{coin} {tf}: FAILED {entry['error']}")
            ss.log(traceback.format_exc()[-800:])
        entry["seconds"] = round(time.time() - t0, 1)
        report.append(entry)
        ss.log(f"{coin} {tf}: {entry.get('distinct', 0)} distinct of "
               f"{len(NAMES)} settings, {entry.get('rows', 0)} rows, kept "
               f"{entry.get('kept', 0)} ({entry.get('why') or entry.get('error') or 'ok'}) "
               f"in {entry['seconds']}s")
    return kept


def _save_report(report: list) -> None:
    os.makedirs("out", exist_ok=True)
    tmp = REPORT_OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"report": report, "names": len(NAMES), "tfs": TFS}, fh,
                  separators=(",", ":"), default=str)
    os.replace(tmp, REPORT_OUT)


# ------------------------------------------------------- the check run (CONFIGS)
#
# After the search, the winners are measured AGAIN on every coin with each
# trade kept — the search keeps sums, and a results table needs every row's
# trades (the click), its worst losing run and its months (CLAUDE.md kit
# items 6 and B). Same function as the search (`sweep_shard.run_pair` through
# `backtest_strategy`), asked for one setting at one stop/target; the trade
# log the engine already writes is captured on its way out, never a second
# walk of the exits.

CONFIGS = os.environ.get("CONFIGS") or ""
TRADES_OUT = os.path.join("out", f"cpw-trades-{ss.SHARD}.jsonl")


def parse_configs(text: str) -> list:
    """'name:tf:sl:tp,...' (stop and target in percent) -> one dict each,
    with the grid's OWN floats for that stop/target (br.pairs_for) — a pair
    re-derived from its percent could differ in the last bit and decide a
    touch the search decided the other way. Anything the search did not
    measure is refused by name."""
    out = []
    for part in [p for p in str(text).split(",") if p.strip()]:
        name, tf, sl, tp = part.strip().split(":")
        if cp.spec_for(name) is None or cp.spec_for(name)["name"] != name:
            raise ValueError(f"{part}: not a Crypto-Predictor setting")
        if tf not in br.BARRIERS:
            raise ValueError(f"{part}: not a timeframe the search measures")
        hit = [b for b in br.pairs_for(tf)
               if round(b[0] * 100, 4) == round(float(sl), 4)
               and round(b[1] * 100, 4) == round(float(tp), 4)]
        if not hit:
            raise ValueError(f"{part}: not a stop/target the search measured on {tf}")
        out.append({"key": f"{name}:{tf}:{sl}:{tp}", "name": name, "tf": tf,
                    "sl": float(sl), "tp": float(tp), "barrier": hit[0]})
    return out


def compact_trades(log: list, df, bs: int) -> list:
    """The engine's trade log as [entry ms, exit ms, side, why, profit].
    The exit is the minute the minutes settled it, else the end of the bar it
    closed in; the entry is the entry bar's open (the exit less `held_s`,
    which the engine counts from that open, floored to the minute)."""
    ts = df["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
    out = []
    for e in log:
        xb = int(e["exit_bar"])
        xm = e.get("exit_minute_ms")
        anchor = int(xm) if xm is not None else int(ts[xb])
        exit_ms = int(xm) if xm is not None else int(ts[xb]) + bs * 1000
        entry_ms = (anchor - int(e.get("held_s") or 0) * 1000) // 60_000 * 60_000
        out.append([entry_ms, exit_ms, 1 if e["side"] == "LONG" else -1,
                    str(e["why"]), round(float(e["pnl $"]), 2)])
    return out


def verify_pair(sym: str, tf: str, df, prefetched: dict, cfgs: list,
                done: int = 0, total: int = 0) -> list:
    """Each config of this timeframe on one coin: its row and its trades.
    A config that made no trade here has no line (as the search wrote no
    row)."""
    _iv, bs, _cap = br.TFS[tf]
    dfw, warm = ss.window(df)
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
                      "row": rows[0], "trades": compact_trades(logs[-1], dfw, bs)})
    return lines


def prefetch(sym: str) -> dict:
    """One coin's fee, liquidation distance, funding, cost and finest bars —
    the search's own reads (cpw_coin)."""
    fee = at.taker_fee(sym, fx=fx)
    liq = fx.liquidation_move_pct(sym, at.LEVERAGE)
    fund = fx.funding_history(sym)
    book = fx.book_cost(sym, ss.BASE_MARGIN * at.LEVERAGE)
    slip = br.charged_slippage([float(book.get("slippage") or 0.0) or 0.0003])
    _t, _h, _l, _n5 = br.fine_bars(sym, int(time.time()) - 31 * 86400, fx=fx)
    return {"fee": fee, "liq": liq, "fund": fund, "slip": slip, "fine": (_t, _h, _l)}


def verify_main(cfgs: list) -> int:
    t0 = time.time()
    os.makedirs("out", exist_ok=True)
    coins = ss.eligible()
    by_tf: dict = {}
    for c in cfgs:
        by_tf.setdefault(c["tf"], []).append(c)
    ss.log(f"crypto-predictor check run: {len(coins)} coin(s), {len(cfgs)} setting(s) "
           f"on {sorted(by_tf)}")
    ss.report.board = len(coins)
    report: list = []
    failed: dict = {}
    done = n_lines = 0
    with open(TRADES_OUT, "w", encoding="utf-8") as out:
        stream = ss.coin_stream(coins, t0)
        queue: list = []
        while True:
            sym = next(stream, None)
            if sym is None:
                if not queue:
                    break
                sym = queue.pop(0)
            coin = sym.replace("_USDT", "")
            try:
                pre = prefetch(sym)
                for tf, group in by_tf.items():
                    t1 = time.time()
                    entry = {"coin": coin, "tf": tf}
                    try:
                        iv, bs, cap = br.TFS[tf]
                        df = at._closed_bars(fx.klines(sym, iv, cap), bs)
                        got = verify_pair(sym, tf, df, pre, group, done, len(coins))
                        for line in got:
                            out.write(json.dumps(line, separators=(",", ":")) + "\n")
                        n_lines += len(got)
                        entry["lines"] = len(got)
                    except Exception as exc:                   # noqa: BLE001
                        entry["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
                        ss.log(f"{coin} {tf}: FAILED {entry['error']}")
                    entry["seconds"] = round(time.time() - t1, 1)
                    report.append(entry)
                out.flush()
                done += 1
            except Exception as exc:                           # noqa: BLE001
                n = failed.get(sym, 0) + 1
                failed[sym] = n
                ss.log(f"{sym}: FAILED ({type(exc).__name__}: {exc}) try {n}")
                if n <= COIN_RETRIES:
                    queue.append(sym)
                else:
                    report.append({"coin": coin, "tf": "*",
                                   "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
            _save_report(report)
            ss.report("testing", done, len(coins), rows=n_lines, note=f"{coin} done")
    _save_report(report)
    ss.log(f"check run done: {done} coin(s), {n_lines} line(s) in "
           f"{(time.time() - t0) / 60:.0f} min")
    return 0


def main() -> int:
    if CONFIGS:
        return verify_main(parse_configs(CONFIGS))
    t0 = time.time()
    os.makedirs("out", exist_ok=True)
    coins = ss.eligible()
    ss.log(f"crypto-predictor switch search: {len(coins)} coin(s), timeframes {TFS}, "
           f"{len(NAMES)} settings of {len(cp.NAMES)} strategies")
    ss.report.board = len(coins)
    summary = Summary()
    report: list = []
    failed: dict = {}
    total = done = 0
    with open(ss.OUT, "w", encoding="utf-8") as out:
        stream = ss.coin_stream(coins, t0)
        queue: list = []
        while True:
            sym = next(stream, None)
            if sym is None:
                if not queue:
                    break
                sym = queue.pop(0)
            try:
                total += cpw_coin(sym, out, summary, report, done, len(coins), total)
                done += 1
            except Exception as exc:                           # noqa: BLE001
                n = failed.get(sym, 0) + 1
                failed[sym] = n
                ss.log(f"{sym}: FAILED ({type(exc).__name__}: {exc}) try {n}")
                if n <= COIN_RETRIES:
                    queue.append(sym)
                else:
                    report.append({"coin": sym.replace("_USDT", ""), "tf": "*",
                                   "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
            summary.save()
            _save_report(report)
            ss.report("testing", done, len(coins), rows=total,
                      note=f"{sym.replace('_USDT', '')} done")
    summary.save()
    _save_report(report)
    ss.log(f"done: {done} coin(s), {total} row(s) kept in "
           f"{(time.time() - t0) / 60:.0f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
