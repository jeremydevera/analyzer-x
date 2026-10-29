"""One GitHub machine of BACKTEST V3 PART 2b (Oct 27, 2026): its share of the
universe measured the v3 way, one record per coin.

The operator: "go" (Oct 27, 2026) to Part 2b - the four idea families judged
on every coin of the universe on GitHub. Spec:
docs/superpowers/specs/2026-10-22-backtest-v3-design.md; decisions:
docs/superpowers/specs/2026-10-23-backtest-v3-part2-decisions.md; plan:
docs/superpowers/plans/2026-10-27-backtest-v3-part2b-github.md.

For every coin it claims off the board (`sweep_shard.coin_stream`: one coin at
a time, claimed on this account's sweep-progress branch), the machine calls
`v3_measure.measure_coin` - the same function `python -m
tradingagents.v3_research run` calls on the PC - against the plan file in its
own checkout, at the research's risk (`v3_rules.RESEARCH_RISK_USD`) and with
`v3_random.RUNS` random runs, and writes, the moment each coin is done:

* out/v3/<coin>.json.gz - the coin's record whole (`v3_research.save_coin`,
  the PC's own file name for a coin), stamped with the machine that measured
  it (`machine`: account, run, shard, commit);
* out/v3-report-<N>.json - one entry per coin: its seconds and size, or the
  error that ended it, or why it was never measured.

A coin that raises is redone BY ITSELF after the others, up to COIN_RETRIES,
its file deleted first (CLAUDE.md: a failed coin is redone alone); one that
never recovers is NAMED with its error. Nothing is chosen or judged here: the
PC collects every account's records (`python -m tradingagents.v3_cloud
collect`) and judges them pooled (`python -m tradingagents.v3_verdicts
publish`).

The machine refuses to measure anything - exit 2, the reason in its report -
when its checkout's plan is not the plan the dispatch named (PLAN_ID), or the
run does not trade on Gate (TA_VENUE).
"""
# ruff: noqa: E402  (sweep_shard is imported after RES is cleared, below)
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
# sweep_shard exits on a resolution it cannot download, and "v3" is a row RESOLUTION, never a
# candle frame (stores.V3): this machine uses only sweep_shard's claim board, its coin list and its
# log, so it is imported as the plain shard
os.environ.pop("RES", None)

import sweep_shard as ss

from tradingagents import (
    v3_measure as vm,
    v3_random as vrn,
    v3_research as vrs,
    v3_rules as vr,
    v3_universe as vu,
    venue as _venue,
)

PLAN_FILE = os.environ.get("PLAN_FILE") or str(vu.PLAN_FILE)     # tests name their own
PLAN_ID = (os.environ.get("PLAN_ID") or "").strip()
RUNS = int(os.environ.get("RUNS") or vrn.RUNS)                     # tests only
OUT_DIR = Path("out") / "v3"
REPORT_OUT = Path("out") / f"v3-report-{ss.SHARD}.json"
COIN_RETRIES = 2
RETRY_CUTOFF_S = 4.8 * 3600      # no retry starts after this (GitHub ends a job at 6 h)
T0 = time.time()
FX = None                        # the exchange door; tests hand in their own


def machine() -> dict:
    """Which machine measured a record: account, run, shard and commit."""
    return {"repo": os.environ.get("GITHUB_REPOSITORY", ""),
            "run": os.environ.get("GITHUB_RUN_ID", ""), "shard": int(ss.SHARD),
            "sha": os.environ.get("GITHUB_SHA", "")}


def save_report(report: list, **head) -> None:
    """The machine's report, written whole after every coin (a machine stopped
    at the time limit still hands over what it finished)."""
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = REPORT_OUT.with_name(REPORT_OUT.name + ".tmp")
    tmp.write_text(json.dumps({"shard": int(ss.SHARD), **head, "report": report}),
                   encoding="utf-8")
    tmp.replace(REPORT_OUT)


def refusal(plan: dict | None, load_error: str = "") -> str:
    """Why this machine may not measure, or "": the plan it holds is the one the
    dispatch named, the run trades on Gate, and the dispatch dealt this machine's
    account some coins (an empty list means "the whole market" to `sweep_shard`,
    and three accounts would each measure every coin)."""
    if _venue.current() != "gate":
        return f"TA_VENUE is {_venue.current()!r}: Backtest v3 measures on Gate only"
    if plan is None:
        return f"the plan file {PLAN_FILE} could not be read: {load_error}"
    if not PLAN_ID:
        return "the dispatch named no plan (PLAN_ID is empty)"
    if plan["id"] != PLAN_ID:
        return (f"this checkout's plan is {plan['id']}, the dispatch named {PLAN_ID}: the plan "
                "file changed between the dispatch and this machine's checkout")
    if not ss.COIN_LIST:
        return ("no coins were dealt to this machine's account (COIN_LIST is empty): every "
                "dispatch names its coins, and an empty list would measure the whole plan "
                "again beside the other accounts")
    return ""


