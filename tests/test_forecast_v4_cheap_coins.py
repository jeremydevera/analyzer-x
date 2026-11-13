"""A "cheap coins only" switch for Forecast v4's switch-on rules (Nov 13, 2026).

The operator asked how to profit more from Backtest v4; the check found costs are the whole loss (unseen
trades +$0.08 a trade before costs, -$1.06 after; coins at $0.25 or less a round trip -$0.22). Every rule
set is now also walked with a $0.25 cost cap, the way the 1.5% stop cap works, and the picker can hand a
room the capped version. Spec: docs/superpowers/specs/2026-11-13-cheap-coins-switch-design.md.

CHP 1h below pays $100 x (2 x 0.075% + 2 x 0.04%) = $0.23 a round trip; every other fixture strategy
pays $0.35 (slip 0.1%). One timeline with tests/test_forecast_v4.py."""
import sqlite3
from pathlib import Path

import numpy as np
import pytest

from tests.test_forecast_v4 import DAY, _line, _make, _pick, daily, ms
from tradingagents import forecast_v4 as f4, v4_picker, v4_store as v4

REPO = Path(__file__).resolve().parents[1]
CAP = 0.25


def _cheap():
    pick = _pick("ta_ma_pullback", 0.015, 0.03,
                 daily(ms(2026, 7, 1), ms(2026, 11, 4), lambda i: -0.5 if i % 5 == 4 else 1.0))
    line = _line("CHP", "1h", [pick], ms(2026, 10, 1))
    line["slip"] = 0.0004
    return {"CHP|1h": line}


@pytest.fixture()
def built(tmp_path, monkeypatch):
    return _make(tmp_path, monkeypatch, extra_taall=_cheap())


def find(window, wr, n, tf="", skill="", tp="any", cap=0.0, money="", cost=0.0):
    rid = f4.rule_id(window, wr, n, tp, cap, tf, skill, money, cost)
    rows = f4.rules_page({"q": rid})["rows"]
    assert rows, f"rule set {rid} not walked"
    return rows[0]


def _as_rule(r):
    return {"window": r["window"], "win_rate": r["min_win_rate"], "min_trades": r["min_trades"],
            "tp_rule": r["tp_rule"], "sl_cap": r["sl_cap"], "tf": r["tf"], "skill": r["skill"],
            "money": r["money"], "cost_cap": r["cost_cap"]}


def test_old_ids_never_change_and_a_capped_rule_has_its_own():
    assert f4.COST_CAPS == (0.0, CAP)
    assert f4.rule_id(30, 90, 20, "any", 0.0, "", "") == "D7EN8BNV"          # the rooms' own ids
    assert f4.rule_id(7, 80, 20, "any", 0.0, "", "") == "KK9SRY28"
    assert f4.rule_id(30, 80, 20, "any", 1.5, "", "", "", 0.0) == "RSS7CUKH"
    capped = f4.rule_id(30, 90, 20, "any", 0.0, "", "", "", CAP)
    assert capped != "D7EN8BNV" and len(capped) == 8
    assert "$0.25 or less" in f4.rule_words(30, 90, 20, "any", 0.0, "", "", "", CAP)
    assert "$0.25" not in f4.rule_words(30, 90, 20, "any", 0.0, "", "")


def test_a_capped_rule_switches_on_only_cheap_coins(built):
    capped = find(7, 50, 3, tf="1h", cost=CAP)
    plain = find(7, 50, 3, tf="1h")
    assert capped["cost_cap"] == CAP and plain["cost_cap"] == 0.0
    assert {t["coin"] for t in capped["top"]} == {"CHP"}
    assert {"AAA", "CHP"} <= {t["coin"] for t in plain["top"]}
    assert 0 < capped["trades"] < plain["trades"]
    assert "$0.25 or less" in capped["words"]


