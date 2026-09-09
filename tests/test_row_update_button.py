"""A row's own UPDATE button — force THIS backtest forward, now.

Operator, 2026-09-09, having searched #SW8Q96E6 and opened it:

    "currently the last backtest was Aug 24, 2026 4:00pm / can i have a button
     'update' to force update the backtest"

That row is STBL 4h. Its watermark really was stale — measured through
Aug 28, 2026 12:00am while the store held candles to Sep 09, 2026 4:00am, so
**73 four-hour bars** had printed since nobody re-measured it.

WHY IT MEASURES THE PAIR AND NOT THE ONE COMBINATION: the store keeps one row
file and one watermark per (coin, timeframe). Bringing a single row forward
would leave the pair's other rows measured through an older bar than the
pair's own watermark claims — a store that lies about itself.

WHY IT RUNS HERE AND NOT ON THE FLEET: measuring moved to GitHub for the
MARKET GRID (`LOCAL_SWEEP_KINDS`), but twenty machines take longer to spin up
than one pair takes to measure. It resumes from the watermark, so only the
bars printed since are walked.

WHAT PRESSING IT FOR REAL FOUND (harddev, 2026-09-09): the measurement landed
— watermark Aug 28 → Sep 09 4:00pm, 8,774 rows — and the REINDEX died on
"database is locked", because a full index rebuild holds the write lock far
longer than `_connect`'s 60-second wait (rows_winrate alone takes 912 s). The
row on screen would have kept August's numbers under a job that said it
finished.
"""
import inspect

import pytest

from tradingagents import db_jobs as dj


@pytest.fixture(autouse=True)
def _own_state(tmp_path, monkeypatch):
    """Never touch the operator's real job files or failure ledger."""
    from tradingagents import pending_ledger as pl

    monkeypatch.setattr(pl, "STATE_DIR", tmp_path)
    monkeypatch.setitem(dj.FILES, "pairbt", {
        "progress": tmp_path / "p.json", "spec": tmp_path / "s.json",
        "pid": tmp_path / "pid", "stop": tmp_path / "STOP"})


def _wire(monkeypatch, *, rows=3, boom=None, index=7, index_boom=None):
    from tradingagents import market_sweep as msw, rows_index as ri

    seen = {}

    def _run_pair(sym, tf, **kw):
        seen.update(sym=sym, tf=tf, **kw)
        if boom:
            raise boom
        return {"rows": [{}] * rows}

    monkeypatch.setattr(msw, "run_pair", _run_pair)
    monkeypatch.setattr(msw, "pair_watermark", lambda c, tf: 1_700_000_000_000)
    monkeypatch.setattr(msw, "ROWDIR", tmpdir_of(msw))
    tries = {"n": 0}

    def _index(path, con=None):
        tries["n"] += 1
        if index_boom:
            raise index_boom
        return index

    monkeypatch.setattr(ri, "index_pair", _index)
    monkeypatch.setattr(ri, "stale_pairs", lambda: [])
    monkeypatch.setattr(dj.time, "sleep", lambda *_: None)
    return seen, tries


def tmpdir_of(msw):
    return msw.ROWDIR


def _progress():
    import json

    return json.loads(dj.FILES["pairbt"]["progress"].read_text())


# ------------------------------------------------------- what it measures
def test_it_measures_the_pair_resuming_from_the_watermark(monkeypatch):
    seen, _ = _wire(monkeypatch)
    dj._run_pairbt({"coin": "STBL", "tf": "4h", "base": 5.0, "days": 365})
    assert seen["sym"] == "STBL_USDT" and seen["tf"] == "4h"
    assert seen["fresh"] is False, "an update RESUMES; it never starts over"


def test_the_threshold_count_matches_the_sweep(monkeypatch):
    """CLAUDE.md: the store stamps its version as `signals<N>-th<K>`, so two
    paths using different K reset each other's store on every alternation.
    `run_pair` defaults to 1; `grid_from_store` uses 3."""
    seen, _ = _wire(monkeypatch)
    dj._run_pairbt({"coin": "STBL", "tf": "4h"})
    assert seen["thresholds"] == 3

    sig = inspect.signature(
        __import__("tradingagents.backtest_report", fromlist=["x"]).grid_from_store)
    assert sig.parameters["thresholds"].default == 3, \
        "the sweep's K moved — this button must move with it"


def test_a_bare_coin_is_turned_into_a_symbol(monkeypatch):
    """`run_pair` passes the name straight to `klines`; a bare coin raises
    `no Min15 candles for CETUS` (2026-09-02)."""
    seen, _ = _wire(monkeypatch)
    dj._run_pairbt({"coin": "STBL", "tf": "4h"})
    assert seen["sym"] == "STBL_USDT"


# ------------------------------------------------------------ the index
def test_it_reindexes_the_pair_so_the_row_actually_changes(monkeypatch):
    _wire(monkeypatch, index=42)
    dj._run_pairbt({"coin": "STBL", "tf": "4h"})
    got = _progress()
    assert got["indexed"] == 42
    assert not got.get("index_error")


def test_a_locked_index_is_retried(monkeypatch):
    """A full rebuild holds the write lock far longer than the 60 s
    `_connect` waits — measured live on STBL 4h."""
    import sqlite3

    _seen, tries = _wire(monkeypatch,
                         index_boom=sqlite3.OperationalError("database is locked"))
    dj._run_pairbt({"coin": "STBL", "tf": "4h"})
    assert tries["n"] == 3, "it must try more than once before giving up"


