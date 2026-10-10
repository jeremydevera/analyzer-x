"""What Gate's order book cost at every minute of the past (phase 4, Oct 10, 2026).

The operator, for a month: *"my goal is to align it with practice so I know
exactly how much will i earn"*. The practice runner reads the live book at
every signal and refuses a trade whose cost eats the target; the backtest had
no book, so it took those trades — measured Oct 09, 2026 as most of the gap
(backtest 59,511 trades against practice's 2,939 over the same hours). Gate
publishes its past books (`download.gatedata.org/futures_usdt/orderbooks/`),
so the backtest can now read the book of the minute each trade happened in.

One file per contract per HOUR, published about two hours after it ends:
a `set` snapshot, then every change merged per 100 ms. Columns
`timestamp, action, price, size, begin_id, merged`. A positive size is the
buy side, a negative one the sell side; `make` ADDS the size to the level and
`take` SUBTRACTS it. Measured: BTC Oct 09, 2026 00:00-01:00 replayed this way
equals the 01:00 snapshot on 41,387 of 41,387 levels (reading the size as the
level's new amount matched 221 of 4,909).

A reading is the book as it stood AT the minute's first instant (every event
stamped at or before it applied) — the moment a candle closes and a signal is
read. Each carries the cost of filling `notional_usd` on each side, walked
level by level exactly as `exchange_common.book_cost_from` walks a live book.
"""
from __future__ import annotations

import gzip
import heapq
import io

_EPS = 1e-12
_KIND = {"set": 0, "make": 1, "take": 2}
SOURCES = {"full": 1, "snapshot": 2}


def _events(raw_gz: bytes):
    """(ts, kind, price, size) lists from one hour's file."""
    import pandas as pd

    df = pd.read_csv(io.BytesIO(gzip.decompress(raw_gz)), header=None,
                     usecols=[0, 1, 2, 3], names=["t", "a", "p", "s"],
                     dtype={"t": "float64", "a": "str", "p": "float64",
                            "s": "float64"})
    kinds = df["a"].map(_KIND).fillna(-1).astype("int8")
    return (df["t"].tolist(), kinds.tolist(), df["p"].tolist(), df["s"].tolist())


def _apply(bids: dict, asks: dict, kind: int, p: float, s: float) -> None:
    side, size = (bids, s) if s > 0 else (asks, -s)
    if kind == 0:                       # set
        if size > _EPS:
            side[p] = size
        else:
            side.pop(p, None)
        return
    v = side.get(p, 0.0) + (size if kind == 1 else -size)
    if v > _EPS:
        side[p] = v
    else:
        side.pop(p, None)               # a level taken past zero is gone


def _walk(levels, want: float):
    """Average price for `want` contracts down `levels` [(px, qty)], best
    first; (avg, filled_all)."""
    need, cost, got = want, 0.0, 0.0
    for px, qty in levels:
        take = min(need, qty)
        cost += take * px
        got += take
        need -= take
        if need <= _EPS:
            break
    return (cost / got if got > 0 else None), need <= _EPS


def _best(side: dict, n: int, lowest: bool):
    keys = heapq.nsmallest(n, side) if lowest else heapq.nlargest(n, side)
    return [(k, side[k]) for k in keys]


def _sample(bids: dict, asks: dict, t: int, *, contract_size: float,
            notional_usd: float, source: str):
    if not bids or not asks:
        return None
    bid, ask = max(bids), min(asks)
    if bid >= ask:
        return None                     # crossed: no reading, never a negative spread
    mid = (bid + ask) / 2.0
    want = notional_usd / (contract_size * mid) if contract_size > 0 else 0.0
    out = {"t": int(t), "bid": bid, "ask": ask, "mid": mid,
           "spread": (ask - bid) / mid, "source": source}
    exhausted = False
    for side, lowest, key in ((asks, True, "buy"), (bids, False, "sell")):
        n = 8
        while True:
            levels = _best(side, n, lowest)
            avg, full = _walk(levels, want)
            if full or n >= len(side):
                break
            n *= 8
        if avg is None:
            return None
        if not full:
            exhausted = True
            far = levels[-1][0]
            avg = max(avg, far) if lowest else min(avg, far)
        out[key] = (avg / mid - 1.0) if lowest else (mid / avg - 1.0)
    out["exhausted"] = exhausted
    return out


