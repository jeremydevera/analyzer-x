"""The app's own order books reach GitHub EVERY HOUR, not once a day
(operator, Oct 31, 2026: "Go").

WHY. The app records Gate's normal book every minute for ~1,070 coins, but a
UTC day reached GitHub only at 00:20 UTC the next day. The nightly Backtest
v2 update runs ~05:47 UTC, so its last ~6 hours paid each coin's usual cost
- and since Gate's own archive ends Oct 22, 2026 04:00 UTC, the app's
recording is the ONLY per-minute cost from then on. Now, ten minutes past
every hour, the day so far goes up as ONE bundle (`partial-<day>-<HH>.npz`
in the `appbook-index` release, ~12 MB for a whole day of 1,070 coins,
measured Oct 31, 2026), named with its cut in the list of published days;
the finished day still goes up coin by coin at 00:20 UTC.

Every reader - this PC and GitHub's shards, through `book_for` - reads a
partial day up to its published cut and no further, so one strategy still
gets one result wherever it is measured.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

import pytest

from tradingagents import app_books as ab, book_history as bh, cost_store as cs

D = 1793404800                 # Oct 31, 2026 00:00 UTC
DAY = "20261031"
H = 3600


def _r(t, bid):
    return {"t": t, "bid": bid, "ask": bid + 0.01, "spread": 0.0003, "buy": 0.0002,
            "sell": 0.0002, "exhausted": False, "source": "app", "at": 3}


class GitHub:
    """The releases of the publishing repo, in memory: what `gh release
    upload` put up, what `release view` lists and `delete-asset` removes."""

    def __init__(self):
        self.assets: dict = {}          # (tag, name) -> bytes
        self.calls: list = []
        self.fail: set = set()          # tags whose uploads are refused

    def __call__(self, *args):
        self.calls.append(args)
        if args[:2] == ("release", "upload"):
            tag = args[2]
            if tag in self.fail:
                return subprocess.CompletedProcess(args, 1, "", "HTTP 502")
            for f in args[3:]:
                if f.startswith("-"):
                    break
                self.assets[(tag, Path(f).name)] = Path(f).read_bytes()
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[:2] == ("release", "view"):
            names = [n for (t, n) in self.assets if t == args[2]]
            return subprocess.CompletedProcess(
                args, 0, json.dumps({"assets": [{"name": n} for n in names]}), "")
        if args[:2] == ("release", "delete-asset"):
            self.assets.pop((args[2], args[3]), None)
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    def uploads(self, tag=None):
        return [c for c in self.calls if c[:2] == ("release", "upload")
                and (tag is None or c[2] == tag)]

    def fetch(self, u):
        """A machine's download: the asset at its release address, or 404."""
        import urllib.parse as up

        parts = u.split("/releases/download/", 1)[1].split("/", 1)
        got = self.assets.get((parts[0], up.unquote(parts[1])))
        return (200, got) if got is not None else (404, b"")


@pytest.fixture
def gh(tmp_path, monkeypatch):
    monkeypatch.setattr(ab, "HOME", tmp_path / "app_books")
    monkeypatch.setattr(ab.time, "sleep", lambda _s: None)
    monkeypatch.setenv("TA_VENUE", "gate")
    monkeypatch.setattr(ab, "_TICKED", {"at": 0.0})
    monkeypatch.setattr(ab, "_PARTIAL_FAIL", {})
    g = GitHub()
    monkeypatch.setattr(ab, "_gh", g)
    return g


def _tick(now):
    """`publish_tick` as the supervisor calls it: pytest sets its own marker
    again for every phase of a test, so it is taken out here, at the call."""
    was = os.environ.pop("PYTEST_CURRENT_TEST", None)
    try:
        return ab.publish_tick(now=now)
    finally:
        if was is not None:
            os.environ["PYTEST_CURRENT_TEST"] = was


def _record(rows: dict, *, flushed_at: float):
    """Write each coin's readings, then stamp each day file as flushed at
    `flushed_at` - the moment the recorder last appended to it."""
    st = ab.Store()
    for sym, rs in rows.items():
        for r in rs:
            st.add(sym, r)
    st.flush()
    for sym in rows:
        for f in (ab.HOME / sym).glob("*.bin"):
            os.utime(f, (flushed_at, flushed_at))


