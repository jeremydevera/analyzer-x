"""The fold must not hold the whole market in memory.

Aug 26, 2026 5:20am: the 2-month sweep died with MemoryError at
backtest_report.py:1019 -- `rows += msw.pair_rows(show, tf)` -- after
measuring 2,367 pairs. The row files were 15.40 GB of JSON on a 17.1 GB
machine, and JSON becomes 3-5x that as Python dicts, so the summarising step
could never finish a market-wide run however long the measuring took.

The measuring was always per-pair and on disk. Only the fold was unbounded.
So the fold now STREAMS: every row goes to the grid snapshot as it is read,
the payload keeps a bounded selection for the page, and the true total is
reported rather than implied (rule 20 -- a capped grid says what it capped).
"""
import concurrent.futures as cf
import json

import pytest

from tradingagents import backtest_report as br, market_sweep as msw, parquet_store as pqs


def _row(coin, tf, sig, profit, **kw):
    r = {"coin": coin, "tf": tf, "signal": sig, "th": 0.3, "sl": 0.6, "tp": 1.8,
         "sizing": "flat", "profit": profit, "trades": 120, "wins": 60,
         "losses": 60, "winrate": 50.0, "dd": 1.0, "days": 89, "bars": 2159,
         "monthly": {"2026-07": profit / 2, "2026-08": profit / 2},
         "green": 1, "months": 2, "lev": 20, "base": 5.0}
    r.update(kw)
    return r


class FakePool:
    def __init__(self, *a, **kw):
        pass

    def submit(self, fn, *a, **kw):
        fut = cf.Future()
        try:
            fut.set_result(fn(*a, **kw))
        except Exception as exc:      # noqa: BLE001
            fut.set_exception(exc)
        return fut

    def shutdown(self, wait=True, *, cancel_futures=False):
        pass


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A fake store: N pairs, each with a known number of rows on 'disk'."""
    monkeypatch.setattr(msw, "HOME", tmp_path)
    monkeypatch.setattr(msw, "CANDLES", tmp_path / "candles")
    monkeypatch.setattr(msw, "STATES", tmp_path / "state")
    monkeypatch.setattr(msw, "ROWDIR", tmp_path / "rows")
    monkeypatch.setattr(pqs, "GRIDS", tmp_path / "grids")
    monkeypatch.setattr(msw, "completed_pairs", lambda pairs: set())
    monkeypatch.setattr(msw, "worker_clear", lambda: None)
    monkeypatch.setattr(msw, "worker_read", lambda: [])
    monkeypatch.setattr(msw, "be_polite", lambda: None)
    monkeypatch.setattr(msw, "cached_candles", lambda sym, tf: None)
    monkeypatch.setattr(cf, "ProcessPoolExecutor", FakePool)

    held: dict = {}

    def set_pair(coin, tf, rows):
        held[(coin, tf)] = rows

    monkeypatch.setattr(msw, "pair_rows", lambda coin, tf: list(held.get((coin, tf), [])))
    monkeypatch.setattr(msw, "run_pair", lambda sym, tf, **kw: {
        "coin": sym.replace("_USDT", ""), "tf": tf, "rows": [], "why": "no new bars",
        "bars": 2159, "days": 89, "rt": 0.0004, "liq": 4.0, "fee": 0.0004,
        "incremental": True, "new_bars": 0})
    return set_pair


def test_every_row_reaches_the_grid_while_the_payload_is_capped(store):
    for i, coin in enumerate(("AAA", "BBB", "CCC")):
        store(coin, "1h", [_row(coin, "1h", f"sig{j}", 10.0 - j) for j in range(20)])
    got = br.grid_from_store(["AAA_USDT", "BBB_USDT", "CCC_USDT"], ["1h"],
                             workers=2, row_cap=25)
    assert got["rows_total"] == 60, "the true count of combinations tested"
    assert got["rows_capped"] is True
    assert len(got["rows"]) == 25, "the page keeps a bounded selection"
    # the SNAPSHOT holds every row, not the selection
    import pyarrow.parquet as pq

    assert got["grid_path"], "the streamed snapshot is named in the payload"
    assert pq.read_metadata(got["grid_path"]).num_rows == 60


def test_a_small_grid_is_unchanged_every_row_and_every_column(store):
    store("AAA", "1h", [_row("AAA", "1h", f"sig{j}", 1.0 * j) for j in range(8)])
    got = br.grid_from_store(["AAA_USDT"], ["1h"], workers=1, row_cap=25)
    assert got["rows_total"] == 8 and got["rows_capped"] is False
    assert len(got["rows"]) == 8
    keys = {k for r in got["rows"] for k in r}
    for r in got["rows"]:
        assert set(r) == keys, "every row carries every column (kit item F)"
        assert len(r["mon"]) == len(got["months"])
        assert r["id"] and "monthly" not in r


def test_the_deployed_row_survives_the_cap(store):
    # 40 fat winners plus the operator's own row at the bottom of the profit column
    # a non-threshold signal is stored with th = 0.0, and grid_from_store
    # normalises the deployed dict the same way -- so the test uses the store's
    # own convention rather than inventing one
    store("AAA", "1h", [_row("AAA", "1h", f"sig{j}", 100.0 - j) for j in range(40)]
          + [_row("AAA", "1h", "mine", -50.0, th=0.0)])
    got = br.grid_from_store(["AAA_USDT"], ["1h"], workers=1, row_cap=10,
                             deployed=[{"coin": "AAA", "tf": "1h", "signal": "mine",
                                        "th": 0.0, "sl": 0.6, "tp": 1.8,
                                        "sizing": "flat"}])
    assert got["rows_capped"] is True and got["rows_total"] == 41
    assert any(r["signal"] == "mine" for r in got["rows"]), \
        "rule 21: the deployed combination must be on the page"


def test_a_row_with_an_unexpected_field_is_kept_and_named(store):
    store("AAA", "1h", [_row("AAA", "1h", "sig0", 1.0)])
    store("BBB", "1h", [_row("BBB", "1h", "sig0", 2.0, brand_new_field=7)])
    got = br.grid_from_store(["AAA_USDT", "BBB_USDT"], ["1h"], workers=2, row_cap=100)
    assert got["rows_total"] == 2
    import pyarrow.parquet as pq

    t = pq.read_table(got["grid_path"])
    assert t.num_rows == 2
    # which pair declares the schema depends on which finishes first, so the
    # contract is: the field survives EITHER as its own column, or inside the
    # `extra` blob AND named in schema_extra. Never lost, never silent.
    cols = set(t.column_names)
    if "brand_new_field" in cols:
        assert 7 in t.column("brand_new_field").to_pylist()
    else:
        blobs = [json.loads(v) for v in t.column("extra").to_pylist() if v]
        assert any(b.get("brand_new_field") == 7 for b in blobs), blobs
        assert "brand_new_field" in got["schema_extra"], \
            "a field outside the declared schema is NAMED, not silently absorbed"


def test_aggregates_are_computed_over_every_row_not_the_selection(store):
    store("AAA", "1h", [_row("AAA", "1h", f"win{j}", 5.0) for j in range(30)]
          + [_row("AAA", "1h", f"lose{j}", -5.0) for j in range(70)])
    got = br.grid_from_store(["AAA_USDT"], ["1h"], workers=1, row_cap=5)
    assert got["rows_total"] == 100
    assert got["profitable_total"] == 30, "counted while streaming, not from the page"
    assert got["trades_total"] == 100 * 120
