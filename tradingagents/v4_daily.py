"""THE SKILL ROOMS' DAILY REFRESH (Nov 10, 2026): Backtest v4 measured again every day.

The operator, Nov 10, 2026: *"can you deploy this 3 and remove the existing strategy in my auto
trade"*, then *"okay es for this"* to "you want practice to trade these exactly the way their backtest
did, so the forecast's dollars carry over". Spec: docs/superpowers/specs/2026-11-10-skill-rooms-design.md,
"4. The daily refresh" and the goals' "daily agreement check".

Once a UTC day, at or after 00:05 UTC (7:05pm on this PC), so every candle of the day before has
closed. One phase per call of `tick()` (the API supervisor's thread, every `POLL_S`), the state in
`stores.V4.home/daily_state.json`:

  dispatch  .github/workflows/skillbt.yml (`set=daily`) on EVERY account, the PINNED coins dealt
            between them (`cloud_sweep.split_coins`): the coins already in the v4 store - and every
            coin pinned since (`daily_coins.json`), so a coin missing one day never leaves the
            universe - that the exchange still trades. A pinned coin the exchange no longer trades is
            `delisted`, named; a new listing is never added (`not_added`, counted). The deal is saved
            BEFORE the first dispatch and every attempt before its dispatch, so a run GitHub took but
            listed late is adopted (`forecast_v2_daily.dispatch(since=)`). An account refusing twice
            gives the day up, named.
  running   every run polled (`run_status`, `run_words`).
  collect   `acs.collect_skill("daily")` IN ITS OWN PROCESS (the file is ~0.5 GB of JSON, millions of
            trades: never added up inside the API). An account whose results could not be downloaded
            twice gives the day up - the store is never built from part of the market. A green run
            that measured no coin is red: started again once with the same pile, then the day is given
            up. A coin that failed or was not reached is redone ALONE once (`label "... redo"`, never
            between 12:45am and 5:00am), collected through `acs.collect_redo("daily")`; still missing,
            it keeps the line of the file the store was LAST BUILT from (`skilldaily-prev.json`),
            marked `"stale": true` and named, or - with no earlier line - is absent that day, named.
  build     `python -m tradingagents.v4_store build --daily` in its own process, its output appended
            to `daily.log` (the store and Forecast v4, replaced whole). Non-zero: tried again.
  lists     each follower room's switch-on (`forecast_v4.switched_on`, judged at the day's midnight)
            written to the day's list in ONE swap - ONCE: a day's list is never rewritten, because the
            follower may already have traded on it.
  agree     yesterday's practice trades of every follower room against the re-measured backtest
            (`agreement`), saved to `rooms/agree-<YYYY-MM-DD>.json` - never into the follower's own
            state, which another thread writes.

EVERY UTC DAY GETS EXACTLY ONE LIST. The follower holds at the first day with no list, so: a chain
begun for day D first writes a FALLBACK list for every day between the newest list and D that has none
(the PC was off) - a copy of the newest earlier list, `fallback_from` naming the day it really is - and
a day not landed by 06:00 UTC (`GIVE_UP_AT_S`) is given up the same way, said. Nothing here runs under
pytest; a line `[v4-daily] ...` is printed only when the sentence changes.

ONE STEP AT A TIME, ACROSS PROCESSES (final review, Nov 11, 2026): every step and `start_now` hold
`daily.lock` (a file lock, tried once), so a `start_now` typed on the command line and the API's
thread can never both write the state or build twice. A built day's lists may be written up to the
LATER of its own deadline and the next midnight; a check of yesterday still failing once the next
UTC day has begun is ended and named, so it never holds the next day's refresh; and `start_now`
refuses a day whose list is already written. `words()` - what every screen prints - carries the
coins kept stale or absent, a redo refused or skipped, a lost copy, and a step failing right now.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WF = "skillbt.yml"
SET = "daily"
SHARDS = 20                       # machines per ACCOUNT: a free account runs 20 at once
DAY_S = 86_400
DUE_AFTER_S = 5 * 60              # 00:05 UTC: every candle of the day before has closed
GIVE_UP_AT_S = 6 * 3600           # a day not landed by 06:00 UTC is given up with yesterday's list
POLL_S = 120
RETRY_S = 30 * 60
RETRIES = 1                       # an account refusing / a run measuring nothing: asked again this often
BUILD_TIMEOUT_S = 3 * 3600
CHILD_TIMEOUT_S = 2 * 3600
SHORT_LIST = 0.10                 # the exchange listing this much fewer coins than last time is a short answer
CATCH_UP_DAYS = 31                # agreement days checked at most in one pass (the rest are named)
LOG_MAX_BYTES = 10_000_000
IDLE = ("idle", "done", "given_up")
BEFORE_LIST = ("dispatch", "running", "collect", "build", "lists")
BUSY = "a step is already running (another process or thread holds the daily lock)"
_SAID: dict = {"text": None}


# ------------------------------------------------------------------ where things are
def home() -> Path:
    """Backtest v4's folder, resolved at the call (a test moves `stores.V4`)."""
    from tradingagents import stores

    return Path(stores.V4.home)


def state_path() -> Path:
    return home() / "daily_state.json"


def log_path() -> Path:
    return home() / "daily.log"


def coins_path() -> Path:
    """Every coin ever pinned (the v4 store's coins on the first run, never fewer)."""
    return home() / "daily_coins.json"


def work() -> Path:
    p = home() / "daily"
    p.mkdir(parents=True, exist_ok=True)
    return p


@contextlib.contextmanager
def _held():
    """`daily.lock` under Backtest v4's folder, tried once: True while this caller holds it. "Is a
    step running" is a LOCK HELD, never a thread lock (final review, Nov 11, 2026: a `start_now` from
    the command line could not see the API thread's `threading.Lock`, and could overwrite the state
    or start a second build beside it)."""
    from tradingagents import portable

    home().mkdir(parents=True, exist_ok=True)
    with open(home() / "daily.lock", "a+b") as fh:
        try:
            portable.lock_exclusive(fh, blocking=False)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            portable.unlock(fh)


def agree_path(day_s: int) -> Path:
    """The agreement check of the UTC day starting `day_s`, beside the day lists."""
    from tradingagents import v4_follow as vf

    return vf.lists_home() / f"agree-{_iso(day_s)}.json"


def _collected() -> Path:
    from tradingagents import acs

    return acs.home() / f"{acs.SKILL_PREFIX[SET]}.json"


def _prev() -> Path:
    """The collected file the store was LAST BUILT from - a missing coin's stale lines come from here."""
    from tradingagents import acs

    return acs.home() / f"{acs.SKILL_PREFIX[SET]}-prev.json"


def _iso(day_s: int) -> str:
    return dt.datetime.fromtimestamp(int(day_s), dt.timezone.utc).date().isoformat()


def _said(iso: str) -> str:
    """A day's name ("2026-11-10", the files' own) as a sentence prints it: its UTC midnight in the
    one date format, as the follower says "waiting for the list of ..."."""
    from tradingagents import v4_follow as vf

    d = vf._day_of(str(iso))
    return _when(d) if d is not None else str(iso)


