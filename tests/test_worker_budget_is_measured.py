"""How much memory a worker costs is MEASURED, not guessed.

Operator, 2026-09-05, looking at 4 workers on a 12-core machine with free RAM
and a CPU at 59%: *"THAT'S THE POINT WHY ARE YOU NOT UTILIZING THE FREE CORES
AND RAM, ITS LIKE YOU ARE USING 20% OF MY PC'S POWER"*.

They were right, and the cause was a constant nobody had re-measured.
`RAM_PER_WORKER_GB` said a 15m/30m worker needs 0.5 GB. Four live workers on
that exact run measured 0.27, 0.29, 0.30 and 0.32 GB of working set (peak
0.41). With 4.0 GB free and 2.0 GB reserved for the desktop, the guess allowed
4 workers where the measurement allows 6.

Working set, not private commit: the same workers held 0.60-0.68 GB of commit,
but commit beyond RAM lives in the page file — the working set is what decides
how many fit before Windows starts paging.

Found by the harddev loop while building it, each with a test below:

* ROUND 1a — the paging guard compared plan to PLAN. The plan runs ahead of the
  window (which climbs one pair at a time), so the window kept growing to a
  stale allowance while the disk thrashed. It now freezes at what is ACTUALLY
  in flight.
* ROUND 1b — `plan()` runs after every completed pair and spawned TWO
  PowerShell processes each time, on a 4,124-pair run, to re-learn numbers that
  move slowly. Probes are cached.
* ROUND 2 — one probe coming back empty (a pool rebuild empties the worker
  list) dropped the budget from 0.32 back to the 0.50 guess: 6 workers to 4,
  and the next probe put it back. The window would saw up and down every 20
  seconds.
* ROUND 3 — the sanity check REJECTED a measurement above 4x the table and fell
  back to the table, which is the SMALLER number. That is over-subscription:
  the one direction that ends in paging and the frozen desktop of 2026-08-27.
"""
import pytest

from tradingagents import db_jobs as dj


# ------------------------------------------------------- the measurement itself
def test_a_measured_worker_beats_the_guess(monkeypatch):
    from tradingagents import market_sweep as msw, portable

    monkeypatch.setattr(msw, "worker_read", lambda: [{"pid": 1}, {"pid": 2},
                                                     {"pid": 3}, {"pid": 4}])
    monkeypatch.setattr(portable, "rss_gb",
                        lambda pids: {1: 0.268, 2: 0.295, 3: 0.298, 4: 0.316})
    got = dj.measured_per_worker_gb(["15m", "30m", "1h", "4h"])
    # the PEAK, so a pair that just started cannot drag the budget down
    assert got == pytest.approx(0.316)
    assert got < dj._per_worker_gb(["15m", "30m", "1h", "4h"])

    # and that is worth two more workers on the operator's own numbers
    assert dj.workers_for_ram(11, ["15m"], free_gb=4.0, per_worker_gb=0.5) == 4
    assert dj.workers_for_ram(11, ["15m"], free_gb=4.0, per_worker_gb=0.316) == 6


def test_one_worker_is_not_enough_evidence(monkeypatch):
    from tradingagents import market_sweep as msw, portable

    monkeypatch.setattr(msw, "worker_read", lambda: [{"pid": 1}])
    monkeypatch.setattr(portable, "rss_gb", lambda pids: {1: 0.30})
    assert dj.measured_per_worker_gb(["15m"]) is None


def test_a_worker_that_has_not_started_is_thrown_away(monkeypatch):
    """64 MB means the sample caught a process before it loaded a pair;
    believing it would licence far too many workers."""
    from tradingagents import market_sweep as msw, portable

    monkeypatch.setattr(msw, "worker_read", lambda: [{"pid": 1}, {"pid": 2}])
    monkeypatch.setattr(portable, "rss_gb", lambda pids: {1: 0.01, 2: 0.02})
    assert dj.measured_per_worker_gb(["15m"]) is None


def test_a_reading_above_the_table_is_believed_not_rejected(monkeypatch):
    """ROUND 3. Rejecting it fell back to the table — the SMALLER number — and
    over-subscribed the machine, which is how the desktop froze on 2026-08-27.
    """
    from tradingagents import market_sweep as msw, portable

    monkeypatch.setattr(msw, "worker_read", lambda: [{"pid": 1}, {"pid": 2}])
    # 3.0 GB against a 0.2 GB table for a 1d run — far above the 4x cap
    monkeypatch.setattr(portable, "rss_gb", lambda pids: {1: 3.0, 2: 2.8})
    got = dj.measured_per_worker_gb(["1d"])
    assert got is not None, "an absurd-HIGH reading must not become the table"
    assert got >= dj._per_worker_gb(["1d"]), got


# ------------------------------------------------------------- the paging guard
def test_growth_stops_while_the_machine_is_paging(monkeypatch):
    """Free memory alone cannot see this: at 108 hard faults a second there is
    memory 'free' and the machine is still reading it back off a mechanical
    disk. More workers then is slower, not faster."""
    from tradingagents import portable

    monkeypatch.setattr(dj, "free_ram_gb", lambda: 9.0)     # room for many
    monkeypatch.setattr(dj, "measured_per_worker_gb", lambda tfs: 0.3)
    monkeypatch.setattr(portable, "page_reads_per_sec", lambda: 108.0)
    p = dj.WorkerPlanner(11, ["15m"], inflight=lambda: 3)
    assert p.plan() == 3, "must freeze at what is in flight, not the allowance"
    assert "reading 108 page(s) a second" in p.why


