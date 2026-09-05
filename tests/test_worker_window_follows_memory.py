"""The pool follows memory WHILE it runs — cautious up, prompt down.

Sep 03, 2026: a crash at 3:30pm restarted the sweep while the dead run's
workers were still being reaped. Free RAM read 3.9 GB, the pool sized itself to
3 of 11 cores, and stayed on 3 for the next 28 hours — two workers pegged at
100% of one core, nine cores idle, 5.6 GB free. `free_ram_settled` fixed the
STARTUP reading; this fixes the rest of the run.

Asymmetric on purpose. Growing one pair at a time keeps the ramp gentle enough
that the 1 GB emergency stop stays unfired; shrinking all at once is what keeps
a real squeeze from reaching it. Grow-only would leave nothing between a
genuine squeeze and a run that quits at 91%.
"""
import pytest

from tradingagents import backtest_report as br, db_jobs as dj


# ------------------------------------------------------------ pure arithmetic
@pytest.mark.parametrize("now,target,cap,want", [
    (3, 7, 11, 4),      # grow ONE step, never straight to the target
    (3, 4, 11, 4),
    (7, 7, 11, 7),      # already there
    (7, 3, 11, 3),      # shrink ALL THE WAY, at once
    (11, 1, 11, 1),
    (3, 0, 11, 1),      # never below one: a run must not stall
    (3, 99, 11, 4),     # never above the cap, even growing
    (11, 20, 11, 11),
    (1, 1, 1, 1),
])
def test_the_window_grows_by_one_and_shrinks_at_once(now, target, cap, want):
    assert br.next_window(now, target, cap) == want


def test_a_machine_that_will_not_report_is_left_alone():
    """`plan_workers` returning None means unknown — never a resize."""
    assert br.next_window(5, None, 11) == 5


# ------------------------------------------------ the loop actually follows it
def test_the_in_flight_window_follows_the_plan(monkeypatch, tmp_path):
    """Drive the real loop with a scripted plan and watch in-flight follow.

    The plan says 1, then 3. With eight pairs and a cap of 11, the number of
    pairs in flight must start at 1 and climb one per completed pair to 3 —
    never eight, which is what submitting everything up front did.
    """
    from tradingagents import market_sweep as msw

    seen: list = []

    def fake_run_pair(sym, tf, **kw):
        return {"rows": [], "coin": sym.replace("_USDT", ""), "tf": tf}

    monkeypatch.setattr(msw, "run_pair", fake_run_pair)
    monkeypatch.setattr(msw, "completed_pairs", lambda pairs: set())
    monkeypatch.setattr(msw, "worker_clear", lambda: None)

    plan = iter([1, 1, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3])

    def plan_workers():
        return next(plan, 3)

    def watch(n_inflight):
        seen.append(n_inflight)

    br._measure_pairs(
        [(f"C{i}_USDT", "15m") for i in range(8)],
        cap=11, plan_workers=plan_workers, on_window=watch,
        base_margin=5.0, days=365, thresholds=None, fresh=False,
        on_done=lambda *a: None, on_failed=lambda *a: None,
        serial=True)

    assert seen[0] == 1, f"must start at the plan's figure, got {seen}"
    assert max(seen) <= 3, f"must never exceed the plan, got {seen}"
    # one step per completed pair, never a jump
    assert all(b - a <= 1 for a, b in zip(seen, seen[1:], strict=False)), seen
    assert 3 in seen, f"must reach the plan's figure, got {seen}"


def test_a_shrink_takes_effect_at_once(monkeypatch):
    from tradingagents import market_sweep as msw

    monkeypatch.setattr(msw, "run_pair", lambda s, t, **k: {"rows": []})
    monkeypatch.setattr(msw, "completed_pairs", lambda pairs: set())
    monkeypatch.setattr(msw, "worker_clear", lambda: None)

    seen: list = []
    plan = iter([5, 5, 5, 1, 1, 1, 1, 1, 1, 1])
    br._measure_pairs(
        [(f"C{i}_USDT", "15m") for i in range(8)],
        cap=11, plan_workers=lambda: next(plan, 1),
        on_window=seen.append,
        base_margin=5.0, days=365, thresholds=None, fresh=False,
        on_done=lambda *a: None, on_failed=lambda *a: None, serial=True)
    # it climbed, then dropped to 1 in ONE step rather than easing down
    hi = max(seen)
    assert hi > 1, seen
    drop = [b for a, b in zip(seen, seen[1:], strict=False) if b < a]
    assert 1 in drop, f"the shrink must land on 1 immediately, got {seen}"


