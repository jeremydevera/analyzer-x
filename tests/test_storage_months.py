"""Storage by month, and deleting a month to free disk.

Operator, 2026-09-09: *"in candles create a table showing candles for each
month for example feb 2025 march 2025 and able to delete it so that i can free
up space same as for backtests results"*.
"""
import calendar
import json
import os
import time

import pytest

from tradingagents import market_sweep as msw, rows_index as ri, storage_months as sm

HOUR = 3_600_000


def _ms(y, m, d, h=0):
    return calendar.timegm((y, m, d, h, 0, 0)) * 1000


def _write_candles(symbol, tf, ts):
    n = len(ts)
    (msw.CANDLES / f"{symbol}-{tf}.json").write_text(json.dumps({
        "t": ts, "o": [1.0] * n, "h": [2.0] * n, "l": [0.5] * n,
        "c": [1.5] * n, "v": [10.0] * n}, separators=(",", ":")))


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(msw, "HOME", tmp_path)
    monkeypatch.setattr(msw, "CANDLES", tmp_path / "candles")
    monkeypatch.setattr(msw, "STATES", tmp_path / "state")
    monkeypatch.setattr(msw, "ROWDIR", tmp_path / "rows")
    monkeypatch.setattr(msw, "INDEX_PATH", tmp_path / "candle_index.json")
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    for d in ("candles", "state", "rows"):
        (tmp_path / d).mkdir()
    # no writer job is running, whatever this PC is doing
    monkeypatch.setattr(sm, "_writer_running", lambda kind: "")
    # the worker runs in-process here (a thread standing in for the detached
    # child); the spawn plumbing has its own test below
    import threading

    def fake_spawn(kind, through):
        threading.Thread(target=sm.run_delete, args=(kind, through),
                         daemon=True).start()
        return os.getpid()
    monkeypatch.setattr(sm, "_spawn_real", sm._spawn, raising=False)
    monkeypatch.setattr(sm, "_spawn", fake_spawn)
    return tmp_path


# ---------------------------------------------------------------- months
def test_month_key_label_and_next():
    assert sm.month_key(_ms(2025, 2, 14, 9)) == "2025-02"
    assert sm.month_label("2025-02") == "Feb 2025"
    assert sm.month_label("2025-03") == "Mar 2025"
    assert sm.next_month("2025-12") == "2026-01"
    assert sm.month_start_ms("2025-03") == _ms(2025, 3, 1)


def test_candle_months_splits_a_series_exactly_when_it_has_no_gaps(store):
    # 1h bars from Jan 30 00:00 to Mar 02 23:00 (UTC), no gaps
    ts = list(range(_ms(2025, 1, 30), _ms(2025, 3, 3), HOUR))
    _write_candles("AAA_USDT", "1h", ts)
    got = sm.candle_months(msw.candle_index(scan=True))
    by = {r["month"]: r for r in got["rows"]}
    assert [r["month"] for r in got["rows"]] == ["2025-03", "2025-02", "2025-01"]
    assert by["2025-01"]["bars"] == 2 * 24          # Jan 30, 31
    assert by["2025-02"]["bars"] == 28 * 24
    assert by["2025-03"]["bars"] == 2 * 24          # Mar 1, 2
    assert sum(r["bars"] for r in got["rows"]) == len(ts)
    assert got["estimated"] is True
    # bytes are shared in proportion to bars and sum to the file
    size = (msw.CANDLES / "AAA_USDT-1h.json").stat().st_size
    assert abs(sum(r["bytes"] for r in got["rows"]) - size) <= 2
    assert by["2025-02"]["pairs"] == 1


def test_candle_months_still_sums_to_the_real_bar_count_with_gaps(store):
    ts = list(range(_ms(2025, 1, 30), _ms(2025, 3, 3), HOUR))
    del ts[100:300]                                 # a hole in February
    _write_candles("AAA_USDT", "1h", ts)
    got = sm.candle_months(msw.candle_index(scan=True))
    assert sum(r["bars"] for r in got["rows"]) == len(ts)


