"""A request never waits for GitHub — the second time this took the page down.

Sep 09, 2026, ~11:56am. The operator's filtered table request sat in the
browser for over five minutes with the Apply button reading "searching 306s".
Playwright's network list showed why: `/api/cloud/status` requests 95, 104,
112 and 119 in flight with no answer. Measured straight at the API:

    GET /api/cloud/status   200 in 216.3 s

The panel polls it every 4 s. `webapp/src/lib/api.ts` allows the app FOUR
lanes to the API (MAX_LANES, added that morning so a page switch stays
instant). Four hung status calls held all four; every other request queued in
the browser behind them. The API itself answered `/api/health` in 0.4 s.

Same disease as `/api/backtest/logs` earlier the same day (RCA-A): a polled
route that shells out to `gh` and `git` inside the request. Same cure, now in
one place — `tradingagents/slow_cache.BackgroundValue` — so the next polled
route does not have to rediscover it.
"""
from __future__ import annotations

import inspect
import time

from tradingagents import api
from tradingagents.slow_cache import BackgroundValue


# ---------------------------------------------------------- the mechanism
def test_the_first_call_answers_at_once_with_the_pending_value():
    def slow():
        time.sleep(3)
        return {"ok": True}
    bv = BackgroundValue("t", slow, ttl=60)
    t0 = time.time()
    got = bv.get(pending={"reading": True})
    assert time.time() - t0 < 0.5, "the request waited on the reader"
    assert got == {"reading": True}


def test_the_value_arrives_once_the_read_lands_and_is_then_served_from_cache():
    calls = []
    def quick():
        calls.append(1)
        return {"n": len(calls)}
    bv = BackgroundValue("t", quick, ttl=60)
    bv.get()
    assert bv.wait(5)
    assert bv.get() == {"n": 1}
    for _ in range(20):
        bv.get()
    time.sleep(0.2)
    assert calls == [1], "inside the ttl, no second read"


def test_only_one_read_runs_at_a_time_however_often_the_panel_polls():
    calls = []
    def slow():
        calls.append(1)
        time.sleep(1.5)
        return 1
    bv = BackgroundValue("t", slow, ttl=60)
    for _ in range(25):                     # 4-second polls stacking up
        bv.get()
    time.sleep(0.3)
    assert len(calls) == 1, f"{len(calls)} reads for 25 polls"


def test_a_failed_read_is_cached_as_a_value_not_retried_every_poll():
    calls = []
    def boom():
        calls.append(1)
        raise RuntimeError("gh: timed out")
    bv = BackgroundValue("t", boom, ttl=60)
    bv.get()
    assert bv.wait(5)
    got = bv.get()
    assert got["ok"] is False and "timed out" in got["why"]
    bv.get()
    time.sleep(0.2)
    assert calls == [1]


def test_a_stale_value_is_served_while_the_refresh_runs():
    """The panel sees the previous answer, never a blank, never a wait."""
    state = {"n": 0}
    def read():
        state["n"] += 1
        if state["n"] > 1:
            time.sleep(2)
        return state["n"]
    bv = BackgroundValue("t", read, ttl=0.1)
    bv.get(); assert bv.wait(5)
    time.sleep(0.15)                        # now stale
    t0 = time.time()
    assert bv.get() == 1                    # old value, instantly
    assert time.time() - t0 < 0.3


def test_on_error_shapes_the_failure_for_the_caller():
    bv = BackgroundValue("t", lambda: 1 / 0, ttl=60,
                         on_error=lambda exc: {"available": False, "why": str(exc),
                                               "run": None, "shards": []})
    bv.get(); assert bv.wait(5)
    got = bv.get()
    assert got["available"] is False and got["shards"] == [] and "division" in got["why"]


# ------------------------------------------------------------ the route
def test_cloud_status_reads_from_the_background_value_only():
    src = inspect.getsource(api.cloud_status)
    assert "_CLOUD_STATUS.get(" in src
    for slow_call in ("cs.available(", "cs.status(", "cs.live_progress(",
                      "_working_run_cached("):
        assert slow_call not in src, f"{slow_call} back inside the request"
    assert isinstance(api._CLOUD_STATUS, BackgroundValue)
    assert api._CLOUD_STATUS.reader is api._read_cloud_status


def test_the_pending_answer_says_it_is_reading_and_keeps_the_panels_shape():
    api._CLOUD_STATUS.forget()
    api._CLOUD_STATUS.reader = lambda: (time.sleep(3) or {})
    try:
        t0 = time.time()
        got = api.cloud_status()
        assert time.time() - t0 < 0.5
        assert got["reading"] is True and got["available"] is False
        assert got["run"] is None and got["shards"] == []
    finally:
        api._CLOUD_STATUS.reader = api._read_cloud_status
        api._CLOUD_STATUS.forget()


def test_the_panel_does_not_call_a_first_read_not_available():
    """`available: false` while still reading must not print "GitHub is not
    available" — that is a false label on a true number."""
    panel = open("webapp/src/components/backtest/JobsPanel.tsx",
                 encoding="utf-8").read()
    assert "cloud?.reading" in panel
    assert "checking GitHub…" in panel
    client = open("webapp/src/lib/api.ts", encoding="utf-8").read()
    assert "reading?: boolean" in client
