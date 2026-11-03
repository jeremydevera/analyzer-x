"""The "all" plan travels to GitHub as the universe plan does (operator, Nov 03, 2026: "run
backtest for v3 for all coins"): `v3_cloud dispatch --plan research/v3/plan-all.json` checks THAT
file's blob on origin/main, keeps its path in the run's state so a retry and a redo check the
same file, and every machine finds the plan by the id the dispatch named - v3.yml keeps its four
inputs."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_v3_cloud import COINS, NOON, fleet  # noqa: F401  (the fixture)
from tradingagents import v3_cloud as vc, v3_universe as vu

ROOT = Path(__file__).resolve().parent.parent


def _all_plan(tmp):
    """An "all" plan file at <tmp>/research/v3/plan-all.json, tmp standing in for the checkout."""
    plan = {"version": vu.VERSION, "kind": "all", "venue": "Gate",
            "start_ms": 1_761_000_000_000, "end_ms": 1_792_500_000_000, "coins": sorted(COINS),
            "months": [], "liquid": {}, "calm": {}}
    plan["id"] = vu.plan_id(plan)
    return vu.save(plan, tmp / "research" / "v3" / "plan-all.json"), plan


@pytest.fixture()
def checkout(fleet, monkeypatch):  # noqa: F811
    asked = []

    def git(*a):
        asked.append(a)
        return "same-blob"

    monkeypatch.setattr(vc, "_git", git)
    monkeypatch.setattr(vc, "repo_root", lambda: fleet.tmp)
    fleet.asked = asked
    fleet.all_path, fleet.all_plan = _all_plan(fleet.tmp)
    return fleet


def test_dispatch_checks_the_all_plans_own_file_on_origin_main_and_keeps_its_path(checkout):
    st = vc.dispatch("all-1", plan_path=checkout.all_path, now=NOON)
    assert ("rev-parse", "origin/main:research/v3/plan-all.json") in checkout.asked
    assert st["plan_rel"] == "research/v3/plan-all.json" and st["plan_kind"] == "all"
    assert {i["plan_id"] for _r, i, _s in checkout.started} == {checkout.all_plan["id"]}
    assert vu.load(st["plan_copy"])["id"] == checkout.all_plan["id"]


def test_a_plan_outside_the_checkout_is_checked_at_the_universe_plans_path(checkout,
                                                                            monkeypatch):
    monkeypatch.setattr(vc, "repo_root", lambda: checkout.tmp / "elsewhere")
    st = vc.dispatch("pilot", plan_path=checkout.path, now=NOON)
    assert ("rev-parse", f"origin/main:{vc.PLAN_REL}") in checkout.asked
    assert st["plan_rel"] == vc.PLAN_REL == "research/v3/plan.json"
    assert vc.rel_of(vc.repo_root().parent / "research" / "v3" / "plan.json") == vc.PLAN_REL


def test_redo_and_retry_check_the_file_the_run_was_dispatched_from(checkout, monkeypatch):
    checkout.fail = {"b/x"}
    vc.dispatch("all-1", plan_path=checkout.all_path, now=NOON)
    checkout.fail = set()
    checkout.asked.clear()
    vc.redo("all-1", "b/x", now=NOON)
    assert ("rev-parse", "origin/main:research/v3/plan-all.json") in checkout.asked
    # a collected run with a failed coin: the retry runs under the kept copy, checked at plan-all
    st = vc.load_state("all-1")
    (vc.home() / "all-1-collected.json").write_text(json.dumps(
        {"not_reached": [], "failed": [f"{st['board'][0]}: ValueError: x"], "unmeasured": [],
         "downloads_failed": []}), encoding="utf-8")
    checkout.asked.clear()
    redo = vc.retry("all-1", now=NOON)
    assert redo["plan_rel"] == "research/v3/plan-all.json"
    assert ("rev-parse", "origin/main:research/v3/plan-all.json") in checkout.asked
    assert ("rev-parse", f"origin/main:{vc.PLAN_REL}") not in checkout.asked


def test_a_state_written_before_plan_rel_reads_the_universe_plans_path(checkout):
    checkout.fail = {"b/x"}
    vc.dispatch("pilot", plan_path=checkout.path, now=NOON)
    st = vc.load_state("pilot")
    st.pop("plan_rel")
    (vc.home() / "pilot.json").write_text(json.dumps(st), encoding="utf-8")
    checkout.fail = set()
    checkout.asked.clear()
    vc.redo("pilot", "b/x", now=NOON)
    assert ("rev-parse", f"origin/main:{vc.PLAN_REL}") in checkout.asked


def test_the_workflow_keeps_its_four_inputs():
    text = (ROOT / ".github" / "workflows" / "v3.yml").read_text(encoding="utf-8")
    block = text.split("inputs:", 1)[1].split("permissions:", 1)[0]
    names = [ln.strip()[:-1] for ln in block.splitlines()
             if ln.startswith("      ") and not ln.startswith("        ") and ln.strip()]
    assert set(names) == {"shards", "coin_list", "label", "plan_id"}


_FIND = r"""
import os, sys
sys.path[:0] = [sys.argv[1], os.path.join(sys.argv[1], ".github", "scripts")]
os.environ.update({"GITHUB_TOKEN": "", "GITHUB_REPOSITORY": "acct/analyzer-x", "INGEST_URL": "",
                   "TA_VENUE": "gate", "SHARD": "0", "SHARDS": "1", "COIN_LIST": "BTC_USDT",
                   "PLAN_ID": sys.argv[2]})
os.environ.pop("PLAN_FILE", None)
os.environ.pop("RES", None)
from tradingagents import v3_universe as vu
vu.PLAN_FILE = vu.Path(sys.argv[3]) / "plan.json"
import v3_shard
print(v3_shard.plan_file())
"""


def test_a_machine_finds_the_plan_its_dispatch_named_by_id(tmp_path):
    folder = tmp_path / "v3"
    path, plan = _all_plan(tmp_path)
    folder.mkdir()
    (folder / "plan-all.json").write_bytes(path.read_bytes())
    uni = {"version": vu.VERSION, "end_ms": 1, "start_ms": 0, "coins": []}
    uni["id"] = vu.plan_id(uni)
    vu.save(uni, folder / "plan.json")
    env = {k: v for k, v in os.environ.items() if k not in ("PLAN_FILE", "RES")}
    for pid, want in ((plan["id"], folder / "plan-all.json"), (uni["id"], folder / "plan.json"),
                      ("0" * 16, folder / "plan.json")):
        out = subprocess.run([sys.executable, "-c", _FIND, str(ROOT), pid, str(folder)],
                             capture_output=True, text=True, env=env, timeout=120)
        assert out.returncode == 0, out.stderr[-1500:]
        assert Path(out.stdout.strip().splitlines()[-1]) == want, \
            "the named plan's file, or plan.json - whose id the refusal then names"
