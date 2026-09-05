"""The unattended sweep: keep measuring, wherever it can.

The operator's requirements, verbatim: accurate data, resume if it hits a rate
limit, a percentage every minute, and if the wifi drops carry on locally from
the candles already stored. These tests pin each one.
"""

import json
import time

import pytest

from tradingagents import sweep_orchestrator as so


@pytest.fixture(autouse=True)
def _sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(so, "HOME", tmp_path)
    monkeypatch.setattr(so, "STATE", tmp_path / "orchestrator.json")
    monkeypatch.setattr(so, "LOG", tmp_path / "orchestrator.log")
    monkeypatch.setattr(so, "STOP", tmp_path / "orchestrator.STOP")
    monkeypatch.setattr(so, "TICK", 0.01)


@pytest.fixture()
def local_allowed(monkeypatch):
    """The rota BEFORE Sep 05, 2026, when this PC still measured.

    The switch is meant to be reversible, so the old routing is still covered
    rather than deleted — flip `capacity.LOCAL_SWEEPS` and these are the rules
    that come back.
    """
    from tradingagents import capacity as cap

    monkeypatch.setattr(cap, "LOCAL_SWEEPS", True)


def test_no_internet_means_it_measures_locally(local_allowed):
    """"if i've been disconnected to wifi then continue the backtest local".
    4,946 candle files are already on disk; run_pair only calls the venue to
    TOP UP, so a dropped connection changes WHERE the work happens."""
    assert so.plan(online_=False, budget=5000, prefer_cloud=True) == "offline"
    assert so.plan(online_=False, budget=0, prefer_cloud=False) == "offline"


def test_a_rate_limit_does_not_stop_the_sweep(local_allowed):
    """"make sure to resume if it hits rate limit" — it keeps measuring here
    while the budget refills, instead of waiting idle."""
    assert so.plan(online_=True, budget=3, prefer_cloud=True) == "local"
    assert so.plan(online_=True, budget=so.GH_BUDGET_FLOOR,
                   prefer_cloud=True) == "local"
    # and a comfortable budget goes to the cloud
    assert so.plan(online_=True, budget=so.GH_BUDGET_FLOOR + 1,
                   prefer_cloud=True) == "cloud"


def test_it_dispatches_to_github_when_there_is_budget(local_allowed):
    assert so.plan(online_=True, budget=4000, prefer_cloud=True) == "cloud"
    # unless the operator turned the cloud off
    assert so.plan(online_=True, budget=4000, prefer_cloud=False) == "local"


# --------------------------------------------- after the move to the fleet
def test_offline_now_waits_instead_of_measuring_here():
    """Operator, Sep 05, 2026: "there will be no option 'this mac'".

    No wifi is also no GitHub, so there is no slice of work this PC could take
    that the operator still wants taken. "offline" used to mean "measure here";
    it now means wait.
    """
    assert so.plan(online_=False, budget=5000, prefer_cloud=True) == "wait"
    assert so.plan(online_=False, budget=0, prefer_cloud=False) == "wait"


def test_a_rate_limit_now_waits_too():
    """The old answer was "keep measuring here while the budget refills". With
    this PC out of the rota the honest answer is that nothing runs until the
    budget comes back."""
    assert so.plan(online_=True, budget=3, prefer_cloud=True) == "wait"
    assert so.plan(online_=True, budget=so.GH_BUDGET_FLOOR,
                   prefer_cloud=True) == "wait"


def test_a_comfortable_budget_still_goes_to_the_cloud():
    assert so.plan(online_=True, budget=so.GH_BUDGET_FLOOR + 1,
                   prefer_cloud=True) == "cloud"
    # prefer_cloud is now irrelevant: there is nowhere else to prefer
    assert so.plan(online_=True, budget=4000, prefer_cloud=False) == "cloud"


def test_the_loop_treats_wait_as_do_nothing():
    """The cloud thread only acts on exactly "cloud" (`!= "cloud": continue`),
    so a new verdict can never be mistaken for permission to dispatch."""
    import inspect

    src = inspect.getsource(so.run)
    assert '!= "cloud"' in src,         "the dispatch must be gated on the one verdict that means dispatch"


def test_the_local_thread_asks_before_it_measures():
    """The real back door: `work()` called `local_round` every tick with
    nothing consulted, and published "this Mac" as the place the work was
    happening — while `plan()` said wait.

    The decision is a named function now, so it can be CALLED. Two earlier
    versions of this test were worse: a source check that passed against its
    own docstring, and a threaded one that raced the scan thread.
    """
    from tradingagents import capacity as cap

    assert so.local_measuring_on() is cap.LOCAL_SWEEPS
    assert so.local_measuring_on() is False,         "this PC is out of the rota after Sep 05, 2026"