def _on_github(monkeypatch, tmp_path, g, sym, lo, hi):
    """What one of GitHub's machines reads: no recorder folder, only the
    releases - a fresh process each time."""
    monkeypatch.setattr(ab, "HOME", tmp_path / "a_runner_has_no_recorder")
    monkeypatch.setattr(ab, "_REMOTE", {})
    monkeypatch.setattr(ab, "_REMOTE_DAYS", {})
    monkeypatch.setattr(ab, "_BUNDLES", {})
    monkeypatch.setattr(cs, "_fetch", g.fetch)
    try:
        return ab.book_for(sym, lo, hi)
    finally:
        monkeypatch.setattr(ab, "HOME", tmp_path / "app_books")


def _same(a, b):
    assert a["t"].tolist() == b["t"].tolist()
    for k in cs.KEYS:
        assert a[k].tolist() == b[k].tolist(), k


# ------------------------------------------------- read up to its stamp
def test_an_hourly_upload_is_read_up_to_its_stamp_and_no_further(gh, monkeypatch, tmp_path):
    """3:10am UTC: the day so far goes up, cut at 3:00am. A reading at
    3:01am is on this PC's disk but not on GitHub, so neither side reads it;
    every minute before the cut is read by both, identically."""
    _record({"QNTX_USDT": [_r(D + 60, 36.91), _r(D + 2 * H, 36.95),
                           _r(D + 3 * H - 60, 36.97), _r(D + 3 * H + 60, 37.0)]},
            flushed_at=D + 3 * H + 300)
    got = ab.publish_partial(now=D + 3 * H + 600)
    assert got["through"] == D + 3 * H and got["coins"] == 1
    assert [c[2] for c in gh.uploads()] == ["appbook-index", "appbook-index"], \
        "one bundle, then the list naming it - never 1,070 files an hour"
    names = [n for (_t, n) in gh.assets]
    assert f"partial-{DAY}-03.npz" in names and "days.json" in names
    here = ab.book_for("QNTX_USDT", D, D + 4 * H)
    assert here["t"].tolist() == [D + 60, D + 2 * H, D + 3 * H - 60], \
        "3:01am is after the cut: not read here either"
    there = _on_github(monkeypatch, tmp_path, gh, "QNTX_USDT", D, D + 4 * H)
    _same(here, there)
    index = json.loads(gh.assets[("appbook-index", "days.json")])
    assert DAY not in index["days"], "a partial day is never listed as finished"
    assert index["partial"][DAY] == {"asset": f"partial-{DAY}-03.npz",
                                     "through": D + 3 * H}


def test_a_coin_flushed_late_is_cut_where_its_file_proves_it_complete(gh, monkeypatch, tmp_path):
    """Harddev: a coin whose file was last appended at 1:30am (its feed
    stopped) holds every minute before 1:28am (a reading reaches memory within
    PROOF_S of its minute) and no promise after; it goes up cut there, on both
    sides, never with a promise its file cannot keep."""
    _record({"QNTX_USDT": [_r(D + 60, 36.91), _r(D + H + 1500, 36.95)]},
            flushed_at=D + 3 * H + 300)
    _record({"ANKR_USDT": [_r(D + 60, 0.01), _r(D + H + 1620, 0.011),
                           _r(D + H + 1680, 0.012)]},
            flushed_at=D + H + 1800)             # 1:30am, nothing since
    ab.publish_partial(now=D + 3 * H + 600)
    cut = ab._cut_here(DAY, "ANKR_USDT")
    assert ab.PROOF_S == 120
    assert cut == D + H + 1680, "1:28am: two minutes before the last write's minute"
    here = ab.book_for("ANKR_USDT", D, D + 4 * H)
    assert here["t"].tolist() == [D + 60, D + H + 1620], \
        "1:28am itself is past the promise, though this disk holds it"
    assert ab._cut_here(DAY, "QNTX_USDT") == D + 3 * H, "a coin still recorded: the hour"
    _same(here, _on_github(monkeypatch, tmp_path, gh, "ANKR_USDT", D, D + 4 * H))


