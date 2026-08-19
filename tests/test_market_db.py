"""The permanent market database: candles in, same candles out, updates only
move the tail, and a dead database never raises into a caller."""

from __future__ import annotations

import pandas as pd
import pytest

from tradingagents.dataflows import market_db as mdb


@pytest.fixture
def db(tmp_path, monkeypatch):
    """A real SQL database on disk (SQLite speaks the same ON CONFLICT
    dialect the Neon store uses), wired in through the env URL."""
    monkeypatch.setenv(mdb.DB_URL_ENV, f"sqlite:///{tmp_path}/market.db")
    monkeypatch.setattr(mdb, "_ENGINE", None)
    monkeypatch.setattr(mdb, "_ENGINE_URL", None)
    monkeypatch.setattr(mdb, "_down_until", 0.0)
    assert mdb.ensure_schema()
    return mdb


def _frame(ts0: int = 1_787_000_000, n: int = 5, step: int = 900,
           close: float = 1.0) -> pd.DataFrame:
    ts = [ts0 + i * step for i in range(n)]
    return pd.DataFrame({
        "Date": pd.to_datetime(ts, unit="s"),
        "Open": [1.0] * n, "High": [2.0] * n, "Low": [0.5] * n,
        "Close": [close] * n, "Volume": [10.0] * n,
    })


def test_candles_round_trip(db):
    assert db.upsert_candles("APEX_USDT", "Min15", _frame()) == 5
    out = db.candles_df("APEX_USDT", "Min15")
    assert len(out) == 5
    assert list(out["Close"]) == [1.0] * 5
    assert out["Date"].is_monotonic_increasing
    # window filters take unix seconds, inclusive
    part = db.candles_df("APEX_USDT", "Min15",
                         start=1_787_000_900, end=1_787_001_800)
    assert len(part) == 2


def test_resending_a_bar_overwrites_not_duplicates(db):
    db.upsert_candles("APEX_USDT", "Min15", _frame(close=1.0))
    db.upsert_candles("APEX_USDT", "Min15", _frame(close=9.9))
    out = db.candles_df("APEX_USDT", "Min15")
    assert len(out) == 5, "same bars re-sent must not duplicate"
    assert list(out["Close"]) == [9.9] * 5, "the fresh copy wins"


def test_last_ts_and_coverage(db):
    assert db.last_ts("APEX_USDT", "Min15") is None
    db.upsert_candles("APEX_USDT", "Min15", _frame())
    assert db.last_ts("APEX_USDT", "Min15") == 1_787_000_000 + 4 * 900
    cov = db.coverage()
    assert cov == [{"symbol": "APEX_USDT", "timeframe": "Min15", "bars": 5,
                    "first_ts": 1_787_000_000,
                    "last_ts": 1_787_000_000 + 4 * 900}]


def test_download_stores_all_then_only_the_new_tail(db):
    class FakeFx:
        frame = _frame(n=5)

        @staticmethod
        def klines(symbol, interval, limit):
            return FakeFx.frame

    r1 = db.download(["APEX_USDT"], ["Min15"], fx=FakeFx)
    assert r1["bars_stored"] == 5 and not r1["errors"]
    # two new bars print; a re-run moves only those two
    FakeFx.frame = _frame(n=7)
    r2 = db.download(["APEX_USDT"], ["Min15"], fx=FakeFx)
    assert r2["bars_stored"] == 2, "update must not re-send stored bars"
    assert len(db.candles_df("APEX_USDT", "Min15")) == 7


def test_download_survives_a_dead_symbol(db):
    class FakeFx:
        @staticmethod
        def klines(symbol, interval, limit):
            raise RuntimeError("no such contract")

    r = db.download(["GONE_USDT"], ["Min15"], fx=FakeFx)
    assert r["bars_stored"] == 0
    assert len(r["errors"]) == 1


def test_results_round_trip_and_overwrite(db):
    row = {"row_code": "#LLZM9D", "symbol": "APEX_USDT", "timeframe": "1h",
           "signal": "sweep30", "tp": 0.04, "sl": 0.01, "sizing": "flat",
           "data_start": 1, "data_end": 2, "profit": 10.0, "trades": 30,
           "wins": 20, "losses": 10, "win_rate": 0.667,
           "worst_streak": -5.0, "worst_streak_len": 3}
    assert db.save_results([row]) == 1
    got = db.load_results(symbol="APEX_USDT")
    assert len(got) == 1 and got[0]["profit"] == 10.0
    # same key recomputed -> replaced, not duplicated
    assert db.save_results([{**row, "profit": 12.5}]) == 1
    got = db.load_results(symbol="APEX_USDT")
    assert len(got) == 1 and got[0]["profit"] == 12.5
    # a new window is a NEW row: both windows stay queryable
    assert db.save_results([{**row, "data_end": 3, "profit": 8.0}]) == 1
    assert len(db.load_results(symbol="APEX_USDT")) == 2
    assert db.load_results(symbol="APEX_USDT", data_end=3)[0]["profit"] == 8.0


def test_no_database_means_quiet_noops(monkeypatch):
    monkeypatch.delenv(mdb.DB_URL_ENV, raising=False)
    monkeypatch.setattr(mdb, "STORE_PATH", mdb.Path("/nonexistent/nope.json"))
    assert not mdb.available()
    assert mdb.upsert_candles("X", "Min15", _frame()) == 0
    assert mdb.candles_df("X", "Min15") is None
    assert mdb.last_ts("X", "Min15") is None
    assert mdb.coverage() == []
    assert mdb.save_results([{"row_code": "x"}]) == 0
    assert mdb.load_results() == []


def test_a_dying_database_stands_down_instead_of_raising(db, monkeypatch):
    db.upsert_candles("APEX_USDT", "Min15", _frame())

    class Boom:
        def connect(self):
            raise RuntimeError("connection refused")

        def begin(self):
            raise RuntimeError("connection refused")

    monkeypatch.setattr(mdb, "_engine", lambda: Boom())
    assert mdb.candles_df("APEX_USDT", "Min15") is None   # no raise
    assert mdb._down_until > 0, "must stand down after a failure"
    # while down, calls answer instantly without touching the engine
    assert mdb.coverage() == []
