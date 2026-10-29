"""Backtest v3 on GitHub, started from this PC (tradingagents/v3_cloud.py,
Part 2b): every account gets its share of the plan's coins with the plan's id,
the state is saved before any dispatch, a plan that is not on origin/main is
never dispatched, a refused share is redone by itself (and a run GitHub listed
late is adopted, never doubled), the collect lands only this run's records and
names every coin it did not, a failed coin loses its old record, a folder of
another plan is never landed into, and a retry redoes only what failed."""
from __future__ import annotations

import datetime as dt
import gzip
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from tradingagents import (
    cloud_sweep as cs,
    forecast_v2_daily as fd,
    v3_cloud as vc,
    v3_research as vrs,
    v3_universe as vu,
)

ROOT = Path(__file__).resolve().parent.parent
NOON = dt.datetime(2026, 10, 28, 12, 0).timestamp()
ONE_AM = dt.datetime(2026, 10, 28, 1, 0).timestamp()
END = 1_792_800_000_000 - 1_792_800_000_000 % 86_400_000
# sorted, the board is BTC ETH PEPE SOL XAG XAU 龙虾, dealt in turn: a/x BTC SOL 龙虾, b/x ETH XAG,
# c/x PEPE XAU
COINS = ["BTC_USDT", "ETH_USDT", "SOL_USDT", "XAU_USDT", "XAG_USDT", "PEPE_USDT", "龙虾_USDT"]


def _plan(tmp):
    plan = {"version": vu.VERSION, "venue": "Gate", "start_ms": END - 365 * 86_400_000,
            "end_ms": END, "coins": sorted(COINS), "months": [], "liquid": {}, "calm": {}}
    plan["id"] = vu.plan_id(plan)
    return vu.save(plan, tmp / "plan.json"), plan


@pytest.fixture()
def fleet(monkeypatch, tmp_path):
    """Three accounts, a/x the origin. `.fail` names the accounts whose dispatch GitHub refuses;
    `.started` holds (repo, inputs, since) of every start."""
    ns = SimpleNamespace(started=[], fail=set(), tmp=tmp_path)

    def start(repo, inputs, since=None):
        assert vc._state_path("pilot").exists() or vc._state_path("pilot-redo1").exists(), \
            "the state is saved before the dispatch"
        if repo in ns.fail:
            raise RuntimeError("could not create workflow dispatch event: HTTP 502")
        ns.started.append((repo, dict(inputs), since))
        return 1000 + len(ns.started)

    monkeypatch.setattr(vc, "home", lambda: (tmp_path / "cloud").mkdir(exist_ok=True)
                        or tmp_path / "cloud")
    monkeypatch.setattr(vrs, "home", lambda label="local": tmp_path / "research"
                        / vrs.plain_label(label))
    monkeypatch.setattr(vc, "_start", start)
    monkeypatch.setattr(vc, "_git", lambda *a: "same-blob")
    monkeypatch.setattr(fd, "fleets_now", lambda: (["a/x", "b/x", "c/x"], []))
    monkeypatch.setattr(cs, "origin_fleet", lambda: "a/x")
    monkeypatch.setattr(cs, "sync_fleet", lambda repo: "")
    ns.path, ns.plan = _plan(tmp_path)
    return ns


def test_every_account_gets_its_share_of_the_plans_coins_with_the_plans_id(fleet):
    started, path, plan = fleet.started, fleet.path, fleet.plan
    st = vc.dispatch("pilot", plan_path=path, now=NOON)
    assert [r for r, _i, _s in started] == ["a/x", "b/x", "c/x"]
    dealt = sorted(c for _r, i, _s in started for c in i["coin_list"].split(","))
    assert dealt == sorted(COINS), "every coin of the plan, once"
    for _repo, inputs, _since in started:
        assert inputs["plan_id"] == plan["id"]
        assert inputs["shards"] == str(len(inputs["coin_list"].split(",")))   # under 20: one each
        assert inputs["label"].startswith("pilot · ")
    assert st["plan_id"] == plan["id"] and st["risk_usd"] == 5.0 and st["runs_per_combo"] == 200
    assert st["folder"] == "pilot" and set(st["runs"]) == {"a/x", "b/x", "c/x"}
    saved = vc.load_state("pilot")
    assert saved["runs"]["b/x"]["run"] == 1002 and not saved["refused"]
    # the plan as dispatched is kept beside the state: the run is judged under it
    assert vu.load(saved["plan_copy"])["id"] == plan["id"]


