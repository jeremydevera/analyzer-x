"""The order IS the safety: grid file first, Neon rows second, prune third.

Any other order can destroy rows that exist nowhere else — the prune deletes
from the database on the promise that the full grid is already on disk.
"""
from tradingagents import db_jobs


def _payload():
    return {"rows": [{"coin": "APEX", "tf": "1h", "signal": "mom6", "th": 0.0,
                      "tp": 4.0, "sl": 1.0, "sizing": "flat", "id": "X",
                      "profit": 1.0, "trades": 100, "wins": 40, "losses": 60,
                      "winrate": 40.0, "dd": 1.0, "monthly": {}}]}


def test_backtest_job_snapshots_the_grid_and_touches_no_database(monkeypatch,
                                                                 tmp_path):
    """Pure local: persist = one grid snapshot on this Mac. The pair store
    already holds every row; no database is written or dieted."""
    calls = []
    fake_grid = tmp_path / "2026-08-20-t.parquet"

    class PQ:
        @staticmethod
        def save_grid(rows, *, label, day=None):
            calls.append(("grid", len(rows)))
            fake_grid.write_bytes(b"x" * 64)
            return fake_grid

    class DB:                                # must never be consulted
        @staticmethod
        def ensure_schema():
            calls.append(("save", 0))
            return True

        @staticmethod
        def save_results(rows):
            calls.append(("save", len(rows)))
            return len(rows)

        @staticmethod
        def retention_tick(**kw):
            calls.append(("prune", ""))
            return {}

    saved = db_jobs.persist_results(_payload(), days=365, label="t",
                                    mdb=DB, pq=PQ)
    assert [c[0] for c in calls] == ["grid"]
    assert saved == 1


def test_a_failed_grid_write_stops_the_save_entirely(monkeypatch, tmp_path):
    """No snapshot, no save, no prune — the exception must propagate so the
    job reports a real error instead of quietly dieting the database."""
    calls = []

    class PQ:
        @staticmethod
        def save_grid(rows, *, label, day=None):
            raise OSError("disk full")

    class DB:
        @staticmethod
        def ensure_schema():
            calls.append("schema")
            return True

        @staticmethod
        def save_results(rows):
            calls.append("save")
            return len(rows)

        @staticmethod
        def retention_tick(**kw):
            calls.append("prune")
            return {}

    monkeypatch.setattr(db_jobs, "_armed_symbols", lambda: [])
    import pytest

    with pytest.raises(OSError):
        db_jobs.persist_results(_payload(), days=365, label="t",
                                mdb=DB, pq=PQ)
    assert "save" not in calls and "prune" not in calls


def test_armed_symbols_reads_only_strategies_with_books(monkeypatch):
    # patch the real module's loader: `from tradingagents import auto_trader`
    # resolves the already-imported attribute, not sys.modules
    from tradingagents import auto_trader as at

    monkeypatch.setattr(at, "load_settings", lambda: {
        "strategy_books": {"a": ["real"], "b": []},
        "strategy_coins": {"a": ["APEX_USDT"], "b": ["GONE_USDT"]}})
    assert db_jobs._armed_symbols() == ["APEX_USDT"]


