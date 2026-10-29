"""One Backtest v3 research machine end to end on a made-up market
(.github/scripts/v3_shard.py, Part 2b), with no network: every coin it was
dealt measured by `v3_measure.measure_coin` at the research's risk, its record
written whole and stamped with the machine, a coin that raises redone by
itself and named when it never recovers, every coin left out named, and a
machine whose plan is not the dispatch's refusing to measure anything.

The shard clears RES and imports sweep_shard when it loads, and writes out/,
so it runs in its own process in a temporary folder, never inside the test
session (the pattern of tests/test_cq_shard.py). The world is
tests/test_v3_measure.py's calm metal, on ONE timeline (RCA-2026-09-12-A)."""
from __future__ import annotations

import gzip
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tradingagents import v3_research as vrs, v3_rules as vr, v3_universe as vu

ROOT = Path(__file__).resolve().parent.parent

_PROG = r'''
import json, os, sys
ROOT, PLAN, PLAN_ID, COINS = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
MODE = sys.argv[6]
sys.path.insert(0, os.path.join(ROOT, ".github", "scripts"))
sys.path.insert(0, ROOT)
os.environ.update({"GITHUB_TOKEN": "", "GITHUB_REPOSITORY": "acct/analyzer-x",
                   "GITHUB_RUN_ID": "4242", "GITHUB_SHA": "abc123", "INGEST_URL": "",
                   "TA_VENUE": sys.argv[5], "SHARD": "0", "SHARDS": "1", "COIN_LIST": COINS,
                   "RUNS": "2", "PLAN_FILE": PLAN, "PLAN_ID": PLAN_ID, "RES": "v3"})
import time as _time
_time.sleep = lambda s: None
import tests.test_v3_measure as tm
import tradingagents.auto_trader as at
from tradingagents import cost_store, v3_measure as vm
vm.UNSEEN_DAYS = 3
at.maker_fee_floor = lambda *a, **k: 0.0002
at.fee_floor = lambda *a, **k: 0.00075
cost_store.engine_book = lambda *a, **k: tm._book(tm.START_A // 1000)
import v3_shard as sh
sh.ss.report = lambda *a, **k: None
sh.ss.log = lambda *a, **k: None
if MODE == "cutoff":
    sh.RETRY_CUTOFF_S = -1          # the 4.8 h cutoff has passed: no coin is redone
# the exchange trades every coin asked for but GONE_USDT
sh.ss.eligible = lambda: sorted(c for c in sh.ss.COIN_LIST if c != "GONE_USDT")
calls = {}


class World(tm.FakeFx):
    """XAU_USDT and the Chinese-named coin read the calm metal; FLAKY_USDT's first candle read
    is cut mid-body, then it reads like the others; DEAD_USDT's never answers; KILL_USDT's
    read is the runner being killed (GitHub's time limit)."""

    def klines(self, sym, iv, limit):
        calls[sym] = calls.get(sym, 0) + 1
        if sym == "KILL_USDT":
            raise KeyboardInterrupt
        if sym == "DEAD_USDT" or (sym == "FLAKY_USDT" and calls[sym] == 1):
            raise ConnectionError(f"{sym}: IncompleteRead(183452 bytes read)")
        return super().klines(sym, iv, limit)


sh.FX = World(tm.START_A, tm.END_A, tm._dips(tm.OLD_DIP, tm.NEW_DIP))
try:
    code = sh.main()
except KeyboardInterrupt:
    code = "killed"
print(json.dumps({"code": code, "calls": calls,
                  "finished": getattr(sh.ss.report, "finished", None)}))
'''


def _plan(tmp, coins):
    """The calm metal's window as a plan file every coin of `coins` is calm in."""
    import tests.test_v3_measure as tm

    calm = {"2026-09": list(coins), "2026-10": list(coins)}
    plan = {**tm._plan(tm.START_A, tm.END_A, calm, kinds=dict.fromkeys(coins, "metals")),
            "version": vu.VERSION, "venue": "Gate", "coins": sorted(coins),
            "start": "Sep 24, 2026 8:00pm", "end": "Oct 04, 2026 8:00pm"}
    plan["id"] = vu.plan_id(plan)
    path = vu.save(plan, Path(tmp) / "plan.json")
    return path, plan["id"]


