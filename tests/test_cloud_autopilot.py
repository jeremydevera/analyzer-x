"""The cloud autopilot LANDS runs; it never starts one.

It used to. The operator's 2026-09-05 goal *"I WANT TO USE GITHUB WHEN THERE IS
FREE"* was read as a standing rule, so starting localhost started the API, the
supervisor ticked, and run 34285739222 (20 machines, 4h+30m) was dispatched on
Sep 09, 2026 with nobody asking. The correction was immediate:

    *"no no no, i want option to start the backtest i only said this because
    i was using my own local back then"*

So: buttons dispatch (RUN ON GITHUB, UPDATE ALL BACKTESTS); the tick only
COLLECTS finished runs, because their artifacts delete themselves after 14
days and rows that never land measured nothing. The first test here is the
correction itself.
"""
import time

import pytest

from tradingagents import cloud_autopilot as ca


@pytest.fixture(autouse=True)
def _own_state(tmp_path, monkeypatch):
    """Never touch the operator's real autopilot state."""
    monkeypatch.setattr(ca, "STATE", tmp_path / "autopilot.json")


# ------------------------------------------------ it NEVER starts a run
def test_the_tick_never_dispatches_no_matter_how_free_github_is(monkeypatch):
    """The correction itself. GitHub idle, a 775-pair hole, cooldowns clear —
    the exact state that used to fire a 20-machine run the moment the API came
    up — and consider() must still start NOTHING."""
    from tradingagents import capacity as cap, cloud_sweep as cs

    sent = []
    monkeypatch.setattr(cs, "dispatch",
                        lambda **kw: (sent.append(kw), {"id": 1})[1])
    monkeypatch.setattr(cap, "cloud_free", lambda: (True, "free"))
    monkeypatch.setattr(ca, "collect_finished",
                        lambda **kw: {"started": False, "why": "nothing "
                                      "finished is uncollected"})
    got = ca.consider()
    assert got["dispatched"] is False
    assert not sent, "starting a backtest is the operator's button, never a tick"


def test_the_module_holds_no_dispatch_machinery():
    """`pick`, MIN_MISSING, the dispatch cooldown — all of it was the engine
    that started runs by itself. Dead code lies, so it is gone, and this fails
    if it grows back without the operator asking."""
    import inspect

    src = inspect.getsource(ca)
    assert "cs.dispatch(" not in src
    assert not hasattr(ca, "pick")
    assert not hasattr(ca, "MIN_MISSING")
    assert "GitHub was free — sent" not in src


def test_a_tick_still_collects_what_finished(monkeypatch):
    """Removing the dispatch half must not take the collect half with it."""
    monkeypatch.setattr(ca, "collect_finished",
                        lambda **kw: {"started": True, "run": 7})
    got = ca.consider()
    assert got["collecting"]["run"] == 7
    assert "collecting run 7" in got["why"]


# ----------------------------------------------------------------- plumbing
def test_a_corrupt_state_file_is_not_fatal():
    ca.STATE.write_text("not json")
    assert ca._read() == {}


def test_the_supervisor_calls_it():
    src = open("tradingagents/api.py", encoding="utf-8").read()
    assert "cloud_autopilot" in src
    assert "_ca.tick()" in src
    # and a failure there must never take the supervisor down with it
    i = src.index("_ca.tick()")
    assert "except Exception" in src[i:i + 300]


def test_missing_is_counted_from_directory_listings(monkeypatch, tmp_path):
    """Never `candle_coverage()`, which opens every candle file — this runs on
    a 30-second tick against a 5,000-pair store."""
    import inspect

    from tradingagents import market_sweep as msw

    # the docstring NAMES candle_coverage as the thing not to use, so check
    # the body rather than the whole source
    src = inspect.getsource(ca.missing_by_timeframe)
    body = src.split('"""')[-1]
    assert "candle_coverage" not in body
    assert ".glob(" in body

    candles, states = tmp_path / "c", tmp_path / "s"
    candles.mkdir(), states.mkdir()
    for n in ("BTC_USDT-15m", "BTC_USDT-1d", "ETH_USDT-1d"):
        (candles / f"{n}.json").write_text("{}")
    (states / "BTC-15m.json").write_text("{}")
    monkeypatch.setattr(msw, "CANDLES", candles)
    monkeypatch.setattr(msw, "STATES", states)
    assert ca.missing_by_timeframe() == {"1d": 2}


