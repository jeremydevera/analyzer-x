"""What is still v1-only about Backtest v2 — and what stopped being.

Sep 18, 2026, when this file was written: a v2 job could not be handed to
GitHub at all, because the fleet had no 1-minute candles. Both halves were
pinned shut here.

Sep 21, 2026, the operator: *"i want backtest to run on github, what ever
existing on v1 i want on v2 the only difference is v2 will be using 1min
candles that's the only difference i want"*. So the fleet downloads its own
minutes now (`RES=1m` -> `market_sweep.bars_from_1m` on the runner) and
Backtest v2 MEASURES on GitHub — see tests/test_v2_measures_on_github.py.

ONE half is still v1-only: the mid-run HAND-OFF. `api._finish_handoff` is
hard-wired to the `backtest` kind and reads v1's store to work out which coins
the PC never reached, so a v2 hand-off would stop the v2 job and dispatch
nothing. That is a real limitation, and this file now pins:

  * that it is still refused, so nobody presses a button that loses a run;
  * that it is refused for the TRUE reason. The old sentence said GitHub has
    no 1-minute store, which is no longer true — a refusal whose reason has
    gone stale sends the reader to fix the wrong thing (label-must-match-data).

The third test never changed: a v2 job's worker list comes from the v2 folder.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from tradingagents import api as api_mod, db_jobs as dj, market_sweep as msw, stores


def test_a_v2_handoff_is_still_refused_because_only_the_handoff_is_v1_only(
        monkeypatch):
    client = TestClient(api_mod.app)
    monkeypatch.setattr(dj, "status", lambda kind: {"running": True, "pid": 1})
    r = client.post("/api/jobs/backtest_v2/handoff")
    assert r.status_code == 400, r.text
    why = r.json()["detail"]
    assert "hand-off" in why.lower()
    assert "BACKTEST on Backtest v2" in why, \
        "a refusal must name the button that DOES work"
    r = client.post("/api/jobs/btupdate_v2/handoff")
    assert r.status_code == 400


def test_the_refusal_no_longer_claims_the_fleet_has_no_1m_store(monkeypatch):
    """THE POINT OF THIS TEST. That claim was true on Sep 18 and false on
    Sep 21, and a stale reason is worse than none — it is a correct-looking
    sentence that sends somebody to build a thing that already exists."""
    client = TestClient(api_mod.app)
    monkeypatch.setattr(dj, "status", lambda kind: {"running": True, "pid": 1})
    for got in (client.post("/api/jobs/backtest_v2/handoff").json()["detail"],
                client.get("/api/jobs/backtest_v2/handoff").json()["why"]):
        assert "no" not in got.lower().split("1-minute")[0][-12:], got
        assert "runs only on this PC" not in got, got


def test_the_v2_handoff_state_says_why_and_stays_unavailable(monkeypatch):
    client = TestClient(api_mod.app)
    monkeypatch.setattr(dj, "status", lambda kind: {"running": True, "pid": 1})
    r = client.get("/api/jobs/backtest_v2/handoff")
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["available"] is False
    assert "hand-off" in got["why"].lower()


def test_a_v2_jobs_workers_come_from_the_v2_folder(monkeypatch):
    """UNCHANGED from Sep 18 — this half was never about the cloud."""
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


def test_the_MEASURING_half_is_no_longer_refused():
    """The counterpart to the refusal above: v2 measuring on the fleet is a
    dispatch, and nothing in the dispatch path may special-case it away."""
    import inspect

    from tradingagents import cloud_sweep as cs

    assert "res" in inspect.signature(cs.dispatch).parameters
    src = inspect.getsource(cs.dispatch)
    assert "_V2_NO_CLOUD" not in src
    # and a v2 run has somewhere to land
    assert "collect_v2" in dj.FILES
    assert stores.for_kind("collect_v2").env_for()["TRADINGAGENTS_FINE_TF"] == "1m"
