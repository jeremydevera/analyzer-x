"""The trading routes are windows onto auto_trader — and the dangerous ones
(runner start, settings save) must be exactly as safe as the module they wrap:
no real process spawned in tests, every settings change recorded to the local
deploy history, and no response ever carrying a credential."""
import json

import pytest
from fastapi.testclient import TestClient

import tradingagents.auto_trader as at
from tradingagents.api import app


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
    from tradingagents.dataflows import mexc_credentials as cred, mexc_futures as fx
    monkeypatch.setattr(cred, "load_into_env", lambda override=True: True)
    monkeypatch.setattr(fx, "preflight", lambda sym: {
        "credentials": True, "read_assets": True, "read_positions": True,
        "order_permission": True, "can_rest_stop": False, "symbol": sym})
    got = client.post("/api/trade/credentials/test",
                      json={"symbol": "APEX_USDT"}).json()
    assert got["can_rest_stop"] is False and got["symbol"] == "APEX_USDT"


# --- trade history --------------------------------------------------------
# "the history is still not here" — the Auto Trade screen had every CLOSED
# trade, on LIVE/DEMO tabs, with a per-month summary and 5-row pages.

def test_history_separates_the_books_and_runs_the_total_over_the_whole_book(
        client, monkeypatch):
    led = [
        {"action": "exit", "dry_run": False, "ts": 1_787_000_000,
         "symbol": "APEX_USDT", "side": "SHORT", "strategy": "sweep30_1h_w",
         "why": "TP", "pnl_est": 2.0},
        {"action": "exit", "dry_run": False, "ts": 1_787_100_000,
         "symbol": "PI_USDT", "side": "LONG", "strategy": "trend50_30m_pi",
         "why": "SL", "pnl_est": -0.5},
        {"action": "exit", "dry_run": True, "ts": 1_787_200_000,
         "symbol": "XAUT_USDT", "side": "LONG", "strategy": "mom6_1h_gx",
         "why": "TP", "pnl_est": 9.0},
        {"action": "enter", "dry_run": False, "ts": 1_787_300_000},
    ]
    monkeypatch.setattr(at, "ledger_tail", lambda n: led)
    live = client.get("/api/trade/history?dry=false").json()
    assert live["total"] == 2, "entries and the paper book are excluded"
    assert [r["coin"] for r in live["rows"]] == ["PI", "APEX"], "newest first"
    assert live["rows"][0]["running"] == 1.5, "running total is book-wide"
    assert live["rows"][1]["running"] == 2.0
    paper = client.get("/api/trade/history?dry=true").json()
    assert [r["coin"] for r in paper["rows"]] == ["XAUT"]


def test_history_pages_are_five_deep_and_clamped(client, monkeypatch):
    led = [{"action": "exit", "dry_run": False, "ts": 1_787_000_000 + i,
            "symbol": "A_USDT", "pnl_est": 1.0} for i in range(12)]
    monkeypatch.setattr(at, "ledger_tail", lambda n: led)
    p1 = client.get("/api/trade/history?per_page=5&page=1").json()
    assert len(p1["rows"]) == 5 and p1["pages"] == 3
    p9 = client.get("/api/trade/history?per_page=5&page=9").json()
    assert p9["page"] == 3, "a page past the end clamps, never empties"
    assert len(p9["rows"]) == 2


def test_history_carries_a_per_month_summary_that_sums_to_its_own_total(
        client, monkeypatch):
    led = [{"action": "exit", "dry_run": False, "ts": 1_785_000_000,
            "symbol": "A_USDT", "pnl_est": 3.0},
           {"action": "exit", "dry_run": False, "ts": 1_787_000_000,
            "symbol": "A_USDT", "pnl_est": -1.0},
           {"action": "exit", "dry_run": False, "ts": 1_787_100_000,
            "symbol": "A_USDT", "pnl_est": 2.0}]
    monkeypatch.setattr(at, "ledger_tail", lambda n: led)
    got = client.get("/api/trade/history").json()
    assert len(got["months"]) == 2
    assert got["months"][0]["label"] > "", "months are printed as 'Aug 2026'"
    assert sum(m["profit"] for m in got["months"]) == got["totals"]["profit"]
    assert got["totals"]["trades"] == 3
    latest = got["months"][0]
    assert latest["wins"] + latest["losses"] == latest["trades"]
    assert latest["win_rate"] == round(100 * latest["wins"] / latest["trades"], 1)


