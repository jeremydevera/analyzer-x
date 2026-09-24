"""Backtest v2 keeps flat rows only (Sep 24, 2026).

The operator deployed 1,473 Backtest v2 ids and 721 of them were a flat row
AND its martingale twin — the same coin, signal, entries and exits, the same
wins (#5JWGQZPG and #L2KBERYD: GPNSTOCK 30m keltner, 28 trades, 27 wins,
+$73.53 each), one switch between them, because the runner stakes by the
book's Martingale mode box, never by a row's label. Their answer: *"okay
remove the martinangale in backtest v2 since they are dup"*.

One rule (`backtest_report.sizings_for`) and every door reads it: the GitHub
shard and the local sweep measure v2 flat only, the index never files a v2
martingale row (so a re-filed pair cannot bring one back), and the screen's
filter, plan and labels say one sizing. v1 is untouched. The pair files keep
the old twins on disk, so the choice stays reversible.
"""
from __future__ import annotations

import ast
import dataclasses
import json
import sqlite3
from pathlib import Path

import pytest

from tradingagents import backtest_report as br, market_sweep as msw
from tradingagents import rows_index as ri, stores

ROOT = Path(__file__).resolve().parents[1]


def _row(sizing, *, res="1m", signal="keltner"):
    return {"coin": "GPNSTOCK", "tf": "30m", "signal": signal, "th": 0.0,
            "sl": 2.0, "tp": 3.0, "rr": 1.5, "sizing": sizing, "lev": 20,
            "base": 5.0, "notional": 100.0, "trades": 28, "wins": 27,
            "losses": 1, "winrate": 96.43, "profit": 73.53, "funding": -0.01,
            "h1": 19.63, "h2": 53.89, "green": 2, "months": 2, "worst": -2.21,
            "dd": 2.21, "liqs": 0, "stop_reachable": True, "days": 29,
            "bars": 1439, "monthly": {"2026-09": 53.89}, "cost_of_tp": 6.5,
            "rt": 0.1953, "gate": "ok", "unclear": 0,
            **({"res": res} if res else {})}


@pytest.fixture
def index(tmp_path, monkeypatch):
    (tmp_path / "rows").mkdir()
    monkeypatch.setattr(msw, "ROWDIR", tmp_path / "rows")
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    ri.ensure()
    return tmp_path


def _filed(store):
    con = sqlite3.connect(store / "rows.db")
    try:
        return sorted(r[0] for r in con.execute("SELECT sizing FROM rows"))
    finally:
        con.close()


def test_the_one_rule_v2_flat_only_and_v1_both():
    assert br.sizings_for("1m") == ("flat",)
    assert br.sizings_for("") == br.sizings_for(None) == br.SIZINGS
    assert br.SIZINGS == ("flat", "martingale"), "v1 keeps both"
    assert br.sizings_for(stores.V2.fine_tf) == ("flat",)


def test_the_index_never_files_a_v2_martingale_row(index):
    f = index / "rows" / "GPNSTOCK-30m.json"
    f.write_text(json.dumps([_row("flat"), _row("martingale")]))
    assert ri.index_pair(f) == 1
    assert _filed(index) == ["flat"]
    # re-filing the pair (a collect, an UPDATE) cannot bring the twin back
    ri.index_pair(f)
    assert _filed(index) == ["flat"]
    assert json.loads(f.read_text())[1]["sizing"] == "martingale", \
        "the pair file keeps the twin on disk: reversible"


def test_v1_rows_keep_both_sizings(index):
    f = index / "rows" / "GPNSTOCK-30m.json"
    f.write_text(json.dumps([_row("flat", res=None), _row("martingale", res=None)]))
    ri.index_pair(f)
    assert _filed(index) == ["flat", "martingale"]


def test_the_v2_filter_offers_no_martingale_and_v1_offers_both(index, monkeypatch):
    monkeypatch.setattr(stores, "V2", dataclasses.replace(
        stores.V2, rows_db=index / "rows.db"))
    assert ri.facets(db_path=index / "rows.db")["sizings"] == ["flat"]
    with ri.using_db(index / "v1-rows.db"):
        assert ri._sizings() == br.SIZINGS, "any other store keeps both"


def test_the_github_shard_and_the_local_sweep_measure_the_stores_sizings():
    """Read the CALLS, not the text: a loop over br.SIZINGS would keep twenty
    machines measuring v2 martingale rows the store then throws away."""
    shard = ast.parse((ROOT / ".github" / "scripts" / "sweep_shard.py")
                      .read_text(encoding="utf-8"))
    loops = [n.iter for n in ast.walk(shard) if isinstance(n, ast.For)]
    raw = [ast.unparse(it) for it in loops if ast.unparse(it) == "br.SIZINGS"]
    per_store = [it for it in loops if ast.unparse(it) == "br.sizings_for(RES)"]
    assert not raw, "the shard loops over both sizings directly"
    assert len(per_store) == 2, "both the full measure and the update read it"
    sweep = (ROOT / "tradingagents" / "market_sweep.py").read_text(encoding="utf-8")
    assert "br.sizings_for(FINE_TF)" in sweep
    assert "br.pairs_for(tf),\n                                                  br.SIZINGS)" not in sweep


def test_the_plan_counts_one_sizing_on_v2(monkeypatch):
    from tradingagents import api

    v1 = api.backtest_plan(coins="GPNSTOCK_USDT", tfs="30m")
    v2 = api.backtest_plan(coins="GPNSTOCK_USDT", tfs="30m", store="v2")
    assert (v1["sizings"], v2["sizings"]) == (2, 1)
    assert v2["combinations"] * 2 == v1["combinations"]


def test_the_screen_says_one_sizing_where_the_store_keeps_one():
    panel = (ROOT / "webapp/src/components/backtest/StrategiesPanel.tsx").read_text(encoding="utf-8")
    assert "(facets.sizings ?? []).length > 1 && (" in panel, \
        "no 'flat and martingale' dropdown over a store with one sizing"
    assert 'oneSizing ? `${oneSizing} only` : "flat and martingale"' in panel
    assert "if (sizing && held.length && !held.includes(sizing)) setSizing(\"\")" in panel, \
        "a hidden control may not keep a filter applied"
    jobs = (ROOT / "webapp/src/components/backtest/JobsPanel.tsx").read_text(encoding="utf-8")
    v2_text = jobs[jobs.index('{store === "v2"'):jobs.index(': <>Every signal × barrier pair × both sizings, over')]
    assert "both sizings" not in v2_text and "flat sizing only" in v2_text
    assert "api.plan(coins, tfs, store)" in jobs
    assert 'sizing{plan.sizings === 1 ? "" : "s"}' in jobs