def test_a_locked_index_says_WAITING_not_FAILED(monkeypatch):
    """The measurement landed; only the index is behind, and a pair whose file
    moved is picked up by `stale_pairs`. "FAILED" reads as work to redo."""
    import sqlite3

    from tradingagents import rows_index as ri

    _wire(monkeypatch, index_boom=sqlite3.OperationalError("database is locked"))

    class _P:
        stem = "STBL-4h"

    monkeypatch.setattr(ri, "stale_pairs", lambda: [_P()])
    dj._run_pairbt({"coin": "STBL", "tf": "4h"})
    got = _progress()
    assert got["index_queued"] is True
    assert "waiting on the index" in got["note"]
    assert "FAILED" not in got["note"]


def test_an_index_that_is_NOT_queued_still_says_it_failed(monkeypatch):
    """Only claim self-healing when the catch-up really has the pair."""
    import sqlite3

    _wire(monkeypatch, index_boom=sqlite3.OperationalError("locked"))
    dj._run_pairbt({"coin": "STBL", "tf": "4h"})
    got = _progress()
    assert got["index_queued"] is False
    assert "NOT indexed" in got["note"]


# ----------------------------------------------------------- the failure
def test_a_failed_measure_lands_on_the_pending_books(monkeypatch):
    """A forced update that failed IS a backtest that had a problem
    (2026-09-09), so RESOLVE PENDING must be able to retry it."""
    from tradingagents import pending_ledger as pl

    _wire(monkeypatch, boom=RuntimeError("klines returned 0 bars"))
    dj._run_pairbt({"coin": "STBL", "tf": "4h"})
    got = pl.pending("backtest")
    assert len(got) == 1
    assert got[0]["symbol"] == "STBL_USDT" and got[0]["timeframe"] == "4h"
    assert "klines returned 0 bars" in got[0]["why"]
    assert "RuntimeError" in _progress()["error"], \
        "the TYPE is named: str(MemoryError()) is empty"


def test_a_success_takes_the_pair_off_the_books(monkeypatch):
    from tradingagents import pending_ledger as pl

    pl.record("backtest", [("STBL_USDT", "4h", "worker: boom")])
    _wire(monkeypatch)
    dj._run_pairbt({"coin": "STBL", "tf": "4h"})
    assert pl.count("backtest") == 0


def test_no_new_bars_says_so(monkeypatch):
    """Pressed twice in a row, the second press must not imply it did work."""
    _wire(monkeypatch)
    dj._run_pairbt({"coin": "STBL", "tf": "4h"})
    assert "already current" in _progress()["note"]


def test_the_job_is_routed():
    src = inspect.getsource(dj.main)
    assert 'elif kind == "pairbt":' in src
    assert "pairbt" in dj.FILES
    assert "pairbt" not in dj.LOCAL_SWEEP_KINDS, \
        "one pair is not the market grid; the fleet switch must not block it"


# ------------------------------------------------------------- the route
def test_the_route_resolves_a_row_id_to_its_pair():
    src = inspect.getsource(
        __import__("tradingagents.api", fromlist=["x"]).strategy_row_update)
    assert "ri.clean_row_id" in src
    assert 'dj.start("pairbt"' in src
    # one at a time — two runs rewrite the same row index
    assert 'dj.status("pairbt")' in src and "409" in src
    # and an id nobody has is a 404, not a silent no-op
    assert "404" in src


def test_the_button_is_on_the_row_and_reads_from_the_job():
    body = open("webapp/src/components/backtest/StrategiesPanel.tsx",
                encoding="utf-8").read()
    assert "UPDATE THIS BACKTEST" in body
    assert "api.strategyRowUpdate" in body
    # the label comes from the JOB, so "UPDATING…" cannot outlive the work
    assert 'pairJob?.running ? "UPDATING…"' in body
    # and an index that could not be written must reach the screen
    assert "pairJob.index_error" in body


def test_every_job_kind_can_be_watched():
    """A kind in `db_jobs.FILES` but not in `api.JOB_KINDS` is a job that
    STARTS and cannot be followed: `/api/jobs/pairbt` answered "unknown job
    kind" while the job it names was running, so the row's UPDATE button could
    never see its own work finish (2026-09-09, caught by pressing it)."""
    from tradingagents import api as api_mod

    missing = set(dj.FILES) - set(api_mod.JOB_KINDS)
    assert not missing, f"cannot be watched: {sorted(missing)}"


def test_it_MERGES_and_never_replaces_the_pair_file(monkeypatch):
    """THE DATA-LOSS BUG (2026-09-09). `run_pair`'s `merge` defaults to FALSE,
    which REPLACES the pair's row file with only what this run produced — and
    a combination that takes no trade writes no row. The first version of this
    button cut STBL 4h from 120 signals to 37, deleting 83 of them including
    the operator's own #SW8Q96E6 (macddiv). market_sweep says it in words:
    "with save_pair_rows would delete every combination not yet reached"."""
    import inspect

    from tradingagents import market_sweep as msw

    assert inspect.signature(msw.run_pair).parameters["merge"].default is False, \
        "if this default ever flips, the comment below stops being the reason"
    seen, _ = _wire(monkeypatch)
    dj._run_pairbt({"coin": "STBL", "tf": "4h"})
    assert seen["merge"] is True, \
        "a re-measure must ADD to the pair, never replace it"
