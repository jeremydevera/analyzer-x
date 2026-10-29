"""The Backtest v3 verdict store (tradingagents/v3_verdicts.py, Part 2b) and
the tab's tested-ideas list that reads it (`v3_page.tested`): a collected run
judged pooled under the plan it was DISPATCHED with, every verdict kept with
what it was judged under and every coin it did not judge named, each verdict's
stop and target sizes read from its trade rows, and the tab saying - from the
store's own numbers - when it is a pilot and not the proof."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import tests.test_v3_proof as tp
from tradingagents import (
    v3_cloud as vc,
    v3_page as vpg,
    v3_proof as vp,
    v3_research as vrs,
    v3_universe as vu,
    v3_verdicts as vv,
)

DAY = 86_400_000


def _plan(coins, end=tp.PLAN_END):
    plan = {"version": vu.VERSION, "venue": "Gate", "start_ms": end - 365 * DAY, "end_ms": end,
            "coins": sorted(coins), "months": [], "liquid": {}, "calm": {}}
    plan["id"] = vu.plan_id(plan)
    return plan


def _eight(rows, stop=0.007, target=0.0067):
    return [r + [stop, target] for r in rows]


def _record(coin, plan, unseen, risk=5.0):
    """A coin's record of the snap family on 1h with no filter: k1.5 +0.05 a trade on the
    older days, k2 +0.10 (k2 is chosen), `unseen` k2's unseen trades, the random runs quiet."""
    walk = tp._walk
    return {"version": 2, "coin": coin, "kind": "metals", "plan_id": plan["id"],
            "plan_end_ms": plan["end_ms"], "risk_usd": risk, "runs": 200,
            "unseen_months": ["2026-07", "2026-08", "2026-09", "2026-10"],
            "windows": {"1h": {"split": "Jul 25, 2026", "end": "Oct 23, 2026",
                               "older_candles": 6600, "unseen_candles": 2160}},
            "combos": {tp.KEY15: {"older": walk(_eight(tp._rows([0.05] * 40))),
                                  "unseen": walk([]), "random": [[0, 0.0]] * 200},
                       tp.KEY: {"older": walk(_eight(tp._rows([0.10] * 40))),
                                "unseen": walk(unseen), "random": tp.QUIET}},
            "skipped": {}, "machine": {"repo": "a/x"}}


@pytest.fixture()
def run(monkeypatch, tmp_path):
    return make_run(monkeypatch, tmp_path)


def make_run(monkeypatch, tmp_path):
    """A collected run "pilot" of 2 of the plan's 4 coins, its plan kept beside the state
    (tests/test_v3_results_page.py builds its page from this run too)."""
    monkeypatch.setattr(vc, "home", lambda: tmp_path / "cloud")
    monkeypatch.setattr(vrs, "home", lambda label="local": tmp_path / "research"
                        / vrs.plain_label(label))
    monkeypatch.setattr(vv, "store_path", lambda: tmp_path / "v3" / "verdicts.json")
    monkeypatch.setattr(vv, "history_dir", lambda: tmp_path / "v3" / "verdicts")
    (tmp_path / "cloud").mkdir()
    plan = _plan(["XAU_USDT", "XAG_USDT", "XPT_USDT", "EURUSD_USDT"])
    copy = vu.save(plan, tmp_path / "cloud" / "pilot.plan.json")
    state = {"name": "pilot", "label": "pilot", "folder": "pilot", "plan_id": plan["id"],
             "plan_copy": str(copy), "risk_usd": 5.0, "runs_per_combo": 200,
             "board": ["XAU_USDT", "XAG_USDT", "XPT_USDT"]}
    (tmp_path / "cloud" / "pilot.json").write_text(json.dumps(state), encoding="utf-8")
    (tmp_path / "cloud" / "pilot-collected.json").write_text(json.dumps(
        {"runs": {"a/x": 11, "b/x": 12}, "not_reached": [], "left_out": [],
         "failed": ["XPT_USDT: ConnectionError: cut"], "refused_records": [],
         "machines_refused": []}), encoding="utf-8")
    # 400 unseen trades over the two coins: +0.30 a trade, each its own stop and target
    unseen = tp._rows([0.30] * 400, per_day=5)
    folder = vrs.home("pilot")
    vrs.save_coin(folder, _record("XAU_USDT", plan, _eight(unseen[:200], 0.004, 0.006)))
    vrs.save_coin(folder, _record("XAG_USDT", plan, _eight(unseen[200:], 0.010, 0.012)))
    return SimpleNamespace(plan=plan, tmp=tmp_path, folder=folder)


def test_publish_judges_the_run_under_the_plan_it_was_dispatched_with(run):
    path = vv.publish("pilot", now=1_793_000_000.0)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["plan_id"] == run.plan["id"] and data["coins"] == ["XAG_USDT", "XAU_USDT"]
    assert (data["risk_usd"], data["runs"], data["tried"]) == (5.0, 200, vp.TRIED)
    assert data["github_runs"] == {"a/x": 11, "b/x": 12} and data["plan_coins"] == 4
    snap = next(v for v in data["verdicts"] if v["id"] == vp.verdict(
        "v3_snap", "1h", "none", vrs.load_coins(run.folder))["id"])
    assert snap["setting"] == "k2" and snap["unseen"]["trades"] == 400
    assert len(data["verdicts"]) == len(vp.verdicts([]))       # every judged group, 27