# ---------------------------------------------------------------- candles
def _wait(kind):
    for _ in range(200):
        j = sm.progress(kind)
        if j and not j["running"]:
            return j
        time.sleep(0.02)
    raise AssertionError("delete never finished")


def test_deleting_a_candle_month_trims_that_month_and_everything_older(store):
    ts = list(range(_ms(2025, 1, 30), _ms(2025, 3, 3), HOUR))
    _write_candles("AAA_USDT", "1h", ts)
    # a pair entirely older than the cut: its file goes
    _write_candles("OLD_USDT", "1h", list(range(_ms(2024, 11, 1), _ms(2024, 12, 5), HOUR)))
    # a pair entirely newer: untouched, not even rewritten
    _write_candles("NEW_USDT", "1h", list(range(_ms(2025, 3, 5), _ms(2025, 3, 9), HOUR)))
    new_mtime = (msw.CANDLES / "NEW_USDT-1h.json").stat().st_mtime_ns
    msw.candle_index(scan=True)

    sm.start_delete("candles", "2025-02", now=_ms(2025, 9, 9) / 1000)
    job = _wait("candles")
    assert job["errors"] == []
    assert job["done"] == job["total"] == 3
    kept = json.loads((msw.CANDLES / "AAA_USDT-1h.json").read_text())
    assert kept["t"][0] == _ms(2025, 3, 1)
    assert len(kept["t"]) == 2 * 24
    # the SAME layout save_candles_cache writes — every array trimmed alike
    assert set(kept) == {"t", "o", "h", "l", "c", "v"}
    assert all(len(kept[k]) == len(kept["t"]) for k in "ohlcv")
    assert not (msw.CANDLES / "OLD_USDT-1h.json").exists()
    assert (msw.CANDLES / "NEW_USDT-1h.json").stat().st_mtime_ns == new_mtime
    assert job["files_removed"] == 1 and job["files_trimmed"] == 1
    assert job["bars_removed"] == (len(ts) - 48) + (34 * 24)
    assert job["freed"] > 0
    # the index was refreshed, so the table now says what is left
    months = [r["month"] for r in sm.candle_months(msw.candle_index(scan=False))["rows"]]
    assert months == ["2025-03"]
    assert job["finished_at"]                       # Aug 03, 2026 8:03pm form
    assert job["label"] == "Feb 2025"


def test_the_current_month_is_refused(store):
    with pytest.raises(ValueError, match="current month"):
        sm.start_delete("candles", "2025-09", now=_ms(2025, 9, 9) / 1000)
    with pytest.raises(ValueError, match="current month"):
        sm.start_delete("results", "2026-01", now=_ms(2025, 9, 9) / 1000)


def test_a_writer_job_refuses_the_delete(store, monkeypatch):
    monkeypatch.setattr(sm, "_writer_running",
                        lambda kind: "download" if kind == "candles" else "")
    with pytest.raises(ValueError, match="download job is writing"):
        sm.start_delete("candles", "2025-02", now=_ms(2025, 9, 9) / 1000)


def test_a_bad_month_or_store_is_refused(store):
    with pytest.raises(ValueError, match="not a month"):
        sm.start_delete("candles", "feb 2025")
    with pytest.raises(ValueError, match="unknown store"):
        sm.start_delete("everything", "2025-02")


def test_the_writer_list_names_every_job_that_rewrites_each_store():
    """A download rewrites candle files; backtest, collect and btupdate all
    write rows files. A store's delete racing its writer loses data silently."""
    assert sm.WRITERS["candles"] == ("download",)
    assert set(sm.WRITERS["results"]) == {"backtest", "collect", "btupdate"}


# ---------------------------------------------------------------- results
def _row(coin, tf):
    return {"coin": coin, "tf": tf, "signal": "scalp", "th": 0.1, "sl": 1.0,
            "tp": 1.0, "rr": 1.0, "sizing": "flat", "lev": 20, "base": 5.0,
            "notional": 100.0, "trades": 120, "wins": 72, "losses": 48,
            "winrate": 60.0, "profit": 10.0, "funding": -0.2, "h1": 5.0,
            "h2": 5.0, "green": 8, "months": 12, "worst": -4.1, "dd": 22.0,
            "liqs": 0, "stop_reachable": True, "days": 360, "bars": 34000,
            "monthly": {"2026-08": 3.0}, "cost_of_tp": 12.5, "rt": 0.04,
            "gate": "ok"}


