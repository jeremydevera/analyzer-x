"""The group "Oct 22": the confluence research's picks landed in Backtest v2
(tradingagents/cq_store.py, .github/scripts/cq_store_shard.py), Oct 22, 2026.

The operator, after the confluence research (Prompt 1): "Okay deploy them in
production, i want t to see then in stored strategies". Every pick the search
found (a name, a stop and a target per coin, timeframe and payout; never a
random entry) is measured as a Backtest v2 row is, each at ITS OWN stop and
target, and lands the way the group "Oct 21" landed (pro_store.land, one body
for both): a pair's old cq_ rows out and the new in under its lock, every
other row and the pair's watermark untouched, only those rules re-filed, a
hundred pairs at a time, each batch filed before the next is rewritten."""
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
    from tradingagents import (cq_store as cqst, market_sweep as msw, pro_store as pst,
                               rows_index as ri)

    monkeypatch.setattr(msw, "FINE_TF", "1m")
    monkeypatch.setattr(msw, "HOME", tmp_path)
    monkeypatch.setattr(msw, "ROWDIR", tmp_path / "rows")
    monkeypatch.setattr(msw, "STATES", tmp_path / "state")
    # both groups' reports: a landing in a test never writes the repo's own
    monkeypatch.setattr(cqst, "REPORT_FILE", tmp_path / "oct22_report.json")
    monkeypatch.setattr(pst, "REPORT_FILE", tmp_path / "oct21_report.json")
    db = tmp_path / "rows.db"
    monkeypatch.setattr(ri, "DB_PATH", db)
    ri._ready.discard(str(db))
    ri.forget_indexes()
    ri.ensure()
    return msw, ri, cqst, db


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


def _cq(con) -> list:
    return sorted(r[0] for r in con.execute(
        "SELECT signal FROM rows WHERE signal >= 'cq_' AND signal < 'cq`'"))


# ------------------------------------------------------------------ the plan
def _results():
    """cq_report.results' shape: per coin and timeframe, the search's picks
    (one per payout) and the luck search's, which is random entries."""
    def pick(name, sl, tp):
        return {"cand": [name, sl, tp, 2, [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]],
                "trades": {}}
    return {"coins": {
        "BTC": {"tfs": {"1h": {"search": {"picks": {"2": pick("cq_ex24", 1.0, 3.0),
                                                    "3": pick("cq_fl00-ev", 0.5, 2.0)},
                                          "final": "2"},
                               "luck": {"picks": {"2": pick("cq_rn00070", 1.0, 3.0)}}},
                        "4h": {"search": {"picks": {}}}}},
        "ETH": {"tfs": {"15m": {"search": {"picks": {"4": pick("cq_ex24", 0.4, 2.0)}}}}},
        "SOL": {"tfs": {}}}}


def test_the_plan_holds_every_pick_and_never_a_random_one():
    from tradingagents import cq_store as cqst, signals_cq as sq

    plan = cqst.build_plan(_results()["coins"], "test runs")
    assert plan["coins"] == {"BTC": {"1h": [["cq_ex24", 1.0, 3.0], ["cq_fl00-ev", 0.5, 2.0]]},
                             "ETH": {"15m": [["cq_ex24", 0.4, 2.0]]}}
    assert plan["picks"] == 3 and plan["pairs"] == 2 and plan["from"] == "test runs"
    # every name carries its plain words, so a machine can refuse a name that
    # means something else in the code it runs
    assert plan["names"] == {"cq_ex24": sq.words("cq_ex24"), "cq_fl00-ev": sq.words("cq_fl00-ev")}
    assert all(plan["names"].values())
    assert "cq_rn00070" not in json.dumps(plan)


def test_the_committed_plan_is_the_research_pages_picks():
    """research/cq/store_plan.json, the file the machines read: 12,861 picks
    on 3,457 coin + timeframes of 862 coins (the all-coins page, Oct 22,
    2026), every name's words matching this code."""
    from tradingagents import signals_cq as sq

    plan = json.loads((ROOT / "research" / "cq" / "store_plan.json").read_text(encoding="utf-8"))
    picks = [(c, tf, p) for c, tfs in plan["coins"].items() for tf, ps in tfs.items() for p in ps]
    assert len(picks) == plan["picks"] == 12_861
    assert sum(len(t) for t in plan["coins"].values()) == plan["pairs"] == 3_457
    assert len(plan["coins"]) == 862
    assert not [p for _c, _t, p in picks if p[0].startswith("cq_rn")]
    assert all(sq.words(n) == w for n, w in plan["names"].items())
    assert all(0 < p[1] <= 2.0 and p[2] > p[1] for _c, _t, p in picks)


