"""ALL COINS x ALL TIMEFRAMES - the trade lists (Nov 05, 2026; tradingagents/acs.py).

Each coin's picks from research/acs/plan.json ({coin: {tf: ["signal:th:sl:tp", ...]}}), measured
AGAIN like a Backtest v2 row - `sweep_shard.run_pair` through `backtest_strategy(fine=)`, Backtest
v2's 30 days + 300 lead-in, minute exits, the runner's own cost check - asked for one signal at one
threshold and one stop/target, with the trade log the engine writes kept on its way out
(`check_run`: never a second walk of the exits). One line per pick: its row and its trades.

A machine measures nothing (exit 2) when its checkout's plan is not the one the dispatch named.
"""
# ruff: noqa: E402  (the imports must follow the RES/MODE environment below)
from __future__ import annotations

import io
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.environ["RES"] = "1m"
os.environ["MODE"] = "full"

import check_run as cr  # noqa: E402
import sweep_shard as ss  # noqa: E402

import tradingagents.auto_trader as at  # noqa: E402
from tradingagents import backtest_report as br  # noqa: E402
from tradingagents.dataflows import exchange as fx  # noqa: E402

PLAN = os.path.join(ROOT, "research", "acs", "plan.json")
PLAN_ID = os.environ.get("PLAN_ID") or ""
TRADES_OUT = os.path.join("out", f"acs-trades-{ss.SHARD}.jsonl")
REPORT_OUT = os.path.join("out", f"acs-report-{ss.SHARD}.json")
COIN_RETRIES = 2


def parse(text: str, tf: str) -> dict:
    """'signal:th:sl:tp' -> the grid's own threshold and barrier floats (a value re-derived from
    its percent could differ in the last bit and decide a touch the other way)."""
    sig, th, sl, tp = text.split(":")
    barrier = cr.barrier_of(tf, sl, tp)
    if barrier is None:
        raise ValueError(f"{text}: not a stop/target the grid measures on {tf}")
    if sig in br.THRESH_SIGNALS:
        hit = [t for t in br.THRESHOLDS[tf] if round(t * 100, 3) == round(float(th), 3)]
        if not hit:
            raise ValueError(f"{text}: not a threshold the grid measures on {tf}")
        ths = [hit[0]]
    else:
        ths = [None]
    return {"key": text, "name": sig, "th": float(th), "ths": ths, "barrier": barrier}


def measure(sym: str, tf: str, df, pre: dict, cfg: dict) -> dict | None:
    """One pick: run_pair for its one signal, threshold and barrier, the engine's log kept."""
    _iv, bs, _cap = br.TFS[tf]
    dfw, warm = ss.window(df)
    logs: list = []
    engine = at.backtest_strategy

    def keep(*a, **kw):
        kw["keep_log"] = True
        r = engine(*a, **kw)
        logs.append(r.get("log") or [])
        return r

    buf = io.StringIO()
    saved = (ss.window, br.pairs_for, at.backtest_strategy, br.THRESHOLDS)
    ss.window = lambda _df: (dfw, warm)
    br.pairs_for = lambda _tf, _b=cfg["barrier"]: [_b]
    br.THRESHOLDS = {**br.THRESHOLDS, tf: cfg["ths"]} if cfg["ths"] != [None] else br.THRESHOLDS
    at.backtest_strategy = keep
    try:
        ss.run_pair(sym, tf, buf, signals=[cfg["name"]], learned={**pre, "df": df})
    finally:
        ss.window, br.pairs_for, at.backtest_strategy, br.THRESHOLDS = saved
    rows = [json.loads(x) for x in buf.getvalue().splitlines() if x.strip()]
    rows = [r for r in rows if r.get("signal") == cfg["name"]
            and round(float(r.get("th") or 0.0), 3) == round(cfg["th"], 3)]
    if not rows or not logs:
        return None
    return {"cfg": cfg["key"], "coin": sym.replace("_USDT", ""), "tf": tf, "row": rows[0],
            "trades": cr.compact_trades(logs[-1], dfw, bs, pre.get("fee"))}


def prefetch(sym: str) -> dict:
    """One coin's fee, liquidation distance, funding, cost and finest bars (the searches' reads)."""
    fee = at.taker_fee(sym, fx=fx)
    liq = fx.liquidation_move_pct(sym, at.LEVERAGE)
    fund = fx.funding_history(sym)
    book = fx.book_cost(sym, ss.BASE_MARGIN * at.LEVERAGE)
    slip = br.charged_slippage([float(book.get("slippage") or 0.0) or 0.0003])
    _t, _h, _l, _n5 = br.fine_bars(sym, int(time.time()) - 31 * 86400, fx=fx)
    return {"fee": fee, "liq": liq, "fund": fund, "slip": slip, "fine": (_t, _h, _l)}


def _save_report(report: list) -> None:
    tmp = REPORT_OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(report, fh)
    os.replace(tmp, REPORT_OUT)


def main() -> int:
    os.makedirs("out", exist_ok=True)
    plan = json.load(open(PLAN, encoding="utf-8"))
    if not PLAN_ID or plan.get("id") != PLAN_ID:
        _save_report([{"coin": "*", "tf": "*", "error": f"this checkout's plan is {plan.get('id')}, "
                       f"the dispatch named {PLAN_ID or 'none'}: nothing measured"}])
        ss.log("plan mismatch - nothing measured")
        return 2
    configs = plan["configs"]
    t0 = time.time()
    coins = [s for s in ss.eligible() if s.replace("_USDT", "") in configs]
    ss.report.board = len(coins)
    report, failed, queue = [], {}, []
    done = n_lines = 0
    with open(TRADES_OUT, "w", encoding="utf-8") as out:
        stream = ss.coin_stream(coins, t0)
        while True:
            sym = next(stream, None)
            if sym is None:
                if not queue:
                    break
                sym = queue.pop(0)
            coin = sym.replace("_USDT", "")
            try:
                pre = prefetch(sym)
                for tf, texts in configs[coin].items():
                    entry = {"coin": coin, "tf": tf, "picks": len(texts), "lines": 0}
                    t1 = time.time()
                    try:
                        iv, bs, cap = br.TFS[tf]
                        df = at._closed_bars(fx.klines(sym, iv, cap), bs)
                        for text in texts:
                            got = measure(sym, tf, df, pre, parse(text, tf))
                            if got is None:
                                entry.setdefault("no_row", []).append(text)
                                continue
                            out.write(json.dumps(got, separators=(",", ":")) + "\n")
                            entry["lines"] += 1
                            n_lines += 1
                    except Exception as exc:                       # noqa: BLE001
                        entry["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
                        ss.log(f"{coin} {tf}: FAILED {entry['error']}")
                    entry["seconds"] = round(time.time() - t1, 1)
                    report.append(entry)
                out.flush()
                done += 1
            except Exception as exc:                               # noqa: BLE001
                failed[sym] = failed.get(sym, 0) + 1
                ss.log(f"{sym}: FAILED ({type(exc).__name__}: {exc}) try {failed[sym]}")
                if failed[sym] <= COIN_RETRIES:
                    queue.append(sym)
                else:
                    report.append({"coin": coin, "tf": "*",
                                   "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
            _save_report(report)
            ss.report("testing", done, len(coins), rows=n_lines, note=f"{coin} done")
    _save_report(report)
    ss.log(f"acs done: {done} coin(s), {n_lines} trade list(s) in {(time.time() - t0) / 60:.0f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
