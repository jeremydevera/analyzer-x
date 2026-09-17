"""A progress-file write can fail; the run may not (docs/RCA.md RCA-2026-09-18-B).

`Sep 17, 2026 7:31pm`: the v1 backtest died at 3,948 of 4,124 pairs when
`db_jobs._write` gave up on `db_backtest.json` after 40 x 5 ms of Windows
PermissionError and raised out of the per-pair progress callback. The
checkpoint was fine, the workers were fine, the SCREEN's file was busy.

Three guards:
* `_write` keeps trying for `WRITE_REPLACE_BUDGET_S` (3 s), not 0.2 s;
* `_write_progress` swallows a refused progress write (printed once a
  minute) and the job goes on; terminal writes stay loud;
* `resume_if_died` WAITS while another disk job holds the disk instead of
  spending a retry and ringing "restarted after a crash" on a start that
  `JobBusy` was going to refuse (Sep 18, 2026 review, never fired).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from tradingagents import db_jobs as dj


# ------------------------------------------------------------- _write's budget
def test_the_replace_outlasts_a_reader_that_holds_the_file(tmp_path, monkeypatch):
    target = tmp_path / "db_backtest.json"
    real = Path.replace
    calls = {"n": 0}
    t0 = time.monotonic()

    def flaky(self, other):
        calls["n"] += 1
        # a reader holding the file for 0.6 s — three times the old 0.2 s budget
        if time.monotonic() - t0 < 0.6:
            raise PermissionError(5, "Access is denied")
        return real(self, other)

    monkeypatch.setattr(Path, "replace", flaky)
    dj._write(target, {"running": True, "done": 3948})
    assert json.loads(target.read_text(encoding="utf-8"))["done"] == 3948
    assert calls["n"] >= 3, calls
    assert not list(tmp_path.glob("*.tmp")), "the temp file is gone once it landed"


def test_past_the_budget_it_still_raises_and_leaves_no_temp_file(tmp_path, monkeypatch):
    target = tmp_path / "db_backtest.json"
    monkeypatch.setattr(dj, "WRITE_REPLACE_BUDGET_S", 0.05)
    monkeypatch.setattr(Path, "replace",
                        lambda self, other: (_ for _ in ()).throw(
                            PermissionError(5, "Access is denied")))
    t0 = time.monotonic()
    with pytest.raises(PermissionError):
        dj._write(target, {"x": 1})
    assert time.monotonic() - t0 < 2.0, "a small budget is honoured"
    assert not list(tmp_path.glob("*.tmp"))


# ---------------------------------------------------------- progress is telemetry
def test_a_refused_progress_write_is_swallowed_and_said_once(tmp_path, monkeypatch, capsys):
    target = tmp_path / "db_backtest.json"

    def refuse(path, payload):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(dj, "_write", refuse)
    dj._PROGRESS_WARNED.clear()
    assert dj._write_progress(target, {"running": True}) is False
    assert dj._write_progress(target, {"running": True}) is False
    out = capsys.readouterr().out
    assert out.count("could not write db_backtest.json") == 1, out
    assert "the run continues" in out


def test_every_mid_run_progress_write_is_forgiving():
    """Every `{"running": True, ...}` write in the jobs module goes through
    `_write_progress`; the terminal `running: False` writes stay `_write`."""
    src = Path(dj.__file__).read_text(encoding="utf-8")
    assert '_write(f["progress"], {"running": True' not in src, \
        "a mid-run progress write that can end the job"
    assert src.count('_write_progress(f["progress"], {"running": True') >= 4
    assert '_write(f["progress"], {"running": False' in src, \
        "terminal writes must still be loud"


def test_the_v2_filing_says_so_on_the_screen():
    """The heartbeat is stopped before the v2 job files its rows; the screen
    used to sit at 100% for the whole filing (Sep 18, 2026 review)."""
    import inspect

    src = inspect.getsource(dj._run_backtest_inner)
    i = src.index('"now": f"filing ')
    j = src.index("_ri.sync(force=True)")
    assert i < j, "the note is written BEFORE the filing starts"


# --------------------------------------------------------- the one-disk rule
def _running(kinds):
    def status(kind):
        return {"running": kind in kinds, "pid": 123 if kind in kinds else 0}
    return status


def test_disk_holder_names_who_keeps_a_kind_off_the_disk(monkeypatch):
    monkeypatch.setattr(dj, "status", _running({"backtest_v2"}))
    assert dj.disk_holder("download") == "backtest_v2"
    assert dj.disk_holder("btupdate_v2") == "backtest_v2"
    monkeypatch.setattr(dj, "status", _running({"download"}))
    assert dj.disk_holder("backtest_v2") == "download", "a v2 kind yields to any disk job"
    assert dj.disk_holder("backtest") == "", "v1 kinds among themselves are as before"
    monkeypatch.setattr(dj, "status", _running(set()))
    assert dj.disk_holder("backtest_v2") == ""


def test_a_resume_waits_for_the_disk_without_spending_a_retry(monkeypatch):
    monkeypatch.setattr(dj, "died_unfinished", lambda kind: True)
    monkeypatch.setattr(dj, "free_gb", lambda: 100.0)
    monkeypatch.setattr(dj, "_retries", lambda kind: 3)
    monkeypatch.setattr(dj, "_read", lambda path: {"coins": ["XPIN_USDT"], "tfs": ["1h"]})
    monkeypatch.setattr(dj, "status", _running({"download_v2"}))
    spent, bells, started = [], [], []
    monkeypatch.setattr(dj, "_set_retries", lambda kind, n: spent.append((kind, n)))
    monkeypatch.setattr(dj, "start", lambda kind, spec: started.append(kind) or 999)

    from tradingagents import notifications as nt
    monkeypatch.setattr(nt, "record", lambda *a, **k: bells.append(a))

    got = dj.resume_if_died("backtest_v2")
    assert got["resumed"] is False
    assert got["why"].startswith("waiting: download_v2 is running"), got
    assert spent == [], "a refusal is not an attempt"
    assert bells == [], "and rings no 'restarted after a crash' bell"
    assert started == []


def test_a_resume_with_the_disk_free_still_counts_and_starts(monkeypatch):
    monkeypatch.setattr(dj, "died_unfinished", lambda kind: True)
    monkeypatch.setattr(dj, "free_gb", lambda: 100.0)
    monkeypatch.setattr(dj, "_retries", lambda kind: 3)
    monkeypatch.setattr(dj, "_read", lambda path: {"coins": ["XPIN_USDT"], "tfs": ["1h"]})
    monkeypatch.setattr(dj, "status", _running(set()))
    spent, started = [], []
    monkeypatch.setattr(dj, "_set_retries", lambda kind, n: spent.append((kind, n)))
    monkeypatch.setattr(dj, "start", lambda kind, spec: started.append((kind, spec)) or 999)

    from tradingagents import notifications as nt
    monkeypatch.setattr(nt, "record", lambda *a, **k: None)

    got = dj.resume_if_died("backtest_v2")
    assert got == {"resumed": True, "pid": 999, "attempt": 4}
    assert spent == [("backtest_v2", 4)]
    assert started[0][0] == "backtest_v2" and started[0][1]["fresh"] is False