def test_the_contract_list_is_available_for_the_pickers(client, monkeypatch):
    from tradingagents.dataflows import mexc_futures as fx
    monkeypatch.setattr(fx, "list_contracts", lambda quote="USDT": [
        {"symbol": "BTC_USDT"}, {"symbol": "APEX_USDT"}, {"symbol": "BTC_USDT"}])
    got = client.get("/api/contracts").json()
    assert got["rows"] == ["APEX_USDT", "BTC_USDT"], "sorted and de-duped"


def test_a_contract_list_failure_says_why_instead_of_being_empty(client,
                                                                 monkeypatch):
    from tradingagents.dataflows import mexc_futures as fx
    def boom(quote="USDT"):
        raise RuntimeError("host blocked")
    monkeypatch.setattr(fx, "list_contracts", boom)
    got = client.get("/api/contracts").json()
    assert got["rows"] == [] and "host blocked" in got["why"]


# --- the ladder columns and the equity curve ------------------------------
# The Streamlit grid printed streak, the whole ladder in dollars with the
# current rung boxed, and next $ — so the next stake is never a number the
# operator has to work out. The React grid shipped without them.

def test_the_ladder_is_reported_in_dollars_with_the_current_rung(client,
                                                                 monkeypatch):
    at.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    at.SETTINGS_PATH.write_text(json.dumps({
        "strategy_books": {"sweep30_1h_w": ["real"]},
        "strategy_coins": {"sweep30_1h_w": ["APEX_USDT"]},
        "strategy_margins": {"sweep30_1h_w": 5.0},
        "sizing": "martingale"}))
    monkeypatch.setattr(at, "sizing_for", lambda s, key=None: "martingale")
    monkeypatch.setattr(at, "load_state", lambda: {
        "APEX_USDT": {"step": 3}})          # three losses deep
    monkeypatch.setattr(at, "pnl_today_by_strategy", lambda dry=None: {})
    r = next(x for x in client.get("/api/trade/strategies").json()["rows"]
             if x["key"] == "sweep30_1h_w")
    assert r["streak"] == 3
    assert r["ladder"] == [round(5.0 * m, 2) for m in at.LADDER]
    assert r["ladder_rung"] == 3
    assert r["next_stake"] == round(5.0 * at.LADDER[3], 2)
    assert r["notional"] == round(5.0 * at.LEVERAGE, 2)


def test_flat_sizing_has_one_rung_and_a_constant_stake(client, monkeypatch):
    at.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    at.SETTINGS_PATH.write_text(json.dumps({
        "strategy_books": {"fvg_1h_w": ["real"]},
        "strategy_margins": {"fvg_1h_w": 8.0}}))
    monkeypatch.setattr(at, "sizing_for", lambda s, key=None: "flat")
    monkeypatch.setattr(at, "load_state", lambda: {})
    monkeypatch.setattr(at, "pnl_today_by_strategy", lambda dry=None: {})
    got = client.get("/api/trade/strategies").json()
    r = next(x for x in got["rows"] if x["key"] == "fvg_1h_w")
    assert got["flat"] is True
    assert r["ladder"] == [8.0] and r["next_stake"] == 8.0


def test_the_streak_is_read_from_the_book_the_row_trades(client, monkeypatch):
    """A demo-only row was printing the LIVE ladder rung."""
    at.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    at.SETTINGS_PATH.write_text(json.dumps({
        "strategy_books": {"mom6_1h_pv": ["paper"]},
        "strategy_coins": {"mom6_1h_pv": ["PROVE_USDT"]},
        "strategy_margins": {"mom6_1h_pv": 5.0}}))
    monkeypatch.setattr(at, "sizing_for", lambda s, key=None: "martingale")
    monkeypatch.setattr(at, "load_state", lambda: {
        "PROVE_USDT": {"step": 6},            # the LIVE book, not this row's
        "PROVE_USDT#paper": {"step": 1}})
    monkeypatch.setattr(at, "pnl_today_by_strategy", lambda dry=None: {})
    r = next(x for x in client.get("/api/trade/strategies").json()["rows"]
             if x["key"] == "mom6_1h_pv")
    assert r["streak"] == 1, "a paper row must read the paper ladder"