# -------------------------------------------------------------- the landing
def test_a_store_run_lands_its_rows_and_leaves_everything_else_alone(v2, tmp_path):
    msw, ri, cqst, db = v2
    grid = [_row("BTC", "15m", "keltner"), _row("BTC", "15m", "pt_brk_n0g0c0")]
    msw.save_pair_rows("BTC", "15m", grid + [_row("BTC", "15m", "cq_ex24", profit=-9.0)])
    msw.save_states("BTC", "15m", {"__cloud__": True, "__last_ms__": 123})
    new = [_row("BTC", "15m", "cq_ex24"), _row("BTC", "15m", "cq_fl00-ev", 0.5, 2.0)]
    root = tmp_path / "run"
    _write(root / "a" / "cq-rows-0.jsonl", new + [_row("ETH", "1h", "cq_ex24")])
    _write(root / "b" / "cq-rows-1.jsonl", [_row("SOL", "4h", "cq_ex24")], '{"coin": "SO')
    report = [{"coin": "BTC", "tf": "15m", "rows": 2},
              {"coin": "ETH", "tf": "1h", "error": "HTTPError: 502"},
              {"coin": "SOL", "tf": "4h", "rows": 1}]
    got = cqst.land(report, [root], run=7)
    rows = msw.pair_rows("BTC", "15m")
    assert sorted(r["signal"] for r in rows) == ["cq_ex24", "cq_fl00-ev", "keltner", "pt_brk_n0g0c0"]
    assert [r["profit"] for r in rows if r["signal"] == "cq_ex24"] == [5.0]
    assert msw.load_states("BTC", "15m").get("__last_ms__") == 123       # never moved
    assert msw.pair_rows("ETH", "1h") == []                              # a failed pair lands nothing...
    assert got["stray"] == ["ETH 1h"]                                     # ...and is NAMED
    assert got["cut"] and got["cut"][0].endswith("cq-rows-1.jsonl")
    assert got["rows"] == 3 and got["pairs_filed"] == 2
    con = sqlite3.connect(db)
    assert _cq(con) == ["cq_ex24", "cq_ex24", "cq_fl00-ev"]
    con.close()
    assert json.loads((tmp_path / "oct22_report.json").read_text(encoding="utf-8"))["run"] == 7


def test_a_store_run_refuses_rows_that_are_not_oct_22s(v2, tmp_path):
    msw, ri, cqst, db = v2
    _write(tmp_path / "a" / "cq-rows-0.jsonl", [_row("BTC", "15m", "pt_brk_n0g0c0")])
    with pytest.raises(ValueError, match="not Oct 22"):
        cqst.land([{"coin": "BTC", "tf": "15m"}], [tmp_path / "a"])
    _write(tmp_path / "b" / "cq-rows-0.jsonl", [{**_row("BTC", "15m", "cq_ex24"), "res": ""}])
    with pytest.raises(ValueError, match="res="):
        cqst.land([{"coin": "BTC", "tf": "15m"}], [tmp_path / "b"])
    assert msw.pair_rows("BTC", "15m") == []                             # nothing touched first