def test_nothing_goes_up_before_the_days_first_hour_has_finished(gh):
    _record({"QNTX_USDT": [_r(D + 60, 36.91)]}, flushed_at=D + 300)
    got = ab.publish_partial(now=D + 600)
    assert got["coins"] == 0 and gh.uploads() == []


# ------------------------------------------------- a newer one replaces it
def test_a_newer_partial_replaces_an_older_one_on_this_pc(gh, monkeypatch, tmp_path):
    _record({"QNTX_USDT": [_r(D + 60, 36.91), _r(D + H + 60, 36.95)]},
            flushed_at=D + H + 300)
    ab.publish_partial(now=D + H + 600)                      # cut 1:00am
    assert ab.book_for("QNTX_USDT", D, D + 3 * H)["t"].tolist() == [D + 60]
    _record({"QNTX_USDT": [_r(D + 2 * H - 60, 36.99)]}, flushed_at=D + 2 * H + 300)
    ab.publish_partial(now=D + 2 * H + 600)                  # cut 2:00am
    here = ab.book_for("QNTX_USDT", D, D + 3 * H)
    assert here["t"].tolist() == [D + 60, D + H + 60, D + 2 * H - 60], \
        "the 2:00am upload is what this PC reads now, never the 1:00am one"
    _same(here, _on_github(monkeypatch, tmp_path, gh, "QNTX_USDT", D, D + 3 * H))


def test_a_long_running_reader_reads_the_list_again_and_the_newer_bundle(gh, monkeypatch, tmp_path):
    """RCA-2026-10-30-C's shape, never repeated: a reader that kept the
    1:00am list for ever would never see the 2:00am bundle."""
    _record({"QNTX_USDT": [_r(D + 60, 36.91), _r(D + H + 60, 36.95)]},
            flushed_at=D + 2 * H + 300)
    ab.publish_partial(now=D + H + 600)
    clock = {"now": 1000.0}
    monkeypatch.setattr(ab, "_clock", lambda: clock["now"])
    monkeypatch.setattr(ab, "HOME", tmp_path / "a_runner_has_no_recorder")
    for k in ("_REMOTE", "_REMOTE_DAYS", "_BUNDLES"):
        monkeypatch.setattr(ab, k, {})
    monkeypatch.setattr(cs, "_fetch", gh.fetch)
    assert ab.book_for("QNTX_USDT", D, D + 3 * H)["t"].tolist() == [D + 60]
    monkeypatch.setattr(ab, "HOME", tmp_path / "app_books")
    ab.publish_partial(now=D + 2 * H + 600)
    monkeypatch.setattr(ab, "HOME", tmp_path / "a_runner_has_no_recorder")
    assert ab.book_for("QNTX_USDT", D, D + 3 * H)["t"].tolist() == [D + 60], \
        "the list read a moment ago still answers"
    clock["now"] += ab.INDEX_TTL_S + 1
    assert ab.book_for("QNTX_USDT", D, D + 3 * H)["t"].tolist() == [D + 60, D + H + 60]


def test_a_restart_inside_the_hour_never_sends_the_same_bundle_twice(gh):
    """Harddev: the same name sent again is a delete then an upload, and a
    machine asking for it in between would read nothing for today."""
    _record({"QNTX_USDT": [_r(D + 60, 36.91)]}, flushed_at=D + 2 * H + 300)
    assert ab.publish_partial(now=D + 2 * H + 600)["coins"] == 1
    n = len(gh.uploads())
    again = ab.publish_partial(now=D + 2 * H + 900)       # a new process, same hour
    assert again["coins"] == 0 and again["why"] == "this hour already went up"
    assert len(gh.uploads()) == n


