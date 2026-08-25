"""One row-less pair made every startup re-scan a 15 GB table.

The shard writes only PROFITABLE rows, so a pair whose backtest produced none
is registered in `pairs` with nothing in `rows`. The backfill read coin/tf back
out of `rows` with correlated subqueries, got NULL, left `coin` NULL -- and the
guard fired again on the next boot. On 2026-08-25 AASTOCK-30m (0 rows) held the
supervisor silent for over four minutes on every restart.
"""

from tradingagents import rows_index as ri


def _fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    ri._ready.clear()
    ri.ensure()


def test_a_pair_with_no_rows_still_gets_its_coin_and_tf(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    with ri._open() as con:
        con.execute("INSERT INTO pairs (pair, mtime, size, n, at) VALUES ('AASTOCK-30m', 0, 0, 0, 0)")
        con.commit()
    ri._ready.clear()
    ri.ensure()                                  # the backfill runs
    with ri._open() as con:
        got = con.execute("SELECT coin, tf FROM pairs "
                          "WHERE pair='AASTOCK-30m'").fetchone()
    assert tuple(got) == ("AASTOCK", "30m"), "taken from the KEY, not from rows"


def test_the_backfill_cannot_run_twice(tmp_path, monkeypatch):
    """The whole bug: coin stayed NULL, so the scan repeated on every boot."""
    _fresh(tmp_path, monkeypatch)
    with ri._open() as con:
        con.execute("INSERT INTO pairs (pair, mtime, size, n, at) VALUES ('AASTOCK-30m', 0, 0, 0, 0)")
        con.commit()
    ri._ready.clear()
    ri.ensure()
    ri._ready.clear()
    ri.ensure()
    with ri._open() as con:
        left = con.execute("SELECT COUNT(*) FROM pairs "
                           "WHERE coin IS NULL").fetchone()[0]
    assert left == 0, "nothing left to backfill, so no boot re-scans"


def test_a_coin_whose_name_contains_a_dash_splits_on_the_LAST_one(tmp_path,
                                                                 monkeypatch):
    _fresh(tmp_path, monkeypatch)
    with ri._open() as con:
        con.execute("INSERT INTO pairs (pair, mtime, size, n, at) VALUES ('SOME-COIN-4h', 0, 0, 0, 0)")
        con.commit()
    ri._ready.clear()
    ri.ensure()
    with ri._open() as con:
        got = con.execute("SELECT coin, tf FROM pairs "
                          "WHERE pair='SOME-COIN-4h'").fetchone()
    assert tuple(got) == ("SOME-COIN", "4h")


def test_signals_are_still_filled_in_when_rows_exist(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    with ri._open() as con:
        con.execute("INSERT INTO pairs (pair, mtime, size, n, at) VALUES ('APEX-1h', 0, 0, 0, 0)")
        cols = [r[1] for r in con.execute("PRAGMA table_info(rows)")]
        vals = {"pair": "APEX-1h", "coin": "APEX", "tf": "1h"}
        for sig in ("mom6", "rsi14", "mom6"):
            vals["signal"] = sig
            names = [c for c in cols if c in vals]
            con.execute(f"INSERT INTO rows ({','.join(names)}) VALUES "
                        f"({','.join('?' * len(names))})",
                        [vals[c] for c in names])
        con.commit()
    ri._ready.clear()
    ri.ensure()
    with ri._open() as con:
        sigs = con.execute("SELECT signals FROM pairs "
                           "WHERE pair='APEX-1h'").fetchone()[0]
    assert sorted((sigs or "").split("\n")) == ["mom6", "rsi14"]
