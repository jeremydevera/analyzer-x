"""The FORWARD-TESTED v3 strategies, followed on every new candle from the day they were chosen.

The operator, Nov 05, 2026, to running the 119 forward-tested strategies in practice: *"go"*.

The practice runner trades Backtest v2 rows only - it has no v3 waiting order, trailing stop or
Monday rank - so this follows them the one way that adds no second set of rules: every hour it
walks each strategy with the SAME v3 engine the research judged it on (`v3_page.run_family`: the
family's rule, its own exit, its filter, the minute's own costs, $5 risk) over candles that end
NOW, and keeps only the trades that opened after `since` - days nobody had seen when the list was
made. Nothing here places an order, practice or real.

* **The list** (`research/v3/forward.json`, committed): every v3 row that was PROFITABLE on
  2025's unseen days and whose setting 2026's older days chose again - 148 rows, 119 different
  trade lists (some filters changed nothing), 67 coins, all 4h - with the day it was made.
* **The plan**: `research/v3/plan-all.json` (every coin in every group) with BTC's mood worked
  out again from today's daily candles (`v3_universe.mood_of`), so `btc_mood` judges today and
  never passes everything as "unknown" after the plan's end. Membership after the plan's end is
  its last month's, which holds every coin.
* **One tick at a time** (`forward.lock`, an exclusive file lock, never a pid); a coin that fails
  is tried again alone after the others and, if it still fails, NAMED in the state with its error.
* **A trade still open** at the newest candle is shown as open (`why` END), never as a result.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

ROSTER = Path(__file__).resolve().parent.parent / "research" / "v3" / "forward.json"
PLAN_FILE = Path(__file__).resolve().parent.parent / "research" / "v3" / "plan-all.json"
RISK_USD = 5.0          # what the research measured them at (v3_rules.RESEARCH_RISK_USD)
EVERY_S = 3600          # one pass an hour
AFTER_CLOSE_S = 600     # ...10 minutes past the hour, once the candle and its minutes are in
MIN_LOOK_DAYS = 30      # the window walked always holds 30 days before `since` (trend's state)
RETRY_S = 600           # a pass that raised is tried again 10 minutes later, not every tick
_LAST_TRY = 0.0


def home() -> Path:
    from tradingagents import stores

    p = Path(stores.V3.home) / "forward"
    p.mkdir(parents=True, exist_ok=True)
    return p


def state_path() -> Path:
    return home() / "state.json"


# ------------------------------------------------------------------ the list
def picks(a_rows: list, b_rows: list) -> list[dict]:
    """The forward-tested rows: 2026's row (a) of a coin x family x timeframe x filter whose
    2025 row (b) was profitable on its unseen days with the SAME setting. One rule, the page's
    (`acs_page.payload`, the `fwd` flag)."""
    b = {r["_key"]: r for r in b_rows}
    out = []
    for r in a_rows:
        k = r["_key"]
        old = b.get(k)
        if old and old["_prof"] and old["_set"] == r["_set"]:
            out.append({"id": r["id"], "coin": k[0], "family": k[1], "tf": k[2],
                        "filter": k[3], "setting": r["_set"]})
    return out


def build_roster(now_s: float | None = None) -> dict:
    from tradingagents import acs_page as ap

    a, _ = ap.v3_rows("all-coins")
    b, _ = ap.v3_rows("all-2025")
    rows = picks(a, b)
    now_s = time.time() if now_s is None else now_s
    return {"made_s": int(now_s), "since_ms": int(now_s) * 1000, "risk_usd": RISK_USD,
            "rule": "profitable on 2025's unseen days AND the same setting chosen again by 2026's "
                    "older days (Backtest v3, per coin)",
            "strategies": rows}


def load_roster(path=None) -> dict:
    return json.loads(Path(path or ROSTER).read_text(encoding="utf-8"))


# ------------------------------------------------------------------- the plan
def plan_now(now_ms: int, *, fx=None, plan_file=None) -> dict:
    """The all-coins plan with BTC's mood worked out again up to `now_ms`."""
    from tradingagents import v3_universe as vu

    if fx is None:
        from tradingagents.dataflows import exchange as fx
    plan = vu.load(plan_file or PLAN_FILE)
    daily = vu.daily_of(fx.klines(vu.BTC, "Day1", 400), now_ms)
    plan["mood"] = vu.mood_of(daily, int(plan["start_ms"]) - 7 * vu.DAY_MS)
    return plan


