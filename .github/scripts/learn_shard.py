"""One GitHub machine of the LEARNED-formula run ("Sep 25 Strat").

The operator, Sep 25, 2026: *"do the prompt and start the development"* —
the prompt being: a new set of formulas for every coin and each timeframe,
found by a research loop on each coin's own candle history, TP strictly
greater than SL, measured on GitHub like Backtest v2, filterable as the group
"Sep 25 Strat".

Per claimed coin: fetch the costs once (fee, liquidation, funding, the book
— charged by the one rule, `backtest_report.charged_slippage`, seeded with
the cost this coin's Backtest v2 rows were charged so a closed-market book
cannot price the whole search), the 1-minute candles once, then for each
timeframe the frame's own candles; run `formula_learner.learn_pair`; and
measure what it kept through `sweep_shard.run_pair` — the SAME function that
measures every Backtest v2 row — so a learned row and a grid row are one
measurement. Every coin+timeframe gets a line in the report, kept or not,
with the reason.

Outputs (artifacts): out/rows-<N>.jsonl (v2 rows, res="1m"),
out/formulas-<N>.json, out/report-<N>.json — rewritten after every coin, so a
machine killed at the 6-hour limit still hands over what it finished.
"""
# ruff: noqa: E402  (the imports must follow the RES/MODE environment below)
from __future__ import annotations

import json
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
# Backtest v2: every exit settled minute by minute; a full measurement, never
# a continuation — set BEFORE sweep_shard reads them at import
os.environ["RES"] = "1m"
os.environ["MODE"] = "full"

import numpy as np  # noqa: E402
import sweep_shard as ss  # noqa: E402

import tradingagents.auto_trader as at  # noqa: E402
from tradingagents import (
    backtest_report as br,  # noqa: E402
    formula_learner as fl,  # noqa: E402
    signals_learned as sl_,  # noqa: E402
)
from tradingagents.dataflows import mexc_futures as fx  # noqa: E402

TFS = [t.strip() for t in (os.environ.get("TFS") or "15m,30m,1h,4h,1d").split(",")
       if t.strip() in br.BARRIERS]
USUAL_FILE = os.path.join(ROOT, "tradingagents", "learned", "usual_costs.json")
FORMULAS_OUT = os.path.join("out", f"formulas-{ss.SHARD}.json")
REPORT_OUT = os.path.join("out", f"report-{ss.SHARD}.json")
COIN_RETRIES = 2


def usual_costs() -> dict:
    """coin -> the round trip (fraction) its Backtest v2 rows were charged."""
    try:
        with open(USUAL_FILE, encoding="utf-8") as fh:
            return {str(k).upper(): float(v)
                    for k, v in (json.load(fh).get("rt") or {}).items()}
    except (OSError, ValueError):
        return {}


def charged(fee: float, fresh: float, usual_rt: float | None) -> tuple[float, list]:
    """The slippage to charge: the one rule over this coin's readings — its
    rows' usual cost and the book read just now (a spike is never charged)."""
    readings = [fresh]
    if usual_rt is not None:
        readings.insert(0, max(0.0, usual_rt / 2.0 - fee))
    return br.charged_slippage(readings), readings


def learn_coin(sym: str, out, formulas: dict, report: list, usual: dict) -> int:
    coin = sym.replace("_USDT", "")
    fee = at.taker_fee(sym, fx=fx)
    liq = fx.liquidation_move_pct(sym, at.LEVERAGE)
    fund = fx.funding_history(sym)
    book = fx.book_cost(sym, ss.BASE_MARGIN * at.LEVERAGE)
    fresh = float(book.get("slippage") or 0.0) or 0.0003
    slip, readings = charged(fee, fresh, usual.get(coin))
    iv1, bs1, cap1 = br.TFS["1m"]
    m1 = at._closed_bars(fx.klines(sym, iv1, cap1), bs1)
    fine = (m1["Date"].to_numpy().astype("datetime64[ms]").astype("int64"),
            np.asarray(m1["High"], dtype="float64"),
            np.asarray(m1["Low"], dtype="float64"))
    rows = 0
    for tf in TFS:
        iv, bs, cap = br.TFS[tf]
        t0 = time.time()
        entry = {"coin": coin, "tf": tf, "fee": fee, "slippage": slip,
                 "readings": readings, "liq": liq}
        try:
            df = at._closed_bars(fx.klines(sym, iv, cap), bs)
            frame = fl.Frame(coin=coin, tf=tf, df=df, fee=fee, slip=slip,
                             liq=liq, funding=fund, fine=fine,
                             base=ss.BASE_MARGIN)
            # the unseen cut from THIS moment, which is also the moment the
            # rows are measured (sweep_shard.window reads the clock): a cut
            # fixed at the start of a five-hour run would drift from them
            rep = fl.learn_pair(frame, now_ms=int(time.time() * 1000), log=ss.log)
            kept = rep.pop("formulas", [])
            entry.update({k: v for k, v in rep.items() if k != "round_log"},
                         rounds_detail=rep.get("round_log"),
                         kept=[f["name"] for f in kept])
            if kept:
                sl_.register({f["name"]: f for f in kept})
                got = ss.run_pair(sym, tf, out, signals=[f["name"] for f in kept],
                                  learned={"fee": fee, "liq": liq, "fund": fund,
                                           "slip": slip, "df": df, "fine": fine})
                entry["rows"] = got
                rows += got
                formulas.update({f["name"]: f for f in kept})
        except Exception as exc:                               # noqa: BLE001
            entry["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            ss.log(f"{coin} {tf}: FAILED {entry['error']}")
            ss.log(traceback.format_exc()[-800:])
        entry["seconds"] = round(time.time() - t0, 1)
        report.append(entry)
        ss.log(f"{coin} {tf}: kept {len(entry.get('kept') or [])} "
               f"({entry.get('why') or entry.get('error') or 'ok'}) "
               f"in {entry['seconds']}s")
    return rows


def _save(formulas: dict, report: list) -> None:
    os.makedirs("out", exist_ok=True)
    for path, obj in ((FORMULAS_OUT, {"formulas": formulas}),
                      (REPORT_OUT, {"report": report})):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, separators=(",", ":"), default=str)
        os.replace(tmp, path)


def main() -> int:
    t0 = time.time()
    os.makedirs("out", exist_ok=True)
    coins = ss.eligible()
    usual = usual_costs()
    ss.log(f"learned-formula run: {len(coins)} coin(s), timeframes {TFS}, "
           f"usual costs for {len(usual)} coin(s)")
    ss.report.board = len(coins)
    formulas: dict = {}
    report: list = []
    failed: dict = {}
    total = done = 0
    with open(ss.OUT, "w", encoding="utf-8") as out:
        # ONE CLAIM AT A TIME, as the last coin finishes — never
        # `list(coin_stream(...))`, which would claim this machine's whole
        # walk of the board up front and leave the other nineteen idle
        stream = ss.coin_stream(coins, t0)
        queue: list = []              # failed coins, redone after the others
        while True:
            sym = next(stream, None)
            if sym is None:
                if not queue:
                    break
                sym = queue.pop(0)
            try:
                total += learn_coin(sym, out, formulas, report, usual)
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
            _save(formulas, report)
            ss.report("testing", done, len(coins), rows=total,
                      note=f"{sym.replace('_USDT', '')}: {len(formulas)} formulas so far")
    _save(formulas, report)
    ss.log(f"done: {done} coin(s), {len(formulas)} formula(s), {total} row(s) "
           f"in {(time.time() - t0) / 60:.0f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
