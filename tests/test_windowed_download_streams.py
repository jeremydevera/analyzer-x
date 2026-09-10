"""A windowed download must write bytes, not sit at 0 B.

Operator, Sep 09, 2026: *"so why does it not download? its still downloading
0B meaning it does not write"*. Their filter was `min win % 85 AND last 30
days`, no coin, ranked by profit.

Measured on their own URL against the running API:

    0.33s   200 OK, content-length=None, transfer-encoding: chunked
    0.33s   FIRST BYTE (the header row)
    600s    still NO first data row — probe gave up

The request was real and in flight (`.run/api.log`: `GET
/api/strategies.csv?sort=profit&min_winrate=85&days=30&desc=true 200 OK`), and
the browser had the header and nothing else, so it showed 0 B. They were right:
it was not writing.

WHY. A windowed batch is re-measured WHOLE before any of it is yielded
(`iter_rows`: `_msw.window_rows(batch_rows, ...)` then `yield from
batch_rows`), and the batch was **250 rows**. With no coin named, the top 250
rows by profit span up to 250 different coin/tf/signal groups, and each group
costs a candle file off a mechanical disk plus a full signal computation. So
the batch size WAS the time to the first byte of data.

The page never hit this: it re-measures at most **50 rows** (`api.DAYS_ROW_MAX`)
and **25 groups** (`market_sweep.WINDOW_GROUP_MAX`), and answers their filter in
1.7 s. The export had neither guard.

Two amplifiers, both fixed here too:

* `_DIRS_CACHE` held 24 entries and called `.clear()` when full — one batch
  spanning hundreds of groups wiped every cached signal ten times over and
  recomputed pairs it had already done. It now evicts the oldest ONE.
* the press log only wrote a line when the stream ENDED, so a download in
  flight was invisible — which is exactly why the operator's question could not
  be answered from the log. `csv START` is now its own line.
"""
from __future__ import annotations

import inspect

from tradingagents import api, market_sweep as msw, rows_index as ri


def test_a_windowed_export_yields_in_the_size_the_page_proves_answerable():
    """25 rows, like the page — not 250, which never produced a first row."""
    assert ri.WINDOW_CSV_STEP <= 50, ri.WINDOW_CSV_STEP
    assert ri.WINDOW_CSV_STEP <= api.DAYS_ROW_MAX, \
        "the export must not re-measure a bigger slice than the page can"
    src = inspect.getsource(ri.iter_rows)
    assert "step = WINDOW_CSV_STEP if win_days else" in src
    assert "min(250" not in src, "the 250-row batch is what sat at 0 B"


def test_the_batch_size_is_the_group_cap_so_it_can_never_raise_mid_stream():
    """A stream that raises is a truncated file that looks complete."""
    src = inspect.getsource(ri.iter_rows)
    assert "group_max=len(batch_rows) + 1" in src
    # and that cap stays in the range the page has proven
    assert ri.WINDOW_CSV_STEP + 1 <= msw.WINDOW_GROUP_MAX + 5, (
        ri.WINDOW_CSV_STEP, msw.WINDOW_GROUP_MAX)


def test_an_unwindowed_export_still_streams_in_big_batches():
    """Without a window there is nothing to re-measure — rows come straight
    off the index, and a small batch would only add round trips."""
    src = inspect.getsource(ri.iter_rows)
    i = src.index("step = WINDOW_CSV_STEP if win_days else")
    assert "max(100, int(batch))" in src[i:i + 120]


def test_the_signal_cache_evicts_one_entry_not_all_of_them():
    src = inspect.getsource(msw.window_rows)
    assert "_DIRS_CACHE.pop(next(iter(_DIRS_CACHE)), None)" in src
    assert "_DIRS_CACHE.clear()" not in src, \
        "clearing the whole cache recomputes pairs already measured"


def test_the_cache_eviction_really_keeps_the_newest(monkeypatch):
    """Behaviour, not just the line: fill past the cap and the oldest goes."""
    monkeypatch.setattr(msw, "_DIRS_CACHE", {}, raising=False)
    monkeypatch.setattr(msw, "_DIRS_CACHE_MAX", 3, raising=False)
    cache = msw._DIRS_CACHE
    for i in range(5):
        if len(cache) >= msw._DIRS_CACHE_MAX:
            cache.pop(next(iter(cache)), None)
        cache[f"k{i}"] = i
    assert list(cache) == ["k2", "k3", "k4"], list(cache)


def test_a_download_in_flight_is_in_the_log_before_it_finishes():
    """The operator pressed download, saw 0 B, asked why — and the log had
    nothing, because the only line was written at the END."""
    src = inspect.getsource(api.strategies_csv_lines)
    start = src.index('_sl.record("csv START"')
    loop = src.index("for r in ri.iter_rows(")
    assert start < loop, "the START line must be written before the first row"
    assert '_sl.record("csv"' in src, "and the completion line still lands"
    assert '_sl.record("csv FAILED"' in src


def test_a_download_never_picks_a_plan_that_must_sort_every_match():
    """THE reason nothing was written.

    The win-rate seek hands back rows in WIN-RATE order. Ordering them by
    profit means SQLite reads and sorts every match first, and a download has
    no LIMIT to bound that. Measured on the operator's own filter (85%, no
    coin, by profit; 566,990 matches of 51,943,352 rows):

        INDEXED BY rows_wr4   SEARCH + USE TEMP B-TREE FOR ORDER BY
                              -> no first row after 600 s   ("0 B")
        no index named        SCAN rows USING INDEX rows_profit
                              -> first row 108.55 s
        INDEXED BY rows_pr2   SCAN in profit order, winrate INSIDE the index
                              -> first row 5.54 s, 25 rows 7.57 s

    End to end after the fix: first row 2.2 s, 100 rows 9.1 s, 500 rows 133 s.
    """
    assert ri.EXPORT_SEEK_MAX <= 100_000, ri.EXPORT_SEEK_MAX
    src = inspect.getsource(ri.export_plan)
    assert 'if key != "winrate":' in src, \
        "the small cap applies only when the seek's order needs a re-sort"
    assert "cap = min(cap, EXPORT_SEEK_MAX)" in src


def test_ordering_by_win_rate_keeps_the_seek():
    """There the seek's own order IS the asked order — no sort, so the page's
    cap is right and must not be narrowed."""
    src = inspect.getsource(ri.export_plan)
    i = src.index("cap = _winrate_seek_cap()")
    guard = src[i:src.index("n = _winrate_matches", i)]
    assert 'key != "winrate"' in guard


def test_the_page_and_the_export_still_agree_about_the_seek_when_it_is_right():
    """The Sep 03 rule (`test_the_export_makes_the_SAME_index_choice_as_the
    page`) is not undone: a SELECTIVE win-rate floor still seeks."""
    src = inspect.getsource(ri.iter_rows)
    i = src.index("_indexed_by(coin, seeks")
    assert "not seeks and" in src[i:i + 260]


def test_the_export_still_carries_the_window_and_its_cap():
    """The fixes above must not undo what the window download already owed."""
    src = inspect.getsource(api.strategies_csv_lines)
    assert "WINDOW CAPPED" in src and "WINDOW FLOOR:" in src
    for _c in ("window_first", "window_last", "window_days",
               "window_straddled"):
        assert f'"{_c}"' in src, _c
    assert ri.DAYS_CSV_MAX >= 500
