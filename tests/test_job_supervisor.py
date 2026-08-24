"""A crashed sweep must restart itself.

The operator, after a 3,960-pair run died at 11.8% and stayed dead for hours:
"if it fails it should have automatic retry and you did not even think of it".
Per-pair checkpointing was already there, so a restart resumes — nothing ever
did the restarting.
"""

import json
import os

import pytest

from tradingagents import db_jobs as dj


@pytest.fixture
def crashed(monkeypatch):
    """A job whose progress says running while its pid is long gone."""
    f = dj.FILES["backtest"]
    f["progress"].write_text(json.dumps({"running": True, "done": 466,
                                         "total": 3960, "now": "AXS 15m"}))
    f["spec"].write_text(json.dumps({"coins": ["BTC_USDT"], "tfs": ["1h"],
                                     "base": 5.0, "days": 365, "fresh": True}))
    f["pid"].write_text("999999")            # a pid that cannot be alive
    dj.RETRY_FILE.write_text("{}")
    started = []
    monkeypatch.setattr(dj, "start",
                        lambda kind, spec: started.append((kind, spec)) or 4242)
    monkeypatch.setattr(dj, "free_gb", lambda path=None: 50.0)
    return started


def test_a_crashed_job_is_restarted_from_its_checkpoint(crashed):
    got = dj.resume_if_died("backtest")
    assert got["resumed"] is True and got["pid"] == 4242
    kind, spec = crashed[0]
    assert kind == "backtest"
    assert spec["fresh"] is False, (
        "a crash is not a click on BACKTEST — resuming must not start over")
    assert spec["coins"] == ["BTC_USDT"], "it must reuse the original spec"


def test_a_finished_job_is_never_restarted(crashed):
    dj.FILES["backtest"]["progress"].write_text(json.dumps(
        {"running": False, "rows": 41190, "finished": 1787326445}))
    assert dj.resume_if_died("backtest")["resumed"] is False
    assert not crashed, "it restarted a job that had already finished"


def test_a_job_stopped_by_the_operator_is_never_restarted(crashed):
    dj.FILES["backtest"]["progress"].write_text(json.dumps(
        {"running": False, "stopped": True, "finished": 1787326445}))
    assert dj.resume_if_died("backtest")["resumed"] is False
    assert not crashed


def test_a_live_job_is_left_alone(crashed):
    dj.FILES["backtest"]["pid"].write_text(str(os.getpid()))   # very much alive
    assert dj.resume_if_died("backtest")["resumed"] is False
    assert not crashed, "it restarted a job that was still running"


def test_it_will_not_restart_into_the_disk_that_killed_it(crashed, monkeypatch):
    """The sweep died BECAUSE the volume filled. Relaunching into 0.4 GB just
    kills it again, and the crash log spends the last of the space."""
    monkeypatch.setattr(dj, "free_gb", lambda path=None: 0.4)
    got = dj.resume_if_died("backtest")
    assert got["resumed"] is False
    assert "0.4 GB free" in got["why"] and "waiting" in got["why"]
    assert not crashed
    # and it resumes by itself once there is room again
    monkeypatch.setattr(dj, "free_gb", lambda path=None: 50.0)
    assert dj.resume_if_died("backtest")["resumed"] is True


def test_retries_are_bounded(crashed):
    for i in range(dj.MAX_RETRIES):
        assert dj.resume_if_died("backtest")["attempt"] == i + 1
    got = dj.resume_if_died("backtest")
    assert got["resumed"] is False and "gave up" in got["why"], (
        "a crash loop that re-reads the same broken state looks like progress")
    assert len(crashed) == dj.MAX_RETRIES


def test_a_manual_start_gets_a_fresh_budget(crashed):
    for _ in range(dj.MAX_RETRIES):
        dj.resume_if_died("backtest")
    assert dj.resume_if_died("backtest")["resumed"] is False
    dj.clear_retries("backtest")
    assert dj.resume_if_died("backtest")["resumed"] is True


def test_the_sweep_stops_cleanly_before_the_disk_is_gone():
    """A fatal OSError mid-write loses the pair in flight and writes no
    terminal record at all — the operator found the dead job hours later."""
    import inspect

    src = inspect.getsource(dj._run_backtest_inner)
    assert "free_gb() < DISK_FLOOR_GB" in src, "no guard before the disk goes"
    assert "_LowDisk" in src
    # the terminal record has to say paused, not failed, and keep the work
    assert '"paused": True' in src
    assert "resumes by" in src


def test_the_api_runs_the_supervisor():
    import inspect

    from tradingagents import api

    src = inspect.getsource(api._keep_the_row_index_current)
    assert "resume_if_died" in src, "nothing is watching for crashed jobs"


