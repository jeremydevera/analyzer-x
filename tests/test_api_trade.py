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


def test_strategies_shows_only_what_is_deployed_by_default(client):
    """27 keys exist; 2 are deployed. Listing all 27 made four armed
    strategies read as twenty-seven running ones (2026-08-21)."""
    payload = {"strategy_books": {"mom6_1h_g": ["real"], "fvg_4h": ["paper"]},
               "strategy_coins": {"mom6_1h_g": ["XAUT_USDT"],
                                  "fvg_4h": ["BTC_USDT"]}}
    at.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    at.SETTINGS_PATH.write_text(json.dumps(payload))
    got = client.get("/api/trade/strategies").json()
    assert {r["key"] for r in got["rows"]} == {"mom6_1h_g", "fvg_4h"}
    assert got["real_count"] == 1 and got["paper_count"] == 1
    assert got["deployed_count"] == 2
    assert got["catalog_count"] == len(at.STRATEGY_ORDER) > 2
    assert got["showing_catalog"] is False
    mine = next(r for r in got["rows"] if r["key"] == "mom6_1h_g")
    assert mine["books"] == ["real"] and mine["coins"] == ["XAUT_USDT"]


def test_the_full_catalog_is_available_but_only_when_asked(client):
    at.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    at.SETTINGS_PATH.write_text(json.dumps(
        {"strategy_books": {"mom6_1h_g": ["real"]}}))
    got = client.get("/api/trade/strategies?catalog=true").json()
    assert {r["key"] for r in got["rows"]} == set(at.STRATEGY_ORDER)
    assert got["showing_catalog"] is True
    assert got["real_count"] == 1, "counts still describe what is DEPLOYED"


def test_open_positions_are_reported_per_book_with_clean_coin_names(client):
    """The grid's "open now" column showed "XAUT#paper" — the book suffix is
    not part of the coin name, and a paper position is not a real one."""
    at.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    at.SETTINGS_PATH.write_text(json.dumps({"strategy_books": {
        "trend50_30m_pi": ["paper"], "sweep30_1h_w": ["real"]}}))
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


# --- the safety controls --------------------------------------------------
# Restored 2026-08-21 after the React port shipped without them: PANIC,
# close-one and halt. A kill switch that needs a second click is fine; one
# that can fire on a mis-click, or cannot fire at all, is not.

def test_panic_refuses_without_an_explicit_confirmation(client, monkeypatch):
    called = []
    monkeypatch.setattr(at, "panic_stop",
                        lambda **kw: called.append(kw) or {"halted": True})
    assert client.post("/api/trade/panic", json={}).status_code == 400
    assert client.post("/api/trade/panic",
                       json={"confirm": "yes"}).status_code == 400
    assert called == [], "panic must not fire without confirm=true"
    got = client.post("/api/trade/panic", json={"confirm": True})
    assert got.status_code == 200 and called == [{"close_positions": True}]


