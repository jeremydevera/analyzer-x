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
    assert kept == ["pilot-1793000000000.json", "pilot-1793000100000.json"], "nothing deletes one"
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
    assert snap["stop_pct"] == "0.70% (0.40%-1.00%)" and snap["lev"] == "20x", "one leverage: 20x (M6)"
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


# ---------------------------------------------------------------- fix round 1 (review of f2eb1bbbb6ba)

def _state(tmp, name, board, *, plan, dealt=None, refused=(), runs=None, label=None):
    """A run's state beside the plan copy `make_run` wrote (a redo keeps its own state)."""
    runs = runs or {"a/x": {"run": 21, "coins": len(board), "label": name}}
    st = {"name": name, "label": label or name, "folder": "pilot", "plan_id": plan["id"],
          "plan_copy": str(tmp / "cloud" / "pilot.plan.json"), "risk_usd": 5.0,
          "runs_per_combo": 200, "coins": len(board), "board": list(board), "runs": runs,
          "refused": list(refused), "dealt": dealt or {}}
    (tmp / "cloud" / f"{name}.json").write_text(json.dumps(st), encoding="utf-8")
    return st


def _collected(tmp, name, **kw):
    base = {"name": name, "runs": {"a/x": 21}, "landed": [], "not_reached": [], "failed": [],
            "left_out": [], "unmeasured": [], "refused_records": [], "machines_refused": [],
            "shares_refused": [], "downloads_failed": []}
    base.update(kw)
    (tmp / "cloud" / f"{name}-collected.json").write_text(json.dumps(base), encoding="utf-8")


def _full_run(monkeypatch, tmp_path):
    """A run dispatched with the WHOLE plan (9 coins, 4 accounts): 2 coins judged, and every other
    coin in the one bucket that is true."""
    make_run(monkeypatch, tmp_path)
    coins = ["XAU_USDT", "XAG_USDT", "XPT_USDT", "EURUSD_USDT", "GBPUSD_USDT", "AAA_USDT",
             "BBB_USDT", "CCC_USDT", "DDD_USDT"]
    plan = _plan(coins)
    vu.save(plan, tmp_path / "cloud" / "pilot.plan.json")
    folder = vrs.home("pilot")
    vrs.save_coin(folder, _record("XAU_USDT", plan, _eight(tp._rows([0.30] * 200, per_day=5))))
    vrs.save_coin(folder, _record("XAG_USDT", plan, _eight(tp._rows([0.30] * 200, per_day=5))))
    dealt = {"a/x": {"coin_list": "XAU_USDT,XAG_USDT,XPT_USDT,EURUSD_USDT,GBPUSD_USDT"},
             "b/x": {"coin_list": "AAA_USDT,BBB_USDT"}, "c/x": {"coin_list": "CCC_USDT"},
             "d/x": {"coin_list": "DDD_USDT"}}
    _state(tmp_path, "pilot", coins, plan=plan, dealt=dealt,
           refused=["c/x: HTTP 422 no workflow"])
    _collected(tmp_path, "pilot", landed=["XAG_USDT", "XAU_USDT"],
               failed=["XPT_USDT: ConnectionError: cut"],
               unmeasured=["EURUSD_USDT: claimed and not finished"],
               left_out=["GBPUSD_USDT: no family's universe"],
               not_reached=["AAA_USDT", "BBB_USDT", "CCC_USDT", "DDD_USDT"],
               downloads_failed=["b/x run 22: no artifact matches v3-out-*"],
               shares_refused=["c/x: HTTP 422 no workflow"],
               machines_refused=["a/x shards 0-3 (4 machines): plan mismatch"])
    return SimpleNamespace(plan=plan, tmp=tmp_path, folder=folder)


def test_every_coin_the_run_did_not_judge_is_named_once_in_the_bucket_that_is_true(
        monkeypatch, tmp_path):
    r = _full_run(monkeypatch, tmp_path)
    data = json.loads(vv.publish("pilot").read_text(encoding="utf-8"))
    nj = data["not_judged"]
    assert nj["failed"] == ["XPT_USDT: ConnectionError: cut"]
    assert nj["unmeasured"] == ["EURUSD_USDT: claimed and not finished"]
    assert nj["left_out"] == ["GBPUSD_USDT: no family's universe"]
    assert [x.split(":")[0] for x in nj["downloads_failed"]] == ["AAA_USDT", "BBB_USDT"]
    assert "b/x run 22" in nj["downloads_failed"][0]
    assert [x.split(":")[0] for x in nj["shares_refused"]] == ["CCC_USDT"]
    assert [x.split(":")[0] for x in nj["not_reached"]] == ["DDD_USDT"]
    assert nj["not_dispatched"] == [] and nj["other_records"] == []
    named = [x.split(":")[0] for lines in nj.values() for x in lines]
    assert len(named) == len(set(named)), "a coin is in ONE bucket"
    assert sorted(named + data["coins"]) == sorted(r.plan["coins"]), "every coin is accounted for"
    # the accounts that failed are named too, with why
    assert data["accounts"]["downloads_failed"] == ["b/x run 22: no artifact matches v3-out-*"]
    assert data["accounts"]["shares_refused"] == ["c/x: HTTP 422 no workflow"]
    assert data["accounts"]["machines_refused"] == ["a/x shards 0-3 (4 machines): plan mismatch"]
    assert data["dispatched"] == 9 and data["plan_coins"] == 9


