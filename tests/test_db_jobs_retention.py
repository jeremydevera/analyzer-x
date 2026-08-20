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


def test_backtest_job_snapshots_grid_then_saves_then_prunes(monkeypatch,
                                                            tmp_path):
    calls = []
    fake_grid = tmp_path / "2026-08-20-t.parquet"

    class PQ:
        @staticmethod
        def save_grid(rows, *, label, day=None):
            calls.append(("grid", len(rows)))
            fake_grid.write_bytes(b"x" * 64)
            return fake_grid

    class DB:
        @staticmethod
        def ensure_schema():
            return True

        @staticmethod
        def save_results(rows):
            calls.append(("save", len(rows)))
            return len(rows)

        @staticmethod
        def retention_tick(**kw):
            calls.append(("prune", str(kw.get("grid_path"))))
            return {"results_dropped": 3, "candle_symbols_dropped": [],
                    "aborted": ""}

    monkeypatch.setattr(db_jobs, "_armed_symbols", lambda: ["APEX_USDT"])
    saved = db_jobs.persist_results(_payload(), days=365, label="t",
                                    mdb=DB, pq=PQ)
    assert [c[0] for c in calls] == ["grid", "save", "prune"]
    assert calls[2][1] == str(fake_grid)
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
