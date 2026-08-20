"""The FastAPI layer the React app talks to.

Zero-bug bar item 1: every endpoint is tested here BEFORE any frontend uses
it. The API adds no business logic — each route is a thin, typed window onto
modules the suite already trusts — so these tests pin the window: shapes,
filters, failure modes, and that no secret ever crosses the wire.
"""
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from tradingagents import market_sweep as msw
    from tradingagents import parquet_store as pqs

    monkeypatch.setattr(msw, "HOME", tmp_path)
    monkeypatch.setattr(msw, "CANDLES", tmp_path / "candles")
    monkeypatch.setattr(msw, "ROWDIR", tmp_path / "rows")
    monkeypatch.setattr(msw, "STATES", tmp_path / "state")
    monkeypatch.setattr(pqs, "ROOT", tmp_path / "pq")
    monkeypatch.setattr(pqs, "CANDLES", tmp_path / "pq" / "candles")
    monkeypatch.setattr(pqs, "GRIDS", tmp_path / "pq" / "grids")
    from tradingagents.api import app

    return TestClient(app)


def _seed_rows(msw):
    msw.save_pair_rows("BTC", "15m", [
        {"coin": "BTC", "tf": "15m", "signal": "rsi14", "th": 0.0, "sl": 2.0,
         "tp": 1.0, "sizing": "flat", "trades": 922, "wins": 400,
         "losses": 522, "winrate": 43.4, "profit": 120.5, "dd": 30.0,
         "green": 9, "months": 12, "days": 360},
        {"coin": "BTC", "tf": "15m", "signal": "mom6", "th": 0.3, "sl": 1.0,
         "tp": 2.0, "sizing": "martingale", "trades": 500, "wins": 100,
         "losses": 400, "winrate": 20.0, "profit": -50.0, "dd": 80.0,
         "green": 3, "months": 12, "days": 360}])


def test_health_names_the_stores(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "storage" in body and "candles" in body["storage"]


def test_strategies_filter_and_paginate(client, monkeypatch):
    from tradingagents import market_sweep as msw

    _seed_rows(msw)
    r = client.get("/api/strategies", params={"coin": "BTC"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert all("id" in x for x in body["rows"]), "row codes travel with rows"
    r2 = client.get("/api/strategies",
                    params={"coin": "BTC", "profitable": "true"})
    assert r2.json()["total"] == 1, "the loser filters out"
    assert r2.json()["rows"][0]["signal"] == "rsi14"
    r3 = client.get("/api/strategies", params={"coin": "NOPE"})
    assert r3.json() == {"rows": [], "total": 0}


def test_storage_by_coin_shape(client, monkeypatch):
    from tradingagents import market_sweep as msw

    (msw.CANDLES).mkdir(parents=True, exist_ok=True)
    (msw.CANDLES / "BTC_USDT-15m.json").write_bytes(b"x" * 1000)
    r = client.get("/api/storage/by-coin")
    assert r.status_code == 200
    rows = r.json()["rows"]
    btc = next(x for x in rows if x["coin"] == "BTC")
    assert btc["total"] == 1000 and btc["tf"] == "15m"


def test_job_status_never_lies_about_a_dead_process(client, monkeypatch):
    from tradingagents import db_jobs

    monkeypatch.setattr(db_jobs, "status", lambda kind: {
        "running": False, "note": "process died before finishing",
        "done": 80, "total": 100, "pid": 0})
    r = client.get("/api/jobs/backtest")
    assert r.status_code == 200
    assert r.json()["running"] is False
    assert "died" in r.json()["note"]


def test_unknown_job_kind_is_a_404_not_a_crash(client):
    assert client.get("/api/jobs/nonsense").status_code == 404
    assert client.post("/api/jobs/nonsense/start", json={}).status_code == 404


def test_job_start_passes_spec_and_returns_pid(client, monkeypatch):
    from tradingagents import db_jobs

    seen = {}

    def fake_start(kind, spec):
        seen["kind"], seen["spec"] = kind, spec
        return 4242

    monkeypatch.setattr(db_jobs, "start", fake_start)
    r = client.post("/api/jobs/download/start",
                    json={"coins": ["BTC_USDT"], "tfs": ["15m"]})
    assert r.status_code == 200 and r.json()["pid"] == 4242
    assert seen == {"kind": "download",
                    "spec": {"coins": ["BTC_USDT"], "tfs": ["15m"]}}


def test_no_response_ever_contains_a_secret(client, monkeypatch):
    """MEXC keys live in ~/.tradingagents and env vars; the API must never
    echo them. Probed by planting a canary and sweeping every GET."""
    monkeypatch.setenv("MEXC_API_KEY", "CANARY-KEY-9f31")
    for path in ("/api/health", "/api/strategies", "/api/storage/by-coin",
                 "/api/jobs/download", "/api/ledger", "/api/deployments"):
        r = client.get(path)
        assert "CANARY-KEY-9f31" not in r.text, path


def test_ledger_and_deployments_read_local_files(client, monkeypatch,
                                                 tmp_path):
    import tradingagents.auto_trader as at
    from tradingagents import local_history as lh

    monkeypatch.setattr(at, "ledger_tail", lambda n=100000: [
        {"ts": 5, "action": "exit", "symbol": "PI_USDT", "pnl": 1.5,
         "why": "TP", "dry_run": False}])
    monkeypatch.setattr(lh, "DEPLOY_LOG", tmp_path / "dep.jsonl")
    lh.record_deployment({"strategy_key": "k", "symbol": "PI_USDT",
                          "action": "changed", "tp": 3.0, "sl": 1.0})
    r = client.get("/api/ledger")
    assert r.json()["rows"][0]["why"] == "TP"
    r2 = client.get("/api/deployments")
    assert r2.json()["rows"][0]["symbol"] == "PI_USDT"
