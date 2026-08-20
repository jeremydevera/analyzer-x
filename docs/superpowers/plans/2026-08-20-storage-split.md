# Storage Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Neon keeps only irreplaceable data (ledger, deployments, best-500 strategies, traded-coin candles); Parquet files on the operator's disk hold the recomputable bulk (all candles, full sweep grids).

**Architecture:** A new `parquet_store` module mirrors `market_db`'s API shape (save/load/sizes) with atomic zstd writes. `market_db.retention_tick()` enforces the Neon diet, but only AFTER the full grid is proven on disk. `db_jobs._run_backtest` orders it: grid file first, Neon rows second, prune third. A storage panel on Backtest 2 makes growth visible.

**Tech Stack:** pandas + pyarrow (installed), SQLAlchemy (installed), Streamlit.

---

### Task 1: parquet_store — candles round-trip, atomic writes

**Files:**
- Create: `tradingagents/parquet_store.py`
- Test: `tests/test_parquet_store.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Parquet is the home of the RECOMPUTABLE bulk. Losing a file costs a
re-download, never history — but a file must never be half-written."""
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
    pd.testing.assert_frame_equal(back, df)


def test_missing_candles_return_none():
    assert pq.load_candles("NOPE_USDT", "1h") is None


def test_writes_are_atomic_no_tmp_left_behind():
    pq.save_candles("APEX_USDT", "15m", _frame())
    leftovers = [f for f in os.listdir(pq.CANDLES) if not
                 f.endswith(".parquet")]
    assert leftovers == []
```

- [ ] **Step 2: Run to verify failure** — `pytest tests/test_parquet_store.py -q` → FAIL (`No module named parquet_store`)

- [ ] **Step 3: Minimal implementation**

```python
"""Parquet files for the recomputable bulk: candles and full sweep grids.

The split rule (docs/superpowers/specs/2026-08-20-storage-split-design.md):
a database for what cannot be recomputed, files for what can. Everything here
can be rebuilt from MEXC, so the only invariants are (1) writes are atomic —
a half-written file is worse than none — and (2) timeframes use the same
shared labels the database uses.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(os.path.expanduser("~/.tradingagents/parquet"))
CANDLES = ROOT / "candles"
GRIDS = ROOT / "grids"
_COMPRESSION = "zstd"          # measured 14x smaller than the same rows in Neon


def _atomic(df, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    df.to_parquet(tmp, compression=_COMPRESSION, index=False)
    tmp.replace(path)
    return path


def _candle_path(symbol: str, tf: str) -> Path:
    from tradingagents.dataflows.market_db import tf_label

    return CANDLES / f"{symbol}-{tf_label(tf)}.parquet"


def save_candles(symbol: str, tf: str, df) -> Path:
    return _atomic(df, _candle_path(symbol, tf))


def load_candles(symbol: str, tf: str):
    import pandas as pd

    p = _candle_path(symbol, tf)
    if not p.exists():
        return None
    return pd.read_parquet(p)
```

- [ ] **Step 4: Run** — `pytest tests/test_parquet_store.py -q` → 3 PASS
- [ ] **Step 5: Commit** — `git add … && git commit -m "feat(storage): parquet candle store with atomic zstd writes"`

### Task 2: parquet_store — grid snapshots

**Files:** Modify `tradingagents/parquet_store.py`, extend `tests/test_parquet_store.py`

- [ ] **Step 1: Failing tests**

```python
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
    import json
    assert json.loads(back.iloc[0]["monthly"]) == {"2026-08": 1.5}


def test_empty_grid_refuses():
    with pytest.raises(ValueError):
        pq.save_grid([], label="empty")


def test_sizes_reports_both_stores():
    pq.save_candles("A_USDT", "1h", _frame())
    pq.save_grid([{"coin": "A", "profit": 1.0}], label="t", day="2026-08-20")
    s = pq.sizes()
    assert s["candles"]["files"] == 1 and s["candles"]["rows"] == 5
    assert s["grids"]["files"] == 1 and s["grids"]["rows"] == 1
    assert s["candles"]["bytes"] > 0
```

- [ ] **Step 2: Run** → FAIL (`no attribute save_grid`)
- [ ] **Step 3: Implement**

```python
def save_grid(rows: list, *, label: str, day: str | None = None) -> Path:
    """One completed sweep, every row — the record the database prunes.

    Dict/list cells (monthly maps, month arrays) are JSON-encoded: Parquet
    wants columns, not ragged Python objects.
    """
    import time

    import pandas as pd

    if not rows:
        raise ValueError("an empty grid is not a snapshot; refuse to write")
    df = pd.DataFrame(rows)
    for col in df.columns:
        if df[col].map(lambda v: isinstance(v, (dict, list))).any():
            df[col] = df[col].map(json.dumps)
    day = day or time.strftime("%Y-%m-%d")
    return _atomic(df, GRIDS / f"{day}-{label}.parquet")


def load_grid(path):
    import pandas as pd

    return pd.read_parquet(path)


def sizes() -> dict:
    """Files, rows and bytes per store — growth must be visible."""
    import pyarrow.parquet as pa

    out = {}
    for name, d in (("candles", CANDLES), ("grids", GRIDS)):
        files = sorted(d.glob("*.parquet")) if d.exists() else []
        rows = 0
        for f in files:
            try:
                rows += pa.ParquetFile(f).metadata.num_rows
            except Exception:
                continue
        out[name] = {"files": len(files), "rows": rows,
                     "bytes": sum(f.stat().st_size for f in files)}
    return out
```

