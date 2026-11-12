"""The daily picker: the three skill rooms follow the best rule sets of the month, and a room whose
rule stopped working is replaced or switched off, by itself (operator, Nov 12, 2026: "i will not
manually search for best switch on and deploy and undeploy what is not working").

Every record here is built with `forecast_v4.rule_id`, so a rule set's id is the real one, and the
tests run on ONE timeline: `NOW` is the day the pass runs, and each practice trade is stamped
relative to it - a trade older than the 30 days the picker reads never counts.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tradingagents import forecast_v4 as f4
from tradingagents import profiles, v4_daily, v4_picker as vp

NOW = 1_794_500_000.0          # Nov 12, 2026, the pass's own clock
DAY = 86_400

ROOMS = ("D7EN8BNV", "RSS7CUKH", "7T3VJU82")


def _rule(win=80, n=20, tf="", sl=0.0, skill="", money="", window=30):
    return {"window": window, "win_rate": win, "min_trades": n, "tp_rule": "any", "sl_cap": sl,
            "tf": tf, "skill": skill, "money": money}


def _rec(rule: dict, *, rank=20.0, profit=None, trades=None, wins=None, luck=False, thin=False,
         month_now=10.0, month_trades=60) -> dict:
    # different rule sets get different results unless a test says they are twins - the picker
    # (rightly) treats identical results as one bet
    seed = (rule["win_rate"] * 3 + rule["min_trades"] + int(rule["sl_cap"] * 10) + len(rule["tf"]) * 5
            + len(rule["skill"]) * 7 + (50 if rule["money"] else 0))
    trades = 500 + seed if trades is None else trades
    wins = 330 + seed if wins is None else wins
    profit = 300.0 + seed if profit is None else profit
    return {"id": f4.rule_id(**rule), "window": rule["window"], "min_win_rate": rule["win_rate"],
            "min_trades": rule["min_trades"], "money": rule["money"], "tp_rule": rule["tp_rule"],
            "sl_cap": rule["sl_cap"], "tf": rule["tf"], "skill": rule["skill"],
            "trades": trades, "wins": wins, "profit": profit, "rank": rank, "luck": luck,
            "words": "x", "predicted": {"thin": thin},
            "months": [{"profit": 40.0, "trades": 200}, {"profit": 50.0, "trades": 200},
                       {"profit": month_now, "trades": month_trades}]}


def _doc(*recs, same_as=None) -> dict:
    return {"rules": list(recs), "same_as": same_as or {}}


@pytest.fixture(autouse=True)
def _sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(profiles, "PICKER_PATH", tmp_path / "picker.json")
    monkeypatch.setattr(vp, "_bell", lambda line: BELLS.append(line))
    BELLS.clear()
    yield


BELLS: list = []


def _the_three():
    """The records of the three rooms' own rules, all good."""
    return [_rec(profiles.get(pid)["v4_rule"] | {"money": ""}, rank=20.0 + i) for i, pid in enumerate(ROOMS)]


def _no_practice(pid):
    return []


# ---------------------------------------------------------------- what "performing well" means
def test_a_rule_set_is_good_only_when_every_check_passes():
    base = _rec(_rule())
    assert vp.judge(base) == (True, "")
    cases = {
        "only 40 trades": {**base, "trades": 40},
        "luck": {**base, "luck": True},
        "fewer than 3 whole months": {**base, "predicted": {"thin": True}},
        "a whole month lost money": {**base, "rank": -3.5},
        "lost over the days walked": {**base, "profit": -2.0},
        "the month so far is losing": {**base, "months": [{"profit": 40.0, "trades": 90}, {"profit": -6.4, "trades": 60}]},
    }
    for words, rec in cases.items():
        ok, why = vp.judge(rec)
        assert not ok and words.split()[0] in why or not ok, (words, why)
        assert not ok, words
    assert vp.judge(None)[0] is False


def test_a_month_that_has_barely_begun_cannot_fail_a_rule_set():
    """On the 2nd of a month one losing trade is not "performing badly": every room would be
    switched off at every month start."""
    few = _rec(_rule(), month_now=-1.2, month_trades=3)
    assert vp.judge(few) == (True, "")
    assert vp.judge(_rec(_rule(), month_now=-1.2, month_trades=vp.MONTH_MIN_TRADES))[0] is False


