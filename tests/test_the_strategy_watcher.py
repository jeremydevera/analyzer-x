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
    # the DEMO column's 30-day figures (rolling30) live under at.STATE_DIR:
    # a test must never read the operator's real ones
    monkeypatch.setattr(at, "STATE_DIR", tmp_path)
    from tradingagents import rolling30 as _r30

    _r30._MEMO.clear()
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
        sw.set_cfg({"off_streak_live": 3})
    # a window is honoured only where every row is measured: 15 or 30 days
    # (Sep 30, 2026, the table's 15-day rooms)
    with pytest.raises(ValueError, match="must be one of"):
        sw.set_cfg({"window_days": 14})
    st = sw.status()
    assert st["window_days"] == sw.store_window_days()
    assert "off_streak_live" not in st["cfg"]


_REAL_REGISTER = sw._register
_REAL_FRESH_ROW = sw._fresh_row


# ------------------------------------------------ harddev round 1 (Sep 29, 2026)
def test_a_check_that_crashes_is_not_retried_every_minute(world, monkeypatch):
    calls = []

    def _boom(cfg, now):
        calls.append(now)
        raise RuntimeError("the index went away")

    monkeypatch.setattr(sw, "_candidates", _boom)
    got = sw.consider(now=NOW)
    assert "failed" in got["why"] and "RuntimeError" in got["why"]
    sw.consider(now=NOW + 60)
    assert len(calls) == 1, "not again a minute later"
    sw.consider(now=NOW + sw.RETRY_S)
    assert len(calls) == 2


def test_a_row_you_switched_off_yourself_stops_counting(world):
    sw.consider(now=NOW)
    s = world["settings"]
    s["strategy_coins"][KEY] = []                    # unticked on the screen
    got = sw.consider(now=NOW + 3601)
    assert SLOT not in world["settings"]["watcher_slots"]
    assert any("switched off outside the watcher" in d["why"] for d in got["decisions"])


def test_the_waits_and_the_report_marks_are_trimmed(world):
    st = sw._read()
    st["cooling"] = {"OLD00001": NOW - 8 * 86_400, "NEW00001": NOW - 86_400}
    st["reported"] = {"OLD00001": "2026-01-01"}
    sw._write(st)
    sw.consider(now=NOW)
    after = sw._read()
    assert "OLD00001" not in after["cooling"] and "NEW00001" in after["cooling"]
    assert "OLD00001" not in (after.get("reported") or {})


def test_the_panel_reads_only_the_logs_tail(world):
    big = [{"at": i, "mode": "act", "action": "report", "id": f"X{i}", "why": "x" * 400}
           for i in range(3000)]
    sw._log(big)
    got = sw.recent(50)
    assert len(got) == 50 and got[0]["id"] == "X2999"


# ------------------------------------------------ harddev round 2
def test_a_strategy_name_set_to_another_stake_is_refused(world):
    """The stake is per NAME (margin_for): a coin added under a $20 name would
    trade $20, never the $5 the replay measured."""
    world["settings"]["strategy_margins"] = {KEY: 20.0}
    got = sw.consider(now=NOW)
    assert got["decisions"][0]["action"] == "refused"
    assert "$20 a trade" in got["decisions"][0]["why"] and world["saves"] == 0


def test_a_row_switched_off_by_hand_is_reported_once_a_day_in_preview(world):
    sw.consider(now=NOW)
    world["settings"]["strategy_coins"][KEY] = []
    sw.set_mode("preview")
    first = sw.consider(now=NOW + 3601)["decisions"]
    again = sw.consider(now=NOW + 7202)["decisions"]
    assert any("outside the watcher" in d["why"] for d in first)
    assert not any("outside the watcher" in d["why"] for d in again)


# ------------------------------------------------------------------------
# SMART WATCHER (Sep 29, 2026): "as i said it should be switched off, you
# should follow my criteria" — #LLC76MPD GPNSTOCK 15m keltner sat at 89% and
# was only REPORTED because the operator had switched it on themselves.

