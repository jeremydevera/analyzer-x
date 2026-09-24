"""The Stored strategies table says EXACTLY how many rows match.

Operator, Sep 25, 2026, over "of 200+" pages: *"when i filter the table can
you show how many rows exacty is it"*. The page's own count stops at
`rows_index.COUNT_CAP` (5,000) — a filtered COUNT(*) over 49.5 million rows
does not fit in a 20-second request — so the SAME query is counted exactly in
the background (`rows_index.count_exact`, `api.exact_count_state`) and the
panel swaps the number in. Measured on Backtest v2 that morning: win % >= 85
with TP >= SL = 1,369,665 (~5 s); TP >= SL alone = 39,403,722 (261.6 s).
"""
from __future__ import annotations

import inspect
import json
import threading
import time
from pathlib import Path

import pytest

import tradingagents.rows_index as ri

REPO = Path(__file__).resolve().parent.parent
PANEL = REPO / "webapp/src/components/backtest/StrategiesPanel.tsx"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    ri._ready.discard(str(tmp_path / "rows.db"))
    ri.forget_indexes()
    ri.ensure()
    rows = [{"id": f"R{i:04d}", "coin": "AAA", "tf": "1h",
             "signal": "ema" if i % 3 else "cf_soup1", "profit": float(i % 97),
             "winrate": 50.0 + (i % 50), "trades": 40 + i, "dd": 2.0,
             "tp": 1.0 + (i % 4), "sl": 1.0 + (i % 3), "sizing": "flat",
             "monthly": {}} for i in range(400)]
    f = tmp_path / "AAA_USDT-1h.json"
    f.write_text(json.dumps(rows), encoding="utf-8")
    with ri._open() as con:
        ri.index_pair(f, con)
    monkeypatch.setattr(ri, "COUNT_CAP", 50)       # the page's cap, small
    return rows


def _truth(rows, pred):
    return sum(1 for r in rows if pred(r))


def test_the_page_stays_capped_and_the_count_is_exact(store):
    page = ri.query(min_winrate=60, limit=5)
    truth = _truth(store, lambda r: r["winrate"] >= 60)
    assert truth > ri.COUNT_CAP
    assert ri.count_exact(min_winrate=60) == truth
    assert page["rows"], "the page itself still answers"


def test_every_filter_shape_counts_exactly(store):
    """The shortcuts that answer "over the cap" (-1) must not answer the
    exact count: the win-rate range and the group path."""
    cases = [
        ({"min_winrate": 60}, lambda r: r["winrate"] >= 60),
        ({"min_winrate": 60, "min_trades": 100},
         lambda r: r["winrate"] >= 60 and r["trades"] >= 100),
        ({"tp_over_sl": True}, lambda r: r["tp"] >= r["sl"]),
        ({"group": "preset"}, lambda r: r["signal"].startswith("cf_")),
        ({"coin": "AAA"}, lambda r: True),
    ]
    for kw, pred in cases:
        assert ri.count_exact(**kw) == _truth(store, pred), kw


def test_query_forwards_every_argument_to_another_store(tmp_path, monkeypatch):
    """The lesson of RCA-2026-09-24-E, applied to query()'s own hand-off."""
    seen: dict = {}
    real = ri.query

    def spy(**kw):
        seen.update(kw)
        return {"total": 0, "rows": []}

    monkeypatch.setattr(ri, "query", spy)
    params = [p for p in inspect.signature(real).parameters if p != "db_path"]
    given = {p: f"m-{p}" for p in params}
    real(db_path=tmp_path / "x.db", **given)
    dropped = [p for p in params if seen.get(p) != given[p]]
    assert not dropped, f"query()'s store hand-off dropped {dropped}"


# ------------------------------------------------------- the background counter

@pytest.fixture
def counter(monkeypatch, tmp_path):
    from tradingagents import api

    monkeypatch.setattr(api, "_EXACT", {"results": {}, "running": None, "started": 0.0})
    gate = threading.Event()
    calls: list = []

    def fake_count(**kw):
        calls.append(kw)
        gate.wait(5)
        return 1_369_665 if kw.get("min_winrate") == 85 else 5_697_751

    monkeypatch.setattr(ri, "count_exact", fake_count)
    sig = {"v": (1, 5004, 49_503_932, 100.0)}
    monkeypatch.setattr(api, "_store_sig", lambda db: sig["v"])
    return api, gate, calls, sig, tmp_path / "rows.db"


def _until(fn, state, s=5.0):
    end = time.time() + s
    got = fn()
    while time.time() < end and got["state"] != state:
        time.sleep(0.02)
        got = fn()
    return got


def test_first_ask_counts_later_asks_get_the_number(counter):
    api, gate, calls, _, db = counter
    f = {"min_winrate": 85, "tp_over_sl": True}
    assert api.exact_count_state(db, f)["state"] == "counting"
    assert api.exact_count_state(db, f)["state"] == "counting", \
        "a repeat ask while it runs must not start a second count"
    gate.set()
    got = _until(lambda: api.exact_count_state(db, f), "done")
    assert got["total"] == 1_369_665
    assert len(calls) == 1