def test_a_no_op_is_logged_when_the_reason_changes(monkeypatch, capsys):
    """The module's docstring says a silent no-op is indistinguishable from a
    broken autopilot — and then every no-op was silent. Logging every tick
    would be a line every 30 seconds; logging only CHANGES is one per event."""
    reasons = iter([{"dispatched": False, "why": "GitHub is not free: run 7"},
                    {"dispatched": False, "why": "GitHub is not free: run 7"},
                    {"dispatched": False, "why": "cooling down, 12 min left"}])
    monkeypatch.setattr(ca, "consider", lambda: next(reasons))
    ca._LAST_SAID["why"] = ""
    for _ in range(3):
        ca.tick()
    out = capsys.readouterr().out
    assert out.count("[cloud-autopilot]") == 2, out
    assert "run 7" in out and "cooling down" in out


def test_the_supervisor_calls_tick_not_consider():
    src = open("tradingagents/api.py", encoding="utf-8").read()
    assert "_ca.tick()" in src


# ------------------------------------------------- landing what it dispatched
def _runs(monkeypatch, rows, *, artifacts=True, collect_running=False):
    from tradingagents import cloud_sweep as cs, db_jobs as dj

    monkeypatch.setattr(cs, "repo_slug", lambda: "me/repo")
    monkeypatch.setattr(cs, "_runs", lambda slug, limit=10: rows)
    monkeypatch.setattr(cs, "artifact_names",
                        lambda rid, slug=None: ["rows-0"] if artifacts else [])
    monkeypatch.setattr(dj, "status",
                        lambda k: {"running": collect_running})
    started = []
    monkeypatch.setattr(dj, "start",
                        lambda kind, spec: (started.append((kind, spec)), 4242)[1])
    return started


def test_a_finished_run_is_collected_into_the_store(monkeypatch):
    """Five runs finished between Sep 03 and Sep 05, 2026 — 100 artifacts,
    ~150M rows — and not one reached the store, because the workflow prints
    "collect with: collect_into_store(<run id>)" and waits for a person. The
    artifacts delete themselves after 14 days."""
    started = _runs(monkeypatch, [{"databaseId": 7, "status": "completed",
                                   "conclusion": "success"}])
    got = ca.collect_finished(now=time.time(), state={})
    assert got["started"] is True and got["run"] == 7
    assert started == [("collect", {"run": 7})]


def test_a_run_is_only_collected_once(monkeypatch):
    """A run is marked done when the JOB says it finished, not when it starts
    — see test_a_collect_that_died_half_way_is_retried."""
    from tradingagents import db_jobs as dj

    started = _runs(monkeypatch, [{"databaseId": 7, "status": "completed",
                                   "conclusion": "success"}])
    state = {}
    ca.collect_finished(now=time.time(), state=state)
    assert state["collecting"] == 7

    monkeypatch.setattr(dj, "_read",
                        lambda p: {"run": 7, "running": False, "rows": 10})
    state["last_collect_look"] = 0        # past the throttle
    got = ca.collect_finished(now=time.time(), state=state)
    assert 7 in state["collected"]
    assert got["started"] is False
    assert len(started) == 1


def test_a_run_still_going_is_left_alone(monkeypatch):
    started = _runs(monkeypatch, [{"databaseId": 7, "status": "in_progress",
                                   "conclusion": None}])
    assert ca.collect_finished(now=time.time(), state={})["started"] is False
    assert not started


def test_expired_artifacts_are_remembered_not_retried_for_ever(monkeypatch):
    started = _runs(monkeypatch, [{"databaseId": 7, "status": "completed",
                                   "conclusion": "success"}], artifacts=False)
    state = {}
    assert ca.collect_finished(now=time.time(), state=state)["started"] is False
    assert 7 in state["collected"], "an expired run must not be walked for ever"
    assert not started


def test_only_one_collect_runs_at_a_time(monkeypatch):
    started = _runs(monkeypatch, [{"databaseId": 7, "status": "completed",
                                   "conclusion": "success"}],
                    collect_running=True)
    got = ca.collect_finished(now=time.time(), state={})
    assert got["started"] is False and "already running" in got["why"]
    assert not started


def test_collecting_ignores_the_old_dispatch_state(monkeypatch):
    """A state file full of dispatch-era keys (cooldowns, missing maps) must
    not stop the collector — those guards were about STARTING runs, and
    starting is gone."""
    monkeypatch.setattr(ca, "collect_finished",
                        lambda **kw: {"started": True, "run": 7})
    ca._write({"last_dispatch": time.time(), "missing": {"4h": 99}})
    got = ca.consider()
    assert got["dispatched"] is False
    assert got["collecting"]["run"] == 7, got


