"""THE PINNED LIST OF THE backtesting-trading-strategies SKILL'S STRATEGIES (skill rooms, Nov 10, 2026).

Backtest v4's 15,933 backtesting-skill strategies were CHOSEN once (Nov 05, 2026: each coin-timeframe's
best 3 on the older 70% of its candles). The daily run measures those same strategies again, never a
fresh choice - a strategy's id is its coin, timeframe, strategy, settings and stop, so choosing again
would move ids under the rooms that follow them. This module freezes the choice into
`research/v4/bt_pinned.json`, which the daily shard reads from its checkout.

    python -m tradingagents.v4_pin build
"""
from __future__ import annotations

import json
import time
from pathlib import Path

KEYS = ("strategy", "params", "stop", "target")


def default_src() -> Path:
    from tradingagents import acs

    return acs.home() / "skill.json"


def default_out() -> Path:
    return Path(__file__).resolve().parent.parent / "research" / "v4" / "bt_pinned.json"


def build(src: Path | None = None, out: Path | None = None) -> dict:
    """Every pick of every line of the collected skill run, with its pair's ORIGINAL split."""
    src = Path(src) if src is not None else default_src()
    out = Path(out) if out is not None else default_out()
    lines = json.loads(src.read_text(encoding="utf-8"))["lines"]
    pairs = {}
    for key in sorted(lines):
        line = lines[key]
        pairs[f"{line['coin']}|{line['tf']}"] = {
            "split_ms": int(line["split_ms"]),
            "picks": [{k: p.get(k) for k in KEYS} for p in line["picks"]]}
    res = {"made_s": int(time.time()), "source": src.name, "pairs": pairs}
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(res, separators=(",", ":")), encoding="utf-8")
    tmp.replace(out)
    return res


def count(pinned: dict) -> int:
    return sum(len(v["picks"]) for v in pinned["pairs"].values())


def main(argv=None) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="python -m tradingagents.v4_pin")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--src", default=None)
    b.add_argument("--out", default=None)
    a = p.parse_args(argv)
    if a.cmd == "build":
        res = build(a.src, a.out)
        print(f"pinned {count(res):,} strategies on {len(res['pairs']):,} coin-timeframes "
              f"from {res['source']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
