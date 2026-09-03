"""One row by the code in its first column — #6YACZSXX.

Operator, 2026-08-27: *"add filter to input a specific id, it should get
speicic id example #6YACZSXX"*. It is also CLAUDE.md kit item H: the id is
HASHED FROM THE COMBINATION, and quoting a row by it is what stopped
"#05146 / #02054 / not there" and the wrong config being deployed.

Two things this holds shut:

* an id OVERRIDES the other filters. It already names one coin × timeframe ×
  signal × threshold × SL/TP × sizing, so anything else in the WHERE can only
  contradict it — and a contradiction reads as "that id is not in the store"
  when it is.
* it needs its own index. `id` carried none: measured on the operator's store
  (35,863,520 rows) `WHERE id = ?` had not returned after 40 s, plain and over
  both covering indexes that already hold the id. So a lookup on a big store
  without `rows_id` is REFUSED with the reason and the index is built behind
  it — never a 40-second hang.
"""
import json

import pytest

from tradingagents import market_sweep as msw, rows_index as ri


def _settled(**kw):
    import time

    return ri.sync(now=time.time() + ri.SETTLE_S + 1, **kw)


@pytest.fixture
def store(tmp_path, monkeypatch):
    rows_dir = tmp_path / "rows"
    rows_dir.mkdir()
    monkeypatch.setattr(msw, "ROWDIR", rows_dir)
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")

    def row(sig, profit, sizing="flat", winrate=60.0, tp=2.0):
        wins = round(120 * winrate / 100)
        return {"coin": "AAA", "tf": "1h", "signal": sig, "th": 0.1, "sl": 0.3,
                "tp": tp, "rr": 3.0, "sizing": sizing, "lev": 20, "base": 5.0,
                "notional": 100.0, "trades": 120, "wins": wins,
                "losses": 120 - wins, "winrate": winrate, "profit": profit,
                "funding": -0.2, "h1": 1.0, "h2": 1.0, "green": 8,
                "months": 12, "worst": -4.1, "dd": 22.0, "liqs": 0,
                "stop_reachable": True, "days": 360, "bars": 34000,
                "monthly": {}, "cost_of_tp": 12.5, "rt": 0.04, "gate": "ok"}

    (rows_dir / "AAA-1h.json").write_text(json.dumps([
        row("mom6", 900.0, "martingale", winrate=11.0),
        row("rsi14", 40.0, "flat", winrate=88.0, tp=5.0),
        row("trend50", 70.0, "flat", winrate=55.0),
    ]))
    _settled()
    return [r["id"] for r in ri.query()["rows"]]


def test_it_finds_exactly_that_row(store):
    wanted = store[1]
    got = ri.query(row_id=wanted)
    assert [r["id"] for r in got["rows"]] == [wanted]
    assert got["total"] == 1
    assert got["row_id"] == wanted, "the payload says what it looked up"


def test_the_hash_is_the_id_the_table_prints(store):
    """The code is `backtest_report.row_code` — hashed from the combination, so
    the same combination always answers to the same id."""
    from tradingagents import backtest_report as br

    r = ri.query(row_id=store[0])["rows"][0]
    assert r["id"] == br.row_code(r["coin"], r["tf"], r["signal"], r["th"],
                                  r["sl"], r["tp"], r["sizing"])


def test_the_hash_is_not_a_page_sequence(store):
    """A per-page number gave the same live row a different id on every page —
    "#05146 / #02054 / not there" (kit item H). Ids are letters and digits from
    the code alphabet, and they survive a re-index."""
    from tradingagents import backtest_report as br

    for rid in store:
        assert rid and not rid.isdigit(), rid
        assert set(rid) <= set(br._CODE_ALPHABET), rid
    _settled(force=True)
    assert [r["id"] for r in ri.query()["rows"]] == store


def test_the_hash_or_hash_less_form_and_any_case_all_work(store):
    wanted = store[2]
    for typed in (wanted, f"#{wanted}", wanted.lower(), f" #{wanted.lower()} "):
        got = ri.query(row_id=typed)
        assert [r["id"] for r in got["rows"]] == [wanted], typed
        assert got["row_id"] == wanted, "cleaned once, in one place"


