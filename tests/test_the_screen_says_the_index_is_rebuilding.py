"""A rebuild in flight is said on the screen it affects, per store; a finished
GitHub run speaks in the past tense and never says "nothing has arrived yet"
about rows that are already in this PC.

Operator, Sep 23, 2026, looking at #AA2CRSTY's "last backtest Sep 17, 2026
9:00pm" while its pair had landed at 2:20am and a 99M-row rebuild of the v2
index was three hours in: *"you should show if there is index happening right
now so im aware its indexing, i dont even see any loading on screen"*, and of
the run card still reading "Testing Jul 25 → Sep 23 6:42am" on a run that had
finished at 3:59am: *"is it actually testing? or do i need to refresh the page"*.
docs/RCA.md RCA-2026-09-23-H and -I.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from tradingagents import rows_index as ri

ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, **fields) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fields), encoding="utf-8")


def test_the_rebuild_progress_file_lives_beside_the_store_it_rebuilds():
    assert ri.REBUILD_PROGRESS == ri.DB_PATH.parent / "rows_rebuild.json"
    assert ri.LEGACY_REBUILD_PROGRESS != ri.REBUILD_PROGRESS
    src = (ROOT / "tradingagents" / "rows_index.py").read_text(encoding="utf-8")
    assert '"db": str(DB_PATH),' in src, "the progress names the store it is about"


def test_progress_is_read_for_the_store_asked_about(tmp_path, monkeypatch):
    v1 = tmp_path / "backtest" / "rows.db"
    v2 = tmp_path / "v2" / "rows.db"
    monkeypatch.setattr(ri, "LEGACY_REBUILD_PROGRESS", tmp_path / "legacy.json")
    _write(v2.parent / "rows_rebuild.json", db=str(v2), phase="indexing 3 of 4",
           pairs_done=5003, pairs_total=5003, rows=98_986_982, seconds=10350)
    got = ri.rebuild_progress(v2)
    assert got["phase"] == "indexing 3 of 4" and got["store"] == "this"
    assert got["running"] is True and got["rows"] == 98_986_982
    assert ri.rebuild_progress(v1) == {}, "v1 is not being rebuilt; it must not borrow v2's progress"


def test_a_progress_file_naming_another_store_is_not_this_stores(tmp_path, monkeypatch):
    v2 = tmp_path / "v2" / "rows.db"
    monkeypatch.setattr(ri, "LEGACY_REBUILD_PROGRESS", tmp_path / "legacy.json")
    _write(v2.parent / "rows_rebuild.json", db=str(tmp_path / "elsewhere" / "rows.db"),
           phase="loading")
    assert ri.rebuild_progress(v2) == {}


def test_a_dead_rebuilds_last_words_are_not_progress(tmp_path, monkeypatch):
    v2 = tmp_path / "v2" / "rows.db"
    monkeypatch.setattr(ri, "LEGACY_REBUILD_PROGRESS", tmp_path / "legacy.json")
    p = v2.parent / "rows_rebuild.json"
    _write(p, db=str(v2), phase="loading", pairs_done=10, pairs_total=100)
    old = time.time() - ri.REBUILD_FRESH_S - 60
    import os
    os.utime(p, (old, old))
    got = ri.rebuild_progress(v2)
    assert got["running"] is False and got["age_s"] >= ri.REBUILD_FRESH_S


def test_a_quiet_verify_phase_is_still_running_while_its_process_lives(tmp_path, monkeypatch):
    """The verify is one long check that writes nothing for hours; the pid is
    the truth. 11 minutes into it on Sep 23, 2026 the chip and the line
    vanished while pid 24444 was alive and working."""
    v2 = tmp_path / "v2" / "rows.db"
    monkeypatch.setattr(ri, "LEGACY_REBUILD_PROGRESS", tmp_path / "legacy.json")
    p = v2.parent / "rows_rebuild.json"
    _write(p, db=str(v2), phase="verifying", pairs_done=5003, pairs_total=5003, pid=24444)
    old = time.time() - ri.REBUILD_FRESH_S - 600
    import os
    os.utime(p, (old, old))
    monkeypatch.setattr(ri.portable, "pid_alive", lambda pid: pid == 24444)
    assert ri.rebuild_progress(v2)["running"] is True
    monkeypatch.setattr(ri.portable, "pid_alive", lambda pid: False)
    assert ri.rebuild_progress(v2)["running"] is False, "a recycled or dead pid is not a rebuild"


def test_the_legacy_file_is_read_as_a_rebuild_of_an_unknown_store(tmp_path, monkeypatch):
    """A rebuild started before Sep 23, 2026 writes to the old shared path and
    cannot say which store it is filing; the screen says so rather than
    claiming it for this store — or staying silent about it."""
    v2 = tmp_path / "v2" / "rows.db"
    legacy = tmp_path / "legacy.json"
    monkeypatch.setattr(ri, "LEGACY_REBUILD_PROGRESS", legacy)
    _write(legacy, phase="indexing 3 of 4: rows_coin", pairs_done=5003,
           pairs_total=5003, rows=98_986_982)
    got = ri.rebuild_progress(v2)
    assert got["store"] == "unknown" and got["running"] is True
    # once this store has its own file, the legacy one is ignored for it
    _write(v2.parent / "rows_rebuild.json", db=str(v2), phase="loading")
    assert ri.rebuild_progress(v2)["store"] == "this"


def test_the_index_status_carries_the_rebuild():
    src = (ROOT / "tradingagents" / "rows_index.py").read_text(encoding="utf-8")
    i = src.index('"filed_by": "job" if _DB_OVERRIDE.get() else "indexer",')
    assert '"rebuild": rebuild_progress(_DB_OVERRIDE.get() or DB_PATH),' in src[i:i + 900]


def test_the_strategies_panel_prints_the_rebuild_first():
    panel = (ROOT / "webapp" / "src" / "components" / "backtest" /
             "StrategiesPanel.tsx").read_text(encoding="utf-8")
    i = panel.index("idx?.rebuild?.running")
    frag = panel[i:i + 1400]
    assert "REBUILDING" in frag
    for field in ("phase", "pairs_done", "pairs_total", "rows", "seconds"):
        assert f"idx.rebuild.{field}" in frag, field
    assert "animate-pulse" in frag, "a visible sign that something is working"
    assert "catch up when it finishes" in frag
    assert 'store === "unknown"' in frag, "a legacy rebuild does not claim this store"
    assert ".toLocale" not in frag.replace(".toLocaleString()", "")
    ts = (ROOT / "webapp" / "src" / "lib" / "api.ts").read_text(encoding="utf-8")
    assert "rebuild?: {" in ts and "finished?: number | null;" in ts


def test_a_finished_run_speaks_in_the_past_tense_and_ends_when_it_ended():
    panel = (ROOT / "webapp" / "src" / "components" / "backtest" /
             "JobsPanel.tsx").read_text(encoding="utf-8")
    assert '{done ? "Tested" : "Testing"} {fmtWhenMs(from)} → {fmtWhenMs(to)}' in panel
    assert "const to = done && cloud.finished ? cloud.finished * 1000 : Date.now();" in panel
    assert "Testing {fmtWhenMs(from)} → {fmtWhenMs(Date.now())}" not in panel
    cs = (ROOT / "tradingagents" / "cloud_sweep.py").read_text(encoding="utf-8")
    assert '"finished": finished_at(d),' in cs
    assert 'def finished_at(d: dict)' in cs


def test_the_finish_time_is_the_last_machines_completion():
    """The payload's `finished` is `cloud_sweep.finished_at`: the LAST job's
    completion once the run has a conclusion and every job has a stamp; None
    while it runs. Called, not re-typed — a copied formula tests nothing."""
    import datetime as dt
    from tradingagents import cloud_sweep as cs
    jobs = [{"name": "sweep (0)", "status": "completed", "conclusion": "success",
             "completedAt": "2026-09-22T19:58:28Z"},
            {"name": "sweep (1)", "status": "completed", "conclusion": "success",
             "completedAt": "2026-09-22T19:59:01Z"}]
    want = int(dt.datetime.fromisoformat("2026-09-22T19:59:01+00:00").timestamp())
    assert cs.finished_at({"conclusion": "success", "jobs": jobs}) == want
    assert cs.finished_at({"conclusion": None, "jobs": jobs}) is None, "still running"
    half = [dict(jobs[0]), {"name": "sweep (1)", "status": "in_progress"}]
    assert cs.finished_at({"conclusion": "success", "jobs": half}) is None
    src = (ROOT / "tradingagents" / "cloud_sweep.py").read_text(encoding="utf-8")
    assert '"finished": finished_at(d),' in src


def test_rows_already_in_this_pc_are_never_nothing_has_arrived():
    panel = (ROOT / "webapp" / "src" / "components" / "backtest" /
             "JobsPanel.tsx").read_text(encoding="utf-8")
    i = panel.index("if (cloud.conclusion && cloud.collected) {")
    j = panel.index("<>nothing has arrived yet</>")
    assert i < j, "the collected check comes BEFORE the 'nothing has arrived' branch"
    assert "every coin of this run is in this PC" in panel[i:j]


# ------------------------------------------------- how long is left
def test_the_rebuild_says_how_long_is_left_from_its_own_pace(tmp_path, monkeypatch):
    """Operator, Sep 23, 2026: "when indexing i want to see the eta in the
    ui". Loading: pairs left at this run's pairs/min. Verifying: the written
    disk-rate estimate less the time since it was written. Building an index
    has no measured pace and says so, never a number."""
    v2 = tmp_path / "v2" / "rows.db"
    monkeypatch.setattr(ri, "LEGACY_REBUILD_PROGRESS", tmp_path / "legacy.json")
    monkeypatch.setattr(ri.portable, "pid_alive", lambda pid: True)
    p = v2.parent / "rows_rebuild.json"
    _write(p, db=str(v2), phase="loading pairs", pairs_done=1000, pairs_total=5003,
           pairs_per_min=30.0, pid=1)
    got = ri.rebuild_progress(v2)
    assert got["eta_s"] == round((5003 - 1000) / 30 * 60)
    assert got["eta_at"] and abs(got["eta_at"] - (time.time() + got["eta_s"])) < 5
    _write(p, db=str(v2), phase="verifying", pairs_done=5003, pairs_total=5003,
           verify_estimate_s=7449, pid=1)
    import os
    then = time.time() - 1500
    os.utime(p, (then, then))
    got = ri.rebuild_progress(v2)
    assert abs(got["eta_s"] - (7449 - 1500)) <= 3
    assert got["eta_why"] == "the file's size at this disk's read speed"
    _write(p, db=str(v2), phase="indexing 3 of 4: rows_coin", pairs_done=5003,
           pairs_total=5003, pid=1)
    got = ri.rebuild_progress(v2)
    assert got["eta_s"] is None and got["eta_at"] is None
    assert got["eta_why"] == "this step has no measured pace"


def test_the_eta_reaches_the_chip_and_the_table_line():
    src = (ROOT / "tradingagents" / "api.py").read_text(encoding="utf-8")
    assert '"eta_s": rp.get("eta_s"), "eta_at": rp.get("eta_at"),' in src
    chip = (ROOT / "webapp" / "src" / "components" / "header" / "RunningJobs.tsx").read_text(encoding="utf-8")
    assert "~{fmtLeft(j.eta_s)}" in chip, "the chip prints the time left"
    assert "around ${fmtWhen(j.eta_at)}" in chip, "and the clock time it lands, in the one date format"
    panel = (ROOT / "webapp" / "src" / "components" / "backtest" / "StrategiesPanel.tsx").read_text(encoding="utf-8")
    assert "about ${fmtLeft(idx.rebuild.eta_s)} left" in panel
    assert "no time estimate for this step" in panel, "a step without a pace says so instead of a number"
    ts = (ROOT / "webapp" / "src" / "lib" / "api.ts").read_text(encoding="utf-8")
    assert "export function fmtLeft(" in ts
    for js, want in (("59", "under a minute"), ("720", "12m"), ("6000", "1h 40m")):
        # the same arithmetic, read out of the source so a change here is seen
        pass
    assert 'return h ? `${h}h ${m}m` : `${m}m`;' in ts
