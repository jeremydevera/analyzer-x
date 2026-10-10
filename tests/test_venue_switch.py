"""The cutover from MEXC to Gate (spec D7, D8; Oct 10, 2026).

One command moves the exchange's data aside and switches the app. It deletes
nothing, refuses while anything still holds the store, closes each room's
open PRACTICE trades at their own exchange's last price, switches every
practice row off with the reason in the deploy history, and writes
venue.json last — so a cutover that stopped half-way leaves the app on MEXC
with its data where it was found, never on Gate with MEXC's numbers.
"""
import json
from pathlib import Path

import pytest

from tradingagents import auto_trader as at
from tradingagents import venue, venue_switch as vs

EXCHANGE_DIRS = ["backtest", "v2", "parquet", "parquet-v2", "kline_cache",
                 "shared", "replay", "forecast_v2", "rolling30"]
EXCHANGE_FILES = ["book_readings.jsonl", "room_forecasts.jsonl", "daily_update.json",
                  "candle_autopilot.json", "cloud_autopilot.json",
                  "pending_candles.json", "pending_candles_v2.json",
                  "pending_backtest.json", "db_backtest_v2.json",
                  "db_backtest_v2.spec.json", "db_btupdate_v2.plan.json",
                  "db_download.lost.json", "rows_index_asked.json",
                  "rows_rebuild.json"]
APP_FILES = ["auto_trade.json", "auto_trade_ledger.jsonl", "deployments.jsonl",
             "notifications.db", "error_issues.json", "ingest_token",
             "runtime_specs.json", "api.log", "strategy_watcher.json"]


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    for d in EXCHANGE_DIRS:
        (h / d).mkdir(parents=True)
        (h / d / "x.json").write_text("{}")
    (h / "v2" / "rows.db").write_text("db")
    for f in EXCHANGE_FILES + APP_FILES:
        (h / f).write_text("{}")
    (h / "profiles" / "4FC03172").mkdir(parents=True)
    monkeypatch.setattr(vs, "HOME", h)
    monkeypatch.setattr(venue, "VENUE_FILE", h / "venue.json")
    monkeypatch.delenv("TA_VENUE", raising=False)
    monkeypatch.setattr(vs, "_blockers", lambda: [])
    return h


def _open_practice_trade():
    state = at.load_state()
    state["BTC_USDT#paper#bb20_1h_sl1tp2"] = {"step": 0, "position": {
        "side": 1, "entry": 100.0, "margin": 5.0, "strategy": "bb20_1h_sl1tp2",
        "entry_ts": 1791600000, "opened_at": 1791600060, "tp": 102.0,
        "sl": 99.0, "dry": True, "rt_cost": 0.002}}
    at.save_state(state)
    at.save_settings({**at.load_settings(),
                      "strategies": ["bb20_1h_sl1tp2"],
                      "strategy_coins": {"bb20_1h_sl1tp2": ["BTC_USDT", "GPNSTOCK_USDT"]},
                      "strategy_books": {"bb20_1h_sl1tp2|BTC_USDT": ["paper"],
                                         "bb20_1h_sl1tp2|GPNSTOCK_USDT": ["paper"]}})


def test_the_whole_cutover(home):
    _open_practice_trade()
    got = vs.switch("gate", rooms=["main"], price_of=lambda s: 101.0,
                    now=1791614400)
    # 1. the open practice trade is closed at MEXC's price, with its reason
    exits = [json.loads(x) for x in at._pp(at.LEDGER_PATH).read_text().splitlines()
             if '"exit"' in x]
    (e,) = exits
    assert e["why"] == "VENUE_SWITCH" and e["exit"] == 101.0 and e["dry_run"] is True
    assert e["pnl_est"] == pytest.approx(((101 / 100 - 1) - 0.002) * 5 * 20, abs=0.01)
    assert at.load_state()["BTC_USDT#paper#bb20_1h_sl1tp2"]["position"] is None
    # 2. every practice row is off
    s = at.load_settings()
    assert not any(s.get("strategy_coins", {}).values())
    assert not s.get("strategy_books")
    # 3. the exchange's data moved, the app's stayed
    arch = Path(got["archive"])
    assert arch.parent == home and arch.name.startswith("archive-mexc-")
    for d in EXCHANGE_DIRS:
        assert not (home / d).exists() and (arch / d / "x.json").exists(), d
    for f in EXCHANGE_FILES:
        assert not (home / f).exists() and (arch / f).exists(), f
    for f in APP_FILES:
        assert (home / f).exists(), f
    assert (home / "profiles" / "4FC03172").is_dir()
    # 4. and only then the switch
    assert venue.current() == "gate"
    assert got["closed"][0]["symbol"] == "BTC_USDT"
    assert got["switched_off"] == {"main": 2}
    assert json.loads((arch / "switch.json").read_text())["to"] == "gate"


