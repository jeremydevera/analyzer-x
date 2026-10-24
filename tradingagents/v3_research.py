"""BACKTEST V3 PART 2a ON THIS PC — build the universe plan, measure a few
coins end to end, print every verdict.

    .venv/Scripts/python -m tradingagents.v3_research plan
    .venv/Scripts/python -m tradingagents.v3_research run BTC_USDT ETH_USDT XAU_USDT --runs 20
    .venv/Scripts/python -m tradingagents.v3_research judge

Decisions doc: docs/superpowers/specs/2026-10-23-backtest-v3-part2-
decisions.md. A few coins is a CHECK of the machinery, never the proof: the
proof pools the whole universe on GitHub (Part 2b), and a check of 3 coins
will rarely reach the 300 unseen trades a verdict needs — it says so.

Reads the exchange; writes only the plan file (`v3_universe.PLAN_FILE`) and
its own folder in the v3 store (`stores.V3.home / "research" / <label>`, on
the store's drive); places no order, files nothing in a list, touches no
screen. Prints the order books' coverage of each coin FIRST (CLAUDE.md
"COVERAGE FIRST"), then the verdicts with the standard kit's figures.
"""
from __future__ import annotations

import argparse
import contextlib
import gzip
import json
import time
from pathlib import Path

from tradingagents import v3_families as vf, v3_proof as vp, v3_universe as vu

DEFAULT_LABEL = "local"
CRASH_GUARD = ("crash_guard (#8) is not tested yet: it needs open-interest history no "
               "reader serves yet (decisions doc).")
FEW_COINS = ("A few coins is a check of the machinery, never the proof: the proof pools the "
             "whole universe on GitHub (Part 2b).")


def home(label: str = DEFAULT_LABEL) -> Path:
    from tradingagents import stores

    return Path(stores.V3.home) / "research" / str(label)


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


def money(x: float | None, places: int = 2) -> str:
    if x is None:
        return "-"
    return f"{'-' if x < 0 else '+'}${abs(x):,.{places}f}"


def pct(x: float | None) -> str:
    return "-" if x is None else f"{100 * x:.1f}%"


def exit_words(family: str, key: str) -> tuple[str, str]:
    """(the target rule, the stop rule) of a family's setting, in words."""
    v = float(key[1:])
    trail = "a trailing stop 3 x ATR(20), never loosened"
    if family == "v3_trend":
        return f"none; out on a close past its {v:g}-day average", trail
    if family == "v3_breakout":
        return "none", trail
    if family == "v3_strength":
        return f"none; out at a Monday 00:00 UTC rank outside the top {2 * v:g}", trail
    return ("the 20-candle average, resting; out after 24 candles",
            "an emergency stop 3 x ATR(20) at the market")


def coin_line(rec: dict) -> str:
    """One coin's COVERAGE FIRST line."""
    if rec.get("why"):
        return f"{rec['coin']}: {rec['why']}"
    pre = rec.get("pre") or {}
    skipped = "; ".join(f"{tf} skipped: {why}" for tf, why in rec.get("skipped", {}).items())
    return (f"{rec['coin']} ({rec['kind']}): order books cover {pct(pre.get('coverage_older'))} "
            f"of the older days' minutes and {pct(pre.get('coverage_unseen'))} of the unseen "
            f"days' (the rest pay its usual {100 * pre.get('flat_slip', 0):.5f}% a side: "
            f"{pre.get('flat_slip_source', '?')}); {len(rec.get('combos', {}))} combinations"
            + (f"; {skipped}" if skipped else ""))


def header_lines(plan: dict, runs: int, coins: int, risk: float) -> list[str]:
    from tradingagents.positions_view import fmt_when
    from tradingagents.v3_measure import UNSEEN_DAYS, windows

    start, split, end = windows(plan)
    return [f"Backtest v3 Part 2a on {plan.get('venue') or 'the exchange'}: {coins} coin(s); "
            f"the window {fmt_when(start / 1000)} to {fmt_when(end / 1000)} - older days to "
            f"{fmt_when(split / 1000)}, then {UNSEEN_DAYS} unseen days; {runs} random runs a "
            f"combination",
            f"{vp.TRIED} combinations tried ({vp.TRIED // len(vf.FILTERS)} family-setting-"
            f"timeframes x {len(vf.FILTERS)} filter choices), "
            f"alpha = 0.05 / {vp.TRIED}, z = {vp.Z:.3f}; ${risk:,.2f} risk a trade (margin = the "
            f"coin bought / its leverage)"]


