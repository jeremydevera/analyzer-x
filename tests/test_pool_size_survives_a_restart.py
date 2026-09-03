"""A restart must not lock the whole run to a fraction of the machine.

Sep 03, 2026, the operator: *"WHAT'S TAKING THIS SO LONG, ITS BEEN STUCK AT 85%
SINCE YESTERDAY"*.

It was not stuck. The run had crashed twice and restarted, and each restart
re-counts `done` from zero: the ~3,690 pairs already measured are skipped in
minutes, so the counter sprints to 89% and then appears to freeze on the 429
pairs that had never been measured at all. The freeze was real work, but it was
running on THREE of eleven cores — because the 3:30pm restart sampled free
memory while the dead run's workers were still being reaped (3.9 GB), sized the
pool to 3, and kept it. Minutes later 5.6 GB was free and nine cores idled while
two workers sat pegged at 100%.

Measured on 3 cores: 15 pairs/hour, 28.6 hours for what was left.
"""
from tradingagents import db_jobs as dj


def test_the_pool_is_sized_on_settled_memory_not_the_worst_instant(monkeypatch):
    """The dying predecessor's memory comes back within seconds."""
    seq = iter([3.9, 4.4, 5.6, 5.6, 5.6, 5.6])
    monkeypatch.setattr(dj, "free_ram_gb", lambda: next(seq, 5.6))
    monkeypatch.setattr(dj.time, "sleep", lambda *_: None)
    assert dj.free_ram_settled(seconds=8, every=2) == 5.6


def test_a_machine_that_will_not_say_is_not_guessed_at(monkeypatch):
    """0 or less means unknown, and unknown must leave the run alone."""
    monkeypatch.setattr(dj, "free_ram_gb", lambda: 0.0)
    monkeypatch.setattr(dj.time, "sleep", lambda *_: None)
    assert dj.free_ram_settled(seconds=8, every=2) == 0.0
    # ... and workers_for_ram then keeps every core it was offered
    assert dj.workers_for_ram(11, ["15m"], free_gb=None) >= 1


def test_settled_memory_buys_back_cores():
    """The measurement from the incident: 3.9 GB gave 3 workers, 5.6 gave 7."""
    tfs = ["15m", "30m", "1h", "4h"]
    assert dj.workers_for_ram(11, tfs, free_gb=3.9) == 3
    assert dj.workers_for_ram(11, tfs, free_gb=5.6) > 3


def test_the_job_actually_uses_the_settled_figure():
    import inspect

    src = inspect.getsource(dj._run_backtest_inner)
    assert "free_ram_settled()" in src
    # and the REASON printed beside the count must use the same figure, or the
    # screen explains a number it did not compute (label-must-match-data)
    assert src.count("free_gb=_free if _free > 0 else None") == 2