def test_download_fills_the_local_store_first(monkeypatch, tmp_path):
    """"i said i want all local machine" — DOWNLOAD writes this Mac's store;
    Neon is a best-effort mirror for armed coins whose absence never fails
    the job."""
    import pandas as pd

    from tradingagents import market_sweep as msw, parquet_store as pqs
    from tradingagents.dataflows import market_db as mdb

    calls = {"local": [], "parquet": [], "neon": []}
    frame = pd.DataFrame({"Date": pd.to_datetime([1_787_000_000], unit="s"),
                          "Open": [1.0], "High": [1.0], "Low": [1.0],
                          "Close": [1.0], "Volume": [1.0]})
    monkeypatch.setattr(msw, "refresh_candles",
                        lambda c, tf, days=365: (calls["local"].append((c, tf))
                                                 or (frame, 1, "fetch")))
    monkeypatch.setattr(pqs, "save_candles",
                        lambda c, tf, df: calls["parquet"].append((c, tf)))
    monkeypatch.setattr(mdb, "available", lambda: True)
    monkeypatch.setattr(mdb, "ensure_schema", lambda: True)
    monkeypatch.setattr(mdb, "upsert_candles",
                        lambda c, tf, df: calls["neon"].append((c, tf)))
    monkeypatch.setattr(db_jobs, "_stopping", lambda kind: False)
    monkeypatch.setattr(db_jobs, "FILES", {
        "download": {"progress": tmp_path / "p.json"}})
    db_jobs._run_download({"coins": ["APEX_USDT", "GONE_USDT"],
                           "tfs": ["15m"]})
    assert calls["local"] == [("APEX_USDT", "15m"), ("GONE_USDT", "15m")]
    assert calls["parquet"] == calls["local"], "parquet copy for every pair"
    assert calls["neon"] == [], \
        "pure local: the database is never written, armed or not"


def test_update_mode_tops_up_what_is_already_stored(monkeypatch, tmp_path):
    """"update candles" means fill the gap since the stored last bar — the
    pairs come from the STORE, so no coin has to be picked, and nothing is
    re-downloaded from scratch."""
    import pandas as pd

    from tradingagents import market_sweep as msw, parquet_store as pqs

    seen = []
    frame = pd.DataFrame({"Date": pd.to_datetime([1_787_000_000], unit="s"),
                          "Open": [1.0], "High": [1.0], "Low": [1.0],
                          "Close": [1.0], "Volume": [1.0]})
    monkeypatch.setattr(msw, "candle_coverage", lambda: [
        {"symbol": "APEX_USDT", "timeframe": "1h"},
        {"symbol": "XAUT_USDT", "timeframe": "15m"}])
    monkeypatch.setattr(msw, "refresh_candles",
                        lambda c, tf, days=365: (seen.append((c, tf))
                                                 or (frame, 7, "delta")))
    monkeypatch.setattr(pqs, "save_candles", lambda c, tf, df: None)
    monkeypatch.setattr(db_jobs, "_stopping", lambda kind: False)
    monkeypatch.setattr(db_jobs, "FILES", {
        "download": {"progress": tmp_path / "p.json"}})
    db_jobs._run_download({"mode": "update"})
    assert seen == [("APEX_USDT", "1h"), ("XAUT_USDT", "15m")]
    import json
    got = json.loads((tmp_path / "p.json").read_text())
    assert got["mode"] == "update" and "gap-filled" in got["note"]
    assert got["bars_stored"] == 14


def test_an_explicit_selection_still_wins_over_the_store(monkeypatch, tmp_path):
    import pandas as pd

    from tradingagents import market_sweep as msw, parquet_store as pqs
    seen = []
    frame = pd.DataFrame({"Date": pd.to_datetime([1_787_000_000], unit="s"),
                          "Open": [1.0], "High": [1.0], "Low": [1.0],
                          "Close": [1.0], "Volume": [1.0]})
    monkeypatch.setattr(msw, "candle_coverage", lambda: [
        {"symbol": "NOPE_USDT", "timeframe": "1h"}])
    monkeypatch.setattr(msw, "refresh_candles",
                        lambda c, tf, days=365: (seen.append((c, tf))
                                                 or (frame, 1, "fetch")))
    monkeypatch.setattr(pqs, "save_candles", lambda c, tf, df: None)
    monkeypatch.setattr(db_jobs, "_stopping", lambda kind: False)
    monkeypatch.setattr(db_jobs, "FILES", {
        "download": {"progress": tmp_path / "p.json"}})
    db_jobs._run_download({"mode": "update", "coins": ["PI_USDT"],
                           "tfs": ["4h"]})
    assert seen == [("PI_USDT", "4h")]
