"""BACKTEST V3 PART 2a ON THIS PC — build the universe plan, measure a few
coins end to end, print every verdict.

    .venv/Scripts/python -m tradingagents.v3_research plan
    .venv/Scripts/python -m tradingagents.v3_research run BTC_USDT ETH_USDT XAU_USDT --runs 20
    .venv/Scripts/python -m tradingagents.v3_research judge

Decisions doc: docs/superpowers/specs/2026-10-23-backtest-v3-part2-
decisions.md. A few coins is a CHECK of the machinery, never the proof: the
proof pools the whole universe on GitHub (Part 2b), and a check of 3 coins
will rarely reach the 300 unseen trades a verdict needs — it says so.

Reads the exchange (public data only: no key, no order). The command itself
writes only the plan file (`v3_universe.PLAN_FILE`, or `--out`) and its own
folder in the v3 store (`stores.V3.home / "research" / <label>`, on the
store's drive; the label is one plain folder name); it files nothing in a
list, starts no job and touches no screen. Every read goes through the one
door (`fx`), and the exchange adapter keeps its own standing candle and
contract caches under ~/.tradingagents, on the same drive, as it does for
every reader; the command adds nothing else. Prints the order books' coverage
of each coin FIRST (CLAUDE.md "COVERAGE FIRST"), then the verdicts with the
standard kit's figures.

Coins are judged together only when they were measured under ONE plan build
(`v3_universe.plan_id`: builds of one UTC day share an end instant), one plan
end, one risk and one random-run count; every other record is left out and
named, with the field that differs and both values. Every rule and figure
printed is read from the code that decides it (`v3_families.exit_spec`,
`v3_rules`, `v3_proof`, `v3_measure`), never typed: change a number there and
the words follow.
"""
from __future__ import annotations

import argparse
import contextlib
import gzip
import json
import re
import time
from pathlib import Path

from tradingagents import (
    v3_families as vf,
    v3_proof as vp,
    v3_random as vrn,
    v3_rules,
    v3_universe as vu,
)

DEFAULT_LABEL = "local"
LABEL_OK = re.compile(r"[A-Za-z0-9_.-]+")
# Names Windows keeps for its devices, in any case and with any extension ("nul.txt" is the device
# too): a folder of one of these names cannot be made, or is the device itself
DEVICE_NAMES = frozenset({"CON", "PRN", "AUX", "NUL", *(f"COM{k}" for k in range(1, 10)),
                          *(f"LPT{k}" for k in range(1, 10))})
CRASH_GUARD = ("crash_guard (#8) is not tested yet: it needs open-interest history no "
               "reader serves yet (decisions doc).")
FEW_COINS = ("A few coins is a check of the machinery, never the proof: the proof pools the "
             "whole universe on GitHub (Part 2b).")


def plain_label(label: str) -> str:
    """The label if it is one plain folder name - letters, digits, "-", "_" and
    "." only, never "." itself or anything holding "..", never a name Windows
    keeps for a device (CON, PRN, AUX, NUL, COM1-COM9, LPT1-LPT9, in any case,
    alone or before a "."), never ending in "." (Windows drops it, so "x." would
    be the folder "x") - else a ValueError that names it. A label is a folder
    under the v3 store's research folder, so a path must never get in: an
    absolute one would put the records on the system drive (which this repo
    forbids for anything big) and ".." would leave the store. (A space, which
    Windows also drops at the end, is refused with every other character.)"""
    s = str(label)
    if (not LABEL_OK.fullmatch(s) or s == "." or ".." in s or s.endswith(".")
            or s.split(".")[0].upper() in DEVICE_NAMES):
        raise ValueError(f"label {s!r} is not a plain folder name: letters, digits, '-', '_' "
                         "and '.' only, never '.' or '..', never ending in '.', never a Windows "
                         "device name (CON, PRN, AUX, NUL, COM1-9, LPT1-9)")
    return s


def home(label: str = DEFAULT_LABEL) -> Path:
    from tradingagents import stores

    return Path(stores.V3.home) / "research" / plain_label(label)