# ------------------------------------------------------- the label follows too
def test_the_published_reason_names_the_memory_it_used(monkeypatch):
    """A frozen "3.9 GB free" beside a live "RAM 5.6/16 GB free" is a label
    arguing with its own data (label-must-match-data)."""
    free = [3.9]
    monkeypatch.setattr(dj, "free_ram_gb", lambda: free[0])
    p = dj.make_worker_planner(cores_offered=11, tfs=["15m", "30m", "1h", "4h"])
    assert p.plan() == 3
    assert "3.9 GB free" in p.why

    # memory frees up: the count rises AND the sentence beside it is rewritten
    free[0] = 5.6
    assert p.plan() > 3
    assert "5.6 GB free" in p.why, p.why
    assert "3.9" not in p.why, "the startup reading must not outlive its number"

    # and when nothing is being held back there is nothing to explain: the
    # reason goes EMPTY rather than keeping the last squeeze's sentence
    free[0] = 9.9
    assert p.plan() == 11
    assert p.why == "", p.why


def test_an_unreadable_machine_never_resizes(monkeypatch):
    monkeypatch.setattr(dj, "free_ram_gb", lambda: 0.0)
    p = dj.make_worker_planner(cores_offered=11, tfs=["15m"])
    assert p.plan() is None, "unknown must not move the window"


# ------------------------------------------------- rebuilding on a big shrink
def test_a_large_shrink_rebuilds_the_pool():
    """Measured on this machine: an idle pool worker holds 86 MB and never
    gives it back — ProcessPoolExecutor does not reap idle workers. A shrink
    from 11 to 3 therefore strands 8 x 86 = 692 MB, which is more than one
    worker's whole budget, in processes doing nothing. During a memory squeeze
    that is exactly the memory the shrink was trying to release.

    So a shrink big enough to strand a worker's worth of memory tears the pool
    down and builds a new one at the new width. A small shrink does not: a
    rebuild costs every worker's imports again.
    """
    assert br.wants_rebuild(peak=11, want=3, per_worker_gb=0.5) is True
    assert br.wants_rebuild(peak=11, want=9, per_worker_gb=0.5) is False
    # never for a GROW, and never when nothing was stranded
    assert br.wants_rebuild(peak=3, want=7, per_worker_gb=0.5) is False
    assert br.wants_rebuild(peak=3, want=3, per_worker_gb=0.5) is False


def test_the_rebuild_waits_for_the_pairs_in_flight(monkeypatch):
    """A pool cannot be torn down under running work, so the rebuild happens
    once the pairs already measuring have finished — nothing is discarded."""
    from tradingagents import market_sweep as msw

    monkeypatch.setattr(msw, "run_pair", lambda s, t, **k: {"rows": []})
    monkeypatch.setattr(msw, "completed_pairs", lambda pairs: set())
    monkeypatch.setattr(msw, "worker_clear", lambda: None)

    rebuilt: list = []
    # climb to 8 (one step per completed pair), then the floor drops to 1:
    # 7 stranded workers x 86 MB = 602 MB, past one worker's 500 MB budget
    plan = iter([8] * 9 + [1] * 30)
    done: list = []
    br._measure_pairs(
        [(f"C{i}_USDT", "15m") for i in range(18)],
        cap=11, plan_workers=lambda: next(plan, 1),
        base_margin=5.0, days=365, thresholds=None, fresh=False,
        on_done=lambda s, t, r: done.append((s, t)),
        on_failed=lambda *a: None, serial=True,
        rebuild=lambda want: rebuilt.append(want),
        per_worker_gb=0.5)
    assert rebuilt, "a shrink from 8 to 1 must rebuild"
    assert rebuilt[0] == 1
    # and every pair still got measured — a rebuild loses no work
    assert len(done) == 18, done