def test_switched_on_matches_the_walk_for_capped_rules(built):
    doc = f4.load()
    start, days = doc["walk"]["from_s"], doc["walk"]["days"]
    con = sqlite3.connect(v4.db_path())

    def opened(sid, lo, hi):
        rows = con.execute("SELECT en, pnl, why FROM trade WHERE sid=? AND en>=? AND en<?", (sid, lo, hi))
        return [p for _en, p, why in rows if why != f4.END_CODE]

    rules = [r for r in doc["rules"] if r["cost_cap"] == CAP and r["min_win_rate"] in (0, 50, 90)
             and r["min_trades"] in (3, 5) and not r["skill"]]
    assert len(rules) >= 10
    traded = 0
    for r in rules:
        n = profit = 0
        for d in range(days):
            at = start + d * DAY // 1000
            on = f4.switched_on(_as_rule(r), at)
            assert {s["coin"] for s in on} <= {"CHP"}, r["id"]
            for s in on:
                got = opened(s["sid"], at, at + DAY // 1000)
                n += len(got)
                profit += sum(got)
        assert n == r["trades"], (r["id"], n, r["trades"])
        assert round(profit, 4) == pytest.approx(r["profit"], abs=1e-3), r["id"]
        traded += 1 if n else 0
    con.close()
    assert traded >= 5


def test_an_unknown_cost_is_never_cheap(built):
    con = sqlite3.connect(v4.db_path())
    con.execute("UPDATE strat SET slip = NULL WHERE coin = 'CHP'")
    con.commit()
    con.close()
    f4._CACHE.update(key=None, doc=None)
    f4.build(log=lambda *_: None)
    # CHP was the only cheap coin: with its cost unknown no strategy is cheap, so no capped rule set exists
    assert not [r for r in f4.load()["rules"] if r["cost_cap"]]
    rule = {"window": 7, "win_rate": 50, "min_trades": 3, "tp_rule": "any", "sl_cap": 0.0, "tf": "1h",
            "skill": "", "money": "", "cost_cap": CAP}
    at = ms(2026, 10, 15) // 1000
    assert f4.switched_on(rule, at) == []
    assert {s["coin"] for s in f4.switched_on({**rule, "cost_cap": 0.0}, at)} >= {"CHP"}
    assert find(7, 50, 3, tf="1h")["trades"] > 0            # the uncapped rule still trades CHP


def test_a_capped_twin_is_listed_as_the_capped_rule_it_equals(built):
    """Every capped kind here switches on the same one strategy (CHP): listed once, and each twin points
    at a CAPPED rule set, never at an uncapped one."""
    doc = f4.load()
    by_id = {r["id"]: r for r in doc["rules"]}
    for tf, sk in (("1h", "technical-analysis"), ("1h", ""), ("", "technical-analysis")):
        twin = f4.rule_id(7, 50, 3, "any", 0.0, tf, sk, "", CAP)
        listed = by_id[doc["same_as"][twin]]
        assert listed["cost_cap"] == CAP and {t["coin"] for t in listed["top"]} == {"CHP"}, (tf, sk)
    plain = f4.rule_id(7, 50, 3, "any", 0.0, "1h", "technical-analysis", "", 0.0)
    assert by_id.get(doc["same_as"].get(plain, plain), {}).get("cost_cap", 0.0) == 0.0


def test_the_page_filters_by_coin_cost_on_the_server(built):
    doc = f4.load()
    cheap = f4.rules_page({"cost": "cheap", "traded": False, "page": 1})
    plain = f4.rules_page({"cost": "none", "traded": False, "page": 1})
    assert cheap["total"] == sum(1 for r in doc["rules"] if r["cost_cap"] == CAP) > 0
    assert plain["total"] == sum(1 for r in doc["rules"] if not r["cost_cap"]) > 0
    assert all(r["cost_cap"] == CAP for r in cheap["rows"]) and all(not r["cost_cap"] for r in plain["rows"])
    assert any("$0.25 or less" in x for x in cheap["filters"])


def test_the_calendar_list_equals_its_box_for_capped_rules(built):
    doc = f4.load()
    folder, index, pos = f4._walk_files(doc)
    D = index["D"]
    t = f4._filed(folder, index, 0, index["rows"])
    offsets = np.array(index["offsets"])
    day = np.searchsorted(offsets, np.arange(index["rows"]), side="right") - 1
    p4 = f4._read(folder, index, "p4").astype(np.int64)
    checked = 0
    for r in doc["rules"]:
        if r["cost_cap"] != CAP:
            continue
        m = f4._takes(t, r)
        i = pos[r["id"]]
        assert (np.bincount(day[m], minlength=D) == f4._read(folder, index, "days_trades", i * D, D)).all()
        assert np.allclose(np.bincount(day[m], weights=p4[m], minlength=D) / 10_000,
                           f4._read(folder, index, "days_profit", i * D, D), atol=1e-6)
        checked += bool(r["trades"])
    assert checked >= 5


def test_a_calendar_folder_from_before_the_cap_is_not_read(built):
    doc = f4.load()
    folder = f4.out_path().parent / doc["walk_dir"]
    p = folder / "index.json"
    import json
    idx = json.loads(p.read_text(encoding="utf-8"))
    idx["format"] = 1
    p.write_text(json.dumps(idx), encoding="utf-8")
    f4._WALK_IDX.update(key=None)
    got = f4.rule_days(find(7, 50, 3, tf="1h", cost=CAP)["id"])
    assert got["days"] == {} and "next build" in got["why"]


def test_the_picker_carries_the_cap_to_the_rooms_list(built):
    doc = f4.load()
    rec = next(r for r in doc["rules"] if r["cost_cap"] == CAP and r["trades"])
    rule = v4_picker._rule_of(rec)
    assert rule["cost_cap"] == CAP and f4.rule_id(**rule) == rec["id"]
    plain = next(r for r in doc["rules"] if not r["cost_cap"] and r["trades"])
    assert f4.rule_id(**v4_picker._rule_of(plain)) == plain["id"]


def test_the_lab_counts_a_capped_kind_on_its_own():
    src = (REPO / "tradingagents/v4_picker_lab.py").read_text(encoding="utf-8")
    assert 'float(rule["sl_cap"]), float(rule.get("cost_cap") or 0.0))' in src


def test_the_page_has_a_coin_cost_filter_sent_to_the_server():
    page = (REPO / "webapp/src/components/forecast/ForecastV4.tsx").read_text(encoding="utf-8")
    api = (REPO / "tradingagents/api.py").read_text(encoding="utf-8")
    assert 'aria-label="coin cost"' in page and "cost: f.cost" in page
    assert '"cost": cost' in api
