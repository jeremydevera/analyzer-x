"""LAND finished cloud runs into the store. Nothing is dispatched here.

This module used to START backtest sweeps on its own: the operator's
2026-09-05 goal *"I WANT TO USE GITHUB WHEN THERE IS FREE"* was read as a
standing rule, so merely starting localhost started the API, the API's
supervisor ticked, and a 20-machine run was dispatched with nobody asking for
one — run 34285739222 on Sep 09, 2026 started that way, and the operator's
correction was immediate:

    *"no no no, i want option to start the backtest i only said this because
    i was using my own local back then"*

Starting a backtest is the operator's BUTTON — RUN ON GITHUB
(`/api/cloud/dispatch`) or UPDATE ALL BACKTESTS — never a side effect of the
app coming up. What stays automatic is the half that finishes THEIR runs: when
a run completes, its rows sit in GitHub artifacts that delete themselves after
14 days (five runs, ~150M rows, were three days from the bin on Sep 05), so
this collects every finished, uncollected run into the store on the
supervisor's tick.
"""
from __future__ import annotations

import contextlib
import json
import time
from pathlib import Path

# How often GitHub itself may be asked what finished. The supervisor ticks
# every 30 s; asking that often is 2 API calls a minute against the endpoints
# whose SECONDARY rate limit 403'd this account for hours on Sep 02, 2026.
CHECK_EVERY_S = 5 * 60

# How many times one run's collect is retried before it is named and dropped.
# A collect that dies half-way leaves a run partly landed, and `resume_if_died`
# does not watch this job kind.
COLLECT_RETRIES = 3

STATE = Path.home() / ".tradingagents" / "cloud_autopilot.json"


def _read() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def _write(d: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(d))
    except OSError:
        pass


def missing_by_timeframe() -> dict:
    """Pairs this machine holds candles for but has never measured, per frame.

    Two directory listings, names only — never `candle_coverage()`, which opens
    every candle file and takes minutes on a 5,000-pair store. The dispatch
    half of this module used to aim runs with it; since that was removed
    (2026-09-09) it is the DIAGNOSTIC the pending routes and tests read — what
    a button run would still have to cover.
    """
    from tradingagents import backtest_logs as bl, market_sweep as msw

    measured = {p.stem for p in msw.STATES.glob("*.json")}
    # DELISTED pairs are not missing: no shard can measure a coin the venue
    # no longer lists, so counting them would report work forever for pairs
    # nothing can touch (Sep 06, 2026). `fleet_symbols` is the SHARD'S own
    # rule (state == 0), cached 300s; unreadable keeps every pair counted.
    live = bl.fleet_symbols()
    out: dict = {}
    for p in msw.CANDLES.glob("*.json"):
        try:
            sym, tf = p.stem.rsplit("-", 1)
        except ValueError:
            continue
        if (f"{sym.replace('_USDT', '')}-{tf}" not in measured
                and (live is None or sym in live)):
            out[tf] = out.get(tf, 0) + 1
    return out


