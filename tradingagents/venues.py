"""Which coins trade where — MEXC against OKX.

Operator, Oct 09, 2026: *"what if in backtest Stored strategies, just add
filter 'Show mexc coin only' meaning show coins that exist in mexc that are
not existing in okx"* — asked while weighing a move to OKX, after a file of
the 595 MEXC-only coins and their 22,083,764 strategies.

* MEXC: every `_USDT` perpetual MEXC is trading now (forecast_v2_daily.market,
  sweep_shard.eligible's rule).
* OKX: every `-USDT-SWAP` perpetual OKX lists (its public instruments API).
* A MEXC tokenized stock (`GMESTOCK`) counts as on OKX when OKX lists the bare
  ticker (`GME-USDT-SWAP` — OKX's stock perpetuals) — except where those
  letters are a CRYPTO coin OKX has listed for years (`SAME_LETTERS_CRYPTO`:
  DASHSTOCK is DoorDash, OKX's DASH is the coin).

Both lists are read at most once a day and kept beside the store
(`venues.json`): a filter must not wait on two exchanges every time the table
is asked. A refresh that fails keeps the last good lists and says how old they
are; with no lists at all the filter REFUSES, by name — it never quietly shows
every coin under a label that says "MEXC only".
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from pathlib import Path

TTL_S = 24 * 3600
SAME_LETTERS_CRYPTO = frozenset({"DASH", "QNT", "WEN"})
OKX_URL = "https://www.okx.com/api/v5/public/instruments?instType=SWAP"
_LOCK = threading.Lock()
_MEM: dict = {}


def _path() -> Path:
    from tradingagents import market_sweep as msw

    return Path(msw.HOME) / "venues.json"


def _fetch_okx() -> list[str]:
    req = urllib.request.Request(OKX_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r).get("data") or []
    out = sorted({d["instId"].split("-")[0] for d in data
                  if str(d.get("instId", "")).endswith("-USDT-SWAP")})
    if not out:
        raise ValueError("OKX listed no USDT perpetual")
    return out


def _fetch_mexc() -> list[str]:
    from tradingagents import forecast_v2_daily as f2d

    out = sorted(s.replace("_USDT", "") for s in f2d.market())
    if not out:
        raise ValueError("MEXC listed no live USDT contract")
    return out


def lists(now: float | None = None) -> dict:
    """{"okx": [...], "mexc": [...], "at": when read} — at most a day old
    when both exchanges answer; the last good lists when one does not."""
    now = time.time() if now is None else now
    with _LOCK:
        got = _MEM.get("lists")
        if got is None:
            try:
                got = json.loads(_path().read_text(encoding="utf-8"))
            except (OSError, ValueError):
                got = None
        if got and now - float(got.get("at") or 0) < TTL_S:
            _MEM["lists"] = got
            return got
        try:
            fresh = {"okx": _fetch_okx(), "mexc": _fetch_mexc(), "at": now}
        except Exception as exc:                               # noqa: BLE001
            if got:
                # the last good lists, and they SAY how old they are
                got = {**got, "stale": f"{type(exc).__name__}: {str(exc)[:160]}"}
                _MEM["lists"] = got
                return got
            raise ValueError(f"cannot tell which coins OKX lists: {type(exc).__name__}: "
                             f"{str(exc)[:160]}") from exc
        try:
            p = _path()
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(f"{p.name}.tmp")
            tmp.write_text(json.dumps(fresh), encoding="utf-8")
            tmp.replace(p)
        except OSError:
            pass
        _MEM["lists"] = fresh
        return fresh


def on_okx(coin: str, okx) -> bool:
    """`coin` (a MEXC name, no `_USDT`) has an OKX USDT perpetual."""
    coin = str(coin).upper()
    if coin in okx:
        return True
    base = coin[:-5] if coin.endswith("STOCK") else ""
    return bool(base) and base in okx and base not in SAME_LETTERS_CRYPTO


def mexc_only(now: float | None = None) -> list[str]:
    """Every coin MEXC trades now that OKX does not list, sorted."""
    got = lists(now)
    okx = set(got["okx"])
    return [c for c in got["mexc"] if not on_okx(c, okx)]
