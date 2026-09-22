"""A refusal that says "try again shortly" must know whether that is true.

Operator, `Sep 15, 2026 9:23pm`: *"when i search 46SGBAHD in filter its taking
too long is tihs expected"*, then *"i want root cause and document this and fix
this"*.

What their screen did: the find-by-ID box sends `row_id=46SGBAHD`, the API
answered **instantly** with

    finding row #46SGBAHD needs the id index (rows_id); it is being built in
    the background — try again shortly

and the panel spun. Every word of that was true about the CHILD and false
about the WAIT:

* `rows_id` genuinely does not exist — find-by-ID without it is a covering
  scan of **113,439,286** rows, measured at **49.8 s** for this very id
  (`FASTSTOCK 1h`).
* a build child really was running: pid **2124**, lock `.build-rows_id.pid`
  written **9:11pm**.
* and it had burned **1 second of CPU in 12 minutes**, because a cloud
  collect was 4 shards into 20 (**17,329,312** rows) and SQLite takes one
  writer. "Shortly" was hours.

CLAUDE.md already demanded the fix — *"a blocked resource NAMES ITS HOLDER"*,
bought by RCA-2026-09-10-C, which is why `rows_index.lock_holder()` exists.
This refusal path never called it. `build_running()` reports a name from a
LOCK FILE's age, so a build that is blocked and a build that is working look
identical, and the message was written from the wrong one.
"""
from __future__ import annotations

import inspect

from tradingagents import rows_index as ri


def test_a_queued_build_names_the_job_holding_the_store(monkeypatch):
    monkeypatch.setattr(ri, "lock_holder", lambda: "")
    monkeypatch.setattr(ri, "_machine_is_busy", lambda: True)
    monkeypatch.setattr(ri, "busy_job", lambda: "collect")
    got = ri.index_wait_reason("rows_id", "finding row #46SGBAHD")
    assert "QUEUED behind collect" in got, got
    assert "one writer" in got
    assert "shortly" not in got, \
        "a build that cannot start must not promise a short wait"


def test_the_lock_holder_is_preferred_when_it_knows(monkeypatch):
    monkeypatch.setattr(ri, "lock_holder", lambda: "delisted cleanup")
    monkeypatch.setattr(ri, "_machine_is_busy", lambda: True)
    monkeypatch.setattr(ri, "busy_job", lambda: "collect")
    assert "delisted cleanup" in ri.index_wait_reason("rows_id", "x")


def test_a_build_that_is_really_running_says_so(monkeypatch):
    monkeypatch.setattr(ri, "lock_holder", lambda: "")
    monkeypatch.setattr(ri, "_machine_is_busy", lambda: False)
    monkeypatch.setattr(ri, "build_running", lambda n=None: "rows_id")
    got = ri.index_wait_reason("rows_id", "finding row #X")
    assert "being built NOW" in got
    assert "minutes to hours" in got, \
        "the operator has waited 12 minutes on a promise of 'shortly'"


def test_nothing_running_and_nothing_holding_is_the_only_shortly(monkeypatch):
    monkeypatch.setattr(ri, "lock_holder", lambda: "")
    monkeypatch.setattr(ri, "_machine_is_busy", lambda: False)
    monkeypatch.setattr(ri, "build_running", lambda n=None: "")
    assert "just started" in ri.index_wait_reason("rows_id", "x")


def test_it_never_raises_into_a_request(monkeypatch):
    """This runs while answering a query; a broken status read must not turn
    a 503-with-a-reason into a 500."""
    def boom():
        raise RuntimeError("status unreadable")

    monkeypatch.setattr(ri, "lock_holder", boom)
    monkeypatch.setattr(ri, "build_running", lambda n=None: "")
    assert ri.index_wait_reason("rows_id", "x")


def test_both_refusal_paths_use_it():
    src = inspect.getsource(ri.export_plan) + inspect.getsource(ri.query)
    assert "it is being built in the background" not in src, \
        "the sentence that spun the operator's screen for 12 minutes"
    assert src.count("index_wait_reason(") >= 1


def test_the_find_by_id_refusal_goes_through_it():
    body = inspect.getsource(ri)
    i = body.index('_build_index("rows_id")')
    assert "index_wait_reason(" in body[i:i + 260], body[i:i + 260]
