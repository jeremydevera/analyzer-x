"""One confluence research machine end to end on a made-up market
(.github/scripts/cq_shard.py, Oct 21, 2026), with no network: the search and
the luck search on one coin + timeframe, every pick measured again with its
trades, the three stretches cut from the engine's own window counts, the
stop/targets legal, a coin too young for its windows skipped with why, and
the run repeating exactly from its seed.

The shard fixes RES/MODE/DAYS and patches br.SHORT_DAYS when it loads, so it
runs in its own process (in a temporary folder: it writes out/), never inside
the test session."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tradingagents import backtest_report as br, cq_core as cq, signals_cq as sq

ROOT = Path(__file__).resolve().parent.parent

_PROG = r'''
import json, os, sys
ROOT = sys.argv[1]
sys.path.insert(0, os.path.join(ROOT, ".github", "scripts"))
sys.path.insert(0, ROOT)
os.environ.update({"GITHUB_TOKEN": "", "GITHUB_REPOSITORY": "", "INGEST_URL": "",
                   "COIN_LIST": "", "TA_VENUE": "gate", "TFS": "4h", "SHARD": "0",
                   "SEARCH": "40,3,2", "LUCK": "all", "MIN_TRADES": "5"})
import pandas as pd
import cq_shard as cs
import sweep_shard as ss
from tests.test_pro_strategies import _frame
from tradingagents import cost_store
# as on GitHub for a coin with no recorded minutes: an EMPTY book, so every
# trade pays the usual cost, counted
ss.cost_book = lambda sym: cost_store.empty()
ss.report = lambda *a, **k: None
ss.log = lambda *a, **k: None
cs._venue.kind = lambda sym: "crypto"
step = 4 * 3_600_000
end_ms = 1_790_812_800_000            # Oct 01, 2026 00:00 UTC: inside the news calendar


def market(n, seed):
    o, h, lo, c, v, ts = _frame(n=n, seed=seed, step_s=step // 1000,
                                start_ms=end_ms - (n - 1) * step, vol=0.012)
    return pd.DataFrame({"Date": pd.to_datetime(ts, unit="ms"), "Open": o, "High": h,
                         "Low": lo, "Close": c, "Volume": v})


frames = {"TEST_USDT": market(4800, int(sys.argv[2])), "YOUNG_USDT": market(1500, 3)}
cs.fx.klines = lambda sym, iv, need: frames[sym].tail(int(need)).reset_index(drop=True)
pre = {"fee": 0.00075, "liq": 4.5, "fund": [], "slip": 0.0003, "fine": None, "meta": {}}
rec = {"coin": "TEST", "tfs": {}}
info = cs.cq_pair("TEST_USDT", "4h", pre, rec)
young = cs.cq_pair("YOUNG_USDT", "4h", pre, {"coin": "YOUNG", "tfs": {}})
bars, ks = cs.barriers_for("4h", 0.0021, 4.5)
fake = {"trades": 9, "recents": {
    240: {"trades": 3, "wins": 1, "profit": -0.5, "rt_sum": 0.6},
    360: {"trades": 5, "wins": 2, "profit": 0.25, "rt_sum": 1.0},
    cs.whole_days("4h"): {"trades": 9, "wins": 4, "profit": 1.75, "rt_sum": 1.8}}}
print(json.dumps({"info": info, "rec": rec, "young": young,
                  "bars": [[sl, tp, k] for (sl, tp), k in zip(bars, ks)],
                  "split": [list(p) for p in cs.stats_from(fake, "4h")]}, default=str))
'''


def _run(tmp, seed="5"):
    out = subprocess.run([sys.executable, "-c", _PROG, str(ROOT), seed], cwd=str(tmp),
                         capture_output=True, text=True, timeout=1200)
    assert out.returncode == 0, out.stderr[-3000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("cq1")), _run(tmp_path_factory.mktemp("cq2"))


def test_the_machine_searches_and_measures_every_pick_again(runs):
    got = runs[0]
    assert "why" not in got["info"] and "error" not in got["info"], got["info"]
    out = got["rec"]["tfs"]["4h"]
    s = out["search"]
    assert s["seed"] == cq.seed_of("TEST", "4h", sq.VERSION)
    assert 0 < s["tried"] <= 40 * 3 and 1 <= len(s["rounds"]) <= 3
    assert s["n_errors"] == 0, s["errors"]
    assert s["picks"] and s["final"] in s["picks"]
    legal = {(b[0], b[1]) for b in out["barriers"]}
    for k, p in s["picks"].items():
        name, sl, tp, bucket, tun, chk, tst = p["cand"]
        assert sq.spec_for(name)["name"] == name and str(bucket) == k
        assert (sl, tp) in legal and tun[0] >= 5
        t = p["trades"]
        assert "drift" not in t, t.get("drift")
        assert t["row"]["trades"] == tun[0] + chk[0] + tst[0] == len(t["trades"])


def test_the_luck_search_measures_random_entries_the_same_way(runs):
    luck = runs[0]["rec"]["tfs"]["4h"]["luck"]
    assert luck["seed"] == cq.seed_of("TEST", "4h", sq.VERSION, "luck")
    assert luck["picks"] and luck["n_errors"] == 0
    assert all(r[0].startswith("cq_rn") for rd in luck["rounds"] for r in rd["best"])


def test_a_run_repeats_exactly_from_its_seed(runs):
    a, b = (r["rec"]["tfs"]["4h"] for r in runs)
    for part in ("search", "luck"):
        x, y = dict(a[part]), dict(b[part])
        x.pop("seconds")
        y.pop("seconds")
        assert x == y, part


def test_every_stop_target_is_the_grids_own_and_pays_two_to_one(runs):
    grid = set(br.pairs_for("4h"))
    assert runs[0]["bars"]
    for sl, tp, k in runs[0]["bars"]:
        assert sl <= 0.02 and tp > sl and sl * 100 < 0.8 * 4.5
        assert (sl, tp) in grid
        assert cq.bucket(cq.payout_of(sl, tp, 0.0021)) == k


def test_the_three_stretches_are_cut_from_the_engines_own_window_counts(runs):
    tun, chk, tst = runs[0]["split"]
    assert tst == [3, 1, -0.5, 0.6]
    assert chk == [2, 1, 0.75, 0.4]
    assert tun == [4, 2, 1.5, 0.8]


def test_a_coin_too_young_for_its_windows_is_skipped_and_says_why(runs):
    assert runs[0]["young"]["why"].startswith("only 249 days")
