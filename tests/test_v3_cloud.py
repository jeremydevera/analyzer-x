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
    # claimed and not finished = NOT MEASURED: one line, not an error, not landed
    assert got["failed"] == []
    assert got["unmeasured"] == [f"{a[2]}: claimed, not finished: the machine stopped before "
                                 "this coin was measured"]
    assert got["landed"] == [a[0]]
    assert a[2] not in got["not_reached"]
    # ... and the retry redoes it (with the share GitHub refused), never the left-out coin
    fleet.started.clear()
    fleet.fail = set()
    vc.retry("pilot", now=NOON)
    redone = sorted(c for _r, i, _s in fleet.started for c in i["coin_list"].split(","))
    assert a[2] in redone and a[1] not in redone and a[0] not in redone


def test_an_unfinished_coin_that_has_a_record_or_a_final_entry_is_not_unmeasured(fleet,
                                                                                 monkeypatch):
    def fill(st, roots, plan):
        a = st["dealt"]["a/x"]["coin_list"].split(",")
        held = {"unfinished": True, "error": "claimed, not finished: x", "tries": 1}
        # a[0]: killed after its record was saved; a[1]: its placeholder replaced by a final error
        _artifact(roots["a/x"], 0, [_rec(a[0], plan)],
                  [{"coin": a[0], **held}, {"coin": a[1], **held},
                   {"coin": a[1], "error": "ValueError: x", "tries": 3}])
        _artifact(roots["b/x"], 0, [], [])

    st, got, _p, _t = _collected(fleet, monkeypatch, fill)
    a = st["dealt"]["a/x"]["coin_list"].split(",")
    assert got["landed"] == [a[0]] and got["unmeasured"] == []
    assert got["failed"] == [f"{a[1]}: ValueError: x"]


# ---- Task 3 fix round 1 ------------------------------------------------------------------------

def _dispatched(fleet, monkeypatch, **kw):
    """pilot dispatched on a/x and b/x (c/x refused), ready to collect."""
    fleet.fail = {"c/x"}
    st = vc.dispatch("pilot", plan_path=fleet.path, now=NOON, **kw)
    roots = {}
    for repo, r in st["runs"].items():
        roots[repo] = fleet.tmp / f"art-{r['run']}"
        roots[repo].mkdir()
    monkeypatch.setattr(fd, "run_status", lambda run, repo: {"status": "completed"})
    monkeypatch.setattr(vc, "download", lambda run, repo: roots[repo])
    return st, roots


def test_one_accounts_failed_download_is_named_and_the_others_still_land(fleet, monkeypatch):
    import subprocess

    st, roots = _dispatched(fleet, monkeypatch)
    a = st["dealt"]["a/x"]["coin_list"].split(",")
    b = st["dealt"]["b/x"]["coin_list"].split(",")
    _artifact(roots["a/x"], 0, [_rec(a[0], fleet.plan)],
              [{"coin": a[0], "seconds": 1.0, "bytes": 5}])

    def download(run, repo):
        if repo == "b/x":
            raise subprocess.CalledProcessError(1, "gh", stderr="no artifact matches v3-out-*")
        return roots[repo]

    monkeypatch.setattr(vc, "download", download)
    got = vc.collect("pilot")
    assert got["landed"] == [a[0]]
    assert got["downloads_failed"] == ["b/x run 1002: no artifact matches v3-out-*"]
    assert set(b) <= set(got["not_reached"])
    assert vc._state_path("pilot").exists() and (vc.home() / "pilot-collected.json").exists()
    # the share stays collectable: once the download works, the same command lands it
    _artifact(roots["b/x"], 0, [_rec(b[0], fleet.plan)],
              [{"coin": b[0], "seconds": 1.0, "bytes": 5}])
    monkeypatch.setattr(vc, "download", lambda run, repo: roots[repo])
    again = vc.collect("pilot")
    assert again["landed"] == sorted([a[0], b[0]]) and again["downloads_failed"] == []


def test_a_retry_waits_for_a_failed_download_and_every_download_failing_collects_nothing(
        fleet, monkeypatch):
    import subprocess

    st, roots = _dispatched(fleet, monkeypatch)

    def boom(run, repo):
        raise subprocess.TimeoutExpired("gh", 3600)

    monkeypatch.setattr(vc, "download", boom)
    with pytest.raises(RuntimeError, match=r"no run could be downloaded: a/x run 1001: "
                                            r"TimeoutExpired"):
        vc.collect("pilot")
    assert not (vc.home() / "pilot-collected.json").exists()
    a = st["dealt"]["a/x"]["coin_list"].split(",")
    _artifact(roots["a/x"], 0, [], [{"coin": a[0], "error": "ValueError: x", "tries": 3}])
    _artifact(roots["b/x"], 0, [], [])

    def half(run, repo):
        if repo == "b/x":
            raise OSError("disk")
        return roots[repo]

    monkeypatch.setattr(vc, "download", half)
    got = vc.collect("pilot")
    assert got["downloads_failed"] == ["b/x run 1002: OSError: disk"]
    with pytest.raises(RuntimeError, match="a download failed .*collect it again first"):
        vc.retry("pilot", now=NOON)
    fleet.fail = set()
    assert vc.retry("pilot", now=NOON, abandon=True)["name"] == "pilot-redo1"