def _measured(coin, tf, when_ms):
    f = msw.ROWDIR / f"{coin}-{tf}.json"
    f.write_text(json.dumps([_row(coin, tf), _row(coin, tf)]))
    s = msw.STATES / f"{coin}-{tf}.json"
    s.write_text(json.dumps({"__last_ms__": when_ms, "x": 1}))
    os.utime(f, (when_ms / 1000, when_ms / 1000))


def test_results_months_group_pairs_by_when_they_were_measured(store):
    _measured("AAA", "1h", _ms(2025, 2, 10))
    _measured("BBB", "1h", _ms(2025, 2, 20))
    _measured("CCC", "4h", _ms(2025, 4, 1))
    ri.sync(now=time.time() + ri.SETTLE_S + 1)
    got = sm.results_months()
    assert [(r["month"], r["pairs"], r["rows"]) for r in got["rows"]] == [
        ("2025-04", 1, 2), ("2025-02", 2, 4)]
    assert got["rows"][0]["label"] == "Apr 2025"
    assert got["total_rows"] == 6
    assert got["total_bytes"] > 0 and got["estimated"] is False


def test_deleting_a_results_month_drops_those_pairs_from_disk_and_the_index(store):
    _measured("AAA", "1h", _ms(2025, 2, 10))
    _measured("BBB", "1h", _ms(2025, 2, 20))
    _measured("CCC", "4h", _ms(2025, 4, 1))
    ri.sync(now=time.time() + ri.SETTLE_S + 1)
    assert ri.query()["total"] == 6

    sm.start_delete("results", "2025-02", now=_ms(2025, 9, 9) / 1000)
    job = _wait("results")
    assert job["errors"] == []
    assert job["done"] == job["total"] == 2
    assert job["rows_removed"] == 4
    assert job["files_removed"] == 4                # 2 rows files + 2 states
    assert job["freed"] > 0
    assert not (msw.ROWDIR / "AAA-1h.json").exists()
    assert not (msw.STATES / "BBB-1h.json").exists()
    assert (msw.ROWDIR / "CCC-4h.json").exists()
    # the index agrees with the disk, at once — no restart, no rebuild
    assert ri.query()["total"] == 2
    assert {r["coin"] for r in ri.query()["rows"]} == {"CCC"}
    assert [r["month"] for r in sm.results_months()["rows"]] == ["2025-04"]


def test_a_sync_tick_between_the_index_delete_and_the_unlink_leaves_no_orphan(
        store, monkeypatch):
    """harddev round 1: the API's sync timer takes a file with no summary as
    NEW. If it ticks after forget_pair and before discard_pair, the pair is
    re-indexed just before its file goes — rows on screen for a pair that no
    longer exists. The delete forgets the pair AGAIN after the files go."""
    _measured("AAA", "1h", _ms(2025, 2, 10))
    ri.sync(now=time.time() + ri.SETTLE_S + 1)
    real = msw.discard_pair

    def racing_discard(coin, tf):
        ri.sync(now=time.time() + ri.SETTLE_S + 1)     # the tick, mid-delete
        assert ri.query()["total"] == 2, "the race did not happen in this test"
        return real(coin, tf)

    monkeypatch.setattr(msw, "discard_pair", racing_discard)
    sm.start_delete("results", "2025-02", now=_ms(2025, 9, 9) / 1000)
    job = _wait("results")
    assert job["errors"] == []
    assert ri.query()["total"] == 0
    assert ri.pair_storage() == []


def _hold_write_lock():
    """Another process's write, as the standalone indexer does it: an open
    IMMEDIATE transaction on the same file."""
    import sqlite3

    con = sqlite3.connect(str(ri.DB_PATH), timeout=0.1, check_same_thread=False)
    con.execute("BEGIN IMMEDIATE")
    return con