def test_a_plan_that_is_not_on_origin_main_is_never_dispatched(fleet, monkeypatch):
    started, path = fleet.started, fleet.path
    monkeypatch.setattr(vc, "_git", lambda *a: "local-blob" if a[0] == "hash-object"
                        else "main-blob")
    with pytest.raises(RuntimeError, match="is not the plan on origin/main"):
        vc.dispatch("pilot", plan_path=path, now=NOON)
    assert started == []


def test_a_coin_outside_the_plan_is_refused_by_name_and_the_night_refuses_a_dispatch(fleet):
    started, path = fleet.started, fleet.path
    with pytest.raises(ValueError, match="not in the plan's universe: DOGE_USDT"):
        vc.dispatch("pilot", coins=["BTC", "DOGE"], plan_path=path, now=NOON)
    with pytest.raises(RuntimeError, match="12:45am and 5:00am"):
        vc.dispatch("pilot", plan_path=path, now=ONE_AM)
    assert started == []
    vc.dispatch("pilot", coins=["BTC", "XAU_USDT"], plan_path=path, now=ONE_AM, force=True)
    assert sorted(c for _r, i, _s in started for c in i["coin_list"].split(",")) == \
        ["BTC_USDT", "XAU_USDT"]


def test_a_refused_share_is_redone_by_itself_and_a_late_listed_run_is_adopted(fleet,
                                                                              monkeypatch):
    started, path = fleet.started, fleet.path
    fleet.fail = {"b/x"}
    st = vc.dispatch("pilot", plan_path=path, now=NOON)
    assert set(st["runs"]) == {"a/x", "c/x"} and st["refused"][0].startswith("b/x:")
    share = st["dealt"]["b/x"]
    started.clear()
    fleet.fail = set()
    got = vc.redo("pilot", "b/x")
    # the share it was dealt, asked with `since`: a run GitHub took and listed late is adopted
    assert started == [("b/x", share, NOON)] and got["runs"]["b/x"]["run"] == 1001
    assert got["refused"] == []
    with pytest.raises(ValueError, match="already has run"):
        vc.redo("pilot", "b/x")


def test_the_dispatcher_adopts_a_run_github_listed_late_never_starting_a_second(monkeypatch):
    # the real start path (forecast_v2_daily.dispatch) with a run of this title made after `since`
    inputs = {"label": "pilot · 2 of 3", "coin_list": "ETH_USDT", "shards": "1", "plan_id": "p"}
    title = vc.title_of(inputs["label"])
    made = dt.datetime.fromtimestamp(NOON + 30, dt.timezone.utc).isoformat()
    monkeypatch.setattr(fd, "_runs", lambda wf, repo, limit=20: [
        {"databaseId": 777, "displayTitle": title, "createdAt": made}])

    def no_new_run(*a, **k):
        raise AssertionError(f"a second run was started: {a}")

    monkeypatch.setattr(fd, "_gh", no_new_run)
    assert vc._start("b/x", inputs, since=NOON) == 777


def test_the_run_is_found_by_the_title_the_workflow_gives_it():
    text = (ROOT / ".github" / "workflows" / "v3.yml").read_text(encoding="utf-8")
    shown = re.search(r'run-name: "(.*)"', text).group(1).replace("${{ inputs.label }}", "L")
    assert fd.title_of(vc.WORKFLOW, {"label": "L"}) == vc.title_of("L") == shown


# ---- the collect ------------------------------------------------------------------------------

def _rec(coin, plan, **over):
    return {"version": 2, "coin": coin, "kind": "crypto", "plan_id": plan["id"],
            "plan_end_ms": plan["end_ms"], "risk_usd": 5.0, "runs": 200, "combos": {"x": {}},
            "windows": {"1d": {}}, "skipped": {}, "machine": {"repo": "a/x"}, **over}


def _artifact(root: Path, shard: int, recs: list, report: list, refused: str = ""):
    """One machine's artifact as `gh run download` unpacks it."""
    d = root / f"v3-out-{shard}"
    for r in recs:
        p = vrs.coin_file(d / "v3", r["coin"])
        p.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(p, "wt", encoding="utf-8") as fh:
            json.dump(r, fh)
    d.mkdir(parents=True, exist_ok=True)
    head = {"shard": shard, "machine": {"repo": "c/x"}, "report": report}
    if refused:
        head["refused"] = refused
    (d / f"v3-report-{shard}.json").write_text(json.dumps(head), encoding="utf-8")


