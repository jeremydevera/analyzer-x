"""Measuring runs on GitHub Actions; the store stays on this machine.

Operator, Sep 05, 2026: *"i WILL FULLY TRANSITION TO GITHUB ACTIONS INSTEAD OF
MY PC meaning there will be no option 'this mac'"*.

One switch decides it — `capacity.LOCAL_SWEEPS` — and this file covers the
three ways the old behaviour could survive it:

* the PLANNER handing this PC a timeframe anyway (tested in
  test_backtest_capacity_and_logs.py),
* a JOB started around the planner — the BACKTEST button called
  `db_jobs.start("backtest")`, which never consulted capacity at all,
* the ORCHESTRATOR's own measuring thread (tested in
  test_sweep_orchestrator.py), which called `local_round` every tick with
  nothing consulted.

Two measurement bugs found while moving it, both older than the move:

* the shard hardcoded `BASE_MARGIN = 5.0` while the local job took `base` from
  the Backtest screen. Every dollar figure the fleet measured was at a stake
  nobody chose, and the UPDATE button had been dispatching that way already.
* the hand-off dispatched with `days` left at its 365 default, so a 60-day
  local sweep became a 365-day cloud run — two different measurements written
  into one store, with no column anywhere saying which was which.
"""
from __future__ import annotations

import inspect

import pytest

from tradingagents import capacity as cap, cloud_sweep as cs, db_jobs as dj


# ------------------------------------------------------------- the job guard
def test_a_from_scratch_sweep_will_not_start_here():
    """The BACKTEST button's old path. It never asked capacity, so the switch
    alone would not have stopped it — a stale browser tab or a curl still
    would have measured on this PC."""
    with pytest.raises(dj.LocalSweepsOff) as exc:
        dj.start("backtest", {"coins": ["A_USDT"], "tfs": ["15m"]})
    said = str(exc.value)
    assert "GitHub" in said, "the refusal must say where it runs now"
    assert "store" in said.lower(), "and that the data did not move"


def test_the_jobs_that_are_not_measuring_still_run():
    """Scope. `download` writes the candle store, which lives here; `stratbt`
    is ONE combination for the deploy check (rule 21) and a round trip to the
    fleet would make that rule unusable; `btupdate` IS the dispatcher — block
    it and nothing reaches GitHub at all."""
    for kind in ("download", "stratbt", "btupdate"):
        assert kind not in dj.LOCAL_SWEEP_KINDS, \
            f"{kind} is not a market-wide measurement"
    assert "backtest" in dj.LOCAL_SWEEP_KINDS


def test_the_guard_lifts_with_the_switch(monkeypatch):
    """One constant, reversible — not a change scattered through the module."""
    monkeypatch.setattr(cap, "LOCAL_SWEEPS", True)
    monkeypatch.setattr(dj, "status", lambda k: {"running": True, "pid": 4242})
    assert dj.start("backtest", {}) == 4242, \
        "with the switch on, the old path works exactly as before"


def test_the_api_calls_it_a_refusal_not_a_crash():
    """409, not 500. Nothing is broken — this machine simply does not measure,
    and a 500 would send the operator to the logs looking for a stack trace."""
    src = inspect.getsource(__import__("tradingagents.api", fromlist=["x"]).job_start)
    assert "LocalSweepsOff" in src
    assert "409" in src


# --------------------------------------------------------------- the stake
def test_the_dispatch_carries_the_operators_stake(monkeypatch):
    """`base` is not decoration: every dollar figure in the grid is measured at
    it. The shard hardcoded 5.0."""
    sent: list = []
    monkeypatch.setattr(cs, "available", lambda: (True, "me/repo"))
    monkeypatch.setattr(cs, "_gh", lambda *a, **k: sent.append(a) or "")
    # The same run id before and after, so `dispatch` never sees a new one and
    # gives up. Without the sleep patch it waits 30 x 2s for a run this test is
    # not pretending to start — a 60-second unit test.
    monkeypatch.setattr(cs.time, "sleep", lambda s: None)
    monkeypatch.setattr(cs, "_runs", lambda slug, limit=1: [{"databaseId": 9}])
    # the run never appears (same id before and after), so dispatch gives up
    # with its own error — we only want the arguments it sent on the way
    with pytest.raises(cs.CloudError):
        cs.dispatch(shards=2, coins=0, timeframes="15m", days=60, base=25.0)
    flat = [x for call in sent for x in call]
    assert "base=25.0" in flat, flat
    assert "days=60" in flat, flat