def test_twins_with_the_same_results_are_one_bet_and_the_plainer_one_is_kept():
    a = _rec(_rule(), rank=22.67, profit=377.37, trades=1207, wins=798)
    twin = _rec(_rule(skill="technical-analysis"), rank=22.67, profit=377.37, trades=1207, wins=798)
    other = _rec(_rule(win=90), rank=18.0, profit=227.0, trades=511, wins=400)
    got = vp.candidates(_doc(twin, a, other))
    assert [r["id"] for r in got] == [a["id"], other["id"]]      # one of the twins, the one with no filter


def test_a_twin_listed_under_same_as_is_found():
    a = _rec(_rule())
    twin_id = f4.rule_id(**_rule(n=30))
    assert vp.resolve(_doc(a, same_as={twin_id: a["id"]}), twin_id)["id"] == a["id"]
    assert vp.resolve(_doc(a), "ZZZZZZZZ") is None


# ---------------------------------------------------------------- the pass
def test_a_first_pass_with_every_rule_good_changes_nothing_but_writes_its_record(tmp_path):
    res = vp.pick(NOW, doc=_doc(*_the_three()), ledger_of=_no_practice)
    assert res["first"] and res["log"] == [] and not BELLS
    st = json.loads((tmp_path / "picker.json").read_text(encoding="utf-8"))
    assert {p: st["slots"][p]["rule_id"] for p in ROOMS} == {p: p for p in ROOMS}
    assert not any(s["off"] for s in st["slots"].values())


def test_a_room_whose_rule_stopped_working_takes_the_best_good_rule_set(tmp_path):
    three = _the_three()
    three[0] = _rec(profiles.get("D7EN8BNV")["v4_rule"] | {"money": ""}, rank=-4.0)         # D7EN8BNV lost a month
    best = _rec(_rule(money="pf15"), rank=22.7, profit=377.0, trades=1207, wins=798)         # the new leader
    res = vp.pick(NOW, doc=_doc(*three, best), ledger_of=_no_practice)
    assert res["slots"]["D7EN8BNV"]["rule_id"] == best["id"]
    assert profiles.v4_rule("D7EN8BNV")["money"] == "pf15"           # the follower and the lists read it
    assert profiles.rule_name("D7EN8BNV") == f"#{best['id']}"        # the tab says it
    assert not profiles.picker_off("D7EN8BNV")
    assert res["slots"]["RSS7CUKH"]["rule_id"] == "RSS7CUKH"         # the others are untouched
    assert len(BELLS) == 1 and best["id"] in BELLS[0]["text"] and "D7EN8BNV" in BELLS[0]["text"]


def test_a_room_with_nothing_to_take_is_switched_off_and_loses_its_tab():
    three = _the_three()
    three[1] = _rec(profiles.get("RSS7CUKH")["v4_rule"] | {"money": ""}, month_now=-8.0)     # losing this month
    res = vp.pick(NOW, doc=_doc(*three), ledger_of=_no_practice)
    assert res["slots"]["RSS7CUKH"]["off"] is True
    assert profiles.picker_off("RSS7CUKH") and profiles.retired("RSS7CUKH")
    assert "RSS7CUKH" not in profiles.shown() and "D7EN8BNV" in profiles.shown()
    assert len(BELLS) == 1 and "switched off" in BELLS[0]["text"]
    # said once: the next quiet day says nothing and writes nothing
    before = profiles.picker_state()["last_pass_s"]
    res2 = vp.pick(NOW + DAY, doc=_doc(*three), ledger_of=_no_practice)
    assert res2["changed"] is False and len(BELLS) == 1
    assert profiles.picker_state()["last_pass_s"] == before


def test_a_switched_off_room_comes_back_the_day_its_rule_passes_again():
    bad = _the_three()
    bad[1] = _rec(profiles.get("RSS7CUKH")["v4_rule"] | {"money": ""}, month_now=-8.0)
    vp.pick(NOW, doc=_doc(*bad), ledger_of=_no_practice)
    assert profiles.picker_off("RSS7CUKH")
    vp.pick(NOW + DAY, doc=_doc(*_the_three()), ledger_of=_no_practice)
    assert not profiles.picker_off("RSS7CUKH") and "RSS7CUKH" in profiles.shown()
    assert any("back on" in b["text"] for b in BELLS)


