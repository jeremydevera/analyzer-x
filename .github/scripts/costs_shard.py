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
# A COIN GATE PUBLISHES LATER THAN THE OTHERS (RCA-2026-10-30-D): a 404 hour the archive
# already holds for another coin is owed to this coin when its own newest hour is at most
# this far behind the archive's end - the run goes red and the day is pressed again; further
# behind, Gate stopped publishing the coin (delisted) and the hour is final, named
LAG_S = 6 * 3600


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
    far, and a day "held" by its first reading would never get the rest.

    Only readings taken when practice looks count (`bh.READ_AT_S`,
    RCA-2026-10-15-G): an hour read at the close itself — every month written
    before Oct 15, 2026 — is read again and replaced."""
    t = packed.get("t") if packed else None
    if t is None or not len(t):
        return set()
    at = packed.get("at")
    if at is None:
        return set()
    return {int(x) - int(x) % 3600 for x, a in zip(t, at, strict=True)
            if int(a) == bh.READ_AT_S}


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
    # coins with hours Gate has NOT PUBLISHED YET (RCA-2026-10-30-A): {sym:
    # (its newest published hour or None, the days waiting)} - never red, never
    # "never published"; the PC marks a day done only once the archive holds it
    waiting: dict = {}
    # what must keep the run RED so the next press tries again (final
    # review, RCA-2026-10-10-F): a run that ends green has its days marked
    # done for ever, so it may only end green when nothing was lost
    redo: list[str] = []
    shards = max(1, int(os.environ.get("SHARDS") or 1))
    tails: list = []       # (coin, its 404 hours, its newest hour seen) - judged after every coin
    run_top = None         # the newest hour this machine saw published or held, for any coin
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
        latest = None          # the newest hour of this coin seen published, read or held
        absent: list = []      # its 404 hours, judged against `latest` once every month is read
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
            if held:
                latest = max(held) if latest is None else max(latest, max(held))
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
                missing = list(part.pop("hours_missing", []) or [])
                # an hour READ is replaced whole (`cs.without_hours`); one
                # that failed, did not parse or was never published keeps
                # what the month already held
                read = (set(want_hours) - set(failed) - set(missing)
                        - {hs for hs, _why in bad})
                there = set(want_hours) - set(failed) - set(missing)   # a bad file is there
                if there:
                    latest = max(there) if latest is None else max(latest, max(there))
                absent += missing
                if merged is not None:
                    merged = cs.without_hours(merged, read)
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
                log(f"{sym} {ym}: no order-book hour of these days was read")
                continue
            path = OUT / cs.asset(sym, ym)
            path.write_bytes(cs.to_bytes(merged))
            if upload(path, cs.tag(sym, ym)):
                done += 1
            else:
                redo.append(f"{sym} {ym}: the upload failed")
            path.unlink(missing_ok=True)
        tails.append((sym, absent, latest))
        if latest is not None:
            run_top = latest if run_top is None else max(run_top, latest)
        log(f"{sym}: done")
    top = _archive_top(run_top) if any(_later(a, lt) for _s, a, lt in tails) else None
    for sym, absent, latest in tails:
        late = _say_absent(sym, absent, latest, top=top, redo=redo)
        if late:
            waiting[sym] = late
    log(f"finished: {done} coin-month file(s) written, {skipped} coin(s) skipped "
        f"(named above), {len(redo)} to do again")
    for line in redo:
        log(f"TO DO AGAIN: {line}")
    if waiting:
        known = sorted({h for h, _d in waiting.values() if h is not None})
        after = ("for any hour asked" if not known
                 else f"after the hour starting {_when(known[0])}" if len(known) == 1
                 else f"after the hours starting {_when(known[0])} to {_when(known[-1])}")
        log(f"Gate has published no order book {after} for {len(waiting)} coin(s); "
            f"{sum(len(d) for _h, d in waiting.values())} coin-day(s) wait for it. Not a "
            f"failure: the PC marks a day done only once Gate's archive (read on "
            f"{bh.PROBE_SYMBOL}) holds its last hour, so a day Gate has published for no "
            f"coin yet is asked for again")
    return 1 if redo else 0


def _when(ts: int) -> str:
    """THE date format (CLAUDE.md "Date format"); a GitHub machine's clock is UTC."""
    from tradingagents.positions_view import fmt_when

    return f"{fmt_when(ts)} UTC"


def _later(absent: list, latest) -> list:
    """The 404 hours of a coin with no later hour of it seen: the end of its archive."""
    return sorted(h for h in absent if latest is None or h >= latest)