def test_an_id_overrides_every_other_filter(store):
    """Kit item H — "a find-by-ID box that overrides the other filters". The
    row below is flat, 88% and TP 5; every filter here contradicts it, and the
    lookup must still return it rather than an empty page."""
    wanted = store[1]
    got = ri.query(row_id=wanted, coin="ZZZ", tf="4h", signal="nope",
                   sizing="martingale", min_winrate=99, min_trades=99999,
                   max_tp=8, profitable=False)
    assert [r["id"] for r in got["rows"]] == [wanted]
    assert got["total"] == 1
    where, args = ri._where(row_id=wanted, coin="ZZZ", min_winrate=99)
    assert where == " WHERE id = ?" and args == [wanted], where


def test_an_unknown_id_is_empty_not_everything(store):
    got = ri.query(row_id="ZZZZZZZZ")
    assert got["rows"] == [] and got["total"] == 0
    assert got["row_id"] == "ZZZZZZZZ", "so the screen can name what it missed"


def test_a_big_store_refuses_until_the_id_index_exists(monkeypatch, tmp_path):
    """40 s of scanning is not an answer. Refuse, say why, build it behind."""
    started = []
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    monkeypatch.setattr(ri, "has_index", lambda name: name != "rows_id")
    monkeypatch.setattr(ri, "_rows_estimate", lambda: ri.UNINDEXED_LIMIT + 1)
    monkeypatch.setattr(ri, "_build_index", lambda name: started.append(name))
    with pytest.raises(ri.SortNotReady) as exc:
        ri.query(row_id="#6yaczsxx")
    assert "6YACZSXX" in str(exc.value), "name the id it could not look up"
    assert "rows_id" in str(exc.value) and "being built" in str(exc.value)
    assert started == ["rows_id"]


def test_a_small_store_just_answers(store):
    """Three rows need no index, and a laptop store must not be told to wait."""
    assert ri.query(row_id=store[0])["total"] == 1


def test_the_index_is_named_when_it_is_there(monkeypatch):
    monkeypatch.setattr(ri, "has_index", lambda name: name == "rows_id")
    assert ri._indexed_by(None, row_id="6YACZSXX") == " INDEXED BY rows_id"
    # and an id outranks a coin: it is one seek
    monkeypatch.setattr(ri, "has_index", lambda name: True)
    assert ri._indexed_by("KAVA", row_id="6YACZSXX") == " INDEXED BY rows_id"
    assert "rows_id" in ri.INDEX_DDL
    assert all("rows_id" not in d for d in ri.KEEP_INDEXES), "on demand only"


def test_the_api_and_the_csv_carry_it(store):
    from tradingagents import api

    got = api.strategies(row_id=f"#{store[1]}")
    assert got["row_id"] == store[1]
    assert [r["id"] for r in got["rows"]] == [store[1]]

    body = "".join(api.strategies_csv_lines(row_id=store[1]))
    lines = [ln for ln in body.strip().split("\n") if ln]
    assert len(lines) == 2, "header plus the one row"
    assert store[1] in body


def test_the_browser_sends_it_and_the_id_overrides_the_and_line():
    client = open("webapp/src/lib/api.ts", encoding="utf-8").read()
    assert client.count('p.set("row_id"') == 2, "the table AND the CSV"

    panel = open("webapp/src/components/backtest/StrategiesPanel.tsx",
                 encoding="utf-8").read()
    assert 'aria-label="Row id"' in panel
    assert 'placeholder="6YACZSXX"' in panel, "the operator's own example"
    # typed with or without the #, any case — cleaned before it is sent
    assert 'rowId.trim().replace(/^#+/, "").trim().toUpperCase()' in panel
    assert panel.count("applied.rowId") >= 3, "table, load-more and CSV"
    # the ANDed sentence must say the id REPLACES the filters, not joins them
    assert "every other filter ignored" in panel
    # a miss is named, and a hit opens the trade log (kit item H)
    assert "no row <b>#{servedFilters.rowId}</b>" in panel.replace("\n", "")
    assert "const idHit = " in panel and "view(idHit)" in panel