def _hand_row(world, winrate, books=("paper",)):
    """The operator's own practice row, armed from Backtest v2."""
    key, sym = HAND.split("|")
    world["settings"]["strategy_coins"] = {key: [sym]}
    world["settings"]["strategy_books"] = {HAND: list(books)}
    world["settings"]["strategy_res"] = {HAND: "1m"}
    world["cands"] = []
    meta = sw._meta_of_key(key, sym)
    rid = sw._row_id(world["settings"], key, sym, meta)
    world["fresh"][rid] = {**R6, "id": rid, "winrate": winrate, "trades": 87,
                           "wins": 78, "losses": 9}
    return key, sym, rid


def test_your_own_practice_row_under_the_line_is_switched_off(world):
    key, sym, rid = _hand_row(world, 89.66)
    got = sw.consider(now=NOW)
    offs = [d for d in got["decisions"] if d["action"] == "off"]
    assert [d["id"] for d in offs] == [rid]
    assert "YOUR practice rows" in offs[0]["why"] and "89.66%" in offs[0]["why"]
    s = world["settings"]
    assert s["strategy_coins"][key] == [], "empty list, never a missing key"
    assert HAND not in s["strategy_books"] and HAND not in s["strategy_res"]
    assert rid in sw._read()["cooling"], "it waits 7 days like any switch-off"


def test_your_own_row_at_the_line_or_above_stays(world):
    key, sym, _rid = _hand_row(world, 90.0)
    got = sw.consider(now=NOW)
    assert not [d for d in got["decisions"] if d["action"] == "off"]
    assert world["settings"]["strategy_coins"][key] == [sym]


def test_a_row_holding_real_money_is_never_switched_off(world):
    key, sym, _rid = _hand_row(world, 50.0, books=("real", "paper"))
    got = sw.consider(now=NOW)
    assert not [d for d in got["decisions"] if d["action"] == "off"]
    assert world["settings"]["strategy_coins"][key] == [sym]
    assert world["settings"]["strategy_books"][HAND] == ["real", "paper"]


def test_it_judges_on_the_demo_columns_30_day_figure(world, monkeypatch):
    """The backtest says 95%, but five practice losses since pulled the last
    30 days to 79% — the operator's own example ("the backtest for last 30
    days is 95% then i have 5 losing trades in live")."""
    from tradingagents import rolling30 as r30

    key, sym, rid = _hand_row(world, 95.0)
    monkeypatch.setattr(r30, "figure", lambda slot, **k: (
        {"wins": 19, "losses": 5, "trades": 24, "pnl": 3.1, "winrate": 79.17,
         "from_backtest": 19, "from_practice": 5} if slot == HAND else None))
    got = sw.consider(now=NOW)
    offs = [d for d in got["decisions"] if d["action"] == "off"]
    assert [d["id"] for d in offs] == [rid] and "79.17%" in offs[0]["why"]


def test_a_row_reported_earlier_today_is_still_switched_off(world):
    """#LLC76MPD was REPORTED at Sep 29, 2026 3:40am under the old rule; the
    day's report mark must not hold its switch-off until tomorrow."""
    key, sym, rid = _hand_row(world, 89.66)
    import datetime as dt

    st = sw._read()
    st["reported"] = {rid: str(dt.date.fromtimestamp(NOW))}
    sw._write(st)
    got = sw.consider(now=NOW)
    assert [d["id"] for d in got["decisions"] if d["action"] == "off"] == [rid]


def test_smart_watcher_off_switches_nothing_on_or_off(world):
    key, sym, _rid = _hand_row(world, 50.0)
    world["cands"] = [R6]
    sw.set_mode("off")
    before = sw._copy(world["settings"])
    got = sw.consider(now=NOW)
    assert got["decisions"] == [] and world["saves"] == 0
    assert world["settings"] == before


def test_preview_says_it_would_switch_your_row_off_and_changes_nothing(world):
    key, sym, rid = _hand_row(world, 89.66)
    sw.set_mode("preview")
    got = sw.consider(now=NOW)
    offs = [d for d in got["decisions"] if d["action"] == "off"]
    assert [d["mode"] for d in offs] == ["preview"]
    assert world["settings"]["strategy_coins"][key] == [sym]
    # said once a day in preview, not every hour
    again = sw.consider(now=NOW + 3601)
    assert not [d for d in again["decisions"] if d["id"] == rid]