def test_a_switched_off_room_takes_a_new_rule_set_when_one_passes():
    bad = _the_three()
    bad[2] = _rec(profiles.get("7T3VJU82")["v4_rule"] | {"money": ""}, rank=-1.0)
    vp.pick(NOW, doc=_doc(*bad), ledger_of=_no_practice)
    assert profiles.picker_off("7T3VJU82")
    fresh = _rec(_rule(win=70, n=30), rank=15.0)
    vp.pick(NOW + DAY, doc=_doc(*bad, fresh), ledger_of=_no_practice)
    assert not profiles.picker_off("7T3VJU82") and profiles.rule_name("7T3VJU82") == f"#{fresh['id']}"


def test_a_room_that_still_passes_is_never_swapped_for_a_slightly_better_one():
    three = _the_three()
    better = _rec(_rule(win=70, n=30), rank=99.0, profit=999.0)
    vp.pick(NOW, doc=_doc(*three, better), ledger_of=_no_practice)
    assert [profiles.rule_name(p) for p in ROOMS] == [f"#{p}" for p in ROOMS]
    assert not BELLS


def test_two_rooms_never_follow_the_same_bet():
    three = _the_three()
    three[0] = _rec(profiles.get("D7EN8BNV")["v4_rule"] | {"money": ""}, rank=-4.0)
    three[1] = _rec(profiles.get("RSS7CUKH")["v4_rule"] | {"money": ""}, rank=-4.0)
    a = _rec(_rule(money="pf15"), rank=22.7, profit=377.0, trades=1207, wins=798)
    twin = _rec(_rule(skill="technical-analysis", money="pf15"), rank=22.7, profit=377.0, trades=1207, wins=798)
    vp.pick(NOW, doc=_doc(*three, a, twin), ledger_of=_no_practice)
    now_on = {p: profiles.rule_name(p) for p in ROOMS}
    assert sorted(now_on.values()).count(f"#{a['id']}") + sorted(now_on.values()).count(f"#{twin['id']}") == 1
    assert profiles.picker_off("RSS7CUKH") or profiles.picker_off("D7EN8BNV")       # nothing else passes


def test_practice_that_loses_money_overrules_a_green_backtest():
    three = _the_three()
    losing = [{"action": "exit", "dry_run": True, "ts": NOW - DAY, "pnl_est": -1.0} for _ in range(12)]
    ledger = lambda pid: losing if pid == "D7EN8BNV" else []            # noqa: E731
    sub = _rec(_rule(win=70, n=30), rank=15.0)
    res = vp.pick(NOW, doc=_doc(*three, sub), ledger_of=ledger)
    assert res["slots"]["D7EN8BNV"]["rule_id"] == sub["id"]
    assert "practice lost -12.00" in res["slots"]["D7EN8BNV"]["why"]


def test_practice_is_not_judged_on_a_handful_of_trades_or_old_ones():
    few = [{"action": "exit", "dry_run": True, "ts": NOW - DAY, "pnl_est": -5.0} for _ in range(9)]
    old = [{"action": "exit", "dry_run": True, "ts": NOW - 40 * DAY, "pnl_est": -5.0} for _ in range(30)]
    assert vp.practice("D7EN8BNV", 0, NOW, lambda p: few)[0] is True
    assert vp.practice("D7EN8BNV", 0, NOW, lambda p: old)[0] is True
    since = [{"action": "exit", "dry_run": True, "ts": NOW - 5 * DAY, "pnl_est": -1.0} for _ in range(12)]
    assert vp.practice("D7EN8BNV", NOW - DAY, NOW, lambda p: since)[0] is True     # before this rule's switch-on
    assert vp.practice("D7EN8BNV", 0, NOW, lambda p: since)[0] is False


def test_a_missing_forecast_leaves_every_room_alone_and_a_switched_off_picker_does_nothing(tmp_path):
    assert "no rule sets" in vp.pick(NOW, doc={}, ledger_of=_no_practice)["skipped"]
    assert not (tmp_path / "picker.json").exists()
    vp.pick(NOW, doc=_doc(*_the_three()), ledger_of=_no_practice)
    vp.set_enabled(False)
    bad = _the_three()
    bad[0] = _rec(profiles.get("D7EN8BNV")["v4_rule"] | {"money": ""}, rank=-4.0)
    assert vp.pick(NOW + DAY, doc=_doc(*bad), ledger_of=_no_practice)["skipped"] == "the picker is switched off"
    assert profiles.rule_name("D7EN8BNV") == "#D7EN8BNV"             # kept what it follows


# ---------------------------------------------------------------- the rooms read it
def test_with_no_picker_record_every_room_follows_its_own_rule():
    assert profiles.picker_state() == {}
    for pid in ROOMS:
        assert f4.rule_id(**profiles.v4_rule(pid)) == pid and profiles.rule_name(pid) == f"#{pid}"
    assert [p for p in profiles.shown() if p != "main"] == list(ROOMS)   # the suite un-retires `main` for its own tests


