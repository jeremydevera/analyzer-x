"""One machine of the daily costs job (phase 4, Oct 10, 2026).

For every coin it claims off the board, and every day it was asked for, this
replays Gate's hourly order-book files (`tradingagents.book_history`) into one
cost reading per minute at the runner's size ($5 x 20), and adds them to that
coin's month file in this account's release (`tradingagents.cost_store`) —
the file every Backtest v2 shard of either account reads its trades' costs
from.

Public data only: Gate's archive needs no key. The upload uses this run's
own GITHUB_TOKEN (contents: write), and only ever writes release assets.

    COIN_LIST  comma-separated symbols this account was dealt (empty: all)
    DAYS_LIST  comma-separated UTC days, YYYY-MM-DD (empty: yesterday)
    NOTIONAL   the size the cost is walked at (default 100 = $5 x 20)
"""
from __future__ import annotations

import calendar
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), ".github", "scripts"))

from progress import ClaimBoard  # noqa: E402

from tradingagents import book_history as bh, cost_store as cs  # noqa: E402
from tradingagents.dataflows import exchange as fx  # noqa: E402

REPO = os.environ.get("GITHUB_REPOSITORY", "")
SHARD = int(os.environ.get("SHARD") or 0)
NOTIONAL = float(os.environ.get("NOTIONAL") or 100.0)
OUT = Path("out")


def log(msg: str) -> None:
    print(f"[costs {SHARD}] {msg}", flush=True)


def days() -> list[int]:
    raw = [d.strip() for d in (os.environ.get("DAYS_LIST") or "").split(",") if d.strip()]
    if not raw:
        t = int(time.time()) - 86400
        return [t - t % 86400]
    out = []
    for d in raw:
        y, m, dd = (int(x) for x in d.split("-"))
        out.append(calendar.timegm((y, m, dd, 0, 0, 0)))
    return sorted(set(out))


def coins() -> list[str]:
    named = [c.strip() for c in (os.environ.get("COIN_LIST") or "").split(",") if c.strip()]
    return named or fx.trading_symbols()


def gh(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True)


def upload(path: Path, tag: str) -> bool:
    """Into this account's release `tag`, creating the release the first
    time any machine needs it (a race between machines is fine: the loser's
    create fails and its upload then succeeds)."""
    for attempt in range(3):
        r = gh("release", "upload", tag, str(path), "--clobber", "-R", REPO)
        if r.returncode == 0:
            return True
        if "release not found" in (r.stderr + r.stdout).lower() or "not found" in r.stderr.lower():
            gh("release", "create", tag, "-R", REPO, "--title", tag, "--notes",
               "Per-minute trading costs replayed from Gate's order-book archive "
               "(tradingagents/book_history.py). One file per coin per month.")
        time.sleep(2 + 3 * attempt)
    log(f"could not upload {path.name} to {tag}: {r.stderr.strip()[:200]}")
    return False


def main() -> int:
    OUT.mkdir(exist_ok=True)
    board = ClaimBoard()
    want = days()
    months: dict[str, list[int]] = {}
    for d in want:
        months.setdefault(cs._month_key(d), []).append(d)
    todo = coins()
    log(f"{len(todo)} coin(s) on the board, {len(want)} day(s): "
        + ", ".join(time.strftime("%Y-%m-%d", time.gmtime(d)) for d in want))
    done = lost = 0
    shards = max(1, int(os.environ.get("SHARDS") or 1))
    for k, sym in enumerate(todo):
        if board.enabled:
            got = board.claim(sym)
            if got is not True:
                continue
        elif k % shards != SHARD:          # no board: a fixed, stable slice
            continue
        try:
            size = float(fx.contract_spec(sym).get("contractSize") or 0.0)
        except Exception as exc:                               # noqa: BLE001
            log(f"{sym}: no contract size ({exc}) — skipped, named")
            lost += 1
            continue
        for ym, ds in sorted(months.items()):
            merged = cs.load_month(sym, ym, repos=(REPO,), cache=False)
            hours = 0
            for d in ds:
                part = bh.day_readings(sym, d, contract_size=size, notional_usd=NOTIONAL)
                hours += int(part.pop("hours_read", 0))
                merged = cs.merge(merged, part)
            if not hours:
                log(f"{sym} {ym}: no order-book hour published for these days")
                continue
            path = OUT / cs.asset(sym, ym)
            path.write_bytes(cs.to_bytes(merged))
            if upload(path, cs.tag(sym, ym)):
                done += 1
            else:
                lost += 1
            path.unlink(missing_ok=True)
        log(f"{sym}: done")
    log(f"finished: {done} coin-month file(s) written, {lost} lost (named above)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