@pytest.mark.parametrize("group", ["oct21", "oct22"])
def test_each_batch_is_filed_before_the_next_is_rewritten(v2, tmp_path, monkeypatch, group):
    """RCA-2026-10-22-G. The list's safety net files (or rebuilds) whatever
    has been newer than the list for 30 minutes (rows_index.keep_list_filed).
    The Oct 21 landing rewrote 4,397 pair files first and filed them over the
    next 11.5 hours, and the safety net started whole rebuilds under it all
    night (RCA-2026-10-21-A). A batch is filed as soon as it is rewritten, so
    no pair waits behind the list longer than one batch - for both groups,
    which land through one body."""
    from tradingagents import learn_collect as lc, pro_store as pst

    msw, ri, cqst, db = v2
    monkeypatch.setattr(lc, "FILE_BATCH", 2)
    events: list = []
    rewrite, file_learned = msw.rewrite_pair_rows, lc.file_learned

    def spy_rewrite(coin, tf, fn):
        events.append(("rewrite", f"{coin}-{tf}"))
        return rewrite(coin, tf, fn)

    def spy_file(entries, *a, **kw):
        events.append(("file", sorted(p.stem for p, _n in entries)))
        return file_learned(entries, *a, **kw)

    monkeypatch.setattr(msw, "rewrite_pair_rows", spy_rewrite)
    monkeypatch.setattr(lc, "file_learned", spy_file)
    coins = ["AAA", "BBB", "CCC", "DDD", "EEE"]
    name, rows_file, land = {"oct21": ("pt_brk_n0g0c0", "pro-rows-0.jsonl", pst.land),
                             "oct22": ("cq_ex24", "cq-rows-0.jsonl", cqst.land)}[group]
    _write(tmp_path / "r" / rows_file, [_row(c, "1h", name) for c in coins])
    got = land([{"coin": c, "tf": "1h"} for c in coins], [tmp_path / "r"])
    assert events == [("rewrite", "AAA-1h"), ("rewrite", "BBB-1h"), ("file", ["AAA-1h", "BBB-1h"]),
                      ("rewrite", "CCC-1h"), ("rewrite", "DDD-1h"), ("file", ["CCC-1h", "DDD-1h"]),
                      ("rewrite", "EEE-1h"), ("file", ["EEE-1h"])]
    assert got["rows"] == 5 and got["indexed"] == 5 and got["pairs_filed"] == 5
    with ri.using_db(db):
        assert ri.stale_pairs() == []                    # nothing left behind the list


def test_both_groups_land_through_one_body():
    from tradingagents import cq_store as cqst, pro_store as pst

    assert (pst.OCT21.key, pst.OCT21.label, pst.OCT21.family.prefix) == ("oct21", "Oct 21", "pt_")
    assert (cqst.OCT22.key, cqst.OCT22.label, cqst.OCT22.family.prefix) == ("oct22", "Oct 22", "cq_")
    assert cqst.OCT22.family.index == "rows_cq_profit"


def test_a_newer_oct_22_row_never_hides_the_pairs_nightly_rows(v2):
    """RCA-2026-10-21-A's rule for this family too: only the nightly grid's
    rules date a pair, so a cq_ row measured after the nightly run is filed
    beside its rows and never pushes them off the list."""
    msw, ri, cqst, db = v2
    nightly = [{**_row("BTC", "1d", "keltner"), "last_ms": 1_000},
               {**_row("BTC", "1d", "trend50"), "last_ms": 1_000}]
    cq = [{**_row("BTC", "1d", "cq_ex24"), "last_ms": 2_000}]
    msw.save_pair_rows("BTC", "1d", nightly + cq)
    msw.save_states("BTC", "1d", {"__cloud__": True, "__last_ms__": 1_000})
    path = msw.ROWDIR / "BTC-1d.json"
    assert ri._newest_measure(path, msw.pair_rows("BTC", "1d")) == 1_000
    ri.index_pair(path)
    con = sqlite3.connect(db)
    filed = sorted(r[0] for r in con.execute("SELECT signal FROM rows WHERE pair = 'BTC-1d'"))
    con.close()
    assert filed == ["cq_ex24", "keltner", "trend50"]


# ---------------------------------------------------------------- the group
def test_oct_22_is_a_group_of_its_own():
    from tradingagents import rows_index as ri

    assert ri.GROUPS["oct22"]["label"] == "Oct 22"
    assert ri.in_group("cq_fl00-ev", "oct22") and not ri.in_group("cq_fl00-ev", "classic")
    assert not ri.in_group("cq_ex24", "preset") and not ri.in_group("cf_mom", "oct22")
    assert not ri.in_group("pt_brk_n0g0c0", "oct22") and not ri.in_group("cq_ex24", "oct21")
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE rows (signal TEXT)")
    names = ["cq_ex24", "cq_fl00-ev-vs1", "pt_brk_n0g0c0", "trend50", "cf_ttm_l2", "cx_veto",
             "lx_BTC_1h_1", "ml_BTC_1h_1"]
    con.executemany("INSERT INTO rows (signal) VALUES (?)", [(n,) for n in names])
    for group, terms in ri.GROUP_TERMS.items():
        sql = {r[0] for r in con.execute(f"SELECT signal FROM rows WHERE {terms}")}
        assert sql == {n for n in names if ri.in_group(n, group)}, group
    con.close()
    assert ri.group_index("oct22", "profit") == "rows_cq_profit"


