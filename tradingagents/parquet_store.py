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


class GridSink:
    """Write a sweep's rows to ONE parquet file AS THEY ARE READ, pair by pair.

    `save_grid()` takes a list, which means the whole market in RAM. On
    2026-08-26 5:20am the 2-month sweep died with MemoryError after measuring
    2,367 pairs: the fold was doing `rows += pair_rows(...)` over 15.40 GB of
    row JSON on a 17.1 GB machine. Nothing was wrong with the measuring -- only
    with holding all of it at once. This sink keeps one pair in memory.

    Two rules it exists to keep:

    * EVERY row is written. A field the declared schema does not have rides in
      an `extra` JSON column and is named in `extra_keys` -- never dropped
      (kit item F).
    * Numbers are float64. A column typed int64 from the first pair breaks the
      moment a later pair carries a float in it, and the failure would land
      mid-sweep after hours of work; a snapshot reading `trades = 120.0` is a
      trade worth making.
    """

    def __init__(self, *, label: str, day: str | None = None,
                 batch_rows: int = 20_000):
        import time

        self.label = label
        self.day = day or time.strftime("%Y-%m-%d")
        self.batch_rows = max(1, int(batch_rows))
        self.path = GRIDS / f"{self.day}-{label}.parquet"
        self.rows_written = 0
        self.extra_keys: list = []
        self._buf: list = []
        self._schema = None
        self._writer = None
        self._tmp = None
        self._cols: list = []
        self._kind: dict = {}

    # ---------------------------------------------------------------- schema
    def _declare(self, rows: list) -> None:
        import pyarrow as pa

        cols, kind = [], {}
        for r in rows:
            for k, v in r.items():
                if k in kind:
                    if kind[k] == "null" and v is not None:
                        kind[k] = self._kind_of(v)
                    continue
                cols.append(k)
                kind[k] = self._kind_of(v)
        cols.append("extra")
        kind["extra"] = "str"
        field = {"bool": pa.bool_(), "num": pa.float64(), "str": pa.string(),
                 "null": pa.string()}
        self._cols, self._kind = cols, kind
        self._schema = pa.schema([pa.field(c, field[kind[c]]) for c in cols])

    @staticmethod
    def _kind_of(v) -> str:
        if isinstance(v, bool):
            return "bool"
        if isinstance(v, (int, float)):
            return "num"
        if v is None:
            return "null"
        return "str"          # str, dict, list -> text (dicts/lists as JSON)

    def _flat(self, r: dict) -> dict:
        out, extra = {}, {}
        for k, v in r.items():
            if k not in self._kind:
                extra[k] = v
                continue
            want = self._kind[k]
            if v is None:
                out[k] = None
            elif want == "num":
                out[k] = None if isinstance(v, (dict, list, str)) else float(v)
            elif want == "bool":
                out[k] = bool(v)
            else:
                out[k] = (json.dumps(v, default=str)
                          if isinstance(v, (dict, list)) else str(v))
        for k in self._cols:
            out.setdefault(k, None)
        if extra:
            for k in extra:
                if k not in self.extra_keys:
                    self.extra_keys.append(k)
            out["extra"] = json.dumps(extra, default=str)
        return out

    # ------------------------------------------------------------------ write
    def add(self, rows: list) -> int:
        """Take one pair's rows. They are flattened NOW, so the caller may
        mutate its own dicts afterwards (the fold does) without touching what
        this snapshot will hold."""
        if not rows:
            return 0
        if self._schema is None:
            self._declare(rows)
        self._buf.extend(self._flat(r) for r in rows)
        self.rows_written += len(rows)
        if len(self._buf) >= self.batch_rows:
            self._flush()
        return len(rows)

    def _flush(self) -> None:
        if not self._buf:
            return
        import pyarrow as pa
        import pyarrow.parquet as pq

        if self._writer is None:
            GRIDS.mkdir(parents=True, exist_ok=True)
            self._tmp = self.path.with_name(self.path.name + ".tmp")
            self._writer = pq.ParquetWriter(self._tmp, self._schema,
                                            compression=_COMPRESSION)
        self._writer.write_table(pa.Table.from_pylist(self._buf,
                                                      schema=self._schema))
        self._buf = []

    def close(self):
        """Finish the file and return its path, or None when nothing was
        written -- an empty snapshot must never license a prune."""
        self._flush()
        if self._writer is None:
            return None
        self._writer.close()
        self._writer = None
        self._tmp.replace(self.path)
        return self.path


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
