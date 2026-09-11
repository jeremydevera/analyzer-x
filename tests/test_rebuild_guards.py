"""A six-hour rebuild must not be thrown away at its last gate.

`rows_index.rebuild()` had no production caller until Sep 12, 2026, when the
operator asked for 6,845,648 newly measured rows to appear in Stored
strategies and the only path fast enough was a full rebuild (~6 h against a
measured 175 s/pair × 5,179 stale pairs = 252 h for the incremental sync).

Three gaps, each of which spends the six hours and then discards the result.
"""
import json

import pytest

from tradingagents import rows_index as ri


@pytest.fixture
def store(tmp_path, monkeypatch):
    from tradingagents import market_sweep as msw

    rows_dir = tmp_path / "rows"
    rows_dir.mkdir()
    monkeypatch.setattr(msw, "ROWDIR", rows_dir)
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    return rows_dir


def _row(coin, tf="1h", signal="cx_veto", profit=1.0):
    return {"coin": coin, "tf": tf, "signal": signal, "th": 0.0, "sl": 1.0,
            "tp": 2.0, "rr": 2.0, "sizing": "flat", "lev": 20, "base": 5.0,
            "notional": 100.0, "trades": 12, "wins": 9, "losses": 3,
            "winrate": 75.0, "profit": profit, "funding": 0.0, "h1": 0.5,
            "h2": 0.5, "green": 1, "months": 1, "worst": -1.0, "dd": 1.0,
            "liqs": 0, "stop_reachable": True, "days": 30, "bars": 720,
            "monthly": {"2026-09": profit}, "cost_of_tp": 5.0, "rt": 0.05,
            "gate": "ok", "last_ms": 1_788_000_000_000}


def test_one_unreadable_file_does_not_discard_the_whole_rebuild(store):
    """THE FAILURE THIS WAS WRITTEN FOR. `index_pair` returns 0 on a file it
    cannot parse — BEFORE writing that pair's summary row — and the loop used
    to count it anyway, so the final gate read `pairs 3 vs 4`, deleted the
    partial, and the re-run met the same file. A collect rewrites ~1,800 pair
    files an hour while the loader reads them, so a half-written file is not
    a theory."""
    for coin in ("AAA", "BBB", "CCC"):
        (store / f"{coin}-1h.json").write_text(json.dumps([_row(coin)]),
                                               encoding="utf-8")
    (store / "HOT-1h.json").write_text("{ this file is half written",
                                       encoding="utf-8")

    got = ri.rebuild(resume=False, keep_backup=False)

    assert got["rebuilt"] is True, got.get("why")
    assert got["pairs"] == 3, "the three readable pairs counted"
    assert got["skipped"] == ["HOT-1h.json"], \
        "the unreadable file is NAMED, never silently dropped (rule 20)"
    assert ri.query(signal="cx_veto")["total"] == 3


def test_an_EMPTY_pair_file_still_counts(store):
    """`[]` is a real measurement — the trade floor kept nothing — and
    index_pair files its summary for it. It returns 0 rows like an unreadable
    file does, so telling them apart by the return value alone would drop a
    legitimate pair and fail the gate the other way."""
    (store / "AAA-1h.json").write_text(json.dumps([_row("AAA")]),
                                       encoding="utf-8")
    (store / "EMPTY-1d.json").write_text("[]", encoding="utf-8")

    got = ri.rebuild(resume=False, keep_backup=False)

    assert got["rebuilt"] is True, got.get("why")
    assert got["pairs"] == 2, "the empty pair is measured, not missing"
    assert got["skipped"] == []


def test_the_swap_queues_the_indexes_it_just_destroyed(store, monkeypatch):
    """The new file carries KEEP_INDEXES only. Five on-demand indexes had
    already cost hours on the operator's store — and `rows_signal` is what
    makes their `signal=cx_veto` filter answer at all — so a rebuild that
    does not queue them leaves the panel 503-ing on its own features."""
    called = []
    monkeypatch.setattr(ri, "_after_fill_indexes",
                        lambda: called.append(True) or ["rows_signal"])
    (store / "AAA-1h.json").write_text(json.dumps([_row("AAA")]),
                                       encoding="utf-8")

    got = ri.rebuild(resume=False, keep_backup=False)

    assert called, "the swap must queue the on-demand indexes"
    assert got["indexes_queued"] == ["rows_signal"]


def test_a_six_hour_job_can_be_spawned_with_a_log():
    """CLAUDE.md, bought on Sep 10, 2026: a long-running process writes a log.
    `main()` took --build and resolve only, so a rebuild could run only inline
    in a shell somebody had to keep open."""
    import inspect

    src = inspect.getsource(ri.main)
    assert '"--rebuild"' in src
    assert "rebuild(resume=" in src, "and it must be resumable by default"
