"""The RESOLVE PENDING count must be able to show the run's own work.

Sep 05, 2026 — the button was pressed and watched:

  7:58pm  RESOLVE PENDING starts, 5,152 pairs queued, count says 5,055
  8:10pm  3,101 pairs done, 73,299 bars stored, ZERO errors
  8:20pm  the pending count reads 5,095 — it went UP

Nothing was failing. Every count in `pending_work` is computed from
`market_sweep.candle_index(scan=False)`, which is a CACHE, and the download job
never refreshed it. The index was 27 minutes old, so its stored `last_ms`
values fell further behind with the wall clock while the job fixed the very
pairs it was counting. The button could never show its own work, and after the
run it would still have claimed ~5,000 pending.

Two things follow, and both are tested here: the job must refresh the index it
is judged by, and until it does, a stale count must SAY it is stale.
"""
import inspect
import re

from tradingagents import db_jobs as dj

HISTORY = "webapp/src/components/candles/DownloadHistory.tsx"


def test_the_download_refreshes_the_index_it_is_judged_by():
    src = inspect.getsource(dj._run_download)
    assert "candle_index()" in src, \
        "the job must refresh the cache pending_work reads"
    # BEFORE it reports finished, or the operator sees a done job with a
    # stale count
    i_refresh = src.index("candle_index()")
    i_done = src.index('"running": False')
    assert i_refresh < i_done, "refresh must come before the final report"


def test_a_failed_refresh_is_named_not_silent():
    """A silently stale index is exactly how this went unnoticed for a run."""
    src = inspect.getsource(dj._run_download)
    assert "could not refresh the candle index" in src


def test_the_refresh_says_what_it_is_doing():
    """It re-reads every rewritten file and took a minute on this store;
    without a line the screen sits on the last pair's name looking hung."""
    src = inspect.getsource(dj._run_download)
    assert "refreshing the candle index" in src


def test_pending_reports_how_old_its_index_is(monkeypatch, tmp_path):
    """A count from a 27-minute-old index is a 27-minute-old count."""
    import time

    from tradingagents import market_sweep as msw

    idx = tmp_path / "candle_index.json"
    idx.write_text("{}")
    old = time.time() - 1800
    import os

    os.utime(idx, (old, old))
    monkeypatch.setattr(msw, "INDEX_PATH", idx)
    monkeypatch.setattr(msw, "candle_index", lambda scan=False: {})
    monkeypatch.setattr(dj, "live_symbols", lambda: None)
    monkeypatch.setattr(dj, "_read", lambda p: {"pairs": []})
    got = dj._pending_sources()
    assert 1700 < got["index_age_s"] < 1900, got["index_age_s"]


def test_the_screen_says_when_the_count_is_stale():
    body = open(HISTORY, encoding="utf-8").read()
    assert "index_age_s" in body
    assert "min old" in body
    # only when it MATTERS — a fresh index needs no apology
    assert re.search(r"index_age_s.{0,20}>\s*300", body), \
        "it must be silent for a fresh index"


def test_a_fresh_index_reports_a_small_age(tmp_path, monkeypatch):
    from tradingagents import market_sweep as msw

    idx = tmp_path / "candle_index.json"
    idx.write_text("{}")
    monkeypatch.setattr(msw, "INDEX_PATH", idx)
    monkeypatch.setattr(msw, "candle_index", lambda scan=False: {})
    monkeypatch.setattr(dj, "live_symbols", lambda: None)
    monkeypatch.setattr(dj, "_read", lambda p: {"pairs": []})
    assert dj._pending_sources()["index_age_s"] < 5