def _collected(fleet, monkeypatch, fill):
    path, plan, tmp = fleet.path, fleet.plan, fleet.tmp
    fleet.fail = {"c/x"}                  # the third account's share never starts
    st = vc.dispatch("pilot", plan_path=path, now=NOON)
    roots = {}
    for repo, r in st["runs"].items():
        roots[repo] = tmp / f"art-{r['run']}"
        roots[repo].mkdir()
    fill(st, roots, plan)
    monkeypatch.setattr(fd, "run_status", lambda run, repo: {"status": "completed"})
    monkeypatch.setattr(vc, "download", lambda run, repo: roots[repo])
    return st, vc.collect("pilot"), plan, tmp


def test_the_collect_lands_this_runs_records_and_names_every_coin_it_did_not(fleet,
                                                                            monkeypatch):
    def fill(st, roots, plan):
        a = st["dealt"]["a/x"]["coin_list"].split(",")       # BTC, SOL, 龙虾 (dealt in turn)
        b = st["dealt"]["b/x"]["coin_list"].split(",")       # ETH, XAG
        _artifact(roots["a/x"], 0, [_rec(a[0], plan), _rec(a[2], plan)],
                  [{"coin": a[0], "seconds": 150.0, "bytes": 80_000, "combos": 1},
                   {"coin": a[1], "error": "ConnectionError: cut", "tries": 3},
                   {"coin": a[2], "seconds": 190.0, "bytes": 90_000, "combos": 1}])
        _artifact(roots["b/x"], 0, [_rec(b[0], plan, risk_usd=1.0)],
                  [{"coin": b[0], "seconds": 100.0, "bytes": 70_000, "combos": 1},
                   {"coin": b[1], "why": "the exchange is not trading it now"}])
        _artifact(roots["b/x"], 1, [], [], refused="TA_VENUE is 'mexc': Backtest v3 measures "
                                                   "on Gate only")

    st, got, _plan_, _tmp = _collected(fleet, monkeypatch, fill)
    a = st["dealt"]["a/x"]["coin_list"].split(",")
    b = st["dealt"]["b/x"]["coin_list"].split(",")
    c = st["dealt"]["c/x"]["coin_list"].split(",")
    assert got["landed"] == sorted([a[0], a[2]])
    assert got["failed"] == [f"{a[1]}: ConnectionError: cut"]
    assert got["left_out"] == [f"{b[1]}: the exchange is not trading it now"]
    assert got["refused_records"] == [f"{b[0]}: risk $1.00, not $5.00"]
    assert got["machines_refused"] == ["c/x shard 1: TA_VENUE is 'mexc': Backtest v3 measures "
                                       "on Gate only"]
    # the share GitHub refused, and the record refused at landing, are coins not reached
    assert got["not_reached"] == sorted(c + [b[0]])
    assert got["seconds"] == {"median": 150.0, "max": 190.0, "total": 440.0}
    held = {r["coin"] for r in vrs.load_coins(vrs.home("pilot"))}
    assert held == {a[0], a[2]}, "a Chinese-named coin lands under its ASCII file name"


def test_a_coin_that_failed_this_time_loses_its_old_record(fleet, monkeypatch):
    plan = fleet.plan
    vrs.save_coin(vrs.home("pilot"), _rec("SOL_USDT", plan))

    def fill(st, roots, plan_):
        _artifact(roots["a/x"], 0, [], [{"coin": "SOL_USDT", "error": "ValueError: x",
                                         "tries": 3}])
        _artifact(roots["b/x"], 0, [], [])

    _st, got, _p, _t = _collected(fleet, monkeypatch, fill)
    assert got["failed"] == ["SOL_USDT: ValueError: x"]
    assert not vrs.coin_file(vrs.home("pilot"), "SOL_USDT").exists()


def test_a_folder_holding_another_plans_records_is_never_landed_into(fleet, monkeypatch):
    plan = fleet.plan
    vrs.save_coin(vrs.home("pilot"), _rec("BTC_USDT", plan, plan_id="0123456789abcdef"))

    def fill(st, roots, plan_):
        _artifact(roots["a/x"], 0, [_rec("SOL_USDT", plan_)], [])
        _artifact(roots["b/x"], 0, [], [])

    with pytest.raises(RuntimeError, match="holds records of another plan"):
        _collected(fleet, monkeypatch, fill)
    assert not vrs.coin_file(vrs.home("pilot"), "SOL_USDT").exists()