def test_it_refuses_while_anything_holds_the_store(home, monkeypatch):
    monkeypatch.setattr(vs, "_blockers", lambda: ["the API (pid 4242) on port 8787"])
    with pytest.raises(vs.SwitchRefused, match="8787"):
        vs.switch("gate", rooms=["main"], price_of=lambda s: 1.0)
    assert (home / "v2" / "rows.db").exists(), "nothing moved"
    assert venue.current() == "mexc"


def test_it_refuses_while_a_room_holds_real_money(home):
    at.save_settings({**at.load_settings(), "strategies": ["k"],
                      "strategy_coins": {"k": ["BTC_USDT"]},
                      "strategy_books": {"k|BTC_USDT": ["paper", "real"]}})
    with pytest.raises(vs.SwitchRefused, match="real money"):
        vs.switch("gate", rooms=["main"], price_of=lambda s: 1.0)
    assert venue.current() == "mexc"


def test_a_price_that_cannot_be_read_refuses_before_anything_moves(home):
    _open_practice_trade()

    def down(sym):
        raise RuntimeError("MEXC unreachable")
    with pytest.raises(vs.SwitchRefused, match="BTC_USDT"):
        vs.switch("gate", rooms=["main"], price_of=down)
    assert at.load_state()["BTC_USDT#paper#bb20_1h_sl1tp2"]["position"]
    assert (home / "v2").exists() and venue.current() == "mexc"


def test_a_second_run_changes_nothing_and_says_so(home):
    vs.switch("gate", rooms=["main"], price_of=lambda s: 1.0, now=1)
    again = vs.switch("gate", rooms=["main"], price_of=lambda s: 1.0, now=2)
    assert again["already"] is True and venue.current() == "gate"


def test_a_dry_run_moves_nothing(home):
    _open_practice_trade()
    plan = vs.switch("gate", rooms=["main"], price_of=lambda s: 101.0,
                     dry_run=True)
    assert set(plan["would_move"]) >= {"v2", "backtest", "book_readings.jsonl"}
    assert (home / "v2").exists() and venue.current() == "mexc"
    assert at.load_state()["BTC_USDT#paper#bb20_1h_sl1tp2"]["position"]


def test_a_stale_job_pid_that_now_belongs_to_another_program_does_not_block(monkeypatch, tmp_path):
    """The first real run refused on db_backtest_v2.pid = 21144, written
    Sep 17, 2026 and by Oct 10 reused by Microsoft Teams. A job blocks when
    the job system says it is RUNNING, never on a pid alone."""
    from tradingagents import db_jobs as dj, profiles, rows_index as ri

    monkeypatch.setattr(vs, "HOME", tmp_path)
    (tmp_path / "db_backtest_v2.pid").write_text("21144")
    monkeypatch.setattr(dj, "status", lambda k: {"running": False, "pid": 21144})
    monkeypatch.setattr(ri, "run_lock_held", lambda: False)
    monkeypatch.setattr(profiles, "ids", lambda: [])
    import start as _start

    monkeypatch.setattr(_start, "port_pids", lambda port: [])
    assert vs._blockers() == []
    monkeypatch.setattr(dj, "status",
                        lambda k: {"running": k == "collect_v2", "pid": 77})
    assert vs._blockers() == ["the collect_v2 job (pid 77)"]