def coin_file(root: Path, sym: str) -> Path:
    """The coin's file; a name the exchange gives in Chinese is written as
    plain ASCII (`x` + its UTF-8 in hex), as the cost store names it."""
    s = str(sym)
    if not s.isascii():
        s = "x" + s.encode("utf-8").hex()
    return Path(root) / f"{s}.json.gz"


def save_coin(root: Path, rec: dict) -> Path:
    p = coin_file(root, rec["coin"])
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(rec, fh, separators=(",", ":"))
    tmp.replace(p)
    return p


def load_coins(root: Path) -> list[dict]:
    out = []
    for p in sorted(Path(root).glob("*.json.gz")):
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            out.append(json.load(fh))
    return out


def drop_coin(root: Path, sym: str) -> bool:
    """Remove a coin's saved record, if it has one (True when it was there)."""
    p = coin_file(root, sym)
    existed = p.exists()
    p.unlink(missing_ok=True)
    return existed


def money(x: float | None, places: int = 2) -> str:
    if x is None:
        return "-"
    return f"{'-' if x < 0 else '+'}${abs(x):,.{places}f}"


def pct(x: float | None) -> str:
    return "-" if x is None else f"{100 * x:.1f}%"


def plural(n: int, word: str) -> str:
    """A count and its noun, said as many times as there are: "1 trade", "2 trades"."""
    return f"{n} {word}" + ("" if n == 1 else "s")


def exit_words(family: str, key: str, tf: str | None = None) -> tuple[str, str]:
    """(the target rule, the stop rule) of a family's setting, in words. Every
    number is read from what the walk runs on: the exit spec (`vf.exit_spec`:
    the trail's and the snap stop's multiple, the average, the candle limit),
    the ATR's period (`v3_rules.ATR_N`) and, for v3_strength's forced exit,
    `vf.STRENGTH_KEEP`. An unknown family is refused by name. The timeframe
    changes no word (a trend's average is its n DAYS on 4h as on 1d); it
    defaults to the family's first."""
    if family not in vf.FAMILIES:
        raise ValueError(f"unknown family {family!r}")
    value = float(key[1:])
    tf = tf or vf.FAMILIES[family]["tfs"][0]
    spec = vf.exit_spec(family, value, tf)
    atr = f"ATR({v3_rules.ATR_N})"
    if spec["kind"] == "snap":
        return (f"the {spec['mean_n']}-candle average at the signal, resting; out after "
                f"{spec['max_bars']} candles",
                f"an emergency stop {spec['stop_atr']:g} x {atr} at the market")
    trail = f"a trailing stop {spec['atr_mult']:g} x {atr}, never loosened"
    if spec["ma_n"]:
        days = spec["ma_n"] / vf.BARS_PER_DAY[tf]
        return f"none; out on a close past its {days:g}-day average", trail
    if family == "v3_strength":
        keep = vf.STRENGTH_KEEP * value
        return f"none; out at a Monday 00:00 UTC rank outside the top {keep:g}", trail
    return "none", trail


def coin_line(rec: dict) -> str:
    """One coin's COVERAGE FIRST line."""
    if rec.get("why"):
        return f"{rec['coin']}: {rec['why']}"
    pre = rec.get("pre") or {}
    skipped = "; ".join(f"{tf} skipped: {why}" for tf, why in rec.get("skipped", {}).items())
    return (f"{rec['coin']} ({rec['kind']}): order books cover {pct(pre.get('coverage_older'))} "
            f"of the older days' minutes and {pct(pre.get('coverage_unseen'))} of the unseen "
            f"days' (the rest pay its usual {100 * pre.get('flat_slip', 0):.5f}% a side: "
            f"{pre.get('flat_slip_source', '?')}"
            + (f"; the older walk's: {100 * pre['flat_slip_older']:.5f}%, "
               f"{pre.get('flat_slip_older_source', '?')}" if "flat_slip_older" in pre else "")
            + f"); {len(rec.get('combos', {}))} combinations"
            + (f"; {skipped}" if skipped else ""))


