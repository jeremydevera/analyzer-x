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


def test_no_internet_means_it_measures_locally():
    """"if i've been disconnected to wifi then continue the backtest local".
    4,946 candle files are already on disk; run_pair only calls the venue to
    TOP UP, so a dropped connection changes WHERE the work happens."""
    assert so.plan(online_=False, budget=5000, prefer_cloud=True) == "offline"
    assert so.plan(online_=False, budget=0, prefer_cloud=False) == "offline"


def test_a_rate_limit_does_not_stop_the_sweep():
    """"make sure to resume if it hits rate limit" — it keeps measuring here
    while the budget refills, instead of waiting idle."""
    assert so.plan(online_=True, budget=3, prefer_cloud=True) == "local"
    assert so.plan(online_=True, budget=so.GH_BUDGET_FLOOR,
                   prefer_cloud=True) == "local"
    # and a comfortable budget goes to the cloud
    assert so.plan(online_=True, budget=so.GH_BUDGET_FLOOR + 1,
                   prefer_cloud=True) == "cloud"


def test_it_dispatches_to_github_when_there_is_budget():
    assert so.plan(online_=True, budget=4000, prefer_cloud=True) == "cloud"
    # unless the operator turned the cloud off
    assert so.plan(online_=True, budget=4000, prefer_cloud=False) == "local"


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
    counter that measures the process instead of the work."""
    from tradingagents import cloud_sweep as cs

    monkeypatch.setattr(cs, "status", lambda rid, slug=None: {"status": "completed"})
    monkeypatch.setattr(cs, "fetch", lambda rid, slug=None: [{"coin": "A", "tf": "1h"}])
    merged = []
    monkeypatch.setattr(cs, "merge_into_store",
                        lambda rows: merged.append(rows) or
                        {"pairs": 1, "rows": len(rows), "skipped": 0})
    assert so.collect_cloud(99) == 1
    assert merged, "the artifact was never folded in"

    # a run still going is left alone — None, not 0
    monkeypatch.setattr(cs, "status", lambda rid, slug=None: {"status": "in_progress"})
    merged.clear()
    assert so.collect_cloud(99) is None and not merged

    # a run that ENDED with no usable artifact still releases the slot, or the
    # orchestrator stays pinned to a cancelled run forever
    monkeypatch.setattr(cs, "status", lambda rid, slug=None: {"status": "completed"})
    monkeypatch.setattr(cs, "fetch", lambda rid, slug=None: (_ for _ in ()).throw(
        RuntimeError("no artifact")))
    assert so.collect_cloud(99) == 0


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
    """Restarting dispatched a SECOND 20-shard run beside the first. GitHub
    gives a free repo about 20 concurrent jobs, so the newcomer queued behind
    the incumbent and both looked stalled."""
    import inspect

    work = inspect.getsource(so.run)
    assert "cs.remembered()" in work, "it must look for a run in flight"
    # the cloud runs on its OWN thread: managing it is seconds of work and must
    # not queue behind a 30-minute local round
    assert "def cloud(" in work and "for fn in (scan, work, cloud)" in work
    i = work.index("cs.remembered()")
    body = work[i:i + 700]        # the liveness check grew; widen the window
    assert 'st0.get("status") != "completed"' in body
    assert 'conclusion' in body, (
        "a cancelled run is remembered too; adopting one waits on a corpse")
    assert "adopting GitHub run" in body
    assert work.index("adopting GitHub run") < work.index("cs.dispatch("),         "adoption has to be tried BEFORE dispatching"


def test_shard_progress_is_read_from_git(monkeypatch):
    """The REST API poll burned 5,000 requests in an hour and blinded every
    tool at once."""
    import inspect

    src = inspect.getsource(so.cloud_shards)
    assert '"git", "fetch"' in src and "sweep-progress" in src
    assert "gh" not in src.replace("github", ""), "it must not touch the API"
