"""A win-rate floor must SEEK its own index when it is selective (2026-08-27).

The operator typed 95 into "min win %", pressed Apply, and got two HTTP 500s
while the table kept the previous rows under the new filter.

Measured on their store (35,863,520 rows, mechanical disk):

    counted from the win-rate index   winrate >= 95     31,768   0.01 s
                                      winrate >= 90     69,064   0.01 s
                                      winrate >= 80    643,186   1.06 s
                                      winrate >= 50  7,465,262  25.50 s

    win % >= 95 ranked by profit, `+winrate` + SCAN rows_profit   never came
                                                                  back (500)
    win % >= 95 ranked by profit, seeking the win-rate index          52.32 s
    win % >= 95 AND >= 100 trades, seeking (470 matches)              0.16 s
    win % >= 50 ranked by profit, `+winrate` (21% of rows qualify)     4.10 s
                                                       -- was 25.50 s, all of
                                                       it in the unbounded
                                                       count, run TWICE

Three rules come out of that and are held here:

1. the plan follows SELECTIVITY, not the presence of a floor: seek when few
   rows qualify, step aside when most of them do
2. the count that decides it is BOUNDED at the same cap, or choosing the plan
   costs more than either plan
3. a total that came from a bound prints with the "+". "5,000 match" with no
   plus, on a filter with 7,465,262 matches, is a true number under a false
   label (label-must-match-data)
"""
import json

import pytest

import tradingagents.rows_index as ri


@pytest.fixture
def store(tmp_path, monkeypatch):
    """200 rows, 12 of them at 95%+ — selective enough to seek."""
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    ri._ready.discard(str(tmp_path / "rows.db"))
    ri.forget_indexes()
    ri.ensure()
    rows = []
    for i in range(200):
        wr = 96.0 + (i % 4) if i < 12 else 40.0 + (i % 50)
        rows.append({"id": f"R{i:04d}", "coin": "AAA", "tf": "1h",
                     "signal": "ema", "profit": float((i * 37) % 200 - 50),
                     "winrate": wr, "trades": 50 + i, "dd": 3.0,
                     "monthly": {}})
    f = tmp_path / "AAA_USDT-1h.json"
    f.write_text(json.dumps(rows), encoding="utf-8")
    with ri._open() as con:
        ri.index_pair(f, con)
    return rows


def test_a_selective_floor_seeks_its_own_index(store):
    where, args = ri._where(min_winrate=95, order_owns_index=True,
                            order_key="profit", winrate_seeks=True)
    assert where == " WHERE winrate >= ?", where     # no `+`
    assert args == [95.0]
    assert "INDEXED BY rows_wr2" in ri._indexed_by(None, True) \
        or "INDEXED BY rows_winrate" in ri._indexed_by(None, True)


def test_a_loose_floor_steps_aside_for_the_order(store):
    """At `winrate >= 50` most of the store qualifies, and sorting all of it in
    a temp b-tree did not return in 25 s while the profit scan took 1.01 s."""
    where, _ = ri._where(min_winrate=50, order_owns_index=True,
                         order_key="profit", winrate_seeks=False)
    assert where == " WHERE +winrate >= ?", where


def test_the_trade_floor_rides_the_same_index_when_it_seeks(store):
    """rows_winrate is (winrate DESC, trades, ...), so a `+trades` beside a
    seeking win-rate range throws away the second column of the index."""
    where, args = ri._where(min_winrate=95, min_trades=100,
                            order_owns_index=True, order_key="profit",
                            winrate_seeks=True)
    assert where == " WHERE trades >= ? AND winrate >= ?", where
    assert args == [100, 95.0]
    # and it still steps aside when the ORDER BY owns the plan
    plain, _ = ri._where(min_winrate=50, min_trades=100,
                         order_owns_index=True, order_key="profit")
    assert plain == " WHERE +trades >= ? AND +winrate >= ?", plain


def test_a_coin_still_outranks_the_win_rate_seek(store):
    """One index can be named, and a pair is ~10k rows against a floor's tens
    of thousands, so a named coin always drives."""
    assert ri._indexed_by("AAA", True) == " INDEXED BY rows_coin"


def test_the_deciding_count_is_bounded(store):
    """Exact under the cap, and stops walking above it."""
    assert ri._winrate_matches(95) == 12
    assert ri._winrate_matches(95, 100) == ri._winrate_matches(95, 100, cap=99)
    assert ri._winrate_matches(0, cap=5) == 6, "cap+1, so the caller sees over"
    assert ri._winrate_matches(0) == 200


def test_an_exact_total_prints_without_a_plus_and_a_bound_with_one(
        store, monkeypatch):
    got = ri.query(min_winrate=95, limit=5)
    assert (got["total"], got["total_capped"]) == (12, False)

    # now make every floor look loose: the total becomes a BOUND and must say so
    monkeypatch.setattr(ri, "WINRATE_SEEK_MAX", 3)
    monkeypatch.setattr(ri, "COUNT_CAP", 4)
    got = ri.query(min_winrate=95, limit=5)
    assert got["total_capped"] is True, "a bound must print the +"
    assert got["total"] == 4, got["total"]


def test_the_rows_are_right_whichever_plan_ran(store, monkeypatch):
    """The plan may change; the answer may not."""
    monkeypatch.setattr(ri, "WINRATE_SEEK_MAX", 1_000_000)   # seek
    seek = [r["id"] for r in ri.query(min_winrate=95, limit=50)["rows"]]
    monkeypatch.setattr(ri, "WINRATE_SEEK_MAX", 0)           # step aside
    scan = [r["id"] for r in ri.query(min_winrate=95, limit=50)["rows"]]
    assert seek == scan and len(seek) == 12, (seek, scan)
    for rid in seek:
        assert next(r for r in store if r["id"] == rid)["winrate"] >= 95


def test_the_wide_index_is_preferred_but_not_required(store, monkeypatch):
    """rows_wr2 carries the profit needed to RANK the matches, which is the
    52.32 s -> ~1 s difference. It is built on demand (45 min on the real
    store), so the narrow one must keep working meanwhile."""
    assert " INDEXED BY rows_winrate" == ri._winrate_index()
    with ri._open() as con:
        con.execute(ri.WIDE_WINRATE)
    ri.forget_indexes()
    assert " INDEXED BY rows_wr2" == ri._winrate_index()
    assert ri.query(min_winrate=95, limit=5)["total"] == 12
    with ri._open() as con:
        con.execute("DROP INDEX rows_wr2")
        con.execute("DROP INDEX rows_winrate")
    ri.forget_indexes()
    assert ri._winrate_index() == "", "neither index: no INDEXED BY at all"
    # and the query still answers, without naming an index that is not there
    assert ri.query(min_winrate=95, limit=5)["total"] == 12