def header_lines(plan: dict, runs: int, coins: int, risk: float,
                 no_universe: int = 0, none_measured: int = 0) -> list[str]:
    """The two lines above the coverage: the venue, the coins measured (at least
    one timeframe measured), how many were in no family's universe and how many
    had every timeframe skipped, the window and its split, the random runs, the
    combinations tried, the luck correction and the risk - each from the plan,
    the arguments or the code that decides it."""
    from tradingagents.positions_view import fmt_when
    from tradingagents.v3_measure import UNSEEN_DAYS, windows

    start, split, end = windows(plan)
    tried, filters = vp.TRIED, len(vf.FILTERS)
    cells = len({c[:3] for c in vf.combos()})
    less = (f", less the {cells * filters - tried} not tried: "
            + ", ".join(f"{f} on {tf}" for f, tf in vf.NOT_TRIED)) if cells * filters > tried else ""
    idle = f", {no_universe} in no family's universe" if no_universe else ""
    idle += (f", {none_measured} with every timeframe skipped (its line says why)"
             if none_measured else "")
    return [f"Backtest v3 Part 2a on {plan.get('venue') or 'the exchange'}: {coins} coin(s) "
            f"measured{idle}; the window {fmt_when(start / 1000)} to {fmt_when(end / 1000)} - "
            f"older days to {fmt_when(split / 1000)}, then {UNSEEN_DAYS} unseen days; {runs} "
            f"random runs a combination",
            f"{tried} combinations tried ({cells} family-setting-timeframes x "
            f"{filters} filter choices{less}), alpha = {vp.ALPHA:g} / {tried}, "
            f"z = {vp.z_for(tried, vp.ALPHA):.3f}; ${risk:,.2f} risk a trade (margin = the coin "
            f"bought / its leverage)"]


# Why a random run's entry never became a trade, in words, in the order a tie is said
# (`v3_proof.not_traded`: "short", "in_trade" and the engine's own counts, `v3_measure.DROPS`)
NOT_TRADED_WORDS = (
    ("in_trade", "fell inside the run's own open trade"),
    ("no_levels", "had no target or stop (ATR or the average not ready, or a snap drawn on the far "
                  "side of its average)"),
    ("short", "could not be placed (the month had too few candles to draw from)"),
    ("too_small", "were under one lot"),
    ("unsafe_stop", "had no safe leverage"),
    ("gate_blocked", "were turned away by the cost check"),
    ("chase_skip", "found the price had run away"),
    ("closed_skip", "fell on a closed market"),
    ("missed", "rested and never filled"),
    ("post_only_reject", "were rejected as post-only"),
    ("no_next_bar", "fell on the last candle"),
)


def _older_one(k: str, o: dict) -> str:
    """One setting's older-days figure, with the share of its exits that paid a
    typical cost beside it (M1: the evidence the choice was made on)."""
    text = f"{k} {money(o['per_trade'], 3)} a trade over {o['trades']}"
    notes = [] if o["eligible"] else ["too few"]
    if o["trades"] and "cost_unmeasured" in o:
        notes.append(f"exits at a typical cost {o['cost_unmeasured']} of {o['trades']}")
    return text + (f" ({'; '.join(notes)})" if notes else "")


def random_line(made: dict) -> str:
    """How far the random runs' trades fell short of the real run's, and why
    their other entries never traded, summed over every run and coin: the luck
    bar is stricter than "as many trades as the real run" by that much (the
    decisions doc, "Random entries")."""
    runs, med = made.get("runs", 0), made.get("median_trades")
    if med is None:
        return "   random runs: how many times they traded was not recorded"
    head = (f"   random runs traded a median {med:,g} of the real run's "
            f"{plural(made.get('real_trades', 0), 'trade')}")
    nt = made.get("not_traded")
    if nt is None:
        return head + "; why their other entries never traded was not recorded"
    said = dict(NOT_TRADED_WORDS)
    order = [k for k, _w in NOT_TRADED_WORDS] + sorted(set(nt) - set(said))
    parts = [f"{nt[k]:,} {said.get(k, k)}"
             for k in sorted((k for k in order if nt.get(k)), key=lambda k: (-nt[k], order.index(k)))]
    if not parts:
        return head + f"; over the {runs:,} runs, every entry they placed traded"
    return head + f"; over the {runs:,} runs, entries that never traded: " + ", ".join(parts)


