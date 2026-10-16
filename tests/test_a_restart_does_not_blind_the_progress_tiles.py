"""A restart of the back end must not blind the machine tiles.

`Oct 16, 2026 6:16am` the back end was restarted (`start.py api`, a deploy).
A restart ends the back end by its pid ALONE (`start.py kill(tree=False)`, so
the detached jobs live), and the progress fetch the old back end had running
kept going with no timeout over it: it held `.git/shallow.lock` from
`6:16:11am` to `6:19:29am`, 198 s. The new back end's two readers found the
lock, tried to delete it (Windows refuses: the live fetch has it open),
DROPPED both progress bookmarks (`origin/` and `colleague/sweep-progress`),
fetched again at once, failed again, and printed "could not fetch
sweep-progress" twice — which became an error issue. The old fetch then could
not write the bookmark it had fetched, because it had been deleted under it.

So, on ONE timeline, as the back end sees it:

* a lock a LIVE git process holds is waited out, never reported and never
  answered by dropping a bookmark;
* a lock nobody holds (a killed fetch's) is still cleared at once;
* the back end's own two readers (the cloud tile's and the LOGS panel's)
  take turns — git lets one fetch hold `.git/shallow.lock` at a time.
"""
from __future__ import annotations

import threading
import time

import pytest


def _sandbox(monkeypatch, tmp_path):
    """Point the helpers at a `.git` under tmp_path: they resolve it from the
    module's own location, and a test may only touch its own tmp_path."""
    from tradingagents import cloud_sweep as cs

    git = tmp_path / ".git"
    (git / "objects" / "pack").mkdir(parents=True)
    (tmp_path / "tradingagents").mkdir()
    monkeypatch.setattr(cs, "__file__", str(tmp_path / "tradingagents" / "cs.py"))
    monkeypatch.setattr(cs, "LOCK_POLL_S", 0.02, raising=False)
    return cs, git / "shallow.lock"


def _refusing_git(cs, lock, calls):
    """git as it behaves here: a fetch refuses while `.git/shallow.lock` exists."""
    def _git(*args, timeout: int = 120):
        calls.append((args[0], lock.exists()))
        if args[0] == "fetch" and lock.exists():
            raise cs.CloudError(
                f"git fetch: fatal: Unable to create '{lock.as_posix()}': "
                "File exists.\n\nAnother git process seems to be running in "
                "this repository, or the lock file may be sta")
        return ""
    return _git


def _held_open(cs, monkeypatch):
    """Windows will not delete a file another process has open — the old
    back end's fetch holds its lock open until it finishes."""
    monkeypatch.setattr(cs, "_clear_dead_lock", lambda force=False: None)


def test_a_live_fetchs_lock_is_waited_out_not_reported(monkeypatch, tmp_path):
    cs, lock = _sandbox(monkeypatch, tmp_path)
    calls: list = []
    monkeypatch.setattr(cs, "_git", _refusing_git(cs, lock, calls))
    _held_open(cs, monkeypatch)
    lock.write_text("x")                     # the old back end's fetch, live
    threading.Timer(0.3, lock.unlink).start()  # ... and finishing

    cs._fetch_progress("colleague")          # must not raise

    fetches = [held for kind, held in calls if kind == "fetch"]
    assert fetches[-1] is False, \
        f"the fetch that counts must run after the live one let go: {calls}"


def test_a_live_fetchs_lock_never_costs_the_bookmark(monkeypatch, tmp_path):
    """Dropping `refs/remotes/<remote>/sweep-progress` is the cure for a
    WEDGED REF, not for `shallow.lock` — and it made the old fetch's own
    bookmark update fail, so both tiles were left with nothing to read."""
    cs, lock = _sandbox(monkeypatch, tmp_path)
    calls: list = []
    monkeypatch.setattr(cs, "_git", _refusing_git(cs, lock, calls))
    _held_open(cs, monkeypatch)
    lock.write_text("x")
    threading.Timer(0.3, lock.unlink).start()

    cs._fetch_progress("origin")

    assert "update-ref" not in [kind for kind, _ in calls], calls


def test_a_lock_nobody_holds_is_still_cleared_at_once(monkeypatch, tmp_path):
    """RCA-2026-09-22-C stays fixed: a killed fetch's lock is not a reason
    to wait — it is removed and the fetch runs straight away."""
    cs, lock = _sandbox(monkeypatch, tmp_path)
    calls: list = []
    monkeypatch.setattr(cs, "_git", _refusing_git(cs, lock, calls))
    monkeypatch.setattr(cs, "LIVE_LOCK_WAIT_S", 30.0, raising=False)
    lock.write_text("x")                     # nobody has it open

    t0 = time.monotonic()
    cs._fetch_progress("origin")

    assert time.monotonic() - t0 < 5, "a dead lock must not be waited for"
    assert not lock.exists()
    assert [kind for kind, _ in calls].count("fetch") == 2, calls


def test_a_lock_that_never_lets_go_is_named_with_its_age(monkeypatch, tmp_path):
    """A blocked resource names its holder — and how long it has held it."""
    cs, lock = _sandbox(monkeypatch, tmp_path)
    calls: list = []
    monkeypatch.setattr(cs, "_git", _refusing_git(cs, lock, calls))
    monkeypatch.setattr(cs, "LIVE_LOCK_WAIT_S", 0.2, raising=False)
    _held_open(cs, monkeypatch)
    lock.write_text("x")

    with pytest.raises(cs.CloudError, match=r"another git process has held "
                                            r"\.git/shallow\.lock for \d+ s"):
        cs._fetch_progress("origin")
    assert "update-ref" not in [kind for kind, _ in calls], calls


def test_the_back_ends_two_readers_take_turns(monkeypatch, tmp_path):
    """The cloud tile's reader and the LOGS panel's reader each fetch on their
    own thread; two fetches at once is one of them refused."""
    cs, _ = _sandbox(monkeypatch, tmp_path)
    mu = threading.Lock()
    active, peak = [0], [0]

    def _git(*args, timeout: int = 120):
        if args[0] == "fetch":
            with mu:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.2)
            with mu:
                active[0] -= 1
        return ""

    monkeypatch.setattr(cs, "_git", _git)
    readers = [threading.Thread(target=cs._fetch_progress, args=(r,))
               for r in ("origin", "colleague")]
    for t in readers:
        t.start()
    for t in readers:
        t.join(10)

    assert peak[0] == 1, f"{peak[0]} progress fetches ran at once"
