"""One GitHub machine of the CONFLUENCE STORE run — the group "Oct 22".

The operator, Oct 22, 2026, after the confluence research (Prompt 1): *"Okay
deploy them in production, i want t to see then in stored strategies"*.

Every pick of the research (research/cq/store_plan.json: per coin and
timeframe, the pick of each payout — a name, a stop, a target; never a random
entry, which is no strategy) measured exactly as a Backtest v2 row is: the
nightly grid's own function (`sweep_shard.run_pair`, rows only — no
pair-done marker, no saved position, no live post), Backtest v2's 30-day
window with 300 bars of lead-in, every exit settled by the minute, every
trade paying its own minute's order book and asked the runner's cost check
at its own minute, funding, the 1-4 and 15-day counts the rooms judge on.

EACH PICK AT ITS OWN STOP AND TARGET, never every name at every pick's stop
and target: one run_pair call per pair, `br.pairs_for` answering with the
stops and targets of the name being read (the research shard's own way,
cq_shard.measure).

A NAME IS MEASURED ONLY AS WHAT IT WAS FOUND AS: a name whose plain words in
this code differ from the words the research recorded is not measured, and
every pick of it is named.

Outputs (artifacts): out/cq-rows-<N>.jsonl (Backtest v2 rows, res="1m"),
out/cq-store-report-<N>.json (every coin + timeframe attempted: its picks, its
rows, and every pick with no row named with why) — the report rewritten after
every coin, and a pair's rows written only once the whole pair is measured.
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

import sweep_shard as ss
from pro_store_shard import charged, usual_costs

import tradingagents.auto_trader as at
from tradingagents import backtest_report as br, signals_cq as sq
from tradingagents.dataflows import exchange as fx

PLAN_FILE = os.environ.get("CQ_PLAN") or os.path.join(ROOT, "research", "cq", "store_plan.json")
TFS = [t.strip() for t in (os.environ.get("TFS") or "15m,30m,1h,4h,1d").split(",")
       if t.strip() in br.BARRIERS]
ROWS_OUT = os.path.join("out", f"cq-rows-{ss.SHARD}.jsonl")
REPORT_OUT = os.path.join("out", f"cq-store-report-{ss.SHARD}.json")
COIN_RETRIES = 2
PAIR_RETRIES = 2                 # a failed coin + timeframe is redone BY ITSELF
RETRY_CUTOFF_S = 4.8 * 3600      # no retry starts after this (runners die at 6 h)
T0 = time.time()


def load_plan(path: str | None = None) -> dict:
    with open(path or PLAN_FILE, encoding="utf-8") as fh:
        return json.load(fh)


def refused_names(plan: dict) -> dict:
    """{name: why} for every name whose plain words in THIS code differ from
    the words the research recorded: measured, it would be some other rule
    written under the name the research found."""
    out = {}
    for name, said in (plan.get("names") or {}).items():
        now = sq.words(name)
        if now != said:
            out[name] = (f"the name means something else in this code: the research found "
                         f"{said!r}, this code reads {now or 'nothing'!r}")
    return out


def why_missing(name: str, sl: float, liq, errors: list, refused: dict,
                result: dict | None) -> tuple[str, str]:
    """(why, kind) for a pick that has no row. `result` is the engine's own
    answer for the pick when the engine ran: a pick whose every signal the
    runner's checks refused says so and how many, never a bare "no trade"."""
    if name in refused:
        return refused[name], "renamed"
    err = next((e for e in errors if e.startswith(name + " signals: ")), None)
    if err:
        return f"its signals could not be read: {err[len(name) + 10:]}", "signal_error"
    err = next((e for e in errors if e.startswith(f"{name} {sl:g}% engine: ")), None)
    if err:
        return f"its measurement failed: {err.split(' engine: ', 1)[1]}", "engine_error"
    if result is not None:
        g, c, k = (int(result.get(x) or 0) for x in ("gate_blocked", "chase_skip", "closed_skip"))
        if g + c + k:
            parts = [f"{g:,} by the cost check" if g else "",
                     f"{c:,} because the price had already run away" if c else "",
                     f"{k:,} on a candle its closed market printed no trade" if k else ""]
            return (f"no trade in its last {ss.DAYS} days: all {g + c + k:,} of its signals "
                    f"refused ({', '.join(x for x in parts if x)})", "refused")
        return f"no signal in its last {ss.DAYS} days", "no_signal"
    if liq is not None and float(liq) <= 0:
        return ("Gate's maintenance margin leaves no room at 20x: the app cannot hold this "
                "coin at its leverage", "cannot_hold")
    if liq is not None and float(sl) >= 0.8 * abs(float(liq)):
        return (f"its {sl:g}% stop is past 80% of the {abs(float(liq)):.2f}% the price may "
                f"move before Gate closes it at 20x", "past_liquidation")
    return "not measured: the grid's rule skipped it", "skipped"