def test_panic_can_halt_without_closing_when_asked(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(at, "panic_stop", lambda **kw: seen.update(kw) or {})
    client.post("/api/trade/panic", json={"confirm": True,
                                          "close_positions": False})
    assert seen == {"close_positions": False}


def test_close_one_needs_a_symbol_and_passes_it_through(client, monkeypatch):
    seen = []
    monkeypatch.setattr(at, "close_one",
                        lambda s, **kw: seen.append(s) or {"closed": True})
    assert client.post("/api/trade/positions/close",
                       json={}).status_code == 400
    got = client.post("/api/trade/positions/close",
                      json={"symbol": "APEX_USDT"}).json()
    assert seen == ["APEX_USDT"] and got["closed"] is True


def test_halt_writes_and_clears_the_kill_file(client, monkeypatch, tmp_path):
    monkeypatch.setattr(at, "KILL_PATH", tmp_path / "auto_trade.KILL")
    assert client.post("/api/trade/halt", json={"halt": True}).json()["halted"] is True
    assert (tmp_path / "auto_trade.KILL").exists()
    assert client.post("/api/trade/halt", json={"halt": False}).json()["halted"] is False
    assert not (tmp_path / "auto_trade.KILL").exists()


def test_positions_route_carries_every_column_and_names_the_unprotected(
        client, monkeypatch):
    monkeypatch.setattr(at, "load_state", lambda: {
        "APEX_USDT": {"position": {"dry": False, "side": 1, "entry": 100.0,
                                   "tp": 110.0, "sl": 95.0, "margin": 5.0,
                                   "vol": 1.0, "strategy": "sweep30_1h_w",
                                   "opened_at": 1_787_000_000,
                                   "bracket": False}}})
    monkeypatch.setattr(at, "taker_fee", lambda s, **kw: 0.0004)
    from tradingagents.dataflows import mexc_futures as fx
    monkeypatch.setattr(fx, "open_positions", lambda symbol=None: [])
    monkeypatch.setattr(fx, "last_price", lambda s: 105.0)
    monkeypatch.setattr(fx, "contract_spec", lambda s: {"contractSize": 1.0})
    got = client.get("/api/trade/positions").json()
    r = got["real"][0]
    assert r["bracket"] == "NO STOP — RETRYING"
    assert got["unprotected"] == ["APEX"], "an unprotected position is named"
    assert r["progress_pct"] == 50.0 and r["progress_to"] == "TP"
    assert r["tp_value"]["pct"] == 10.0 and r["sl_value"]["usd"] < 0
    assert r["held"] != "—" and r["opened"] != "—"


def test_progress_needs_a_real_price_reader_not_a_dataframe_index(client,
                                                                  monkeypatch):
    """klines() returns a DataFrame; indexing it like a list yielded no price
    and blanked the 'to TP' column on every row (2026-08-21)."""
    monkeypatch.setattr(at, "load_state", lambda: {
        "PI_USDT": {"position": {"dry": False, "side": 1, "entry": 100.0,
                                 "tp": 110.0, "sl": 95.0, "margin": 5.0,
                                 "vol": 1.0, "opened_at": 1_787_000_000,
                                 "bracket": True}}})
    monkeypatch.setattr(at, "taker_fee", lambda s, **kw: 0.0004)
    from tradingagents.dataflows import mexc_futures as fx
    monkeypatch.setattr(fx, "open_positions", lambda symbol=None: [])
    monkeypatch.setattr(fx, "contract_spec", lambda s: {"contractSize": 1.0})
    monkeypatch.setattr(fx, "last_price", lambda s: 105.0)
    r = client.get("/api/trade/positions").json()["real"][0]
    assert r["price"] == 105.0
    assert r["progress_pct"] == 50.0 and r["progress_to"] == "TP"


# --- the loss caps --------------------------------------------------------
# Two separate breakers: one per strategy (pauses that strategy for the day,
# so the working ones keep trading) and one for the account (stops the runner
# and drops the kill file). Both were missing from the React screen.

def test_per_strategy_cap_and_trip_state_reach_the_screen(client, monkeypatch):
    at.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    at.SETTINGS_PATH.write_text(json.dumps({
        "strategy_books": {"sweep30_1h_w": ["real"], "fvg_1h_w": ["real"]},
        "strategy_loss_limits": {"sweep30_1h_w": 20.0},
        "loss_limit": 50.0}))
    monkeypatch.setattr(at, "pnl_today_by_strategy",
                        lambda dry=None: {"sweep30_1h_w": -25.0,
                                          "fvg_1h_w": -1.0})
    monkeypatch.setattr(at, "loss_limit_hit", lambda s=None: False)
    got = client.get("/api/trade/strategies").json()
    hot = next(r for r in got["rows"] if r["key"] == "sweep30_1h_w")
    cool = next(r for r in got["rows"] if r["key"] == "fvg_1h_w")
    assert hot["loss_cap"] == 20.0 and hot["tripped"] is True
    assert hot["today"] == -25.0
    assert cool["loss_cap"] is None and cool["tripped"] is False
    assert got["tripped"] == ["sweep30_1h_w"]
    assert got["account_loss_cap"] == 50.0 and got["account_cap_hit"] is False


def test_the_account_breaker_reports_when_it_has_fired(client, monkeypatch):
    at.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    at.SETTINGS_PATH.write_text(json.dumps({"loss_limit": 10.0}))
    monkeypatch.setattr(at, "pnl_today_by_strategy", lambda dry=None: {})
    monkeypatch.setattr(at, "loss_limit_hit", lambda s=None: True)
    got = client.get("/api/trade/strategies").json()
    assert got["account_cap_hit"] is True


def test_saving_keeps_both_kinds_of_cap(client):
    payload = {"strategy_books": {"fvg_1h_w": ["real"]},
               "strategy_loss_limits": {"fvg_1h_w": 8.5},
               "loss_limit": 40.0}
    client.post("/api/trade/settings", json=payload)
    back = client.get("/api/trade/settings").json()["settings"]
    assert back["strategy_loss_limits"] == {"fvg_1h_w": 8.5}
    assert back["loss_limit"] == 40.0


# --- credentials ----------------------------------------------------------
# The panel was missing entirely, so keys could only be set by editing a file
# or exporting a shell var. What it may NEVER do is echo a secret back.

def test_credentials_status_never_returns_key_material(client, monkeypatch):
    monkeypatch.setenv("MEXC_API_KEY", "CANARY-KEY-mx-1234abcd")
    monkeypatch.setenv("MEXC_API_SECRET", "CANARY-SECRET-mx-9876wxyz")
    from tradingagents.dataflows import mexc_credentials as cred
    monkeypatch.setattr(cred, "load_into_env", lambda override=True: True)
    body = client.get("/api/trade/credentials").text
    assert "CANARY-KEY-mx-1234abcd" not in body
    assert "CANARY-SECRET-mx-9876wxyz" not in body
    got = json.loads(body)
    assert got["has_credentials"] is True
    assert "1234abcd"[-4:] in got["key_fingerprint"], "the stub keeps 4 chars"
    assert "•" in got["key_fingerprint"]


def test_saving_credentials_requires_both_halves(client, monkeypatch):
    from tradingagents.dataflows import mexc_credentials as cred
    saved = []
    monkeypatch.setattr(cred, "save", lambda k, s: saved.append((k, s)))
    monkeypatch.setattr(cred, "load_into_env", lambda override=True: True)
    monkeypatch.setattr(cred, "status", lambda: {"has_credentials": True})
    monkeypatch.setattr(cred, "env_conflict", lambda: {})
    assert client.post("/api/trade/credentials",
                       json={"api_key": "abc"}).status_code == 400
    assert saved == []
    got = client.post("/api/trade/credentials",
                      json={"api_key": "abc", "api_secret": "def"})
    assert got.status_code == 200 and saved == [("abc", "def")]
    assert "abc" not in got.text, "the saved key is not echoed back"


def test_the_probe_reports_whether_a_stop_can_actually_rest(client,
                                                           monkeypatch):
    """Reading a balance proves nothing about protection. Rule 14."""
    from tradingagents.dataflows import mexc_credentials as cred
    from tradingagents.dataflows import mexc_futures as fx
    monkeypatch.setattr(cred, "load_into_env", lambda override=True: True)
    monkeypatch.setattr(fx, "preflight", lambda sym: {
        "credentials": True, "read_assets": True, "read_positions": True,
        "order_permission": True, "can_rest_stop": False, "symbol": sym})
    got = client.post("/api/trade/credentials/test",
                      json={"symbol": "APEX_USDT"}).json()
    assert got["can_rest_stop"] is False and got["symbol"] == "APEX_USDT"
