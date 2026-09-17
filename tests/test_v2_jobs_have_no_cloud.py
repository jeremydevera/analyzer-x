"""A v2 job cannot be handed to GitHub, and its worker list is its own
(Sep 18, 2026 review; never fired).

`POST /api/jobs/backtest_v2/handoff` was accepted by the generic route and
stopped the v2 job under "handed over to GitHub Actions — the cloud takes the
rest", while `_finish_handoff` is hard-wired to `backtest` and the fleet has
no 1-minute store. And `/api/jobs/backtest_v2` replaced the job's own
`workers` with this process's v1 workers folder.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from tradingagents import api as api_mod, db_jobs as dj, market_sweep as msw, stores


def test_a_v2_handoff_is_refused_with_the_reason(monkeypatch):
    client = TestClient(api_mod.app)
    monkeypatch.setattr(dj, "status", lambda kind: {"running": True, "pid": 1})
    r = client.post("/api/jobs/backtest_v2/handoff")
    assert r.status_code == 400, r.text
    assert "1-minute store" in r.json()["detail"]
    r = client.post("/api/jobs/btupdate_v2/handoff")
    assert r.status_code == 400


def test_the_v2_handoff_state_says_no_cloud_is_available(monkeypatch):
    client = TestClient(api_mod.app)
    monkeypatch.setattr(dj, "status", lambda kind: {"running": True, "pid": 1})
    r = client.get("/api/jobs/backtest_v2/handoff")
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["available"] is False
    assert "1-minute store" in got["why"]


def test_a_v2_jobs_workers_come_from_the_v2_folder(monkeypatch):
    client = TestClient(api_mod.app)
    seen = {}
    monkeypatch.setattr(dj, "status", lambda kind: {"running": True, "pid": 1,
                                                    "workers": [], "done": 1, "total": 5})
    monkeypatch.setattr(msw, "worker_read",
                        lambda stale_seconds=0, workers_dir=None:
                        seen.update(dir=workers_dir) or [])
    client.get("/api/jobs/backtest_v2")
    assert seen["dir"] == stores.V2.home / "workers", seen
    client.get("/api/jobs/backtest")
    assert seen["dir"] is None, "a v1 job reads this process's own folder"
