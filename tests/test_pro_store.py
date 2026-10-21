"""The group "Oct 21": the Pro Trader settings landed in Backtest v2
(tradingagents/pro_store.py, .github/scripts/pro_store_shard.py), Oct 20, 2026.

The operator: "okay deploy this i want this new batch as group 'Oct 21'". The
rows land the way the learned families land: a pair's old pt_ rows out and
the new in under its lock, every other row and the pair's watermark untouched,
only those rules re-filed in the index; and a strategy key names its rule by
the rule's own grammar, so its id is the row's id."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def v2(tmp_path, monkeypatch):
    from tradingagents import market_sweep as msw, pro_store as pst, rows_index as ri

    monkeypatch.setattr(msw, "FINE_TF", "1m")
    monkeypatch.setattr(msw, "HOME", tmp_path)
    monkeypatch.setattr(msw, "ROWDIR", tmp_path / "rows")
    monkeypatch.setattr(msw, "STATES", tmp_path / "state")
    monkeypatch.setattr(pst, "REPORT_FILE", tmp_path / "oct21_report.json")
    db = tmp_path / "rows.db"
    monkeypatch.setattr(ri, "DB_PATH", db)
    ri._ready.discard(str(db))
    ri.forget_indexes()
    ri.ensure()
    return msw, ri, pst, db


def _row(coin, tf, signal, sl=0.4, tp=1.5, profit=5.0):
    return {"coin": coin, "tf": tf, "signal": signal, "th": 0.0, "sl": sl, "tp": tp,
            "sizing": "flat", "trades": 12, "wins": 5, "losses": 7, "winrate": 41.67,
            "profit": profit, "monthly": {}, "res": "1m", "last_ms": 1,
            # what its trades paid: the list keeps a row only when it pays 2:1
            # after its OWN fees (backtest_report.index_keeps)
            "rt": 0.2, "rt_paid": 0.2, "cost_of_tp": round(0.2 / tp * 100, 1)}


def _write(path: Path, rows: list, tail: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows) + tail, encoding="utf-8")


def _pt(con) -> list:
    return sorted(r[0] for r in con.execute(
        "SELECT signal FROM rows WHERE signal >= 'pt_' AND signal < 'pt`'"))


def test_a_store_run_lands_its_rows_and_leaves_everything_else_alone(v2, tmp_path):
    msw, ri, pst, db = v2
    grid = [_row("BTC", "15m", "keltner"), _row("BTC", "15m", "lx_BTC_15m_1")]
    msw.save_pair_rows("BTC", "15m", grid + [_row("BTC", "15m", "pt_brk_n0g0c0", profit=-9.0)])
    msw.save_states("BTC", "15m", {"__cloud__": True, "__last_ms__": 123})
    new = [_row("BTC", "15m", "pt_brk_n0g0c0"), _row("BTC", "15m", "pt_tsm_l0e0s0", 0.6, 2.0)]
    root = tmp_path / "run"
    # machine 0: BTC 15m, then a pair whose report line says it FAILED
    _write(root / "a" / "pro-rows-0.jsonl", new + [_row("ETH", "1h", "pt_ma_p0e0")])
    # machine 1: SOL 4h, then a line cut by a machine stopped mid-write
    _write(root / "b" / "pro-rows-1.jsonl", [_row("SOL", "4h", "pt_abn_k0v0")], '{"coin": "SO')
    report = [{"coin": "BTC", "tf": "15m", "rows": 2},
              {"coin": "ETH", "tf": "1h", "error": "HTTPError: 502"},
              {"coin": "SOL", "tf": "4h", "rows": 1}]
    got = pst.land(report, [root], run=7)
    sigs = sorted(r["signal"] for r in msw.pair_rows("BTC", "15m"))
    assert sigs == ["keltner", "lx_BTC_15m_1", "pt_brk_n0g0c0", "pt_tsm_l0e0s0"]
    assert [r["profit"] for r in msw.pair_rows("BTC", "15m") if r["signal"] == "pt_brk_n0g0c0"] == [5.0]
    assert msw.load_states("BTC", "15m").get("__last_ms__") == 123       # never moved
    assert msw.pair_rows("ETH", "1h") == []                              # a failed pair lands nothing...
    assert got["stray"] == ["ETH 1h"]                                     # ...and is NAMED
    assert got["cut"] and got["cut"][0].endswith("pro-rows-1.jsonl")
    assert got["rows"] == 3 and got["pairs_filed"] == 2
    con = sqlite3.connect(db)
    assert _pt(con) == ["pt_abn_k0v0", "pt_brk_n0g0c0", "pt_tsm_l0e0s0"]
    con.close()


def test_a_second_run_replaces_the_first_and_a_pair_with_none_loses_its_rows(v2, tmp_path):
    msw, ri, pst, db = v2
    root = tmp_path / "run1"
    _write(root / "pro-rows-0.jsonl", [_row("BTC", "1h", "pt_brk_n0g0c0"),
                                       _row("ETH", "1h", "pt_ma_p0e0")])
    pst.land([{"coin": "BTC", "tf": "1h"}, {"coin": "ETH", "tf": "1h"}], [root])
    root2 = tmp_path / "run2"
    _write(root2 / "pro-rows-0.jsonl", [_row("BTC", "1h", "pt_vwm_n0e0")])
    got = pst.land([{"coin": "BTC", "tf": "1h"}, {"coin": "ETH", "tf": "1h", "why": "no setting traded"}],
                   [root2])
    assert [r["signal"] for r in msw.pair_rows("BTC", "1h")] == ["pt_vwm_n0e0"]
    assert msw.pair_rows("ETH", "1h") == []
    con = sqlite3.connect(db)
    assert _pt(con) == ["pt_vwm_n0e0"]
    con.close()
    assert got["rows"] == 1


def test_a_store_run_refuses_rows_that_are_not_oct_21s(v2, tmp_path):
    msw, ri, pst, db = v2
    _write(tmp_path / "a" / "pro-rows-0.jsonl", [_row("BTC", "15m", "keltner")])
    with pytest.raises(ValueError, match="not Oct 21"):
        pst.land([{"coin": "BTC", "tf": "15m"}], [tmp_path / "a"])
    _write(tmp_path / "b" / "pro-rows-0.jsonl", [{**_row("BTC", "15m", "pt_brk_n0g0c0"), "res": ""}])
    with pytest.raises(ValueError, match="res="):
        pst.land([{"coin": "BTC", "tf": "15m"}], [tmp_path / "b"])
    assert msw.pair_rows("BTC", "15m") == []                             # nothing touched first


def test_a_pair_met_twice_keeps_its_later_rows(v2, tmp_path):
    msw, ri, pst, db = v2
    _write(tmp_path / "a" / "pro-rows-0.jsonl",
           [_row("BTC", "1d", "pt_brk_n0g0c0", profit=1.0), _row("ETH", "1d", "pt_ma_p0e0"),
            _row("BTC", "1d", "pt_brk_n0g0c0", profit=2.0)])
    got = pst.land([{"coin": "BTC", "tf": "1d"}, {"coin": "ETH", "tf": "1d"}], [tmp_path / "a"])
    assert [r["profit"] for r in msw.pair_rows("BTC", "1d")] == [2.0]
    assert got["twice"] == ["BTC 1d"]


def test_oct_21_is_a_group_of_its_own():
    from tradingagents import rows_index as ri

    assert ri.GROUPS["oct21"]["label"] == "Oct 21"
    assert ri.in_group("pt_brk_n0g0c0", "oct21") and not ri.in_group("pt_brk_n0g0c0", "classic")
    assert not ri.in_group("trend50", "oct21") and not ri.in_group("cf_ttm_l2", "oct21")
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE rows (signal TEXT)")
    names = ["pt_brk_n0g0c0", "pt_vwm_n2e1", "trend50", "cf_ttm_l2", "lx_BTC_1h_1", "ml_BTC_1h_1"]
    con.executemany("INSERT INTO rows (signal) VALUES (?)", [(n,) for n in names])
    for group, terms in ri.GROUP_TERMS.items():
        sql = {r[0] for r in con.execute(f"SELECT signal FROM rows WHERE {terms}")}
        assert sql == {n for n in names if ri.in_group(n, group)}, group
    con.close()
    assert ri.group_index("oct21", "profit") == "rows_pt_profit"


def test_a_strategy_key_names_its_pro_rule_whole():
    from tradingagents import backtest_report as br, strategy_keys as sk
    from tradingagents.local_history import _sig_of

    row = {"signal": "pt_tsm_l3e1s0", "tf": "15m", "sl": 0.4, "tp": 1.5, "th": 0.0}
    key = sk.key_for(row)
    assert key == "pt_tsm_l3e1s0_15m_sl04tp15"
    assert _sig_of(key) == "pt_tsm_l3e1s0"           # never "pt" (RCA-2026-09-24-G)
    assert br.row_code("BTC", "15m", _sig_of(key), 0.0, 0.4, 1.5, "flat", res="1m") == \
        br.row_code("BTC", "15m", "pt_tsm_l3e1s0", 0.0, 0.4, 1.5, "flat", res="1m")


def test_the_screen_offers_the_group_in_the_operators_words():
    panel = (ROOT / "webapp/src/components/backtest/StrategiesPanel.tsx").read_text(encoding="utf-8")
    assert 'oct21: "Oct 21"' in panel
    assert '<option value="oct21">{GROUP_LABEL.oct21}</option>' in panel
    api = (ROOT / "webapp/src/lib/api.ts").read_text(encoding="utf-8")
    assert api.count('"sep27ml" | "oct21"') == 2


# ------------------------------------------- one machine, on a made-up market
_PROG = r'''
import json, os, sys, time
ROOT = sys.argv[1]
sys.path.insert(0, os.path.join(ROOT, ".github", "scripts"))
sys.path.insert(0, ROOT)
os.environ.update({"GITHUB_TOKEN": "", "GITHUB_REPOSITORY": "", "INGEST_URL": "",
                   "COIN_LIST": "", "TA_VENUE": "gate", "TFS": "15m", "SHARD": "0"})
import pandas as pd
import pro_store_shard as pss
import sweep_shard as ss
from tradingagents import cost_store
from tests.test_pro_strategies import _frame
ss.cost_book = lambda sym: cost_store.empty()
ss.report = lambda *a, **k: None
ss.log = lambda *a, **k: None
n = 4000
step = 900_000
end_ms = (int(time.time() * 1000) // step) * step - step
o, h, lo, c, v, ts = _frame(n=n, seed=7, step_s=900, start_ms=end_ms - (n - 1) * step)
df = pd.DataFrame({"Date": pd.to_datetime(ts, unit="ms"), "Open": o, "High": h, "Low": lo,
                   "Close": c, "Volume": v})
pss.fx.klines = lambda sym, iv, cap: df
pre = {"fee": 0.00075, "liq": 4.5, "fund": [], "slip": 0.0003, "fine": None}
lines, info = pss.store_pair("TEST_USDT", "15m", pre, 0, 1)
dfw, warm = ss.window(df)
reps = pss.groups_for(dfw, warm)
print(json.dumps({"info": info, "rows": [json.loads(x) for x in lines],
                  "groups": list(reps.values()), "names": pss.NAMES,
                  "barriers": pss.BARRIERS["15m"]}))
'''


def test_one_store_machine_writes_backtest_v2_rows_for_every_setting(tmp_path):
    out = subprocess.run([sys.executable, "-c", _PROG, str(ROOT)], cwd=str(tmp_path),
                         capture_output=True, text=True, timeout=900)
    assert out.returncode == 0, out.stderr[-3000:]
    got = json.loads(out.stdout.strip().splitlines()[-1])
    rows, info = got["rows"], got["info"]
    assert rows and info["rows"] == len(rows)
    assert not [n for n in got["names"] if n.startswith("pt_rand_")], "the luck bar is no strategy"
    assert {r["res"] for r in rows} == {"1m"} and {r["sizing"] for r in rows} == {"flat"}
    assert all(r["signal"].startswith("pt_") and not r["signal"].startswith("pt_rand_") for r in rows)
    # Backtest v2's own window and the counts the rooms judge on
    assert max(r["days"] for r in rows) <= 31
    assert all(k in rows[0] for k in ("t15", "t1", "t2", "t3", "t4", "rt_paid"))
    # only the research's stop/targets, every one of them paying 2:1
    want = {(round(a * 100, 4), round(b * 100, 4)) for a, b in got["barriers"]}
    assert {(round(r["sl"], 4), round(r["tp"], 4)) for r in rows} <= want
    # every setting of a group carries the group's numbers under its OWN name
    by = {(r["signal"], r["sl"], r["tp"]): r for r in rows}
    for names in got["groups"]:
        for sl, tp in {(r["sl"], r["tp"]) for r in rows if r["signal"] == names[0]}:
            a = by[(names[0], sl, tp)]
            for other in names[1:]:
                b = by[(other, sl, tp)]
                assert {k: v for k, v in b.items() if k != "signal"} == \
                       {k: v for k, v in a.items() if k != "signal"}


def test_a_newer_oct_21_row_never_hides_the_pairs_nightly_rows(v2):
    """RCA-2026-10-21-A. A pair's NEWEST backtest is the nightly grid's: the
    Oct 21 rows were measured the evening after the nightly run, and when
    their later `last_ms` counted as the pair's newest, every nightly row read
    as an older run and left the list — the Oct 21, 2026 rebuild kept 895,520
    rows of 12.4 million. Only the rules the nightly grid measures date the
    pair; a learned or Pro Trader row is filed beside them, never over them."""
    msw, ri, pst, db = v2
    nightly = [{**_row("BTC", "1d", "keltner"), "last_ms": 1_000},
               {**_row("BTC", "1d", "trend50"), "last_ms": 1_000}]
    pt = [{**_row("BTC", "1d", "pt_brk_n0g0c0"), "last_ms": 2_000}]
    msw.save_pair_rows("BTC", "1d", nightly + pt)
    msw.save_states("BTC", "1d", {"__cloud__": True, "__last_ms__": 1_000})
    path = msw.ROWDIR / "BTC-1d.json"
    assert ri._newest_measure(path, msw.pair_rows("BTC", "1d")) == 1_000
    ri.index_pair(path)
    con = sqlite3.connect(db)
    filed = sorted(r[0] for r in con.execute("SELECT signal FROM rows WHERE pair = 'BTC-1d'"))
    con.close()
    assert filed == ["keltner", "pt_brk_n0g0c0", "trend50"]
