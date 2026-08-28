"""A pair whose row file is `[]` must be indexed ONCE, not forever.

Measured on the operator's store on Aug 28, 2026, straight after the index was
rebuilt from scratch: `rows_index.status()` said 4,232 of 4,232 pairs indexed,
and `stale_pairs()` still returned **758**. Every one of them was a 1d pair
whose row file is two bytes -- `[]` -- because the trade floor kept nothing on
~90 daily bars.

The cause: `index_pair` read the coin and timeframe out of `rows[0]`, so an
empty pair recorded neither, and the block that copies the state file's
watermark into the index is guarded by `if coin and tf`. The indexed `last_ms`
therefore stayed 0 while the state file carried a real one
(1787616000000), and `stale_watermark()` compares exactly those two -- so the
pair reported itself unfinished on every pass, forever. 758 pairs re-read every
cycle, producing nothing, while the operator's screen showed a backlog that
could never reach zero.

The pair KEY carries both fields ("SPX500-1d" -> SPX500, 1d) and is free.
`ensure()`'s own backfill had already learned this in August; `index_pair` had
not.
"""
from __future__ import annotations

import json

import pytest

from tradingagents import market_sweep as msw, rows_index as ri


@pytest.fixture
def store(tmp_path, monkeypatch):
    rows = tmp_path / "rows"
    states = tmp_path / "state"
    rows.mkdir()
    states.mkdir()
    monkeypatch.setattr(msw, "ROWDIR", rows)
    monkeypatch.setattr(msw, "STATES", states)
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    ri._ready.clear()
    ri.forget_indexes()
    return tmp_path


def _pair(store, pair, rows, last_ms):
    (msw.ROWDIR / f"{pair}.json").write_text(json.dumps(rows))
    coin, _, tf = pair.rpartition("-")
    (msw.STATES / f"{coin}-{tf}.json").write_text(json.dumps({
        "mom6|0|1|2|flat": {"trades": 3},
        "__last_ms__": last_ms, "__version__": "signals120-th3"}))


def test_an_empty_pair_records_its_watermark_and_stops_being_stale(store):
    """The 758-pair case, in miniature."""
    _pair(store, "SPX500-1d", [], 1_787_616_000_000)
    ri.ensure()
    ri.index_pair(msw.ROWDIR / "SPX500-1d.json")
    assert ri.stale_watermark("SPX500-1d") is False, \
        "an indexed empty pair still reports itself unfinished"
    assert ri.stale_pairs() == [], \
        "a pair with nothing to keep must not be re-read on every pass"


def test_the_empty_pair_is_still_listed_with_its_coin_and_timeframe(store):
    """It has to appear on the storage screen: 'measured, kept nothing' is a
    result, and a pair with NULL coin used to make every boot re-scan the
    whole table looking for one."""
    _pair(store, "SPX500-1d", [], 1_787_616_000_000)
    ri.ensure()
    ri.index_pair(msw.ROWDIR / "SPX500-1d.json")
    with ri._open(readonly=True) as con:
        got = con.execute("SELECT coin, tf, n, last_ms, combos FROM pairs "
                          "WHERE pair = 'SPX500-1d'").fetchone()
    assert got["coin"] == "SPX500" and got["tf"] == "1d"
    assert got["n"] == 0, "no rows kept, and it says so"
    assert got["last_ms"] == 1_787_616_000_000, "the watermark IS the answer"
    assert got["combos"] == 1, "and what was measured is still counted"


def test_a_pair_with_rows_is_unchanged(store):
    """The fix must not move what a normal pair records."""
    row = {"coin": "BTC", "tf": "1h", "signal": "mom6", "th": 0.1, "sl": 1.0,
           "tp": 2.0, "sizing": "flat", "trades": 120, "wins": 60, "losses": 60,
           "winrate": 50.0, "profit": 12.5, "days": 89, "bars": 2159}
    _pair(store, "BTC-1h", [row], 1_787_616_000_000)
    ri.ensure()
    n = ri.index_pair(msw.ROWDIR / "BTC-1h.json")
    assert n == 1
    with ri._open(readonly=True) as con:
        got = con.execute("SELECT coin, tf, n, signals, last_ms FROM pairs "
                          "WHERE pair = 'BTC-1h'").fetchone()
    assert got["coin"] == "BTC" and got["tf"] == "1h"
    assert got["n"] == 1 and got["signals"] == "mom6"
    assert got["last_ms"] == 1_787_616_000_000
    assert ri.stale_pairs() == []


def test_a_coin_name_with_a_dash_still_parses(store):
    """The key is split on the LAST dash, so a coin containing one survives."""
    _pair(store, "1000000BABYDOGE-1d", [], 1_787_616_000_000)
    ri.ensure()
    ri.index_pair(msw.ROWDIR / "1000000BABYDOGE-1d.json")
    with ri._open(readonly=True) as con:
        got = con.execute("SELECT coin, tf FROM pairs "
                          "WHERE pair = '1000000BABYDOGE-1d'").fetchone()
    assert (got["coin"], got["tf"]) == ("1000000BABYDOGE", "1d")
