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


UPLOAD_TRIES = 7


def upload(path: Path, tag: str) -> bool:
    """Into this account's release `tag`, creating the release the first
    time any machine needs it (a race between machines is fine: the loser's
    create fails and its upload then succeeds).

    A RATE-LIMIT refusal is a WAIT, never a lost file (RCA-2026-10-10-N):
    the account's ~1,000 requests an hour come back, and the job has hours.
    It waits 1, 2, 4, 8, 10, 10 minutes before giving up."""
    r = None
    for attempt in range(UPLOAD_TRIES):
        r = gh("release", "upload", tag, str(path), "--clobber", "-R", REPO)
        if r.returncode == 0:
            return True
        said = (r.stderr + r.stdout).lower()
        if "rate limit" in said:
            _pause(min(60 * 2 ** attempt, 600))
            continue
        if "release not found" in said or "not found" in r.stderr.lower():
            gh("release", "create", tag, "-R", REPO, "--title", tag, "--latest=false", "--notes",
               "Per-minute trading costs replayed from Gate's order-book archive "
               "(tradingagents/book_history.py). One file per coin per month.")
        if attempt >= 2:
            break
        _pause(2 + 3 * attempt)
    log(f"could not upload {path.name} to {tag}: {(r.stderr if r else '').strip()[:200]}")
    return False


def _now() -> float:
    return time.time()


def _pause(seconds: float) -> None:
    time.sleep(seconds)


class _NoBoard:
    enabled = False


_NO_BOARD = _NoBoard()


def my_coins(board, todo: list, shards: int, redo: list):
    """The coins THIS machine replays, claimed one at a time — the backtest
    shard's own walk (sweep_shard.coin_stream; RCA-2026-10-10-M):

    * each machine starts in ITS OWN part of the list and staggers its first
      claim, so twenty machines do not race one coin in the same second;
    * a coin another machine took (read over git, free) is never claimed;
    * ONE claim with no answer skips that coin — under contention the board
      runs out of tries while someone else is taking it — and the coin gets
      one more try at the end; three in a row is a board that is down, and
      the walk stops. A coin nobody could claim is left `redo`, named.

    Without a board (local runs) the old fixed slice."""
    if not board.enabled:
        for k, sym in enumerate(todo):
            if k % shards == SHARD:
                yield sym
        return
    _pause((SHARD % shards) * 0.7)
    start = (SHARD * len(todo)) // shards
    order = todo[start:] + todo[:start]
    seen: set = set()
    unanswered: list = []
    dead = 0
    for k, sym in enumerate(order):
        seen |= board.taken()
        if sym in seen:
            continue
        got = board.claim(sym)
        if got is None:
            dead += 1
            if dead >= 3:
                left = [c for c in order[k:] if c not in seen] + unanswered
                redo.append(f"the claim board stopped answering at {sym}: "
                            f"{len(left)} coin(s) left for the next press")
                return
            log(f"claim of {sym} got no answer — skipping it, not stopping")
            unanswered.append(sym)
            continue
        dead = 0
        if got is True:
            yield sym
        else:
            seen.add(sym)
    for sym in unanswered:                 # one more try, when the race is over
        if sym in board.taken():
            continue                       # another machine measured it
        got = board.claim(sym)
        if got is True:
            yield sym
        elif got is None:
            redo.append(f"{sym}: its claim got no answer twice, so no machine "
                        f"measured it")


def held_hours(packed: dict) -> set[int]:
    """The hours (their first second) a month file has readings in. By the
    HOUR, not the day (RCA-2026-10-10-H): the 07:00 UTC press saves today so
    far, and a day "held" by its first reading would never get the rest."""
    t = packed.get("t") if packed else None
    if t is None or not len(t):
        return set()
    return {int(x) - int(x) % 3600 for x in t}


def held_days(packed: dict) -> set[int]:
    """The UTC days whose 24 hours a month file all holds."""
    hrs = held_hours(packed)
    days = {h - h % 86400 for h in hrs}
    return {d for d in days if all(d + 3600 * k in hrs for k in range(24))}


