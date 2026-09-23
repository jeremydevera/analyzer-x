"""A sort-index build that DIED must not keep the screen waiting on it.

`Sep 24, 2026 12:11am`, the operator: *"is it still indexing"*. It was not.
The v2 store held `.build-rows_id.pid` with pid 17152, written when the build
started at `Sep 23, 2026 11:24pm`; that process was gone, and nothing had
noticed. `build_running()` believed the lock for `BUILD_LOCK_TTL_S` — SIX
HOURS — so every search needing that order answered "it is being built NOW"
while nothing was building, and no new build could start either, because
`_build_index` refuses while `build_running()` names one.

The lock has held the builder's pid since it was written. Nothing read it.
"""
from __future__ import annotations

import time

import pytest


@pytest.fixture
def store(tmp_path, monkeypatch):
    from tradingagents import rows_index as ri

    db = tmp_path / "rows.db"
    db.write_bytes(b"")
    monkeypatch.setattr(ri, "DB_PATH", db, raising=False)
    monkeypatch.setattr(ri, "_db", lambda: db)
    return ri, db


def test_a_build_whose_process_is_gone_is_not_running(store, monkeypatch):
    ri, db = store
    (db.parent / ".build-rows_id.pid").write_text("17152")
    monkeypatch.setattr(ri.portable, "pid_alive", lambda pid: False)

    assert ri.build_running() == "", \
        "a dead build kept every search waiting for up to six hours"
    assert not (db.parent / ".build-rows_id.pid").exists(), \
        "and the next search must be able to start a new one"


def test_a_live_build_is_still_reported(store, monkeypatch):
    ri, db = store
    (db.parent / ".build-rows_id.pid").write_text("4242")
    monkeypatch.setattr(ri.portable, "pid_alive", lambda pid: True)

    assert ri.build_running() == "rows_id"
    assert (db.parent / ".build-rows_id.pid").exists(), (
        "a running build's lock may never be removed: two builds "
        "queue on one SQLite writer and neither finishes")


def test_an_unreadable_pid_falls_back_to_the_clock(store, monkeypatch):
    """Old locks, empty files and half-written ones keep the TTL behaviour."""
    import os

    ri, db = store
    lock = db.parent / ".build-rows_id.pid"
    lock.write_text("")
    monkeypatch.setattr(ri.portable, "pid_alive",
                        lambda pid: pytest.fail("there is no pid to check"))

    assert ri.build_running() == "rows_id", "no pid is not proof of death"

    old = time.time() - ri.BUILD_LOCK_TTL_S - 60
    os.utime(lock, (old, old))
    assert ri.build_running() == "", "older than any real build is still dead"
