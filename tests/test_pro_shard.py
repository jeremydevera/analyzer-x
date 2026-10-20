"""One Pro Trader research machine, end to end on a made-up market
(.github/scripts/pro_shard.py, Oct 20, 2026), with no network.

What the review asked for (Oct 20, 2026): the shard's own path — every family's
settings, the dedupe that measures one signal set once and credits it to every
setting that made it, the four test months, the fees each window paid — then the
PC's reader (pro_search.read_lines -> pro_report.months), then the CHECK RUN over
the same bars, whose row must be the search's row and whose trades must add up.

The shard is a script that fixes RES/MODE/DAYS and patches br.SHORT_DAYS when it
loads, so it runs in its own process (in a temporary folder: it writes out/),
never inside the test session."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from tradingagents import pro_report as pr, pro_search as ps

ROOT = Path(__file__).resolve().parent.parent

# A 1d market ending yesterday: deep enough for the shard's 1,095-day window
# plus its 300-bar lead-in, so the lead-in is real (warm > 0)
_PROG = r'''
import json, os, sys, time
ROOT = sys.argv[1]
sys.path.insert(0, os.path.join(ROOT, ".github", "scripts"))
sys.path.insert(0, ROOT)
os.environ.update({"GITHUB_TOKEN": "", "GITHUB_REPOSITORY": "", "INGEST_URL": "",
                   "COIN_LIST": "", "TA_VENUE": "gate", "TFS": "1d", "SHARD": "0"})
import pandas as pd
from tradingagents import signals_pro as sp
# a COPY of the breakout under another name, added before the shard reads the
# list: its settings give exactly brk's signals, so the dedupe must measure
# each once and credit both (no real family is an exact copy of another)
sp.FAMILIES["dup"] = {**sp.FAMILIES["brk"], "title": "a copy of brk (test only)"}
import pro_shard as ps
import sweep_shard as ss
import check_run as cr
from tests.test_pro_strategies import _frame
# as on GitHub for a coin with no recorded minutes: an EMPTY book (prefetch
# never hands the engine None), so every trade pays the usual cost, counted
from tradingagents import cost_store
ss.cost_book = lambda sym: cost_store.empty()
ss.report = lambda *a, **k: None
ss.log = lambda *a, **k: None
n = 1500
day = 86_400_000
end_ms = (int(time.time() * 1000) // day) * day - day
o, h, lo, c, v, ts = _frame(n=n, seed=int(sys.argv[2]), step_s=86400,
                            start_ms=end_ms - (n - 1) * day, vol=0.03)
df = pd.DataFrame({"Date": pd.to_datetime(ts, unit="ms"), "Open": o, "High": h,
                   "Low": lo, "Close": c, "Volume": v})
ps.fx.klines = lambda sym, iv, need: df.tail(int(need)).reset_index(drop=True)
pre = {"fee": 0.00075, "liq": 4.5, "fund": [], "slip": 0.0003, "fine": None}
store = ps.Store()
info = ps.pro_pair("TEST_USDT", "1d", store, pre, 0, 1)
store.save()
whole, dfw, warm = ps.frame("TEST_USDT", "1d")
# THE CHECK RUN: the three most-traded lines of the search and the most-traded
# copy (credited, never measured under its own name), measured again
order = sorted(range(len(store.vals)), key=lambda k: -store.vals[k][0])
dup = [k for k in order if ps.NAMES[store.var[k]].startswith("pt_dup_")][:1]
order = order[:3] + dup
keys = []
for k in order:
    sl, tp = ps.BARRIERS["1d"][store.bar[k]]
    keys.append(f"{ps.NAMES[store.var[k]]}:1d:{round(sl * 100, 4):g}:{round(tp * 100, 4):g}")
cfgs = cr.parse_configs(",".join(keys), sp.spec_for, "Pro Trader")
back, dfw2, warm2 = ps.frame("TEST_USDT", "1d", end_s=int(info["last"]))
lines = cr.verify_pair("TEST_USDT", "1d", back, pre, cfgs,
                       window=lambda _df, _w=(dfw2, warm2): _w)
print(json.dumps({"info": info, "warm": warm, "picked": [store.vals[k] for k in order],
                  "keys": keys, "lines": lines, "fields": list(ps.FIELDS),
                  "last_bar": int(dfw["Date"].iloc[-1].timestamp()),
                  "last_bar_check": int(dfw2["Date"].iloc[-1].timestamp())}))
'''


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("pro_shard")
    out = subprocess.run([sys.executable, "-c", _PROG, str(ROOT), "5"], cwd=str(tmp),
                         capture_output=True, text=True, timeout=900)
    assert out.returncode == 0, out.stderr[-3000:]
    return tmp, json.loads(out.stdout.strip().splitlines()[-1])


def test_the_machine_measures_every_family_and_writes_its_lines(run):
    tmp, got = run
    info = got["info"]
    assert got["warm"] > 0, "the made-up market must give the window a real lead-in"
    assert info["rows"] > 0 and 0 < info["distinct"] <= info["settings"]
    L = ps.read_lines([tmp])
    assert L["coins"] == ["TEST"] and L["tfs"] == ["1d"]
    assert list(L["fields"]) == list(pr.FIELDS)
    fams = {n.split("_")[1] for n in np.asarray(L["names"])[np.unique(L["var"])]}
    # every family that traded on this market has lines, the baseline among them
    assert "rand" in fams and len(fams) >= 5, fams


def test_settings_with_the_same_signals_carry_the_same_numbers(run):
    tmp, got = run
    L = ps.read_lines([tmp])
    names = list(L["names"])
    # more lines than measured signal sets: the dedupe credited its members
    assert len(L["vals"]) > got["info"]["rows"]
    at = {(names[int(L["var"][k])], int(L["bar"][k])): k for k in range(len(L["vals"]))}
    twins = [(k, at[("pt_brk_" + nm[len("pt_dup_"):], b)]) for (nm, b), k in at.items()
             if nm.startswith("pt_dup_")]
    assert twins and len(twins) == sum(1 for nm, _b in at if nm.startswith("pt_brk_"))
    for k, j in twins:
        assert np.array_equal(L["vals"][k], L["vals"][j], equal_nan=True)


def test_the_four_test_months_and_their_fees_add_up(run):
    tmp, _got = run
    L = ps.read_lines([tmp])
    v = L["vals"]
    F = pr.F
    for a, b in (("t30", "t60"), ("t60", "t90"), ("t90", "t120"), ("t120", "trades")):
        assert (v[:, F[a]] <= v[:, F[b]]).all(), (a, b)
    mon = pr.months(L)
    assert np.allclose(mon[:, :, 0].sum(axis=1), v[:, F["trades"]])
    assert np.allclose(mon[:, :, 2].sum(axis=1), v[:, F["profit"]], atol=0.05)
    # every line knows what its trades paid (a book is always handed in)...
    assert np.isfinite(v[:, F["rt_paid"]]).all()
    assert (v[:, F["cost_unmeasured"]] > 0).any()
    # ...and the fees a window's trades paid never exceed the whole window's
    paid = v[:, F["rt_paid"]] * v[:, F["trades"]]
    for d in (30, 60, 90, 120):
        assert (v[:, F[f"c{d}"]] <= paid + 1e-4 * v[:, F["trades"]] + 1e-3).all(), d
        # and a window with trades paid at least both fees on each
        has = v[:, F[f"t{d}"]] > 0
        assert (v[has, F[f"c{d}"]] >= v[has, F[f"t{d}"]] * 2 * 0.075 - 1e-3).all(), d


def test_the_check_runs_row_is_the_searchs_row_and_its_trades_add_up(run):
    _tmp, got = run
    assert got["last_bar_check"] == got["last_bar"], "the check run measures the SAME bars"
    assert len(got["lines"]) == len(got["keys"])
    fi = {f: k for k, f in enumerate(got["fields"])}
    for want, line in zip(got["picked"], got["lines"], strict=True):
        row, trades = line["row"], line["trades"]
        assert row["trades"] == pytest.approx(want[fi["trades"]])
        assert row["wins"] == pytest.approx(want[fi["wins"]])
        assert row["profit"] == pytest.approx(want[fi["profit"]], abs=0.01)
        assert len(trades) == row["trades"]
        assert sum(1 for t in trades if t[4] > 0) == row["wins"]
        assert sum(t[4] for t in trades) == pytest.approx(row["profit"], abs=0.01 * len(trades))
        # each test month's trades, by their exit, are the search's month
        # (the engine counts back from the last bar's open: sweep_shard's
        # recent_windows)
        for d in (30, 60, 90, 120):
            cut = got["last_bar"] * 1000 - d * 86_400_000
            n = sum(1 for t in trades if t[1] >= cut)
            assert n == pytest.approx(want[fi[f"t{d}"]]), d


def test_a_cut_last_line_is_skipped_and_named(tmp_path):
    good = {"cfg": "pt_brk_n0g0c0:1d:2:6", "trades": []}
    f = tmp_path / "pro-trades-3.jsonl"
    f.write_text(json.dumps(good) + "\n" + '{"cfg": "pt_brk', encoding="utf-8")
    lines, cut = ps.read_trades([tmp_path])
    assert lines == [good] and cut == [str(f)]


def test_machines_that_measured_other_settings_are_refused(tmp_path):
    def write(folder, names):
        folder.mkdir()
        np.savez_compressed(folder / "pro-0.npz", names=np.array(names),
                            fields=np.array(pr.FIELDS), coins=np.array(["A"]),
                            tfs=np.array(["1d"]), coin=np.zeros(1, np.int32),
                            tf=np.zeros(1, np.int8), var=np.zeros(1, np.int32),
                            bar=np.zeros(1, np.int8),
                            vals=np.zeros((1, len(pr.FIELDS)), np.float32),
                            barriers_1d=np.array([(0.02, 0.06)]))
    write(tmp_path / "a", ["pt_rand_s0r0"])
    write(tmp_path / "b", ["pt_rand_s1r0"])
    with pytest.raises(ValueError, match="other settings"):
        ps.read_lines([tmp_path / "a", tmp_path / "b"])