def test_forget_pairs_waits_for_the_lock_then_takes_it(store):
    """the standalone indexer commits between pairs; the batched delete waits
    for that gap and then holds the lock for every pair"""
    import threading

    _measured("AAA", "1h", _ms(2025, 2, 10))
    ri.sync(now=time.time() + ri.SETTLE_S + 1)
    holder = _hold_write_lock()
    threading.Timer(0.5, lambda: (holder.rollback(), holder.close())).start()
    t = time.time()
    assert ri.forget_pairs(["AAA-1h"], busy_ms=5000) == 2
    assert time.time() - t >= 0.4                    # it waited for the gap
    assert ri.query()["total"] == 0


def test_forget_pair_raises_behind_another_writer_instead_of_saying_zero(store, monkeypatch):
    """Pressed for real on 2026-09-09: the standalone indexer held the lock,
    every forget_pair waited 60 s and returned 0 as if it had worked, and the
    files were deleted underneath 341,884 rows still on screen."""
    import sqlite3

    _measured("AAA", "1h", _ms(2025, 2, 10))
    ri.sync(now=time.time() + ri.SETTLE_S + 1)
    holder = _hold_write_lock()
    try:
        monkeypatch.setattr(ri, "_connect",
                            _short_timeout(ri._connect, monkeypatch))
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            ri.forget_pair("AAA-1h")
        assert ri.write_available(timeout_ms=100).startswith("the row index")
    finally:
        holder.rollback(); holder.close()
    assert ri.write_available() == ""
    assert ri.query()["total"] == 2                  # nothing was lost


def _short_timeout(real_connect, monkeypatch):
    """the test cannot wait the production 60 s busy_timeout"""
    def connect(*a, **k):
        con = real_connect(*a, **k)
        con.execute("PRAGMA busy_timeout=100")
        return con
    return connect


def test_a_failed_index_delete_keeps_every_file(store, monkeypatch):
    """index first, files second — and no files at all when the first step
    fails, or the next screen shows rows for a pair the disk no longer has."""
    _measured("AAA", "1h", _ms(2025, 2, 10))
    _measured("BBB", "1h", _ms(2025, 2, 12))
    ri.sync(now=time.time() + ri.SETTLE_S + 1)

    def refuse(pairs, on_pair=None, busy_ms=0):
        raise RuntimeError("database is locked")
    monkeypatch.setattr(ri, "forget_pairs", refuse)
    sm.start_delete("results", "2025-02", now=_ms(2025, 9, 9) / 1000)
    job = _wait("results")
    for c in ("AAA", "BBB"):
        assert (msw.ROWDIR / f"{c}-1h.json").exists()
        assert (msw.STATES / f"{c}-1h.json").exists()
    assert job["files_removed"] == 0 and job["freed"] == 0
    assert job["rows_removed"] == 0
    assert job["errors"] == ["the row index still holds every pair "
                             "(RuntimeError: database is locked) — no file "
                             "was deleted; press again when the index is free"]
    assert ri.query()["total"] == 4                  # and the index is intact


def test_the_index_pairs_go_in_one_transaction(store):
    """one lock, held until every pair is gone — never a gap the indexer can
    take between pairs (the 2026-09-09 press got one pair per gap)"""
    _measured("AAA", "1h", _ms(2025, 2, 10))
    _measured("BBB", "1h", _ms(2025, 2, 12))
    ri.sync(now=time.time() + ri.SETTLE_S + 1)
    seen = []
    n = ri.forget_pairs(["AAA-1h", "BBB-1h", "NOPE-1h"],
                        on_pair=lambda p, k: seen.append((p, k)))
    assert n == 4 and seen == [("AAA-1h", 2), ("BBB-1h", 2), ("NOPE-1h", 0)]
    assert ri.query()["total"] == 0 and ri.pair_storage() == []