def replay_hour(raw_gz: bytes, *, hour_start: int, contract_size: float,
                notional_usd: float) -> list:
    """Sixty readings — one per minute of the hour starting `hour_start`
    (unix s) — each a dict or None (crossed, empty, or unreadable book)."""
    ts, kinds, ps, ss = _events(raw_gz)
    bids: dict = {}
    asks: dict = {}
    full = any(k in (1, 2) for k in kinds)
    source = "full" if full else "snapshot"
    out = []
    i, n = 0, len(ts)
    for k in range(60):
        edge = hour_start + 60 * k
        while i < n and ts[i] <= edge:
            if kinds[i] >= 0:
                _apply(bids, asks, kinds[i], ps[i], ss[i])
            i += 1
        out.append(_sample(bids, asks, edge, contract_size=contract_size,
                           notional_usd=notional_usd, source=source))
    return out


def pack(readings) -> dict:
    """Readings → compact arrays (None readings dropped): t (int64, s), bid,
    ask (float64), spread, buy, sell (float32 fractions), exhausted (bool),
    source (int8: 1 full replay, 2 snapshot-only hour)."""
    import numpy as np

    rows = [r for r in readings if r]
    return {
        "t": np.asarray([r["t"] for r in rows], dtype="int64"),
        "bid": np.asarray([r["bid"] for r in rows], dtype="float64"),
        "ask": np.asarray([r["ask"] for r in rows], dtype="float64"),
        "spread": np.asarray([r["spread"] for r in rows], dtype="float32"),
        "buy": np.asarray([r["buy"] for r in rows], dtype="float32"),
        "sell": np.asarray([r["sell"] for r in rows], dtype="float32"),
        "exhausted": np.asarray([r["exhausted"] for r in rows], dtype="bool"),
        "source": np.asarray([SOURCES[r["source"]] for r in rows], dtype="int8"),
    }


MAX_AGE_S = 3600


def reading_at(packed: dict, ts: float, max_age_s: int = MAX_AGE_S):
    """The newest reading at or before `ts`, at most `max_age_s` old, as a
    dict with its age — or None."""
    import numpy as np

    t = packed["t"]
    if not len(t):
        return None
    j = int(np.searchsorted(t, int(ts), side="right")) - 1
    if j < 0:
        return None
    age = int(ts) - int(t[j])
    if age > max_age_s:
        return None
    return {"t": int(t[j]), "age_s": age, "bid": float(packed["bid"][j]),
            "ask": float(packed["ask"][j]), "spread": float(packed["spread"][j]),
            "buy": float(packed["buy"][j]), "sell": float(packed["sell"][j]),
            "exhausted": bool(packed["exhausted"][j]),
            "source": int(packed["source"][j])}


# -------------------------------------------------------------- the archive
ARCHIVE = "https://download.gatedata.org/futures_usdt/orderbooks"


def hour_url(symbol: str, hour_start: int) -> str:
    import time

    g = time.gmtime(hour_start)
    return (f"{ARCHIVE}/{g.tm_year:04d}{g.tm_mon:02d}/{symbol}-"
            f"{g.tm_year:04d}{g.tm_mon:02d}{g.tm_mday:02d}{g.tm_hour:02d}.csv.gz")


def day_readings(symbol: str, day_start: int, *, contract_size: float,
                 notional_usd: float, fetch=None) -> dict:
    """Every minute of one UTC day for one contract, packed. An hour whose
    file is missing (404) contributes nothing — its minutes stay unmeasured,
    and the caller counts them."""
    if fetch is None:
        from tradingagents.dataflows import gate_futures as gf

        fetch = gf._fetch_archive
    out = []
    hours_read = 0
    for h in range(24):
        hs = day_start + 3600 * h
        status, raw = fetch(hour_url(symbol, hs))
        if status != 200 or not raw:
            continue
        hours_read += 1
        out.extend(replay_hour(raw, hour_start=hs, contract_size=contract_size,
                               notional_usd=notional_usd))
    packed = pack(out)
    packed["hours_read"] = hours_read
    return packed