def test_the_daily_backtest_update_runs_whatever_the_watcher_says():
    """ "still the scheduled github backest run should still run every 24 hrs
    wether this is on or off" — the supervisor ticks daily_update on its own,
    and daily_update never asks the watcher anything."""
    src = open("tradingagents/daily_update.py", encoding="utf-8").read()
    assert "strategy_watcher" not in src and "watcher" not in src.lower()
    api = open("tradingagents/api.py", encoding="utf-8").read()
    tick = api[api.index("from tradingagents import daily_update as _du"):]
    tick = tick[:tick.index("_du.tick()") + len("_du.tick()")]
    assert "mode" not in tick and "watcher" not in tick


def test_the_screen_has_one_smart_watcher_box_in_both_places():
    box = open("webapp/src/components/trade/SmartWatcherBox.tsx", encoding="utf-8").read()
    assert "Smart Watcher" in box
    assert 'mode: v ? "act" : "off"' in box
    grid = open("webapp/src/components/trade/StrategiesGrid.tsx", encoding="utf-8").read()
    panel = open("webapp/src/components/trade/WatcherPanel.tsx", encoding="utf-8").read()
    assert "<SmartWatcherBox />" in grid and "<SmartWatcherBox onChange=" in panel
    assert 'aria-label="Watcher mode"' not in panel, "the three mode buttons are gone"
    assert "the daily backtest update still runs" in panel


# ------------------------------------------------------------------------
# NO STOP WIDER THAN 2% (Sep 29, 2026, "okay do it"): the 93 practice trades
# with a stop wider than 2% won 31% and lost $139.66 of the -$138.02.

def test_a_row_with_a_stop_wider_than_two_percent_is_never_switched_on():
    from tradingagents import watcher_policy as wp

    cfg = dict(wp.DEFAULTS)
    row = {"tp": 5.0, "sl": 3.0, "winrate": 100.0, "trades": 30, "profit": 9.0, "gate": "ok"}
    assert "SL 3% is wider than 2%" in wp.passes_on(row, cfg)
    assert wp.passes_on({**row, "sl": 2.0}, cfg) == "", "2% itself is allowed"
    assert wp.passes_on(row, {**cfg, "max_sl": 0}) == "", "0 means no cap"


def test_the_cap_is_a_live_rule_and_reaches_the_index_query():
    assert "max_sl" in sw.LIVE_RULES and sw.cfg_of({})["max_sl"] == 2.0
    src = open("tradingagents/watcher_candidates.py", encoding="utf-8").read()
    assert 'max_sl=float(cfg.get("max_sl") or 0))' in src
    panel = open("webapp/src/components/trade/WatcherPanel.tsx", encoding="utf-8").read()
    assert "SL no wider than ${c.max_sl}%" in panel


def test_a_wide_stop_candidate_is_refused_in_a_real_pass(world):
    world["cands"] = [{**R6, "id": "WIDE0001", "sl": 3.0, "tp": 5.0}]
    got = sw.consider(now=NOW)
    assert not [d for d in got["decisions"] if d["action"] == "on"]
    assert not (world["settings"].get("watcher_slots") or {})


# ------------------------------------------------------------------------
# ONE WATCHER PER PROFILE (Sep 29, 2026): each room starts ON with its own
# rules, practice only until its live switch is on ("i want both, if i enable
# live trade, then it should be included").

def test_a_rooms_watcher_starts_on_with_that_rooms_rules(world):
    from tradingagents import profiles

    with profiles.using("B52662ED"):
        st = sw._read()
        assert st["mode"] == "act" and st["live"] is False
        cfg = sw.cfg_of(st)
        assert (cfg["on_winrate"], cfg["off_winrate"], cfg["min_trades"], cfg["max_sl"]) \
            == (70.0, 70.0, 50, 2.0)
        assert sw._state_path().parent.name == "B52662ED"
    assert sw._read() == {}, "Main's watcher is untouched"


def test_the_live_switch_arms_both_books_and_off_takes_real_back(world):
    from tradingagents import profiles

    with profiles.using("CC94D9FB"):
        st = sw._read()
        st["cfg"] = {}                       # R6 (100%, 20 trades) passes the defaults
        sw._write(st)
        sw.set_live(True)
        sw.consider(now=NOW)
        s = world["settings"]
        assert s["strategy_books"][SLOT] == ["paper", "real"]
        assert s["watcher_slots"][SLOT]["real"] is True
        sw.set_live(False)
        s = world["settings"]
        assert s["strategy_books"][SLOT] == ["paper"], "real money is taken back, practice stays"
        assert s["watcher_slots"][SLOT]["real"] is False


