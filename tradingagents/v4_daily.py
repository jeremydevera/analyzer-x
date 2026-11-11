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
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
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
LOG_MAX_BYTES = 10_000_000
IDLE = ("idle", "done", "given_up")
BEFORE_LIST = ("dispatch", "running", "collect", "build", "lists")
_LOCK = threading.Lock()
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
def read() -> dict:
    try:
        st = json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"phase": "idle"}
    return st if isinstance(st, dict) else {"phase": "idle"}


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
        got = _child("collect", {})
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
    if "redo_runs" not in c:
        c["redo_runs"], c["redo_piles"] = {}, {}
        if cq_search.quiet_hours(now):
            c["redo_skipped"] = "not redone: no press between 12:45am and 5:00am (the nightly jobs' hours)"
        else:
            fd = _fd()
            repos = [r for r in st["deal"] if r in st["runs"]]
            from tradingagents import cloud_sweep as cs

            for repo, pile in zip(repos, cs.split_coins(to_redo, len(repos)), strict=False):
                if not pile:            # an EMPTY coin_list is the whole market: never sent
                    continue
                try:
                    c["redo_runs"][repo] = fd.dispatch(WF, _inputs(pile, _label(st, True), few=True), repo,
                                                       since=_tried(st, f"redo {st['day']} {repo}", now))
                    c["redo_piles"][repo] = list(pile)
                except Exception as exc:                               # noqa: BLE001
                    c.setdefault("redo_refused", []).append(f"{_owner(repo)}: {type(exc).__name__}: "
                                                            f"{str(exc)[:160]}")
                _write(st)
        if c["redo_runs"]:
            st["why"] = (f"redoing {len(to_redo)} coin(s) alone: "
                         + ", ".join(f"run {r} on {_owner(repo)}" for repo, r in c["redo_runs"].items()))
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
              stale=dict(got.get("stale") or {}), error="", failed_at=0)
    bits = []
    if st["stale"]:
        bits.append(f"{len(st['stale'])} coin(s) keep yesterday's line, marked stale ({', '.join(sorted(st['stale'])[:10])})")
    if st["missing"]:
        bits.append(f"{len(st['missing'])} coin(s) absent today ({', '.join(st['missing'][:10])})")
    if got.get("redo_error"):
        bits.append(f"the redo could not be collected: {got['redo_error']}")
    st["why"] = "collected - " + ("; ".join(bits) if bits else "every redone coin came back") + " - building next"


def _build(st: dict, now: float) -> None:
    _say(st, "building the Backtest v4 store and Forecast v4 from today's results (in its own process)")
    log = log_path()
    _rotate(log)
    with log.open("a", encoding="utf-8") as fh:
        fh.write(f"--- {_when(time.time())}: the daily build of {st['day']} ---\n")
        fh.flush()
        got = _spawn([sys.executable, "-m", "tradingagents.v4_store", "build", "--daily"], stdout=fh,
                     stderr=subprocess.STDOUT, timeout=BUILD_TIMEOUT_S, cwd=str(ROOT),
                     env={**os.environ, "PYTHONUNBUFFERED": "1"})
    if got.returncode != 0:
        raise RuntimeError(f"the build ended {got.returncode}: {_tail(log)}")
    try:
        _keep_prev()
        st.pop("prev_error", None)
    except OSError as exc:          # never a reason to build the store again: named instead
        st["prev_error"] = (f"the collected file could not be kept for tomorrow ({type(exc).__name__}: {exc}); "
                            f"a coin missing tomorrow will be absent rather than stale")
    st.update(phase="lists", built_s=time.time(), error="", failed_at=0,
              why="the store and Forecast v4 are rebuilt - switching on each room's strategies next")


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
        for pid in vf.rooms():
            _say(st, f"switching on {profiles.name_of(pid)}'s strategies for {_when(day_s)}")
            rooms[pid] = f4.switched_on(profiles.v4_rule(pid), day_s)
        if path.exists():               # never rewritten, even by a race
            st["list_note"] = f"the list of {_when(day_s)} had already been written and is kept as it is"
        else:
            f2.publish(path, json.dumps({"day": st["day"], "day_s": day_s, "made_s": now, "fallback_from": None,
                                         "rooms": rooms}))
            counts = {pid: len(r) for pid, r in rooms.items()}
    st.update(phase="agree", landed_s=now, counts=counts, error="", failed_at=0,
              why=(f"the list of {_when(day_s)} landed at {_when(now)}: "
                   + (", ".join(f"{profiles.name_of(p)} {n}" for p, n in counts.items()) + " switched on"
                      if counts else st.get("list_note", "")) + " - checking yesterday next"))


