"""Every Backtest v2 surface reads THE STORE BEING SERVED, never v1's
(docs/RCA.md RCA-2026-09-18-D and -E; Sep 18, 2026 review).

Found by seven reviewers reading commits 65d13cb9f5c8^..d8964780374c:
* the v2 report file minted every row's id WITHOUT `res`, so archive-v2.html
  printed 82,758 v2 rows under their v1 twins' ids (FIRED, 7:57pm Sep 17);
* an on-demand index build under `using_db(v2)` locked, spawned and was
  remembered against v1's rows.db, so v2 would answer 503 for ever once it
  passed 200,000 rows (never fired — v2 held 82,758 rows);
* `status(db_path=v2)` printed v1's indexer as v2's filer;
* the watermark read under the override parsed each ~9 MB state file whole;
* the API's worker list for a v2 job came from v1's workers folder;
* the rebuild gate did not know the v2 kinds;
* a v1 re-deploy over a v2-armed slot kept printing the v2 id;
* the kline disk cache (40,000) could never satisfy the 1m ask (44,000).
"""
from __future__ import annotations

import inspect
import json
import os
import time
from pathlib import Path

import pytest

from tradingagents import backtest_report as br, market_sweep as msw, rows_index as ri


# ------------------------------------------------------------ the report's ids
def test_both_report_minters_carry_res():
    """`run_grid` and `grid_from_store` re-mint `r["id"]`; a v2 row's `res`
    must reach `row_code`, or the report names the v1 twin."""
    for fn in (br.run_grid, br.grid_from_store):
        src = inspect.getsource(fn)
        i = src.index('r["id"] = row_code(')
        # the call spans lines and holds nested parens (`r.get("th", 0)`), so
        # read a window past it rather than stopping at the first `)`
        call = src[i:i + 320]
        assert 'res=r.get("res")' in call, f"{fn.__name__}: {call}"


def test_a_v2_row_and_its_v1_twin_never_share_an_id():
    row = {"coin": "XPIN", "tf": "1h", "signal": "ote", "th": 0.0,
           "sl": 3.0, "tp": 1.0, "sizing": "flat"}
    v1 = br.row_code(row["coin"], row["tf"], row["signal"], row["th"],
                     row["sl"], row["tp"], row["sizing"])
    v2 = br.row_code(row["coin"], row["tf"], row["signal"], row["th"],
                     row["sl"], row["tp"], row["sizing"], res="1m")
    assert v1 == "LG9NSU4B", "the v1 id the operator reads today is a fixed point"
    assert v2 != v1


# ------------------------------------------------- the index build's target
@pytest.fixture
def v2_db(tmp_path):
    db = tmp_path / "v2" / "rows.db"
    db.parent.mkdir(parents=True)
    (db.parent / "state").mkdir()
    (db.parent / "rows").mkdir()
    with ri.using_db(db):
        ri.ensure()
    return db


def test_the_build_lock_and_the_spawned_child_target_the_store_being_read(v2_db, monkeypatch):
    spawned = {}

    class _Proc:
        pid = 4242

    def fake_popen(*args, **kwargs):
        spawned["env"] = kwargs.get("env") or {}
        return _Proc()

    monkeypatch.setattr(ri.subprocess, "Popen", fake_popen)
    with ri.using_db(v2_db):
        assert ri._build_lock("rows_id").parent == v2_db.parent
        assert ri.has_index("rows_id") is False
        ri._build_index("rows_id")
    assert spawned, "a build was spawned"
    assert spawned["env"].get("TA_ROWS_DB") == str(v2_db), \
        "the child builds the database the request was about, never v1's"
    # and the lock that says "a build is running" sits beside v2's file
    assert list(v2_db.parent.glob(".build-*.pid")), "lock beside the v2 db"
    assert not list(ri.DB_PATH.parent.glob(".build-rows_id.pid")) or \
        ri.DB_PATH.parent == v2_db.parent


def test_build_running_looks_beside_the_store_being_read(v2_db):
    (v2_db.parent / ".build-rows_wr4.pid").write_text(str(os.getpid()), encoding="utf-8")
    with ri.using_db(v2_db):
        assert "rows_wr4" in ri.build_running()


# --------------------------------------------------------- status is honest
def test_v2_status_does_not_borrow_v1s_indexer(v2_db):
    got = ri.status(db_path=v2_db)
    assert got["indexer_running"] is None, "no indexer process exists for v2"
    assert got["filed_by"] == "job"
    assert got["syncing"] is False and got["blocked_by"] == "" and got["last_error"] == ""
    v1 = ri.status()
    assert v1["filed_by"] == "indexer"


def test_the_rebuild_gate_knows_the_v2_kinds():
    for kind in ("download_v2", "backtest_v2", "btupdate_v2"):
        assert kind in ri._PAIR_WRITERS, kind


