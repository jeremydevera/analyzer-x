"""A practice trade carries its Backtest id, period (operator, Oct 14, 2026:
"the id in practice should be same as backtest id period").

Room #55D32617's watcher switched GPS 15m tsi (TP 1% / SL 0.8%) on as
#5RKPYVQ7, its Backtest v2 id, at Oct 13, 2026 2:00am, and off at 9:09am. Its
two practice trades (6:45am, 8:15am) were then listed as #ZQJMM3GF — the same
strategy's v1 twin, which the Backtest tab cannot find — because the switch-off
erased the room's note that the row came from v2 (`strategy_res`), and every
screen names a trade from that note (`api.row_id_for`).
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import tradingagents.auto_trader as at
from tradingagents import profiles
from tradingagents import strategy_watcher as sw

pytestmark = pytest.mark.unit

KEY, SYM = "squeeze_1h_sl3tp3", "KITE_USDT"
SLOT = f"{KEY}|{SYM}"


def _ids() -> tuple[str, str]:
    """(the Backtest v2 id, its v1 twin) of KEY on SYM."""
    from tradingagents import api

    v2 = api.row_id_for(KEY, SYM, {"strategy_res": {SLOT: "1m"}})
    v1 = api.row_id_for(KEY, SYM, {})
    assert v2 and v1 and v2 != v1
    return v2, v1


def _trade(ts: int, tid: str) -> list[dict]:
    """One closed practice trade, its entry and its exit, on one timeline."""
    return [{"ts": ts - 600, "action": "enter", "symbol": SYM, "strategy": KEY,
             "trade_id": tid, "opened_at": ts - 600, "side": "SHORT",
             "dry_run": True, "entry": 1.0, "tp": 0.99, "sl": 1.008},
            {"ts": ts, "action": "exit", "symbol": SYM, "strategy": KEY,
             "dry_run": True, "why": "SL", "pnl_est": -1.09, "trade_id": tid,
             "opened_at": ts - 600, "held_s": 600, "side": "SHORT"}]


def _shown(client: TestClient) -> tuple[list, list]:
    """The strategy id each trade list prints: the room's own and Main's."""
    one = client.get("/api/trade/history?dry=true",
                     headers={"X-TA-Profile": "55D32617"}).json()["rows"]
    every = client.get("/api/trade/history/rooms?dry=true").json()["rows"]
    return ([r["strategy_id"] for r in one], [r["strategy_id"] for r in every])


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(profiles, "shown", lambda: ["main", "55D32617"])
    from tradingagents.api import app
    return TestClient(app)


def test_a_strategy_switched_off_keeps_its_backtest_id_on_its_trades(client, write_ledger):
    """The operator's case: switched on as the v2 row, traded, switched off
    by the watcher — both trade lists still print the v2 id."""
    v2, v1 = _ids()
    with profiles.using("55D32617"):
        at.save_settings(sw._arm(at.load_settings(), KEY, SYM, {"id": v2}))
        write_ledger(_trade(5_000, "HZ5H2P7B"))
        at.save_settings(sw._disarm(at.load_settings(), SLOT))
        s = at.load_settings()
        assert SLOT not in (s.get("strategy_books") or {}), "it IS switched off"
        assert SLOT not in (s.get("watcher_slots") or {})
    assert _shown(client) == ([v2], [v2]), f"{v1} is the v1 twin Backtest cannot find"


def _watcher_said(action: str, rid: str, mode: str = "act") -> None:
    """One line of the room's own watcher log, as `strategy_watcher._log`
    writes it."""
    p = sw._log_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"action": action, "at": 4_000.0, "coin": "KITE",
                             "id": rid, "mode": mode, "signal": "squeeze",
                             "tf": "1h", "tp": 3.0, "sl": 3.0, "why": "test"}) + "\n")


def test_a_note_erased_before_the_fix_is_restored_from_the_watchers_record(client, write_ledger):
    """#5RKPYVQ7's note was erased at 9:09am on Oct 13, 2026, before this fix.
    The watcher's own log names the id it switched on, so the note comes back
    from there — once, and only for a row the watcher really switched on."""
    v2, v1 = _ids()
    with profiles.using("55D32617"):
        write_ledger(_trade(5_000, "HZ5H2P7B"))
        _watcher_said("on", v2)
        _watcher_said("off", v2)
    assert _shown(client) == ([v1], [v1]), "the damage this repairs"
    assert sw.restore_backtest_notes() == {"55D32617": 1}
    assert _shown(client) == ([v2], [v2])
    assert sw.restore_backtest_notes() == {}, "a second run changes nothing"


def test_a_row_the_watcher_only_previewed_or_never_touched_keeps_its_id(client, write_ledger):
    """PREVIEW reports a row without switching it on, so it proves nothing
    about where a trade came from; and with no record at all, nothing is
    guessed."""
    v2, v1 = _ids()
    with profiles.using("55D32617"):
        write_ledger(_trade(5_000, "HZ5H2P7B"))
        _watcher_said("on", v2, mode="preview")
    assert sw.restore_backtest_notes() == {}
    assert _shown(client) == ([v1], [v1])


def test_a_replace_deploy_keeps_the_notes_of_what_it_switches_off():
    """`replace` switches off every row the preset does not name; their trades
    must keep the id they were made under, exactly as a watcher switch-off."""
    from tradingagents import deploy_preset as dp

    settings = sw._arm(at.load_settings(), KEY, SYM, {})
    other = "sweep_1h"
    assert other in at.STRATEGY_SPECS
    out = dp.merged({"replace": True, "res": "1m",
                     "strategies": {other: {"coins": ["ARKM_USDT"]}}}, settings)
    assert KEY not in out["strategies"], "it IS switched off"
    assert out["strategy_res"][SLOT] == "1m"
    assert out["strategy_res"][f"{other}|ARKM_USDT"] == "1m"
