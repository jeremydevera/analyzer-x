"""`/api/backtest/logs` answers at once, whatever GitHub is doing.

Operator, Sep 09, 2026: *"check my current filter why is this having internal
server error once i open the csv file"*.

The CSV was fine. What broke was the PAGE around it. Measured on the
operator's machine that day:

    GET /api/backtest/logs                 82.3 s
    GET /api/backtest/logs?cloud=false      0.2 s

The cloud half shells out to `gh run list` and then to `git fetch` plus a
`git show` per shard, and the LOGS panel polls that endpoint every 30 seconds
— so a request was permanently in flight. Start a CSV export beside it (a
windowed download RE-MEASURES every row, ~0.09 s each) and the poll tipped
over its timeout, which the browser showed as a server error on a store that
was perfectly healthy:

    /api/health          200 in 23.8 s      (normally instant)
    /api/jobs            200 in  2.4 s
    /api/backtest/logs   TIMED OUT at 47 s

Two changes, and the numbers after them:

* the cloud read moved OFF the request into a background thread, so the first
  call is 0.61 s and says "reading GitHub in the background" rather than
  holding the connection; once the thread lands, the same call is 0.14 s with
  the real run and shard count. Cached for `CLOUD_CACHE_S`, failures included
  — a `gh` that is timing out will time out again a second later, and paying
  82 s to rediscover that on every poll is what took the panel down.
* the CSV export hands the interpreter lock back every `_CSV_BREATHE` rows, so
  a long download no longer starves the app: `/api/health` went 23.8 s -> 2.4 s
  while one ran.
"""
from __future__ import annotations

import time

import pytest

from tradingagents import backtest_logs as bl


@pytest.fixture(autouse=True)
def _clean_cache():
    bl._CLOUD.update(at=0.0, payload=None, busy=False)
    yield
    bl._CLOUD.update(at=0.0, payload=None, busy=False)


def test_the_first_call_does_not_wait_for_github(monkeypatch):
    """The bug: a poll every 30 s against an 82-second read."""
    started = []

    def _slow(limit: int = 200):
        started.append(time.time())
        time.sleep(5)                       # stand in for gh + git fetch
        return bl._cloud_cached([], {"ok": True, "run": 42, "shards": 20}, limit)

    monkeypatch.setattr(bl, "_read_cloud_errors", _slow)
    t0 = time.time()
    rows, status = bl._cloud_errors()
    took = time.time() - t0
    assert took < 1.0, f"the request waited {took:.1f}s on GitHub"
    assert status.get("reading") is True
    assert rows == []
    assert started, "and it did start the read"


def test_the_answer_arrives_once_the_background_read_lands(monkeypatch):
    def _quick(limit: int = 200):
        return bl._cloud_cached([{"pair": "AAA"}],
                                {"ok": True, "run": 42, "shards": 20}, limit)

    monkeypatch.setattr(bl, "_read_cloud_errors", _quick)
    bl._cloud_errors()
    for _ in range(50):
        if bl._CLOUD["payload"] is not None:
            break
        time.sleep(0.05)
    rows, status = bl._cloud_errors()
    assert status["run"] == 42 and status["shards"] == 20
    assert rows == [{"pair": "AAA"}]


def test_only_one_read_runs_at_a_time(monkeypatch):
    """The panel polls every 30 s. Without a guard, every poll spawns another
    `gh` while the last is still going."""
    calls = []

    def _slow(limit: int = 200):
        calls.append(1)
        time.sleep(3)
        return bl._cloud_cached([], {"ok": True}, limit)

    monkeypatch.setattr(bl, "_read_cloud_errors", _slow)
    for _ in range(6):
        bl._cloud_errors()
    time.sleep(0.4)
    assert len(calls) == 1, f"{len(calls)} background reads for 6 polls"


def test_a_failure_is_cached_too(monkeypatch):
    """A `gh` that is timing out will time out again a second later."""
    calls = []

    def _boom(limit: int = 200):
        calls.append(1)
        raise RuntimeError("gh: timed out")

    monkeypatch.setattr(bl, "_read_cloud_errors", _boom)
    bl._cloud_errors()
    for _ in range(40):
        if bl._CLOUD["payload"] is not None:
            break
        time.sleep(0.05)
    rows, status = bl._cloud_errors()
    assert status["ok"] is False and "timed out" in status["why"]
    bl._cloud_errors()
    time.sleep(0.2)
    assert len(calls) == 1, "a cached failure must not be retried on every poll"


def test_an_unreadable_cloud_never_reads_as_no_errors(monkeypatch):
    """The rule this module already had: the panel must not show a green count
    it did not earn."""
    monkeypatch.setattr(bl, "_read_cloud_errors",
                        lambda limit=200: bl._cloud_cached(
                            [], {"ok": False, "why": "gh: not logged in"}, limit))
    bl._cloud_errors()
    for _ in range(40):
        if bl._CLOUD["payload"] is not None:
            break
        time.sleep(0.05)
    _rows, status = bl._cloud_errors()
    assert status["ok"] is False


def test_logs_is_fast_even_with_the_cloud_asked_for(monkeypatch):
    """End to end: the endpoint's own payload."""
    monkeypatch.setattr(bl, "_read_cloud_errors",
                        lambda limit=200: (time.sleep(4) or
                                           bl._cloud_cached([], {"ok": True}, limit)))
    monkeypatch.setattr(bl, "pending", lambda force=False: {
        "count": 0, "by_timeframe": {}, "stored": 0, "measured": 0})
    t0 = time.time()
    got = bl.logs(include_cloud=True)
    took = time.time() - t0
    assert took < 1.0, f"logs() took {took:.1f}s"
    assert got["cloud"].get("reading") is True


# ------------------------------------------------------- the CSV's manners
def test_the_csv_hands_the_lock_back():
    """A windowed export re-measures every row and held the interpreter lock
    for the whole download; `/api/health` took 23.8 s beside it."""
    import inspect

    from tradingagents import api as api_mod

    src = inspect.getsource(api_mod.strategies_csv_lines)
    assert "_CSV_BREATHE" in src, "the export must pause for the rest of the app"
    assert "_time.sleep" in src
    assert api_mod._CSV_BREATHE >= 1