def test_a_real_row_the_watcher_armed_is_switched_off_by_the_same_rule(world):
    from tradingagents import profiles

    with profiles.using("CC94D9FB"):
        st = sw._read()
        st["cfg"] = {}
        sw._write(st)
        sw.set_live(True)
        sw.consider(now=NOW)
        world["fresh"]["77Y3BPFG"] = {**R6, "winrate": 60.0}
        got = sw.consider(now=NOW + 3601)
        assert [d["id"] for d in got["decisions"] if d["action"] == "off"] == ["77Y3BPFG"]
        assert SLOT not in (world["settings"].get("strategy_books") or {})


def test_a_real_row_you_armed_yourself_is_never_touched(world):
    world["settings"]["strategy_coins"] = {KEY: ["GPNSTOCK_USDT"]}
    world["settings"]["strategy_books"] = {SLOT: ["real", "paper"]}
    world["settings"]["strategy_res"] = {SLOT: "1m"}
    world["settings"]["watcher_slots"] = {SLOT: {"id": "77Y3BPFG", "coin": "GPNSTOCK",
                                                 "tf": "1h", "signal": "macddiv",
                                                 "th": 0.0, "sl": 0.7, "tp": 1.0}}
    world["fresh"]["77Y3BPFG"] = {**R6, "winrate": 10.0}
    got = sw.consider(now=NOW)
    assert not [d for d in got["decisions"] if d["action"] == "off"]
    assert world["settings"]["strategy_books"][SLOT] == ["real", "paper"]


def test_a_target_narrower_than_the_stop_is_its_own_rule():
    """Sep 29, 2026: "you can try sl greater than tp"."""
    import numpy as np

    from tradingagents import watcher_policy as wp
    from tradingagents import watcher_research as wr_

    cfg = {**wp.DEFAULTS, "tp_rule": "<", "max_sl": 0}
    row = {"tp": 1.0, "sl": 2.0, "winrate": 95.0, "trades": 30, "profit": 5.0, "gate": "ok"}
    assert wp.passes_on(row, cfg) == ""
    assert "not narrower" in wp.passes_on({**row, "tp": 2.0}, cfg)
    assert "not narrower" in wp.passes_on({**row, "tp": 3.0}, cfg)
    ok = wr_._tp_ok(np.array([1.0, 2.0, 3.0]), np.array([2.0, 2.0, 2.0]), "<")
    assert ok.tolist() == [True, False, False]
    assert wr_.loose([{**wr_.CURRENT, "tp_rule": "<"}, {**wr_.CURRENT, "tp_rule": ">"}])["tp_rule"] == "any"
    assert len(wr_.scenarios2()) == 120


# ------------------------------------------------------------------------
# NO LIMIT (operator, Sep 30, 2026: "i dont want a limit remove it", "if its
# millions then deploy all i dont care"). #B52662ED ran 7 rows while 5,000+
# passed its rules, because the day allowed 20 and the list stopped at 5,000.

def test_zero_means_no_limit_on_the_day_the_total_or_a_coin():
    from tradingagents import watcher_policy as wp

    cfg = {**wp.DEFAULTS, "max_new_per_day": 0, "max_slots": 0, "max_per_coin": 0}
    cands = [{**R6, "id": f"X{i:04d}", "coin": "GPNSTOCK"} for i in range(250)]
    got = wp.pick(cands, [], {}, NOW, cfg)
    assert len(got) == 250, "every row that passes, all on one coin"
    capped = wp.pick(cands, [], {}, NOW, dict(wp.DEFAULTS))
    assert len(capped) == 3, "the old defaults still mean what they said"


def test_with_no_limit_the_whole_list_is_read(monkeypatch):
    from tradingagents import watcher_candidates as wc

    pages = []

    def page(cfg, limit, offset):
        pages.append(offset)
        n = 12_345 - offset
        return [{"coin": "X", "tf": "1h", "signal": "s", "th": 0, "sl": 1, "tp": 2}] * max(0, min(limit, n))

    monkeypatch.setattr(wc, "_index_page", page)
    got = wc._index_rows({}, 0)
    assert len(got) == 12_345 and pages == [0, 5000, 10000]