def test_the_worker_is_a_detached_process_and_a_dead_one_says_so(store, monkeypatch):
    """The first DELETE 29 DELISTED ran as a thread in the API and died when
    another session restarted the API at 8:03am (2026-09-09), 2 coins in.
    The worker is its own process now; a record whose pid is gone reads as
    not running, with the reason, never as RUNNING for ever."""

    calls = []

    class P:
        pid = 424242
    monkeypatch.setattr(sm.subprocess, "Popen", lambda cmd, **kw: (calls.append((cmd, kw)), P())[1])
    monkeypatch.setattr(sm, "_spawn", sm._spawn_real)              # the real one
    _measured("AAA", "1h", _ms(2025, 2, 10))
    ri.sync(now=time.time() + ri.SETTLE_S + 1)
    got = sm.start_delete("results", "2025-02", now=_ms(2025, 9, 9) / 1000)
    # the stub also catches the indexer's own detached builds — pick ours
    cmd, kw = next((c, k) for c, k in calls if "tradingagents.storage_months" in c)
    assert cmd[1:] == ["-m", "tradingagents.storage_months", "--run", "results", "2025-02"]
    assert kw["env"]["TA_ROWS_DB"] == str(ri.DB_PATH)
    assert kw["env"]["TRADINGAGENTS_SWEEP_HOME"] == str(msw.HOME)
    assert kw["env"]["TRADINGAGENTS_CANDLES"] == str(msw.CANDLES)
    if os.name == "nt":
        assert kw["creationflags"] == 0x00000008 | 0x00000200
    else:
        assert kw["start_new_session"] is True
    # the child records its own pid; until then the record is "starting"
    assert got["running"] is True and got["pid"] == 0
    # a child that never wrote its pid within a minute is a dead job
    rec = sm._load("results")
    rec["started"] -= 120
    sm._save(rec)
    assert sm.progress("results")["running"] is False
    assert "died before finishing" in sm.progress("results")["errors"][-1]
    # and so is one whose recorded pid is gone
    rec["pid"] = 424242
    sm._save(rec)
    assert sm.progress("results")["running"] is False
    assert sm.job_path("results").exists()
    assert (msw.HOME / "delete_results.log").exists()
    # the module refuses to be anything but the worker from the command line
    assert sm.main(["--build", "x"]) == 2


def test_a_results_delete_waits_for_another_writer_and_says_so(store, monkeypatch):
    """The indexer holds the row index's write lock ~95% of the time on the
    operator's disk. A delete that REFUSED while it was held (11:31am,
    2026-09-09) almost never got to run; the detached worker waits for the
    lock instead, and its phase line says what it is waiting for."""
    _measured("AAA", "1h", _ms(2025, 2, 10))
    ri.sync(now=time.time() + ri.SETTLE_S + 1)
    monkeypatch.setattr(sm, "LOCK_WAIT_MS", 5000)
    holder = _hold_write_lock()
    sm.start_delete("results", "2025-02", now=_ms(2025, 9, 9) / 1000)
    time.sleep(0.3)
    got = sm.progress("results")
    assert got["running"] is True
    assert "write lock" in got["phase"], got["phase"]
    assert (msw.ROWDIR / "AAA-1h.json").exists()   # nothing touched while waiting
    holder.rollback(); holder.close()
    job = _wait("results")
    assert job["errors"] == [] and job["rows_removed"] == 2
    assert not (msw.ROWDIR / "AAA-1h.json").exists()


def test_forget_pair_removes_rows_and_the_summary(store):
    _measured("AAA", "1h", _ms(2025, 2, 10))
    ri.sync(now=time.time() + ri.SETTLE_S + 1)
    assert ri.forget_pair("AAA-1h") == 2
    assert ri.query()["total"] == 0
    assert ri.pair_storage() == []
    assert ri.forget_pair("AAA-1h") == 0            # twice is harmless


# ---------------------------------------------------------------- delisted
# Operator, 2026-09-09: "create a button in backtest 'Delete X Delisted' where
# x is number of coin delisted. if i click this delete the candle and backtest
# for the delisted coin"