def test_a_list_that_cannot_be_read_again_keeps_the_one_read_before(gh, monkeypatch, tmp_path):
    """Harddev: re-reading the list every INDEX_TTL_S must not let one cut
    wire take every app book out of the coins a machine has left."""
    _record({"QNTX_USDT": [_r(D + 60, 36.91)]}, flushed_at=D + 2 * H + 300)
    ab.publish_partial(now=D + 2 * H + 600)
    clock = {"now": 1000.0}
    monkeypatch.setattr(ab, "_clock", lambda: clock["now"])
    monkeypatch.setattr(ab, "HOME", tmp_path / "a_runner_has_no_recorder")
    for k in ("_REMOTE", "_REMOTE_DAYS", "_BUNDLES"):
        monkeypatch.setattr(ab, k, {})
    monkeypatch.setattr(cs, "_fetch", gh.fetch)
    assert ab.book_for("QNTX_USDT", D, D + 3 * H)["t"].tolist() == [D + 60]
    monkeypatch.setattr(cs, "_fetch", lambda u: (0, b""))
    clock["now"] += ab.INDEX_TTL_S + 1
    assert ab.book_for("QNTX_USDT", D, D + 3 * H)["t"].tolist() == [D + 60]


def test_a_list_never_read_is_asked_again_in_a_minute(gh, monkeypatch, tmp_path):
    """Harddev: the list is swapped in every hour (a delete, then an upload);
    a machine whose FIRST read lands in between must not go without the app's
    books for half an hour."""
    _record({"QNTX_USDT": [_r(D + 60, 36.91)]}, flushed_at=D + 2 * H + 300)
    ab.publish_partial(now=D + 2 * H + 600)
    clock = {"now": 1000.0}
    monkeypatch.setattr(ab, "_clock", lambda: clock["now"])
    monkeypatch.setattr(ab, "HOME", tmp_path / "a_runner_has_no_recorder")
    for k in ("_REMOTE", "_REMOTE_DAYS", "_BUNDLES"):
        monkeypatch.setattr(ab, k, {})
    monkeypatch.setattr(cs, "_fetch", lambda u: (404, b""))
    assert len(ab.book_for("QNTX_USDT", D, D + 3 * H)["t"]) == 0
    clock["now"] += ab.RETRY_LIST_S + 1
    assert len(ab.book_for("QNTX_USDT", D, D + 3 * H)["t"]) == 0, "missed twice"
    monkeypatch.setattr(cs, "_fetch", gh.fetch)
    clock["now"] += 30
    assert len(ab.book_for("QNTX_USDT", D, D + 3 * H)["t"]) == 0, "not every call"
    clock["now"] += ab.RETRY_LIST_S
    assert ab.book_for("QNTX_USDT", D, D + 3 * H)["t"].tolist() == [D + 60]


def test_a_bundle_that_could_not_be_read_is_asked_again_later_not_every_coin(gh, monkeypatch, tmp_path):
    _record({"QNTX_USDT": [_r(D + 60, 36.91)]}, flushed_at=D + 2 * H + 300)
    ab.publish_partial(now=D + 2 * H + 600)
    clock = {"now": 1000.0}
    monkeypatch.setattr(ab, "_clock", lambda: clock["now"])
    monkeypatch.setattr(ab, "HOME", tmp_path / "a_runner_has_no_recorder")
    for k in ("_REMOTE", "_REMOTE_DAYS", "_BUNDLES"):
        monkeypatch.setattr(ab, k, {})
    asked = []

    def flaky(u):
        asked.append(u)
        if u.endswith(".npz") and len([a for a in asked if a.endswith(".npz")]) == 1:
            return 0, b""                                    # the wire cut once
        return gh.fetch(u)

    monkeypatch.setattr(cs, "_fetch", flaky)
    assert len(ab.book_for("QNTX_USDT", D, D + 3 * H)["t"]) == 0
    assert len(ab.book_for("ANKR_USDT", D, D + 3 * H)["t"]) == 0
    assert len([a for a in asked if a.endswith(".npz")]) == 1, "not asked again per coin"
    clock["now"] += ab.INDEX_TTL_S + 1
    assert ab.book_for("QNTX_USDT", D, D + 3 * H)["t"].tolist() == [D + 60]