def _filter_counts(c: dict) -> str:
    """The filter's counts of the verdict's own signal candles (one setting's,
    pooled over the coins): what it blocked, and what it could not judge
    (each where it is above 0, with the filter that counted it)."""
    sig = c.get("signal_candles", 0)
    out = f"filter blocked {c.get('blocked', 0)} of {sig} signal candles"
    for key, words in (("funding_unknown", "funding_side could not judge {n} of {s} signal "
                                           "candles (they passed)"),
                       ("mood_unknown", "btc_mood could not judge {n} of {s} signal candles "
                                        "(they passed)"),
                       ("settle_by_cycle", "funding_minutes judged {n} of {s} signal candles by "
                                           "the settlement cycle (no recorded settlement)")):
        if c.get(key):
            out += "; " + words.format(n=c[key], s=sig)
    return out


def _verdict_body(v: dict) -> list[str]:
    from tradingagents.v3_measure import BOOK_USD, UNSEEN_DAYS

    head = f"#{v['id']} {v['family']} {v['tf']} {v['filter']}"
    older = ", ".join(_older_one(k, o) for k, o in v["older"].items())
    state = "PASSED" if v["passed"] else f"FAILED at {v['failed']}"
    if v["failed"] == "choose":
        return [f"{head}: {state} - {v['why']} (older days: {older or 'no trades'})"]
    s, r, b = v["unseen"], v["random"] or {}, v["bootstrap"]
    c = v["counts"]
    if not s["trades"]:
        # a filter that blocked the unseen days' signals says how many, here as on a full line
        said = "" if v["filter"] == "none" else f"; {_filter_counts(c)}"
        return [f"{head}: setting {v['setting']} - {state}: no trade on the unseen days{said} "
                f"(older days: {older})"]
    target, stop = exit_words(v["family"], v["setting"], v["tf"])
    lev = v["lev"] or ["-", "-"]
    notional = v["notional"] or [0.0, 0.0]
    made = v.get("random_runs") or r      # the runs made and those that traded, bar or no bar
    return [
        f"{head}: setting {v['setting']} - {state} (older days: {older})",
        f"   unseen: {plural(s['trades'], 'trade')} ({s['trades'] / UNSEEN_DAYS:.2f} a day), "
        f"{s['wins']} won / {s['losses']} lost, {pct(s['win_rate'])} (break-even "
        f"{pct(s['break_even'])}), PROFIT {money(s['profit'])}, {money(s['per_trade'], 3)} a "
        f"trade; random runs: median {money(r.get('median'), 3)}, bar {money(r.get('bar'), 3)} "
        f"({made.get('traded', 0)} of {made.get('runs', 0)} traded); bootstrap low "
        f"{money(b['low'], 3)} over {plural(b['days'], 'day')}; worst losing run "
        f"{money(s['worst_run_usd'])} over {plural(s['worst_run_trades'], 'trade')}",
        random_line(v.get("random_runs") or {}),
        f"   target: {target}; stop: {stop}; leverage {lev[0]}x-{lev[1]}x; "
        f"${notional[0]:,.0f}-${notional[1]:,.0f} of coin a trade ({v['over_book']} over the "
        f"books' ${BOOK_USD:,.0f})",
        f"   counts: missed {c.get('missed', 0)} and post-only rejected "
        f"{c.get('post_only_reject', 0)} (their market twins {money(v['twins_pnl'])} over "
        f"{v['twins']}); exits at a typical cost {c.get('cost_unmeasured', 0)} of {s['trades']}; "
        f"funding estimated on {c.get('funding_estimated', 0)} of {plural(s['trades'], 'trade')}; "
        f"{_filter_counts(c)}; refused signal candles: under one lot "
        f"{c.get('too_small', 0)}, no safe leverage {c.get('unsafe_stop', 0)}, the cost check "
        f"{c.get('gate_blocked', 0)}; open at the end {s['open_at_end']}; coins {len(v['coins'])}"]


def verdict_lines(v: dict) -> list[str]:
    """One verdict as the standard kit asks: id first, profit, target and stop
    rules, leverage, wins and losses, worst losing run, trades and a day - then
    each note its filter carries, beneath it. The survivorship note every
    verdict carries is said once, at the foot of the report, not under each."""
    notes = [n for n in v.get("notes") or [] if n != vu.SURVIVORSHIP]
    return _verdict_body(v) + [f"   note: {n}" for n in notes]