def test_a_strategy_key_names_its_confluence_rule_whole():
    from tradingagents import backtest_report as br, strategy_keys as sk
    from tradingagents.local_history import _sig_of

    for name in ("cq_fl00-ev-vs1", "cq_ex24"):
        row = {"signal": name, "tf": "15m", "sl": 0.4, "tp": 1.5, "th": 0.0}
        key = sk.key_for(row)
        assert key == f"{name}_15m_sl04tp15"
        assert _sig_of(key) == name                     # never "cq" (RCA-2026-09-24-G)
        assert br.row_code("BTC", "15m", _sig_of(key), 0.0, 0.4, 1.5, "flat", res="1m") == \
            br.row_code("BTC", "15m", name, 0.0, 0.4, 1.5, "flat", res="1m")


def test_the_screen_offers_the_group_in_the_operators_words():
    panel = (ROOT / "webapp/src/components/backtest/StrategiesPanel.tsx").read_text(encoding="utf-8")
    assert 'oct22: "Oct 22"' in panel
    assert '<option value="oct22">{GROUP_LABEL.oct22}</option>' in panel
    assert '"oct21" | "oct22" | undefined' in panel
    api = (ROOT / "webapp/src/lib/api.ts").read_text(encoding="utf-8")
    assert api.count('"sep27ml" | "oct21" | "oct22"') == 2


# ----------------------------------------------- starting it and bringing it home
def test_a_store_dispatch_deals_the_plans_coins_and_says_it_is_the_store(monkeypatch, tmp_path):
    import datetime as dt

    from tradingagents import cloud_sweep as cs, cq_search as cqs, forecast_v2_daily as fd

    started = []
    monkeypatch.setattr(cqs, "home", lambda: tmp_path)
    monkeypatch.setattr(cqs, "_start", lambda repo, inputs: started.append((repo, dict(inputs)))
                        or 1000 + len(started))
    monkeypatch.setattr(fd, "fleets_now", lambda: (["a/x", "b/x", "c/x"], []))
    monkeypatch.setattr(cs, "origin_fleet", lambda: "a/x")
    monkeypatch.setattr(cs, "sync_fleet", lambda repo: "")
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"coins": {"BTC": {"1h": []}, "ETH": {"4h": []}, "SOL": {"1d": []},
                                          "XRP": {"15m": []}}}), encoding="utf-8")
    noon = dt.datetime(2026, 10, 22, 12, 0).timestamp()
    st = cqs.dispatch("Oct 22 store", store=True, plan=plan, now=noon)
    dealt = sorted(c for _r, i in started for c in i["coin_list"].split(","))
    assert dealt == ["BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT"]
    assert {i["store"] for _r, i in started} == {"1"} and {i["luck"] for _r, i in started} == {""}
    assert st["store"] is True and (tmp_path / "store.json").exists()
    with pytest.raises(RuntimeError, match="12:45am and 5:00am"):
        cqs.dispatch("x", store=True, plan=plan,
                     now=dt.datetime(2026, 10, 22, 1, 0).timestamp())


