"""One GitHub machine of the Sep 27 ML run.

The operator, Sep 27, 2026: "use machine learning on what's best strategy i
want tp higher than sl". Per claimed coin: the costs once (the one cost rule,
seeded with the coin's usual Backtest v2 cost — learn_shard.charged), the
1-minute candles ONCE — fetched per coin and reused for every timeframe's
minute-exact exits — then for each timeframe the frame's own candles;
`ml_learner.learn_pair`; and the kept models measured through
`sweep_shard.run_pair` — the function that measures every Backtest v2 row.

ONE STORED ROW PER MODEL, at the model's own TP/SL (`own_rows`): run_pair
walks every TP > SL pair of the grid, and a model learned at TP 2% / SL 1%
measured at TP 3% / SL 1.5% is a strategy nobody learned.

DAYS IS PINNED TO 30: the stored row covers exactly the learner's UNSEEN
window. A wider window would mix VALIDATE — the month the model was chosen
on — into the number shown as its test.

Outputs (artifacts): out/rows-<N>.jsonl, out/formulas-<N>.json (the kept
models), out/report-<N>.json — rewritten after every TIMEFRAME, so a machine
stopped mid-coin hands over what it finished.
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
# THE LEARNER'S UNSEEN IS 30 DAYS (ml_learner.UNSEEN_DAYS): the stored row
# must measure exactly those, and a wider window would mix VALIDATE — the
# month the model was chosen on — into it. Read by sweep_shard at import.
os.environ["DAYS"] = "30"

import numpy as np
import sweep_shard as ss
from learn_shard import charged, usual_costs

import tradingagents.auto_trader as at
from tradingagents import backtest_report as br
from tradingagents import formula_learner as fl
from tradingagents import ml_learner as ml
from tradingagents import signals_ml as sml
from tradingagents.dataflows import exchange as fx

TFS = [t.strip() for t in (os.environ.get("TFS") or "15m,30m,1h,4h,1d").split(",")
       if t.strip() in br.BARRIERS]
FORMULAS_OUT = os.path.join("out", f"formulas-{ss.SHARD}.json")
REPORT_OUT = os.path.join("out", f"report-{ss.SHARD}.json")
COIN_RETRIES = 2


def own_rows(lines, kept) -> list:
    """Only the rows at a kept model's OWN (signal, TP, SL): one stored row
    per model. Stored rows carry tp/sl in PERCENT, rounded to 3 places by
    the writer, so the model's fractions are compared the same way."""
    want = [(str(f["name"]), round(float(f["tp"]) * 100, 3),
             round(float(f["sl"]) * 100, 3)) for f in kept]
    out = []
    for line in lines:
        if not line.strip():
            continue
        try:
            r = json.loads(line)
            sig, tp, sl = str(r.get("signal")), float(r["tp"]), float(r["sl"])
        except (ValueError, KeyError, TypeError):
            continue
        if any(sig == n and abs(tp - t) < 1e-9 and abs(sl - s) < 1e-9
               for n, t, s in want):
            out.append(line if line.endswith("\n") else line + "\n")
    return out


def ml_coin(sym: str, out, formulas: dict, report: list, usual: dict,
            done: int = 0, total: int = 0, rows_so_far: int = 0) -> int:
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
            frame = fl.Frame(coin=coin, tf=tf, df=df, fee=fee, slip=slip, liq=liq,
                             funding=fund, fine=fine, base=ss.BASE_MARGIN)
            rep = ml.learn_pair(frame, now_ms=int(time.time() * 1000), log=ss.log)
            kept = rep.pop("formulas", [])
            entry.update(rep, kept=[f["name"] for f in kept])
            if kept:
                sml.register({f["name"]: f for f in kept})
                buf = io.StringIO()
                ss.run_pair(sym, tf, buf, i=done, n=total,
                            rows_so_far=rows_so_far + rows,
                            signals=[f["name"] for f in kept],
                            learned={"fee": fee, "liq": liq, "fund": fund,
                                     "slip": slip, "df": df, "fine": fine})
                mine = own_rows(buf.getvalue().splitlines(), kept)
                out.writelines(mine)
                out.flush()
                got = len(mine)
                entry["rows"] = got
                rows += got
                formulas.update({f["name"]: f for f in kept})
        except Exception as exc:                               # noqa: BLE001
            entry["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            ss.log(f"{coin} {tf}: FAILED {entry['error']}")
            ss.log(traceback.format_exc()[-800:])
        entry["seconds"] = round(time.time() - t0, 1)
        report.append(entry)
        # AFTER EVERY TIMEFRAME, not every coin: a machine stopped mid-coin
        # must hand over the timeframes it finished, with their report lines,
        # or the collect finds rows no report accounts for
        _save(formulas, report)
        ss.log(f"{coin} {tf}: kept {len(entry.get('kept') or [])} "
               f"({entry.get('why') or entry.get('error') or 'ok'}) in {entry['seconds']}s")
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
    ss.log(f"Sep 27 ML run: {len(coins)} coin(s), timeframes {TFS}, "
           f"usual costs for {len(usual)} coin(s)")
    ss.report.board = len(coins)
    formulas: dict = {}
    report: list = []
    failed: dict = {}
    total = done = 0
    with open(ss.OUT, "w", encoding="utf-8") as out:
        # ONE CLAIM AT A TIME, as the last coin finishes (learn_shard's rule)
        stream = ss.coin_stream(coins, t0)
        queue: list = []
        while True:
            sym = next(stream, None)
            if sym is None:
                if not queue:
                    break
                sym = queue.pop(0)
            try:
                total += ml_coin(sym, out, formulas, report, usual,
                                 done=done, total=len(coins), rows_so_far=total)
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
            _save(formulas, report)
            ss.report("testing", done, len(coins), rows=total,
                      note=f"{sym.replace('_USDT', '')}: {len(formulas)} models so far")
    _save(formulas, report)
    ss.log(f"done: {done} coin(s), {len(formulas)} model(s), {total} row(s) "
           f"in {(time.time() - t0) / 60:.0f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
