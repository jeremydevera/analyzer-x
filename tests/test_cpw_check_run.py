"""The Crypto-Predictor CHECK RUN (.github/scripts/cpw_shard.py, CONFIGS): the
winners of the search measured again on every coin with each trade kept, so a
results table can show every row's trades, its worst losing run and its months
(CLAUDE.md kit items 6 and B).

The guard that matters: the check run's row IS the search's row — the same
`sweep_shard.run_pair`, asked for one setting at one stop/target — and its
trades add up to it. The shard is a script that fixes RES/MODE in the
environment when it loads, so it runs in its own process here, never inside
the test session (where it would change RES for every test after it)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# A made-up 15m market ending now (the shard's window counts back from the
# clock), driven through the search's path and the check run's path with no
# network: the coin's costs are handed in (`learned`), the minute book is
# absent (the bar rule settles exits), and nothing is reported or posted.
_PROG = r'''
import json, os, sys, time, io
sys.path.insert(0, ".github/scripts")
sys.path.insert(0, ".")
os.environ.update({"GITHUB_TOKEN": "", "GITHUB_REPOSITORY": "", "INGEST_URL": "",
                   "COIN_LIST": "", "TA_VENUE": "gate"})
import pandas as pd
import cpw_shard as cs
import sweep_shard as ss
from tests.test_cpw_strategies import _frame
ss.cost_book = lambda sym: None
ss.report = lambda *a, **k: None
ss.log = lambda *a, **k: None
n = 3500
end_ms = (int(time.time()) // 900) * 900 * 1000 - 900 * 1000
o, h, lo, c, v, ts = _frame(n=n, seed=int(sys.argv[1]), start_ms=end_ms - (n - 1) * 900 * 1000,
                            vol=0.006)
df = pd.DataFrame({"Date": pd.to_datetime(ts, unit="ms"), "Open": o, "High": h,
                   "Low": lo, "Close": c, "Volume": v})
pre = {"fee": 0.00075, "liq": 4.5, "fund": [], "slip": 0.0003, "fine": None}
name = sys.argv[2]
# THE SEARCH: every stop/target of the timeframe, as cpw_pair asks it
dfw, warm = ss.window(df)
buf = io.StringIO()
orig = ss.window
ss.window = lambda _df: (dfw, warm)
ss.run_pair("TEST_USDT", "15m", buf, signals=[name], learned={**pre, "df": df})
ss.window = orig
search = [json.loads(x) for x in buf.getvalue().splitlines() if x.strip()]
search = [r for r in search if r.get("signal") == name]
# THE CHECK RUN, for the three most-traded stop/targets the search wrote
search.sort(key=lambda r: -r["trades"])
picks = search[:3]
cfgs = cs.parse_configs(",".join(f"{name}:15m:{r['sl']}:{r['tp']}" for r in picks))
lines = cs.verify_pair("TEST_USDT", "15m", df, pre, cfgs)
print(json.dumps({"search": picks, "lines": lines,
                  "bar_ms": [int(x) for x in dfw["Date"].to_numpy().astype("datetime64[ms]").astype("int64")]}))
'''


def _run(seed: int, name: str) -> dict:
    out = subprocess.run([sys.executable, "-c", _PROG, str(seed), name], cwd=str(ROOT),
                         capture_output=True, text=True, timeout=600)
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("seed,name", [(7, "cp_st_f1u0h0x0i0d0"), (3, "cp_bb_z1j1k1c1x1h0")])
def test_the_check_runs_row_is_the_searchs_row_and_its_trades_add_up(seed, name):
    got = _run(seed, name)
    assert got["search"], "the made-up market must trade this setting"
    assert len(got["lines"]) == len(got["search"])
    bars = set(got["bar_ms"])
    for want, line in zip(got["search"], got["lines"], strict=True):
        row, trades = line["row"], line["trades"]
        assert line["cfg"] == f"{name}:15m:{want['sl']}:{want['tp']}"
        # the same function, the same answer — every field of the row
        assert row == want
        # and the kept trades ARE that row
        assert len(trades) == row["trades"]
        assert sum(1 for t in trades if t[4] > 0) == row["wins"]
        assert sum(t[4] for t in trades) == pytest.approx(row["profit"], abs=0.01 * len(trades))
        for entry_ms, exit_ms, side, why, _pnl in trades:
            assert entry_ms in bars, "an entry is the open of a bar of the window"
            assert exit_ms > entry_ms and side in (1, -1)
            assert why in ("TP", "SL", "END", "LIQ")
        assert [t[0] for t in trades] == sorted(t[0] for t in trades)


@pytest.mark.parametrize("bad", [
    "cp_st_f1u0h0x0i0d0:15m:0.25:1.0",      # 0.25 is not a 15m stop of the grid
    "cp_st_f1u0h0x0i0d0:2h:0.5:1.0",        # not a timeframe the search measures
    "cp_st_f9u0h0x0i0d0:15m:0.5:1.0",       # not a setting
    "trend50:15m:0.5:1.0",                  # not a Crypto-Predictor rule at all
])
def test_a_config_the_search_did_not_measure_is_refused(bad):
    prog = ("import sys;sys.path.insert(0,'.github/scripts');sys.path.insert(0,'.');"
            "import cpw_shard as cs\n"
            f"try:\n    cs.parse_configs({bad!r})\nexcept ValueError as e:\n    print('REFUSED', e)\n"
            "else:\n    print('ACCEPTED')")
    out = subprocess.run([sys.executable, "-c", prog], cwd=str(ROOT), capture_output=True,
                         text=True, timeout=300,
                         env={**__import__("os").environ, "GITHUB_TOKEN": "", "GITHUB_REPOSITORY": ""})
    assert out.stdout.strip().splitlines()[-1].startswith("REFUSED"), out.stdout + out.stderr[-800:]


def test_the_workflow_hands_the_check_run_its_settings_and_keeps_its_trades():
    wf = (ROOT / ".github" / "workflows" / "cpw.yml").read_text(encoding="utf-8")
    assert "      configs:\n" in wf
    assert "CONFIGS: ${{ github.event.inputs.configs }}" in wf
    assert "name: cpw-trades-${{ matrix.shard }}" in wf
    assert "path: out/cpw-trades-*.jsonl" in wf
    # workflow_dispatch takes at most ten inputs
    inputs = wf.split("inputs:")[1].split("permissions:")[0]
    assert sum(1 for line in inputs.splitlines()
               if line.startswith("      ") and not line.startswith("        ")
               and line.strip().endswith(":")) <= 10