def _midnight(now_s: float) -> int:
    return int(now_s) // DAY_S * DAY_S


def _bare(sym: str) -> str:
    s = str(sym)
    return s[: -len("_USDT")] if s.endswith("_USDT") else s


def _owner(repo: str) -> str:
    return str(repo).split("/")[0]


def _fd():
    from tradingagents import forecast_v2_daily as fd

    return fd


def _when(ts: float) -> str:
    from tradingagents.positions_view import fmt_when

    return fmt_when(float(ts))


# ------------------------------------------------------------------ the state
def _load() -> tuple[dict | None, str | None]:
    """(state, None), or (None, why) when the file EXISTS but cannot be read. A missing file is a
    chain that never ran; an unreadable one is NAMED and never overwritten - reading it as "idle"
    would start a new day's chain and dispatch every account's machines again."""
    p = state_path()
    if not p.exists():
        return {"phase": "idle"}, None
    # NEVER THE FILE'S PATH in what a screen prints (final review, Nov 11, 2026): the reason only;
    # the log line and a command-line start_now add where the file is (`_where`)
    try:
        st = json.loads(p.read_text(encoding="utf-8"))
    except OSError as exc:
        return None, f"the record cannot be read ({type(exc).__name__}: {exc.strerror or exc.errno})"
    except ValueError as exc:
        return None, f"the record cannot be read ({type(exc).__name__}: {str(exc)[:160]})"
    if not isinstance(st, dict):
        return None, f"the record cannot be read (it holds a {type(st).__name__}, not a state)"
    return st, None


def _stopped(bad: str) -> str:
    return (f"the daily refresh is stopped: {bad} - it is never overwritten; repair it, or move it aside to "
            f"start clean")


def _where() -> str:
    """Where the daily refresh's record is - for the log and the command line, never a screen."""
    return f" (the file is {state_path()})"


def read() -> dict:
    st, bad = _load()
    if bad:
        return {"phase": "unreadable", "why": _stopped(bad), "error": bad}
    return st


def _write(st: dict) -> None:
    from tradingagents import forecast_v2 as f2

    f2.publish(state_path(), json.dumps(st, separators=(",", ":"), allow_nan=False))


def _say(st: dict, why: str) -> None:
    """Where the chain is, ON DISK before a slow step."""
    st["why"] = why
    try:
        _write(st)
    except OSError as exc:
        print(f"[v4-daily] could not save the status: {exc!r}", flush=True)


def _tried(st: dict, what: str, now: float) -> float | None:
    """When an earlier attempt at THIS dispatch was made - saved ON DISK BEFORE the dispatch, so a
    run GitHub took but listed late is adopted on the retry, never started twice."""
    was = dict(st.get("tried") or {})
    since = was.get(what)
    was[what] = since or now
    st["tried"] = was
    _write(st)
    return since


# ------------------------------------------------------------------ is it due
def due(now_s: float, st: dict | None = None) -> bool:
    """True once a UTC day, at or after 00:05 UTC, until a chain for that day has begun."""
    st = read() if st is None else st
    day_s = _midnight(now_s)
    if now_s < day_s + DUE_AFTER_S:
        return False
    return st.get("day") != _iso(day_s)


# ------------------------------------------------------------------ the pinned universe
def _store_coins(db: Path | None = None) -> set:
    from tradingagents import v4_store

    p = Path(db) if db else v4_store.db_path()
    if not p.exists():
        return set()
    con = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True, timeout=30)
    try:
        return {str(r[0]) for r in con.execute("SELECT DISTINCT coin FROM strat")}
    finally:
        con.close()