def test_the_shard_reads_the_stake_it_was_given():
    src = (__import__("pathlib").Path(".github/scripts/sweep_shard.py")
           .read_text(encoding="utf-8"))
    assert 'os.environ.get("BASE_MARGIN")' in src, \
        "the shard must take the stake from the dispatch"
    assert "BASE_MARGIN = 5.0\n" not in src, "the hardcoded stake is gone"


def test_the_workflow_offers_the_input_and_passes_it_on():
    y = (__import__("pathlib").Path(".github/workflows/sweep.yml")
         .read_text(encoding="utf-8"))
    assert "\n      base:\n" in y, "the workflow must accept a base margin"
    assert "BASE_MARGIN: ${{ github.event.inputs.base }}" in y, \
        "and hand it to the shard's environment"


def test_every_dispatch_that_has_a_stake_sends_it():
    """The update job and the hand-off both have the spec in hand. Sending the
    default instead is how the fleet measured at $5 while the screen said
    something else."""
    upd = inspect.getsource(dj._run_btupdate)
    assert 'base=float(spec.get("base")' in upd

    # the hand-off, read from the file rather than guessing its function name
    from pathlib import Path

    api_src = Path("tradingagents/api.py").read_text(encoding="utf-8")
    i = api_src.index("[handoff]")
    block = api_src[max(0, i - 2000):i + 2000]
    assert 'base=float(spec.get("base")' in block, \
        "the hand-off measures the same sweep and must use the same stake"
    assert 'days=int(spec.get("days")' in block, \
        "and the same window — 365 by default turned a 60-day sweep into a year"


def test_a_crashed_local_sweep_is_not_quietly_restarted(monkeypatch):
    """The caller one level up — the bug harddev exists for.

    The API ticks `resume_if_died("backtest")` every cycle. With the guard in
    `start()` alone it would take a LocalSweepsOff a minute forever, and a
    resume is the silent route back to measuring here.
    """
    monkeypatch.setattr(dj, "died_unfinished", lambda k: True)
    got = dj.resume_if_died("backtest")
    assert got["resumed"] is False
    assert "GitHub" in got["why"]


def test_a_crashed_download_still_resumes(monkeypatch):
    """Scope again: the candle store lives here, so its job still recovers."""
    monkeypatch.setattr(dj, "died_unfinished", lambda k: k == "download")
    monkeypatch.setattr(dj, "free_gb", lambda path=None: 500.0)
    monkeypatch.setattr(dj, "_retries", lambda k: 0)
    monkeypatch.setattr(dj, "_set_retries", lambda k, n: None)
    monkeypatch.setattr(dj, "_read", lambda p: {"coins": ["A_USDT"]})
    monkeypatch.setattr(dj, "start", lambda kind, spec: 7777)
    assert dj.resume_if_died("download")["resumed"] is True


def test_a_refused_dispatch_measures_nothing_here(monkeypatch):
    """The loudest hole: `_run_btupdate` handed every frame BACK to this PC
    when GitHub refused, which would have started a full local sweep."""
    src = inspect.getsource(dj._run_btupdate)
    i = src.index("GitHub refused the dispatch")
    assert "cap.LOCAL_SWEEPS" in src[:i], \
        "the fallback must ask whether this PC is still in the rota"
    assert "NOTHING was measured" in src[i:i + 900], \
        "and must say so rather than silently sweeping here"


def test_the_cloud_only_finish_never_claims_a_run_it_did_not_start():
    """label-must-match-data: "all of it went to GitHub" printed for a
    dispatch that was refused is a true sentence about a run that never was."""
    src = inspect.getsource(dj._finish_btupdate_cloud_only)
    assert "nothing = not plan.get(\"cloud\")" in src
    assert "NOTHING was measured" in src
    assert '"errors": 1 if nothing else 0' in src, \
        "a sweep that measured nothing is an error, not a tidy finish"


def test_use_cloud_false_cannot_reinstate_the_option(monkeypatch):
    """A spec field that forces everything local is the removed option wearing
    a different name."""
    src = inspect.getsource(dj._run_btupdate)
    i = src.index('spec.get("use_cloud"')
    assert "not cap.LOCAL_SWEEPS" in src[max(0, i - 300):i + 300], \
        "use_cloud=False must be honoured only while this PC is in the rota"
