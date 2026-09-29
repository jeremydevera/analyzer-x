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
    monkeypatch.setattr(sw, "_register", lambda key, spec, persist=True:
                        (w["registered"].append((key, persist)), "added")[1])
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
    assert world["registered"] == [(KEY, True)]


def test_preview_decides_and_writes_nothing(world):
    sw.set_mode("preview")
    got = sw.consider(now=NOW)
    assert world["saves"] == 0 and got["decisions"][0]["mode"] == "preview"
    assert world["registered"] == [(KEY, False)], "no recipe file written in preview"


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


def test_the_watcher_runs_on_its_own_thread_not_in_the_supervisor():
    """Its switch-on pass reads the index, 6 MB pair files and the live book;
    inside the supervisor loop that minute would stop it restarting a dead
    runner or indexer."""
    import pathlib

    src = pathlib.Path(sw.__file__).with_name("api.py").read_text("utf-8")
    watch = src[src.index("def _watch() -> None:"):]
    watch = watch[:watch.index("_th.Thread(target=_watch")]
    assert "_sw.tick()" not in watch
    loop = src[src.index("def _watcher_loop() -> None:"):]
    loop = loop[:loop.index('name="strategy-watcher"')]      # the loop's own body
    assert "_sw.tick()" in loop and "[watcher] up" in loop, "it ticks, and says it started"
    assert 'name="strategy-watcher"' in src


def _local(y, m, d, h, mi=0):
    import datetime as dt

    return dt.datetime(y, m, d, h, mi).timestamp()


def test_the_switch_on_pass_waits_for_noon(world):
    """Sep 29, 2026 3:36am: stock-token books at night blocked IGV 1h on a
    0.675% gap. The switch-on pass runs once a day at or after 12:00pm."""
    night = _local(2026, 9, 29, 3, 36)
    assert not [d for d in sw.consider(now=night)["decisions"] if d["action"] == "on"]
    assert sw.next_on(night, 0) == _local(2026, 9, 29, 12)
    noon = _local(2026, 9, 29, 12, 1)
    assert [d["action"] for d in sw.consider(now=noon)["decisions"]] == ["on"]
    assert sw.next_on(noon + 60, noon) == _local(2026, 9, 30, 12)


def test_a_cost_warning_is_not_a_refusal(world):
    """The runner trades on "warn" (cost over 20% of the target); only "block"
    stops it. #GUCXTP4L VUG 30m (91.3%, 37% of its target) was refused."""
    world["edge"]["GPNSTOCK_USDT"] = "warn"
    got = sw.consider(now=NOW)
    assert [d["action"] for d in got["decisions"]] == ["on"]


def test_a_refused_pick_does_not_use_up_one_of_the_days_places(world):
    """Twenty candidates, the first ten on a coin whose cost check blocks: the
    day's 20 new must still be filled from the rest, 3 per coin."""
    world["cands"] = ([{**R6, "id": f"BAD{i:05d}", "coin": "IGV", "winrate": 99.0,
                        "tp": 1.0 + i / 100} for i in range(10)]
                      + [{**R6, "id": f"OK{i:06d}", "coin": f"C{i}", "tp": 1.0 + i / 100}
                         for i in range(25)])
    world["edge"]["IGV_USDT"] = "block"
    got = sw.consider(now=NOW)
    on = [d for d in got["decisions"] if d["action"] == "on"]
    assert len(on) == 20 and all(d["coin"] != "IGV" for d in on)



# ------------------------------------------------ the review of Sep 29, 2026
def test_a_switched_off_last_coin_leaves_an_empty_list_never_a_missing_key(world):
    """coins_for() reads a MISSING key as every coin in the global list, and
    with no book entry left the row would take the GLOBAL switches."""
    world["settings"]["coins"] = ["BTC_USDT", "ETH_USDT"]
    world["settings"]["enabled"] = True
    sw.consider(now=NOW)
    world["fresh"]["77Y3BPFG"] = {**R6, "winrate": 60.0}
    sw.consider(now=NOW + 3601)
    s = world["settings"]
    assert s["strategy_coins"][KEY] == [], "explicitly empty means none"
    assert at.coins_for(KEY, s) == []