def differences(rec: dict, plan: dict, runs: int, risk: float) -> list[str]:
    """What differs between a saved record and the plan, run count and risk
    being judged, one phrase per field with both values (plan build, plan end,
    risk, run count); empty when the record fits. A field the record does not
    carry is never assumed to fit: it is named as not recorded."""
    from tradingagents.positions_view import fmt_when

    out = []
    ours = plan.get("id") or vu.plan_id(plan)
    if rec.get("plan_id") != ours:
        out.append(f"plan build {rec.get('plan_id') or 'not recorded'}, not {ours}")
    end = int(plan["end_ms"])
    if rec.get("plan_end_ms") != end:
        theirs = rec.get("plan_end_ms")
        said = "not recorded" if theirs is None else fmt_when(int(theirs) / 1000)
        out.append(f"plan end {said}, not {fmt_when(end / 1000)}")
    if rec.get("risk_usd") is None:
        out.append("no risk recorded")
    elif float(rec["risk_usd"]) != risk:
        out.append(f"risk ${float(rec['risk_usd']):,.2f}, not ${risk:,.2f}")
    got = int(rec.get("runs") or 0)
    if not got:
        out.append("no run count recorded")
    elif got != runs:
        out.append(f"{got} random runs, not {runs}")
    return out


def split_records(records: list[dict], plan: dict, runs: int,
                  risk: float) -> tuple[list[dict], list[tuple[str, list[str]]]]:
    """(the records measured under THIS plan build, plan end, risk and run
    count, and every other record as (its coin, what differs)): a record of
    another plan is never pooled, and always named."""
    kept, other = [], []
    for r in records:
        why = differences(r, plan, runs, risk)
        if why:
            other.append((r["coin"], why))
        else:
            kept.append(r)
    return kept, other


def left_out_line(other: list[tuple[str, list[str]]]) -> str:
    return ("left out, not measured under this plan build, plan end, risk and run count: "
            + ", ".join(f"{coin} ({'; '.join(why)})" for coin, why in other))


def report(records: list[dict], plan: dict, runs: int, risk: float) -> tuple[list[str], list[dict]]:
    """Every line the command prints, and the verdicts."""
    verdicts = vp.verdicts(records)
    # a coin is measured when at least one of its timeframes was: a record whose every timeframe was
    # skipped (too few candles) holds no walk, and its coverage line says why
    idle = [r for r in records if r.get("why")]
    measured = [r for r in records if not r.get("why") and r.get("windows")]
    lines = header_lines(plan, runs, len(measured), risk, len(idle),
                         len(records) - len(idle) - len(measured))
    lines += [coin_line(r) for r in records]
    for v in verdicts:
        lines += verdict_lines(v)
    passed = sum(1 for v in verdicts if v["passed"])
    lines += [f"{passed} of {len(verdicts)} verdicts passed.", vu.SURVIVORSHIP, CRASH_GUARD,
              FEW_COINS]
    return lines, verdicts


def verdicts_file(plan: dict, risk: float, runs: int, records: list[dict],
                  verdicts: list[dict]) -> dict:
    """What `verdicts.json` holds: the verdicts WITH what they were judged
    under - the plan build and its end (ms), the risk, the random runs, the
    coins pooled and when (seconds) - so a reader (the Backtest v3 tab's check
    card) says what it shows without guessing. A file written before this
    (a bare list) carries none of it, and the tab says to judge again."""
    return {"plan_id": plan.get("id") or vu.plan_id(plan), "plan_end": int(plan["end_ms"]),
            "risk_usd": float(risk), "runs": int(runs),
            "coins": [r["coin"] for r in records], "judged_at": time.time(),
            "verdicts": verdicts}


