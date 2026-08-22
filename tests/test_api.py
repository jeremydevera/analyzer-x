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
    # /api/strategies answers from the SQLite index now, not by re-parsing the
    # store (that cost 28.6s per request on the real one). A tiny store fills
    # inline on the first read; syncing here keeps the test deterministic.
    from tradingagents import rows_index as ri

    ri.sync()
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
    body3 = r3.json()
    assert (body3["rows"], body3["total"]) == ([], 0)
    assert body3["index"]["behind"] == 0, (
        "the response must say whether the index is still catching up, or a "
        "partial list gets read as the whole store")


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


def test_report_file_refuses_to_walk_out_of_its_folder(client):
    """A report name is a filename, never a path. '..' must 404, not read."""
    for evil in ("../../etc/passwd", "..%2f..%2fetc%2fpasswd", "notes.txt"):
        assert client.get(f"/api/reports/file/{evil}").status_code in (404, 400)


def test_report_file_serves_a_real_report(client, tmp_path, monkeypatch):
    from pathlib import Path

    import tradingagents.api as api_mod

    d = Path(api_mod.__file__).resolve().parent.parent / "static" / "bt"
    d.mkdir(parents=True, exist_ok=True)
    probe = d / "api-selftest.html"
    probe.write_text("<h1>grid</h1>", encoding="utf-8")
    try:
        got = client.get("/api/reports/file/api-selftest.html")
        assert got.status_code == 200 and "grid" in got.text
    finally:
        probe.unlink(missing_ok=True)


def test_the_plan_counts_combinations_from_the_real_registry(client):
    """'Say the cost before spending it.' A hardcoded count would drift the
    moment a signal is added — the registry is the source."""
    from tradingagents import backtest_report as br
    got = client.get("/api/backtest/plan?coins=BTC_USDT,ETH_USDT&tfs=1h,4h").json()
    assert got["signals"] == len(br.SIGNALS)
    per_tf = ((len(br.SIGNALS) - len(br.THRESH_SIGNALS)) * 110 * 2
              + len(br.THRESH_SIGNALS) * 3 * 110 * 2)
    assert got["combinations"] == per_tf * 2 * 2
    assert got["eta_minutes"] > 0


def test_deployed_rows_are_filtered_to_the_selection(client, monkeypatch):
    import tradingagents.auto_trader as at
    monkeypatch.setattr(at, "load_settings", lambda: {
        "strategy_books": {"mom6_1h_gx": ["real"], "mom15_4h_w": ["paper"]},
        "strategy_coins": {"mom6_1h_gx": ["XAUT_USDT"],
                           "mom15_4h_w": ["PI_USDT"]},
        "sizing": "martingale"})
    got = client.get("/api/backtest/deployed?coins=XAUT_USDT&tfs=1h").json()
    assert [r["coin"] for r in got["rows"]] == ["XAUT"]
    r = got["rows"][0]
    assert r["tf"] == "1h" and r["signal"] == "mom6" and r["key"] == "mom6_1h_gx"
    # a strategy with no book is not deployed and must not be injected
    monkeypatch.setattr(at, "load_settings", lambda: {
        "strategy_books": {"mom6_1h_gx": []},
        "strategy_coins": {"mom6_1h_gx": ["XAUT_USDT"]}})
    assert client.get("/api/backtest/deployed").json()["rows"] == []


def test_cloud_status_says_why_when_github_is_unusable(client, monkeypatch):
    from tradingagents import cloud_sweep as cs
    monkeypatch.setattr(cs, "available", lambda: (False, "gh CLI not signed in"))
    monkeypatch.setattr(cs, "remembered", lambda: {})
    got = client.get("/api/cloud/status").json()
    assert got["available"] is False and "gh CLI" in got["why"]
    assert got["shards"] == []


def test_cloud_dispatch_is_refused_when_unavailable(client, monkeypatch):
    from tradingagents import cloud_sweep as cs
    fired = []
    monkeypatch.setattr(cs, "available", lambda: (False, "no gh"))
    monkeypatch.setattr(cs, "dispatch", lambda **kw: fired.append(kw) or {})
    assert client.post("/api/cloud/dispatch", json={}).status_code == 400
    assert fired == [], "never dispatch when the CLI cannot answer"


def test_cloud_status_reports_each_machine_not_just_a_count(client,
                                                            monkeypatch):
    from tradingagents import cloud_sweep as cs
    monkeypatch.setattr(cs, "available", lambda: (True, "ok"))
    monkeypatch.setattr(cs, "remembered", lambda: {"id": 42})
    monkeypatch.setattr(cs, "status", lambda rid, slug=None: {
        "conclusion": None, "shards": 20, "done": 3})
    monkeypatch.setattr(cs, "live_progress", lambda rid, slug=None: [
        {"shard": 1, "stage": "backtesting", "pct": 40, "note": "BTC 15m"},
        {"shard": 2, "stage": "downloading", "pct": 10, "note": "ETH 30m"}])
    got = client.get("/api/cloud/status").json()
    assert len(got["shards"]) == 2
    assert got["shards"][0]["stage"] == "backtesting"


def test_storage_rows_carry_when_each_pair_was_last_updated(client,
                                                            monkeypatch):
    """'last updated' is the store's own LAST BAR, not a file mtime: a rewrite
    that added no bars is not an update."""
    from tradingagents import market_sweep as msw
    monkeypatch.setattr(msw, "storage_by_coin", lambda: [
        {"coin": "APEX", "tf": "1h", "candles": 10, "rows": 0, "states": 0,
         "total": 10},
        {"coin": "APEX", "tf": "4h", "candles": 5, "rows": 0, "states": 0,
         "total": 5}])
    monkeypatch.setattr(msw, "candle_index", lambda scan=True: {
        "APEX_USDT-1h": {"symbol": "APEX_USDT", "timeframe": "1h",
                          "bars": 9999, "last_ms": 1_787_000_000_000}})
    rows = client.get("/api/storage/by-coin").json()["rows"]
    one = next(r for r in rows if r["tf"] == "1h")
    four = next(r for r in rows if r["tf"] == "4h")
    assert one["last_ms"] == 1_787_000_000_000 and one["bars"] == 9999
    assert four["last_ms"] is None, "a pair the index has not seen says so"


def test_storage_never_scans_on_a_request(client, monkeypatch):
    """The scan opens every candle file; a request must read the index only."""
    from tradingagents import market_sweep as msw
    seen = {}
    monkeypatch.setattr(msw, "storage_by_coin", lambda: [])
    monkeypatch.setattr(msw, "candle_index",
                        lambda scan=True: seen.update(scan=scan) or {})
    client.get("/api/storage/by-coin")
    assert seen["scan"] is False