def test_every_verdict_is_kept_with_every_coin_it_did_not_judge_named(run):
    vv.publish("pilot", now=1_793_000_000.0)
    vv.publish("pilot", now=1_793_000_100.0)
    kept = sorted(p.name for p in (run.tmp / "v3" / "verdicts").iterdir())
    assert kept == ["pilot-1793000000.json", "pilot-1793000100.json"], "nothing deletes one"
    data = json.loads((run.tmp / "v3" / "verdicts.json").read_text(encoding="utf-8"))
    nj = data["not_judged"]
    assert nj["failed"] == ["XPT_USDT: ConnectionError: cut"]
    assert nj["not_dispatched"] == ["EURUSD_USDT"], "a pilot names the coins it never sent"


def test_levels_are_the_chosen_settings_unseen_stops_and_targets(run):
    data = json.loads(vv.publish("pilot").read_text(encoding="utf-8"))
    snap = next(v for v in data["verdicts"] if v["family"] == "v3_snap" and v["tf"] == "1h"
                and v["filter"] == "none")
    # 200 trades at a 0.4% stop and 200 at 1.0%: least, median, most
    assert snap["levels"] == {"stop": [0.004, pytest.approx(0.007), 0.01],
                              "target": [0.006, pytest.approx(0.009), 0.012], "trades": 400}
    chose = next(v for v in data["verdicts"] if v["failed"] == "choose")
    assert chose["levels"] == {"stop": None, "target": None, "trades": 0}


def test_a_record_of_another_risk_is_named_and_never_pooled(run):
    vrs.save_coin(run.folder, _record("XPT_USDT", run.plan, [], risk=1.0))
    data = json.loads(vv.publish("pilot").read_text(encoding="utf-8"))
    assert "XPT_USDT" not in data["coins"]
    assert data["not_judged"]["other_records"] == ["XPT_USDT: risk $1.00, not $5.00"]


def test_a_plan_copy_that_is_not_the_runs_plan_is_refused(run):
    state = json.loads((run.tmp / "cloud" / "pilot.json").read_text(encoding="utf-8"))
    vu.save(_plan(["BTC_USDT"]), state["plan_copy"])
    with pytest.raises(ValueError, match="the run was dispatched with"):
        vv.publish("pilot")


def test_the_tab_lists_every_stored_verdict_and_says_a_pilot_is_not_the_proof(run):
    path = vv.publish("pilot", now=1_793_000_000.0)
    t = vpg.tested(path, check_file=run.tmp / "none.json")
    assert t["state"] == "stored" and t["rows"] == len(t["store"]["verdicts"])
    s = t["store"]
    assert s["tried"] == vp.TRIED and s["plan_coins"] == 4 and len(s["coins"]) == 2
    assert s["not_judged"] == {"failed": 1, "not_dispatched": 1}
    # the sentence is the store's own count, never typed
    passed = sum(1 for r in s["verdicts"] if r["passed"])
    assert t["words"].startswith(f"{passed} of {len(s['verdicts'])} judged ideas passed")
    assert "on 2 of the plan's 4 coins - a pilot of the machinery, not the proof" in t["words"]
    snap = next(r for r in s["verdicts"] if r["family"] == "v3_snap" and r["tf"] == "1h"
                and r["filter"] == "none")
    # the kit's columns: the rules in words, their sizes, leverage, trades a day
    assert snap["target"].startswith("the 20-candle average at the signal, resting")
    assert snap["stop"].startswith("an emergency stop 3 x ATR(20)")
    assert snap["stop_pct"] == "0.70% (0.40%-1.00%)" and snap["lev"] == "20x-20x"
    assert snap["per_day"] == round(400 / 90, 2) and snap["trades"] == 400
    for row in s["verdicts"]:
        for k, v in row.items():
            assert v is not None or row["blank"], f"{row['id']} {k} is empty with no reason"


def test_an_unreadable_store_says_so_and_none_says_nothing_has_run(tmp_path):
    bad = tmp_path / "verdicts.json"
    bad.write_text("{not json", encoding="utf-8")
    t = vpg.tested(bad, check_file=tmp_path / "none.json")
    assert t["state"] == "unreadable" and str(bad) in t["words"] and t["store"] is None
    t = vpg.tested(tmp_path / "absent.json", check_file=tmp_path / "none.json")
    assert t["state"] == "not_run" and t["store"] is None and "not run yet" in t["words"]


def test_the_tabs_list_prints_the_kits_columns_and_derives_its_heading():
    root = Path(__file__).resolve().parent.parent / "webapp" / "src" / "components" / "backtest-v3"
    src = (root / "V3Check.tsx").read_text(encoding="utf-8")
    for label in ('"ID"', "PROFIT (total $)", "Target (TP rule)", "Target size", "Stop (SL rule)",
                  "Stop size", '"Leverage"', "Unseen trades", "Trades a day", "Won / lost",
                  "Worst losing run"):
        assert label in src, label
    # the heading and the combinations come from the store, never typed
    assert "Pilot — ${coins.length} of the plan's ${planCoins} coins, not the proof" in src
    assert "combinations tried" in src and "check.tried" in src
    runner = (root / "V3Runner.tsx").read_text(encoding="utf-8")
    assert 'kind="stored"' in runner and "opts.tested.store" in runner
