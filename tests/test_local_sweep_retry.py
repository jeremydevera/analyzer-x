"""A failed coin must be purged and redone — never marked done.

The operator's rule (2026-08-25): "if a coin fails, delete the backtest then
redo again the last failed job (not the whole)". Two properties: a failed
pair leaves NOTHING half-written behind, and the coin does not enter `done`,
so the next run picks it up instead of inheriting a gap.
"""
import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "local_sweep", Path(__file__).resolve().parent.parent / "scripts"
    / "local_sweep.py")
ls = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ls)


def _db(tmp_path):
    return ls.connect(tmp_path / "t.sqlite")


def test_purge_removes_rows_and_the_on_disk_state(tmp_path):
    db = _db(tmp_path)
    db.execute("INSERT INTO rows (id, coin, tf, profit) VALUES ('X','PI','1h',1)")
    db.execute("INSERT INTO trades (row_id, n, pnl) VALUES ('X', 1, 2.0)")
    db.commit()
    home = tmp_path / "home"
    for sub, name in (("rows", "PI-1h.json"), ("state", "PI-1h.json"),
                      ("locks", "PI-1h.lock")):
        (home / sub).mkdir(parents=True, exist_ok=True)
        (home / sub / name).write_text("{}")

    ls._purge_pair(db, str(home), "PI_USDT", "1h")

    assert db.execute("SELECT COUNT(*) FROM rows WHERE coin='PI'").fetchone()[0] == 0
    for sub, name in (("rows", "PI-1h.json"), ("state", "PI-1h.json"),
                      ("locks", "PI-1h.lock")):
        assert not (home / sub / name).exists(), f"{sub} file survived the purge"


def test_purge_leaves_other_pairs_untouched(tmp_path):
    """Only the failed pair is redone — not the coin's other timeframes,
    and not other coins."""
    db = _db(tmp_path)
    db.execute("INSERT INTO rows (id, coin, tf, profit) VALUES ('A','PI','1h',1)")
    db.execute("INSERT INTO rows (id, coin, tf, profit) VALUES ('B','PI','4h',2)")
    db.execute("INSERT INTO rows (id, coin, tf, profit) VALUES ('C','APEX','1h',3)")
    db.commit()
    ls._purge_pair(db, str(tmp_path / "nohome"), "PI_USDT", "1h")
    left = {r[0] for r in db.execute("SELECT id FROM rows")}
    assert left == {"B", "C"}


def test_read_pair_rows_survives_a_truncated_file(tmp_path):
    home = tmp_path / "home"
    (home / "rows").mkdir(parents=True)
    (home / "rows" / "PI-1h.json").write_text('{"rows": [{"coin": "PI"')
    assert ls._read_pair_rows(str(home), "PI_USDT", "1h") == []


def test_read_pair_rows_reads_both_shapes(tmp_path):
    home = tmp_path / "home"
    (home / "rows").mkdir(parents=True)
    (home / "rows" / "A-1h.json").write_text('{"rows": [{"coin": "A"}]}')
    (home / "rows" / "B-1h.json").write_text('[{"coin": "B"}]')
    assert ls._read_pair_rows(str(home), "A_USDT", "1h")[0]["coin"] == "A"
    assert ls._read_pair_rows(str(home), "B_USDT", "1h")[0]["coin"] == "B"


def test_worker_returns_a_count_never_the_rows(monkeypatch, tmp_path):
    """Handing multi-MB row lists back through the pool pipe deadlocked the
    sweep on 2026-08-25; the worker must return a count only."""
    import sys
    import types

    import tradingagents
    fake = types.ModuleType("tradingagents.market_sweep")
    fake.run_pair = lambda *a, **k: {"rows": [{"x": 1}] * 5000}
    monkeypatch.setitem(sys.modules, "tradingagents.market_sweep", fake)
    # `from tradingagents import market_sweep` reads the PACKAGE attribute,
    # so patching sys.modules alone leaves the real module in play.
    monkeypatch.setattr(tradingagents, "market_sweep", fake, raising=False)
    sym, tf, n, err = ls._pair_job(("PI_USDT", "1h", str(tmp_path), 5.0, 365, 3))
    assert (sym, tf, n, err) == ("PI_USDT", "1h", 5000, "")


def test_worker_reports_the_error_instead_of_raising(monkeypatch, tmp_path):
    import sys
    import types

    import tradingagents
    fake = types.ModuleType("tradingagents.market_sweep")

    def boom(*a, **k):
        raise RuntimeError("venue said no")

    fake.run_pair = boom
    monkeypatch.setitem(sys.modules, "tradingagents.market_sweep", fake)
    monkeypatch.setattr(tradingagents, "market_sweep", fake, raising=False)
    sym, tf, n, err = ls._pair_job(("PI_USDT", "1h", str(tmp_path), 5.0, 365, 3))
    assert n == 0 and "venue said no" in err


def test_run_batch_returns_rows_AND_failures(monkeypatch, tmp_path):
    """It returned a bare list once, and `rows, failures = _run_batch(...)`
    then died with 'too many values to unpack' — after the sweep had already
    been launched. Pin the shape."""
    import types
    calls = []

    class FakeEx:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def map(self, fn, jobs):
            for j in jobs:
                calls.append(j[0])
                yield (j[0], j[1], 0,
                       "boom" if j[0] == "BAD_USDT" else "")

    import concurrent.futures as cf
    monkeypatch.setattr(cf, "ProcessPoolExecutor", FakeEx)
    monkeypatch.setattr(ls, "_read_pair_rows",
                        lambda home, s, tf: [{"coin": s, "tf": tf}])
    args = types.SimpleNamespace(home=str(tmp_path), base=5.0, days=365,
                                 thresholds=1)
    rows, failures = ls._run_batch(["OK_USDT", "BAD_USDT"], ["1h"], args, 2)
    assert [r["coin"] for r in rows] == ["OK_USDT"]
    assert failures == [("BAD_USDT", "1h", "boom")]