def test_the_equity_curve_is_built_from_the_same_exit_rows(client, monkeypatch):
    monkeypatch.setattr(at, "ledger_since", lambda ts: [
        {"action": "exit", "dry_run": False, "ts": 1.0, "pnl_est": 2.0,
         "symbol": "A_USDT"},
        {"action": "enter", "dry_run": False, "ts": 2.0},
        {"action": "exit", "dry_run": True, "ts": 3.0, "pnl_est": 99.0},
        {"action": "exit", "dry_run": False, "ts": 4.0, "pnl_est": -0.5,
         "symbol": "B_USDT"}])
    got = client.get("/api/trade/equity").json()
    assert [p["equity"] for p in got["points"]] == [2.0, 1.5]
    assert got["last"] == 1.5 and got["trades"] == 2


# --- the live lock --------------------------------------------------------
# One coin runs ONE timeframe with real money. MEXC nets same-symbol
# positions, so a second live entry resizes the first and either stop closes
# part of a trade it does not own. Streamlit disabled the checkbox; the React
# port had no guard at all.

def test_many_live_strategies_on_one_coin_are_allowed_now(client, monkeypatch):
    """Superseded 2026-09-04, on the operator's instruction: they armed 35 rows
    over 9 coins, 20 of them on GPNSTOCK, and asked for the RUNTIME rule
    instead — "SINCE I RECEIVED A SIGNAL AND I HAVE OPEN POSITION THEN DO NOT
    ACCEPT SIGNAL FOR [the others] ... WHICH EVER COMES FIRST SHOULD BE THE ONE
    TO FOLLOWED". One OPEN POSITION per coin is tighter than one ARMED row per
    coin: see tests/test_one_position_per_coin.py."""
    at.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    at.SETTINGS_PATH.write_text(json.dumps({
        "strategy_books": {"trend50_30m_pi": ["real"], "mom15_4h_w": ["real"]},
        "strategy_coins": {"trend50_30m_pi": ["PI_USDT"],
                           "mom15_4h_w": ["PI_USDT"]}}))
    monkeypatch.setattr(at, "pnl_today_by_strategy", lambda dry=None: {})
    got = client.get("/api/trade/strategies").json()
    assert got["locks"] == {}
    for key in ("trend50_30m_pi", "mom15_4h_w"):
        row = next(r for r in got["rows"] if r["key"] == key)
        assert not row.get("live_locked"), row


def test_paper_is_never_locked(client, monkeypatch):
    at.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    at.SETTINGS_PATH.write_text(json.dumps({
        "strategy_books": {"trend50_30m_pi": ["paper"], "mom15_4h_w": ["paper"]},
        "strategy_coins": {"trend50_30m_pi": ["PI_USDT"],
                           "mom15_4h_w": ["PI_USDT"]}}))
    monkeypatch.setattr(at, "pnl_today_by_strategy", lambda dry=None: {})
    assert client.get("/api/trade/strategies").json()["locks"] == {}


def test_saving_two_live_strategies_on_one_coin_is_ACCEPTED_now(client):
    """It was a 409 until 2026-09-04 (the PROVE incident: two live strategies
    netting into one position). The protection moved to the runtime, where it
    is stronger — a coin with a position open accepts no other strategy's
    signal until it closes."""
    payload = {"strategy_books": {"trend50_30m_pi": ["real"],
                                  "mom15_4h_w": ["real"]},
               "strategy_coins": {"trend50_30m_pi": ["PI_USDT"],
                                  "mom15_4h_w": ["PI_USDT"]}}
    got = client.post("/api/trade/settings", json=payload)
    assert got.status_code == 200, got.text


def test_the_same_coin_on_the_SAME_timeframe_is_allowed_now_too(client):
    """The history, because it is the reason the runtime rule exists: MEXC nets
    by CONTRACT, so two OPEN positions on one coin resize each other and either
    stop closes part of a trade it does not own (PROVE, 2026-08-22,
    fade15_1h_pv2 and mom6_1h_pv live together at 1h). Arming both is fine
    because only one of them can HOLD the coin at a time."""
    got = client.post("/api/trade/settings", json={
        "strategy_books": {"mom6_1h_gx": ["real"], "mom6_1h_pv": ["real"]},
        "strategy_coins": {"mom6_1h_gx": ["XAUT_USDT"],
                           "mom6_1h_pv": ["XAUT_USDT"]}})
    assert got.status_code == 200, got.text


