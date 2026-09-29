"""One watcher pass, end to end, on an in-memory settings file.

Operator, Sep 29, 2026: "deploy now the wathcer replay, /goal i want this
fully working, the backtest everyday the promotion and demotion". Everything
runs on tmp_path and an in-memory settings dict: no test can reach the
operator's real settings, trade record or GitHub.
"""
from __future__ import annotations

import pytest

from tradingagents import auto_trader as at
from tradingagents import strategy_watcher as sw

NOW = 1_790_700_000.0
# #77Y3BPFG GPNSTOCK 1h macddiv SL 0.7% / TP 1.0%: 20 trades, 100%, +$15.84.
# Its key macddiv_1h_sl07tp1 is in no committed block (the runtime registry).
R6 = {"id": "77Y3BPFG", "coin": "GPNSTOCK", "tf": "1h", "signal": "macddiv",
      "th": 0.0, "sl": 0.7, "tp": 1.0, "trades": 20, "wins": 20, "losses": 0,
      "winrate": 100.0, "profit": 15.84, "gate": "ok", "measured_ms": NOW * 1000}
KEY = "macddiv_1h_sl07tp1"
SLOT = f"{KEY}|GPNSTOCK_USDT"
HAND = "bb20_15m_sl12tp12|FASTSTOCK_USDT"


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = {"settings": {"strategies": [], "strategy_coins": {}, "strategy_books": {},
                      "strategy_margins": {}, "strategy_sizing": {}, "enabled": False},
         "saves": 0, "edge": {}, "cands": [R6], "fresh": {}, "readable": True,
         "registered": [], "bells": [], "not_ready": False}
    monkeypatch.setattr(sw, "STATE", tmp_path / "w.json")
    monkeypatch.setattr(sw, "LOG", tmp_path / "w.jsonl")
    monkeypatch.setattr(at, "load_settings", lambda: sw._copy(w["settings"]))

    def _save(s):
        w["saves"] += 1
        w["settings"] = s
        return []

    monkeypatch.setattr(at, "save_settings", _save)
    monkeypatch.setattr(sw, "_edge", lambda key, sym: {"verdict": w["edge"].get(sym, "ok"),
                                                       "reason": "test"})
    monkeypatch.setattr(sw, "_candidates", lambda cfg, now: (
        {"rows": [], "not_ready": True, "why": "rows_wr4 is being built"}
        if w["not_ready"] else {"rows": list(w["cands"]), "why": "fake"}))
    monkeypatch.setattr(sw, "_fresh_row", lambda meta, now, cfg: (
        w["fresh"].get(meta["id"], R6 if meta["id"] == "77Y3BPFG" else None),
        w["readable"]))
    monkeypatch.setattr(sw, "_register", lambda key, spec: w["registered"].append(key) or "added")
    monkeypatch.setattr(sw, "_sig_of", lambda key: key.split("_")[0])
    monkeypatch.setattr(sw.time, "sleep", lambda s: None)
    from tradingagents import notifications as nt

    monkeypatch.setattr(nt, "record", lambda *a, **k: (w["bells"].append(a), 1)[1])
    return w


def test_it_acts_by_default_and_arms_practice_only_by_id(world):
    got = sw.consider(now=NOW)
    s = world["settings"]
    assert [d["action"] for d in got["decisions"]] == ["on"]
    assert s["strategy_coins"][KEY] == ["GPNSTOCK_USDT"]
    assert at.book_names(s, KEY, "GPNSTOCK_USDT") == ["paper"]
    assert s["strategy_res"][SLOT] == "1m" and s["strategy_margins"][KEY] == 5.0
    assert s["watcher_slots"][SLOT]["id"] == "77Y3BPFG"
    assert s["enabled"] is False, "the live switch is never turned on"
    assert "#77Y3BPFG" in got["decisions"][0]["why"]
    assert world["registered"] == [KEY]


def test_preview_decides_and_writes_nothing(world):
    sw.set_mode("preview")
    got = sw.consider(now=NOW)
    assert world["saves"] == 0 and got["decisions"][0]["mode"] == "preview"


def test_off_does_nothing(world):
    sw.set_mode("off")
    assert sw.consider(now=NOW)["decisions"] == [] and world["saves"] == 0


@pytest.mark.parametrize("verdict", ["block", "unknown"])
def test_a_cost_check_that_is_not_ok_refuses_by_id(world, verdict):
    world["edge"]["GPNSTOCK_USDT"] = verdict
    got = sw.consider(now=NOW)
    assert world["saves"] == 0
    assert got["decisions"][0]["action"] == "refused" and "#77Y3BPFG" in got["decisions"][0]["why"]


