"""UPDATE ALL BACKTESTS must not sit silent while it reads the candle store.

Pressed on `Sep 12, 2026 1:55am`. The panel said **"starting"** and nothing
else for **9 minutes 39 seconds**; `db_btupdate.log` was untouched the whole
time (mtime still `Sep 06, 2026 9:42am`) and every one of its five lines
appeared at once when the process exited at `2:05am`. The only way to learn
what it was doing was py-spy on the pid:

    read_text (pathlib/_local.py:546)
    candle_coverage (tradingagents/market_sweep.py:1456)
    stored_symbols (tradingagents/db_jobs.py:1724)
    _run_btupdate (tradingagents/db_jobs.py:1750)

`candle_coverage()` opens and JSON-parses EVERY candle file -- 5,235 files,
1.77 GB on a mechanical G: -- to build first/last/bars strings that
`stored_symbols` throws away, keeping the one field the FILENAME already
carries. Measured after the fix, same store, same answer of 1,054 contracts:
**86.8 s cold, 0.4 s warm**, against 579 s.

Three separate faults, one per section below, each already a rule in
CLAUDE.md that had not reached these four buttons:

* a long phase PUBLISHES while it runs, or it is indistinguishable from a
  stall ("a job that cannot start must SAY SO");
* a detached job's log must not be block-buffered, or it appears only at
  exit, which is exactly when nobody needs it (RCA-2026-09-10-C);
* the expensive walk is not needed at all -- two other callers already carry
  a comment saying never to use `candle_coverage` for this.
"""
from __future__ import annotations

import ast
import inspect
import json

import pytest

from tradingagents import db_jobs as dj, market_sweep as msw


# ------------------------------------------------- 1. it does not open them
def _calls(fn) -> set:
    """Every function name called in `fn`'s body, read from the AST -- never a
    string search, because this module's own DOCSTRINGS quote the banned call
    and a grep matches the warning as readily as the offence."""
    src = inspect.getsource(fn)
    tree = ast.parse("if 1:\n" + "\n".join("    " + ln
                                           for ln in src.splitlines()))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute):
                out.add(f.attr)
            elif isinstance(f, ast.Name):
                out.add(f.id)
    return out


def test_listing_the_store_does_not_open_every_candle_file():
    called = _calls(dj.stored_symbols)
    assert "candle_coverage" not in called, (
        "candle_coverage parses 1.77 GB to return names the filenames carry")
    assert "candle_index" in called, "the incremental, cached listing"


def test_it_still_answers_with_symbols_not_bare_coins(tmp_path, monkeypatch):
    """`run_pair` takes `CETUS_USDT` and strips `_USDT` itself. Handing it the
    bare coin makes every combination raise `no Min15 candles for CETUS` --
    which is what a hand-built spec did on 2026-09-03."""
    got = _store(tmp_path, monkeypatch,
                 {"CETUS_USDT-15m": 900, "CETUS_USDT-1h": 900,
                  "BTC_USDT-4h": 900})
    assert got == ["BTC_USDT", "CETUS_USDT"], got
    assert not [s for s in got if s.endswith("-15m")], "symbols, not pairs"


def _store(tmp_path, monkeypatch, bars_by_pair: dict) -> list:
    candles = tmp_path / "candles"
    candles.mkdir()
    monkeypatch.setattr(msw, "CANDLES", candles)
    monkeypatch.setattr(msw, "INDEX_PATH", tmp_path / "candle_index.json")
    for pair, n in bars_by_pair.items():
        ts = [1_700_000_000_000 + i * 3_600_000 for i in range(n)]
        (candles / f"{pair}.json").write_text(json.dumps(
            {"t": ts, "o": [1.0] * n, "h": [1.0] * n,
             "l": [1.0] * n, "c": [1.0] * n, "v": [1.0] * n}))
    return dj.stored_symbols()


def test_a_pair_file_with_no_candles_is_not_a_pair(tmp_path, monkeypatch):
    """The one thing a filename cannot tell you. A zero-bar file handed to
    `run_pair` raises on every combination and the coin is counted FAILED, so
    dropping it is not a nicety -- `candle_coverage` skipped these too
    (`if not ts: continue`) and the replacement has to keep doing it."""
    got = _store(tmp_path, monkeypatch,
                 {"GOOD_USDT-1h": 500, "EMPTY_USDT-1h": 0})
    assert got == ["GOOD_USDT"], got


def test_a_coin_is_kept_when_any_one_of_its_timeframes_has_bars(
        tmp_path, monkeypatch):
    got = _store(tmp_path, monkeypatch,
                 {"HALF_USDT-15m": 0, "HALF_USDT-4h": 120})
    assert got == ["HALF_USDT"], got


# --------------------------------------------- 2. it says so while it works
def test_the_job_publishes_a_phase_before_the_long_listing():
    """"starting" for 9m39s is a stall to everyone reading the screen. The
    write must come BEFORE the call, or it publishes the phase it has already
    finished."""
    src = inspect.getsource(dj._run_btupdate)
    assert '"now": "reading the candle store"' in src
    where_write = src.index("reading the candle store")
    where_call = src.index("coins = stored_symbols()")
    assert where_write < where_call, (
        "the phase is published after the work it describes")


def test_the_listing_reports_how_long_it_took():
    """A duration in the log is what turns 'it felt slow' into a measurement
    the next reader can act on -- this incident took py-spy to diagnose
    precisely because no phase had ever timed itself."""
    src = inspect.getsource(dj._run_btupdate)
    assert "listed in" in src and "t_list" in src


# ------------------------------------------------ 3. the log is not buffered
def test_a_detached_job_writes_its_log_as_it_goes():
    """Python block-buffers stdout when it is a FILE. Without this the log is
    written when the process EXITS, which is the one moment it is no longer
    needed. `rows_index.spawn_indexer` had this and a test for it since
    RCA-2026-09-10-C; the four buttons did not."""
    src = inspect.getsource(dj.start)
    assert '"PYTHONUNBUFFERED": "1"' in src
    # and it must actually reach Popen -- setting it in a dict nothing passes
    # is the shape of every "fixed but not wired" bug in this repo
    tree = ast.parse("if 1:\n" + "\n".join("    " + ln
                                           for ln in src.splitlines()))
    popen = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)
             and n.func.attr == "Popen"]
    assert popen, "db_jobs.start no longer launches the job with Popen"
    assert any(kw.arg == "env" for kw in popen[0].keywords), \
        "the unbuffered environment is built and never handed to the child"


def test_the_log_still_goes_to_the_jobs_own_file():
    """Unbuffering must not become DEVNULL by another route."""
    src = inspect.getsource(dj.start)
    assert "subprocess.DEVNULL" not in src
    assert "stdout=logf" in src and "stderr=logf" in src
    assert 'db_{kind}.log' in src


@pytest.mark.parametrize("kind", ["download", "backtest", "btupdate",
                                  "collect"])
def test_every_button_gets_it(kind):
    """One `start()` launches all of them, so there is no per-kind branch that
    could miss out -- this asserts the four the operator presses are served by
    that single path."""
    assert kind in dj.FILES
    assert dj.FILES[kind]["progress"].name == f"db_{kind}.json"
