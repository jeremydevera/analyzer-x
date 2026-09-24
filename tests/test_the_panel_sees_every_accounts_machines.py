"""The progress tiles must show all 40 machines, and never go blind for days.

`Sep 22, 2026 11:14pm`, the operator: *"why cant i see any loading on
screen"*, with 30 machines measuring Backtest v2. Three faults, one screen:

* `live_progress` read `origin/sweep-progress` whatever repo the run was in,
  so the partner's 15 reporting machines were unreadable.
* `_read_cloud_status` asked only the LEAD run for its machines, and the lead
  run was the one still queued.
* `.git/shallow.lock` — left behind by a progress fetch this reader had KILLED
  on `Sep 14, 2026 4:51pm` — made every fetch since answer "Another git
  process seems to be running". Eight days of blind tiles on every run.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest


def _fake_remotes(monkeypatch, text):
    from tradingagents import cloud_sweep as cs

    class _R:
        stdout = text

    monkeypatch.setattr(cs.subprocess, "run", lambda *a, **k: _R())


def test_a_run_is_read_from_its_own_accounts_repo(monkeypatch):
    from tradingagents import cloud_sweep as cs

    _fake_remotes(monkeypatch, (
        "colleague\thttps://github.com/jeremydvera/analyzer-x (fetch)\n"
        "colleague\thttps://github.com/jeremydvera/analyzer-x (push)\n"
        "origin\thttps://github.com/jeremydevera/analyzer-x (fetch)\n"
        "origin\thttps://github.com/jeremydevera/analyzer-x (push)\n"))

    assert cs.remote_for("jeremydvera/analyzer-x") == "colleague"
    assert cs.remote_for("jeremydevera/analyzer-x") == "origin"
    assert cs.remote_for("someone/else") == "origin", "unknown falls back"
    assert cs.remote_for(None) == "origin"


def test_the_progress_is_read_from_that_remotes_branch(monkeypatch):
    """The fork's machines write to the FORK's branch."""
    from tradingagents import cloud_sweep as cs

    _fake_remotes(monkeypatch, (
        "colleague\thttps://github.com/jeremydvera/analyzer-x (fetch)\n"
        "origin\thttps://github.com/jeremydevera/analyzer-x (fetch)\n"))
    seen: list = []

    def fake_git(*args, timeout=120):
        seen.append(args)
        if args[0] == "ls-tree":
            return "progress/run-77/shard-0.json\n"
        if args[0] == "show":
            return '{"shard": 0, "stage": "testing", "rows": 12}'
        return ""

    monkeypatch.setattr(cs, "_git", fake_git)
    monkeypatch.setattr(cs, "_fetch_progress", lambda remote="origin": None)
    monkeypatch.setattr(cs, "_PROGRESS_CACHE", {"at": 0.0, "run": None, "rows": []})

    rows = cs.live_progress(77, "jeremydvera/analyzer-x")

    assert rows and rows[0]["shard"] == 0
    assert rows[0]["repo"] == "jeremydvera/analyzer-x", \
        "a machine must carry the account it ran on — both runs number 0..19"
    assert any("colleague/sweep-progress" in str(a) for a in seen), seen


def test_a_killed_fetchs_lock_is_cleared_and_a_live_one_is_not(monkeypatch, tmp_path):
    """The eight-day blindness: `.git/shallow.lock` from a killed fetch."""
    from tradingagents import cloud_sweep as cs

    git = tmp_path / ".git"
    git.mkdir()
    lock = git / "shallow.lock"
    lock.write_text("x")
    # point the helper at this sandbox: it resolves `.git` from the module's
    # own location, and a test may only touch its own tmp_path
    (tmp_path / "tradingagents").mkdir()
    monkeypatch.setattr(cs, "__file__", str(tmp_path / "tradingagents" / "cs.py"))

    # a LIVE fetch's lock (seconds old) is left alone
    cs._clear_dead_lock()
    assert lock.exists(), "a lock a running fetch holds must never be removed"

    # an old one is cleared
    import os
    old = time.time() - cs.DEAD_LOCK_S - 60
    os.utime(lock, (old, old))
    cs._clear_dead_lock()
    assert not lock.exists(), "a lock from a killed fetch blocks every read"


def test_the_tile_gets_every_accounts_machines(monkeypatch):
    """One press, two runs, 40 machines — the tile draws 40."""
    from tradingagents import api, cloud_sweep as cs

    lead = {"id": 1, "repo": "a/x", "res": "1m",
            "runs": [{"id": 1, "repo": "a/x"}, {"id": 2, "repo": "b/x"}]}
    monkeypatch.setattr(api, "_working_run_cached", lambda: lead)
    monkeypatch.setattr(cs, "available", lambda: (True, "a/x"))
    monkeypatch.setattr(cs, "status", lambda rid, slug=None: {
        "status": "in_progress", "running": 10, "queued": 10, "conclusion": ""})
    monkeypatch.setattr(cs, "live_progress", lambda rid, slug=None: [
        {"shard": n, "repo": slug or "", "rows": 100} for n in range(20)])

    out = api._read_cloud_status()

    assert len(out["shards"]) == 40, "20 of 40 machines is the wrong label"
    assert {s["repo"] for s in out["shards"]} == {"a/x", "b/x"}
    assert out["running"] == 20, "the count must add the other account's too"


def test_the_v2_screen_reads_the_cloud_at_all():
    """`if (store !== "v1") return;` skipped the cloud read on Backtest v2,
    so the v2 screen could not draw a run it had just started itself."""
    src = (Path(__file__).resolve().parent.parent / "webapp" / "src" /
           "components" / "backtest" / "JobsPanel.tsx").read_text(encoding="utf-8")
    poll = src[src.index("const poll = useCallback"):][:900]
    read = poll.index("api.cloudStatus()")
    guard = poll.index('if (store !== "v1") return;')
    assert read < guard, \
        "the cloud status must be read before the v1-only hand-over guard"


def test_each_screen_shows_only_its_own_stores_run():
    """A v2 run reporting under the v1 heading is label-must-match-data."""
    src = (Path(__file__).resolve().parent.parent / "webapp" / "src" /
           "components" / "backtest" / "JobsPanel.tsx").read_text(encoding="utf-8")
    assert '(store === "v2") === ((cloud.run.res ?? "") === "1m")' in src
    assert 'store === "v1" && cloud?.run?.id' not in src, \
        "the old gate hid every v2 run and showed it on the v1 tab instead"


def test_a_v2_run_is_merged_by_the_v2_collect_job(monkeypatch):
    """MERGE INTO THIS PC on a v2 run must not collect in the API process:
    that runs in v1's environment, so `land_rows` would refuse every row."""
    from tradingagents import api, cloud_sweep as cs, db_jobs as dj

    monkeypatch.setattr(cs, "run_res", lambda rid: "1m")
    monkeypatch.setattr(cs, "remembered", lambda: {
        "id": 1, "repo": "a/x", "runs": [{"id": 2, "repo": "b/x"}]})
    monkeypatch.setattr(cs, "collect_into_store",
                        lambda *a, **k: pytest.fail("a v2 run may not land here"))
    started: list = []
    monkeypatch.setattr(dj, "start",
                        lambda kind, spec: started.append((kind, spec)) or 4242)

    got = api.cloud_merge({"run_id": 2})

    assert started == [("collect_v2", {"run": 2, "repo": "b/x"})], started
    assert got["kind"] == "collect_v2" and got["pid"] == 4242


def test_the_bar_counts_both_boards_not_one():
    """Every machine reports its RUN's whole board. Taking the max across two
    runs counted 35 machines' finished coins against one account's 499."""
    src = (Path(__file__).resolve().parent.parent / "webapp" / "src" /
           "components" / "backtest" / "JobsPanel.tsx").read_text(encoding="utf-8")
    fn = src[src.index("function runProgress"):]
    fn = fn[:fn.index("\n}") + 2]
    assert "new Map" in fn and "s.run ?? s.repo" in fn, fn
    assert "shards.reduce((a, s) => Math.max(a, s.board ?? 0), 0)" not in fn, \
        "one account's board may not stand for a two-account press"