# ------------------------------------------------- the finished day lands
def test_the_finished_days_final_upload_still_lands(gh, monkeypatch, tmp_path):
    """00:20 UTC the next day: the whole day goes up coin by coin, the list
    names it finished and drops its partial, and both sides read all of it -
    11:30pm included, which no hourly bundle held."""
    _record({"QNTX_USDT": [_r(D + 60, 36.91), _r(D + 23 * H + 1800, 37.2)]},
            flushed_at=D + 23 * H + 300)
    ab.publish_partial(now=D + 23 * H + 600)                 # cut 11:00pm
    assert ab.book_for("QNTX_USDT", D, D + 86400)["t"].tolist() == [D + 60]
    tick = _tick(D + 86400 + 1500)             # Nov 01 00:25 UTC
    assert [g["day"] for g in tick["published"]] == [DAY]
    assert ("appbook-20261031-b", "QNTX_USDT.npz") in gh.assets
    index = json.loads(gh.assets[("appbook-index", "days.json")])
    assert DAY in index["days"] and DAY not in index.get("partial", {})
    here = ab.book_for("QNTX_USDT", D, D + 86400)
    assert here["t"].tolist() == [D + 60, D + 23 * H + 1800]
    _same(here, _on_github(monkeypatch, tmp_path, gh, "QNTX_USDT", D, D + 86400))


def test_a_day_with_only_an_hourly_upload_is_still_finished_the_next_day(gh):
    """Harddev: the old tick finished only a day with NO marker; an hourly
    upload writes one, and the day must still go up whole."""
    _record({"QNTX_USDT": [_r(D + 60, 36.91)]}, flushed_at=D + 2 * H + 300)
    ab.publish_partial(now=D + 2 * H + 600)
    assert ab._marker(DAY).exists()
    tick = _tick(D + 86400 + 3 * H)
    assert [g["day"] for g in tick["published"]] == [DAY]
    assert ab._published(DAY) == {"QNTX_USDT"}


def test_a_final_upload_that_failed_whole_keeps_the_hourly_one_on_both_sides(gh, monkeypatch, tmp_path):
    """Harddev: every coin of the final upload refused - GitHub's list still
    names the 11:00pm bundle, so this PC must keep reading it too."""
    _record({"QNTX_USDT": [_r(D + 60, 36.91), _r(D + 23 * H + 1800, 37.2)]},
            flushed_at=D + 23 * H + 300)
    ab.publish_partial(now=D + 23 * H + 600)
    gh.fail.add("appbook-20261031-b")
    got = ab.publish_day(DAY)
    assert got["failed"] == ["QNTX_USDT"]
    here = ab.book_for("QNTX_USDT", D, D + 86400)
    assert here["t"].tolist() == [D + 60]
    _same(here, _on_github(monkeypatch, tmp_path, gh, "QNTX_USDT", D, D + 86400))


# ------------------------------------------------- PC and GitHub agree
def test_a_bundle_up_but_its_list_refused_is_read_by_neither_side(gh, monkeypatch, tmp_path):
    """The 2:00am bundle went up, the list naming it did not: GitHub still
    reads the 1:00am cut, so this PC does too."""
    _record({"QNTX_USDT": [_r(D + 60, 36.91), _r(D + H + 60, 36.95)]},
            flushed_at=D + 2 * H + 300)
    ab.publish_partial(now=D + H + 600)

    real = gh.__call__

    def list_refused(*args):
        if args[:2] == ("release", "upload") and any(
                str(a).endswith("days.json") for a in args):
            gh.calls.append(args)
            return subprocess.CompletedProcess(args, 1, "", "HTTP 502")
        return real(*args)

    monkeypatch.setattr(ab, "_gh", list_refused)
    got = ab.publish_partial(now=D + 2 * H + 600)
    assert got["coins"] == 0 and "list" in got["why"]
    here = ab.book_for("QNTX_USDT", D, D + 3 * H)
    assert here["t"].tolist() == [D + 60]
    _same(here, _on_github(monkeypatch, tmp_path, gh, "QNTX_USDT", D, D + 3 * H))