def _label_arg(text: str) -> str:
    try:
        return plain_label(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def main(argv=None) -> int:
    import sys

    p = argparse.ArgumentParser(prog="python -m tradingagents.v3_research",
                                description="Backtest v3 Part 2a on this PC.")
    sub = p.add_subparsers(dest="cmd", required=True)
    risk_help = (f"dollars a trade risks (default ${v3_rules.RESEARCH_RISK_USD:,.2f}, the "
                 f"research's own; the tab's is ${v3_rules.RISK_USD:,.2f})")
    runs_help = f"random runs a combination (default {vrn.RUNS})"
    pl = sub.add_parser("plan", help="build the universe plan from daily candles")
    pl.add_argument("--out", default=str(vu.PLAN_FILE))
    ru = sub.add_parser("run", help="measure coins end to end and print every verdict")
    ru.add_argument("coins", nargs="+")
    ru.add_argument("--plan", default=str(vu.PLAN_FILE))
    ru.add_argument("--runs", type=int, default=vrn.RUNS, help=runs_help)
    ru.add_argument("--risk", type=float, default=None, help=risk_help)
    ru.add_argument("--label", type=_label_arg, default=DEFAULT_LABEL)
    ju = sub.add_parser("judge", help="judge the coins already measured under a label")
    ju.add_argument("--plan", default=str(vu.PLAN_FILE))
    ju.add_argument("--runs", type=int, default=vrn.RUNS, help=runs_help)
    ju.add_argument("--risk", type=float, default=None, help=risk_help)
    ju.add_argument("--label", type=_label_arg, default=DEFAULT_LABEL)
    a = p.parse_args(argv)
    with contextlib.suppress(AttributeError, ValueError):
        sys.stdout.reconfigure(encoding="utf-8")        # coin names in Chinese
    if a.cmd == "plan":
        t0 = time.time()
        plan = vu.collect(log=print)
        path = vu.save(plan, a.out)
        print(f"plan {path}: {plan['start']} to {plan['end']}, {len(plan['months'])} months, "
              f"{len(plan['coins'])} coins in a group; liquid {len(plan['liquid'][plan['months'][-1]])}"
              f" and calm {len(plan['calm'][plan['months'][-1]])} in {plan['months'][-1]}; "
              f"{len(plan.get('left_out', {}))} left out; "
              f"{len(plan['skipped'])} skipped ({time.time() - t0:.0f} s)")
        for sym, why in plan["skipped"].items():
            print(f"  skipped {sym}: {why}")
        for sym, why in plan.get("left_out", {}).items():
            print(f"  left out {sym}: {why}")
        return 0
    plan = vu.load(a.plan)
    root = home(a.label)
    risk = v3_rules.RESEARCH_RISK_USD if a.risk is None else float(a.risk)
    failed: dict[str, str] = {}
    if a.cmd == "run":
        from tradingagents.v3_measure import measure_coin

        for sym in a.coins:
            sym, t0 = sym.upper(), time.time()
            try:
                rec = measure_coin(sym, plan, runs=a.runs, risk_usd=risk, log=print)
            except Exception as exc:                            # noqa: BLE001
                failed[sym] = f"{type(exc).__name__}: {str(exc)[:160]}"
                rec = None
            if rec is None:
                # A failed coin is named, its OLD record is dropped (a failed redo must never leave
                # the last measurement in the pool) and the others go on; the command ends 1. A
                # record that cannot be dropped (a file another program holds) is named with the
                # failure and left out of the judging below, never allowed to stop the coins after it
                try:
                    drop_coin(root, sym)
                except OSError as exc:
                    failed[sym] += (f"; its old record {coin_file(root, sym)} could not be "
                                    f"dropped ({type(exc).__name__}: {str(exc)[:120]})")
                print(f"FAILED {sym}: {failed[sym]} ({time.time() - t0:.0f} s)")
                continue
            save_coin(root, rec)
            print(coin_line(rec) + f" ({time.time() - t0:.0f} s)")
    # a coin that failed in this run is never judged, even if its old record could not be dropped
    records, other = split_records([r for r in load_coins(root) if r.get("coin") not in failed],
                                   plan, a.runs, risk)
    lines, verdicts = report(records, plan, a.runs, risk)
    if other:
        lines.insert(2, left_out_line(other))
    root.mkdir(parents=True, exist_ok=True)
    (root / "verdicts.json").write_text(json.dumps(
        verdicts_file(plan, risk, a.runs, records, verdicts), default=str), encoding="utf-8")
    print("\n".join(lines))
    if failed:
        print(f"{len(failed)} coin(s) failed and were left out: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
