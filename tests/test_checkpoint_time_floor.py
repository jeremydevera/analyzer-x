"""A checkpoint happens at most once every CHECKPOINT_MIN_S per worker.

Aug 26, 2026 1:17am on the PC: the data home had moved to G:, a spinning
1 TB HDD. Eleven workers each rewrote a 5.8 MB state file plus the rows file
every 200 combinations -- ~89 rewrites per pair -- and the disk sat at 502%
busy. The workers spent their time blocked in those writes (0 CPU-seconds and
0 completed writes in a 10 s sample): a pair that took ~90 s on the SSD in the
afternoon took ~23 minutes, 162 pairs in 5.7 hours instead of ~1,400.

The count-based cadence was sized for a Mac SSD where 200 combinations is a
second of work. The floor makes the cadence about TIME: a crash still costs at
most CHECKPOINT_MIN_S of work, and a slow disk gets breathing room between
writes instead of a queue of them. CHECKPOINT_MIN_S = 0 restores the old
behaviour exactly.
"""
from tradingagents import market_sweep as msw


def test_the_floor_exists_and_is_a_real_pause():
    assert 10.0 <= msw.CHECKPOINT_MIN_S <= 120.0


def test_a_checkpoint_is_not_due_until_the_floor_has_passed(monkeypatch):
    monkeypatch.setattr(msw, "CHECKPOINT_MIN_S", 30.0)
    now = 1000.0
    assert msw.checkpoint_due(last_at=now - 5.0, now=now) is False
    assert msw.checkpoint_due(last_at=now - 29.9, now=now) is False
    assert msw.checkpoint_due(last_at=now - 30.0, now=now) is True
    assert msw.checkpoint_due(last_at=now - 600.0, now=now) is True


def test_a_zero_floor_is_the_old_every_200_behaviour(monkeypatch):
    monkeypatch.setattr(msw, "CHECKPOINT_MIN_S", 0.0)
    assert msw.checkpoint_due(last_at=1000.0, now=1000.0) is True


def test_the_loop_uses_the_floor_and_resets_it_after_each_write():
    src = open("tradingagents/market_sweep.py", encoding="utf-8").read()
    ck = src.index("done_combos % CHECKPOINT_EVERY")
    window = src[ck:ck + 400]
    assert "checkpoint_due(" in window, "the count alone must not trigger a write"
    assert "last_ckpt" in window and "save_states(" in window and "merge_pair_rows(" in window
    # the hand-off save is a checkpoint too, so it resets the clock as well.
    # Anchored on the CALL SITE inside the loop, not on the def -- the first
    # `handoff_pending()` in the file is the function itself.
    ho = src.index("and handoff_pending():")
    assert "last_ckpt" in src[ho:ho + 500]
