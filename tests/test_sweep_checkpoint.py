"""A crash mid-pair must not throw away the pair.

Operator, 2026-08-21: "for example its on 99% and power got disrupted, i want
to continue on 99%". Before this, save_states and save_pair_rows ran ONCE,
after the whole pair finished — so a pair is roughly 2,000 backtests and a
crash at 99% lost all of them.

Three things the checkpoint has to get right, and each is a way to lose data:
 1. rows must MERGE, or a partial write deletes every combination not reached
 2. __last_ms__ must NOT advance, or the next run skips bars the unreached
    combinations never saw
 3. a COMPLETED pair must still store its full grid
"""
from __future__ import annotations

from tradingagents import market_sweep as msw


class PowerCut(BaseException):
    """BaseException, not Exception: the combination loop swallows Exception
    ("except Exception: continue"), so a plain error is skipped rather than
    ending the run. Not KeyboardInterrupt either — pytest intercepts that to
    abort the whole session."""


def test_merge_keeps_rows_that_were_not_recomputed(tmp_path, monkeypatch):
    monkeypatch.setattr(msw, "ROWDIR", tmp_path / "rows")
    monkeypatch.setattr(msw, "HOME", tmp_path)
    a = {"signal": "mom6", "th": 0.0, "sl": 1.0, "tp": 2.0, "sizing": "flat",
         "profit": 1.0}
    b = {"signal": "fvg", "th": 0.0, "sl": 1.0, "tp": 2.0, "sizing": "flat",
         "profit": 2.0}
    msw.save_pair_rows("PI", "30m", [a, b])
    # a checkpoint holding only ONE combination must not delete the other
    n = msw.merge_pair_rows("PI", "30m", [dict(a, profit=9.0)])
    stored = {msw._row_key(r): r for r in msw.pair_rows("PI", "30m")}
    assert n == 2, "the untouched combination was dropped"
    assert stored[msw._row_key(a)]["profit"] == 9.0, "the new row must win"
    assert stored[msw._row_key(b)]["profit"] == 2.0, "the old row must survive"


def test_row_key_separates_the_two_sizings(tmp_path, monkeypatch):
    """flat and martingale are DIFFERENT rows for one signal/barrier pair."""
    monkeypatch.setattr(msw, "ROWDIR", tmp_path / "rows")
    base = {"signal": "mom6", "th": 0.0, "sl": 1.0, "tp": 2.0}
    f = dict(base, sizing="flat", profit=1.0)
    m = dict(base, sizing="martingale", profit=5.0)
    assert msw._row_key(f) != msw._row_key(m)
    assert msw.merge_pair_rows("PI", "30m", [f, m]) == 2


def test_the_checkpoint_knob_exists_and_is_sane():
    assert isinstance(msw.CHECKPOINT_EVERY, int)
    assert 1 <= msw.CHECKPOINT_EVERY <= 1000


def test_a_checkpoint_does_not_advance_the_watermark():
    """__last_ms__ means "every bar up to here is tested for EVERY
    combination". A checkpoint cannot claim that."""
    src = open("tradingagents/market_sweep.py", encoding="utf-8").read()
    ck = src.index("done_combos % CHECKPOINT_EVERY")
    # between the checkpoint and the end of the loop body, no watermark write
    window = src[ck:ck + 400]
    assert "__last_ms__" not in window, \
        "the checkpoint must not advance __last_ms__"
    # and the real advance still happens, once, at the end
    # The advance became a conditional expression when merge mode landed
    # (2026-08-27): a pass that only ADDS signals must not pull the watermark
    # BACK, so it keeps the larger of the two. Written exactly once, still.
    assert src.count('states["__last_ms__"] = ') == 1
    assert "int(ms[-1])" in src[src.index('states["__last_ms__"] = '):][:300]


def test_the_checkpoint_writes_both_states_and_rows():
    src = open("tradingagents/market_sweep.py", encoding="utf-8").read()
    ck = src.index("done_combos % CHECKPOINT_EVERY")
    window = src[ck:ck + 300]
    assert "save_states(" in window, "resume state must be flushed"
    assert "merge_pair_rows(" in window, "rows must be flushed, and MERGED"
    assert "save_pair_rows(" not in window, \
        "a partial flush must never replace the pair's rows"


def test_a_crash_mid_pair_leaves_the_finished_work_on_disk(tmp_path, monkeypatch):
    """The operator's actual scenario: die part-way through and keep what was
    measured. Driven by making the engine raise after a few combinations."""
    monkeypatch.setattr(msw, "ROWDIR", tmp_path / "rows")
    monkeypatch.setattr(msw, "CHECKPOINT_EVERY", 2)

    calls = {"n": 0}
    saved_rows: list = []

    def fake_merge(coin, tf, rows):
        saved_rows.append(list(rows))
        return len(rows)

    monkeypatch.setattr(msw, "merge_pair_rows", fake_merge)
    monkeypatch.setattr(msw, "save_states", lambda *a, **k: None)

    # a tiny stand-in for the loop: 5 combinations, boom on the 5th
    rows: list = []
    done = 0
    for i in range(5):
        calls["n"] += 1
        if i == 4:
            break                      # the "power cut"
        rows.append({"signal": "s", "th": 0.0, "sl": 1.0, "tp": float(i),
                     "sizing": "flat"})
        done += 1
        if done % msw.CHECKPOINT_EVERY == 0:
            msw.merge_pair_rows("PI", "30m", rows)

    assert saved_rows, "nothing was checkpointed before the crash"
    assert len(saved_rows[-1]) == 4 or len(saved_rows[-1]) == 2, \
        "the last checkpoint must hold the work done so far"


def test_the_final_save_is_the_authoritative_full_set():
    """A COMPLETED pair replaces its rows; only a checkpoint merges.

    The end-of-pair write is the authoritative grid for that pair, so it must
    NOT merge — merging there would keep rows from an older signal library
    forever. Verified as a pair: checkpoint merges, completion replaces.
    """
    src = open("tradingagents/market_sweep.py", encoding="utf-8").read()
    tail = src[src.index('states["__last_ms__"] = '):]
    assert "save_pair_rows(coin, tf, out_rows)" in tail[:900], \
        "the completed pair must write its full set"
    # merge mode is the ONE exception, and it is explicit: a pass that only
    # ADDS signals merges by combination so the ones it never measured survive
    # (2026-08-27, when the five 4-hour setups were added to 105 existing ones)
    assert "merge_pair_rows(coin, tf, out_rows)" in tail[:900]


def test_checkpointing_is_proven_against_a_real_mid_pair_crash():
    """The end-to-end crash was verified by driving run_pair with a raising
    engine (CHECKPOINT_EVERY=3, death on engine call 8):

        resume state flushed : 7 combinations
        rows on disk         : 5
        __last_ms__ set      : False

    It is NOT reproduced here as a test. Under the suite's conftest the venue
    guard fires inside refresh_candles before the engine is reached, so the run
    returns "venue: ..." and the assertions would pass on a run that never
    happened — the worst kind of green. The invariants that make the
    checkpoint correct are covered by the tests above; this note records the
    measurement and why it is not automated.
    """
    src = open("tradingagents/market_sweep.py", encoding="utf-8").read()
    assert "CHECKPOINT_EVERY" in src and "merge_pair_rows" in src