# ----------------------------------------------------- the watermark's tail
def test_pair_watermark_reads_another_roots_tail(tmp_path):
    root = tmp_path / "v2"
    (root / "state").mkdir(parents=True)
    big = {f"combo_{i}": {"pnl": i} for i in range(2000)}
    big["__last_ms__"] = 1_789_516_800_000
    (root / "state" / "XPIN-1h.json").write_text(json.dumps(big), encoding="utf-8")
    assert msw.pair_watermark("XPIN", "1h", root=root) == 1_789_516_800_000
    assert msw.pair_watermark("XPIN", "1h") == 0, "the default root is this process's own"


def test_stale_watermark_under_the_override_reads_the_tail_not_the_whole_file(v2_db, monkeypatch):
    seen = {}

    def spy(coin, tf, root=None):
        seen.update(coin=coin, tf=tf, root=root)
        return 1_789_516_800_000

    monkeypatch.setattr(msw, "pair_watermark", spy)
    with ri.using_db(v2_db):
        ri.stale_watermark("XPIN-1h")
    assert seen == {"coin": "XPIN", "tf": "1h", "root": v2_db.parent}, seen


# ------------------------------------------------------------ the workers
def test_worker_read_takes_another_stores_folder(tmp_path):
    slots = tmp_path / "v2" / "workers"
    slots.mkdir(parents=True)
    (slots / "w1.json").write_text(json.dumps(
        {"pid": os.getpid(), "updated": time.time(), "now": "XPIN 1h"}), encoding="utf-8")
    got = msw.worker_read(workers_dir=slots)
    assert [w["now"] for w in got] == ["XPIN 1h"]


# ------------------------------------------------------- the kline disk cap
def test_the_kline_disk_cache_holds_a_full_1m_frame():
    from tradingagents.dataflows import mexc_futures as fx

    assert br.TFS["1m"][2] <= fx._KLINE_DISK_MAX, \
        "a cache smaller than the ask re-pages the same bars on every download"


# ------------------------------------------------ deploy: v1 clears the v2 id
def test_a_v1_redeploy_over_a_v2_slot_forgets_the_v2_id():
    from tradingagents import auto_trader as at, deploy_preset as dp

    k = "ote_1h_sl3tp1"
    base = {"strategies": [], "strategy_coins": {}}
    s1 = dp.merged({"strategies": {k: {"coins": ["XPIN_USDT"], "res": "1m"}},
                    "book": ["paper"]}, base)
    assert s1["strategy_res"] == {at.book_slot(k, "XPIN_USDT"): "1m"}
    s2 = dp.merged({"strategies": {k: {"coins": ["XPIN_USDT"]}}, "book": ["paper"]}, s1)
    assert s2["strategy_res"] == {}, "re-armed from v1: the v2 memory is gone"
    # an UNRELATED slot keeps its memory
    s3 = dp.merged({"strategies": {"fvg_4h": {"coins": ["RPL_USDT"]}}, "book": ["paper"]}, s1)
    assert s3["strategy_res"] == {at.book_slot(k, "XPIN_USDT"): "1m"}


def test_the_read_back_names_the_store():
    from tradingagents import deploy_preset as dp

    base = {"strategies": [], "strategy_coins": {}}
    v2 = dp.describe({"name": "x", "strategies": {"ote_1h_sl3tp1": {
        "coins": ["XPIN_USDT"], "res": "1m", "rows": ["U9YP5N7L"]}}, "book": ["paper"]}, base)
    v1 = dp.describe({"name": "x", "strategies": {"ote_1h_sl3tp1": {
        "coins": ["XPIN_USDT"], "rows": ["LG9NSU4B"]}}, "book": ["paper"]}, base)
    assert "Backtest v2" in v2 and "minute-exact" in v2
    assert "Backtest v2" not in v1


# ------------------------------------------------ held follows the exit minute
from tests.test_minute_exact_exits import (  # noqa: E402,F401  (fixture + helpers)
    BOTH,
    DIRS,
    H0 as _H0,
    _fine,
    _flat_minutes,
    _minutes,
    _run,
    # `_spec` IS USED — by pytest, not by this module. It is a FIXTURE, so it
    # has to be in this namespace for the tests below to receive it, and it
    # never appears in the source. It was deleted on Sep 22, 2026 when a
    # blanket per-line suppression sat on a one-line import and `ruff --fix`
    # split that line: the directive stayed with the FIRST name and every
    # other name lost its cover. It is on the parenthesis now, where it
    # covers them all. (Written without the literal directive text, because
    # ruff reads a comment that contains one AS one.)
    _spec,
)


def test_held_follows_the_exit_minute_not_the_bar():
    """The row said 'exit time 1:28am' beside 'held <1h' — two clocks on one
    line. With the minutes known, `held` is measured to the minute."""
    path = [(100.0, 100.0)] * 28 + [(100.0, 96.5)] + [(100.0, 100.0)] * 31
    fine = _fine(_flat_minutes(0, 100.0), _minutes(1, path), _flat_minutes(2, 100.0))
    a = _run(BOTH, DIRS, fine=fine)
    row = a["log"][0]
    assert row["why"] == "SL"
    assert row["exit_minute_ms"] == _H0 + 3_600_000 + 28 * 60_000
    assert row["held_s"] == 28 * 60, row
    assert row["held"] == "28m", row
    # without the minutes the bar rule is untouched: an upper bound
    b = _run(BOTH, DIRS)
    assert b["log"][0]["held"] == "<1h" and b["log"][0]["held_s"] == 0