def store_pair(sym: str, tf: str, picks: list, pre: dict, done: int, total: int,
               refused: dict) -> tuple[list, dict]:
    """Every pick of one coin + timeframe: (row lines, report fields). The
    lines are returned only once the whole pair is measured."""
    iv, bs, cap = br.TFS[tf]
    df = at._closed_bars(fx.klines(sym, iv, cap), bs)
    dfw, warm = ss.window(df)
    info = {"picks": len(picks)}
    if len(dfw) - warm < br.min_bars(tf):
        return [], {**info, "rows": 0, "why": f"only {len(dfw) - warm} measurable bars"}
    want: dict = {}
    for name, sl, tp in picks:
        if name not in refused:
            want.setdefault(name, []).append((float(sl) / 100.0, float(tp) / 100.0))
    errors: list = []
    current: list = [None]
    results: dict = {}
    dirs_fn, engine = at._dirs_for_backtest, at.backtest_strategy

    def keep(*a, **kw):
        # the engine's own answer for every pick it measures, trades or none:
        # run_pair writes no row for a pick with no trade, and its refusals
        # are the only way to say why
        key = (str(a[0]).rsplit("_gh_", 1)[0], round(float(kw["sl"]) * 100, 3),
               round(float(kw["tp"]) * 100, 3))
        try:
            r = engine(*a, **kw)
        except Exception as exc:                               # noqa: BLE001
            errors.append(f"{key[0]} {key[1]:g}% engine: {type(exc).__name__}: {str(exc)[:120]}")
            raise
        results[key] = r
        return r

    def dirs(key, *a, **kw):
        current[0] = str(key).rsplit("_gh_", 1)[0]
        try:
            return dirs_fn(key, *a, **kw)
        except Exception as exc:                               # noqa: BLE001
            # run_pair skips a name whose signals raise; counted here, so a
            # broken rule is named, never a quiet "no trade"
            errors.append(f"{current[0]} signals: {type(exc).__name__}: {str(exc)[:120]}")
            raise

    buf = io.StringIO()
    if want:
        saved = (ss.window, br.pairs_for, at._dirs_for_backtest, at.backtest_strategy)
        # the window the plan was checked on IS the window measured (window()
        # reads the clock), and each name at its own stops and targets
        ss.window = lambda _df: (dfw, warm)
        br.pairs_for = lambda _tf: list(want.get(current[0], ()))
        at._dirs_for_backtest = dirs
        at.backtest_strategy = keep
        try:
            ss.run_pair(sym, tf, buf, i=done, n=total, signals=list(want),
                        learned={**pre, "df": df})
        finally:
            ss.window, br.pairs_for, at._dirs_for_backtest, at.backtest_strategy = saved
    keys = {(str(n), round(float(sl), 3), round(float(tp), 3)) for n, sl, tp in picks}
    lines, got = [], set()
    for line in buf.getvalue().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        k = (str(row.get("signal")), round(float(row.get("sl") or 0), 3),
             round(float(row.get("tp") or 0), 3))
        if row.get("pair_done") or k not in keys or k in got:
            continue
        got.add(k)
        lines.append(line)
    missing = []
    for name, sl, tp in picks:
        if (str(name), round(float(sl), 3), round(float(tp), 3)) in got:
            continue
        k = (str(name), round(float(sl), 3), round(float(tp), 3))
        why, kind = why_missing(str(name), float(sl), pre.get("liq"), errors, refused,
                                results.get(k))
        missing.append([name, sl, tp, why, kind])
    info.update(rows=len(lines),
                days=int((dfw["Date"].iloc[-1] - dfw["Date"].iloc[warm]).days),
                last=int(dfw["Date"].iloc[-1].timestamp()))
    if missing:
        info["missing"] = missing
    if errors:
        info["errors"] = errors[:20]
    return lines, info