def window_days(since_ms: int, now_ms: int) -> int:
    """The shortest window the tab offers that holds every day since `since` plus 30 before."""
    from tradingagents import v3_page as vp

    need = (now_ms - since_ms) / 86_400_000 + MIN_LOOK_DAYS
    return next((d for d in vp.DAYS if d >= need), vp.DAYS[-1])


def follow(x: dict, plan: dict, since_ms: int, now_ms: int, *, fx=None, run=None) -> dict:
    """One strategy walked to `now_ms`; only trades that OPENED at or after `since_ms`."""
    from tradingagents import v3_page as vp

    run = run or vp.run_family
    got = run({"sym": x["coin"], "tf": x["tf"], "signal": x["family"], "setting": x["setting"],
               "filter": x["filter"], "days": window_days(since_ms, now_ms),
               "risk_usd": RISK_USD}, fx=fx, plan=plan, now_ms=now_ms)
    from tradingagents import v3_research as vrs

    keep = [t for t in got["trades"] if int(t["entry_ms"]) >= since_ms]
    closed = [t for t in keep if t["why"] != "END"]
    pnls = [t["pnl"] for t in closed]
    worst, worst_n = vp.worst_run(pnls)
    target, stop = vrs.exit_words(x["family"], x["setting"], x["tf"])
    return {"id": x["id"], "coin": x["coin"], "family": x["family"], "tf": x["tf"],
            "filter": x["filter"], "setting": x["setting"], "target": target, "stop": stop,
            "profit": vp.cents(sum(pnls)), "wins": sum(1 for v in pnls if v > 0),
            "losses": sum(1 for v in pnls if v <= 0), "worst_run_usd": worst,
            "worst_run_trades": worst_n,
            "closed": [_slim(t) for t in closed], "open": [_slim(t) for t in keep if t["why"] == "END"],
            # a trade opened BEFORE the start and still open: the strategy is busy with it, so it
            # takes no new one until it ends (the backtest's own rule) - counted, never shown
            "carried": sum(1 for t in got["trades"]
                           if int(t["entry_ms"]) < since_ms and t["why"] == "END"),
            "last_candle_ms": int(got["provenance"]["end_ms"])}


def _slim(t: dict) -> dict:
    return {k: t[k] for k in ("side", "entry_ms", "entry", "exit_ms", "exit", "why", "pnl",
                              "leverage", "notional", "measured_exit")}


def summary(rows: list[dict]) -> dict:
    """The whole list's closed trades, added up in closing order."""
    from tradingagents import v3_page as vp

    trades = sorted((t for r in rows for t in r["closed"]), key=lambda t: t["exit_ms"])
    pnls = [t["pnl"] for t in trades]
    wins = sum(1 for v in pnls if v > 0)
    worst, worst_n = vp.worst_run(pnls)
    return {"trades": len(pnls), "wins": wins, "losses": len(pnls) - wins,
            "profit": vp.cents(sum(pnls)), "worst_run_usd": worst, "worst_run_trades": worst_n,
            "open": sum(len(r["open"]) for r in rows),
            "open_pnl": vp.cents(sum(t["pnl"] for r in rows for t in r["open"])),
            "carried": sum(r.get("carried", 0) for r in rows),
            "in_profit": sum(1 for r in rows if r["closed"] and sum(t["pnl"] for t in r["closed"]) > 0),
            "strategies": len(rows)}