def verdict_lines(v: dict) -> list[str]:
    """One verdict as the standard kit asks: id first, profit, target and stop
    rules, leverage, wins and losses, worst losing run, trades and a day."""
    from tradingagents.v3_measure import UNSEEN_DAYS

    head = f"#{v['id']} {v['family']} {v['tf']} {v['filter']}"
    older = ", ".join(f"{k} {money(o['per_trade'], 3)} a trade over {o['trades']}"
                      + ("" if o["eligible"] else " (too few)")
                      for k, o in v["older"].items())
    state = "PASSED" if v["passed"] else f"FAILED at {v['failed']}"
    if v["failed"] == "choose":
        return [f"{head}: {state} - {v['why']} (older days: {older or 'no trades'})"]
    s, r, b = v["unseen"], v["random"] or {}, v["bootstrap"]
    if not s["trades"]:
        return [f"{head}: setting {v['setting']} - {state}: no trade on the unseen days "
                f"(older days: {older})"]
    target, stop = exit_words(v["family"], v["setting"])
    c = v["counts"]
    lev = v["lev"] or ["-", "-"]
    notional = v["notional"] or [0.0, 0.0]
    return [
        f"{head}: setting {v['setting']} - {state} (older days: {older})",
        f"   unseen: {s['trades']} trades ({s['trades'] / UNSEEN_DAYS:.2f} a day), {s['wins']} "
        f"won / {s['losses']} lost, {pct(s['win_rate'])} (break-even {pct(s['break_even'])}), "
        f"PROFIT {money(s['profit'])}, {money(s['per_trade'], 3)} a trade; random runs: median "
        f"{money(r.get('median'), 3)}, bar {money(r.get('bar'), 3)} ({r.get('traded', 0)} of "
        f"{r.get('runs', 0)} traded); bootstrap low {money(b['low'], 3)} over {b['days']} days; "
        f"worst losing run {money(s['worst_run_usd'])} over {s['worst_run_trades']} trades",
        f"   target: {target}; stop: {stop}; leverage {lev[0]}x-{lev[1]}x; "
        f"${notional[0]:,.0f}-${notional[1]:,.0f} of coin a trade ({v['over_book']} over the "
        f"books' $100)",
        f"   counts: missed {c.get('missed', 0)} and post-only rejected "
        f"{c.get('post_only_reject', 0)} (their market twins {money(v['twins_pnl'])} over "
        f"{v['twins']}); exits at a typical cost {c.get('cost_unmeasured', 0)} of {s['trades']}; "
        f"funding estimated {c.get('funding_estimated', 0)}, unknown "
        f"{c.get('funding_unknown', 0)}; filter blocked {c.get('blocked', 0)} of "
        f"{c.get('signal_candles', 0)} signal candles; refused signal candles: under one lot "
        f"{c.get('too_small', 0)}, no safe leverage {c.get('unsafe_stop', 0)}, the cost check "
        f"{c.get('gate_blocked', 0)}; open at the end {s['open_at_end']}; coins {len(v['coins'])}"]


def report(records: list[dict], plan: dict, runs: int, risk: float) -> tuple[list[str], list[dict]]:
    """Every line the command prints, and the verdicts."""
    verdicts = vp.verdicts(records)
    lines = header_lines(plan, runs, len(records), risk)
    lines += [coin_line(r) for r in records]
    for v in verdicts:
        lines += verdict_lines(v)
    passed = sum(1 for v in verdicts if v["passed"])
    lines += [f"{passed} of {len(verdicts)} verdicts passed.", vu.SURVIVORSHIP, CRASH_GUARD,
              FEW_COINS]
    return lines, verdicts


def main(argv=None) -> int:
    import sys

    p = argparse.ArgumentParser(prog="python -m tradingagents.v3_research",
                                description="Backtest v3 Part 2a on this PC.")
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("plan", help="build the universe plan from daily candles")
    pl.add_argument("--out", default=str(vu.PLAN_FILE))
    ru = sub.add_parser("run", help="measure coins end to end and print every verdict")
    ru.add_argument("coins", nargs="+")
    ru.add_argument("--plan", default=str(vu.PLAN_FILE))
    ru.add_argument("--runs", type=int, default=200)
    ru.add_argument("--risk", type=float, default=None, help="dollars a trade risks ($1)")
    ru.add_argument("--label", default=DEFAULT_LABEL)
    ju = sub.add_parser("judge", help="judge the coins already measured under a label")
    ju.add_argument("--plan", default=str(vu.PLAN_FILE))
    ju.add_argument("--runs", type=int, default=200)
    ju.add_argument("--risk", type=float, default=None, help="dollars a trade risks ($1)")
    ju.add_argument("--label", default=DEFAULT_LABEL)
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
    from tradingagents import v3_rules

    plan = vu.load(a.plan)
    root = home(a.label)
    risk = v3_rules.RISK_USD if a.risk is None else float(a.risk)
    if a.cmd == "run":
        from tradingagents.v3_measure import measure_coin

        for sym in a.coins:
            t0 = time.time()
            rec = measure_coin(sym.upper(), plan, runs=a.runs, risk_usd=risk, log=print)
            save_coin(root, rec)
            print(coin_line(rec) + f" ({time.time() - t0:.0f} s)")
    records, other = [], []
    for r in load_coins(root):
        same = (r.get("plan_end_ms") == int(plan["end_ms"])
                and float(r.get("risk_usd", v3_rules.RISK_USD)) == risk
                and int(r.get("runs") or 0) == a.runs)
        (records if same else other).append(r)
    lines, verdicts = report(records, plan, a.runs, risk)
    if other:
        lines.insert(2, f"left out, measured under another plan, at another risk than "
                        f"${risk:,.2f} or with other than {a.runs} random runs: "
                        + ", ".join(r["coin"] for r in other))
    root.mkdir(parents=True, exist_ok=True)
    (root / "verdicts.json").write_text(json.dumps(verdicts, default=str), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