def main() -> int:
    OUT.mkdir(exist_ok=True)
    # NO CLAIM BOARD BY DEFAULT (RCA-2026-10-10-N): every claim is a GitHub
    # request out of the account's ~1,000 an hour, shared with the backtest
    # and the research; the coins are already dealt to this account, so each
    # machine takes a fixed share. COSTS_CLAIM_BOARD=1 switches it back on.
    board = (ClaimBoard() if os.environ.get("COSTS_CLAIM_BOARD") == "1"
             else _NO_BOARD)
    want = days()
    months: dict[str, list[int]] = {}
    for d in want:
        months.setdefault(cs._month_key(d), []).append(d)
    todo = coins()
    log(f"{len(todo)} coin(s) on the board, {len(want)} day(s): "
        + ", ".join(time.strftime("%Y-%m-%d", time.gmtime(d)) for d in want))
    done = skipped = 0
    # what must keep the run RED so the next press tries again (final
    # review, RCA-2026-10-10-F): a run that ends green has its days marked
    # done for ever, so it may only end green when nothing was lost
    redo: list[str] = []
    shards = max(1, int(os.environ.get("SHARDS") or 1))
    for sym in my_coins(board, todo, shards, redo):
        try:
            size = float(fx.contract_spec(sym).get("contractSize") or 0.0)
        except Exception as exc:                               # noqa: BLE001
            log(f"{sym}: no contract size ({exc}) — skipped, named")
            skipped += 1
            continue
        if size <= 0:
            log(f"{sym}: contract size {size} — no cost can be walked; skipped, named")
            skipped += 1
            continue
        for ym, ds in sorted(months.items()):
            # EVERY ACCOUNT'S FILE, merged, and STRICT: the deal moves coins
            # between accounts, so the month may sit on either; and a read
            # that FAILED is never "no file" — the upload below replaces the
            # month with whatever was read
            try:
                merged = cs.load_month(sym, ym, cache=False, strict=True)
            except cs.CostReadError as exc:
                redo.append(str(exc))
                log(f"{exc} — skipped, never overwritten")
                continue
            # RESUMED, never redone: a run that ran out of time leaves its
            # days for the next press, which asks for all of them again — a
            # day this month file already holds is skipped, so each press
            # picks up where the last one stopped (30 days x ~26 coins a
            # machine is past the 350-minute limit: BTC took 132 s a day)
            held = held_hours(merged)
            now = _now()
            ask = {d: [d + 3600 * h for h in range(24)
                       if d + 3600 * h not in held and d + 3600 * (h + 1) <= now]
                   for d in ds}
            ask = {d: hs for d, hs in ask.items() if hs}
            if not ask:
                continue
            hours = 0
            for d, want_hours in sorted(ask.items()):
                part = bh.day_readings(sym, d, contract_size=size, notional_usd=NOTIONAL,
                                       hours=want_hours)
                day = time.strftime("%Y-%m-%d", time.gmtime(d))
                failed = list(part.pop("hours_failed", []) or [])
                bad = list(part.pop("hours_bad", []) or [])
                part.pop("hours_missing", None)
                for hs, why in bad:
                    log(f"{sym} {day} hour {time.gmtime(hs).tm_hour:02d}: the file "
                        f"does not read ({why}) — its minutes stay unmeasured")
                if failed:
                    # the hours that WERE read are kept (held by the hour); a
                    # failed hour holds no reading, so the next press asks
                    # for it again — and this run ends red until it does
                    redo.append(f"{sym} {day}: {len(failed)} hour(s) could not be "
                                f"downloaded")
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
                redo.append(f"{sym} {ym}: the upload failed")
            path.unlink(missing_ok=True)
        log(f"{sym}: done")
    log(f"finished: {done} coin-month file(s) written, {skipped} coin(s) skipped "
        f"(named above), {len(redo)} to do again")
    for line in redo:
        log(f"TO DO AGAIN: {line}")
    return 1 if redo else 0


if __name__ == "__main__":
    raise SystemExit(main())