- [ ] **Step 4: Run** → 6 PASS · **Step 5: Commit** `feat(storage): grid snapshots + sizes`

### Task 3: market_db.retention_tick — the diet, guarded

**Files:** Modify `tradingagents/dataflows/market_db.py`, extend `tests/test_market_db.py`

- [ ] **Step 1: Failing tests**

```python
def _result(i, symbol="BTC_USDT"):
    return {"row_code": f"R{i:04d}", "symbol": symbol, "timeframe": "1h",
            "signal": "mom6", "tp": 4.0, "sl": 1.0, "sizing": "flat",
            "data_start": 0, "data_end": 100, "code_version": "v",
            "profit": float(i), "trades": 200}


def test_retention_prunes_results_and_unarmed_candles(db, tmp_path):
    db.save_results([_result(i) for i in range(30)])
    db.upsert_candles("BTC_USDT", "1h", _frame())
    db.upsert_candles("GONE_USDT", "1h", _frame())
    grid = tmp_path / "g.parquet"
    grid.write_bytes(b"x" * 100)          # a real, non-empty snapshot
    r = db.retention_tick(keep_per_pair=10, armed_symbols=["BTC_USDT"],
                          grid_path=grid)
    assert r["results_dropped"] == 20
    assert r["candle_symbols_dropped"] == ["GONE_USDT"]
    assert len(db.load_results(symbol="BTC_USDT")) == 10
    assert db.candles_df("BTC_USDT", "1h") is not None
    assert db.candles_df("GONE_USDT", "1h") is None


def test_retention_aborts_without_the_grid_on_disk(db, tmp_path):
    """Never delete from Neon what disk does not yet hold."""
    db.save_results([_result(i) for i in range(30)])
    r = db.retention_tick(keep_per_pair=10, armed_symbols=["BTC_USDT"],
                          grid_path=tmp_path / "missing.parquet")
    assert r["aborted"] == "grid snapshot missing or empty"
    assert len(db.load_results(symbol="BTC_USDT")) == 30


def test_retention_never_deletes_candles_when_armed_list_is_empty(db):
    db.upsert_candles("BTC_USDT", "1h", _frame())
    r = db.retention_tick(keep_per_pair=10, armed_symbols=[], grid_path=None)
    assert r["candle_symbols_dropped"] == []
    assert db.candles_df("BTC_USDT", "1h") is not None
```

- [ ] **Step 2: Run** → FAIL (`no attribute retention_tick`)
- [ ] **Step 3: Implement** (after `prune_results` in market_db.py)

```python
def retention_tick(*, keep_per_pair: int = 500,
                   armed_symbols: list | None = None,
                   grid_path=None) -> dict:
    """Enforce the storage split's Neon diet, loudly and guardedly.

    * results pruned to the best `keep_per_pair` per (symbol, timeframe,
      window, code_version) — but ONLY when the full grid is proven on disk
      (`grid_path` exists and is non-empty). Never delete from the database
      what the file store does not yet hold.
    * candles kept only for coins with a live strategy. An EMPTY armed list
      deletes nothing: a config hiccup must not empty the archive.
    """
    out = {"results_dropped": 0, "candle_symbols_dropped": [], "aborted": ""}
    if grid_path is not None:
        try:
            ok = os.path.getsize(grid_path) > 0
        except OSError:
            ok = False
        if not ok:
            out["aborted"] = "grid snapshot missing or empty"
            return out
    out["results_dropped"] = prune_results(keep_per_pair=keep_per_pair)
    if armed_symbols:
        from sqlalchemy import text
        try:
            with _engine().begin() as cx:
                gone = [r[0] for r in cx.execute(text(
                    "SELECT DISTINCT symbol FROM candles")).fetchall()
                    if r[0] not in set(armed_symbols)]
                for sym in gone:
                    cx.execute(text("DELETE FROM candles WHERE symbol=:s"),
                               {"s": sym})
                out["candle_symbols_dropped"] = sorted(gone)
        except Exception as exc:
            _stand_down(exc, "retention_tick")
    return out
```

(`import os` already present at module top; verify, add if not.)

- [ ] **Step 4: Run** `pytest tests/test_market_db.py -q` → all PASS · **Step 5: Commit** `feat(storage): retention_tick — prune only after the grid is on disk`

### Task 4: db_jobs writes the grid BEFORE the diet

**Files:** Modify `tradingagents/db_jobs.py` (in `_run_backtest`, around the `mdb.save_results(...)` call), test `tests/test_db_jobs_retention.py`

- [ ] **Step 1: Failing test**

