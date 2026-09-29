"""The strategy watcher's candidates: found in the v2 index, judged on the pair
file's FRESH figures.

Task 4 of docs/superpowers/plans/2026-09-28-strategy-watcher.md. Measured Sep
28, 2026: the top v2 rows by win rate read measured-through Sep 22, 2026 in the
index while their pair files ended Sep 28, 2026 12:30pm — 3,656 of 5,006 pairs
stale in the index. So the index only NOMINATES; every decision is made on the
row as its pair file holds it now, and a pair file whose last candle is older
than `fresh_hours` is not "the last 30 days" and is skipped, counted and named.

Every group is a candidate (the replay the operator approved walked all four),
as long as its strategy key reaches its own rule — `strategy_keys.key_for`
round-trips through `local_history._sig_of`, or the row is refused by name.
"""
from __future__ import annotations

import json
from pathlib import Path

from tradingagents import backtest_report as br
from tradingagents import stores

DAY_MS = 86_400_000


def _index_rows(cfg: dict, limit: int) -> list[dict]:
    """The v2 index's nominees: flat rows at or over the floors, best win rate
    first. TP >= SL is asked of the index; a strict TP > SL is applied after."""
    from tradingagents import rows_index as ri

    got = ri.query(db_path=stores.V2.rows_db, sort="winrate", desc=True,
                   limit=limit, min_trades=int(cfg["min_trades"]),
                   min_winrate=float(cfg["on_winrate"]), tp_over_sl=True,
                   sizing="flat")
    return list(got.get("rows") or [])


def _pair_rows(coin: str, tf: str) -> list[dict]:
    from tradingagents import market_sweep as msw

    return msw.pair_rows(coin, tf, root=stores.V2.home)


def _last_ms(coin: str, tf: str) -> float | None:
    """The last candle the pair file was measured through (its state's
    `__last_ms__`), or None when it cannot be read."""
    p = Path(stores.V2.home) / "state" / f"{coin}-{tf}.json"
    try:
        return float(json.loads(p.read_text(encoding="utf-8")).get("__last_ms__") or 0) or None
    except (OSError, ValueError):
        return None


def _match(rows: list[dict], want: dict) -> dict | None:
    """The pair row that IS this index row: same signal, threshold, SL, TP,
    flat sizing."""
    for r in rows:
        if (r.get("signal") == want["signal"]
                and round(float(r.get("th") or 0), 3) == round(float(want.get("th") or 0), 3)
                and round(float(r.get("sl")), 3) == round(float(want["sl"]), 3)
                and round(float(r.get("tp")), 3) == round(float(want["tp"]), 3)
                and (r.get("sizing") or "flat") == "flat"):
            return r
    return None


def _fresh(coin: str, tf: str, r: dict, last_ms: float) -> dict:
    return {"id": br.row_code(coin, tf, r["signal"], float(r.get("th") or 0),
                              float(r["sl"]), float(r["tp"]), "flat", res="1m"),
            "coin": coin, "tf": tf, "signal": r["signal"],
            "th": float(r.get("th") or 0), "sl": float(r["sl"]), "tp": float(r["tp"]),
            "trades": int(r["trades"]), "wins": int(r["wins"]),
            "losses": int(r.get("losses", int(r["trades"]) - int(r["wins"]))),
            "winrate": float(r["winrate"]), "profit": float(r["profit"]),
            "gate": r.get("gate") or "", "cost_of_tp": r.get("cost_of_tp"),
            "measured_ms": last_ms}


def fresh_candidates(cfg: dict, *, now: float, limit: int = 5000) -> dict:
    """{"rows", "asked", "stale", "gone", "why"}: the index's nominees, each
    replaced by its pair file's current figures. Each pair file is read once."""
    try:
        nominees = _index_rows(cfg, limit)
    except Exception as exc:                                   # noqa: BLE001
        # NOT "no candidates". The index can be mid-rebuild or building the
        # sort list this query needs (rows_wr4 was, on Sep 29, 2026 3:40am,
        # right after a rebuild swapped in): the pass must wait and ask
        # again, never switch on nothing and call it a day's decision.
        return {"rows": [], "asked": 0, "stale": 0, "gone": 0, "not_ready": True,
                "why": f"the Backtest v2 list could not be read yet "
                       f"({type(exc).__name__}: {str(exc)[:160]}) — asking again later"}
    by_pair: dict = {}
    for r in nominees:
        by_pair.setdefault((r["coin"], r["tf"]), []).append(r)
    rows, stale, gone = [], 0, 0
    fresh_ms = float(cfg.get("fresh_hours", 36)) * 3_600_000
    for (coin, tf), want in by_pair.items():
        last = _last_ms(coin, tf)
        if last is None or now * 1000 - last > fresh_ms:
            stale += len(want)
            continue
        have = _pair_rows(coin, tf)
        for w in want:
            got = _match(have, w)
            if got is None:
                gone += 1
                continue
            rows.append(_fresh(coin, tf, got, last))
    why = (f"{len(rows):,} candidate(s) from {len(nominees):,} nominated · "
           f"{stale:,} row(s) skipped: pair file older than "
           f"{cfg.get('fresh_hours', 36):g} hours · {gone:,} gone from their pair file")
    return {"rows": rows, "asked": len(nominees), "stale": stale, "gone": gone,
            "why": why}


def fresh_row(row_id: str, coin: str, tf: str, spec: dict, *, now: float,
              cfg: dict) -> dict | None:
    """A RUNNING slot's row as its pair file holds it now, or None when the
    file no longer holds it. A stale pair file still answers with what it has
    (switching off on old news would be its own mistake); `measured_ms` says
    how old it is."""
    last = _last_ms(coin, tf) or 0.0
    got = _match(_pair_rows(coin, tf), spec)
    return None if got is None else _fresh(coin, tf, got, last)