def test_a_store_collect_reads_the_store_report_and_says_measured(monkeypatch, tmp_path):
    import datetime as dt

    from tradingagents import cloud_sweep as cs, cq_search as cqs, forecast_v2_daily as fd

    monkeypatch.setattr(cqs, "home", lambda: tmp_path)
    monkeypatch.setattr(cqs, "_start", lambda repo, inputs: 1001)
    monkeypatch.setattr(fd, "fleets_now", lambda: (["a/x"], []))
    monkeypatch.setattr(cs, "origin_fleet", lambda: "a/x")
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"coins": {"BTC": {"1h": []}, "NVDA": {"4h": []}}}), encoding="utf-8")
    cqs.dispatch("s", store=True, plan=plan, now=dt.datetime(2026, 10, 22, 12, 0).timestamp())
    root = tmp_path / "run-1001"
    root.mkdir()
    (root / "cq-store-report-0.json").write_text(json.dumps({"report": [
        {"coin": "BTC", "tf": "1h", "picks": 2, "rows": 2},
        {"coin": "NVDA", "tf": "4h", "picks": 1, "rows": 0, "why": "only 40 measurable bars"}]}),
        encoding="utf-8")
    # the research's own report beside it is never read for a store run
    (root / "cq-report-0.json").write_text(json.dumps({"report": [
        {"coin": "XAU", "tf": "1h", "error": "planted"}]}), encoding="utf-8")
    monkeypatch.setattr(cqs, "_gh", lambda *a, **k: json.dumps({"status": "completed"}))
    monkeypatch.setattr(cqs, "download", lambda run, repo: root)
    cov = cqs.collect(cqs.STORE_STATE)["coverage"]
    assert cov["reached"] == 2 and cov["pairs_failed"] == []
    assert cov["skipped"] == ["NVDA 4h: only 40 measurable bars"]
    prog = json.loads((tmp_path / "progress.json").read_text(encoding="utf-8"))
    assert "1 measured" in prog["stage"] and "searched" not in prog["stage"]


def test_the_workflow_runs_the_store_machine_when_asked():
    import re

    text = (ROOT / ".github" / "workflows" / "cq.yml").read_text(encoding="utf-8")
    block = text.split("inputs:", 1)[1].split("permissions:", 1)[0]
    names = re.findall(r"^      ([a-z_]+):\s*$", block, flags=re.M)
    assert len(names) <= 10 and "store" in names            # GitHub allows exactly ten
    assert ("python .github/scripts/${{ github.event.inputs.store == '1' && "
            "'cq_store_shard.py' || 'cq_shard.py' }}") in text
    assert "out/cq-rows-*.jsonl" in text and "out/cq-store-report-*.json" in text


# ------------------------------------------- one machine, on a made-up market
_PROG = r'''
import json, os, sys, time
ROOT, PLAN = sys.argv[1], sys.argv[2]
sys.path.insert(0, os.path.join(ROOT, ".github", "scripts"))
sys.path.insert(0, ROOT)
os.environ.update({"GITHUB_TOKEN": "", "GITHUB_REPOSITORY": "", "INGEST_URL": "",
                   "COIN_LIST": "", "TA_VENUE": "gate", "SHARD": "0", "CQ_PLAN": PLAN})
import pandas as pd
import cq_store_shard as css
import sweep_shard as ss
from tradingagents import backtest_report as br, cost_store, signals_cq as sq
from tests.test_pro_strategies import _frame
ss.cost_book = lambda sym: cost_store.empty()
ss.report = lambda *a, **k: None
ss.log = lambda *a, **k: None
ss._venue.kind = lambda sym: "crypto"
n = 4000
step = 900_000
end_ms = (int(time.time() * 1000) // step) * step - step
o, h, lo, c, v, ts = _frame(n=n, seed=7, step_s=900, start_ms=end_ms - (n - 1) * step)
df = pd.DataFrame({"Date": pd.to_datetime(ts, unit="ms"), "Open": o, "High": h, "Low": lo,
                   "Close": c, "Volume": v})
css.fx.klines = lambda sym, iv, cap: df
dfw, warm = ss.window(df)
cols = [[float(x) for x in dfw[k]] for k in ("Open", "High", "Low", "Close", "Volume")]
wts = [int(x) for x in dfw["Date"].to_numpy().astype("datetime64[ms]").astype("int64")]
live = []
for name in sq.entries_for("15m"):
    d = sq.dirs_for(sq.spec_for(name), *cols, wts, [])
    if sum(1 for x in d[warm:] if x) >= 8:
        live.append(name)
    if len(live) == 4:
        break
a, b, dead, broken = live
real = sq.dirs_for
sq.dirs_for = lambda spec, *x, **k: ([0] * len(x[3]) if spec == sq.spec_for(dead) else
                                     (_ for _ in ()).throw(RuntimeError("planted"))
                                     if spec == sq.spec_for(broken) else real(spec, *x, **k))
# stops and targets a pick really has: 2:1 or better after the usual costs
grid = sorted((round(sl * 100, 3), round(tp * 100, 3)) for sl, tp in br.pairs_for("15m")
              if tp > sl and tp >= 0.01 and sl >= 0.003)
# and one no pick has: a 0.2% target, which the cost check refuses every time
tiny = (0.1, 0.2)
picks = [[a, *grid[0]], [a, *grid[-1]], [b, *grid[1]], [dead, *grid[0]], [broken, *grid[0]],
         ["cq_ex24", *grid[0]], [a, *tiny]]
plan = {"names": {**{x: sq.words(x) for x in (a, b, dead, broken)}, "cq_ex24": "something else"},
        "coins": {"TEST": {"15m": picks}}}
with open(PLAN, "w", encoding="utf-8") as fh:
    json.dump(plan, fh)
refused = css.refused_names(css.load_plan())
pre = {"fee": 0.00075, "liq": 4.5, "fund": [], "slip": 0.0003, "fine": None}
lines, info = css.store_pair("TEST_USDT", "15m", picks, pre, 0, 1, refused)
# each traded pick measured ALONE through the same function: the shared call
# must give every pick exactly the row it would get by itself
alone = []
for name, sl, tp in picks[:3]:
    import io
    buf = io.StringIO()
    saved = (ss.window, br.pairs_for)
    ss.window = lambda _df: (dfw, warm)
    br.pairs_for = lambda _tf, _b=((sl / 100.0, tp / 100.0),): list(_b)
    try:
        ss.run_pair("TEST_USDT", "15m", buf, signals=[name], learned={**pre, "df": df})
    finally:
        ss.window, br.pairs_for = saved
    alone += [json.loads(x) for x in buf.getvalue().splitlines() if x.strip()]
print(json.dumps({"info": info, "rows": [json.loads(x) for x in lines], "picks": picks,
                  "alone": alone, "refused": refused}))
'''