```python
"""The order is the safety: grid file first, Neon rows second, prune third."""
import json

from tradingagents import db_jobs


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
    saved = db_jobs.persist_results(
        {"rows": [{"coin": "APEX", "tf": "1h", "signal": "mom6", "th": 0.0,
                   "tp": 4.0, "sl": 1.0, "sizing": "flat", "id": "X",
                   "profit": 1.0, "trades": 100, "wins": 40, "losses": 60,
                   "winrate": 40.0, "dd": 1.0, "monthly": {}}]},
        days=365, label="t", mdb=DB, pq=PQ)
    assert [c[0] for c in calls] == ["grid", "save", "prune"]
    assert calls[2][1] == str(fake_grid)
    assert saved == 1
```

- [ ] **Step 2: Run** → FAIL (`no attribute persist_results`)
- [ ] **Step 3: Implement** in `db_jobs.py` — extract the existing save into one ordered function and call it from `_run_backtest`:

```python
def _armed_symbols() -> list:
    """Coins with a live strategy — the only candles Neon keeps."""
    try:
        from tradingagents import auto_trader as at

        cfg = at.load_settings()
        books = cfg.get("strategy_books") or {}
        coins = cfg.get("strategy_coins") or {}
        return sorted({c for k, cs in coins.items()
                       for c in (cs or []) if books.get(k)})
    except Exception:
        return []


def persist_results(payload: dict, *, days: int, label: str,
                    mdb=None, pq=None) -> int:
    """Grid file FIRST, Neon rows second, prune third — in that order, so the
    database diet can never destroy rows that are not yet on disk."""
    if mdb is None:
        from tradingagents.dataflows import market_db as mdb
    if pq is None:
        from tradingagents import parquet_store as pq
    grid_path = pq.save_grid(payload["rows"], label=label)
    mdb.ensure_schema()
    saved = mdb.save_results(result_rows(payload, days, _signals_count()))
    mdb.retention_tick(keep_per_pair=500, armed_symbols=_armed_symbols(),
                       grid_path=grid_path)
    return saved


def _signals_count() -> int:
    from tradingagents import backtest_report as br

    return len(br.SIGNALS)
```

Then in `_run_backtest`, replace the `mdb.ensure_schema(); saved = mdb.save_results(result_rows(...))` block with:

```python
        saved = persist_results(payload, days=int(spec["days"]),
                                label=spec.get("label") or "archive")
```

(keep the existing try/except and progress write around it, unchanged).

- [ ] **Step 4: Run** `pytest tests/test_db_jobs_retention.py tests/test_market_db.py -q` → PASS
- [ ] **Step 5: Commit** `feat(storage): grid snapshot before save, prune after — ordered and tested`

### Task 5: storage panel on Backtest 2

**Files:** Modify `app.py` (inside `render_history_section`, at its end), test `tests/test_webapp.py` (append)

- [ ] **Step 1: Failing test**

```python
def test_backtest2_shows_the_storage_panel():
    src = open("app.py").read()
    assert "def render_storage_panel" in src
    assert "render_storage_panel()" in src
    for label in ("table_sizes", "parquet_store"):
        assert label in src.split("def render_storage_panel", 1)[1] \
            .split("def ", 1)[0]
```

- [ ] **Step 2: Run** → FAIL
- [ ] **Step 3: Implement** in `app.py` (new function + one call at the end of `render_backtest2_tab`):

```python
def render_storage_panel() -> None:
    """Every store, its rows and bytes — growth visible before it is a
    problem. Neon's free project caps at 0.5 GB; parquet is the operator's
    own disk."""
    import pandas as pd

    from tradingagents import parquet_store as pqs
    from tradingagents.dataflows import market_db as mdb

    st.markdown('<div class="ta-section">Storage</div>',
                unsafe_allow_html=True)
    rows = []
    for name, v in (mdb.table_sizes() or {}).items():
        rows.append({"store": f"Neon · {name}", "rows": v.get("rows"),
                     "size": v.get("size") or "—"})
    for name, v in pqs.sizes().items():
        rows.append({"store": f"Disk · {name}", "rows": v["rows"],
                     "size": f"{v['bytes'] / 1e6:.1f} MB "
                             f"({v['files']} files)"})
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True,
                     height=min(300, 60 + 35 * len(rows)))
    st.caption("Neon holds the irreplaceable (ledger, deployments, best "
               "strategies, traded-coin candles) and stays under its 0.5 GB "
               "free cap. Parquet on this Mac holds the recomputable bulk — "
               "full candle history and complete sweep grids.")
```

- [ ] **Step 4: Run** `pytest tests/test_webapp.py -q -k storage` → PASS
- [ ] **Step 5: Commit** `feat(storage): storage panel on Backtest 2`

### Task 6: prove it end to end, push

- [ ] **Step 1:** Full suite `.venv/bin/python -m pytest tests/ -q` → all pass
- [ ] **Step 2:** Real migration — export Neon's untraded candles to Parquet, then retention-tick with the real armed list; print before/after `table_sizes()` + `pq.sizes()`
- [ ] **Step 3:** Restart the app, screenshot the Storage panel via Playwright, verify labels match the measured numbers
- [ ] **Step 4:** Commit + push to `mine/main`