def test_one_order_book_read_per_coin_per_pass(monkeypatch):
    calls = []

    class FX:
        def order_book(self, symbol):
            calls.append(("book", symbol))
            return {"asks": [], "bids": []}

        def book_cost(self, symbol, notional_usd=200.0):
            calls.append(("cost", symbol))
            return {"spread": 0.001}

    f = sw._PassFx()
    f._fx = FX()
    monkeypatch.setattr(sw.time, "sleep", lambda s: None)
    for _ in range(50):
        f.book_cost("VUG_USDT", 100.0)
        f.order_book("VUG_USDT")
    f.book_cost("XLI_USDT", 100.0)
    assert calls == [("cost", "VUG_USDT"), ("book", "VUG_USDT"), ("cost", "XLI_USDT")]


def test_every_new_room_starts_with_no_limit():
    from tradingagents import profiles

    for p in profiles.BUILTIN:
        if p["rules"]:
            assert (p["rules"]["max_new_per_day"], p["rules"]["max_slots"],
                    p["rules"]["max_per_coin"]) == (0, 0, 0), p["id"]


def test_raw_is_the_criteria_and_nothing_else():
    """Sep 30, 2026: "i want raw output, dont put any limit, you only need to
    serach a criteria in the table and deploy it"."""
    from tradingagents import watcher_policy as wp

    cfg = {**wp.DEFAULTS, "raw": True, "on_winrate": 70.0, "min_trades": 50,
           "tp_rule": ">", "max_sl": 2.0}
    row = {"tp": 2.0, "sl": 1.5, "winrate": 71.0, "trades": 55, "profit": -3.0, "gate": "warn"}
    assert wp.passes_on(row, cfg) == "", "a loss and a warned cost do not stop raw"
    assert wp.passes_on({**row, "winrate": 69.9}, cfg)
    assert wp.passes_on({**row, "trades": 49}, cfg)
    assert wp.passes_on({**row, "tp": 1.5}, cfg)
    assert wp.passes_on({**row, "sl": 2.5, "tp": 3.0}, cfg)
    cands = [{**R6, **row, "id": f"R{i}", "coin": "VUG"} for i in range(40)]
    assert len(wp.pick(cands, [], {f"R{i}": NOW for i in range(40)}, NOW, cfg)) == 40, \
        "no wait, no daily cap, no per-coin cap"


def test_raw_deploys_every_match_without_the_cost_pre_check(world, monkeypatch):
    many = [{**R6, "id": f"RAW{i:03d}", "coin": f"C{i}", "gate": "warn", "profit": -1.0}
            for i in range(30)]
    world["cands"] = many
    world["edge"] = {f"C{i}_USDT": "block" for i in range(30)}   # would refuse all
    st = sw._read()
    st["cfg"] = {"raw": True}
    sw._write(st)
    got = sw.consider(now=NOW)
    assert sum(d["action"] == "on" for d in got["decisions"]) == 30
    assert len(world["settings"]["watcher_slots"]) == 30


def test_a_used_up_day_stops_it_never_turns_into_no_limit(world):
    """0 means no limit, so 20 - 20 must not become it."""
    world["cands"] = [{**R6, "id": f"D{i:03d}", "coin": f"C{i}"} for i in range(60)]
    st = sw._read()
    st["cfg"] = {"max_new_per_day": 20, "max_per_coin": 3, "max_slots": 100}
    sw._write(st)
    got = sw.consider(now=NOW)
    assert sum(d["action"] == "on" for d in got["decisions"]) == 20


def test_raw_searches_at_any_hour():
    import datetime as dt

    morning = dt.datetime(2026, 9, 30, 9, 21).timestamp()
    yesterday = dt.datetime(2026, 9, 29, 16, 18).timestamp()
    assert not sw._on_due(morning, yesterday), "the old rule waited for noon"
    assert sw._on_due(morning, yesterday, raw=True)
    assert not sw._on_due(morning, morning - 60, raw=True), "still once a day"