def test_the_same_coin_on_many_DEMO_strategies_is_allowed(client):
    """"for demo it can have multiple strategies so i can see if its working"."""
    got = client.post("/api/trade/settings", json={
        "strategy_books": {"mom6_1h_gx": ["paper"], "mom6_1h_pv": ["paper"],
                           "fade15_1h_pv2": ["paper"]},
        "strategy_coins": {"mom6_1h_gx": ["XAUT_USDT"],
                           "mom6_1h_pv": ["XAUT_USDT"],
                           "fade15_1h_pv2": ["XAUT_USDT"]}})
    assert got.status_code == 200, got.text


def test_a_position_carries_the_same_id_the_strategy_grid_shows(client,
                                                                monkeypatch):
    """'which strategy is running here?' must be answerable from the position
    row alone — and the id must MATCH the grid's, or two screens name one row
    differently."""
    at.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    at.SETTINGS_PATH.write_text(json.dumps({
        "strategy_books": {"mom6_1h_gx": ["real"]},
        "strategy_coins": {"mom6_1h_gx": ["XAUT_USDT"]},
        "strategy_margins": {"mom6_1h_gx": 5.0}}))
    monkeypatch.setattr(at, "load_state", lambda: {
        "XAUT_USDT": {"position": {"dry": False, "side": 1, "entry": 4500.0,
                                   "tp": 4600.0, "sl": 4400.0, "margin": 5.0,
                                   "vol": 1.0, "strategy": "mom6_1h_gx",
                                   "opened_at": 1_787_000_000,
                                   "bracket": True}}})
    monkeypatch.setattr(at, "taker_fee", lambda s, **kw: 0.0004)
    monkeypatch.setattr(at, "pnl_today_by_strategy", lambda dry=None: {})
    from tradingagents.dataflows import mexc_futures as fx
    monkeypatch.setattr(fx, "open_positions", lambda symbol=None: [])
    monkeypatch.setattr(fx, "contract_spec", lambda s: {"contractSize": 1.0})
    monkeypatch.setattr(fx, "last_price", lambda s: 4550.0)

    pos = client.get("/api/trade/positions").json()["real"][0]
    grid = next(r for r in client.get("/api/trade/strategies").json()["rows"]
                if r["key"] == "mom6_1h_gx")
    assert pos["id"] and pos["id"] == grid["id"], "one row, one id"
    assert len(pos["id"]) == 8


def test_a_position_with_no_strategy_gets_a_blank_id_not_a_wrong_one(client,
                                                                    monkeypatch):
    """An exchange position the bot never opened has no combination to hash."""
    at.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    at.SETTINGS_PATH.write_text("{}")
    monkeypatch.setattr(at, "load_state", lambda: {})
    monkeypatch.setattr(at, "taker_fee", lambda s, **kw: 0.0004)
    from tradingagents.dataflows import mexc_futures as fx
    monkeypatch.setattr(fx, "open_positions", lambda symbol=None: [
        {"symbol": "GHOST_USDT", "positionType": 1, "holdVol": 1.0,
         "holdAvgPrice": 5.0, "unRealizedPnl": 0.1}])
    monkeypatch.setattr(fx, "contract_spec", lambda s: {"contractSize": 1.0})
    monkeypatch.setattr(fx, "last_price", lambda s: 5.0)
    r = client.get("/api/trade/positions").json()["real"][0]
    assert r["strategy"] == "(not the bot's)" and r["id"] == ""


# --- the ladder rung is the COIN's, not the strategy's ---------------------
# 2026-08-22: #3RAUB3WW showed "11 loss" beside its own 3W/1L record. The 11
# was PROVE's real-book ladder rung, advanced by a DIFFERENT strategy on the
# same coin that had lost four in a row.

