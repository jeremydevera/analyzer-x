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
    # stored under MEXC's name, reported under the shared label
    assert cov == [{"symbol": "APEX_USDT", "timeframe": "15m", "bars": 5,
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


def test_deployment_history_records_what_was_live(db):
    """Config files overwrite. Without this, "what was running on APEX on the
    12th, at what barriers" is unanswerable the moment it is saved."""
    assert db.record_deployment({
        "changed_at": 1000, "strategy_key": "sweep30_1h_w",
        "symbol": "APEX_USDT", "action": "changed", "timeframe": "1h",
        "signal": "sweep30", "threshold": 0.0, "tp": 3.0, "sl": 3.0,
        "sizing": "martingale", "books": "real,paper", "base_margin": 5.0,
        "ladder_step": 6, "row_code": "VB4SNUHQ",
        "prev_json": '{"tp": 4.0, "sl": 1.0}', "note": "cold two months"}) == 1
    got = db.deployments("APEX_USDT")
    assert len(got) == 1
    assert got[0]["tp"] == 3.0 and got[0]["sl"] == 3.0
    assert got[0]["ladder_step"] == 6
    assert got[0]["action"] == "changed"
    # a row with no strategy or coin is not history, it is noise
    assert db.record_deployment({"action": "changed"}) == 0


def test_deployments_come_back_newest_first(db):
    for t in (100, 300, 200):
        db.record_deployment({"changed_at": t, "strategy_key": "k",
                              "symbol": "PI_USDT", "action": "changed"})
    got = db.deployments("PI_USDT")
    assert [d["changed_at"] for d in got] == [300, 200, 100]


def test_ledger_sync_is_idempotent_and_reports_real_writes(db):
    """Syncing the same file twice must not duplicate it — and must not claim
    it wrote rows the second time."""
    lines = [
        {"ts": 10, "action": "enter", "symbol": "PI_USDT", "strategy": "s",
         "side": "SHORT", "entry": 0.087, "margin": 5.0, "dry_run": False},
        {"ts": 20, "action": "exit", "symbol": "PI_USDT", "strategy": "s",
         "exit": 0.085, "pnl": 1.25, "why": "TP", "dry_run": False},
    ]
    assert db.sync_ledger(lines) == 2
    assert db.sync_ledger(lines) == 0, "a second sync writes nothing new"
    rows = db.ledger_rows("PI_USDT")
    assert len(rows) == 2
    ex = [r for r in rows if r["action"] == "exit"][0]
    assert ex["pnl"] == 1.25 and ex["why"] == "TP"
    assert ex["exit_price"] == 0.085
    assert db.sync_ledger([]) == 0


def test_ledger_filters_by_action(db):
    db.sync_ledger([
        {"ts": 1, "action": "enter", "symbol": "X_USDT"},
        {"ts": 2, "action": "error", "symbol": "X_USDT", "why": "2015"},
    ])
    assert len(db.ledger_rows(action="error")) == 1
    assert len(db.ledger_rows()) == 2


def test_timeframes_use_one_vocabulary(db):
    """candles stored MEXC's names (Min60) and results the short label (1h),
    so the two tables could not be joined at all."""
    assert db.tf_label("Min60") == "1h"
    assert db.tf_label("1h") == "1h"
    assert db.tf_label("Hour4") == "4h"
    import pandas as pd
    frame = pd.DataFrame({
        "Date": pd.to_datetime([1_700_000_000], unit="s"),
        "Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0],
        "Volume": [1.0]})
    db.upsert_candles("Z_USDT", "Min60", frame)      # written as MEXC's name
    assert db.candles_df("Z_USDT", "1h") is not None, "must be findable as 1h"
    assert db.last_ts("Z_USDT", "Min60") == db.last_ts("Z_USDT", "1h")
    assert {c["timeframe"] for c in db.coverage()} == {"1h"}


def test_a_missing_dry_run_is_unknown_not_real_money(db):
    db.sync_ledger([{"ts": 1, "action": "enter", "symbol": "A_USDT"},
                    {"ts": 2, "action": "enter", "symbol": "A_USDT",
                     "dry_run": True},
                    {"ts": 3, "action": "enter", "symbol": "A_USDT",
                     "dry_run": False}])
    rows = {r["ts"]: r["dry_run"] for r in db.ledger_rows("A_USDT")}
    assert rows[1] is None, "absent must not read as real money"
    # SQLite hands booleans back as 1/0 where Postgres gives True/False, so
    # compare the value, not its identity
    assert bool(rows[2]) is True and bool(rows[3]) is False


def test_two_lines_that_differ_only_in_why_are_both_kept(db):
    """A real BDX pair shared a second, a symbol and an action but differed in
    `why` — MANUAL/EXCHANGE against LIQUIDATED. The old fingerprint dropped
    one of them, and it was an exit."""
    a = {"ts": 1786518636, "symbol": "BDX_USDT", "action": "exit",
         "strategy": "fade15_1m", "why": "MANUAL/EXCHANGE", "pnl": -1.0}
    b = dict(a, why="LIQUIDATED")
    assert db.sync_ledger([a, b]) == 2
    assert len(db.ledger_rows("BDX_USDT")) == 2


def test_two_changes_in_one_second_are_both_history(db):
    """The key was (changed_at, strategy, symbol, action), so a second edit
    inside the same second overwrote the first."""
    t = 1_787_000_000
    a = {"changed_at": t, "strategy_key": "k", "symbol": "APEX_USDT",
         "action": "changed", "tp": 3.0, "sl": 3.0}
    b = dict(a, tp=4.0)
    assert db.record_deployment(a) == 1
    assert db.record_deployment(b) == 1
    got = db.deployments("APEX_USDT")
    assert len(got) == 2, "both edits must survive"
    assert {g["tp"] for g in got} == {3.0, 4.0}
    # ...but saving the identical change twice is not two pieces of history
    db.record_deployment(a)
    assert len(db.deployments("APEX_USDT")) == 2


def test_pruning_keeps_the_best_rows_per_pair(db):
    rows = [{
        "row_code": f"C{i:04d}", "symbol": "BTC_USDT", "timeframe": "1h",
        "signal": "mom6", "tp": 4.0, "sl": 1.0, "sizing": "flat",
        "data_start": 0, "data_end": 100, "code_version": "v",
        "profit": float(i), "trades": 200} for i in range(50)]
    assert db.save_results(rows) == 50
    dropped = db.prune_results(keep_per_pair=10)
    assert dropped == 40
    left = db.load_results(symbol="BTC_USDT")
    assert len(left) == 10
    assert min(r["profit"] for r in left) == 40.0, "the best ten survive"


def test_table_sizes_reports_every_table(db):
    sizes = db.table_sizes()
    assert set(sizes) == {"candles", "backtest_results", "deployments",
                          "trade_ledger"}
    assert all("rows" in v for v in sizes.values())
