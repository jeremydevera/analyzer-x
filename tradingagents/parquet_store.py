"""Parquet files for the recomputable bulk: candles and full sweep grids.

The split rule (docs/superpowers/specs/2026-08-20-storage-split-design.md):
**a database for what cannot be recomputed, files for what can.** Everything
here can be rebuilt from MEXC, so the invariants are narrow:

* writes are ATOMIC — write to ``<name>.tmp`` then rename, because a
  half-written file poisons every later read, while a missing one just costs
  a re-download;
* timeframes use the same shared labels the database uses (``1h``, not
  ``Min60``), so both stores name the same thing the same way;
* dict/list cells are JSON-encoded on the way in — Parquet wants columns,
  not ragged Python objects.

Measured on the operator's real data before this module existed: the same
rows are ~14x smaller here than in Neon (2.6 MB vs 37.7 MB for 123,859
candles), which is what makes "the full market on your own disk" ~2 GB
instead of ~20.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(os.path.expanduser("~/.tradingagents/parquet"))
CANDLES = ROOT / "candles"
GRIDS = ROOT / "grids"
_COMPRESSION = "zstd"


def _atomic(df, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    df.to_parquet(tmp, compression=_COMPRESSION, index=False)
    tmp.replace(path)
    return path


# ---------------------------------------------------------------- candles
def _candle_path(symbol: str, tf: str) -> Path:
    from tradingagents.dataflows.market_db import tf_label

    return CANDLES / f"{symbol}-{tf_label(tf)}.parquet"


def save_candles(symbol: str, tf: str, df) -> Path:
    """One file per contract and timeframe, same shape ``fx.klines`` returns."""
    return _atomic(df, _candle_path(symbol, tf))


def load_candles(symbol: str, tf: str):
    import pandas as pd

    p = _candle_path(symbol, tf)
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    # Parquet stores timestamps at millisecond resolution, so a frame written
    # as datetime64[s] comes back as datetime64[ms]. Same instants, different
    # dtype — and a backtest comparing bar times would see them as unequal.
    # Normalise to nanoseconds, pandas' default, on the way out.
    if "Date" in df.columns:
        df["Date"] = df["Date"].astype("datetime64[ns]")
    return df


# ------------------------------------------------------------------ grids
def save_grid(rows: list, *, label: str, day: str | None = None) -> Path:
    """One completed sweep, EVERY row — the record the database prunes.

    The prune guard (`market_db.retention_tick`) checks this file exists and
    is non-empty before deleting anything from Neon, which is why an empty
    grid refuses to write: an empty snapshot must never license a prune.
    """
    import time

    import pandas as pd

    if not rows:
        raise ValueError("an empty grid is not a snapshot; refusing to write")
    df = pd.DataFrame(rows)
    for col in df.columns:
        if df[col].map(lambda v: isinstance(v, (dict, list))).any():
            df[col] = df[col].map(json.dumps)
    day = day or time.strftime("%Y-%m-%d")
    return _atomic(df, GRIDS / f"{day}-{label}.parquet")


def load_grid(path):
    import pandas as pd

    return pd.read_parquet(path)


# ------------------------------------------------------------------ sizes
def sizes(rows: bool = True) -> dict:
    """Files, rows and bytes per store — growth must be visible.

    `rows=False` skips the row counts, and that is the difference between a
    stat and a storm: counting rows OPENS every parquet file, 4,909 of them
    measured on 2026-08-22. That is 2s on an idle disk and over 20s while the
    sweep has seven cores on it — and /api/health was polled every 10 seconds
    by the header chip, so the chip read "API unreachable" while the API was
    perfectly healthy and merely busy counting. Liveness probes get
    `rows=False`; the storage screen, which the operator opens deliberately,
    gets the full count.
    """
    out = {}
    for name, d in (("candles", CANDLES), ("grids", GRIDS)):
        files = sorted(d.glob("*.parquet")) if d.exists() else []
        n = 0
        if rows:
            import pyarrow.parquet as pa

            for f in files:
                try:
                    n += pa.ParquetFile(f).metadata.num_rows
                except Exception:
                    continue
        out[name] = {"files": len(files), "rows": (n if rows else None),
                     "bytes": sum(f.stat().st_size for f in files)}
    return out