def test_under_ninety_percent_switches_it_off_and_it_waits_seven_days(world):
    sw.consider(now=NOW)
    world["fresh"]["77Y3BPFG"] = {**R6, "winrate": 89.9}
    got = sw.consider(now=NOW + 3601)
    assert [d["action"] for d in got["decisions"]] == ["off"]
    assert "GPNSTOCK_USDT" not in (world["settings"]["strategy_coins"].get(KEY) or [])
    assert SLOT not in world["settings"]["watcher_slots"]
    assert SLOT not in world["settings"]["strategy_books"]
    world["fresh"]["77Y3BPFG"] = R6
    got = sw.consider(now=NOW + 86_400 + 3602)
    assert not [d for d in got["decisions"] if d["action"] == "on"], "7-day wait"


def test_a_backtest_file_that_cannot_be_read_keeps_the_row(world):
    """An unreadable file is not a row that is gone — switching off on it would
    be the watcher's own mistake."""
    sw.consider(now=NOW)
    world["readable"] = False
    got = sw.consider(now=NOW + 3601)
    assert not [d for d in got["decisions"] if d["action"] == "off"]
    assert SLOT in world["settings"]["watcher_slots"]


def test_a_list_that_is_not_ready_is_tried_again_not_skipped_for_a_day(world):
    world["not_ready"] = True
    got = sw.consider(now=NOW)
    assert world["saves"] == 0 and "waiting" in got["why"]
    world["not_ready"] = False
    assert not sw.consider(now=NOW + 60)["decisions"], "not every tick"
    assert [d["action"] for d in sw.consider(now=NOW + sw.RETRY_S)["decisions"]] == ["on"]


def test_the_on_pass_is_daily_and_the_off_pass_hourly(world):
    sw.consider(now=NOW)
    world["cands"] = [{**R6, "id": "OTHER001", "coin": "KKRSTOCK"}]
    assert not [d for d in sw.consider(now=NOW + 3601)["decisions"] if d["action"] == "on"]
    assert [d for d in sw.consider(now=NOW + 86_401)["decisions"] if d["action"] == "on"]


def test_it_never_touches_real_money_or_a_row_you_armed_yourself(world):
    world["settings"]["strategy_coins"] = {KEY: ["GPNSTOCK_USDT"],
                                           "bb20_15m_sl12tp12": ["FASTSTOCK_USDT"]}
    world["settings"]["strategy_books"] = {KEY: ["real"], HAND: ["paper"]}
    got = sw.consider(now=NOW)
    s = world["settings"]
    assert got["decisions"][0]["action"] == "refused"
    assert "already run this row yourself" in got["decisions"][0]["why"]
    assert s["strategy_books"] == {KEY: ["real"], HAND: ["paper"]}
    assert "watcher_slots" not in s or not s["watcher_slots"]


def test_a_save_on_screen_between_read_and_write_is_kept(world, monkeypatch):
    calls = {"n": 0}

    def _load():
        calls["n"] += 1
        if calls["n"] == 4:                       # the re-read inside the write
            world["settings"]["strategy_margins"] = {"keltner_30m_sl2tp2": 7.0}
        return sw._copy(world["settings"])

    monkeypatch.setattr(at, "load_settings", _load)
    sw.consider(now=NOW)
    assert world["settings"]["strategy_margins"]["keltner_30m_sl2tp2"] == 7.0
    assert KEY in world["settings"]["strategy_coins"]


def test_off_never_closes_a_position_itself():
    import inspect

    src = inspect.getsource(sw)
    for banned in ("save_state", "close_position", "_dry_fill", "place_order"):
        assert banned not in src


def test_rules_are_the_operators_and_can_be_changed_on_screen(world):
    assert (sw.cfg_of()["on_winrate"], sw.cfg_of()["off_winrate"],
            sw.cfg_of()["min_trades"], sw.cfg_of()["tp_rule"]) == (90.0, 90.0, 20, ">")
    sw.set_cfg({"on_winrate": 80})
    assert sw.cfg_of()["on_winrate"] == 80.0
    with pytest.raises(ValueError):
        sw.set_cfg({"nope": 1})
    with pytest.raises(ValueError):
        sw.set_cfg({"min_trades": "20"})


def test_it_never_runs_under_a_test():
    assert sw.tick() == {"decisions": [], "why": "never under a test run"}


def test_the_supervisor_ticks_it():
    import pathlib

    src = pathlib.Path(sw.__file__).with_name("api.py").read_text("utf-8")
    watch = src[src.index("def _watch() -> None:"):]
    watch = watch[:watch.index("_th.Thread(target=_watch")]
    assert "_sw.tick()" in watch