def test_the_rung_names_its_book_and_who_shares_it(client, monkeypatch):
    at.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    at.SETTINGS_PATH.write_text(json.dumps({
        "strategy_books": {"mom6_1h_pv": ["real", "paper"],
                           "fade15_1h_pv2": ["real", "paper"],
                           "mom6_1h_gx": ["paper"]},
        "strategy_coins": {"mom6_1h_pv": ["PROVE_USDT"],
                           "fade15_1h_pv2": ["PROVE_USDT"],
                           "mom6_1h_gx": ["XAUT_USDT"]}}))
    monkeypatch.setattr(at, "load_state", lambda: {
        "PROVE_USDT": {"step": 11}, "PROVE_USDT#paper": {"step": 0},
        "XAUT_USDT#paper": {"step": 2}, "XAUT_USDT": {"step": 9}})
    monkeypatch.setattr(at, "strategy_stats",
                        lambda dry=None: ({"mom6_1h_pv": {"wins": 3, "losses": 1,
                                                          "trades": 4, "pnl": 20.35}}
                                          if not dry else
                                          {"mom6_1h_gx": {"wins": 7, "losses": 0,
                                                           "trades": 7, "pnl": 9.0}}))
    monkeypatch.setattr(at, "pnl_today_by_strategy", lambda dry=None: {})
    rows = {r["key"]: r for r in client.get("/api/trade/strategies").json()["rows"]}

    mom = rows["mom6_1h_pv"]
    assert mom["streak"] == 11
    assert mom["streak_book"] == "real", "an armed row reads the REAL ladder"
    assert mom["streak_shared_with"] == ["fade15_1h_pv2"], \
        "the rung is not attributable to this row alone"
    assert (mom["wins"], mom["losses"]) == (3, 1)

    # a paper-only row reads the PAPER ladder and the PAPER record — it was
    # showing the live book's ladder and the live book's wins
    gx = rows["mom6_1h_gx"]
    assert gx["streak_book"] == "paper"
    assert gx["streak"] == 2, "the paper rung, not the live book's 9"
    assert (gx["wins"], gx["losses"]) == (7, 0)
    assert gx["streak_shared_with"] == [], "nothing else trades XAUT on paper"


def test_a_lone_strategy_on_a_coin_owns_its_rung(client, monkeypatch):
    at.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    at.SETTINGS_PATH.write_text(json.dumps({
        "strategy_books": {"sweep30_1h_w": ["real"]},
        "strategy_coins": {"sweep30_1h_w": ["APEX_USDT"]}}))
    monkeypatch.setattr(at, "load_state", lambda: {"APEX_USDT": {"step": 3}})
    monkeypatch.setattr(at, "strategy_stats", lambda dry=None: {})
    monkeypatch.setattr(at, "pnl_today_by_strategy", lambda dry=None: {})
    r = next(x for x in client.get("/api/trade/strategies").json()["rows"]
             if x["key"] == "sweep30_1h_w")
    assert r["streak"] == 3 and r["streak_shared_with"] == []


def test_sizing_is_per_strategy_not_one_switch_for_the_account(client, monkeypatch):
    """NOM/mom6 measured +$114.57 flat and +$113.26 laddered over the same year
    — the same money — but its worst losing run was -$41.00 flat and -$188.60
    laddered against a $210.68 wallet. Flat was right for that row and wrong to
    force on the others, and a single global switch could not say so."""
    import json

    at.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    at.SETTINGS_PATH.write_text(json.dumps({
        "strategies": ["mom6_1h_pv", "fvg_1h_w"],
        "strategy_books": {"mom6_1h_pv": ["real"], "fvg_1h_w": ["real"]},
        "strategy_coins": {"mom6_1h_pv": ["PROVE_USDT"], "fvg_1h_w": ["ALICE_USDT"]},
        "strategy_margins": {"mom6_1h_pv": 5.0, "fvg_1h_w": 5.0},
        "sizing": "martingale",
        "strategy_sizing": {"fvg_1h_w": "flat"},
    }))
    saved = json.loads(at.SETTINGS_PATH.read_text())

    assert at.sizing_for(saved) == "martingale", "the account default is unchanged"
    assert at.sizing_for(saved, "mom6_1h_pv") == "martingale"
    assert at.sizing_for(saved, "fvg_1h_w") == "flat"

    # the STAKE follows it: at rung 3 the ladder doubles, flat does not
    assert at.staked_margin("fvg_1h_w", saved, 3) == 5.0
    assert at.staked_margin("mom6_1h_pv", saved, 3) > 5.0

    # and the grid draws each row's own ladder, or it shows the operator a
    # ladder for a row that will never take one
    body = client.get("/api/trade/strategies").json()
    by = {r["key"]: r for r in body["rows"]}
    assert by["fvg_1h_w"]["sizing"] == "flat"
    assert by["fvg_1h_w"]["ladder"] == [5.0], by["fvg_1h_w"]["ladder"]
    assert by["mom6_1h_pv"]["sizing"] == "martingale"
    assert len(by["mom6_1h_pv"]["ladder"]) > 1


