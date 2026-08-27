"""No test may write into the operator's own ~/.tradingagents.

Bought on Aug 27, 2026. The 60-day market sweep finished at 7:56am having
measured 22,478,876 combinations and written its snapshot to

    ~/.tradingagents/parquet/grids/2026-08-27-grid.parquet

At 8:07am that file was 8,943 bytes holding 40 rows: coin APEX, timeframe 1h,
signals s0..s39, profit 0.0 to 39.0 — the fixture of
`test_the_parent_does_not_hold_every_pairs_rows`. The previous day's snapshot,
for comparison, is 338,936,957 bytes and 9,439,792 rows.

The row store survived only because conftest's sandbox already redirects
`market_sweep.ROWDIR`. `parquet_store.GRIDS` was not in that list, and its own
comment had warned about exactly this: "Individual tests patched ROWDIR and
STATES themselves, so the ones that forgot wrote into the operator's real
15 GB store".

So this test does not check one module. It walks every module the suite
imports and fails if any path constant still points inside the real home —
the next module with a `Path(os.path.expanduser("~/..."))` at the top cannot
reopen the hole quietly.
"""
import os
from pathlib import Path

import pytest

REAL_HOME = Path(os.path.expanduser("~/.tradingagents")).resolve()

# Modules whose module-level paths must be redirected while tests run. Each is
# a real place this project writes.
GUARDED = [
    ("tradingagents.market_sweep", ("HOME", "ROWDIR", "STATES", "CANDLES",
                                    "WORKERS", "INDEX_PATH", "HANDOFF_PATH",
                                    "MANIFEST", "PIDFILE", "PROGRESS", "ROWS")),
    ("tradingagents.parquet_store", ("ROOT", "CANDLES", "GRIDS")),
    ("tradingagents.rows_index", ("DB_PATH", "PIDFILE")),
    ("tradingagents.auto_trader", ("STATE_DIR", "LOCK_PATH",
                                   "WANT_PATH")),
]


def _inside(p) -> bool:
    try:
        Path(p).resolve().relative_to(REAL_HOME)
        return True
    except (ValueError, OSError, TypeError):
        return False


@pytest.mark.parametrize("mod,names", GUARDED, ids=lambda x: str(x)[:40])
def test_no_module_path_points_at_the_real_home(mod, names):
    import importlib

    m = importlib.import_module(mod)
    bad = [f"{mod}.{n} = {getattr(m, n)}"
           for n in names
           if hasattr(m, n) and _inside(getattr(m, n))]
    assert not bad, (
        "these would write into the operator's own store during a test:\n  "
        + "\n  ".join(bad))


def test_the_sandbox_covers_every_path_constant_it_can_find():
    """Not just the names listed above: any module-level Path under the real
    home is a hole, whatever it is called."""
    import importlib

    holes = []
    for mod, _names in GUARDED:
        m = importlib.import_module(mod)
        for name in dir(m):
            if name.startswith("__"):
                continue
            val = getattr(m, name, None)
            if isinstance(val, Path) and _inside(val):
                holes.append(f"{mod}.{name} = {val}")
    assert not holes, "unsandboxed paths inside the real home:\n  " + \
        "\n  ".join(holes)


def test_a_grid_written_now_lands_in_the_sandbox(tmp_path):
    """The specific failure: fold a grid and prove the file is not in the
    operator's grids directory."""
    from tradingagents import parquet_store as pqs

    sink = pqs.GridSink(label="guard-test")
    sink.add([{"coin": "AAA", "tf": "1h", "signal": "mom6", "profit": 1.0,
               "trades": 10, "winrate": 50.0}])
    path = sink.close()
    assert path is not None
    assert not _inside(path), path
    assert Path(path).exists()