def test_a_finished_sweep_is_never_discarded_over_a_missing_name():
    """A run measured all six pairs, then died with `failed: 'report_name'` and
    threw the whole payload away. The same failure is in the operator's feed
    from the day before. A report always has somewhere to go."""
    import inspect

    # comments stripped: the docstring and the explanatory comment both quote
    # the banned expression, and matching those is testing documentation
    src = "\n".join(ln for ln in
                    inspect.getsource(dj._run_backtest_inner).splitlines()
                    if not ln.lstrip().startswith("#"))
    assert 'spec["report_name"]' not in src, "a bare lookup can still KeyError"
    assert 'spec.get("report_name") or spec.get("name")' in src
    assert '"archive.html"' in src, "there must be a fallback name"


def test_the_report_name_gets_an_html_suffix():
    """The operator's own spec passes `name: retry-proof`; writing that
    without .html produces a file the report list cannot open."""
    import inspect

    src = "\n".join(ln for ln in
                    inspect.getsource(dj._run_backtest_inner).splitlines()
                    if not ln.lstrip().startswith("#"))
    i = src.index('spec.get("report_name")')
    assert '.html' in src[i:i + 400], src[i:i + 200]


def test_a_dropped_connection_resumes_but_a_broken_spec_does_not(crashed):
    """The operator's internet went down mid-sweep on 2026-08-24. The job died
    with `transport failure: <urlopen error [Errno 8] nodename nor servname
    provided>`, RECORDED it, and the supervisor read that as "this job ended" —
    leaving 3,000 measured pairs while the network was already back.

    Retrying a deterministic error is a crash loop wearing progress's clothes;
    retrying a transient one is the reason a supervisor exists."""
    f = dj.FILES["backtest"]

    f["progress"].write_text(json.dumps({
        "running": False, "finished": 1787000000, "transient": True,
        "error": "transport failure: <urlopen error [Errno 8] nodename nor "
                 "servname provided, or not known>"}))
    assert dj.died_unfinished("backtest") is True
    assert dj.resume_if_died("backtest")["resumed"] is True

    # a deterministic failure is left alone, however many times it happens
    crashed.clear()
    dj.clear_retries("backtest")
    f["progress"].write_text(json.dumps({
        "running": False, "finished": 1787000000, "transient": False,
        "error": "'report_name'"}))
    assert dj.died_unfinished("backtest") is False
    assert dj.resume_if_died("backtest")["resumed"] is False
    assert not crashed


def test_transient_is_decided_by_type_not_by_reading_the_message():
    """The flag is written where the exception is caught. A supervisor that
    pattern-matched an error string later would be reading a label instead of
    the thing that produced it."""
    import inspect

    assert dj.is_transient(OSError("[Errno 8] nodename nor servname provided"))
    assert dj.is_transient(TimeoutError("timed out"))
    assert dj.is_transient(ConnectionError("connection reset by peer"))
    # MEXC's own rate-limit wording, from the runner's log
    assert dj.is_transient(Exception("510 Requests are too frequent"))
    # and the deterministic ones stay deterministic
    assert not dj.is_transient(KeyError("report_name"))
    assert not dj.is_transient(ValueError("started without coins"))
    assert not dj.is_transient(ZeroDivisionError("division by zero"))

    src = inspect.getsource(dj.died_unfinished)
    assert 'prog.get("transient")' in src, "it must read the flag"
    for word in ("urlopen", "nodename", "timed out"):
        assert word not in src, f"died_unfinished is matching on {word!r}"


# ------------------------------------------------------- hand off to the cloud
# The operator: "create a button 'switch to github actions', if i click that,
# finish the current task then switch to github actions after its done".
def test_a_handoff_is_not_a_stop(crashed):
    """It must finish the pairs in flight and keep every measured one. A plain
    STOP records "nothing was saved" and leaves the unmeasured coins to
    nobody."""
    import inspect

    src = inspect.getsource(dj._run_backtest_inner)
    assert 'handoff_requested("backtest")' in src, "the job must notice it"
    i = src.index('handoff_requested("backtest")')
    assert "_HandOff" in src[i:i + 200], "and raise the handoff, not a stop"

    # the handler sits beside _LowDisk in the inner function, which is where
    # grid_from_store is called from
    assert "_HandOff" in src
    assert '"handoff": True' in src, "the record must say handed off"
    # and it must NOT reuse the stop wording, which claims nothing was saved
    hand = src[src.index("except _HandOff"):src.index("except _LowDisk")]
    assert "nothing was saved" not in hand
    assert "kept" in hand


def test_the_handoff_flag_round_trips():
    assert dj.handoff_requested("backtest") is False
    dj.request_handoff("backtest")
    assert dj.handoff_requested("backtest") is True
    dj.clear_handoff("backtest")
    assert dj.handoff_requested("backtest") is False