@pytest.fixture(scope="module")
def machine(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("cqstore")
    out = subprocess.run([sys.executable, "-c", _PROG, str(ROOT), str(tmp / "plan.json")],
                         cwd=str(tmp), capture_output=True, text=True, timeout=900)
    assert out.returncode == 0, out.stderr[-3000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_each_pick_is_measured_at_its_own_stop_and_target_only(machine):
    rows, picks = machine["rows"], machine["picks"]
    got = sorted((r["signal"], r["sl"], r["tp"]) for r in rows)
    assert got == sorted(tuple(p) for p in picks[:3])           # never the cross product
    assert machine["info"]["picks"] == 7 and machine["info"]["rows"] == 3


def test_a_store_row_is_exactly_the_row_its_pick_gets_alone(machine):
    alone = {(r["signal"], r["sl"], r["tp"]): r for r in machine["alone"]}
    for r in machine["rows"]:
        assert r == alone[(r["signal"], r["sl"], r["tp"])]


def test_every_row_is_a_backtest_v2_row(machine):
    rows = machine["rows"]
    assert {r["res"] for r in rows} == {"1m"} and {r["sizing"] for r in rows} == {"flat"}
    assert max(r["days"] for r in rows) <= 31                   # Backtest v2's own 30 days
    for k in ("t15", "t1", "t2", "t3", "t4", "rt_paid", "gate_blocked", "cost_unmeasured",
              "chase_skip"):
        assert all(k in r for r in rows), k


def test_a_pick_with_no_row_is_named_with_why(machine):
    picks = machine["picks"]
    why = {(m[0], m[1], m[2]): m[3] for m in machine["info"]["missing"]}
    assert set(why) == {tuple(p) for p in picks[3:]}
    assert why[tuple(picks[3])] == "no signal in its last 30 days"
    assert "planted" in why[tuple(picks[4])]                     # a signal that raised
    assert why[tuple(picks[5])].startswith("the name means something else in this code")
    # every signal refused is said so, with the count: never a bare "no trade"
    assert why[tuple(picks[6])].startswith("no trade in its last 30 days: all ")
    assert "by the cost check" in why[tuple(picks[6])]
    kinds = {(m[0], m[1], m[2]): m[4] for m in machine["info"]["missing"]}
    assert [kinds[tuple(p)] for p in picks[3:]] == ["no_signal", "signal_error", "renamed",
                                                     "refused"]
    assert machine["refused"] == {"cq_ex24": machine["refused"]["cq_ex24"]}