def _saved_coins() -> dict:
    try:
        got = json.loads(coins_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def _pinned() -> set:
    """The store's coins and every coin pinned before: a coin absent from one day's store (it failed
    and had no earlier line) stays in the universe and is measured again the next day; a delisted
    one stays too, named every day it is not traded, and is measured again if it comes back."""
    return set(_saved_coins().get("coins") or []) | _store_coins()


def _deal(st: dict) -> None:
    """Who measures what, saved before any dispatch."""
    from tradingagents import cloud_sweep as cs

    fd = _fd()
    ready, refused = fd.fleets_now()
    if not ready:
        raise RuntimeError("no GitHub account can run it: " + ("; ".join(refused) or "none found"))
    market = {_bare(s) for s in fd.market()}
    if not market:
        raise RuntimeError("the exchange's coin list came back empty")
    saved = _saved_coins()
    was = int(saved.get("market_n") or 0)
    if was and len(market) < (1 - SHORT_LIST) * was:
        # an exchange that answered with half its list is a short answer, not hundreds of delistings
        raise RuntimeError(f"the exchange listed {len(market):,} coins against {was:,} last time - read as a "
                           f"short list, not delistings")
    pinned = _pinned()
    if not pinned:
        raise RuntimeError("no pinned coin: the Backtest v4 store holds none")
    coins = sorted(pinned & market)
    if not coins:
        raise RuntimeError(f"none of the {len(pinned):,} pinned coins is on the exchange's list")
    delisted = sorted(pinned - market)
    from tradingagents import forecast_v2 as f2

    f2.publish(coins_path(), json.dumps({"coins": sorted(pinned), "market_n": len(market),
                                         "made_s": int(time.time())}))
    deal = {repo: list(pile) for repo, pile in zip(ready, cs.split_coins(coins, len(ready)), strict=False)
            if pile}                  # an EMPTY coin_list is the whole market to the shard: never sent
    st.update(deal=deal, refused=list(refused), pinned=len(pinned), coins=len(coins), delisted=delisted,
              not_added=len(market - pinned))
    _write(st)


def _label(st: dict, redo: bool = False) -> str:
    return f"v4 daily {st['day']}" + (" redo" if redo else "")


def _inputs(coins: list, label: str, few: bool = False) -> dict:
    """skillbt.yml's four inputs. `few`: a redo of a handful of coins asks no more machines than coins."""
    shards = max(1, min(SHARDS, len(coins))) if few else SHARDS
    return {"shards": str(shards), "coin_list": ",".join(coins), "label": label, "set": SET}


# ------------------------------------------------------------------ the day lists
def _list_days() -> list[int]:
    from tradingagents import v4_follow as vf

    try:
        names = [p.stem for p in vf.lists_home().glob("*.json")]
    except OSError:
        return []
    return sorted(d for d in (vf._day_of(n) for n in names) if d is not None)


def _fallback(day_s: int, now: float) -> dict | None:
    """Day `day_s`'s list as a copy of the newest earlier list, `fallback_from` naming the day it
    really is. None when the day already has a list (never rewritten)."""
    from tradingagents import forecast_v2 as f2
    from tradingagents import v4_follow as vf

    path = vf.list_path(day_s)
    if path.exists():
        return None
    src_day = src = None
    for d in reversed([d for d in _list_days() if d < day_s]):
        try:
            got = json.loads(vf.list_path(d).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue                       # unreadable: the one before it
        if isinstance(got, dict) and isinstance(got.get("rooms", {}), dict):
            src_day, src = d, got
            break
    if src is None:
        return {"day": _iso(day_s), "from": None}
    origin = src.get("fallback_from") or _iso(src_day)
    doc = {"day": _iso(day_s), "day_s": int(day_s), "made_s": now, "fallback_from": origin,
           "copied_from": _iso(src_day), "rooms": src.get("rooms") or {}}
    f2.publish(path, json.dumps(doc))
    return {"day": _iso(day_s), "from": origin}


def _fill_gaps(day_s: int, now: float) -> list[dict]:
    """A fallback list for every day between the newest earlier list and `day_s` that has none."""
    earlier = [d for d in _list_days() if d < day_s]
    if not earlier:
        return []
    out = []
    for d in range(earlier[-1] + DAY_S, int(day_s), DAY_S):
        got = _fallback(d, now)
        if got:
            out.append(got)
    return out


# ------------------------------------------------------------------ the chain
def _begin(st: dict, now: float, deadline: float, manual: bool = False) -> None:
    day_s = _midnight(now)
    last = ({k: st.get(k) for k in ("day", "phase", "why", "landed_s", "agree") if st.get(k) is not None}
            if st.get("day") else st.get("last"))
    st.clear()
    st.update(day=_iso(day_s), day_s=day_s, phase="dispatch", started_at=now, deadline_s=float(deadline),
              manual=bool(manual), runs={}, tries={}, tried={}, redo={}, collect={}, polled_at=0, failed_at=0,
              error="", missing=[], stale={}, failed=[], delisted=[], fallbacks=[], last=last)
    st["fallbacks"] = _fill_gaps(day_s, now)
    gaps = [_said(f["day"]) for f in st["fallbacks"]]
    st["why"] = (f"the refresh of {_when(day_s)} started at {_when(now)}"
                 + (f"; the missed day(s) {', '.join(gaps)} got a copy of the list before them" if gaps else ""))
    _write(st)


def _fail(st: dict, now: float, why: str) -> None:
    st["error"] = f"{st.get('phase', 'idle')}: {why}"
    st["failed_at"] = now
    st["why"] = (f"the {st.get('phase', 'idle')} step failed at {_when(now)} - tried again after "
                 f"{RETRY_S // 60} minutes: {why}")


def _give_up(st: dict, now: float, why: str) -> None:
    """The day ends NAMED; its list is a copy of the newest earlier one, said."""
    phase = st.get("phase")
    got = _fallback(int(st["day_s"]), now)
    if got is None:
        said = "its list had already been written and is kept"
    elif got["from"] is None:
        said = "there is no earlier list to copy, so the rooms wait for tomorrow's"
    else:
        said = f"today's list is a copy of the list of {_said(got['from'])}"
        st.setdefault("fallbacks", []).append(got)
    st.update(phase="given_up", failed_at=0, done_at=now, error=f"{phase}: {why}")
    st["why"] = f"the refresh of {_when(int(st['day_s']))} was given up ({why}); {said}"


def _dispatch(st: dict, now: float) -> None:
    from tradingagents import cloud_sweep as cs
    from tradingagents import cq_search

    if cq_search.quiet_hours(now):
        st["why"] = "waiting: no press between 12:45am and 5:00am (the nightly jobs' hours)"
        return
    if not st.get("deal"):
        _deal(st)
    fd = _fd()
    runs, tries, errors = st.setdefault("runs", {}), st.setdefault("tries", {}), []
    for repo, pile in st["deal"].items():
        if repo in runs:
            continue
        try:
            # THE SAME CODE ON EVERY ACCOUNT, or the halves are not one measurement
            drift = cs.sync_fleet(repo)
            if drift:
                raise RuntimeError(drift)
            runs[repo] = fd.dispatch(WF, _inputs(pile, _label(st)), repo,
                                     since=_tried(st, f"dispatch {st['day']} {repo}", now))
            _write(st)
        except Exception as exc:                                       # noqa: BLE001
            tries[repo] = int(tries.get(repo, 0)) + 1
            _write(st)
            errors.append(f"{_owner(repo)}: {type(exc).__name__}: {str(exc)[:160]}")
    if errors:
        if any(int(n) > RETRIES for n in tries.values()):
            _give_up(st, now, f"an account refused the backtest {RETRIES + 1} times ({'; '.join(errors)})")
            return
        raise RuntimeError(f"the backtest was refused - tried again in {RETRY_S // 60} minutes "
                           f"({'; '.join(errors)})")
    st.update(phase="running", error="", failed_at=0,
              why=f"measuring {st.get('coins', 0):,} coins on GitHub: "
                  + ", ".join(f"run {r} on {_owner(repo)}" for repo, r in runs.items()))


def _running(st: dict, now: float) -> None:
    fd = _fd()
    runs = dict(st.get("runs") or {})
    stat = {repo: fd.run_status(int(run), repo) for repo, run in runs.items()}
    if any(s.get("status") != "completed" for s in stat.values()):
        st["why"] = "; ".join(f"run {runs[repo]} on {_owner(repo)}: "
                              + ("finished" if s.get("status") == "completed" else fd.run_words(s))
                              for repo, s in stat.items())
        return
    st["ended"] = {repo: s.get("conclusion") for repo, s in stat.items()}
    st.update(phase="collect", collect={}, error="", failed_at=0,
              why="every account's run finished - collecting the results")


def _acs_state(st: dict, runs: dict, piles: dict, redo: bool) -> None:
    """The state `acs.collect_skill` / `acs.collect_redo` read, in `acs.dispatch`'s shape."""
    from tradingagents import acs

    label = _label(st, redo)
    state = {"label": label, "plan_id": "", "started_s": int(st.get("started_at") or 0),
             "coins": sum(len(piles[r]) for r in runs), "set": SET, "refused": list(st.get("refused") or []),
             "runs": {repo: {"repo": repo, "run": int(run), "coin_list": list(piles[repo]), "label": label}
                      for repo, run in runs.items()}}
    (acs.home() / acs._state_name(True, redo, SET)).write_text(json.dumps(state, indent=1), encoding="utf-8")


def _zero(st: dict, now: float, empty: list) -> None:
    """Runs that delivered no coin (green with nothing measured, or red with nothing to download):
    started again with the same pile, once. What is still to start is SAVED before each dispatch, so a
    dispatch that raises is retried - adopting a run GitHub listed late - without collecting again."""
    from tradingagents import cq_search

    fd = _fd()
    zero = st.setdefault("redo", {}).setdefault("zero", {})
    c = st.setdefault("collect", {})
    if not c.get("zero_pending"):
        for repo in empty:
            if int(zero.get(repo, 0)) >= RETRIES:
                _give_up(st, now, f"run {st['runs'][repo]} on {_owner(repo)} finished but measured no coin, "
                                  f"on every try")
                return
        c.clear()
        c.update(zero_pending=list(empty), zero_said=[])
        _write(st)
    if cq_search.quiet_hours(now):
        st["why"] = (f"run(s) on {', '.join(_owner(r) for r in c['zero_pending'])} measured no coin - started "
                     f"again after 5:00am (no press between 12:45am and 5:00am)")
        return
    for repo in list(c["zero_pending"]):
        old = st["runs"][repo]
        st["runs"][repo] = fd.dispatch(WF, _inputs(st["deal"][repo], _label(st)), repo,
                                       since=_tried(st, f"zero {old}", now))
        zero[repo] = int(zero.get(repo, 0)) + 1
        st.setdefault("replaced", {})[str(old)] = st["runs"][repo]
        c["zero_pending"].remove(repo)
        c["zero_said"].append(f"run {old} on {_owner(repo)} finished but measured no coin - started again as "
                              f"run {st['runs'][repo]}")
        _write(st)
    st.update(phase="running", collect={}, why="; ".join(c["zero_said"]))


def _collect(st: dict, now: float) -> None:
    from tradingagents import cq_search

    c = st.setdefault("collect", {})
    if c.get("zero_pending"):
        _zero(st, now, [])
        return
    if "got" not in c:
        _acs_state(st, st["runs"], st["deal"], redo=False)
        _say(st, "downloading every account's results and adding them up on this PC (in its own process)")
        t0 = _mono()
        got = _child("collect", {})
        if now + (_mono() - t0) >= _deadline(st, now):
            # the collect held this thread past 06:00: no redo is sent for a day already lost
            _give_up(st, now + (_mono() - t0), f"it had not landed by {_when(_deadline(st, now))}")
            return
        lost = {s.split(": ")[0]: s for s in got.get("downloads_failed") or []}
        ended = st.get("ended") or {}
        # a run that ended RED with nothing to download measured nothing: it gets the one redo below;
        # a GREEN run whose download failed is the network, collected again
        red_lost = [r for r in lost if ended.get(r) not in (None, "success")]
        green_lost = [s for r, s in lost.items() if r not in red_lost]
        if green_lost:
            dl = st.setdefault("dl_tries", {})
            for s in green_lost:
                repo = s.split(": ")[0]
                dl[repo] = int(dl.get(repo, 0)) + 1
            if any(int(n) > RETRIES for n in dl.values()):
                _give_up(st, now, f"an account's results could not be downloaded {RETRIES + 1} times "
                                  f"({'; '.join(green_lost)}) - the store is never built from part of the market")
                return
            raise RuntimeError(f"an account's results could not be downloaded ({'; '.join(green_lost)})")
        unreached = set(got.get("not_reached") or [])
        empty = [repo for repo, pile in st["deal"].items()
                 if repo in st["runs"] and pile and (set(pile) <= unreached or repo in red_lost)]
        if empty:
            _zero(st, now, empty)
            return
        to_redo = sorted(set(got.get("failed_coins") or []) | unreached)
        c.update(got={k: got.get(k) for k in ("lines", "coins", "skipped_n")}, to_redo=to_redo)
        st["failed"] = list(got.get("failed") or [])
        if not to_redo:
            st.update(phase="build", missing=[], stale={}, error="", failed_at=0,
                      why=f"collected {got.get('lines', 0):,} coin-timeframes of {got.get('coins', 0):,} coins - "
                          f"building the store next")
            return
        st["why"] = (f"{len(to_redo)} coin(s) failed or were not reached ({', '.join(to_redo[:10])}"
                     f"{' ...' if len(to_redo) > 10 else ''}) - redone alone next")
        return
    to_redo = list(c.get("to_redo") or [])
    if "redo_pending" not in c:
        # THE DEAL IS SAVED BEFORE ANY DISPATCH, like the day's own: a restart during a dispatch's
        # 90-second wait finds what is still to start, and its retry adopts a run GitHub listed late
        from tradingagents import cloud_sweep as cs

        repos = [r for r in st["deal"] if r in st["runs"]]
        c.update(redo_pending={repo: list(pile) for repo, pile in
                               zip(repos, cs.split_coins(to_redo, len(repos)), strict=False)
                               if pile},           # an EMPTY coin_list is the whole market: never sent
                 redo_runs={}, redo_piles={}, redo_tries={})
        _write(st)
    pend = c["redo_pending"]
    if pend and cq_search.quiet_hours(now):
        c["redo_skipped"] = (f"{sum(len(p) for p in pend.values())} coin(s) not redone "
                             f"({', '.join(sorted(x for p in pend.values() for x in p)[:10])}): no press between "
                             f"12:45am and 5:00am (the nightly jobs' hours)")
        pend.clear()
        _write(st)
    if pend:
        fd = _fd()
        errors = []
        for repo, pile in list(pend.items()):
            try:
                c["redo_runs"][repo] = fd.dispatch(WF, _inputs(pile, _label(st, True), few=True), repo,
                                                   since=_tried(st, f"redo {st['day']} {repo}", now))
                c["redo_piles"][repo] = list(pile)
                del pend[repo]
            except Exception as exc:                                   # noqa: BLE001
                n = c["redo_tries"][repo] = int(c["redo_tries"].get(repo, 0)) + 1
                said = f"{_owner(repo)}: {type(exc).__name__}: {str(exc)[:160]}"
                if n > RETRIES:          # refused twice: named, its coins keep yesterday's line or are absent
                    c.setdefault("redo_refused", []).append(
                        f"{said} - {len(pile)} coin(s) not redone ({', '.join(pile[:10])})")
                    del pend[repo]
                else:
                    errors.append(said)
            _write(st)
        if pend:
            raise RuntimeError(f"the redo was refused - tried again in {RETRY_S // 60} minutes "
                               f"({'; '.join(errors)})")
        if c["redo_runs"]:
            st["why"] = (f"redoing {len(to_redo)} coin(s) alone: "
                         + ", ".join(f"run {r} on {_owner(repo)}" for repo, r in c["redo_runs"].items())
                         + _notes(st))
            return
    if c["redo_runs"] and not c.get("redo_finished"):
        fd = _fd()
        stat = {repo: fd.run_status(int(run), repo) for repo, run in c["redo_runs"].items()}
        if any(s.get("status") != "completed" for s in stat.values()):
            st["why"] = "; ".join(f"redo run {c['redo_runs'][repo]} on {_owner(repo)}: "
                                  + ("finished" if s.get("status") == "completed" else fd.run_words(s))
                                  for repo, s in stat.items())
            return
        c["redo_finished"] = True
        _acs_state(st, c["redo_runs"], c["redo_piles"], redo=True)
    _say(st, f"adding up the redo of {len(to_redo)} coin(s) and keeping yesterday's line for any still missing "
             f"(in its own process)")
    got = _child("finish", {"redo": bool(c["redo_runs"]), "prev": str(_prev())})
    c["finish"] = {k: got.get(k) for k in ("redo_error", "lines")}
    st.update(phase="build", failed=list(got.get("failed") or []), missing=list(got.get("absent") or []),
              stale=dict(got.get("stale") or {}), error="", failed_at=0,
              redo_refused=list(c.get("redo_refused") or []), redo_skipped=c.get("redo_skipped") or "",
              redo_error=got.get("redo_error") or "")
    st["why"] = "collected - building the store next" + _notes(st)


def _notes(st: dict) -> str:
    """What today's store is missing or carried, said in every sentence after the collect: the
    coins kept stale or absent, a redo refused or skipped, a kept copy that failed."""
    c = st.get("collect") or {}
    bits = []
    if st.get("stale"):
        bits.append(f"{len(st['stale'])} coin(s) keep yesterday's line, marked stale "
                    f"({', '.join(sorted(st['stale'])[:10])})")
    if st.get("missing"):
        bits.append(f"{len(st['missing'])} coin(s) absent today ({', '.join(st['missing'][:10])})")
    for r in st.get("redo_refused") or c.get("redo_refused") or []:
        bits.append(f"redo refused twice on {r}")
    if st.get("redo_skipped") or c.get("redo_skipped"):
        bits.append(st.get("redo_skipped") or c.get("redo_skipped"))
    if st.get("redo_error"):
        bits.append(f"the redo could not be collected: {st['redo_error']}")
    if st.get("prev_error"):
        bits.append(st["prev_error"])
    if st.get("picker_error"):
        bits.append(st["picker_error"])
    return (" - note: " + "; ".join(bits)) if bits else ""


def _build(st: dict, now: float) -> None:
    _say(st, "building the Backtest v4 store and Forecast v4 from today's results (in its own process)")
    log = log_path()
    _rotate(log)
    t0 = _mono()
    with log.open("a", encoding="utf-8") as fh:
        fh.write(f"--- {_when(time.time())}: the daily build of {_said(st['day'])} ---\n")
        fh.flush()
        got = _spawn([sys.executable, "-m", "tradingagents.v4_store", "build", "--daily"], stdout=fh,
                     stderr=subprocess.STDOUT, timeout=BUILD_TIMEOUT_S, cwd=str(ROOT),
                     env={**os.environ, "PYTHONUNBUFFERED": "1"})
    after = now + (_mono() - t0)         # the build holds this thread for up to 3 hours
    if got.returncode != 0:
        why = f"the build ended {got.returncode}: {_tail(log)}"
        if after >= _deadline(st, now):  # no second try after 06:00: the day takes the earlier list now
            _give_up(st, after, why)
            return
        raise RuntimeError(why)
    st["built_day"] = st["day"]          # from here the 06:00 cut-off no longer applies to this day's lists
    try:
        _keep_prev()
        st.pop("prev_error", None)
    except OSError as exc:          # never a reason to build the store again: named instead
        st["prev_error"] = (f"the collected file could not be kept for tomorrow ({type(exc).__name__}: {exc}); "
                            f"a coin missing tomorrow will be absent rather than stale")
    st.update(phase="lists", built_s=time.time(), error="", failed_at=0)
    st["why"] = "the store and Forecast v4 are rebuilt - switching on each room's strategies next" + _notes(st)


def _pick(st: dict, now: float) -> None:
    """The daily picker (`v4_picker`, Nov 12, 2026): which rule set each room follows today. Its
    failure never stops the day's list - the rooms keep the rules they follow - and is named."""
    st.pop("picker_error", None)
    try:
        from tradingagents import v4_picker as vp

        res = vp.pick(now)
        st["picker_note"] = (res.get("skipped") or
                             ("; ".join(x["text"] for x in res.get("log") or []) or "every room keeps its rule"))
    except Exception as exc:        # noqa: BLE001 - never a reason to lose the day's list
        st["picker_error"] = f"the picker could not run ({type(exc).__name__}: {exc}); every room keeps its rule"


def _lists(st: dict, now: float) -> None:
    from tradingagents import forecast_v2 as f2
    from tradingagents import forecast_v4 as f4
    from tradingagents import profiles
    from tradingagents import v4_follow as vf

    day_s = int(st["day_s"])
    path = vf.list_path(day_s)
    counts = {}
    if path.exists():
        st["list_note"] = f"the list of {_when(day_s)} had already been written and is kept as it is"
    else:
        rooms = {}
        _pick(st, now)                  # BEFORE the list: the day's list is judged by the rules just chosen
        for pid in vf.rooms():
            _say(st, f"switching on {profiles.rule_name(pid)}'s strategies for {_when(day_s)}")
            # a slot the picker switched off opens nothing; a trade it holds is finished by the follower
            rooms[pid] = [] if profiles.picker_off(pid) else f4.switched_on(profiles.v4_rule(pid), day_s)
        if path.exists():               # never rewritten, even by a race
            st["list_note"] = f"the list of {_when(day_s)} had already been written and is kept as it is"
        else:
            f2.publish(path, json.dumps({"day": st["day"], "day_s": day_s, "made_s": now, "fallback_from": None,
                                         "rooms": rooms}))
            counts = {pid: len(r) for pid, r in rooms.items()}
    st.update(phase="agree", landed_s=now, counts=counts, error="", failed_at=0,
              why=(f"the list of {_when(day_s)} landed at {_when(now)}: "
                   + (", ".join(f"{profiles.name_of(p)} {n}" for p, n in counts.items()) + " switched on"
                      if counts else st.get("list_note", ""))
                   + (f" - picker: {st['picker_note']}" if st.get("picker_note") else "")
                   + " - checking yesterday next" + _notes(st)))


def _agreed_days() -> list[int]:
    """The days an agreement file exists for, oldest first."""
    from tradingagents import v4_follow as vf

    try:
        names = [p.stem[len("agree-"):] for p in vf.lists_home().glob("agree-*.json")]
    except OSError:
        return []
    return sorted(d for d in (vf._day_of(n) for n in names) if d is not None)


def _agree(st: dict, now: float) -> None:
    """Yesterday's check - and every day after the newest check up to yesterday that was missed (the
    PC off, a day given up), one file each, at most CATCH_UP_DAYS."""
    from tradingagents import forecast_v2 as f2
    from tradingagents import profiles
    from tradingagents import v4_follow as vf

    y = int(st["day_s"]) - DAY_S
    done = [d for d in _agreed_days() if d < y]
    first = done[-1] + DAY_S if done else y
    skipped = max(0, (y - first) // DAY_S + 1 - CATCH_UP_DAYS)
    days = list(range(max(first, y - (CATCH_UP_DAYS - 1) * DAY_S), y + DAY_S, DAY_S))
    lists = _DayLists()
    out = {}
    for d in days:
        out = {}
        for pid in vf.rooms():
            try:
                out[pid] = agreement(pid, d, lists=lists)
            except Exception as exc:                                   # noqa: BLE001
                out[pid] = {"day": _iso(d), "day_s": d, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
        f2.publish(agree_path(d), json.dumps(out))
    st["agreed_days"] = [_iso(d) for d in days]
    st["agree"] = {pid: {k: r[k] for k in ("same", "of", "dollars_apart", "error") if k in r}
                   for pid, r in out.items()}
    words = [f"{profiles.name_of(p)} {r['same']} of {r['of']} the same (${r['dollars_apart']:.2f} apart)"
             if "error" not in r else f"{profiles.name_of(p)} not checked: {r['error']}" for p, r in out.items()]
    caught = (f"; {len(days) - 1} earlier day(s) checked too" if len(days) > 1 else "") + (
        f"; {skipped} day(s) before {_when(days[0])} were not checked" if skipped else "")
    st.update(phase="done", done_at=now, error="", failed_at=0,
              why=f"the list of {_when(int(st['day_s']))} landed at {_when(float(st.get('landed_s') or now))}; "
                  f"yesterday's closed trades: " + "; ".join(words) + caught + _notes(st))


_PHASES = {"dispatch": _dispatch, "running": _running, "collect": _collect, "build": _build,
           "lists": _lists, "agree": _agree}


def _step(st: dict, now: float) -> None:
    phase = st.get("phase") or "idle"
    if phase not in IDLE and phase not in _PHASES:
        phase = st["phase"] = "idle"           # a state no step knows: start clean
    if phase in IDLE:
        if due(now, st):
            _begin(st, now, _midnight(now) + GIVE_UP_AT_S)
        elif not st.get("why"):
            st["why"] = f"the next refresh starts at {_when(_next_due(now))}"
        return
    # the deadline before the retry wait: a step that failed at 5:50am is not left waiting past 6:00am.
    # A store BUILT for this day writes its real lists whenever the build ends - only a list that
    # cannot be worked out by the next midnight gives the day up (the next day's chain needs the turn)
    deadline = _deadline(st, now)
    day_end = int(st.get("day_s") or _midnight(now)) + DAY_S
    if phase == "lists" and st.get("built_day") == st.get("day"):
        # the LATER of the two (final review, Nov 11, 2026): a late `start_now` carries its own
        # deadline past midnight, and replacing it with midnight gave up a good build's lists
        deadline = max(deadline, day_end)
    if phase in BEFORE_LIST and now >= deadline:
        _give_up(st, now, f"it had not landed by {_when(deadline)}")
        return
    if phase == "agree" and st.get("failed_at") and now >= day_end:
        _end_agree(st, now, day_end)
        return
    if st.get("failed_at") and now - float(st["failed_at"]) < RETRY_S:
        return
    if now - float(st.get("polled_at") or 0) < POLL_S:
        return
    st["polled_at"] = now
    _PHASES[phase](st, now)


def _end_agree(st: dict, now: float, day_end: int) -> None:
    """The check of yesterday still failing when the next UTC day has begun: the step ENDS - the day
    is done, its list long landed - and the reason is named, so the next day's refresh is never held
    behind a check (final review, Nov 11, 2026)."""
    err = str(st.get("error") or "it had not finished")
    err = err[len("agree: "):] if err.startswith("agree: ") else err
    st.update(phase="done", done_at=now, failed_at=0, error="", agree_error=f"{err} - given up at {_when(day_end)}")
    st["why"] = (f"the list of {_when(int(st['day_s']))} landed at {_when(float(st.get('landed_s') or now))}; "
                 f"yesterday's check could not be made ({st['agree_error']})" + _notes(st))


def _deadline(st: dict, now: float) -> float:
    return float(st.get("deadline_s") or (int(st.get("day_s") or _midnight(now)) + GIVE_UP_AT_S))


def _next_due(now: float) -> float:
    d = _midnight(now)
    return d + DUE_AFTER_S if now < d + DUE_AFTER_S else d + DAY_S + DUE_AFTER_S


def tick(now: float | None = None) -> dict:
    """The supervisor's call, in its own thread: at most one phase. Nothing under pytest."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return {"why": "never under a test run"}
    return _tick(now)


def _tell(why: str) -> None:
    if why and why != _SAID["text"]:
        _SAID["text"] = why
        print(f"[v4-daily] {why}", flush=True)


def _tick(now: float | None = None) -> dict:
    with _held() as ok:
        if not ok:
            return {"why": BUSY}
        now = time.time() if now is None else float(now)
        st, bad = _load()
        if bad:                         # named once, nothing done, the file left exactly as it is
            _tell(_stopped(bad) + _where())
            return {"phase": "unreadable", "why": _stopped(bad)}
        try:
            _step(st, now)
        except Exception as exc:                                       # noqa: BLE001
            _fail(st, now, f"{type(exc).__name__}: {str(exc)[:300]}")
        _write(st)
        _tell(st.get("why") or "")
        return {"phase": st.get("phase"), "why": st.get("why", "")}


def start_now(now: float | None = None) -> dict:
    """Today's chain at once, whatever `due()` says - the first refresh. Never between 12:45am and
    5:00am, never over a chain already under way, never while another process holds the daily lock,
    and never for a day whose list already exists (a day's list is never written twice, so a refresh
    could only measure the whole market and change nothing). Its deadline is six hours from now (a
    first refresh started late is not given up at 06:00 UTC); the dispatch is the next tick's."""
    from tradingagents import cq_search
    from tradingagents import v4_follow as vf

    now = time.time() if now is None else float(now)
    if cq_search.quiet_hours(now):
        raise RuntimeError("no press between 12:45am and 5:00am (the nightly jobs' hours)")
    with _held() as ok:
        if not ok:
            raise RuntimeError(f"the daily refresh is in the middle of a step ({BUSY}); ask again in a minute")
        st, bad = _load()
        if bad:
            raise RuntimeError(_stopped(bad) + _where())
        if (st.get("phase") or "idle") not in IDLE:
            raise RuntimeError(f"the refresh of {_said(st.get('day'))} is already under way ({st.get('phase')}): "
                               f"{st.get('why', '')}")
        day_s = _midnight(now)
        path = vf.list_path(day_s)
        if path.exists():
            raise RuntimeError(_list_exists(day_s, path))
        _begin(st, now, max(day_s + GIVE_UP_AT_S, now + GIVE_UP_AT_S), manual=True)
    return status()


def _list_exists(day_s: int, path: Path) -> str:
    """Why `start_now` refuses a day whose list is already written - with the day and when, in the
    one date format, never the file's name."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc = doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        doc = {}
    made = f" at {_when(float(doc['made_s']))}" if doc.get("made_s") else ""
    copy = (f", as a copy of the list of the day that began {_said(doc['fallback_from'])}"
            if doc.get("fallback_from") else "")
    return (f"today's list (the day that began {_when(day_s)}) was already written{made}{copy}; a day's list "
            f"is never written twice, so a refresh now would measure the whole market and change nothing")


# ------------------------------------------------------------------ the agreement check
class _DayLists:
    """The day lists, each read once per agreement pass and shared by the rooms and the days."""

    def __init__(self):
        self._docs: dict = {}
        self._days: list | None = None

    def days(self) -> list[int]:
        if self._days is None:
            self._days = _list_days()
        return self._days

    def ids(self, day_s: int, pid: str) -> dict:
        """{id: row} switched on in room `pid` on the UTC day starting `day_s` ({} when it has no list)."""
        from tradingagents import v4_follow as vf

        day_s = int(day_s)
        if day_s not in self._docs:
            try:
                doc = json.loads(vf.list_path(day_s).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                doc = {}
            self._docs[day_s] = doc if isinstance(doc, dict) else {}
        rooms = self._docs[day_s].get("rooms")
        return {str(r["id"]): r for r in ((rooms if isinstance(rooms, dict) else {}).get(pid) or [])
                if isinstance(r, dict) and r.get("id")}

    def ever(self, pid: str, upto_s: int) -> dict:
        """Every strategy room `pid` had switched on on any day up to `upto_s`."""
        out: dict = {}
        for d in self.days():
            if d <= upto_s:
                out.update(self.ids(d, pid))
        return out


def agreement(pid: str, day_s: int, db: Path | None = None, lists: _DayLists | None = None) -> dict:
    """Room `pid`'s practice trades that CLOSED on the UTC day `day_s` against the re-measured
    backtest's trades that closed that day - judged by the day a trade CLOSED, so a trade held over
    midnight, a 1d trade and the day's last candles are all compared once, on the day they end.

    Practice: the room's exit rows (strategy v4_*) whose exit CANDLE closed in
    (day_s, day_s + 1 day], whatever day they opened - a row the minutes settled carries that candle
    (`v4_candle`, its `ts` being the minute inside it); an older row's `ts` is the candle's close.
    Backtest: the store's trades with
    `ex + bar` in that window and why != END, kept only when the strategy was on the day list of its
    OWN entry day (`en`'s UTC day) - the day lists read back as far as they go; a strategy not
    switched on when the trade opened was never expected to take it.

    A pair is THE SAME when strategy id, side, entry candle (`entry_ts == en`), exit candle
    (`ts - bar == ex`) and exit reason all match; `dollars_apart` adds |practice - backtest| over
    those, to the cent. `of` counts the trades either side closed that day (a pair once); every trade
    that is not the same is listed - practice's by trade id, the backtest's by strategy id and entry."""
    import tradingagents.auto_trader as at
    from tradingagents import backtest_report as br
    from tradingagents import profiles, v4_store

    day_s = int(day_s)
    end = day_s + DAY_S
    end_code = v4_store.WHYS.index("END")
    lists = lists or _DayLists()
    ever = lists.ever(pid, day_s)                     # a trade closing today opened today or before
    with profiles.using(pid):
        rows = at.ledger_trades(day_s)
    # widened by a day each way: a minute exit's `ts` lies inside its candle, so the candle's own close
    # (known once the strategy's timeframe is) decides which day it belongs to
    exits = [r for r in rows if r.get("action") == "exit" and str(r.get("strategy") or "").startswith("v4_")
             and day_s - DAY_S < int(r.get("ts") or 0) <= end + DAY_S]

    def rid_of(r) -> str:
        return str(r.get("v4_id") or str(r.get("strategy"))[3:])

    ids = set(ever) | {rid_of(r) for r in exits}
    p = Path(db) if db else v4_store.db_path()
    con = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True, timeout=30)
    tf_of, by_sid = {}, {}
    trades = []
    try:
        idl = sorted(ids)
        for i in range(0, len(idl), 900):
            part = idl[i:i + 900]
            for sid, rid, tf in con.execute(f"SELECT sid, id, tf FROM strat WHERE id IN ({','.join('?' * len(part))})",
                                            part):
                tf_of[rid] = tf
                if rid in ever:
                    by_sid[int(sid)] = rid
        sl = sorted(by_sid)
        for i in range(0, len(sl), 900):
            part = sl[i:i + 900]
            # the exit candle OPENS at most one 1d candle before the window (trade_ex serves it)
            trades += con.execute(f"SELECT sid, ex, en, side, why, pnl FROM trade WHERE ex > ? AND ex <= ? "
                                  f"AND sid IN ({','.join('?' * len(part))})", [day_s - DAY_S, end, *part]).fetchall()
    finally:
        con.close()
    for rid, r in ever.items():
        tf_of.setdefault(rid, r.get("tf"))

    def bar(rid):
        tf = tf_of.get(rid)
        return int(br.TFS[tf][1]) if tf in br.TFS else None

    bt = {}
    for sid, ex, en, side, why, pnl in trades:
        rid = by_sid[int(sid)]
        b = bar(rid)
        if int(why) == end_code or b is None or not (day_s < int(ex) + b <= end):
            continue
        if rid not in lists.ids(int(en) // DAY_S * DAY_S, pid):
            continue                     # not switched on the day it opened: never expected
        bt[(rid, int(side), int(en))] = (int(ex), int(why), float(pnl))
    pr = {}
    for r in exits:
        rid = rid_of(r)
        b = bar(rid)
        ts = int(r.get("ts") or 0)
        cand = r.get("v4_candle")
        cs = int(cand) if cand is not None else (ts - b if b is not None else None)
        if b is None or cs is None or not (day_s < cs + b <= end):
            continue                     # its exit candle closed on another day
        pr[(rid, 1 if str(r.get("side")).upper() == "LONG" else -1, int(r.get("entry_ts") or 0))] = (
            cs, v4_store.why_code(r.get("why") or ""),
            float(r.get("pnl_est") or 0.0), str(r.get("trade_id") or ""))
    same = [k for k in bt if k in pr and pr[k][0] == bt[k][0] and pr[k][1] == bt[k][1]]
    return {"day": _iso(day_s), "day_s": day_s, "same": len(same), "of": len(set(bt) | set(pr)),
            "dollars_apart": round(sum(abs(pr[k][2] - bt[k][2]) for k in same), 2),
            "only_practice": sorted(pr[k][3] for k in pr if k not in same),
            "only_backtest": [f"{k[0]} {_when(k[2])}" for k in sorted(k for k in bt if k not in same)],
            "checked_s": time.time()}


# ------------------------------------------------------------------ the page
def words(st: dict) -> str:
    """Where the daily refresh is, in plain words - what every screen prints after "refreshed every
    day", never the phase's own name (operator's plain-words rule). Works on `read()`'s state or
    `status()`'s fields; every date is `fmt_when`."""
    phase = st.get("phase") or "idle"
    if phase == "unreadable":
        return f"its record cannot be read: {st.get('error') or st.get('why') or 'unknown'}"
    return _phase_words(st, phase) + _news(st, phase)


def _phase_words(st: dict, phase: str) -> str:
    if phase in ("dispatch", "running"):
        return "measuring on GitHub"
    if phase == "collect":
        return "collecting the results"
    if phase == "build":
        return "rebuilding Backtest v4"
    if phase in ("lists", "agree"):
        return "choosing today's strategies"
    if phase == "given_up":
        return f"gave up: {st.get('error') or st.get('why') or 'no reason kept'}"
    if phase == "done":
        got = st.get("landed_s") or st.get("done_at")
        return f"done {_when(got)}" if got else "done"
    nxt = st.get("next_s") or _next_due(time.time())
    return f"next refresh {_when(nxt)}"


def _news(st: dict, phase: str) -> str:
    """What the screens were missing after the list landed (final review, Nov 11, 2026): the coins
    kept stale or absent, a redo refused or skipped, a kept copy lost (`_notes`); a step failing right
    now and when it is tried again; a check that could not be made."""
    out = _notes(st)
    if st.get("failed_at") and st.get("error") and phase != "given_up":
        out += f" - the last try failed: {st['error']} (tried again after {RETRY_S // 60} minutes)"
    if phase == "done" and st.get("agree_error"):
        out += f" - yesterday's check could not be made: {st['agree_error']}"
    return out


def status() -> dict:
    """What the rooms and Backtest v4 print about the daily refresh."""
    st = read()
    deal = st.get("deal") or {}
    out = {"phase": st.get("phase") or "idle", "day": st.get("day"), "why": st.get("why") or "",
            "error": st.get("error") or "", "started_at": st.get("started_at"), "deadline_s": st.get("deadline_s"),
            "landed_s": st.get("landed_s"), "done_at": st.get("done_at"), "manual": bool(st.get("manual")),
            "deal": {_owner(r): len(p) for r, p in deal.items()}, "runs": st.get("runs") or {},
            "refused": st.get("refused") or [], "coins": st.get("coins"), "pinned": st.get("pinned"),
            "delisted": st.get("delisted") or [], "not_added": st.get("not_added"),
            "missing": st.get("missing") or [], "stale": st.get("stale") or {}, "failed": st.get("failed") or [],
            "fallbacks": st.get("fallbacks") or [], "agree": st.get("agree") or {},
            "agreed_days": st.get("agreed_days") or [], "last": st.get("last"),
            "redo_refused": st.get("redo_refused") or (st.get("collect") or {}).get("redo_refused") or [],
            "redo_skipped": st.get("redo_skipped") or (st.get("collect") or {}).get("redo_skipped") or "",
            "redo_error": st.get("redo_error") or "", "prev_error": st.get("prev_error") or "",
            "failed_at": st.get("failed_at") or 0, "agree_error": st.get("agree_error") or "",
            "next_s": _next_due(time.time())}
    out["words"] = words(out)
    return out


# ------------------------------------------------------------------ the processes
def _spawn(args: list, **kw):
    """One place a child process starts (a test replaces this, never `subprocess.run` itself)."""
    return subprocess.run(args, **kw)


def _mono() -> float:
    """How long a step took (a test advances it; `now` itself is the tick's clock)."""
    return time.monotonic()


def _rotate(log: Path) -> None:
    try:
        if log.exists() and log.stat().st_size > LOG_MAX_BYTES:
            os.replace(log, log.with_name(log.name + ".old"))
    except OSError:
        pass


def _tail(log: Path, n: int = 3) -> str:
    try:
        lines = [x for x in log.read_text(encoding="utf-8", errors="replace").splitlines() if x.strip()]
    except OSError:
        return "(no log)"
    return " | ".join(lines[-n:])[:400]


def _keep_prev() -> None:
    """The collected file the new store was built from, kept for tomorrow's stale lines."""
    src, dst = _collected(), _prev()
    if not src.exists():
        return
    tmp = dst.with_name(dst.name + ".copying")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)


def _child(cmd: str, spec: dict) -> dict:
    """`python -m tradingagents.v4_daily <cmd> <spec>` in its own process, its output in the log; the
    result is the small summary it writes. A failure is raised with the log's last lines."""
    w = work()
    spec_path, result = w / f"{cmd}-spec.json", w / f"{cmd}-result.json"
    if result.exists():
        result.unlink()
    spec_path.write_text(json.dumps({**spec, "result": str(result)}), encoding="utf-8")
    log = log_path()
    _rotate(log)
    with log.open("a", encoding="utf-8") as fh:
        fh.write(f"--- {_when(time.time())}: {cmd} ---\n")
        fh.flush()
        got = _spawn([sys.executable, "-m", "tradingagents.v4_daily", cmd, str(spec_path)], stdout=fh,
                     stderr=subprocess.STDOUT, timeout=CHILD_TIMEOUT_S, cwd=str(ROOT),
                     env={**os.environ, "PYTHONUNBUFFERED": "1"})
    if got.returncode != 0:
        raise RuntimeError(f"the {cmd} step's process ended {got.returncode}: {_tail(log)}")
    return json.loads(result.read_text(encoding="utf-8"))


def _coin_of(failure: str) -> str:
    return str(failure).split(" ")[0]


def collect_main(spec: dict) -> dict:
    """In the child: every account's lines (`acs.collect_skill("daily")`), answered as a summary."""
    from tradingagents import acs

    out = acs.collect_skill(SET)
    failed = list(out.get("failed") or [])
    lines = out.get("lines") or {}
    return {"failed": failed, "failed_coins": sorted({_coin_of(f) for f in failed}),
            "not_reached": list(out.get("not_reached") or []),
            "downloads_failed": list(out.get("downloads_failed") or []),
            "skipped_n": len(out.get("skipped") or []), "lines": len(lines),
            "coins": len({k.split("|")[0] for k in lines})}


def finish_main(spec: dict) -> dict:
    """In the child: the redo's lines laid over the collected file (`acs.collect_redo("daily")`), then
    every coin still missing keeps the previous built file's lines, marked stale - never the Nov 05
    files. Holds one ~0.5 GB file in memory at a time."""
    import gc

    from tradingagents import acs

    redo_error = None
    if spec.get("redo"):
        try:
            acs.collect_redo(SET)
        except Exception as exc:                                       # noqa: BLE001
            redo_error = f"{type(exc).__name__}: {str(exc)[:300]}"
    path = _collected()
    d = json.loads(path.read_text(encoding="utf-8"))
    lines = d.get("lines") or {}
    coins_with = {k.split("|")[0] for k in lines}

    def still(f: str) -> bool:
        head = str(f).split(":")[0].split(" ")
        coin, tf = head[0], (head[1] if len(head) > 1 else "*")
        return coin not in coins_with if tf == "*" else f"{coin}|{tf}" not in lines

    failed = [f for f in (d.get("failed") or []) if still(f)]
    missing = sorted({_coin_of(f) for f in failed} | set(d.get("not_reached") or []))
    have = set(lines)
    stale: dict = {}
    if missing and Path(spec["prev"]).exists():
        want = set(missing)
        del d, lines
        gc.collect()
        p = json.loads(Path(spec["prev"]).read_text(encoding="utf-8"))
        carry = {k: v for k, v in (p.get("lines") or {}).items() if k.split("|")[0] in want and k not in have}
        del p
        gc.collect()
        d = json.loads(path.read_text(encoding="utf-8"))
        for k, v in sorted(carry.items()):
            d["lines"][k] = {**v, "stale": True}
            stale.setdefault(k.split("|")[0], []).append(k.split("|")[1])
        lines = d["lines"]
    absent = sorted(c for c in missing if not any(k.split("|")[0] == c for k in lines))
    if stale or absent:
        d["stale"] = {c: sorted(t) for c, t in stale.items()}
        d["absent"] = absent
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(d), encoding="utf-8")
        os.replace(tmp, path)
    return {"redo_error": redo_error, "failed": failed, "absent": absent,
            "stale": {c: sorted(t) for c, t in stale.items()}, "lines": len(lines)}


CHILD = {"collect": collect_main, "finish": finish_main}


def main(argv: list | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) == 2 and args[0] in CHILD:
        spec = json.loads(Path(args[1]).read_text(encoding="utf-8"))
        out = CHILD[args[0]](spec)
        Path(spec["result"]).write_text(json.dumps(out), encoding="utf-8")
        print(json.dumps({k: v for k, v in out.items() if not isinstance(v, (list, dict)) or len(v) < 20}), flush=True)
        return 0
    if args == ["status"]:
        print(json.dumps(status(), indent=1))
        return 0
    print("usage: python -m tradingagents.v4_daily collect|finish <spec.json> | status")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