def late() -> bool:
    return time.time() - T0 > RETRY_CUTOFF_S


def store_coin(sym: str, tf_picks: dict, out, report: list, usual: dict, refused: dict,
               done: int, total: int) -> int:
    """One coin's timeframes in the plan; a frame that raises is redone BY
    ITSELF after the others (CLAUDE.md: a failed coin is redone alone), and
    named."""
    coin = sym.replace("_USDT", "")
    fee = at.taker_fee(sym, fx=fx)
    liq = fx.liquidation_move_pct(sym, at.LEVERAGE)
    fund = fx.funding_history(sym, since_ms=ss.funding_since_ms())
    book = fx.book_cost(sym, ss.BASE_MARGIN * at.LEVERAGE)
    fresh = float(book.get("slippage") or 0.0) or 0.0003
    pre = {"fee": fee, "liq": liq, "fund": fund, "slip": charged(fee, fresh, usual.get(coin)),
           "fine": ss.fine_bars(sym)}
    rows = 0
    pending = [tf for tf in TFS if tf_picks.get(tf)]
    for attempt in range(PAIR_RETRIES + 1):
        again = []
        for tf in pending:
            t1 = time.time()
            entry = {"coin": coin, "tf": tf}
            try:
                lines, info = store_pair(sym, tf, tf_picks[tf], pre, done, total, refused)
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
            ss.log(f"{coin} {tf}: {entry.get('rows', 0)} row(s) of {len(tf_picks[tf])} pick(s) "
                   f"({entry.get('why') or entry.get('error') or 'ok'}) in {entry['seconds']}s")
        if not again:
            break
        time.sleep(5 * (attempt + 1))
        pending = again
    return rows


def save_report(report: list, plan: dict, refused: dict) -> None:
    os.makedirs("out", exist_ok=True)
    tmp = REPORT_OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"report": report, "plan_picks": plan.get("picks"), "refused_names": refused,
                   "tfs": TFS, "days": ss.DAYS}, fh, separators=(",", ":"), default=str)
    os.replace(tmp, REPORT_OUT)


def main() -> int:
    os.makedirs("out", exist_ok=True)
    plan = load_plan()
    refused = refused_names(plan)
    coins = ss.eligible()
    usual = usual_costs()
    ss.log(f"confluence store run (Oct 22): {len(coins)} coin(s), timeframes {TFS}, "
           f"{plan.get('picks')} pick(s) in the plan, {len(refused)} name(s) refused, "
           f"{ss.DAYS} days")
    for name, why in sorted(refused.items()):
        ss.log(f"refused {name}: {why}")
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
            coin = sym.replace("_USDT", "")
            tf_picks = (plan.get("coins") or {}).get(coin)
            if not tf_picks:
                report.append({"coin": coin, "tf": "*", "error": "not in the plan"})
                save_report(report, plan, refused)
                continue
            try:
                total += store_coin(sym, tf_picks, out, report, usual, refused, done,
                                    len(coins))
                done += 1
            except Exception as exc:                           # noqa: BLE001
                n = failed.get(sym, 0) + 1
                failed[sym] = n
                ss.log(f"{sym}: FAILED ({type(exc).__name__}: {exc}) try {n}")
                if n <= COIN_RETRIES:
                    queue.append(sym)         # by itself, after the others
                else:
                    report.append({"coin": coin, "tf": "*",
                                   "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
            save_report(report, plan, refused)
            ss.report("testing", done, len(coins), rows=total, note=f"{coin} done")
    save_report(report, plan, refused)
    ss.log(f"done: {done} coin(s), {total} row(s) in {(time.time() - T0) / 60:.0f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