def test_the_operator_turning_it_off_mid_pass_wins(world, monkeypatch):
    """set_mode writes the state file while the pass holds an older copy."""
    def _edge_then_off(key, sym):
        sw.set_mode("off")
        return {"verdict": "ok", "reason": "t"}

    monkeypatch.setattr(sw, "_edge", _edge_then_off)
    got = sw.consider(now=NOW)
    assert world["saves"] == 0, "nothing armed after it was switched off"
    assert sw.mode_of() == "off", "the pass must not write the old mode back"
    assert got["decisions"][0]["action"] == "refused"
    assert "NOT DONE" in got["decisions"][0]["why"]


def test_a_write_that_never_lands_is_not_logged_as_done(world, monkeypatch):
    monkeypatch.setattr(sw, "_write_settings", lambda mutate: False)
    got = sw.consider(now=NOW)
    assert [d["action"] for d in got["decisions"]] == ["refused"]
    assert not world["bells"], "no 'switched on' bell for nothing"


def test_preview_starts_no_seven_day_wait(world):
    sw.consider(now=NOW)                       # act: armed
    sw.set_mode("preview")
    world["fresh"]["77Y3BPFG"] = {**R6, "winrate": 60.0}
    sw.consider(now=NOW + 3601)
    assert "77Y3BPFG" not in (sw._read().get("cooling") or {})


def test_a_preview_recipe_does_not_outlive_its_check(world, monkeypatch):
    """Left in memory it made the next act pass answer "same" and write no
    file, so the runner never learned the key."""
    monkeypatch.setattr(sw, "_register", sw.__dict__["_register"].__wrapped__
                        if hasattr(sw.__dict__["_register"], "__wrapped__") else _REAL_REGISTER)
    sw.set_mode("preview")
    sw.consider(now=NOW)
    assert KEY not in at.STRATEGY_SPECS


def test_a_key_only_in_memory_is_still_written_to_the_runners_file(tmp_path, monkeypatch):
    from tradingagents import runtime_specs as rs

    monkeypatch.setattr(rs, "PATH", tmp_path / "runtime_specs.json")
    spec = {"interval": "Min60", "bar_seconds": 3600, "tp": 0.01, "sl": 0.007}
    monkeypatch.setitem(at.STRATEGY_SPECS, KEY, dict(spec))     # a stray preview
    assert rs.register(KEY, spec) == "added"
    assert KEY in rs.load()


def test_a_deleted_pair_file_switches_the_row_off(world, monkeypatch, tmp_path):
    """The delisted cleanup removes a coin's pair files: that row is gone, not
    unreadable, and must not sit in the watcher for ever."""
    from tradingagents import watcher_candidates as wc

    monkeypatch.setattr(sw, "_fresh_row", _REAL_FRESH_ROW)
    sw.consider(now=NOW)
    monkeypatch.setattr(wc, "pair_file", lambda coin, tf: tmp_path / "gone.json")
    got = sw.consider(now=NOW + 3601)
    assert [d["action"] for d in got["decisions"]] == ["off"]
    assert "no longer holds" in got["decisions"][0]["why"]


def test_a_pair_file_that_is_there_but_unreadable_keeps_the_row(world, monkeypatch, tmp_path):
    from tradingagents import watcher_candidates as wc

    monkeypatch.setattr(sw, "_fresh_row", _REAL_FRESH_ROW)
    sw.consider(now=NOW)
    f = tmp_path / "broken.json"
    f.write_text("{not json")
    monkeypatch.setattr(wc, "pair_file", lambda coin, tf: f)
    monkeypatch.setattr(wc, "_pair_rows", lambda coin, tf: [])
    got = sw.consider(now=NOW + 3601)
    assert not [d for d in got["decisions"] if d["action"] == "off"]


def test_a_rule_the_live_watcher_cannot_honour_is_refused_not_printed(world):
    with pytest.raises(ValueError, match="does not use"):
        sw.set_cfg({"window_days": 14})
    st = sw.status()
    assert "window_days" not in st["cfg"] and st["window_days"] == sw.store_window_days()
    assert "off_streak_live" not in st["cfg"]


_REAL_REGISTER = sw._register
_REAL_FRESH_ROW = sw._fresh_row
