"""The table's own route must not wait on `rows_index.status()`.

MEASURED on the operator's rebuilt store, Sep 10, 2026, right after the swap:

    ri.query(limit=500)          1.11 s
    ri.query(limit=500, fresh)   2.25 s
    stamp_measured(500 rows)     0.035 s
    ri.status()                  267.55 s      <-- called on every poll

`status()` walks `stale_pairs()`, which stats all 5,367 pair files and their
state files, so on a cold cache it is minutes. `/api/strategies` called it
INSIDE the request — and the panel polls that route — so a request whose real
work took 1.1 s answered in over four minutes, and my own probe timed out at
240 s twice while the store itself was answering in under a second.

This is PATTERN 4 in docs/RCA.md, written after two routes took the page down
the same way one day apart: *"a polled route must never do the slow thing
inside the request"*. `slow_cache.BackgroundValue` was built that morning so
the third one would not have to rediscover it. This is the third.

The reindex BUTTON keeps reading it live, and that is deliberate: the number a
button prints is the number of work it will do (RCA-2026-09-10-C), so it must
be the real one, not one up to 20 s old.
"""
from __future__ import annotations

import inspect
import time

import pytest

from tradingagents import api, rows_index as ri


@pytest.fixture(autouse=True)
def _fresh_reader():
    api._INDEX_STATUS.forget()
    yield
    api._INDEX_STATUS.forget()


def _calls(fn) -> set:
    """Every `x.y(...)` and `y(...)` this function CALLS, by name.

    The AST, not a string search: the first version of this test grepped for
    `ri.status()` and went red on the COMMENT that explains why the call is
    gone. `test_no_artifact_is_unpacked_on_the_system_drive` already learned
    this — read the calls, never the prose.
    """
    import ast
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute):
                base = getattr(f.value, "id", "")
                out.add(f"{base}.{f.attr}" if base else f.attr)
            elif isinstance(f, ast.Name):
                out.add(f.id)
    return out


def test_the_route_does_not_call_status_inline():
    calls = _calls(api.strategies)
    assert "index_status" in calls
    assert "ri.status" not in calls, \
        "the polled route must never call it directly"


def test_the_storage_route_does_not_either():
    """It is polled by the Storage screen and reads the same 5,367 files."""
    calls = _calls(api.backtest_storage)
    assert "index_status" in calls and "ri.status" not in calls


def test_a_slow_status_does_not_slow_the_table(monkeypatch):
    """The one that matters: drive the REAL route with a status() that takes
    five seconds and require the answer anyway."""
    slow = []

    def crawl():
        slow.append(1)
        time.sleep(5)
        return {"pairs_indexed": 1, "rows": 1, "behind": 0, "stale": 0}

    monkeypatch.setattr(ri, "status", crawl)
    t0 = time.time()
    got = api.strategies(limit=1)
    el = time.time() - t0
    assert el < 2.0, f"the route waited {el:.1f}s on a background read"
    assert "index" in got, "and it still answers with the key the panel reads"


def test_the_first_answer_says_UNKNOWN_not_zero(monkeypatch):
    """A zero `pairs_indexed` claims an empty store, and `behind` is
    `on_disk - pairs`, so a zero there claims EVERY pair is missing — the
    loudest possible version of a default that reads as data
    (RCA-2026-09-10-F)."""
    monkeypatch.setattr(ri, "status", lambda: time.sleep(5) or {})
    st = api.index_status()
    assert st.get("pairs_indexed") is None
    assert st.get("behind") is None
    assert st.get("reading") is True, "and it must say it is still reading"


def test_a_failing_status_is_reported_not_swallowed(monkeypatch):
    def boom():
        raise OSError("the store is gone")

    monkeypatch.setattr(ri, "status", boom)
    api._INDEX_STATUS.forget()
    api.index_status()                      # kicks the read off
    for _ in range(100):                    # let the one worker finish
        time.sleep(0.05)
        st = api.index_status()
        if st.get("unreadable"):
            break
    assert "the store is gone" in (st.get("unreadable") or ""), st
    assert st.get("pairs_indexed") is None, "never 0 — that would read as empty"


def test_the_reindex_button_still_reads_it_LIVE():
    """The count on a button is the count of work it will do. A cached number
    would promise a job that is already done, or hide one that appeared —
    RCA-2026-09-10-C, where the button printed 806 for a 5,276-pair job."""
    # the CALLS, so a comment mentioning it can never satisfy this
    assert "ri.status" in _calls(api.strategies_reindex), \
        "a press is not a poll: it must read the real number"
    assert "index_status" not in _calls(api.strategies_reindex), \
        "a cached count would promise work that is already done"


def test_the_ttl_is_short_enough_to_be_useful():
    """20 s of staleness on "how far behind is the index" costs nothing — the
    number moves a pair at a time over hours — but a minute would make the
    'catching up' banner lie about a finished catch-up."""
    assert 5.0 <= api.INDEX_STATUS_TTL <= 30.0