def test_a_second_filter_waits_its_turn(counter):
    api, gate, _, _, db = counter
    api.exact_count_state(db, {"min_winrate": 85})
    assert api.exact_count_state(db, {"min_winrate": 70})["state"] == "waiting"
    gate.set()
    _until(lambda: api.exact_count_state(db, {"min_winrate": 85}), "done")
    api.exact_count_state(db, {"min_winrate": 70})
    assert _until(lambda: api.exact_count_state(db, {"min_winrate": 70}),
                  "done")["total"] == 5_697_751


def test_new_rows_mean_a_new_count(counter):
    """Filed rows (the pairs summary moved) or a rebuild swap (the file id)
    change the signature, and a finished number is then counted again."""
    api, gate, calls, sig, db = counter
    gate.set()
    f = {"min_winrate": 85}
    api.exact_count_state(db, f)
    _until(lambda: api.exact_count_state(db, f), "done")
    sig["v"] = (1, 5004, 49_600_000, 200.0)
    assert api.exact_count_state(db, f)["state"] == "counting"
    _until(lambda: api.exact_count_state(db, f), "done")
    assert len(calls) == 2


def test_an_index_build_does_not_look_like_new_rows(tmp_path):
    """Found live: a rows_pr2 build grew the file every second and the
    counter answered "waiting" on its OWN count. The signature is the rows."""
    import sqlite3

    from tradingagents import api

    db = tmp_path / "rows.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE pairs (pair TEXT, n INTEGER, at REAL)")
    con.execute("INSERT INTO pairs VALUES ('AAA-1h', 400, 1.0)")
    con.execute("CREATE TABLE rows (id TEXT, x REAL)")
    con.executemany("INSERT INTO rows VALUES (?, ?)", [(str(i), i) for i in range(2000)])
    con.commit()
    before = api._store_sig(db)
    con.execute("CREATE INDEX grows ON rows (x)")      # an index build
    con.commit()
    con.close()
    assert api._store_sig(db) == before, "the rows summary did not move"


def test_a_count_that_cannot_finish_says_why(counter, monkeypatch):
    api, _, _, _, db = counter

    def refuse(**kw):
        raise ri.SortNotReady("needs the rows_wr4 index; it is being built NOW")

    monkeypatch.setattr(ri, "count_exact", refuse)
    f = {"min_winrate": 85, "tf": "1h"}
    api.exact_count_state(db, f)
    got = _until(lambda: api.exact_count_state(db, f), "failed")
    assert "rows_wr4" in got["why"]


def test_the_v1_and_v2_count_routes_take_the_same_filters():
    from tradingagents import api

    a = set(inspect.signature(api.strategies_count).parameters)
    b = set(inspect.signature(api.strategies_count_v2).parameters)
    assert a == b
    table = set(inspect.signature(api.strategies).parameters)
    paging = {"limit", "offset", "sort", "desc", "months", "days"}
    assert a == table - paging, sorted(a ^ (table - paging))
    assert set(api.COUNT_FILTERS) == a


# ------------------------------------------------------------------- the screen

def test_the_table_and_its_count_are_built_from_one_filter_builder():
    ts = (REPO / "webapp/src/lib/api.ts").read_text(encoding="utf-8")
    assert "export function strategyParams(q: StrategyQuery)" in ts
    count = ts[ts.index("strategiesCount: (q: StrategyQuery) => {"):]
    assert "strategyParams(" in count[:400]
    table = ts[ts.index("strategies: (q: StrategyQuery) => {"):]
    assert "strategyParams(q)" in table[:200]
    panel = PANEL.read_text(encoding="utf-8")
    assert "api.strategies({ ...filterQuery(applied)" in panel
    assert "api.strategiesCount(q)" in panel and "filterQuery(servedFilters)" in panel


def test_the_caption_says_counting_and_then_the_number():
    panel = PANEL.read_text(encoding="utf-8")
    anchor = '{chips.length ? "match" : "stored strategies"}'
    cap = panel[panel.index(anchor):][:2400]
    assert "counting all matches…" in cap and "animate-spin" in cap
    assert "the exact count could not finish" in cap
    assert "setTotal(c.total); setCapped(false)" in panel, \
        "the exact number replaces the capped one"


def test_load_more_sends_every_filter_the_table_sends():
    """RCA-2026-09-25-D. "+500 more" built its filters by hand and had lost
    six — minTp, minSl, tpOverSl, asset, group, measuredDays — so under
    TP >= SL it appended rows whose TP was smaller than their SL. It spreads
    the same builder as the table now."""
    panel = PANEL.read_text(encoding="utf-8")
    more = panel[panel.index("const loadMore = async () => {"):]
    more = more[:more.index("setExtra(")]
    assert "...filterQuery(applied)" in more, more
    # and nothing in it names a filter by hand any more
    assert "applied.minWinrate" not in more and "applied.coin" not in more