def test_a_row_id_is_hashed_with_that_rows_own_sizing(client):
    """Sizing is part of the combination. Hashed with the ACCOUNT default, the
    flat NOM row printed #L4TCWCZY in the app while the board it came from
    called it #F2S7J87Z — one row with two names, which is exactly what the
    stable id exists to prevent."""
    import json

    from tradingagents import backtest_report as br
    from tradingagents.api import row_id_for

    at.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    saved = {"strategies": ["mom6_4h_nom"],
             "strategy_books": {"mom6_4h_nom": ["real"]},
             "strategy_coins": {"mom6_4h_nom": ["NOM_USDT"]},
             "sizing": "martingale",
             "strategy_sizing": {"mom6_4h_nom": "flat"}}
    at.SETTINGS_PATH.write_text(json.dumps(saved))

    want = br.row_code("NOM", "4h", "mom6", 0.8, 4.0, 5.0, "flat")
    assert row_id_for("mom6_4h_nom", "NOM_USDT", saved) == want == "F2S7J87Z"

    # and the account default alone would give a different, wrong id
    other = br.row_code("NOM", "4h", "mom6", 0.8, 4.0, 5.0, "martingale")
    assert other != want


def test_a_strategy_can_carry_a_human_label(client):
    """The grid showed only the key and the id. "Best winrate for Aug" is
    provenance a spec cannot express — where the row came from and why it was
    picked — and the operator asked for it on the row itself."""
    import json

    at.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    at.SETTINGS_PATH.write_text(json.dumps({
        "strategies": ["mom6_4h_nom", "fvg_1h_w"],
        "strategy_books": {"mom6_4h_nom": ["real"], "fvg_1h_w": ["real"]},
        "strategy_coins": {"mom6_4h_nom": ["NOM_USDT"], "fvg_1h_w": ["ALICE_USDT"]},
    }))
    by = {r["key"]: r for r in client.get("/api/trade/strategies").json()["rows"]}
    assert by["mom6_4h_nom"]["label"] == "Best winrate for Aug"
    # a row without one gets "", so the cell does not render "None"
    assert by["fvg_1h_w"]["label"] == ""


def test_no_label_repeats_a_barrier():
    """app._strategy_label records the incident: barriers typed into a label
    drift from the spec the runner trades — the APEX tile advertised TP 4.0%
    against a real 3.0% for weeks. Labels carry provenance, not numbers."""
    import re

    for key, label in at.STRATEGY_LABELS.items():
        assert not re.search(r"\d", label), f"{key} label has a number: {label!r}"


def test_a_label_is_editable_config_not_a_constant_in_the_source():
    """It began as a dict in auto_trader only, so the operator could not change
    a label without editing code — they asked outright whether it was hard
    coded. strategy_labels overrides it, like strategy_margins does."""
    shipped = at.label_for("mom6_4h_nom")
    assert shipped == "Best winrate for Aug"

    cfg = {"strategy_labels": {"mom6_4h_nom": "renamed by hand",
                               "fvg_1h_w": ""}}
    assert at.label_for("mom6_4h_nom", cfg) == "renamed by hand"
    # an EMPTY string in the config means "no label", not "fall back"
    assert at.label_for("fvg_1h_w", cfg) == ""
    # a key the config does not mention still gets its shipped default
    assert at.label_for("mom6_1h_pv4", cfg) == "Best winrate for Aug"
    assert at.label_for("nothing_here", cfg) == ""


def test_an_open_position_carries_the_same_label_as_its_strategy_row():
    """The operator saw it on one table and not the other. Two tables naming
    one row differently is the reason the id is derived rather than typed."""
    from tradingagents import positions_view as pv

    settings = {"strategy_labels": {"mom6_4h_nom": "Best winrate for Aug"}}
    # state is keyed by BOOK ("SYMBOL#book"), each holding one "position"
    rows = pv.build_rows(
        state={"NOM_USDT#paper": {"position": {
            "side": -1, "vol": 6191, "margin": 5.0, "entry": 0.001614,
            "dry": True, "strategy": "mom6_4h_nom",
            "opened_at": 1787000000}}},
        exchange_positions=[], stats={}, dry=True,
        last_price=lambda s: 0.0016, contract_size=lambda s: 1.0,
        taker_fee=lambda s, fx=None: 0.0002, leverage=20,
        settings=settings)
    assert rows, "no row built"
    assert rows[0]["label"] == "Best winrate for Aug"
    assert rows[0]["strategy"] == "mom6_4h_nom"