# ------------------------------------------------------------------- one pass
def run_pass(now_ms: int | None = None, *, fx=None, roster=None, plan=None, run=None,
             log=print) -> dict:
    """Every strategy on the list walked to now; a failure is tried again alone after the
    others and named if it still fails. Returns the state written."""
    from tradingagents import forecast_v2 as f2
    from tradingagents.positions_view import fmt_when

    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    roster = load_roster() if roster is None else roster
    since = int(roster["since_ms"])
    plan = plan_now(now_ms, fx=fx) if plan is None else plan
    t0 = time.time()
    done, failed = {}, {}
    todo = list(roster["strategies"])
    for attempt in (1, 2):
        again = []
        for x in todo:
            try:
                done[x["id"]] = follow(x, plan, since, now_ms, fx=fx, run=run)
                failed.pop(x["id"], None)
            except Exception as exc:                               # noqa: BLE001
                failed[x["id"]] = f"{x['coin']} {x['tf']} {x['family']}: {type(exc).__name__}: {exc}"
                again.append(x)
        todo = again
        if not todo:
            break
    # a strategy that failed this pass keeps what the last pass saw, marked stale - a failed read
    # must never show its trades as gone
    before = {}
    if failed and state_path().exists():
        try:
            before = {r["id"]: r for r in json.loads(state_path().read_text(encoding="utf-8"))["rows"]}
        except (OSError, ValueError, KeyError):
            before = {}
    rows = []
    for x in roster["strategies"]:
        if x["id"] in done:
            rows.append(done[x["id"]])
        elif x["id"] in before:
            rows.append({**before[x["id"]], "stale": True})
    state = {"since_ms": since, "since": fmt_when(since / 1000), "ticked_s": int(now_ms / 1000),
             "ticked": fmt_when(now_ms / 1000), "took_s": round(time.time() - t0, 1),
             "risk_usd": RISK_USD, "listed": len(roster["strategies"]),
             "failed": [failed[k] for k in sorted(failed)], "summary": summary(rows), "rows": rows}
    f2.publish(state_path(), json.dumps(state))
    s = state["summary"]
    log(f"[v3 forward] {state['ticked']}: {s['trades']} closed trades since {state['since']}, "
        f"{s['wins']} won / {s['losses']} lost, {s['profit']:+.2f}; {s['open']} open; "
        f"{len(state['failed'])} failed; {state['took_s']} s")
    return state


def due(now_s: float, last_s: float | None) -> bool:
    """Once an hour, 10 minutes past it (a 4h candle closes on the hour)."""
    if last_s is None:
        return True
    slot = now_s - (now_s % EVERY_S) + AFTER_CLOSE_S
    if now_s < slot:
        slot -= EVERY_S
    return last_s < slot <= now_s


def tick(now_s: float | None = None) -> dict | None:
    """The supervisor's call: one pass when due, under the lock; None when not due or another
    pass holds the lock. Never raises."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    global _LAST_TRY
    now_s = time.time() if now_s is None else now_s
    if now_s - _LAST_TRY < RETRY_S:
        return None
    try:
        if not ROSTER.exists():
            return None
        last = None
        p = state_path()
        if p.exists():
            try:
                last = json.loads(p.read_text(encoding="utf-8")).get("ticked_s")
            except (OSError, ValueError):
                last = None
        if not due(now_s, last):
            return None
        _LAST_TRY = now_s          # a pass that raises waits RETRY_S, never every 30 s tick
        return locked_pass(now_s)
    except Exception as exc:                                       # noqa: BLE001
        print(f"[v3 forward] the pass failed: {type(exc).__name__}: {exc}", flush=True)
        return None


def locked_pass(now_s: float | None = None) -> dict | None:
    """One pass under `forward.lock` (the hourly tick and a hand-run pass both); None when
    another pass holds it."""
    from tradingagents import portable

    now_s = time.time() if now_s is None else now_s
    with open(home() / "forward.lock", "a+b") as fh:
        try:
            portable.lock_exclusive(fh, blocking=False)
        except OSError:
            return None
        try:
            return run_pass(int(now_s * 1000))
        finally:
            portable.unlock(fh)


def read_state() -> dict | None:
    p = state_path()
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tradingagents.v3_forward")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("roster", help="write research/v3/forward.json (the list and its start)")
    sub.add_parser("pass", help="walk every strategy to now and save the state")
    sub.add_parser("status", help="print the state")
    a = ap.parse_args(argv)
    if a.cmd == "roster":
        r = build_roster()
        ROSTER.write_text(json.dumps(r, indent=1), encoding="utf-8")
        print(f"{len(r['strategies'])} strategies on "
              f"{len({x['coin'] for x in r['strategies']})} coins, since {r['since_ms']}")
        return 0
    if a.cmd == "pass":
        st = locked_pass()
        if st is None:
            print("another pass is running (forward.lock)")
            return 1
        return 1 if st["failed"] else 0
    st = read_state()
    print(json.dumps(st["summary"] if st else None, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