def _delisted_store(monkeypatch, live):
    monkeypatch.setattr(sm, "_live_symbols", lambda: live)
    bars = list(range(_ms(2026, 8, 1), _ms(2026, 8, 3), HOUR))
    _write_candles("AAA_USDT", "1h", bars)            # listed
    _write_candles("DEAD_USDT", "1h", bars)           # gone: candles + rows
    _write_candles("DEAD_USDT", "4h", bars)
    _measured("AAA", "1h", _ms(2026, 8, 10))
    _measured("DEAD", "1h", _ms(2026, 8, 10))
    _measured("GONE", "4h", _ms(2026, 8, 10))         # gone: rows only
    msw.candle_index(scan=True)
    ri.sync(now=time.time() + ri.SETTLE_S + 1)


def test_delisted_report_names_every_stored_coin_the_venue_dropped(store, monkeypatch):
    _delisted_store(monkeypatch, {"AAA_USDT", "OTHER_USDT"})
    rep = sm.delisted_report()
    assert rep["known"] is True
    assert [c["coin"] for c in rep["coins"]] == ["DEAD", "GONE"]
    dead = rep["coins"][0]
    assert dead["candle_pairs"] == 2 and dead["result_pairs"] == 1
    assert dead["result_rows"] == 2 and dead["candle_bytes"] > 0
    assert rep["coins"][1]["candle_pairs"] == 0 and rep["coins"][1]["result_pairs"] == 1
    assert rep["candle_pairs"] == 2 and rep["result_pairs"] == 2
    assert rep["bytes"] == rep["candle_bytes"] + rep["result_bytes"] > 0


def test_the_report_does_not_count_candle_files_that_are_already_gone(store, monkeypatch):
    """the candle index is a cache: an interrupted press left it listing 24
    files it had removed, and the button said 97 over 73 (2026-09-09)"""
    _delisted_store(monkeypatch, {"AAA_USDT"})
    (msw.CANDLES / "DEAD_USDT-4h.json").unlink()      # gone, index not rescanned
    assert "DEAD_USDT-4h" in msw.candle_index(scan=False)
    rep = sm.delisted_report()
    dead = next(c for c in rep["coins"] if c["coin"] == "DEAD")
    assert dead["candle_pairs"] == 1
    assert rep["candle_pairs"] == 1


def test_a_coin_quoted_in_something_else_is_not_called_delisted(store, monkeypatch):
    """rows pairs carry the coin, not the symbol: AAA listed as AAA_USDC must
    not be deleted for lacking an AAA_USDT twin."""
    _delisted_store(monkeypatch, {"AAA_USDC", "DEAD_USDT", "GONE_USDT"})
    assert sm.delisted_report()["coins"] == []


def test_an_unreadable_live_list_means_nothing_is_delisted(store, monkeypatch):
    """'I could not look' must never read as 'every coin is gone'."""
    _delisted_store(monkeypatch, None)
    rep = sm.delisted_report()
    assert rep["known"] is False and rep["coins"] == []
    assert "could not be read" in rep["why"]
    with pytest.raises(ValueError, match="could not be read"):
        sm.start_delete("delisted", "")


def test_delete_delisted_removes_candles_and_backtests_for_those_coins_only(store, monkeypatch):
    _delisted_store(monkeypatch, {"AAA_USDT"})
    assert ri.query()["total"] == 6
    sm.start_delete("delisted", "")
    job = _wait("delisted")
    assert job["errors"] == []
    assert job["done"] == job["total"] == 2
    assert job["coins"] == ["DEAD", "GONE"]
    assert job["label"] == "2 delisted coin(s)"
    # DEAD: two candle files, one rows file, one state file; GONE: rows + state
    assert not (msw.CANDLES / "DEAD_USDT-1h.json").exists()
    assert not (msw.CANDLES / "DEAD_USDT-4h.json").exists()
    assert not (msw.ROWDIR / "DEAD-1h.json").exists()
    assert not (msw.ROWDIR / "GONE-4h.json").exists()
    assert not (msw.STATES / "GONE-4h.json").exists()
    assert job["files_removed"] == 2 + 2 + 2
    assert job["rows_removed"] == 4
    assert job["freed"] > 0
    # the listed coin is untouched, on disk and in the index
    assert (msw.CANDLES / "AAA_USDT-1h.json").exists()
    assert (msw.ROWDIR / "AAA-1h.json").exists()
    assert ri.query()["total"] == 2
    assert {r["coin"] for r in ri.query()["rows"]} == {"AAA"}
    # and the candle index no longer lists them
    assert set(msw.candle_index(scan=False)) == {"AAA_USDT-1h"}
    assert sm.delisted_report()["coins"] == []


