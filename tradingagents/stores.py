"""Which store: v1 (the 113-million-row, year-deep grid) or v2 (Backtest v2,
minute-exact exits on a 1-minute candle store). Sep 17, 2026.

ONE place that knows both folders. The sweep, the index and the parquet
store already switch roots on environment settings; a v2 JOB is the same
code launched with `V2.env_for()`, and the API reads a v2 store by passing
these paths explicitly (it serves both versions from one process, so it can
never flip a module global).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_HOME = Path(os.path.expanduser("~/.tradingagents"))

FIVE = ("15m", "30m", "1h", "4h", "1d")


@dataclass(frozen=True)
class Store:
    name: str
    home: Path            # market_sweep.HOME: state/, rows/, rows.db, manifest
    candles: Path         # market_sweep.CANDLES: the sweep's candle cache
    rows_db: Path         # rows_index.DB_PATH
    parquet: Path         # parquet_store.ROOT
    fine_tf: str          # market_sweep.FINE_TF: "" for v1, "1m" for v2
    download_kind: str    # db_jobs.FILES key
    backtest_kind: str

    def env_for(self) -> dict[str, str]:
        """The environment a job process needs to work in THIS store."""
        return {
            "TRADINGAGENTS_SWEEP_HOME": str(self.home),
            "TRADINGAGENTS_CANDLES": str(self.candles),
            "TA_ROWS_DB": str(self.rows_db),
            "TRADINGAGENTS_PARQUET": str(self.parquet),
            "TRADINGAGENTS_FINE_TF": self.fine_tf,
        }

    def exists(self) -> bool:
        return self.candles.exists() or self.rows_db.exists()

    @property
    def tfs(self) -> tuple[str, ...]:
        """What the DOWNLOAD fetches here: 1m alone for v2, the five for v1 and
        v3 (v3 reads its minutes on GitHub, never a 1m download here)."""
        return ("1m",) if self.fine_tf == "1m" else FIVE


V1 = Store(name="v1", home=_HOME / "backtest",
           candles=_HOME / "backtest" / "candles",
           rows_db=_HOME / "backtest" / "rows.db", parquet=_HOME / "parquet",
           fine_tf="", download_kind="download", backtest_kind="backtest")
V2 = Store(name="v2", home=_HOME / "v2", candles=_HOME / "v2" / "candles",
           rows_db=_HOME / "v2" / "rows.db", parquet=_HOME / "parquet-v2",
           fine_tf="1m", download_kind="download_v2",
           backtest_kind="backtest_v2")

# BACKTEST V3 (Oct 22, 2026; spec docs/superpowers/specs/2026-10-22-backtest-
# v3-design.md): research-backed ideas with waiting-order entries, their own
# exits and $1 risk a trade, in folders of their own so v1 and v2 are never
# written. `fine_tf` "v3" is the RESOLUTION a v3 row is stamped with (its id
# hashes res="v3"), never a timeframe. NO job runs with V3.env_for() until
# Part 2 has checked every reader of market_sweep.FINE_TF (30 references in
# 9 files on Oct 22, 2026): several read "set" as "this is v2".
V3 = Store(name="v3", home=_HOME / "v3", candles=_HOME / "v3" / "candles",
           rows_db=_HOME / "v3" / "rows.db", parquet=_HOME / "parquet-v3",
           fine_tf="v3", download_kind="", backtest_kind="backtest_v3")

_BY_NAME = {"v1": V1, "v2": V2, "v3": V3}


def by_name(name: str) -> Store:
    return _BY_NAME[str(name).lower()]


def for_kind(kind: str) -> Store:
    """The store a job KIND works in (`..._v2` → V2, `..._v3` → V3, else V1)."""
    k = str(kind)
    return V3 if k.endswith("_v3") else V2 if k.endswith("_v2") else V1