def test_the_switch_is_read_at_call_time(monkeypatch):
    """Flipping it must need no restart — and a stale import would make the
    whole switch a lie."""
    from tradingagents import capacity as cap

    monkeypatch.setattr(cap, "LOCAL_SWEEPS", True)
    assert so.local_measuring_on() is True
    monkeypatch.setattr(cap, "LOCAL_SWEEPS", False)
    assert so.local_measuring_on() is False


def test_the_measuring_thread_is_gated_on_it():
    """The helper must be the thing `work()` asks, and it must ask BEFORE it
    measures. Checked on the code with its docstring stripped, because the
    first version of this test matched its own prose."""
    import ast
    import inspect
    import textwrap

    src = textwrap.dedent(inspect.getsource(so.run))
    tree = ast.parse(src)
    work = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "work")
    work.body = [n for n in work.body
                 if not (isinstance(n, ast.Expr)
                         and isinstance(n.value, ast.Constant)
                         and isinstance(n.value.value, str))]
    body = ast.unparse(work)
    assert "local_measuring_on" in body,         "the measuring thread must consult the switch"
    assert body.index("local_measuring_on") < body.index("local_round"),         "and must consult it BEFORE it measures anything"


def test_progress_is_published_every_tick(monkeypatch):
    """"give me update on percentage every 1 min"."""
    assert so.TICK <= 60.0, "a tick must not be slower than the minute asked for"
    monkeypatch.setattr(so, "online", lambda: False)
    monkeypatch.setattr(so, "local_round", lambda left, **k: 0)
    monkeypatch.setattr(so, "store_pair", lambda c, tf: 0)
    # threaded now: the scan thread may call this many times, so it must
    # not be a one-shot iterator
    monkeypatch.setattr(so, "measured", lambda pairs: set(pairs))

    so.run(["A_USDT"], ["1h", "4h"])
    got = json.loads((so.STATE).read_text())
    for field in ("pct", "done", "total", "where", "elapsed_min"):
        assert field in got, f"the update is missing {field}"


def test_it_watches_git_not_the_rest_api():
    """Polling the REST API burned 5,000 requests in an hour on 2026-08-25 and
    blinded every tool at once. Shard progress lives on a branch."""
    import inspect

    src = inspect.getsource(so)
    assert "sweep-progress" in src or "git fetch" in src.lower() or \
        "watches git" in src.lower(), "it must not poll the REST API for progress"
    # the API is for dispatching and for reading the budget, nothing else
    assert src.count('subprocess.run(["gh"') <= 1


def test_finished_pairs_reach_the_database(monkeypatch, tmp_path):
    """"make sure to store the backtest in database"."""
    import inspect

    assert "rows_index" in inspect.getsource(so.store_pair)
    assert "index_pair" in inspect.getsource(so.store_pair)
    src = inspect.getsource(so.run)
    assert "store_pair" in src, "each cycle must fold finished pairs in"


def test_a_stop_file_ends_it(monkeypatch):
    monkeypatch.setattr(so, "online", lambda: False)
    monkeypatch.setattr(so, "local_round", lambda left, **k: 0)
    monkeypatch.setattr(so, "store_pair", lambda c, tf: 0)
    monkeypatch.setattr(so, "measured", lambda pairs: set())
    so.STOP.touch()
    t = time.time()
    so.run(["A_USDT"], ["1h"])
    assert time.time() - t < 5, "it ignored the stop file"
    assert "stopped by request" in (so.LOG).read_text()


def test_a_finished_cloud_run_is_merged_not_just_awaited(monkeypatch):
    """`done` counts LOCAL watermarks, so without collecting the artifact the
    percentage sat at 0 for hours and then jumped — the same false label as a
    counter that measures the process instead of the work.

    It collects by STREAMING the per-shard artifacts. On 2026-08-25 the old
    path asked only for the merged `sweep-results` file, the workflow's merge
    job was OOM-killed before writing it, and 29.7 million measured rows in
    twenty `rows-N` artifacts were logged as "no usable artifact" and dropped.
    """
    from tradingagents import cloud_sweep as cs

    monkeypatch.setattr(cs, "status",
                        lambda rid, slug=None: {"status": "completed"})
    calls = []
    monkeypatch.setattr(cs, "collect_into_store",
                        lambda rid, slug=None, **k: calls.append(rid) or
                        {"pairs": 1, "rows": 4, "skipped": 0, "artifacts": 20})
    assert so.collect_cloud(99) == 1
    assert calls == [99], "the artifacts were never folded in"

    # a run still going is left alone — None, not 0
    monkeypatch.setattr(cs, "status",
                        lambda rid, slug=None: {"status": "in_progress"})
    calls.clear()
    assert so.collect_cloud(99) is None and not calls

    # a run that ENDED with no live artifact still releases the slot, or the
    # orchestrator stays pinned to a cancelled run forever
    monkeypatch.setattr(cs, "status",
                        lambda rid, slug=None: {"status": "completed"})
    monkeypatch.setattr(cs, "collect_into_store",
                        lambda rid, slug=None, **k: {"pairs": 0, "rows": 0,
                                                     "artifacts": 0,
                                                     "skipped": 0})
    assert so.collect_cloud(99) == 0

    # and a collector that RAISES releases it too
    monkeypatch.setattr(cs, "collect_into_store",
                        lambda rid, slug=None, **k: (_ for _ in ()).throw(
                            RuntimeError("network died")))
    assert so.collect_cloud(99) == 0