def test_delete_delisted_clears_those_coins_from_the_download_lost_list(store, monkeypatch, tmp_path):
    """harddev round 1: lost.json kept naming the deleted pairs, so the
    Candles screen went on saying 'N delisted — nothing to retry' for coins no
    longer on this PC, and RETRY FAILED would have attempted them."""
    from tradingagents import db_jobs as dj

    lost = tmp_path / "db_download.lost.json"
    lost.write_text(json.dumps({"pairs": [["DEAD_USDT", "1h"], ["AAA_USDT", "4h"],
                                          ["GONE_USDT", "1h"]],
                                "written": 1.0}))
    monkeypatch.setitem(dj.FILES["download"], "lost", lost)
    _delisted_store(monkeypatch, {"AAA_USDT"})
    sm.start_delete("delisted", "")
    job = _wait("delisted")
    assert job["errors"] == []
    left = json.loads(lost.read_text())
    assert left["pairs"] == [["AAA_USDT", "4h"]]
    assert left["written"] == 1.0                    # nothing else touched
    assert job["lost_cleared"] == 2


def test_delete_delisted_refuses_when_nothing_is_delisted(store, monkeypatch):
    _delisted_store(monkeypatch, {"AAA_USDT", "DEAD_USDT", "GONE_USDT"})
    with pytest.raises(ValueError, match="nothing to delete"):
        sm.start_delete("delisted", "")


def test_delisted_waits_for_the_rows_writers_but_not_for_a_download():
    """a download skips delisted symbols by the same is_delisted test, so it
    never writes a file this delete removes; the rows writers can (a cloud
    shard may still hand collect a delisted coin's rows)"""
    assert set(sm.WRITERS["delisted"]) == {"backtest", "collect", "btupdate"}
    assert "download" in sm.WRITERS["candles"]


def test_the_backtest_screen_has_the_button_and_asks_twice():
    p = open("webapp/src/components/backtest/JobsPanel.tsx", encoding="utf-8").read()
    assert "DELETE {dead.delisted.coins.length} DELISTED" in p, \
        "the count on the button is the API's, never counted in the component"
    assert "yes, delete" in p and "cancel" in p
    assert "!dead.delisted.known" in p, "an unreadable venue list disables it"
    a = open("webapp/src/lib/api.ts", encoding="utf-8").read()
    assert '"/api/storage/delisted"' in a
    api = open("tradingagents/api.py", encoding="utf-8").read()
    assert '@app.get("/api/storage/delisted")' in api


# ---------------------------------------------------------------- the UI
def test_the_panel_says_older_months_go_too_and_asks_twice():
    p = open("webapp/src/components/candles/MonthsPanel.tsx", encoding="utf-8").read()
    assert "delete this and older" in p
    assert "and everything older?" in p, "the confirm must say what goes"
    assert "yes, delete" in p and "cancel" in p
    assert "newest — kept" in p, "the newest month has no delete"
    # a refusal's reason reaches the screen, not "HTTP 409"
    a = open("webapp/src/lib/api.ts", encoding="utf-8").read()
    assert 'postDetail<MonthJob>("/api/storage/months/delete"' in a
    assert 'get<StorageMonths>("/api/storage/months")' in a
    d = open("webapp/src/components/candles/DownloadScreen.tsx", encoding="utf-8").read()
    assert "<MonthsPanel />" in d


def test_the_routes_exist_and_refuse_with_409():
    a = open("tradingagents/api.py", encoding="utf-8").read()
    assert '@app.get("/api/storage/months")' in a
    assert '@app.post("/api/storage/months/delete")' in a
    i = a.index('@app.post("/api/storage/months/delete")')
    assert "HTTPException(409" in a[i:i + 900]