def _run(tmp, asked, plan_id=None, venue="gate", inside=None, mode=""):
    path, pid = _plan(tmp, inside or [c for c in asked if c not in ("OUT_USDT", "GONE_USDT")]
                      or ["XAU_USDT"])
    out = subprocess.run([sys.executable, "-c", _PROG, str(ROOT), str(path), plan_id or pid,
                          ",".join(asked), venue, mode], cwd=str(tmp), capture_output=True,
                         text=True, timeout=900, encoding="utf-8")
    assert out.returncode == 0, out.stderr[-3000:]
    got = json.loads(out.stdout.strip().splitlines()[-1])
    rep = json.loads((Path(tmp) / "out" / "v3-report-0.json").read_text(encoding="utf-8"))
    return got, rep, pid


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("v3shard")
    got, rep, pid = _run(tmp, ["XAU_USDT", "FLAKY_USDT", "DEAD_USDT", "OUT_USDT", "GONE_USDT",
                               CHINESE])
    return tmp, got, rep, pid


CHINESE = "龙虾_USDT"          # a coin the exchange names in Chinese


def _record(tmp, sym):
    with gzip.open(vrs.coin_file(Path(tmp) / "out" / "v3", sym), "rt", encoding="utf-8") as fh:
        return json.load(fh)


def test_every_coin_it_can_measure_is_one_whole_record_at_the_research_risk(world):
    tmp, got, rep, pid = world
    assert got["code"] == 0
    rec = _record(tmp, "XAU_USDT")
    # measure_coin's own record, at $5 a trade (never the tab's $1) and the plan the dispatch named
    assert rec["coin"] == "XAU_USDT" and rec["risk_usd"] == vr.RESEARCH_RISK_USD == 5.0
    assert rec["runs"] == 2 and rec["plan_id"] == pid and rec["version"] == 2
    assert rec["combos"] and all(len(c["random"]) == 2 for c in rec["combos"].values())
    assert rec["machine"] == {"repo": "acct/analyzer-x", "run": "4242", "shard": 0, "sha": "abc123"}
    entry = next(e for e in rep["report"] if e["coin"] == "XAU_USDT")
    assert entry["combos"] == len(rec["combos"]) and entry["bytes"] > 0 and "error" not in entry
    assert rep["plan_id"] == pid and rep["risk_usd"] == 5.0 and rep["runs"] == 2


def test_a_coin_that_fails_once_is_redone_by_itself_and_one_that_never_recovers_is_named(world):
    tmp, got, rep, _pid = world
    flaky = next(e for e in rep["report"] if e["coin"] == "FLAKY_USDT")
    assert flaky["tries"] == 2 and "error" not in flaky
    assert _record(tmp, "FLAKY_USDT")["coin"] == "FLAKY_USDT"
    dead = next(e for e in rep["report"] if e["coin"] == "DEAD_USDT")
    assert dead["tries"] == 3 and dead["error"].startswith("ConnectionError: DEAD_USDT")
    assert not vrs.coin_file(Path(tmp) / "out" / "v3", "DEAD_USDT").exists(), \
        "a coin that never recovered leaves no record behind"
    # DEAD_USDT's three tries each died on its first candle read
    assert got["calls"]["DEAD_USDT"] == 3


def test_every_coin_left_out_is_named_with_why(world):
    _tmp, _got, rep, _pid = world
    why = {e["coin"]: e.get("why") for e in rep["report"] if "why" in e}
    assert why["GONE_USDT"] == "the exchange is not trading it now"
    assert why["OUT_USDT"] == "not in the plan's universe"
    assert {e["coin"] for e in rep["report"]} == {"XAU_USDT", "FLAKY_USDT", "DEAD_USDT",
                                                   "OUT_USDT", "GONE_USDT", CHINESE}


def test_a_coin_named_in_chinese_is_claimed_measured_and_named_in_the_report(world):
    tmp, got, rep, _pid = world
    path = vrs.coin_file(Path(tmp) / "out" / "v3", CHINESE)
    assert re.fullmatch(r"x[0-9a-f]+\.json\.gz", path.name) and path.exists()
    assert path.name == "x" + CHINESE.encode("utf-8").hex() + ".json.gz"
    assert _record(tmp, CHINESE)["coin"] == CHINESE
    entry = next(e for e in rep["report"] if e["coin"] == CHINESE)
    assert entry["combos"] > 0 and "error" not in entry and not entry.get("unfinished")