def test_an_unreadable_record_is_no_record(tmp_path):
    (tmp_path / "picker.json").write_text("{not json", encoding="utf-8")
    assert profiles.picker_state() == {} and profiles.v4_rule("D7EN8BNV")["win_rate"] == 90


def test_the_tab_and_the_follow_payload_say_the_rule_followed_today():
    from tradingagents import api

    three = _the_three()
    three[0] = _rec(profiles.get("D7EN8BNV")["v4_rule"] | {"money": ""}, rank=-4.0)
    best = _rec(_rule(money="pf15"), rank=22.7, profit=377.0, trades=1207, wins=798)
    vp.pick(NOW, doc=_doc(*three, best), ledger_of=_no_practice)
    rooms = {r["id"]: r for r in api.trade_profiles()["profiles"]}
    assert rooms["D7EN8BNV"]["name"] == f"#{best['id']}" and rooms["D7EN8BNV"]["slot"] == "#D7EN8BNV"
    assert rooms["D7EN8BNV"]["picker"]["rule_id"] == best["id"]
    assert "pf15" not in rooms["D7EN8BNV"]["rule_words"] and "$1.50" in rooms["D7EN8BNV"]["rule_words"]
    assert rooms["RSS7CUKH"]["name"] == "#RSS7CUKH"


def test_a_switched_off_room_has_no_tab_in_the_rooms_answer():
    from tradingagents import api

    bad = _the_three()
    bad[1] = _rec(profiles.get("RSS7CUKH")["v4_rule"] | {"money": ""}, month_now=-8.0)
    vp.pick(NOW, doc=_doc(*bad), ledger_of=_no_practice)
    got = [r["id"] for r in api.trade_profiles()["profiles"] if r["id"] != "main"]
    assert got == ["D7EN8BNV", "7T3VJU82"]


def test_a_switched_off_rooms_past_trades_stay_in_the_main_tabs_list():
    bad = _the_three()
    bad[1] = _rec(profiles.get("RSS7CUKH")["v4_rule"] | {"money": ""}, month_now=-8.0)
    vp.pick(NOW, doc=_doc(*bad), ledger_of=_no_practice)
    assert "RSS7CUKH" not in profiles.shown() and "RSS7CUKH" in profiles.history_rooms()
    assert "55D32617" not in profiles.history_rooms()          # a room retired by hand stays out
    src = Path(__import__("tradingagents.api", fromlist=["x"]).__file__).read_text(encoding="utf-8")
    assert "rooms = _pf.history_rooms()" in src


# ---------------------------------------------------------------- the daily chain
def test_the_pick_runs_before_the_days_list_and_a_switched_off_room_gets_an_empty_list():
    src = Path(v4_daily.__file__).read_text(encoding="utf-8")
    lists = src[src.index("def _lists("):src.index("def _agreed_days")]
    assert lists.index("_pick(st, now)") < lists.index("f4.switched_on(") < lists.index("f2.publish(")
    assert "[] if profiles.picker_off(pid) else f4.switched_on(" in lists


def test_a_picker_that_fails_never_stops_the_day_and_says_so(monkeypatch):
    def boom(*a, **k):
        raise OSError("disk")

    monkeypatch.setattr(vp, "pick", boom)
    st: dict = {}
    v4_daily._pick(st, NOW)
    assert "could not run (OSError: disk)" in st["picker_error"] and "keeps its rule" in st["picker_error"]
    assert "could not run" in v4_daily._notes(st)


# ---------------------------------------------------------------- the screen
def test_the_screen_names_the_rule_hides_an_off_room_and_explains_the_picker():
    web = Path(__file__).resolve().parents[1] / "webapp/src"
    s = (web / "components/trade/AutoTradeScreen.tsx").read_text(encoding="utf-8")
    assert "PROFILES.filter(onScreen).map(" in s and "{tabName(p)}" in s
    assert "!rooms || rooms.some((x) => x.id === p.id)" in s
    assert "pick(ALL_ROOMS)" in s[s.index("const onScreen"):s.index("const waitlist")]
    assert "picked by the daily picker" in s
    f = (web / "components/trade/V4FollowPanel.tsx").read_text(encoding="utf-8")
    assert "The daily picker gave this room" in f and "d.picker" in f
