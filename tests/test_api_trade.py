"""The trading routes are windows onto auto_trader — and the dangerous ones
(runner start, settings save) must be exactly as safe as the module they wrap:
no real process spawned in tests, every settings change recorded to the local
deploy history, and no response ever carrying a credential."""
import json

import pytest
from fastapi.testclient import TestClient

from tradingagents.api import app
import tradingagents.auto_trader as at


@pytest.fixture()
def client(monkeypatch, tmp_path):
    # never touch the real exchange, process table, or home directory
    monkeypatch.setattr(at, "SETTINGS_PATH", tmp_path / "auto_trade.json")
    monkeypatch.setattr(at, "runner_pid", lambda: None)
    monkeypatch.setattr(at, "coin_stats", lambda dry=None: {
        "APEX_USDT": {"pnl": 12.5, "trades": 10, "wins": 6, "losses": 4}})
    monkeypatch.setattr(at, "strategy_stats", lambda dry=None: {})
    monkeypatch.setattr(at, "pnl_today", lambda dry=None: {
        "total": 1.0, "wins": 1, "losses": 0, "trades": 1})
    monkeypatch.setattr(at, "load_state", lambda: {
        # the real book-key shape: SYMBOL#paper for the simulated book
        "PI_USDT#paper": {"position": {"dry": True, "side": 1, "entry": 0.09,
                                       "margin": 5.0, "strategy": "trend50_30m_pi"}},
        "APEX_USDT": {"position": {"dry": False, "side": -1, "entry": 0.21,
                                   "margin": 5.0, "strategy": "sweep30_1h_w"}}})
    monkeypatch.setattr(at, "daily_pnl", lambda dry=None: {"2026-08-21": 1.0})
    from tradingagents.dataflows import mexc_futures as fx
    # the real shape: a DICT keyed by currency. Iterating it as a list is the
    # bug this fixture exists to catch (2026-08-21: equity read as null).
    monkeypatch.setattr(fx, "assets", lambda: {
        "USDT": {"currency": "USDT", "equity": 81.25}})
    monkeypatch.setattr(fx, "has_credentials", lambda: True)
    monkeypatch.setattr(fx, "open_positions", lambda symbol=None: [])
    from tradingagents.dataflows import mexc_credentials as cred
    monkeypatch.setattr(cred, "load_into_env", lambda: None)
    return TestClient(app)


def test_summary_reads_the_wallet_and_says_stopped(client):
    got = client.get("/api/trade/summary").json()
    assert got["pid"] is None and got["mode"] == "STOPPED"
    assert got["equity"] == 81.25
    assert got["all_time_closed"] == 12.5
    assert got["all_time"] == 12.5      # nothing open


def test_equity_survives_the_real_assets_shape(client, monkeypatch):
    """assets() is keyed by currency; a list-style read returns None and the
    ribbon then prints a dash where the wallet should be."""
    assert client.get("/api/trade/summary").json()["equity"] == 81.25
    from tradingagents.dataflows import mexc_futures as fx
    monkeypatch.setattr(fx, "has_credentials", lambda: False)
    assert client.get("/api/trade/summary").json()["equity"] is None


def test_paper_position_symbol_is_the_coin_not_the_book_key(client):
    """state_key() joins with '#', not ':' — splitting on the wrong one put
    "PI_USDT#paper" in the coin column."""
    rows = client.get("/api/trade/summary").json()["paper_positions"]
    assert [r["symbol"] for r in rows] == ["PI_USDT"]
    assert rows[0]["strategy"] == "trend50_30m_pi"


def test_runner_start_calls_the_module_not_a_shell(client, monkeypatch):
    calls = []
    monkeypatch.setattr(at, "start_runner", lambda: calls.append(1) or 4242)
    assert client.post("/api/trade/runner/start").json() == {"pid": 4242}
    assert calls == [1]


def test_settings_save_records_the_deploy_history(client, monkeypatch,
                                                  tmp_path):
    from tradingagents import local_history as lh
    monkeypatch.setattr(lh, "DEPLOY_LOG", tmp_path / "deployments.jsonl")
    payload = {"strategy_books": {"mom6_1h_g": ["real"]},
               "strategy_coins": {"mom6_1h_g": ["XAUT_USDT"]},
               "strategy_margins": {"mom6_1h_g": 5.0}}
    got = client.post("/api/trade/settings", json=payload).json()
    assert got["ok"] is True and got["changes_recorded"] == 1
    assert json.loads(at.SETTINGS_PATH.read_text()) == payload
    line = json.loads((tmp_path / "deployments.jsonl").read_text())
    assert line["action"] == "deployed" and line["symbol"] == "XAUT_USDT"
    assert client.get("/api/trade/settings").json()["settings"] == payload


def test_strategies_lists_every_key_with_deploy_state(client, monkeypatch):
    payload = {"strategy_books": {"mom6_1h_g": ["real"]},
               "strategy_coins": {"mom6_1h_g": ["XAUT_USDT"]}}
    at.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    at.SETTINGS_PATH.write_text(json.dumps(payload))
    rows = client.get("/api/trade/strategies").json()["rows"]
    assert {r["key"] for r in rows} == set(at.STRATEGY_ORDER)
    mine = next(r for r in rows if r["key"] == "mom6_1h_g")
    assert mine["books"] == ["real"] and mine["coins"] == ["XAUT_USDT"]


def test_open_positions_are_reported_per_book_with_clean_coin_names(client):
    """The grid's "open now" column showed "XAUT#paper" — the book suffix is
    not part of the coin name, and a paper position is not a real one."""
    rows = client.get("/api/trade/strategies").json()["rows"]
    paper = next(r for r in rows if r["key"] == "trend50_30m_pi")
    assert paper["open_on_paper"] == ["PI_USDT"] and paper["open_on"] == []
    real = next(r for r in rows if r["key"] == "sweep30_1h_w")
    assert real["open_on"] == ["APEX_USDT"] and real["open_on_paper"] == []


def test_no_trade_response_carries_a_credential(client, monkeypatch):
    canary = "CANARY-TRADE-KEY-77xx"
    monkeypatch.setenv("MEXC_API_KEY", canary)
    monkeypatch.setenv("MEXC_API_SECRET", canary)
    for path in ("/api/trade/summary", "/api/trade/strategies",
                 "/api/trade/settings", "/api/trade/pnl/daily",
                 "/api/trade/pnl/by-coin", "/api/trade/log"):
        body = client.get(path).text
        assert canary not in body, f"{path} leaked a credential"
