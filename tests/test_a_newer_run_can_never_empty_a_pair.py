"""A newer measurement may add and overwrite. It may never SHRINK a pair.

Sep 10-11, 2026. The operator: *"so you mean there are backtest from my
previous days that was lost?"* — and the answer, from their own index copies,
was yes:

    pairs that GAINED rows   4,214   (+39,370,830)
    pairs that LOST rows       267   (-1,261,358)
    of those, EMPTIED          100

    GPNSTOCK-15m   18,880 -> 0        SUPRA-15m    21,780 -> 0
    GPNSTOCK-30m   20,880 -> 0        WDAYSTOCK-15m 19,520 -> 0
    DVNSTOCK-15m   20,880 -> 4,720    KKRSTOCK-1h   19,440 -> 0

Nothing was wrong with the lost measurements. A later shard produced FEWER
rows for those pairs, because `run_pair`'s cost gate skips a barrier whose
round-trip cost is half its take-profit or more — and the coins' spreads were
wide when the shard happened to run. Two ways to be expensive, both measured:

* a tokenized stock outside US market hours: PSXSTOCK read **1.287%** at 1am
  New York and **0.263%** with the market open;
* a thin alt whose book is always wide: UTILITY-1h costs **3.5866%**, so of the
  1h grid's eleven targets only the 8% one cleared the gate.

Then `cloud_sweep.land_rows` wrote that smaller set with `save_pair_rows`,
which REPLACES the file. Freshness had been judged by `is_fresher`, which
compares watermarks — when a run ENDED, nothing about what it holds.

`merge_pair_rows` has existed all along, and the LOCAL sweep has always used
it; its own docstring says `save_pair_rows` "would delete every combination not
yet reached". The cloud path used the destructive writer instead.
"""
from __future__ import annotations

import pytest

from tradingagents import cloud_sweep as cs, market_sweep as msw


def _row(signal="willr14", sl=1.0, tp=1.2, sizing="flat", **kw):
    r = {"id": f"{signal}{sl}{tp}{sizing}", "coin": "AAA", "tf": "15m",
         "signal": signal, "th": 0.0, "sl": sl, "tp": tp, "sizing": sizing,
         "trades": 90, "wins": 70, "losses": 20, "winrate": 77.7,
         "profit": 45.5, "last_ms": 1_700_000_000_000, "monthly": {}}
    r.update(kw)
    return r


@pytest.fixture()
def store(tmp_path, monkeypatch):
    rows_dir, states = tmp_path / "rows", tmp_path / "states"
    rows_dir.mkdir()
    states.mkdir()
    monkeypatch.setattr(msw, "ROWDIR", rows_dir)
    monkeypatch.setattr(msw, "STATES", states)
    monkeypatch.setattr(msw, "LOCKS", tmp_path / "locks", raising=False)
    return tmp_path


def _stored():
    return msw.pair_rows("AAA", "15m")


def test_a_newer_but_emptier_run_keeps_every_stored_row(store):
    """GPNSTOCK's 18,880 rows, in miniature: a run that measured NOTHING for
    the pair must not empty it."""
    full = [_row(sl=s, tp=t) for s in (0.5, 1.0) for t in (1.2, 2.0, 3.0)]
    msw.save_pair_rows("AAA", "15m", full)
    msw.save_states("AAA", "15m", {"__last_ms__": 1_600_000_000_000})

    got = cs.land_rows("AAA", "15m", [],
                       marks=[{"last_ms": 1_800_000_000_000}])
    assert len(_stored()) == 6, f"{len(_stored())} rows left of 6"
    assert got in {"kept", "empty", "stale"}


def test_a_newer_smaller_run_keeps_what_it_did_not_measure(store):
    """The general case: the gate skipped the tight targets, so the run comes
    back with one row. The other five stay."""
    full = [_row(sl=1.0, tp=t) for t in (0.4, 0.6, 1.0, 1.2, 2.0, 3.0)]
    msw.save_pair_rows("AAA", "15m", full)
    msw.save_states("AAA", "15m", {"__last_ms__": 1_600_000_000_000})

    cs.land_rows("AAA", "15m",
                 [_row(sl=1.0, tp=3.0, profit=99.0,
                       last_ms=1_800_000_000_000)])
    after = _stored()
    assert len(after) == 6, f"the file shrank to {len(after)}"
    # the re-measured combination WINS
    fresh = [r for r in after if r["tp"] == 3.0]
    assert len(fresh) == 1 and fresh[0]["profit"] == 99.0
    # and the ones it never looked at are untouched
    assert sorted(r["tp"] for r in after) == [0.4, 0.6, 1.0, 1.2, 2.0, 3.0]


def test_a_FIRST_measurement_may_still_write_nothing(store):
    """The 1d incident (2026-08-26): a pair whose every combination fell under
    the trade floor legitimately stores an empty file, and the state file
    beside it is what says "measured". That must keep working."""
    got = cs.land_rows("AAA", "15m", [],
                       marks=[{"last_ms": 1_800_000_000_000}])
    assert _stored() == []
    assert got in {"empty", "kept"}
    assert msw.pair_watermark("AAA", "15m") == 1_800_000_000_000, \
        "the watermark still has to advance, or the pair re-sweeps for ever"


def test_the_shrink_is_impossible_by_construction(store):
    """Not "we remembered to check" — the writer cannot express a shrink.
    `merge_pair_rows` unions by combination, so the result is never smaller
    than what was stored."""
    import ast
    import inspect
    import textwrap
    # the CALLS, not the source text: the comment that explains this fix names
    # `save_pair_rows`, and a string search on it fails on the explanation
    # rather than on the code. Third time today (see
    # test_the_strategies_route_never_waits_on_status).
    tree = ast.parse(textwrap.dedent(inspect.getsource(cs.land_rows)))
    called = {getattr(n.func, "attr", None) or getattr(n.func, "id", None)
              for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert "merge_pair_rows" in called
    assert "save_pair_rows" not in called, \
        "the destructive writer must not be in the code path any more"

    before = [_row(sl=1.0, tp=t) for t in (1.0, 2.0, 3.0)]
    msw.save_pair_rows("AAA", "15m", before)
    for rows in ([], [_row(sl=1.0, tp=1.0)], [_row(sl=9.9, tp=9.9)]):
        cs.land_rows("AAA", "15m", rows,
                     marks=[{"last_ms": 1_900_000_000_000}])
        assert len(_stored()) >= len(before), \
            f"{len(_stored())} < {len(before)} after landing {len(rows)} row(s)"


def test_the_watermark_still_decides_whether_to_land_at_all(store):
    """`is_fresher` stays: an OLDER run is still refused outright, so a stale
    shard cannot overwrite fresher figures for the same combination."""
    msw.save_pair_rows("AAA", "15m", [_row(sl=1.0, tp=1.0, profit=10.0)])
    msw.save_states("AAA", "15m", {"__last_ms__": 1_900_000_000_000})
    got = cs.land_rows("AAA", "15m",
                       [_row(sl=1.0, tp=1.0, profit=-5.0,
                             last_ms=1_500_000_000_000)])
    assert got == "stale"
    assert _stored()[0]["profit"] == 10.0, "an older run overwrote a newer one"


def test_it_is_the_ONE_place_the_rule_lives(store):
    """`land_rows`'s own docstring: two paths write cloud measurements — the
    collector and the live door — and a store rule with two implementations is
    how this repo lost a week of measurements (RCA-2026-09-09-P)."""
    import inspect

    from tradingagents import live_ingest
    src = inspect.getsource(live_ingest)
    assert "save_pair_rows" not in src, \
        "the live door must land rows through land_rows, not write them itself"
