"""The full CSV holds EVERY matching row — and is the quick download's twin.

Operator, Sep 25, 2026: *"when i download csv you are only downloading top
2000, if the result is bilion i want to see billion in csv"*. A days window
re-measures every row it exports, so the quick download stops at
`rows_index.DAYS_CSV_MAX`. `tradingagents/full_export.py` re-checks every
matching row a coin at a time and writes the file through the SAME
`api.strategies_csv_lines`, looking the window figures up.

Verified on the operator's own store before these tests were written: CAKE,
win % >= 85, TP >= SL, last 30 days — 1,309 matched, 940 passed the window,
and the full file was byte-identical to the quick download's.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

import tradingagents.rows_index as ri

REPO = Path(__file__).resolve().parent.parent


def _fake_window(rows, days, *a, **k):
    """A deterministic re-measure: the window keeps trades-2 of them and wins
    all but one, so some rows fail a win % floor INSIDE the window."""
    for r in rows:
        t = max(0, int(r["trades"]) - 2)
        # every row whose id ends in an even digit wins only half inside the
        # window — so a win % floor cuts rows that passed on whole history
        w = t // 2 if int(r["id"][-1]) % 2 == 0 else t
        r.update(restated=True, w_trades=t, w_wins=w, w_losses=t - w,
                 w_winrate=round(100.0 * w / t, 2) if t else 0.0,
                 w_profit=float(r["profit"]) / 2, w_dd=1.0, w_funding=0.0,
                 w_first="Aug 26, 2026 12:15am", w_last="Sep 23, 2026 12:30am",
                 w_days=28.0, w_straddle=0)
    return {"rows": rows, "first": "", "last": "", "groups": 1,
            "skipped": {"no_candles": 0, "outside_window": 0, "failed": 0},
            "straddled": 0}


@pytest.fixture
def store(tmp_path, monkeypatch):
    from tradingagents import market_sweep as msw, stores

    db = tmp_path / "rows.db"
    monkeypatch.setattr(ri, "DB_PATH", db)
    ri._ready.discard(str(db))
    ri.forget_indexes()
    ri.ensure()
    rows = []
    for c, coin in enumerate(("AAA", "BBB", "CCC")):
        rows += [{"id": f"{coin}{i:03d}", "coin": coin, "tf": "1h",
                  "signal": "ema", "profit": float((i * 7 + c) % 97),
                  "winrate": 80.0 + (i % 20), "trades": 5 + (i % 9), "dd": 2.0,
                  "tp": 2.0, "sl": 1.0, "sizing": "flat", "monthly": {}}
                 for i in range(40)]
    for coin in ("AAA", "BBB", "CCC"):
        f = tmp_path / f"{coin}_USDT-1h.json"
        f.write_text(json.dumps([r for r in rows if r["coin"] == coin]),
                     encoding="utf-8")
        with ri._open() as con:
            ri.index_pair(f, con)
    monkeypatch.setattr(msw, "window_rows", _fake_window)
    # the v1 store's folder, sandboxed, for the finished file
    v1 = stores.Store(name="v1", home=tmp_path / "v1home", candles=tmp_path / "c",
                      rows_db=db, parquet=tmp_path / "p", fine_tf="",
                      download_kind="download", backtest_kind="backtest")
    monkeypatch.setitem(stores._BY_NAME, "v1", v1)
    monkeypatch.setattr(stores, "V1", v1)
    return db, rows


def _run(db, spec):
    from tradingagents import full_export as fx

    seen: list = []
    facts = fx.run(spec, db, "v1", lambda **kw: seen.append(kw), processes=0)
    return facts, seen


def test_the_full_file_is_the_quick_files_twin(store):
    """Same filter, both small enough for the quick path: identical bytes."""
    from tradingagents import api

    db, _ = store
    facts, _ = _run(db, {"min_winrate": 85, "days": 30})
    full = Path(facts["file"]).read_text(encoding="utf-8")
    quick = "".join(api.strategies_csv_lines(min_winrate=85, days=30, _dl={}))
    assert full == quick


def test_there_is_no_2000_row_ceiling(store, monkeypatch):
    """The quick download stops at DAYS_CSV_MAX; the full file does not."""
    from tradingagents import api

    db, rows = store
    monkeypatch.setattr(ri, "DAYS_CSV_MAX", 7)
    facts, _ = _run(db, {"days": 30})
    body = Path(facts["file"]).read_text(encoding="utf-8")
    data = [r for r in csv.DictReader(io.StringIO(body)) if r["id"][:3] in ("AAA", "BBB", "CCC")]
    assert len(data) == len(rows) == facts["rows"] == 120, len(data)
    assert "WINDOW CAPPED" not in body
    quick = "".join(api.strategies_csv_lines(days=30, _dl={}))
    assert "WINDOW CAPPED" in quick, "the quick file still says it stopped"


def test_the_window_floor_is_applied_and_counted(store):
    db, rows = store
    facts, _ = _run(db, {"min_winrate": 85, "days": 30})
    body = Path(facts["file"]).read_text(encoding="utf-8")
    data = [r for r in csv.DictReader(io.StringIO(body)) if r["id"][:3] in ("AAA", "BBB", "CCC")]
    assert all(float(r["winrate"]) >= 85 for r in data)
    matched = sum(1 for r in rows if r["winrate"] >= 85)
    assert facts["matched"] == matched and facts["rows"] == len(data) < matched
    assert "WINDOW FLOOR" in body and facts["floor_note"].startswith("WINDOW FLOOR")


def test_it_reports_progress_and_the_exact_match_count(store):
    db, rows = store
    facts, seen = _run(db, {"min_winrate": 85, "days": 30})
    phases = [s.get("phase") for s in seen if s.get("phase")]
    assert phases[0] == "counting the rows" and "re-checking" in phases
    assert "writing the file" in phases
    last = [s for s in seen if s.get("phase") == "re-checking"][-1]
    assert last["done"] == last["total"] == facts["matched"]


def test_a_quick_file_cut_by_the_floor_still_says_it_was_capped(store, monkeypatch):
    """Found building this: 2,000 re-measured with 133 cut wrote 1,867, and
    the old `sent >= 2,000` test left that file silent about its cap."""
    from tradingagents import api

    monkeypatch.setattr(ri, "DAYS_CSV_MAX", 10)
    body = "".join(api.strategies_csv_lines(min_winrate=85, days=30, _dl={}))
    data = [r for r in csv.DictReader(io.StringIO(body)) if r["id"][:3] in ("AAA", "BBB", "CCC")]
    assert len(data) < 10, "some of the 10 re-measured rows were cut"
    assert "WINDOW CAPPED" in body


def test_the_same_filter_names_the_same_job(store):
    from tradingagents import full_export as fx

    a = fx.key_of({"min_winrate": 85, "tp_over_sl": True, "days": 30, "coin": ""})
    b = fx.key_of({"tp_over_sl": True, "min_winrate": 85, "days": 30, "sort": "profit"})
    assert a == b


def test_the_download_route_only_serves_the_jobs_own_file(store, monkeypatch, tmp_path):
    from fastapi import HTTPException

    from tradingagents import api, db_jobs as dj

    monkeypatch.setattr(dj, "status", lambda kind: {"running": False,
                                                    "file": "../../secrets.txt"})
    with pytest.raises(HTTPException) as got:
        api.strategies_export_file()
    assert got.value.status_code == 404
    monkeypatch.setattr(dj, "status", lambda kind: {"running": True, "file": "x.csv"})
    with pytest.raises(HTTPException):
        api.strategies_export_file()


def test_a_second_filter_cannot_start_while_one_builds(store, monkeypatch):
    from fastapi import HTTPException

    from tradingagents import api, db_jobs as dj, full_export as fx

    running = {"running": True, "key": fx.key_of({"min_winrate": 85, "days": 30})}
    monkeypatch.setattr(dj, "status", lambda kind: running)
    monkeypatch.setattr(dj, "start", lambda *a, **k: pytest.fail("no second job"))
    same = api.strategies_export({"min_winrate": 85, "days": 30})
    assert same["running"] is True and same["started"] is False
    with pytest.raises(HTTPException) as got:
        api.strategies_export({"min_winrate": 70, "days": 30})
    assert got.value.status_code == 409


def test_the_panel_offers_the_full_file_under_a_days_window():
    panel = (REPO / "webapp/src/components/backtest/StrategiesPanel.tsx").read_text(encoding="utf-8")
    assert "build the full CSV — all ${total.toLocaleString()}" in panel
    assert "download ALL ${(exportJob.done ?? 0).toLocaleString()} rows — the full CSV" in panel
    assert "or just the top ${csvMax.toLocaleString()} now" in panel
    assert "pass the last ${servedFilters.days} days (full re-check" in panel
    # the body the panel sends has the job's own keys
    from tradingagents import full_export as fx

    body = panel[panel.index("const exportBody = (f: typeof applied)"):]
    body = body[:body.index("return b;")]
    for k in fx.FILTER_KEYS:
        assert f"{k}:" in body, f"the full CSV would ignore {k}"