# ------------------------------------- the two stores do not pause each other
def test_a_v2_job_does_not_pause_the_v1_index(monkeypatch, tmp_path):
    """RCA-2026-09-18-K: a 21-hour `btupdate_v2` froze the V1 index, so the
    220 rows the operator's UPDATE on #LG9NSU4B measured at 3:05am could not
    be filed. A v2 job writes ~/.tradingagents/v2 and never a byte of v1's."""
    from tradingagents import db_jobs as dj, stores

    running = {"btupdate_v2"}
    monkeypatch.setattr(dj, "status",
                        lambda kind: {"running": kind in running, "pid": 7})
    # takes the store it reports on since 723aecc46d6d (Sep 23, 2026);
    # a zero-argument stub raised TypeError inside status()
    monkeypatch.setattr(ri, "rebuild_progress", lambda *a, **k: {})
    assert ri.busy_job() == "", "v1 keeps indexing while Backtest v2 measures"
    assert ri._machine_is_busy() is False

    v2db = stores.V2.rows_db
    with ri.using_db(v2db):
        assert ri.busy_job() == "btupdate_v2", "v2's own job still pauses v2"

    running.clear()
    running.add("collect")
    assert ri.busy_job() == "collect", "a v1 job still pauses v1"
    with ri.using_db(v2db):
        assert ri.busy_job() == "", "and v1's jobs do not pause v2"


def test_the_rebuild_still_yields_to_both_because_it_is_the_disk():
    """A six-hour rebuild is sequential IO on the one platter — a different
    question from a one-pair trickle, so its gate keeps every kind."""
    for kind in ("collect", "backtest", "download", "btupdate",
                 "download_v2", "backtest_v2", "btupdate_v2"):
        assert kind in ri._PAIR_WRITERS, kind


def test_the_backlog_waits_for_the_other_store_but_a_pressed_row_does_not(monkeypatch):
    """RCA-2026-09-18-K, round 4: not pausing at all would have put a bulk
    re-file of 5,270 v1 pairs on the same platter as a 4,012-pair v2 sweep.
    The rows a PERSON pressed UPDATE on are filed at once; the rest waits."""
    from tradingagents import db_jobs as dj

    monkeypatch.setattr(dj, "status",
                        lambda kind: {"running": kind == "btupdate_v2", "pid": 7})
    # takes the store it reports on since 723aecc46d6d (Sep 23, 2026);
    # a zero-argument stub raised TypeError inside status()
    monkeypatch.setattr(ri, "rebuild_progress", lambda *a, **k: {})
    assert ri.busy_job() == "", "not a pause"
    assert ri.other_store_job() == "btupdate_v2", "but the disk is shared"
    assert ri.status()["deferring_to"] == "btupdate_v2"

    loop = inspect.getsource(ri.start_keeping_up)
    i = loop.index("other_store_job()")
    j = loop.index("sync(", i)
    block = loop[i:j]
    assert "_asked()" in block, "only the pressed pairs go in while it runs"
    assert "someone pressed UPDATE on" in block, "and the log says so"
    assert "sync(todo" in loop[j - 6:j + 20], "the filtered list is what is filed"

    panel = (Path(__file__).resolve().parents[1]
             / "webapp/src/components/backtest/StrategiesPanel.tsx").read_text(encoding="utf-8")
    assert "idx.deferring_to" in panel
    assert "a row you press UPDATE on is filed at once" in panel


def test_a_one_pair_remeasure_is_never_refused_for_a_sweep(monkeypatch):
    """RCA-2026-09-18-L: clicking UPDATE THIS BACKTEST in Chrome answered
    `409 btupdate_v2 is running — one job at a time` for the whole 21 hours of
    a Backtest v2 run. The one-disk rule is about SWEEPS; `pairbt`/`stratbt`
    are one pair, minutes, pressed by a person who is watching."""
    from tradingagents import db_jobs as dj

    monkeypatch.setattr(dj, "status",
                        lambda kind: {"running": kind == "btupdate_v2", "pid": 7})
    for small in ("pairbt", "stratbt"):
        assert small not in dj._DISK_JOBS, small
        assert dj.disk_holder(small) == "", small
    # the sweeps still yield, in both directions
    assert dj.disk_holder("backtest") == "btupdate_v2"
    assert dj.disk_holder("download") == "btupdate_v2"
    monkeypatch.setattr(dj, "status",
                        lambda kind: {"running": kind == "collect", "pid": 7})
    assert dj.disk_holder("backtest_v2") == "collect"
    assert dj.disk_holder("pairbt") == "", "still not a sweep"