def test_the_collector_is_never_the_list_shaped_one():
    """cs.fetch builds one list of every row. At 29.7M rows that is the same
    12 GB that killed the cloud's merge job, on a Mac that is also measuring."""
    import inspect

    src = inspect.getsource(so.collect_cloud)
    assert "collect_into_store" in src
    assert "cs.fetch(" not in src


def test_the_mac_works_while_the_cloud_works():
    """It dispatched and then idled — eight cores and 4,946 candle files doing
    nothing for hours. merge_into_store refuses a pair this machine already
    holds, so the two cannot overwrite each other."""
    import inspect

    src = inspect.getsource(so.run)
    work = src[src.index("def work("):]
    assert "local_round(left" in work, "the Mac must measure every cycle"
    # and it must NOT be gated on the cloud: measuring happens either way
    assert "cloud" not in work.split("local_round(left")[0].lower(), (
        "the local round must not sit behind a cloud decision")
    assert "+ this Mac" in src


def test_a_restart_adopts_the_run_already_in_flight():
    """Restarting dispatched a SECOND 20-shard run beside the first, which just
    queued behind it. Worse, `remembered()` holds the last DISPATCHED run: on
    2026-08-25 three existed at once and the orchestrator adopted a QUEUED one
    while another had 20 shards live and half a million rows per shard, so it
    reported "0/0 shards" while the cloud was most of the way through."""
    import inspect

    work = inspect.getsource(so.run)
    assert "cs.working_run()" in work, "it must find the run actually MEASURING"
    assert "cs.remembered()" not in work, (
        "the last dispatched run is not the working one")
    # the cloud runs on its OWN thread: managing it is seconds of work and must
    # not queue behind a 30-minute local round
    assert "def cloud(" in work and "for fn in (scan, work, cloud)" in work
    assert work.index("adopting GitHub run") < work.index("cs.dispatch("), \
        "adoption has to be tried BEFORE dispatching"

def test_shard_progress_is_read_from_git(monkeypatch):
    """The REST API poll burned 5,000 requests in an hour and blinded every
    tool at once."""
    import inspect

    src = inspect.getsource(so.cloud_shards)
    assert '"git", "fetch"' in src and "sweep-progress" in src
    assert "gh" not in src.replace("github", ""), "it must not touch the API"


def test_stop_takes_the_pool_down_instead_of_waiting_for_it():
    """STOP is read once a TICK, so the loop notices in a minute. The PROCESS
    took over two: local_round's ProcessPoolExecutor registers an atexit
    handler that joins every worker, so 'stop' waited for a 24-pair round to
    drain. Killing the parent instead left 8 workers reparented to init."""
    import inspect

    src = inspect.getsource(so.shutdown_pool)
    assert "signal.SIGTERM" in src and "portable.kill_hard" in src
    assert "portable.pid_alive(pid)" in src, "check it is alive before SIGKILL"

    work = inspect.getsource(so.run)
    assert work.count("shutdown_pool()") == 2, (
        "both exits close the pool: stopped-by-request AND finished")
    i = work.index("stopped by request")
    assert "shutdown_pool()" in work[max(0, i - 300):i]


def test_shutdown_pool_only_signals_its_own_children(monkeypatch):
    """A ps line whose ppid is somebody else must never be signalled."""
    sent = []
    monkeypatch.setattr(so.os, "getpid", lambda: 4242)
    monkeypatch.setattr(so.os, "kill", lambda p, s: sent.append((p, s)))
    monkeypatch.setattr(so.time, "sleep", lambda s: None)

    class R:
        stdout = "  PID  PPID\n 100 4242\n 101 4242\n 102    1\n 103  9999\n"

    monkeypatch.setattr(so.subprocess, "run", lambda *a, **k: R())
    assert so.shutdown_pool() == 2
    assert {p for p, _ in sent} == {100, 101}


def test_startup_says_something_before_the_slow_part():
    """ri.ensure() opens a 15 GB index and can migrate it. It ran BEFORE the
    first log line, so a four-minute boot looked identical to a hang -- I killed
    a healthy process twice on 2026-08-25 before reading its stack."""
    import inspect

    # the comment above the call names ri.ensure() too, so compare CODE
    src = inspect.getsource(so.run)
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert code.index('log(f"start:') < code.index("ri.ensure()"), (
        "the start line comes first, or a slow index reads as a hang")
    assert "opening the row index" in src
    assert "row index ready in" in src