def test_the_collector_does_not_ask_github_on_every_tick(monkeypatch):
    """BUG B. artifact_names() is an API call PER RUN, up to ten, on a
    30-second tick — the secondary limit that 403'd this account for hours."""
    from tradingagents import cloud_sweep as cs

    calls = {"n": 0}
    _runs(monkeypatch, [])

    def counted(slug, limit=10):
        calls["n"] += 1
        return []

    monkeypatch.setattr(cs, "_runs", counted)
    state, t = {}, time.time()
    for i in range(20):                       # ten minutes of ticks
        ca.collect_finished(now=t + i * 30, state=state)
    assert calls["n"] <= 3, f"asked GitHub {calls['n']} times in 10 minutes"


def test_the_collect_job_exists_and_is_routed():
    from tradingagents import db_jobs as dj

    assert "collect" in dj.FILES
    assert hasattr(dj, "_run_collect")
    src = open("tradingagents/db_jobs.py", encoding="utf-8").read()
    assert 'elif kind == "collect":' in src


def test_a_collect_that_died_half_way_is_retried(monkeypatch):
    """It was marked collected the moment it STARTED, so a job that died left
    a run partly landed and never retried — and `resume_if_died` does not
    watch this job kind."""
    from tradingagents import db_jobs as dj

    started = _runs(monkeypatch, [{"databaseId": 7, "status": "completed",
                                   "conclusion": "success"}])
    state = {}
    ca.collect_finished(now=time.time(), state=state)
    assert state["collecting"] == 7
    assert 7 not in (state.get("collected") or []), "not done until it says so"

    # the job reports it failed
    monkeypatch.setattr(dj, "_read",
                        lambda p: {"run": 7, "running": False,
                                   "error": "IncompleteRead"})
    state["last_collect_look"] = 0
    ca.collect_finished(now=time.time(), state=state)
    assert 7 not in (state.get("collected") or []), "a failure must be retried"
    assert len(started) == 2


def test_a_collect_that_keeps_failing_is_named_and_dropped(monkeypatch):
    from tradingagents import db_jobs as dj

    _runs(monkeypatch, [{"databaseId": 7, "status": "completed",
                         "conclusion": "success"}])
    monkeypatch.setattr(dj, "_read",
                        lambda p: {"run": 7, "running": False, "error": "boom"})
    state = {"collect_tries": {"7": ca.COLLECT_RETRIES}, "collecting": 7}
    ca.collect_finished(now=time.time(), state=state)
    assert 7 in state["collected"], "it must stop, not loop for ever"


def test_a_collect_that_succeeded_is_marked_done(monkeypatch):
    from tradingagents import db_jobs as dj

    _runs(monkeypatch, [{"databaseId": 7, "status": "completed",
                         "conclusion": "success"}])
    monkeypatch.setattr(dj, "_read",
                        lambda p: {"run": 7, "running": False,
                                   "rows": 1000, "pairs": 5})
    state = {"collecting": 7}
    ca.collect_finished(now=time.time(), state=state)
    assert 7 in state["collected"]


def test_the_collect_progress_callback_matches_what_calls_it():
    """`collect_into_store` calls `on_progress(name, n, len(names), kept,
    rows_seen)` — FIVE arguments, from inside the parse loop with no guard.

    The first version of `_run_collect` passed a three-argument callback, so
    the call raised TypeError the moment the first shard finished parsing: all
    the download work was done and the job then died reporting a crash. Source
    inspection cannot see this; the two signatures have to be checked against
    each other.
    """
    # how many positional arguments the caller actually sends. Parsed, not
    # regexed: `len(names)` is an argument containing a bracket, and a regex
    # counted it as the end of the call.
    import ast
    import inspect
    import re
    import textwrap

    from tradingagents import cloud_sweep as cs, db_jobs as dj

    tree = ast.parse(textwrap.dedent(inspect.getsource(cs.collect_into_store)))
    sent = max(len(n.args) for n in ast.walk(tree)
               if isinstance(n, ast.Call)
               and getattr(n.func, "id", "") == "on_progress")
    assert sent == 5, f"the caller now sends {sent}; update _run_collect"

    # and the callback must swallow that many
    body = inspect.getsource(dj._run_collect)
    sig = re.search(r"def prog\(([^)]*)\)", body)
    assert sig, "prog moved"
    params = [a.strip() for a in sig.group(1).split(",") if a.strip()]
    positional = [a for a in params if not a.startswith("*")]
    assert len(positional) >= sent or any(a.startswith("*") for a in params), \
        f"prog takes {len(positional)}, the caller sends {sent}"