def _agree(st: dict, now: float) -> None:
    from tradingagents import forecast_v2 as f2
    from tradingagents import profiles
    from tradingagents import v4_follow as vf

    y = int(st["day_s"]) - DAY_S
    out = {}
    for pid in vf.rooms():
        try:
            out[pid] = agreement(pid, y)
        except Exception as exc:                                       # noqa: BLE001
            out[pid] = {"day": _iso(y), "day_s": y, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
    f2.publish(agree_path(y), json.dumps(out))
    st["agree"] = {pid: {k: r[k] for k in ("same", "of", "dollars_apart", "error") if k in r}
                   for pid, r in out.items()}
    words = [f"{profiles.name_of(p)} {r['same']} of {r['of']} the same (${r['dollars_apart']:.2f} apart)"
             if "error" not in r else f"{profiles.name_of(p)} not checked: {r['error']}" for p, r in out.items()]
    st.update(phase="done", done_at=now, error="", failed_at=0,
              why=f"the list of {_when(int(st['day_s']))} landed at {_when(float(st.get('landed_s') or now))}; "
                  f"yesterday's trades: " + "; ".join(words))


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
    # the deadline before the retry wait: a step that failed at 5:50am is not left waiting past 6:00am
    deadline = float(st.get("deadline_s") or (int(st.get("day_s") or _midnight(now)) + GIVE_UP_AT_S))
    if phase in BEFORE_LIST and now >= deadline:
        _give_up(st, now, f"it had not landed by {_when(deadline)}")
        return
    if st.get("failed_at") and now - float(st["failed_at"]) < RETRY_S:
        return
    if now - float(st.get("polled_at") or 0) < POLL_S:
        return
    st["polled_at"] = now
    _PHASES[phase](st, now)


def _next_due(now: float) -> float:
    d = _midnight(now)
    return d + DUE_AFTER_S if now < d + DUE_AFTER_S else d + DAY_S + DUE_AFTER_S


def tick(now: float | None = None) -> dict:
    """The supervisor's call, in its own thread: at most one phase. Nothing under pytest."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return {"why": "never under a test run"}
    if not _LOCK.acquire(blocking=False):
        return {"why": "a step is already running"}
    try:
        now = time.time() if now is None else float(now)
        st = read()
        try:
            _step(st, now)
        except Exception as exc:                                       # noqa: BLE001
            _fail(st, now, f"{type(exc).__name__}: {str(exc)[:300]}")
        _write(st)
        if st.get("why") and st["why"] != _SAID["text"]:
            _SAID["text"] = st["why"]
            print(f"[v4-daily] {st['why']}", flush=True)
        return {"phase": st.get("phase"), "why": st.get("why", "")}
    finally:
        _LOCK.release()


def start_now(now: float | None = None) -> dict:
    """Today's chain at once, whatever `due()` says - the first refresh. Never between 12:45am and
    5:00am, never over a chain already under way. Its deadline is six hours from now (a first refresh
    started late is not given up at 06:00 UTC); the dispatch is the next tick's."""
    from tradingagents import cq_search

    now = time.time() if now is None else float(now)
    if cq_search.quiet_hours(now):
        raise RuntimeError("no press between 12:45am and 5:00am (the nightly jobs' hours)")
    if not _LOCK.acquire(blocking=False):
        raise RuntimeError("the daily refresh is in the middle of a step; ask again in a minute")
    try:
        st = read()
        if (st.get("phase") or "idle") not in IDLE:
            raise RuntimeError(f"the refresh of {st.get('day')} is already under way ({st.get('phase')}): "
                               f"{st.get('why', '')}")
        _begin(st, now, max(_midnight(now) + GIVE_UP_AT_S, now + GIVE_UP_AT_S), manual=True)
    finally:
        _LOCK.release()
    return status()


# ------------------------------------------------------------------ the agreement check
def agreement(pid: str, day_s: int, db: Path | None = None) -> dict:
    """Room `pid`'s practice trades that OPENED on the UTC day `day_s` against the re-measured
    backtest's trades of the strategies on that day's list that opened that day (never END).

    A pair is THE SAME when strategy id, side, entry candle (`entry_ts == en`), exit candle (the exit
    row's `ts` is the exit candle's close: `ts - bar == ex`) and exit reason all match; `dollars_apart`
    adds |practice - backtest| over those, to the cent. Compared are the trades CLOSED BY THE NEXT
    MIDNIGHT on either side - the store was measured to then, and the follower holds there until the
    next list lands - so a trade still open at midnight on either side is counted
    (`open_at_midnight`), never called a difference. `of` counts the trades either side made (a pair
    once); every trade that is not the same is listed - practice's by trade id, the backtest's by
    strategy id and entry."""
    import tradingagents.auto_trader as at
    from tradingagents import backtest_report as br
    from tradingagents import profiles, v4_store
    from tradingagents import v4_follow as vf

    day_s = int(day_s)
    end = day_s + DAY_S
    end_code = v4_store.WHYS.index("END")
    try:
        doc = json.loads(vf.list_path(day_s).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = {}
    listed = {str(r["id"]): r for r in ((doc.get("rooms") if isinstance(doc, dict) else None) or {}).get(pid) or []
              if isinstance(r, dict) and r.get("id")}
    with profiles.using(pid):
        rows = at.ledger_trades(day_s)

    def ours(r):
        return (str(r.get("strategy") or "").startswith("v4_")
                and day_s <= int(r.get("entry_ts") or -1) < end)

    exits = [r for r in rows if r.get("action") == "exit" and ours(r)]
    enters = [r for r in rows if r.get("action") == "enter" and ours(r)]

    def sid_of(r) -> str:
        return str(r.get("v4_id") or str(r.get("strategy"))[3:])

    ids = set(listed) | {sid_of(r) for r in exits + enters}
    p = Path(db) if db else v4_store.db_path()
    con = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True, timeout=30)
    tf_of, sids = {}, {}
    trades = []
    try:
        idl = sorted(ids)
        for i in range(0, len(idl), 500):
            part = idl[i:i + 500]
            for sid, rid, tf in con.execute(f"SELECT sid, id, tf FROM strat WHERE id IN ({','.join('?' * len(part))})",
                                            part):
                tf_of[rid] = tf
                if rid in listed:
                    sids[int(sid)] = rid
        sl = sorted(sids)
        for i in range(0, len(sl), 500):
            part = sl[i:i + 500]
            trades += con.execute(f"SELECT sid, ex, en, side, why, pnl FROM trade WHERE en >= ? AND en < ? "
                                  f"AND sid IN ({','.join('?' * len(part))})", [day_s, end, *part]).fetchall()
    finally:
        con.close()
    for rid, r in listed.items():
        tf_of.setdefault(rid, r.get("tf"))

    def bar(rid):
        tf = tf_of.get(rid)
        return int(br.TFS[tf][1]) if tf in br.TFS else None

    bt, bt_open = {}, set()
    for sid, ex, en, side, why, pnl in trades:
        rid = sids[int(sid)]
        k = (rid, int(side), int(en))
        b = bar(rid)
        if int(why) == end_code or b is None or int(ex) + b > end:
            bt_open.add(k)
        else:
            bt[k] = (int(ex), int(why), float(pnl))
    pr, pr_open = {}, set()
    for r in exits:
        rid = sid_of(r)
        k = (rid, 1 if str(r.get("side")).upper() == "LONG" else -1, int(r["entry_ts"]))
        b = bar(rid)
        ts = int(r.get("ts") or 0)
        if b is not None and ts > end:
            pr_open.add(k)
        else:
            pr[k] = (ts - b if b is not None else None, v4_store.why_code(r.get("why") or ""),
                     float(r.get("pnl_est") or 0.0), str(r.get("trade_id") or ""))
    for r in enters:
        k = (sid_of(r), 1 if str(r.get("side")).upper() == "LONG" else -1, int(r["entry_ts"]))
        if k not in pr:
            pr_open.add(k)
    same = [k for k in bt if k in pr and pr[k][0] == bt[k][0] and pr[k][1] == bt[k][1]]
    union = set(bt) | set(pr)
    return {"day": _iso(day_s), "day_s": day_s, "same": len(same), "of": len(union),
            "dollars_apart": round(sum(abs(pr[k][2] - bt[k][2]) for k in same), 2),
            "only_practice": sorted(pr[k][3] for k in pr if k not in same),
            "only_backtest": [f"{k[0]} {_when(k[2])}" for k in sorted(k for k in bt if k not in same)],
            "open_at_midnight": len((bt_open | pr_open) - union), "listed": len(listed),
            "checked_s": time.time()}


# ------------------------------------------------------------------ the page
def status() -> dict:
    """What the rooms and Backtest v4 print about the daily refresh."""
    st = read()
    deal = st.get("deal") or {}
    return {"phase": st.get("phase") or "idle", "day": st.get("day"), "why": st.get("why") or "",
            "error": st.get("error") or "", "started_at": st.get("started_at"), "deadline_s": st.get("deadline_s"),
            "landed_s": st.get("landed_s"), "done_at": st.get("done_at"), "manual": bool(st.get("manual")),
            "deal": {_owner(r): len(p) for r, p in deal.items()}, "runs": st.get("runs") or {},
            "refused": st.get("refused") or [], "coins": st.get("coins"), "pinned": st.get("pinned"),
            "delisted": st.get("delisted") or [], "not_added": st.get("not_added"),
            "missing": st.get("missing") or [], "stale": st.get("stale") or {}, "failed": st.get("failed") or [],
            "fallbacks": st.get("fallbacks") or [], "agree": st.get("agree") or {}, "last": st.get("last"),
            "next_s": _next_due(time.time())}


# ------------------------------------------------------------------ the processes
def _spawn(args: list, **kw):
    """One place a child process starts (a test replaces this, never `subprocess.run` itself)."""
    return subprocess.run(args, **kw)


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