def test_a_run_and_its_redos_are_one_family_and_a_coin_a_redo_landed_is_never_failed(run):
    plan = run.plan
    vrs.save_coin(run.folder, _record("XPT_USDT", plan, _eight(tp._rows([0.30] * 200, per_day=5))))
    _state(run.tmp, "pilot-redo1", ["XPT_USDT"], plan=plan,
           runs={"b/x": {"run": 31, "coins": 1, "label": "pilot redo 1"}})
    _collected(run.tmp, "pilot-redo1", runs={"b/x": 31}, landed=["XPT_USDT"])
    data = json.loads(vv.publish("pilot", now=1_793_000_000.0).read_text(encoding="utf-8"))
    assert data["family"] == ["pilot", "pilot-redo1"]
    assert "XPT_USDT" in data["coins"] and data["not_judged"]["failed"] == []
    assert data["github_runs"] == {"a/x": 11, "b/x": 12, "b/x (pilot-redo1)": 31}
    with pytest.raises(ValueError, match="publish pilot"):
        vv.publish("pilot-redo1")


def test_a_redo_that_failed_again_is_failed_by_the_newest_word(run):
    _state(run.tmp, "pilot-redo1", ["XPT_USDT"], plan=run.plan)
    _collected(run.tmp, "pilot-redo1", failed=["XPT_USDT: Timeout: again"])
    data = json.loads(vv.publish("pilot").read_text(encoding="utf-8"))
    assert data["not_judged"]["failed"] == ["XPT_USDT: Timeout: again"]


def test_a_redo_not_collected_yet_and_a_run_not_collected_are_refused_by_name(run):
    _state(run.tmp, "pilot-redo1", ["XPT_USDT"], plan=run.plan)
    with pytest.raises(ValueError, match="pilot-redo1 is not collected yet"):
        vv.publish("pilot")
    (run.tmp / "cloud" / "pilot-redo1.json").unlink()
    (run.tmp / "cloud" / "pilot-collected.json").unlink()
    with pytest.raises(ValueError, match="pilot is not collected yet"):
        vv.publish("pilot")


def test_a_missing_plan_copy_is_refused_by_name(run):
    (run.tmp / "cloud" / "pilot.plan.json").unlink()
    with pytest.raises(ValueError, match="the plan copy of pilot is missing"):
        vv.publish("pilot")


def test_a_coin_with_no_measured_timeframe_is_not_judged_and_says_why(run):
    idle = _record("XAG_USDT", run.plan, [])
    idle.pop("windows")
    idle["why"] = "too few candles on every timeframe"
    idle["combos"] = {}
    vrs.save_coin(run.folder, idle)
    data = json.loads(vv.publish("pilot").read_text(encoding="utf-8"))
    assert data["coins"] == ["XAU_USDT"], "only a coin with a measured timeframe is judged"
    assert data["not_judged"]["no_walk"] == ["XAG_USDT: too few candles on every timeframe"]


def test_two_publishes_in_one_second_keep_two_copies(run):
    vv.publish("pilot", now=1_793_000_000.0)
    vv.publish("pilot", now=1_793_000_000.0)
    assert len(list((run.tmp / "v3" / "verdicts").iterdir())) == 2


def test_pilot_is_said_only_when_the_run_was_sent_fewer_coins_than_the_plan_holds(
        monkeypatch, tmp_path):
    r = _full_run(monkeypatch, tmp_path)
    t = vpg.tested(vv.publish("pilot"), check_file=r.tmp / "none.json")
    assert "pilot" not in t["words"].lower()
    assert "a full run with 7 of the plan's 9 coins not judged" in t["words"]
    assert t["store"]["dispatched"] == 9
    assert t["store"]["not_judged"] == {"failed": 1, "unmeasured": 1, "left_out": 1,
                                        "downloads_failed": 2, "shares_refused": 1,
                                        "not_reached": 1}


def test_a_pilot_publishes_the_coins_it_never_sent_and_says_pilot(run):
    t = vpg.tested(vv.publish("pilot"), check_file=run.tmp / "none.json")
    assert t["store"]["dispatched"] == 3 and "a pilot of the machinery" in t["words"]


def test_options_passes_the_store_path_so_a_test_never_reads_the_real_store(run):
    mine = vv.publish("pilot")

    class FX:
        def trading_symbols(self):
            return ["BTC_USDT"]

    o = vpg.options(fx=FX(), store_file=mine, check_file=run.tmp / "none.json")
    assert o["tested"]["state"] == "stored"
    o = vpg.options(fx=FX(), store_file=run.tmp / "absent.json", check_file=run.tmp / "none.json")
    assert o["tested"]["state"] == "not_run"