def collect_finished(*, now: float, state: dict) -> dict:
    """Land the rows of any finished cloud run that has not been collected.

    One at a time and DETACHED (`db_jobs.start("collect", ...)`): a 20-artifact
    run is gigabytes and minutes, and this is called from the supervisor's
    30-second tick.

    Only runs THIS autopilot dispatched, plus whatever the operator asked for
    by hand, are chased — it walks the recent run list rather than guessing.
    """
    from tradingagents import cloud_sweep as cs, db_jobs as dj

    try:
        for k in ("collect", "collect_v2"):
            if dj.status(k).get("running"):
                return {"started": False,
                        "why": f"a {k} is already running"}
    except Exception:                                          # noqa: BLE001
        pass

    if now - float(state.get("last_collect_look") or 0) < CHECK_EVERY_S:
        return {"started": False, "why": "waiting before asking GitHub again"}
    state["last_collect_look"] = now
    _write(state)

    done = set(state.get("collected") or [])

    # Did the LAST collect finish? Its own progress file is the truth — the
    # autopilot never waits for it.
    pending = state.get("collecting")
    if pending is not None:
        st = {}
        # EITHER KIND. A v2 run is collected by `collect_v2` and writes its own
        # progress file; reading only v1's would leave `collecting` set for
        # ever, and the autopilot would never start another collect at all.
        for _k in ("collect", "collect_v2"):
            with contextlib.suppress(Exception):               # noqa: BLE001
                got = dj._read(dj.FILES[_k]["progress"])
                if got.get("run") == pending:
                    st = got
                    break
        if st.get("run") == pending and not st.get("running"):
            state["collecting"] = None
            if st.get("error"):
                n = int((state.get("collect_tries") or {}).get(str(pending), 0))
                if n >= COLLECT_RETRIES:
                    print(f"[cloud-autopilot] run {pending} could not be "
                          f"collected after {n} attempt(s): {st['error']} — "
                          f"giving up on it", flush=True)
                    done.add(pending)      # named above, not silently dropped
                # under the limit it is left OUT of `done`, so the next look
                # picks it up again
            else:
                done.add(pending)
            state["collected"] = sorted(done)
            _write(state)

    # EVERY ACCOUNT, not just this checkout's first remote. Since
    # Sep 21, 2026 one press can dispatch to the operator's account and their
    # partner's fork at once ("i want 40"), and a run collected from the
    # wrong repo is a 404 — or worse, somebody else's run id that happens to
    # exist. Each run is carried with the account that produced it.
    runs, seen_fleets = [], []
    try:
        seen_fleets = cs.fleets()
    except Exception as exc:                                   # noqa: BLE001
        return {"started": False, "why": f"cannot read the remotes: {exc}"}
    # ONE ACCOUNT PER LOOK, IN TURN. Asking every fleet each time would
    # multiply the calls to the endpoint whose secondary limit 403'd this
    # account for hours (RCA-2026-09-02) — by the number of accounts, which
    # is the number the operator is trying to grow. A run takes twenty
    # minutes and the look is throttled anyway, so turns cost nothing.
    turn = int(state.get("fleet_turn") or 0)
    slug = seen_fleets[turn % len(seen_fleets)] if seen_fleets else ""
    state["fleet_turn"] = (turn + 1) % max(1, len(seen_fleets))
    _write(state)
    if slug:
        try:
            runs = [{**r, "repo": slug} for r in cs._runs(slug, limit=10)]
        except Exception as exc:                               # noqa: BLE001
            # one account being unreachable must never stop the other's rows
            # from landing; it is named, not swallowed, and the next look
            # takes the other account's turn
            return {"started": False,
                    "why": f"cannot list {slug}'s runs: {exc}"}
    for r in runs:
        rid = r.get("databaseId")
        slug = r.get("repo")
        if rid in done or r.get("status") != "completed":
            continue
        if r.get("conclusion") not in ("success", "failure"):
            continue           # cancelled/skipped produced nothing to collect
        try:
            if not cs.artifact_names(rid, slug):
                # expired or never uploaded: remember it so the list is not
                # walked for it on every tick for ever
                done.add(rid)
                continue
            # WHICH STORE this run's rows belong to. A Backtest v2 run is
            # collected by `collect_v2`, which is spawned with
            # `stores.V2.env_for()` so `land_rows` writes into
            # ~/.tradingagents/v2 without knowing a second store exists.
            kind = "collect_v2" if cs.run_res(rid) == "1m" else "collect"
            # WHICH ACCOUNT the artifacts are on, or the collect job asks the
            # wrong GitHub and lands nothing
            pid = dj.start(kind, {"run": rid, "repo": slug})
        except Exception as exc:                               # noqa: BLE001
            return {"started": False, "why": f"could not start: {exc}"}
        # NOT marked collected yet — only when the job SAYS it finished. A
        # collect that dies half-way used to be marked done here and never
        # retried, leaving a run partly landed with nothing to say so, and
        # `resume_if_died` does not watch this kind.
        tries = dict(state.get("collect_tries") or {})
        tries[str(rid)] = int(tries.get(str(rid), 0)) + 1
        state["collect_tries"] = tries
        state["collecting"] = rid
        _write(state)
        print(f"[cloud-autopilot] collecting run {rid} from {slug} into "
              f"the store (pid {pid})", flush=True)
        return {"started": True, "run": rid, "repo": slug, "pid": pid}
    if done != set(state.get("collected") or []):
        state["collected"] = sorted(done)
        _write(state)
    return {"started": False, "why": "nothing finished is uncollected"}


def consider(*, now: float | None = None) -> dict:
    """Look once: land any finished run. NEVER start one.

    The dispatch half lived here until 2026-09-09 and fired the moment the API
    came up — the operator started localhost and got a 20-machine backtest they
    never asked for (run 34285739222). Their words: *"no no no, i want option
    to start the backtest"*. The buttons dispatch; this only collects, because
    a finished run's artifacts delete themselves after 14 days and rows that
    never land measured nothing.

    Returns what it did and WHY, always — a silent no-op is indistinguishable
    from a broken autopilot.
    """
    now = time.time() if now is None else now
    state = _read()
    col = collect_finished(now=now, state=state)
    if col.get("started"):
        return {"dispatched": False, "collecting": col,
                "why": f"collecting run {col['run']} into the store"}
    return {"dispatched": False, "why": col.get("why") or "nothing to collect"}


_LAST_SAID = {"why": ""}


def tick() -> dict:
    """`consider()`, with its answer logged WHENEVER IT CHANGES.

    The module's own docstring says a silent no-op is indistinguishable from a
    broken autopilot, and then every no-op was silent: nothing in the log said
    "GitHub is busy" or "waiting for the gap to change", so the only way to
    know it was alive was to run it by hand. Logging every tick would be a line
    every 30 seconds; logging only CHANGES is one line per real event.
    """
    got = consider()
    why = str(got.get("why") or "")
    if why and why != _LAST_SAID["why"] and not got.get("collecting"):
        # a starting collect prints its own, fuller line in collect_finished
        print(f"[cloud-autopilot] {why}", flush=True)
    _LAST_SAID["why"] = why
    return got
