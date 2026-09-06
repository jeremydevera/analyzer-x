"""The shard-progress fetch survives a lock race on its tracking ref.

Found by watching, Sep 06, 2026. The panel showed no machines at all for
minutes while run 34011544601 was perfectly healthy, and the only symptom was
one line in the API log:

    [cloud] could not fetch sweep-progress: git fetch: error: cannot lock ref
    'refs/remotes/origin/sweep-progress': is at 1c14b6d8... but expected
    418409e6...

`--force` was already on the fetch. It overrides a non-fast-forward; it does
NOT help when another git process is writing the same ref at that instant —
and something is, constantly: the API polls this branch every few seconds
while a sweep, the orchestrator, or a person running `git fetch origin` (which
fetches every ref, this one included) touches it too.

A stale remote-tracking ref is worth nothing on its own — the branch is
re-fetched whole every time — so the wedged ref is dropped and the fetch
retried once. `FETCH_FAIL_S` then hides the failure for a minute, which is
what turned a two-second race into a blind panel.
"""
from __future__ import annotations

import pytest

from tradingagents import cloud_sweep as cs

LOCK = ("git fetch: error: cannot lock ref "
        "'refs/remotes/origin/sweep-progress': is at 1c14b6d8 but expected "
        "418409e6")


def test_a_lock_race_is_retried_once(monkeypatch):
    calls: list = []

    def _git(*args, timeout: int = 120):
        calls.append(args)
        if args[0] == "fetch" and len(
                [c for c in calls if c[0] == "fetch"]) == 1:
            raise cs.CloudError(LOCK)
        return ""

    monkeypatch.setattr(cs, "_git", _git)
    cs._fetch_progress()                      # must not raise
    kinds = [c[0] for c in calls]
    assert kinds.count("fetch") == 2, f"expected one retry: {kinds}"
    assert "update-ref" in kinds, "the wedged tracking ref must be dropped"
    dropped = next(c for c in calls if c[0] == "update-ref")
    assert dropped[1] == "-d"
    assert dropped[2].endswith("sweep-progress")


def test_the_retry_order_is_delete_then_fetch(monkeypatch):
    """Fetching again without dropping the ref hits the same lock."""
    calls: list = []

    def _git(*args, timeout: int = 120):
        calls.append(args[0])
        if args[0] == "fetch" and calls.count("fetch") == 1:
            raise cs.CloudError(LOCK)
        return ""

    monkeypatch.setattr(cs, "_git", _git)
    cs._fetch_progress()
    assert calls.index("update-ref") < len(calls) - 1
    assert calls[-1] == "fetch"


def test_any_other_failure_is_raised_not_retried(monkeypatch):
    """A dead network is not a lock race, and retrying it hides the reason."""
    calls: list = []

    def _git(*args, timeout: int = 120):
        calls.append(args[0])
        raise cs.CloudError("git fetch: could not resolve host github.com")

    monkeypatch.setattr(cs, "_git", _git)
    with pytest.raises(cs.CloudError, match="could not resolve host"):
        cs._fetch_progress()
    assert calls.count("fetch") == 1, "no retry for a failure that is not a lock"
    assert "update-ref" not in calls, "and the ref is left alone"


def test_a_clean_fetch_touches_nothing_else(monkeypatch):
    calls: list = []
    monkeypatch.setattr(cs, "_git",
                        lambda *a, timeout=120: calls.append(a[0]) or "")
    cs._fetch_progress()
    assert calls == ["fetch"]


def test_a_ref_that_will_not_delete_still_lets_the_retry_run(monkeypatch):
    """`update-ref -d` failing must not swallow the retry — the second fetch
    may well succeed anyway once the other process has let go."""
    calls: list = []

    def _git(*args, timeout: int = 120):
        calls.append(args[0])
        if args[0] == "update-ref":
            raise cs.CloudError("git update-ref: unable to lock")
        if args[0] == "fetch" and calls.count("fetch") == 1:
            raise cs.CloudError(LOCK)
        return ""

    monkeypatch.setattr(cs, "_git", _git)
    cs._fetch_progress()
    assert calls.count("fetch") == 2


def test_live_progress_uses_it(monkeypatch):
    """A helper nothing calls fixes nothing."""
    import inspect

    src = inspect.getsource(cs.live_progress)
    assert "_fetch_progress()" in src
    assert '"fetch", "--quiet"' not in src, \
        "the raw fetch must not be re-spelled inside the poller"