def test_the_tab_names_every_bucket_the_provenance_and_the_full_run_heading():
    root = Path(__file__).resolve().parent.parent / "webapp" / "src" / "components" / "backtest-v3"
    src = (root / "V3Check.tsx").read_text(encoding="utf-8")
    for key in ("unmeasured", "downloads_failed", "shares_refused", "no_walk"):
        assert key in src, key
    assert "coins not judged" in src and "check.dispatched" in src
    assert "of the plan's ${planCoins} coins judged" in src       # the provenance line
    assert "check.accounts" in src and "not_judged_coins" in src


# ---- the final fix wave (Oct 29, 2026) ---------------------------------------------------------

def test_an_account_whose_machines_all_refused_or_that_left_no_artifact_files_its_coins_there(
        monkeypatch, tmp_path):
    """M4, M13: d/x's machines all refused, e/x's run produced no artifact - their coins are filed
    under that account's line, never "no machine reported it"."""
    r = _full_run(monkeypatch, tmp_path)
    st = json.loads((tmp_path / "cloud" / "pilot.json").read_text(encoding="utf-8"))
    st["board"] = sorted(set(st["board"]) | {"EEE_USDT"})
    st["dealt"]["e/x"] = {"coin_list": "EEE_USDT"}
    (tmp_path / "cloud" / "pilot.json").write_text(json.dumps(st), encoding="utf-8")
    plan = _plan(r.plan["coins"] + ["EEE_USDT"])
    vu.save(plan, tmp_path / "cloud" / "pilot.plan.json")
    st["plan_id"] = plan["id"]
    (tmp_path / "cloud" / "pilot.json").write_text(json.dumps(st), encoding="utf-8")
    for coin in ("XAU_USDT", "XAG_USDT"):
        vrs.save_coin(r.folder, _record(coin, plan, _eight(tp._rows([0.30] * 200, per_day=5))))
    _collected(tmp_path, "pilot", landed=["XAG_USDT", "XAU_USDT"],
               failed=["XPT_USDT: ConnectionError: cut"],
               unmeasured=["EURUSD_USDT: claimed and not finished"],
               left_out=["GBPUSD_USDT: no family's universe"],
               not_reached=["AAA_USDT", "BBB_USDT", "CCC_USDT", "DDD_USDT", "EEE_USDT"],
               downloads_failed=["b/x run 22: no artifact matches v3-out-*"],
               shares_refused=["c/x: HTTP 422 no workflow"],
               machines_refused=["d/x shards 0-19 (20 machines): plan mismatch"],
               runs_without_artifact=["e/x run 25: the run produced no artifact"])
    data = json.loads(vv.publish("pilot").read_text(encoding="utf-8"))
    nj = data["not_judged"]
    assert nj["machines_refused"] == ["DDD_USDT: d/x shards 0-19 (20 machines): plan mismatch"]
    assert nj["not_reached"] == ["EEE_USDT: e/x run 25: the run produced no artifact"]
    assert data["accounts"]["runs_without_artifact"] == ["e/x run 25: the run produced no artifact"]
    named = [x.split(":")[0] for lines in nj.values() for x in lines]
    assert len(named) == len(set(named))


def test_a_run_no_account_started_names_redo_when_it_is_published(run):
    st = json.loads((run.tmp / "cloud" / "pilot.json").read_text(encoding="utf-8"))
    st.update(runs={}, refused=["a/x: HTTP 502"], dealt={"a/x": {"coin_list": "XAU_USDT"}})
    (run.tmp / "cloud" / "pilot.json").write_text(json.dumps(st), encoding="utf-8")
    (run.tmp / "cloud" / "pilot-collected.json").unlink()
    with pytest.raises(ValueError, match=r"pilot: no run was started \(every share refused: "
                                         r"a/x: HTTP 502\); start each share with python -m "
                                         r"tradingagents.v3_cloud redo pilot <a/x>"):
        vv.publish("pilot")


def test_the_store_swap_is_retried_under_a_reader_and_a_failed_one_keeps_no_copy(run,
                                                                                monkeypatch):
    """M10: Windows refuses a replace while the site reads verdicts.json - retried; a swap that
    never goes takes its kept copy back, so publishing again keeps ONE copy of one judgement."""
    real = Path.replace
    calls = []

    def flaky(self, dest):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError("in use")
        return real(self, dest)

    monkeypatch.setattr(Path, "replace", flaky)
    vv.publish("pilot", now=1_793_000_000.0)
    assert len(calls) == 3 and (run.tmp / "v3" / "verdicts.json").exists()
    assert not list((run.tmp / "v3").glob("*.tmp"))

    def never(self, dest):
        raise PermissionError("in use")

    monkeypatch.setattr(Path, "replace", never)
    monkeypatch.setattr(vc, "_swap", lambda tmp, p, wait=0.0: never(tmp, p))
    with pytest.raises(PermissionError):
        vv.publish("pilot", now=1_793_000_500.0)
    kept = sorted(p.name for p in (run.tmp / "v3" / "verdicts").iterdir())
    assert kept == ["pilot-1793000000000.json"], "the refused publish kept no copy"
    assert not list((run.tmp / "v3").glob("*.tmp"))
