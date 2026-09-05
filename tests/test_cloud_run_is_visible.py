"""The panel shows the run GitHub is MEASURING, not the one we last dispatched.

Operator, Sep 05, 2026: *"i cannot see it running in ui i only see this"* — a
screenshot of the local job at 3924/4124 and nothing else, while run
33954675312 had been measuring on GitHub for 36 minutes and
`/api/cloud/status` was answering `{"run": null}`.

`remembered()` is a FILE this machine writes when IT dispatches. A run started
by the autopilot, by `sweep_orchestrator`, from another PC, or by a session
whose remember-file was cleared is a real run measuring our grid — and was
invisible. `cloud_sweep.working_run()` has always known how to find it; the
status route simply never asked.

A stale remembered run hides a live one the same way, which is the
2026-08-25 shape: three runs existed at once, the wrong one was adopted, and
"0/0 shards" was reported for twenty minutes while the cloud was most of the
way through the grid. So the live run wins and the remembered one is the
fallback that keeps a finished run's summary on screen.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tradingagents import api as api_mod, cloud_sweep as cs


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(cs, "available", lambda: (True, "me/repo"))
    monkeypatch.setattr(cs, "status", lambda rid, slug=None: {"running": 20})
    monkeypatch.setattr(cs, "live_progress", lambda rid: [{"shard": 0}])
    api_mod._WORKING_RUN.update({"at": 0.0, "run": None})     # no stale cache
    return TestClient(api_mod.app)


def test_a_run_we_never_dispatched_is_still_shown(client, monkeypatch):
    """The operator's case, exactly: nothing remembered, a run measuring."""
    monkeypatch.setattr(cs, "remembered", dict)
    monkeypatch.setattr(cs, "working_run",
                        lambda slug=None: {"id": 33954675312, "repo": "me/repo"})
    got = client.get("/api/cloud/status").json()
    assert got["run"] and got["run"]["id"] == 33954675312, \
        "a run measuring our grid must be on screen whoever started it"
    assert got["running"] == 20
    assert got["shards"], "and its machines with it"


def test_the_live_run_beats_a_stale_remembered_one(client, monkeypatch):
    """Three runs at once, the wrong one adopted (2026-08-25)."""
    monkeypatch.setattr(cs, "remembered",
                        lambda: {"id": 111, "repo": "me/repo"})
    monkeypatch.setattr(cs, "working_run",
                        lambda slug=None: {"id": 222, "repo": "me/repo"})
    got = client.get("/api/cloud/status").json()
    assert got["run"]["id"] == 222, "the run that is measuring wins"


def test_the_remembered_run_is_the_fallback(client, monkeypatch):
    """Nothing live — the last run's summary must stay on screen rather than
    the panel emptying the moment a sweep finishes."""
    monkeypatch.setattr(cs, "remembered",
                        lambda: {"id": 111, "repo": "me/repo"})
    monkeypatch.setattr(cs, "working_run", lambda slug=None: None)
    got = client.get("/api/cloud/status").json()
    assert got["run"]["id"] == 111


def test_the_lookup_is_cached(client, monkeypatch):
    """The panel polls this every 4 seconds and `working_run` costs a
    `gh run list` plus a status call per live run. Polling the REST API burned
    5,000 requests in an hour on 2026-08-25 and blinded every tool at once."""
    calls = {"n": 0}

    def _count(slug=None):
        calls["n"] += 1
        return {"id": 7, "repo": "me/repo"}

    monkeypatch.setattr(cs, "remembered", dict)
    monkeypatch.setattr(cs, "working_run", _count)
    for _ in range(10):
        client.get("/api/cloud/status")
    assert calls["n"] == 1, f"gh was asked {calls['n']} times in 10 polls"
    assert api_mod._WORKING_RUN_TTL >= 30, "and the window must be seconds, not one poll"


def test_a_broken_gh_never_breaks_the_panel(client, monkeypatch):
    """`working_run` shells out. A failure there must cost the RUN, never the
    endpoint — the panel also carries whether GitHub is usable at all."""
    def _boom(slug=None):
        raise RuntimeError("gh: not logged in")

    monkeypatch.setattr(cs, "remembered", dict)
    monkeypatch.setattr(cs, "working_run", _boom)
    got = client.get("/api/cloud/status").json()
    assert got["run"] is None
    assert got["available"] is True


def test_nothing_is_asked_when_github_is_unusable(client, monkeypatch):
    """No point shelling out to `gh` when `available()` already said no."""
    calls = {"n": 0}
    monkeypatch.setattr(cs, "available", lambda: (False, "gh is not installed"))
    monkeypatch.setattr(cs, "remembered", dict)
    monkeypatch.setattr(cs, "working_run",
                        lambda slug=None: calls.__setitem__("n", calls["n"] + 1))
    got = client.get("/api/cloud/status").json()
    assert got["available"] is False and got["run"] is None
    assert calls["n"] == 0
