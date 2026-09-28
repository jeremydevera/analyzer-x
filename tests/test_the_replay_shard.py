"""The GitHub machine of the watcher replay tests only what could be armed.

Operator, Sep 28, 2026: "Then do the backtest replay so i know the pnl for
every day". The machine walks every combination the watcher could ever switch
on — TP strictly wider than SL, a stop inside 80% of liquidation, a cost under
20% of the target — with the market grid's own signals, walk and per-trade
formula, and writes only the ones that pass at some daily check. These tests
drive `replay_pair` on made-up candles (no network) and pin each filter.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import re
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".github" / "scripts"


class _Groups:
    value = "classic,preset"


rs_groups = _Groups()


@pytest.fixture
def rs(monkeypatch):
    for k in ("GITHUB_TOKEN", "GITHUB_REPOSITORY", "COIN_LIST", "INGEST_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("START", "2026-09-01")
    # the shared rules only, so the learned formulas that really exist for
    # GPNSTOCK do not join these made-up candles (the group tests set it)
    monkeypatch.setenv("REPLAY_GROUPS", getattr(rs_groups, "value", "classic,preset"))
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("replay_shard_test",
                                                  SCRIPTS / "replay_shard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop("replay_shard_test", None)


def _bars(n_hours: int, start: dt.datetime) -> pd.DataFrame:
    """A 1h series that rises 0.4% every bar: every long hits a 1% target in
    three bars and never touches a stop."""
    rows, px = [], 100.0
    for i in range(n_hours):
        o = px
        c = px * 1.004
        rows.append({"Date": pd.Timestamp(start + dt.timedelta(hours=i)),
                     "Open": o, "High": c * 1.0005, "Low": o * 0.9999,
                     "Close": c, "Volume": 1.0})
        px = c
    return pd.DataFrame(rows)


@pytest.fixture
def world(rs, monkeypatch):
    from tradingagents import auto_trader as at, backtest_report as br
    from tradingagents.dataflows import mexc_futures as fx

    start = dt.datetime(2026, 7, 20)
    now = dt.datetime(2026, 9, 10)
    n = int((now - start).total_seconds() // 3600)
    df = _bars(n, start)
    monkeypatch.setattr(fx, "klines", lambda sym, iv, limit: df.tail(limit))
    monkeypatch.setattr(at, "_closed_bars", lambda d, bs: d)
    monkeypatch.setattr(rs.time, "time", lambda: now.timestamp())
    # one rule, long every 6th bar
    monkeypatch.setattr(br, "SIGNALS", ["bb20"])
    monkeypatch.setattr(at, "_dirs_for_backtest",
                        lambda key, hi, *a, **k: [1 if i % 6 == 0 else 0
                                                  for i in range(len(hi))])
    monkeypatch.setattr(br, "pairs_for",
                        lambda tf: [(0.01, 0.01), (0.007, 0.01), (0.04, 0.05),
                                    (0.005, 0.0006), (0.006, 0.012)])
    cost = {"fee": 0.0002, "slip": 0.0001, "liq": 4.5, "fund": [],
            "rt": 0.0006}
    return {"cost": cost, "df": df}


def _run(rs, world, tf="1h"):
    stats = {"pairs": 0, "tested": 0, "kept": 0, "short": [], "spans": {}}
    lines = rs.replay_pair("GPNSTOCK_USDT", tf, world["cost"], stats)
    import json

    return [json.loads(x) for x in lines], stats


def test_only_tp_wider_than_sl_inside_the_wall_and_cheap_enough_is_tested(rs, world):
    combos, stats = _run(rs, world)
    # (0.01, 0.01) equal: refused. (0.04, 0.05): a 4% stop past 80% of the
    # 4.5% wall: refused. (0.005, 0.0006): TP narrower: refused.
    # (0.007, 0.01) and (0.006, 0.012) are the two tested.
    assert stats["tested"] == 2
    assert {(c["sl"], c["tp"]) for c in combos} <= {(0.7, 1.0), (0.6, 1.2)}


def test_a_cost_over_a_fifth_of_the_target_is_not_tested(rs, world):
    world["cost"]["rt"] = 0.0021           # 21% of a 1.0% target, 17.5% of 1.2%
    _combos, stats = _run(rs, world)
    assert stats["tested"] == 1


def test_a_passing_combination_carries_its_v2_id_and_every_trade(rs, world):
    from tradingagents import backtest_report as br, fast_grid as fg

    combos, _ = _run(rs, world)
    c = next(c for c in combos if c["tp"] == 1.0)
    assert c["id"] == br.row_code("GPNSTOCK", "1h", "bb20", 0.0, 0.7, 1.0,
                                  "flat", res="1m")
    won = [t for t in c["trades"] if t[3] and t[2] > 0]
    assert won, "a rising series wins every long"
    expect = fg.trade_pnl(0.01, fg.WHY_TP, 0.0, margin=5.0, lev=20,
                          fee=0.0003)
    assert won[0][2] == pytest.approx(round(expect, 4))
    assert all(t[1] > t[0] for t in c["trades"]), "exit after entry"


def test_no_trade_is_taken_inside_the_warm_up(rs, world):
    combos, _ = _run(rs, world)
    first_measured = dt.datetime(2026, 8, 2).timestamp() * 1000
    for c in combos:
        assert min(t[0] for t in c["trades"]) >= first_measured - 3_600_000


def test_a_combination_that_never_passes_is_counted_not_written(rs, world, monkeypatch):
    from tradingagents import auto_trader as at

    # long every 6th bar on a series that now FALLS: every trade loses
    df = world["df"].copy()
    df["Open"], df["Close"] = df["Close"][::-1].values, df["Open"][::-1].values
    df["High"] = df[["Open", "Close"]].max(axis=1) * 1.0005
    df["Low"] = df[["Open", "Close"]].min(axis=1) * 0.9995
    from tradingagents.dataflows import mexc_futures as fx

    monkeypatch.setattr(fx, "klines", lambda sym, iv, limit: df.tail(limit))
    combos, stats = _run(rs, world)
    assert combos == [] and stats["tested"] == 2 and stats["kept"] == 0


def test_it_downloads_only_what_the_replay_reads(rs, world):
    """58 days of 1h is ~1,400 bars, never the 10,000 a year-deep fetch asks for."""
    need = rs.bars_needed("1h", int(dt.datetime(2026, 9, 28).timestamp() * 1000))
    assert 1_400 < need < 2_000


def test_the_workflow_runs_this_script_on_the_operators_clock():
    wf = (ROOT / ".github" / "workflows" / "replay.yml").read_text("utf-8")
    assert "python .github/scripts/replay_shard.py" in wf
    assert "America/New_York" in wf, "the daily checks are the operator's midnights"
    assert "out/replay-" in wf


def test_the_groups_input_decides_which_rules_are_walked(rs, world, monkeypatch):
    """Operator, Sep 28, 2026: "did you used all group available?" / "i want
    all then". A pair's learned formulas are ITS OWN (signals_learned.for_pair)
    and join the shared rules only when their group is asked for."""
    from tradingagents import signals_learned as sl, signals_ml as sm

    monkeypatch.setattr(sl, "for_pair", lambda coin, tf: ["lx_GPNSTOCK_1h_1"])
    monkeypatch.setattr(sm, "for_pair", lambda coin, tf: [])
    monkeypatch.setattr(rs, "GROUPS", ("sep25",))
    combos, stats = _run(rs, world)
    assert stats["tested"] == 2, "only the one learned formula, both pairs"
    assert {c["signal"] for c in combos} == {"lx_GPNSTOCK_1h_1"}
    assert {c["group"] for c in combos} == {"sep25"}
    monkeypatch.setattr(rs, "GROUPS", ("classic", "preset", "sep25", "sep27ml"))
    _combos, stats = _run(rs, world)
    assert stats["tested"] == 4, "bb20 and the learned formula"


def test_a_pair_with_nothing_in_the_asked_groups_downloads_nothing(rs, world, monkeypatch):
    from tradingagents import signals_ml as sm
    from tradingagents.dataflows import mexc_futures as fx

    asked = []
    monkeypatch.setattr(fx, "klines", lambda *a, **k: asked.append(a))
    monkeypatch.setattr(sm, "for_pair", lambda coin, tf: [])
    monkeypatch.setattr(rs, "GROUPS", ("sep27ml",))
    combos, stats = _run(rs, world)
    assert combos == [] and asked == [] and stats["tested"] == 0


def test_every_written_combination_names_its_group(rs, world):
    combos, _ = _run(rs, world)
    assert combos and all(c["group"] == "classic" for c in combos)


def test_all_means_every_group():
    import os
    import subprocess
    import sys as _sys

    code = ("import os,sys;sys.path.insert(0,'.github/scripts');"
            "os.environ['REPLAY_GROUPS']='all';import replay_shard as r;print(','.join(r.GROUPS))")
    out = subprocess.run([_sys.executable, "-c", code], capture_output=True,
                         text=True, cwd=str(ROOT), timeout=120,
                         env={**os.environ, "GITHUB_TOKEN": "", "GITHUB_REPOSITORY": ""})
    assert out.stdout.strip().splitlines()[-1] == "classic,preset,sep25,sep27ml", out.stderr[-400:]


def test_the_groups_setting_survives_a_bash_shell():
    """GROUPS is a bash builtin, never passed to a child: GitHub runs this
    step through bash, so the setting must travel under another name — and
    arrive. Run exactly the way the workflow does: bash sets it, python reads."""
    import shutil
    import subprocess

    bash = shutil.which("bash")
    if not bash:
        pytest.skip("no bash on this machine")
    wf = (ROOT / ".github" / "workflows" / "replay.yml").read_text("utf-8")
    assert "REPLAY_GROUPS: ${{ github.event.inputs.groups }}" in wf
    assert re.search(r"^\s+GROUPS:", wf, re.M) is None, "the bash builtin name"
    import os
    import sys as _sys

    probe = "import os; print(os.environ.get('REPLAY_GROUPS'))"
    out = subprocess.run([bash, "-c", 'REPLAY_GROUPS=sep25 "$PY" -c "$PROBE"'],
                         capture_output=True, text=True, timeout=60,
                         env={**os.environ, "PY": _sys.executable, "PROBE": probe})
    assert out.stdout.strip() == "sep25", out.stderr[-300:]


def test_a_coin_nobody_claimed_is_picked_up_on_the_next_walk(rs, monkeypatch):
    """Run 36488093731: fast coins, unanswered claims, and 261 of 1,067 coins
    claimed by nobody. A second walk takes what is still untaken."""
    walks = [["A_USDT", "B_USDT"], ["C_USDT"], []]
    calls = []

    def _stream(coins, t0):
        calls.append(1)
        yield from walks[len(calls) - 1]

    monkeypatch.setattr(rs.ss, "coin_stream", _stream)
    monkeypatch.setattr(rs.ss.board, "enabled", True)
    assert list(rs.board_passes([], 0)) == ["A_USDT", "B_USDT", "C_USDT"]
    assert len(calls) == 3, "stops once a walk claims nothing"


def test_without_a_board_one_walk_is_the_whole_slice(rs, monkeypatch):
    calls = []

    def _stream(coins, t0):
        calls.append(1)
        yield "A_USDT"

    monkeypatch.setattr(rs.ss, "coin_stream", _stream)
    monkeypatch.setattr(rs.ss.board, "enabled", False)
    assert list(rs.board_passes([], 0)) == ["A_USDT"] and len(calls) == 1