def test_the_engine_reads_the_same_book_on_this_pc_and_on_github(gh, monkeypatch, tmp_path):
    """`cost_store.with_app_books` - the ONE function both sides call - over
    Gate's record, after an hourly upload."""
    record = bh.pack([_r(D + 60, 36.94) | {"source": "full"},
                      _r(D + 2 * H + 60, 36.96) | {"source": "full"}])
    _record({"QNTX_USDT": [_r(D + 60, 36.91), _r(D + 2 * H + 60, 36.95)]},
            flushed_at=D + 2 * H + 300)
    ab.publish_partial(now=D + 2 * H + 600)                  # cut 2:00am
    here = cs.with_app_books("QNTX_USDT", record, D, D + 3 * H)
    assert here["bid"].tolist() == [36.91, 36.96], \
        "the app's 36.91 before the cut; Gate's record after it"
    monkeypatch.setattr(ab, "HOME", tmp_path / "a_runner_has_no_recorder")
    for k in ("_REMOTE", "_REMOTE_DAYS", "_BUNDLES"):
        monkeypatch.setattr(ab, k, {})
    monkeypatch.setattr(cs, "_fetch", gh.fetch)
    _same(here, cs.with_app_books("QNTX_USDT", record, D, D + 3 * H))


# ------------------------------------------------- the hourly schedule
def test_the_tick_sends_the_day_so_far_ten_minutes_past_each_hour_once(gh):
    _record({"QNTX_USDT": [_r(D + 60, 36.91), _r(D + 5 * H - 60, 36.95)]},
            flushed_at=D + 5 * H + 300)
    early = _tick(D + 5 * H + 300)             # 5:05am
    assert early.get("partial") is None and gh.uploads() == [], \
        "5:05am: the recorder's 5-minute flush may not have written 4:59am yet"
    got = _tick(D + 5 * H + 600)               # 5:10am
    assert got["partial"]["through"] == D + 5 * H
    n = len(gh.uploads())
    again = _tick(D + 5 * H + 1800)            # 5:30am
    assert again.get("partial") is None and len(gh.uploads()) == n, "once an hour"
    assert _tick(D + 6 * H + 600)["partial"]["through"] == D + 6 * H


def test_a_failed_hourly_upload_is_tried_next_hour_and_said_once(gh, caplog):
    _record({"QNTX_USDT": [_r(D + 60, 36.91)]}, flushed_at=D + 9 * H + 300)
    gh.fail.add("appbook-index")
    caplog.set_level(logging.INFO, logger="app_books")
    for h in (5, 6, 7):
        got = _tick(D + h * H + 600)
        assert got["partial"]["coins"] == 0
        _tick(D + h * H + 1200)                # same hour: not again
    tries = [c for c in gh.uploads("appbook-index")]
    assert len(tries) == 3 * ab.UPLOAD_TRIES, "one upload (with its own retries) an hour"
    warned = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warned) == 1, [r.getMessage() for r in warned]
    assert not ab._marker(DAY).exists(), "nothing went up: nothing is read here"
    gh.fail.clear()
    got = _tick(D + 8 * H + 600)
    assert got["partial"]["through"] == D + 8 * H
    said = [r.getMessage() for r in caplog.records]
    assert any("after 3 failed hour" in m for m in said), said


def test_old_bundles_are_removed_but_never_one_the_list_names(gh):
    _record({"QNTX_USDT": [_r(D + 60, 36.91)]}, flushed_at=D + 23 * H + 300)
    for h in range(1, 23):
        ab.publish_partial(now=D + h * H + 600)
    held = sorted(n for (t, n) in gh.assets if n.startswith("partial-"))
    newest = f"partial-{DAY}-22.npz"
    assert newest in held
    oldest_kept = 22 - ab.KEEP_PARTIAL_S // H
    assert held[0] == f"partial-{DAY}-{oldest_kept:02d}.npz", held
    assert len(held) <= ab.KEEP_PARTIAL_S // H + 1


def test_a_bundle_is_far_smaller_than_github_s_limits():
    """Measured Oct 31, 2026 on this PC: the whole day of 1,070 coins
    (1,524,750 readings) packs to 11,972,368 bytes - GitHub takes an asset up
    to 2 GiB - and an hour's upload is two requests (bundle, list) plus the
    clean-up, against 5,000 an hour per account."""
    assert ab.KEEP_PARTIAL_S >= 6 * H, "a GitHub job runs at most 6 hours"
    assert ab.PARTIAL_AFTER_S > ab.FLUSH_S, \
        "the hour's last minute must be on disk before the hour goes up"