def _archive_top(run_top):
    """The newest hour Gate's archive holds for ANY coin (RCA-2026-10-30-D): the newer of
    what this machine read or held and the archive's own probe (`bh.PROBE_SYMBOL`); a probe
    that cannot be read leaves this machine's own coins as the yardstick, said."""
    try:
        probed = bh.newest_published_hour(_now())
    except Exception as exc:                                   # noqa: BLE001
        log(f"the archive's end could not be read on {bh.PROBE_SYMBOL} "
            f"({str(exc)[:120]}) - judged on this machine's own coins")
        probed = None
    known = [h for h in (run_top, probed) if h is not None]
    return max(known) if known else None


def _say_holes(sym: str, hours) -> None:
    """One line a DAY (a young coin pressed for a month has hundreds of hours before its
    first file): "hour 06: ... it" for one hour, "12 hours, 00 to 11: ... them" for more."""
    by_day: dict = {}
    for h in sorted(hours):
        by_day.setdefault(h - h % 86400, []).append(time.gmtime(h).tm_hour)
    for d, hrs in by_day.items():
        day = time.strftime('%Y-%m-%d', time.gmtime(d))
        if len(hrs) == 1:
            log(f"{sym} {day} hour {hrs[0]:02d}: Gate never published it (a later hour is "
                f"published) - its minutes stay unmeasured")
        else:
            log(f"{sym} {day} {len(hrs)} hours, {hrs[0]:02d} to {hrs[-1]:02d}: Gate never "
                f"published them (a later hour is published) - their minutes stay unmeasured")


def _judge_behind(sym: str, behind: list, top: int, redo: list) -> None:
    """404 hours of `sym` that Gate's archive holds for another coin (RCA-2026-10-30-D),
    judged on the coin's OWN newest hour (`bh.newest_published_hour`, starting at `top`: one
    HEAD when the coin is there): an hour before it is a hole; after it, the coin is LAGGING
    when it is at most LAG_S behind - red, so the day is pressed again - and STOPPED when
    further (final, named); a coin with no hour in the archive is final, named. A coin that
    cannot be checked is red: unknown is not final."""
    try:
        own = bh.newest_published_hour(top + 3600, symbol=sym)
    except Exception as exc:                                   # noqa: BLE001
        redo.append(f"{sym}: {len(behind)} hour(s) Gate's archive holds for other coins "
                    f"could not be checked for this coin ({str(exc)[:120]})")
        return
    if own is None:
        log(f"{sym}: Gate's archive holds no hour of this coin in the last "
            f"{bh.PROBE_BACK_HOURS // 24} days - {len(behind)} hour(s) stay unmeasured")
        return
    _say_holes(sym, [h for h in behind if h < own])
    owed = [h for h in behind if h > own]
    if not owed:
        return
    if top - own <= LAG_S:
        log(f"{sym}: Gate's archive is behind for this coin - it holds hours to "
            f"{_when(top)} for other coins and to {_when(own)} for this one; "
            f"{len(owed)} hour(s) are read again by the next press")
        for d in sorted({h - h % 86400 for h in owed}):
            k = sum(1 for h in owed if h - h % 86400 == d)
            redo.append(f"{sym} {time.strftime('%Y-%m-%d', time.gmtime(d))}: {k} hour(s) "
                        f"Gate has not published for this coin yet, while it has for others")
        return
    log(f"{sym}: Gate stopped publishing this coin after {_when(own)} "
        f"({(top - own) // 3600} hours before the archive's end, {_when(top)}) - "
        f"{len(owed)} hour(s) stay unmeasured")


def _say_absent(sym: str, absent: list, latest, *, top=None, redo=None) -> tuple | None:
    """Name each hour Gate's archive answered 404 for (RCA-2026-10-30-A). One with a LATER
    hour of the same coin published is a hole, final (Oct 08, 2026 06:00 UTC: 05 and 07 are
    there). One the archive holds for ANOTHER coin (`top`, the archive's end) is judged on
    this coin's own newest hour (`_judge_behind`, RCA-2026-10-30-D). One after the archive's
    end is NOT PUBLISHED YET: said plainly, never red - a coin Gate stopped publishing would
    turn every run red for ever - and never final. Returns (newest published hour or None,
    [the days waiting]) or None."""
    holes = sorted(h for h in absent if latest is not None and h < latest)
    later = _later(absent, latest)
    _say_holes(sym, holes)
    if top is not None:
        behind = [h for h in later if h <= top]
        later = [h for h in later if h > top]
        if behind:
            _judge_behind(sym, behind, top, [] if redo is None else redo)
    if not later:
        return None
    days = sorted({h - h % 86400 for h in later})
    since = (f"after the hour starting {_when(latest)}" if latest is not None
             else "for any of the hours asked")
    log(f"{sym}: Gate has published no order-book hour {since}; {len(later)} hour(s) of "
        f"{len(days)} day(s) wait for it - not published by Gate yet")
    return latest, days


if __name__ == "__main__":
    raise SystemExit(main())