def test_a_name_whose_runs_are_going_is_never_dispatched_again(fleet, monkeypatch):
    started = fleet.started
    st = vc.dispatch("pilot", plan_path=fleet.path, now=NOON)
    before = vc.load_state("pilot")
    with pytest.raises(RuntimeError, match=r"pilot still has 3 run\(s\) going: collect or "
                                           r"retry them first"):
        vc.dispatch("pilot", plan_path=fleet.path, now=NOON)
    assert vc.load_state("pilot") == before and len(started) == 3
    # a collected run is finished: the name can be used again, and its old summary goes
    roots = {}
    for repo, r in st["runs"].items():
        roots[repo] = fleet.tmp / f"art-{r['run']}"
        _artifact(roots[repo], 0, [], [])
    monkeypatch.setattr(fd, "run_status", lambda run, repo: {"status": "completed"})
    monkeypatch.setattr(vc, "download", lambda run, repo: roots[repo])
    vc.collect("pilot")
    assert (vc.home() / "pilot-collected.json").exists()
    vc.dispatch("pilot", plan_path=fleet.path, now=NOON)
    assert len(started) == 6 and not (vc.home() / "pilot-collected.json").exists()


def test_every_machine_of_an_account_refusing_for_one_cause_is_one_line(fleet, monkeypatch):
    def fill(st, roots, plan):
        why = "the plan file changed between the dispatch and this machine's checkout"
        for n in range(4):
            _artifact(roots["a/x"], n, [], [], refused=why)
        _artifact(roots["a/x"], 9, [], [], refused="TA_VENUE is 'mexc'")
        _artifact(roots["b/x"], 0, [], [])

    _st, got, _p, _t = _collected(fleet, monkeypatch, fill)
    # the machines name themselves c/x in _artifact's header
    assert got["machines_refused"] == [
        "c/x shards 0-3 (4 machines): the plan file changed between the dispatch and this "
        "machine's checkout", "c/x shard 9: TA_VENUE is 'mexc'"]


def test_a_run_is_labelled_with_the_runs_that_exist(fleet):
    st = vc.dispatch("pilot", coins=["BTC", "ETH"], plan_path=fleet.path, now=NOON)
    assert [i["label"] for i in st["dealt"].values()] == ["pilot · 1 of 2", "pilot · 2 of 2"]


def test_a_left_out_coin_loses_its_old_record_and_no_coin_is_in_two_buckets(fleet, monkeypatch):
    plan = fleet.plan
    vrs.save_coin(vrs.home("pilot"), _rec("SOL_USDT", plan))

    def fill(st, roots, plan_):
        left = "the exchange is not trading it now"
        _artifact(roots["a/x"], 0, [], [{"coin": "SOL_USDT", "why": left},
                                        {"coin": "BTC_USDT", "why": left},
                                        {"coin": "BTC_USDT", "error": "ValueError: x", "tries": 3}])
        _artifact(roots["b/x"], 0, [], [])

    st, got, _p, _t = _collected(fleet, monkeypatch, fill)
    assert not vrs.coin_file(vrs.home("pilot"), "SOL_USDT").exists()
    assert got["left_out"] == ["SOL_USDT: the exchange is not trading it now"]
    assert got["failed"] == ["BTC_USDT: ValueError: x"]
    buckets = [got["landed"], [x.split(": ")[0] for x in got["failed"]],
               [x.split(": ")[0] for x in got["unmeasured"]],
               [x.split(": ")[0] for x in got["left_out"]], got["not_reached"]]
    every = [c for b in buckets for c in b]
    assert len(every) == len(set(every))


def test_collect_sweeps_old_run_folders_in_its_own_directory_only(fleet):
    import os
    import time as _t

    home = vc.home()
    old, new, other, notrun = (home / "run-111", home / "run-222", home / "keep-me",
                               home / "run-abc")
    for d in (old, new, other, notrun):
        d.mkdir()
        (d / "f").write_text("x")
    ten_days = _t.time() - 10 * 86400
    for d in (old, other, notrun):
        os.utime(d, (ten_days, ten_days))
    stranger = fleet.tmp / "run-333"          # beside the cloud folder, not in it
    stranger.mkdir()
    os.utime(stranger, (ten_days, ten_days))
    assert vc.sweep_runs() == ["run-111"]
    assert not old.exists() and new.exists() and other.exists() and notrun.exists()
    assert stranger.exists()


def test_collect_calls_the_sweep_before_it_downloads(fleet, monkeypatch):
    order = []
    st, roots = _dispatched(fleet, monkeypatch)
    for r in roots.values():
        _artifact(r, 0, [], [])
    monkeypatch.setattr(vc, "sweep_runs", lambda now=None: order.append("sweep") or [])
    monkeypatch.setattr(vc, "download", lambda run, repo: order.append("download") or roots[repo])
    vc.collect("pilot")
    assert order[0] == "sweep" and "download" in order