def board_of(plan: dict, report: list) -> list:
    """The coins this machine's account was dealt that it can measure:
    `sweep_shard.eligible` (the dispatch's coin list, less the coins the
    exchange is not trading now), less the coins outside the plan's universe.
    Every coin left out is NAMED in the report."""
    want = [c if c.endswith("_USDT") else f"{c}_USDT" for c in ss.COIN_LIST]
    live = ss.eligible()
    for c in want:
        if c not in live:
            report.append({"coin": c, "why": "the exchange is not trading it now"})
    inside = set(plan["coins"])
    for c in live:
        if c not in inside:
            report.append({"coin": c, "why": "not in the plan's universe"})
    return [c for c in live if c in inside]


def settle(report: list, entry: dict) -> None:
    """A coin's entry in the report: its final one replaces the placeholder it was given
    when it was claimed (`unfinished`), so a coin claimed and not finished - the machine
    killed at GitHub's time limit, or stopped at the cutoff - stays NAMED in the report
    written so far."""
    report[:] = [e for e in report if not (e["coin"] == entry["coin"] and e.get("unfinished"))]
    report.append(entry)


def hold(report: list, sym: str, tries: int, said: str = "") -> None:
    """The placeholder of a coin this machine holds and has not finished."""
    settle(report, {"coin": sym, "tries": tries, "unfinished": True,
                    "error": said or "claimed, not finished: the machine stopped before this "
                                     "coin was measured"})


def late() -> bool:
    return time.time() - T0 > RETRY_CUTOFF_S


def measure(sym: str, plan: dict) -> dict:
    """One coin's record, saved whole; its report entry."""
    t0 = time.time()
    rec = vm.measure_coin(sym, plan, runs=RUNS, risk_usd=vr.RESEARCH_RISK_USD, fx=FX,
                          log=ss.log)
    rec["machine"] = machine()
    path = vrs.save_coin(OUT_DIR, rec)
    entry = {"coin": sym, "seconds": round(time.time() - t0, 1), "bytes": path.stat().st_size,
             "combos": len(rec.get("combos", {}))}
    if rec.get("why"):
        entry["why"] = rec["why"]
    if rec.get("skipped"):
        entry["skipped"] = rec["skipped"]
    return entry


def run(plan: dict, report: list, head: dict) -> int:
    """Measure every claimed coin; a coin that raises is redone by itself after
    the others (its file deleted first), and named if it never recovers."""
    board = board_of(plan, report)
    ss.report.board = len(board)
    tries: dict = {}
    queue: list = []
    stream = ss.coin_stream(board, T0)
    done = 0
    while True:
        sym = next(stream, None)
        if sym is None:
            if not queue or late():
                for q in queue:
                    settle(report, {"coin": q, "error": "not redone: out of time",
                                    "tries": tries[q]})
                break
            sym = queue.pop(0)
        tries[sym] = tries.get(sym, 0) + 1
        vrs.drop_coin(OUT_DIR, sym)                # never a half-run's file beside a redo
        hold(report, sym, tries[sym])              # named on disk from the moment it is claimed
        save_report(report, **head)
        try:
            entry = measure(sym, plan)
            if tries[sym] > 1:
                entry["tries"] = tries[sym]
            settle(report, entry)
            done += 1
            ss.report.finished = done
        except Exception as exc:                               # noqa: BLE001
            vrs.drop_coin(OUT_DIR, sym)
            said = f"{type(exc).__name__}: {str(exc)[:200]}"
            ss.log(f"{sym}: FAILED (try {tries[sym]}) {said}")
            ss.log(traceback.format_exc()[-800:])
            if tries[sym] <= COIN_RETRIES:
                queue.append(sym)
                hold(report, sym, tries[sym], f"failed, waiting to be redone: {said}")
                time.sleep(5 * tries[sym])
            else:
                settle(report, {"coin": sym, "error": said, "tries": tries[sym]})
        save_report(report, **head)
        ss.report("testing", done, len(board), note=f"{sym} done")
    save_report(report, **head)        # the coins named "not redone" are on disk too
    ss.log(f"done: {done} coin(s) in {(time.time() - T0) / 60:.0f} min")
    return 0


def main() -> int:
    plan, load_error = None, ""
    try:
        plan = vu.load(PLAN_FILE)
    except (OSError, ValueError) as exc:
        load_error = f"{type(exc).__name__}: {exc}"
    head = {"plan_id": PLAN_ID, "risk_usd": vr.RESEARCH_RISK_USD, "runs": RUNS,
            "version": vm.VERSION, "machine": machine()}
    report: list = []
    why = refusal(plan, load_error)
    if why:
        ss.log(f"REFUSED: {why}")
        save_report(report, refused=why, **head)
        return 2
    ss.log(f"backtest v3: plan {plan['id']} ({plan['start']} to {plan['end']}), "
           f"${vr.RESEARCH_RISK_USD:,.2f} risk a trade, {RUNS} random runs a combination")
    return run(plan, report, head)


if __name__ == "__main__":
    raise SystemExit(main())