def test_a_shrink_is_never_blocked_by_paging(monkeypatch):
    """The guard exists to stop making a squeeze worse — it must never stop
    RELIEVING one."""
    from tradingagents import portable

    monkeypatch.setattr(dj, "free_ram_gb", lambda: 2.6)     # room for 2
    monkeypatch.setattr(dj, "measured_per_worker_gb", lambda tfs: 0.3)
    monkeypatch.setattr(portable, "page_reads_per_sec", lambda: 500.0)
    p = dj.WorkerPlanner(11, ["15m"], inflight=lambda: 8)
    assert p.plan() == 2, "a shrink must go through untouched"


def test_the_guard_freezes_the_window_not_the_last_plan(monkeypatch):
    """ROUND 1a. The plan runs AHEAD of the window, so comparing plan to plan
    let the window climb to a stale allowance while the disk thrashed."""
    from tradingagents import portable

    monkeypatch.setattr(dj, "free_ram_gb", lambda: 9.0)
    monkeypatch.setattr(dj, "measured_per_worker_gb", lambda tfs: 0.3)
    monkeypatch.setattr(portable, "page_reads_per_sec", lambda: 200.0)
    window = {"n": 2}
    p = dj.WorkerPlanner(11, ["15m"], inflight=lambda: window["n"])
    assert p.plan() == 2
    window["n"] = 5                     # the window really did grow
    p._probed_at = 0.0
    assert p.plan() == 5, "it tracks the real window, not its own last answer"


def test_a_broken_window_view_never_stops_the_run(monkeypatch):
    from tradingagents import portable

    def boom():
        raise RuntimeError("gone")

    monkeypatch.setattr(dj, "free_ram_gb", lambda: 9.0)
    monkeypatch.setattr(dj, "measured_per_worker_gb", lambda tfs: 0.3)
    monkeypatch.setattr(portable, "page_reads_per_sec", lambda: 200.0)
    p = dj.WorkerPlanner(11, ["15m"], inflight=boom)
    assert p.plan() >= 1


# -------------------------------------------------------------- no flapping
def test_an_empty_probe_keeps_the_last_real_measurement(monkeypatch):
    """ROUND 2. A pool rebuild empties the worker list for a moment. Falling
    back to the guess took 0.32 -> 0.50 GB, which is 6 workers -> 4, and the
    next probe put it back: a sawtooth every 20 seconds."""
    from tradingagents import portable

    monkeypatch.setattr(dj, "free_ram_gb", lambda: 4.0)
    monkeypatch.setattr(portable, "page_reads_per_sec", lambda: 0.0)
    monkeypatch.setattr(dj, "measured_per_worker_gb", lambda tfs: 0.32)
    p = dj.WorkerPlanner(11, ["15m"])
    first = p.plan()
    assert p.measured and p.per_worker == pytest.approx(0.32)

    monkeypatch.setattr(dj, "measured_per_worker_gb", lambda tfs: None)
    p._probed_at = 0.0
    assert p.plan() == first
    assert p.per_worker == pytest.approx(0.32), "must not revert to the guess"


def test_before_anything_is_measured_the_table_is_used(monkeypatch):
    from tradingagents import portable

    monkeypatch.setattr(dj, "free_ram_gb", lambda: 4.0)
    monkeypatch.setattr(portable, "page_reads_per_sec", lambda: 0.0)
    monkeypatch.setattr(dj, "measured_per_worker_gb", lambda tfs: None)
    p = dj.WorkerPlanner(11, ["15m"])
    p.plan()
    assert not p.measured
    assert p.per_worker == dj._per_worker_gb(["15m"])
    assert "estimated" in p.why


# ------------------------------------------------------------ the probe is cheap
def test_the_probe_is_not_run_on_every_pair(monkeypatch):
    """ROUND 1b. Two PowerShell spawns per completed pair, on 4,124 pairs."""
    from tradingagents import portable

    calls = {"n": 0}

    def counted(tfs):
        calls["n"] += 1
        return 0.3

    monkeypatch.setattr(dj, "free_ram_gb", lambda: 6.0)
    monkeypatch.setattr(portable, "page_reads_per_sec", lambda: 0.0)
    monkeypatch.setattr(dj, "measured_per_worker_gb", counted)
    p = dj.WorkerPlanner(11, ["15m"])
    for _ in range(50):
        p.plan()
    assert calls["n"] == 1, f"probed {calls['n']} times for 50 pairs"


# ------------------------------------------------------- the label says which
def test_the_reason_says_whether_the_figure_was_measured(monkeypatch):
    """label-must-match-data: "0.32 GB per pair" is a different claim depending
    on whether it was measured or guessed, and the reader cannot tell
    otherwise."""
    from tradingagents import portable

    monkeypatch.setattr(dj, "free_ram_gb", lambda: 4.0)
    monkeypatch.setattr(portable, "page_reads_per_sec", lambda: 0.0)
    monkeypatch.setattr(dj, "measured_per_worker_gb", lambda tfs: 0.32)
    p = dj.WorkerPlanner(11, ["15m"])
    p.plan()
    assert "0.32 GB per pair" in p.why
    assert "measured on the live workers" in p.why


def test_rss_and_paging_answer_on_this_machine():
    """Not a mock: the two probes must actually work here, or the whole thing
    silently falls back to the guess for ever."""
    import os

    from tradingagents import portable

    got = portable.rss_gb([os.getpid()])
    assert os.getpid() in got, "this process must be readable"
    assert 0.005 < got[os.getpid()] < 8.0, got
    assert portable.page_reads_per_sec() >= 0.0
