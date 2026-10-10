"""Where the per-minute trading costs live (phase 4, Oct 10, 2026).

`book_history` turns Gate's hourly order-book files into one cost reading per
minute. Those readings are made by the daily costs job on GitHub's 40
machines (`.github/workflows/costs.yml`) and read by the Backtest v2 shards on
the same machines — and by this PC — for the coins and the window each one
measures. So they live where every machine of either account can read them
without a key: GitHub RELEASE ASSETS on the account whose machine made them,
one file per coin per month (`BTC_USDT-202610.npz`), in two releases a month
(`costs-202610-a` for coins starting 0-9 or A-M, `-b` for N-Z) because one
release holds at most 1,000 assets and Gate lists 1,027 contracts.

A completed month never changes, so it is downloaded once and kept
(`~/.tradingagents/cost_cache`); the current month grows every day and is
read again after CURRENT_TTL_S. Nothing here raises for a month nobody has
measured: that is `None`, and the engine counts every trade in it as
`cost_unmeasured`.
"""
from __future__ import annotations

import io
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

REPOS = tuple(r for r in os.environ.get(
    "COST_REPOS", "jeremydevera/analyzer-x,jeremydvera/analyzer-x").split(",") if r)
CACHE = Path(os.path.expanduser("~/.tradingagents")) / "cost_cache"
CURRENT_TTL_S = 6 * 3600
LEAD_S = 3600            # a reading this old still answers a minute (book_history.MAX_AGE_S)
KEYS = ("t", "bid", "ask", "spread", "buy", "sell", "exhausted", "source")
_now = time.time


def group(sym: str) -> str:
    c = str(sym or "?")[:1].upper()
    return "a" if (c.isdigit() or c <= "M") else "b"


def tag(sym: str, ym: str) -> str:
    return f"costs-{ym}-{group(sym)}"


def asset(sym: str, ym: str) -> str:
    return f"{sym}-{ym}.npz"


def url(repo: str, sym: str, ym: str) -> str:
    return (f"https://github.com/{repo}/releases/download/"
            f"{tag(sym, ym)}/{asset(sym, ym)}")


def empty() -> dict:
    import numpy as np

    return {"t": np.zeros(0, "int64"), "bid": np.zeros(0), "ask": np.zeros(0),
            "spread": np.zeros(0, "float32"), "buy": np.zeros(0, "float32"),
            "sell": np.zeros(0, "float32"), "exhausted": np.zeros(0, "bool"),
            "source": np.zeros(0, "int8")}


def to_bytes(packed: dict) -> bytes:
    import numpy as np

    buf = io.BytesIO()
    np.savez_compressed(buf, **{k: packed[k] for k in KEYS})
    return buf.getvalue()


def from_bytes(raw: bytes) -> dict:
    import numpy as np

    with np.load(io.BytesIO(raw)) as z:
        return {k: z[k] for k in KEYS}


def merge(a: dict | None, b: dict | None) -> dict:
    """Both, sorted by minute; where both hold a minute, `b` (the newer) wins."""
    import numpy as np

    parts = [p for p in (a, b) if p is not None and len(p["t"])]
    if not parts:
        return empty()
    cat = {k: np.concatenate([p[k] for p in parts]) for k in KEYS}
    # the LAST occurrence of each minute wins: reverse, unique, reverse back
    t = cat["t"][::-1]
    _, first = np.unique(t, return_index=True)
    keep = (len(t) - 1 - first)
    order = np.argsort(cat["t"][keep], kind="stable")
    idx = keep[order]
    return {k: cat[k][idx] for k in KEYS}


def _fetch(u: str) -> tuple[int, bytes]:
    req = urllib.request.Request(u, headers={"User-Agent": "tradingagents/0.3"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return int(r.status), r.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), b""


def _month_key(t: float) -> str:
    g = time.gmtime(int(t))
    return f"{g.tm_year:04d}{g.tm_mon:02d}"


def load_month(sym: str, ym: str, *, repos=None, fetch=None,
               cache: bool = True) -> dict | None:
    """One coin's readings for one month, from whichever account has them."""
    repos = tuple(repos or REPOS)
    fetch = fetch or _fetch
    path = CACHE / asset(sym, ym)
    current = ym >= _month_key(_now())
    if cache and path.exists():
        age = _now() - path.stat().st_mtime
        if not current or age < CURRENT_TTL_S:
            try:
                return from_bytes(path.read_bytes())
            except Exception:                                  # noqa: BLE001
                pass            # a broken cache file is read again below
    for repo in repos:
        status, raw = fetch(url(repo, sym, ym))
        if status == 200 and raw:
            got = from_bytes(raw)
            if cache:
                CACHE.mkdir(parents=True, exist_ok=True)
                tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
                tmp.write_bytes(raw)
                # stamped with THIS module's clock, the one the age is read by
                os.utime(tmp, (_now(), _now()))
                os.replace(tmp, path)
            return got
    return None


def book_for(sym: str, start_s: int, end_s: int, *, repos=None,
             fetch=None) -> dict:
    """Every reading of `sym` from LEAD_S before `start_s` to `end_s`
    (the lead lets a reading just before the window answer its first
    minute), across months. Empty when none was measured."""
    import numpy as np

    lo = int(start_s) - LEAD_S
    months, t = [], lo
    while True:
        k = _month_key(t)
        if k not in months:
            months.append(k)
        if k >= _month_key(end_s):
            break
        g = time.gmtime(t)
        y, m = (g.tm_year + (g.tm_mon == 12), g.tm_mon % 12 + 1)
        import calendar

        t = calendar.timegm((y, m, 1, 0, 0, 0))
    got = None
    for ym in months:
        part = load_month(sym, ym, repos=repos, fetch=fetch)
        got = merge(got, part) if part is not None else got
    if got is None:
        return empty()
    keep = (got["t"] >= lo) & (got["t"] <= int(end_s))
    return {k: np.asarray(got[k])[keep] for k in KEYS}