def test_retry_redoes_only_the_failed_and_unreached_coins_into_the_same_folder(fleet,
                                                                               monkeypatch):
    def fill(st, roots, plan):
        a = st["dealt"]["a/x"]["coin_list"].split(",")
        _artifact(roots["a/x"], 0, [_rec(a[0], plan), _rec(a[2], plan)],
                  [{"coin": a[1], "error": "ConnectionError: cut", "tries": 3}])
        _artifact(roots["b/x"], 0, [], [{"coin": c, "why": "the exchange is not trading it now"}
                                        for c in st["dealt"]["b/x"]["coin_list"].split(",")])

    started = fleet.started
    st, got, _p, _t = _collected(fleet, monkeypatch, fill)
    started.clear()
    fleet.fail = set()
    again = vc.retry("pilot", now=NOON)
    assert again["name"] == "pilot-redo1" and again["folder"] == "pilot"
    redone = sorted(c for _r, i, _s in started for c in i["coin_list"].split(","))
    # the failed coin and the refused share's coins; never the left-out or the landed ones
    want = sorted([st["dealt"]["a/x"]["coin_list"].split(",")[1]]
                  + st["dealt"]["c/x"]["coin_list"].split(","))
    assert redone == want == sorted(got["not_reached"] + [x.split(": ")[0] for x in got["failed"]])


def test_parity_ignores_when_and_where_and_names_what_differs():
    a = {"coin": "XAU_USDT", "pre": {"seconds": 20.1, "flat_slip": 0.0002},
         "windows": {"1h": {"seconds": 40.0, "older_candles": 6600}},
         "combos": {"k": {"older": {"rows": [[1, 2, 3, 1, 0.5, "TP", 0.007, 0.0067]]}}},
         "machine": {"repo": "a/x"}}
    b = json.loads(json.dumps(a))
    b["pre"]["seconds"], b["windows"]["1h"]["seconds"], b["machine"] = 31.0, 55.5, {"repo": "pc"}
    assert vc.same_measure(a, b) == []
    b["combos"]["k"]["older"]["rows"][0][4] = 0.51
    assert vc.same_measure(a, b) == ["combos.k.older.rows[0][4]"]


# ---- Task 3 review pins: an account with no coins, and the same coin named by every machine ----

def test_an_account_dealt_no_coins_is_never_dispatched(fleet):
    """Two coins on three accounts: the machine refuses an empty coin list, and an empty list
    would mean "the whole plan" to the sweep - so no run is started for the account with none."""
    started, path = fleet.started, fleet.path
    st = vc.dispatch("pilot", coins=["BTC", "ETH"], plan_path=path, now=NOON)
    assert [r for r, _i, _s in started] == ["a/x", "b/x"]
    assert all(i["coin_list"] and i["shards"] != "0" for _r, i, _s in started)
    assert set(st["dealt"]) == set(st["runs"]) == {"a/x", "b/x"}


def test_a_coin_every_machine_names_as_left_out_is_one_line(fleet, monkeypatch):
    """Every machine of an account names the account's left-out coins (and a killed machine's
    claimed coins are named on each report written so far): one line per coin, not one per
    machine."""
    def fill(st, roots, plan):
        a = st["dealt"]["a/x"]["coin_list"].split(",")
        out = {"coin": a[1], "why": "the exchange is not trading it now"}
        dead = {"coin": a[2], "error": "claimed, not finished: the machine stopped before this "
                                       "coin was measured", "unfinished": True, "tries": 1}
        for n in range(3):
            _artifact(roots["a/x"], n, [_rec(a[0], plan)] if n == 0 else [],
                      [out, dead] + ([{"coin": a[0], "seconds": 1.0, "bytes": 5}] if n == 0
                                     else []))
        _artifact(roots["b/x"], 0, [], [])

    st, got, _p, _t = _collected(fleet, monkeypatch, fill)
    a = st["dealt"]["a/x"]["coin_list"].split(",")
    assert got["left_out"] == [f"{a[1]}: the exchange is not trading it now"]
    assert got["failed"] == [f"{a[2]}: claimed, not finished: the machine stopped before this "
                             "coin was measured"]
    assert got["landed"] == [a[0]]
