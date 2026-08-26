"""ALL the rows, not a page of them.

Operator, 2026-08-26: "in Stored strategies i can still only see like about
100 rows give me all / i dont want to repeat this agian".

21,858,026 rows do not fit in a DOM table or in one JSON response, so `all`
has two shapes: a page the screen can actually hold (up to MAX_LIMIT, and a
LOAD MORE that keeps appending), and a streamed CSV with no ceiling at all.
Both must carry every field the table shows (kit item F) and obey the same
filters and order — a export that quietly differs from the screen is worse
than no export.
"""
import csv
import io
import json

import pytest

from tradingagents import market_sweep as msw, rows_index as ri


def _csv(**kw) -> str:
    """The CSV as text. The generator is module-level so no event loop (and so
    no socket, and so no tripped network guard) is needed to read it."""
    from tradingagents import api

    return "".join(api.strategies_csv_lines(**kw))


def _row(coin, tf, signal, profit, trades=120, winrate=50.0):
    return {"coin": coin, "tf": tf, "signal": signal, "th": 0.1, "sl": 0.3,
            "tp": 0.9, "rr": 3.0, "sizing": "flat", "lev": 20, "base": 5.0,
            "notional": 100.0, "trades": trades, "wins": 60, "losses": 60,
            "winrate": winrate, "profit": profit, "funding": -0.2, "h1": 1.0,
            "h2": 1.0, "green": 8, "months": 12, "worst": -4.1, "dd": 22.0,
            "liqs": 0, "stop_reachable": True, "days": 360, "bars": 34000,
            "monthly": {"2026-07": 1.5, "2026-08": profit / 3},
            "cost_of_tp": 12.5, "rt": 0.04, "gate": "ok"}


@pytest.fixture
def store(tmp_path, monkeypatch):
    rows_dir = tmp_path / "rows"
    rows_dir.mkdir()
    monkeypatch.setattr(msw, "ROWDIR", rows_dir)
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    batch = [_row("BTC", "1h", f"sig{i:03d}", 500.0 - i) for i in range(120)]
    batch += [_row("PI", "15m", f"sig{i:03d}", 10.0 - i, trades=40) for i in range(30)]
    (rows_dir / "BTC-1h.json").write_text(json.dumps(batch[:120]))
    (rows_dir / "PI-15m.json").write_text(json.dumps(batch[120:]))
    import time

    ri.sync(now=time.time() + ri.SETTLE_S + 1)
    return batch


def test_iter_rows_yields_every_match_with_no_limit(store):
    got = list(ri.iter_rows())
    assert len(got) == 150, len(got)
    assert len({r["id"] for r in got}) == 150
    # in the default order, highest profit first
    assert got[0]["profit"] > got[-1]["profit"]


def test_iter_rows_obeys_the_filters_and_the_direction(store):
    assert len(list(ri.iter_rows(coin="PI"))) == 30
    assert len(list(ri.iter_rows(min_trades=100))) == 120
    up = list(ri.iter_rows(sort="profit", desc=False))
    assert up[0]["profit"] < up[-1]["profit"]
    assert len(list(ri.iter_rows(profitable=True))) == 120 + 10


def test_iter_rows_batches_without_dropping_a_row_at_the_seam(store):
    small = [r["id"] for r in ri.iter_rows(batch=100)]
    assert len(small) == 150 and len(set(small)) == 150


def test_a_page_may_now_be_thousands_not_three_hundred():
    assert ri.MAX_LIMIT >= 5_000
    from tradingagents import api
    import inspect

    assert "limit" in inspect.signature(api.strategies).parameters


def test_the_csv_carries_every_field_the_table_shows(store):
    from tradingagents import api

    body = _csv()
    rows = list(csv.reader(io.StringIO(body)))
    head, data = rows[0], rows[1:]
    for col in ri.COLS:
        assert col in head, f"{col} missing from the export"
    assert "monthly_json" in head, "the month figures must survive the export"
    assert len(data) == 150, f"{len(data)} rows exported, expected 150"
    # and the same order as the screen's default
    p = head.index("profit")
    assert float(data[0][p]) > float(data[-1][p])
    m = head.index("monthly_json")
    assert json.loads(data[0][m]).get("2026-07") == 1.5


def test_the_csv_obeys_the_screens_filters(store):
    from tradingagents import api

    body = _csv(coin="PI", sort="winrate", min_trades=0)
    rows = list(csv.reader(io.StringIO(body)))
    assert len(rows) - 1 == 30
    coin = rows[0].index("coin")
    assert {r[coin] for r in rows[1:]} == {"PI"}


def test_the_csv_is_offered_as_a_download_with_a_name_that_says_the_filter(store):
    from tradingagents import api

    name = api.strategies_csv_name("PI", "15m", None, 100, "winrate")
    assert name.endswith(".csv")
    for bit in ("PI", "15m", "min100", "winrate"):
        assert bit in name, name