def test_progress_counts_the_coins_finished_as_they_finish(world):
    _tmp, got, rep, _pid = world
    # XAU, FLAKY (on its redo) and the Chinese-named coin; never the dead one or the left-out two
    assert got["finished"] == 3
    assert not [e for e in rep["report"] if e.get("unfinished")],         "a finished run leaves no placeholder behind"


def test_a_coin_claimed_when_the_machine_is_killed_is_named_in_the_report_on_disk(tmp_path):
    got, rep, _pid = _run(tmp_path, ["KILL_USDT", "XAU_USDT"], mode="kill")
    assert got["code"] == "killed"
    kill = next(e for e in rep["report"] if e["coin"] == "KILL_USDT")
    assert kill["unfinished"] is True and kill["error"].startswith("claimed, not finished")
    assert kill["tries"] == 1
    assert not vrs.coin_file(tmp_path / "out" / "v3", "KILL_USDT").exists()


def test_a_coin_still_queued_when_the_retry_cutoff_passes_is_named_not_redone(tmp_path):
    got, rep, _pid = _run(tmp_path, ["XAU_USDT", "FLAKY_USDT", "DEAD_USDT"], mode="cutoff")
    assert got["code"] == 0
    by = {e["coin"]: e for e in rep["report"]}
    for coin in ("FLAKY_USDT", "DEAD_USDT"):
        assert by[coin]["error"] == "not redone: out of time" and by[coin]["tries"] == 1
        assert not by[coin].get("unfinished")
    assert got["calls"]["FLAKY_USDT"] == 1 and got["calls"]["DEAD_USDT"] == 1
    assert "error" not in by["XAU_USDT"] and by["XAU_USDT"]["combos"] > 0


def test_a_machine_dealt_no_coins_measures_nothing(tmp_path):
    got, rep, _pid = _run(tmp_path, [], inside=["XAU_USDT"])
    assert got["code"] == 2 and rep["report"] == []
    assert rep["refused"].startswith("no coins were dealt to this machine's account")
    assert not (tmp_path / "out" / "v3").exists() or not list((tmp_path / "out" / "v3").iterdir())


def test_a_machine_whose_plan_is_not_the_dispatchs_measures_nothing(tmp_path):
    got, rep, pid = _run(tmp_path, ["XAU_USDT"], plan_id="0" * 16)
    assert got["code"] == 2 and rep["report"] == []
    assert rep["refused"].startswith(f"this checkout's plan is {pid}, the dispatch named "
                                     + "0" * 16)
    assert not (tmp_path / "out" / "v3").exists() or not list((tmp_path / "out" / "v3").iterdir())


def test_a_machine_not_on_gate_measures_nothing(tmp_path):
    got, rep, _pid = _run(tmp_path, ["XAU_USDT"], venue="mexc")
    assert got["code"] == 2 and rep["refused"].startswith("TA_VENUE is 'mexc'")


def test_the_workflow_takes_exactly_what_the_dispatch_sends():
    text = (ROOT / ".github" / "workflows" / "v3.yml").read_text(encoding="utf-8")
    block = text.split("inputs:", 1)[1].split("permissions:", 1)[0]
    names = re.findall(r"^      ([a-z_]+):\s*$", block, flags=re.M)
    assert len(names) <= 10                      # GitHub allows exactly ten
    assert set(names) == {"shards", "coin_list", "label", "plan_id"}
    assert 'run-name: "Backtest v3 research · ${{ inputs.label }}"' in text
    assert "TA_VENUE: gate" in text and "timeout-minutes: 350" in text
    assert "python .github/scripts/v3_shard.py" in text and "v3-out-${{ matrix.shard }}" in text
    assert "out/v3/*.json.gz" in text and "out/v3-report-*.json" in text
    for env in ("COIN_LIST", "PLAN_ID", "SHARD", "SHARDS", "GITHUB_TOKEN"):
        assert f"          {env}: " in text, env
