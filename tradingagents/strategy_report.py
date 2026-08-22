"""Build the full-grid page for ONE deployed strategy. No UI framework.

Extracted from app.py's `_bt_report_build` so the same page can be produced
from the HTTP layer. The behaviours that matter and why:

* the DEPLOYED row is injected, because a live 0.80/2.40 pair appears in no
  grid of round numbers (CLAUDE.md rule 21);
* candles are read store-first, so a re-run tests only new bars;
* the page is cached under a signature of everything that could change it —
  including the signal count — so a repeat click is instant but a widened
  registry rebuilds;
* the fetch is sized from the timeframe, never a flat 2000 bars: 2000 bars is
  333 days on 4h and 83 days on 1h, which silently turned a "1 year" backtest
  into under three months (rule 13).
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import hashlib
from pathlib import Path

REPORT_DIR = Path(__file__).resolve().parent.parent / "static" / "bt"
KEEP = 12

TF_NAME = {"Min1": "1m", "Min15": "15m", "Min30": "30m", "Min60": "1h",
           "Hour4": "4h", "Day1": "1d"}


def signature(key: str, coins: list[str], tfs: list[str], sizing: str,
              base_margin: float, days: int, spec: dict,
              n_signals: int) -> str:
    return "-".join([key, ",".join(sorted(coins)), ",".join(tfs), sizing,
                     f"{base_margin:g}", str(days),
                     f"{spec.get('sl')}/{spec.get('tp')}/"
                     f"{spec.get('threshold')}", str(n_signals)])


def build(key: str, *, label: str, coins: list[str], base_margin: float,
          days: int = 365, progress=None, today: str | None = None) -> dict:
    """Run the grid and write the page. Returns {name, url, rows, cached}."""
    from tradingagents import auto_trader as at, backtest_report as br

    if not coins:
        raise ValueError("select at least one contract to backtest")
    spec = at.STRATEGY_SPECS.get(key) or {}
    own = TF_NAME.get(spec.get("interval"), "1h")
    tfs = [own] + [t for t in ("1h", "4h") if t != own]
    signal = key.split("_")[1] if key.startswith("ict_") else key.split("_")[0]
    sizing = at.sizing_for(at.load_settings())
    deployed = [{"coin": c.replace("_USDT", ""), "tf": own, "signal": signal,
                 "th": round(float(spec.get("threshold") or 0) * 100, 3),
                 "sl": round(float(spec.get("sl", 0)) * 100, 3),
                 "tp": round(float(spec.get("tp", 0)) * 100, 3),
                 "sizing": sizing} for c in coins]

    sig = signature(key, coins, tfs, sizing, base_margin, days, spec,
                    len(br.SIGNALS))
    stamp = today or _dt.datetime.now().strftime("%Y%m%d")
    stem = f"{key}-{hashlib.blake2s(sig.encode(), digest_size=4).hexdigest()}"
    fresh = REPORT_DIR / f"{stem}-{stamp}.html"
    if fresh.exists() and fresh.stat().st_size > 10_000:
        return {"name": fresh.name, "url": f"/api/reports/file/{fresh.name}",
                "rows": None, "cached": True}

    payload = br.grid_from_store(coins, tfs, base_margin=base_margin,
                                days=days, deployed=deployed,
                                progress=progress)
    if not payload["rows"]:
        raise RuntimeError("no rows could be tested — is any candle stored?")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    shown = [c.replace("_USDT", "") for c in dict.fromkeys(coins)]
    extra = [c for c in shown if c not in label]
    br.write_report(
        str(fresh), payload,
        title=label + (" · " + ", ".join(extra) if extra else ""),
        note=(f"<b>{label}</b> is deployed on {', '.join(shown)} at "
              f"SL {float(spec.get('sl', 0)) * 100:.2f}% / "
              f"TP {float(spec.get('tp', 0)) * 100:.2f}%, {sizing}. That row is "
              f"marked <b>DEPLOYED</b> and always visible, whatever the Show "
              f"box says — every other row is an alternative measured on the "
              f"same candles."))
    for stale in sorted(REPORT_DIR.glob("*.html"),
                        key=lambda p: p.stat().st_mtime, reverse=True)[KEEP:]:
        with contextlib.suppress(OSError):
            stale.unlink()
    return {"name": fresh.name, "url": f"/api/reports/file/{fresh.name}",
            "rows": len(payload["rows"]), "cached": False}