def test_the_cloud_only_gets_coins_the_mac_never_reached(monkeypatch, tmp_path):
    """merge_into_store REPLACES the pairs it covers, so re-measuring a
    finished pair in the cloud would land rows behind the Mac's own watermark —
    and the next local update would extend a measurement it never made."""
    from tradingagents import cloud_sweep as cs, market_sweep as msw

    marks = {("DONE", "1h"): 1787450400000, ("DONE", "4h"): 1787450400000,
             ("HALF", "1h"): 1787450400000, ("HALF", "4h"): 0}
    monkeypatch.setattr(msw, "pair_watermark",
                        lambda coin, tf: marks.get((coin, tf), 0))

    left = cs.unmeasured(["DONE_USDT", "HALF_USDT", "NEW_USDT"], ["1h", "4h"])
    assert left == ["HALF_USDT", "NEW_USDT"], left

    # and the merge refuses a pair that is already measured
    saved = []
    monkeypatch.setattr(msw, "save_pair_rows",
                        lambda c, tf, rs: saved.append((c, tf)))
    got = cs.merge_into_store([
        {"coin": "DONE", "tf": "1h", "profit": 1.0},
        {"coin": "NEW", "tf": "1h", "profit": 2.0}])
    assert saved == [("NEW", "1h")], saved
    assert got["pairs"] == 1 and got["skipped"] == 1
    assert "DONE 1h" in got["skipped_pairs"]
    assert "watermark" in got["why_skipped"]


def test_the_handoff_waits_for_the_local_job_to_stand_down(monkeypatch):
    """Dispatching while it was still finishing would have both measuring the
    same pairs."""
    from tradingagents import api, cloud_sweep as cs

    dj.FILES["backtest"]["spec"].write_text(json.dumps(
        {"coins": ["A_USDT", "B_USDT"], "tfs": ["1h"]}))
    dj.request_handoff("backtest")
    sent = []
    monkeypatch.setattr(cs, "dispatch",
                        lambda **kw: sent.append(kw) or {"id": 1})
    monkeypatch.setattr(cs, "remember", lambda run: None)
    monkeypatch.setattr(cs, "unmeasured", lambda coins, tfs: list(coins))

    monkeypatch.setattr(dj, "status", lambda kind: {"running": True})
    api._finish_handoff()
    assert not sent, "it dispatched while the local job was still running"
    assert dj.handoff_requested("backtest"), "and it must stay requested"

    monkeypatch.setattr(dj, "status", lambda kind: {"running": False})
    api._finish_handoff()
    assert sent and sent[0]["coins"] == 2
    assert not dj.handoff_requested("backtest"), "served requests are cleared"


def test_a_handoff_with_nothing_left_does_not_dispatch(monkeypatch):
    from tradingagents import api, cloud_sweep as cs

    dj.FILES["backtest"]["spec"].write_text(json.dumps(
        {"coins": ["A_USDT"], "tfs": ["1h"]}))
    dj.request_handoff("backtest")
    sent = []
    monkeypatch.setattr(cs, "dispatch", lambda **kw: sent.append(kw) or {"id": 1})
    monkeypatch.setattr(cs, "unmeasured", lambda coins, tfs: [])
    monkeypatch.setattr(dj, "status", lambda kind: {"running": False})
    api._finish_handoff()
    assert not sent, "there was nothing for the cloud to do"
    assert not dj.handoff_requested("backtest")


def test_a_handoff_the_job_cannot_serve_says_stuck(monkeypatch):
    """It sat on "finishing the current pairs, then handing over" for 19
    minutes on 2026-08-25. The job had started before the hand-off code
    existed, so no code in that process could ever notice the flag — and the
    badge reported patience instead of a problem."""
    import time

    from tradingagents import api
    from tradingagents import cloud_sweep as cs

    monkeypatch.setattr(cs, "available", lambda: (True, ""))
    monkeypatch.setattr(dj, "status", lambda kind: {"running": True})
    dj.request_handoff("backtest")

    fresh = api.job_handoff_state("backtest")
    assert fresh["requested"] is True and fresh["stalled"] is False

    # age the request past the threshold
    f = dj.FILES["backtest"]["handoff"]
    old = time.time() - api.HANDOFF_STALL_SECONDS - 60
    import os

    os.utime(f, (old, old))
    late = api.job_handoff_state("backtest")
    assert late["stalled"] is True
    assert "stood down" in late["stalled_why"]
    assert "loses nothing" in late["stalled_why"], "it must say what to do"

    # once the job stops, it is no longer stuck — it is waiting to dispatch
    monkeypatch.setattr(dj, "status", lambda kind: {"running": False})
    assert api.job_handoff_state("backtest")["stalled"] is False


def test_a_handoff_with_no_github_says_so(monkeypatch):
    """gh's keyring token had expired, so the dispatch had nowhere to go."""
    from tradingagents import api
    from tradingagents import cloud_sweep as cs

    monkeypatch.setattr(cs, "available",
                        lambda: (False, "gh is not logged in (token invalid)"))
    monkeypatch.setattr(dj, "status", lambda kind: {"running": True})
    got = api.job_handoff_state("backtest")
    assert got["available"] is False
    assert "not logged in" in got["why"]