def test_a_second_retry_before_the_first_is_collected_is_refused_by_name(fleet, monkeypatch):
    def fill(st, roots, plan):
        a = st["dealt"]["a/x"]["coin_list"].split(",")
        _artifact(roots["a/x"], 0, [_rec(a[0], plan)],
                  [{"coin": a[1], "error": "ConnectionError: cut", "tries": 3}])
        _artifact(roots["b/x"], 0, [], [])

    _collected(fleet, monkeypatch, fill)
    fleet.fail = set()
    assert vc.retry("pilot", now=NOON)["name"] == "pilot-redo1"
    started = len(fleet.started)
    with pytest.raises(RuntimeError, match="pilot-redo1 has not been collected"):
        vc.retry("pilot", now=NOON)
    assert len(fleet.started) == started


def test_a_coin_that_landed_since_is_not_redone_and_nothing_left_is_named(fleet, monkeypatch):
    def fill(st, roots, plan):
        a = st["dealt"]["a/x"]["coin_list"].split(",")
        _artifact(roots["a/x"], 0, [], [{"coin": a[0], "error": "ValueError: x", "tries": 3}])
        _artifact(roots["b/x"], 0, [], [])

    st, got, plan, _t = _collected(fleet, monkeypatch, fill)
    fleet.fail = set()
    todo = got["not_reached"] + [x.split(": ")[0] for x in got["failed"]]
    assert len(todo) > 2
    for c in todo[1:]:
        vrs.save_coin(vrs.home("pilot"), _rec(c, plan))      # landed by a redo since
    fleet.started.clear()
    vc.retry("pilot", now=NOON)
    redone = [c for _r, i, _s in fleet.started for c in i["coin_list"].split(",")]
    assert redone == [todo[0]]


def test_a_retry_with_every_coin_landed_since_has_nothing_to_redo(fleet, monkeypatch):
    def fill(st, roots, plan):
        a = st["dealt"]["a/x"]["coin_list"].split(",")
        _artifact(roots["a/x"], 0, [], [{"coin": a[0], "error": "ValueError: x", "tries": 3}])
        _artifact(roots["b/x"], 0, [], [])

    st, got, plan, _t = _collected(fleet, monkeypatch, fill)
    for c in got["not_reached"] + [x.split(": ")[0] for x in got["failed"]]:
        vrs.save_coin(vrs.home("pilot"), _rec(c, plan))
    started = len(fleet.started)
    with pytest.raises(ValueError, match="nothing to redo"):
        vc.retry("pilot", now=NOON)
    assert len(fleet.started) == started


def test_a_corrupt_record_is_named_and_the_landing_goes_on(fleet, monkeypatch):
    def fill(st, roots, plan):
        a = st["dealt"]["a/x"]["coin_list"].split(",")
        _artifact(roots["a/x"], 0, [_rec(a[0], plan), _rec(a[2], plan)],
                  [{"coin": a[0], "seconds": 1.0, "bytes": 5},
                   {"coin": a[2], "seconds": 1.0, "bytes": 5}])
        bad = vrs.coin_file(roots["a/x"] / "v3-out-0" / "v3", a[2])
        bad.write_bytes(b"\x1f\x8b\x08 not a real gzip")
        _artifact(roots["b/x"], 0, [], [])

    st, got, _p, _t = _collected(fleet, monkeypatch, fill)
    a = st["dealt"]["a/x"]["coin_list"].split(",")
    assert got["landed"] == [a[0]]
    assert len(got["refused_records"]) == 1 and got["refused_records"][0].startswith(
        "unreadable record ")
    assert a[2] not in got["landed"]


def test_the_summary_is_swapped_whole_and_the_swap_is_retried(fleet, monkeypatch):
    target = vc.home() / "x.json"
    real = Path.replace
    calls = []

    def flaky(self, dest):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError("in use")
        return real(self, dest)

    monkeypatch.setattr(Path, "replace", flaky)
    vc._write_whole(target, '{"a": 1}')
    assert json.loads(target.read_text()) == {"a": 1} and len(calls) == 3
    assert not list(vc.home().glob("*.tmp"))


def test_the_progress_command_before_any_run_says_so(fleet, capsys):
    assert vc.main(["progress"]) == 0
    assert capsys.readouterr().out.strip() == "no run yet"


def test_a_retry_under_a_plan_that_is_no_longer_on_main_says_so_not_rebuild_it(fleet,
                                                                              monkeypatch):
    def fill(st, roots, plan):
        a = st["dealt"]["a/x"]["coin_list"].split(",")
        _artifact(roots["a/x"], 0, [], [{"coin": a[0], "error": "ValueError: x", "tries": 3}])
        _artifact(roots["b/x"], 0, [], [])

    _collected(fleet, monkeypatch, fill)
    monkeypatch.setattr(vc, "_git", lambda *a: "local-blob" if a[0] == "hash-object"
                        else "main-blob")
    with pytest.raises(RuntimeError, match="a retry cannot run under another plan"):
        vc.retry("pilot", now=NOON)
