"""Parquet is the home of the RECOMPUTABLE bulk — full candle history and
complete sweep grids. Losing a file costs a re-download, never history, so the
invariants under test are narrow and hard:

* round-trips are IDENTICAL (dtypes, order, values) — a store that mutates
  candles corrupts every backtest that reads them;
* writes are atomic — a half-written file is worse than none;
* timeframes use the same shared labels the database uses, so the two stores
  can name the same thing the same way.
"""
import json
import os

import pandas as pd
import pytest

from tradingagents import parquet_store as pq


@pytest.fixture(autouse=True)
def _root(tmp_path, monkeypatch):
    monkeypatch.setattr(pq, "ROOT", tmp_path)
    monkeypatch.setattr(pq, "CANDLES", tmp_path / "candles")
    monkeypatch.setattr(pq, "GRIDS", tmp_path / "grids")


def _frame(n=5):
    return pd.DataFrame({
        "Date": pd.to_datetime([1_787_000_000 + i * 900 for i in range(n)],
                               unit="s"),
        "Open": [1.0 + i for i in range(n)],
        "High": [1.5 + i for i in range(n)],
        "Low": [0.5 + i for i in range(n)],
        "Close": [1.2 + i for i in range(n)],
        "Volume": [10.0 * i for i in range(n)]})


def test_candles_round_trip_identical():
    df = _frame()
    p = pq.save_candles("APEX_USDT", "Min15", df)   # MEXC name in…
    assert p.name == "APEX_USDT-15m.parquet"        # …shared label on disk
    back = pq.load_candles("APEX_USDT", "15m")
    # the store's contract: Date always comes back as nanoseconds, whatever
    # resolution went in — so compare against the ns view of the input
    want = df.copy()
    want["Date"] = want["Date"].astype("datetime64[ns]")
    pd.testing.assert_frame_equal(back, want)


def test_round_trip_from_second_resolution_frames():
    """MEXC frames arrive as datetime64[s]; the store must hand back
    nanoseconds either way, or bar-time comparisons silently fail."""
    df = _frame()
    df["Date"] = df["Date"].values.astype("datetime64[s]")
    pq.save_candles("SEC_USDT", "1h", df)
    back = pq.load_candles("SEC_USDT", "1h")
    assert str(back["Date"].dtype) == "datetime64[ns]"
    assert list(back["Date"].astype("int64")) ==         list(df["Date"].astype("datetime64[ns]").astype("int64"))


def test_candles_findable_under_either_timeframe_name():
    pq.save_candles("APEX_USDT", "15m", _frame())
    assert pq.load_candles("APEX_USDT", "Min15") is not None


def test_missing_candles_return_none():
    assert pq.load_candles("NOPE_USDT", "1h") is None


def test_writes_are_atomic_no_tmp_left_behind():
    pq.save_candles("APEX_USDT", "15m", _frame())
    leftovers = [f for f in os.listdir(pq.CANDLES)
                 if not f.endswith(".parquet")]
    assert leftovers == []


def test_grid_snapshot_round_trip_with_dict_columns():
    rows = [{"coin": "XAUT", "tf": "1h", "signal": "mom6", "profit": 1.5,
             "monthly": {"2026-08": 1.5}, "mon": [1.5, None]},
            {"coin": "XAUT", "tf": "1h", "signal": "fvg", "profit": -2.0,
             "monthly": {}, "mon": []}]
    p = pq.save_grid(rows, label="xaut-test", day="2026-08-20")
    assert p.name == "2026-08-20-xaut-test.parquet"
    back = pq.load_grid(p)
    assert len(back) == 2
    assert back.iloc[0]["profit"] == 1.5
    assert json.loads(back.iloc[0]["monthly"]) == {"2026-08": 1.5}


def test_empty_grid_refuses():
    """An empty snapshot must never satisfy the prune guard."""
    with pytest.raises(ValueError):
        pq.save_grid([], label="empty")


def test_sizes_reports_both_stores():
    pq.save_candles("A_USDT", "1h", _frame())
    pq.save_grid([{"coin": "A", "profit": 1.0}], label="t", day="2026-08-20")
    s = pq.sizes()
    assert s["candles"]["files"] == 1 and s["candles"]["rows"] == 5
    assert s["grids"]["files"] == 1 and s["grids"]["rows"] == 1
    assert s["candles"]["bytes"] > 0


def test_sizes_when_nothing_written_yet():
    s = pq.sizes()
    assert s["candles"] == {"files": 0, "rows": 0, "bytes": 0}
    assert s["grids"] == {"files": 0, "rows": 0, "bytes": 0}


def test_sizes_can_skip_the_row_count(tmp_path, monkeypatch):
    """Counting rows opens every parquet file — 4,909 of them on the real
    store, over 20s while the sweep is running. /api/health is polled every
    10 seconds, so it must not do that."""
    import pyarrow.parquet as pa

    from tradingagents import parquet_store as pq

    monkeypatch.setattr(pq, "CANDLES", tmp_path / "c")
    monkeypatch.setattr(pq, "GRIDS", tmp_path / "g")
    (tmp_path / "c").mkdir()
    (tmp_path / "g").mkdir()
    pq.save_candles("BTC_USDT", "15m", _frame())

    opens = []
    real = pa.ParquetFile
    monkeypatch.setattr(pa, "ParquetFile",
                        lambda *a, **k: (opens.append(a), real(*a, **k))[1])

    cheap = pq.sizes(rows=False)
    assert not opens, f"health opened {len(opens)} parquet files"
    assert cheap["candles"]["files"] == 1
    assert cheap["candles"]["bytes"] > 0
    assert cheap["candles"]["rows"] is None, (
        "None says 'not counted'; a 0 would read as an empty store")

    full = pq.sizes()
    assert opens, "the storage screen still counts rows"
    assert full["candles"]["rows"] > 0
