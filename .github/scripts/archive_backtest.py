"""Run the shared backtest grid on a GitHub runner, off the candle archive.

Same grid as the app's Backtest button (`tradingagents.backtest_report`) —
never a private copy. Rows are written to the database's backtest_results,
and the standalone report page is uploaded as the run's artifact.
"""

from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.getcwd())

from tradingagents import backtest_report as br  # noqa: E402
from tradingagents.dataflows import market_db as mdb  # noqa: E402


def main() -> int:
    coins = [c.strip() for c in (os.environ.get("COINS") or "").split(",")
             if c.strip()]
    tfs = [t.strip() for t in (os.environ.get("TFS") or "1h").split(",")
           if t.strip() in br.TFS]
    days = int(os.environ.get("DAYS") or 365)
    base = float(os.environ.get("BASE") or 5.0)
    if not coins or not tfs:
        print("FATAL: no coins or timeframes", file=sys.stderr)
        return 1

    t0 = time.time()
    payload = br.run_grid(
        coins, tfs, base_margin=base, days=days,
        progress=lambda m, f: print(f"{f * 100:5.1f}%  {m}", flush=True))
    print(f"grid done in {time.time() - t0:.0f}s — "
          f"{len(payload['rows']):,} rows")
    if not payload["rows"]:
        return 0

    os.makedirs("out", exist_ok=True)
    br.write_report(
        "out/report.html", payload,
        title=f"Archive backtest · {', '.join(c.replace('_USDT', '') for c in coins)}",
        note=f"{days} days, {', '.join(tfs)}, base margin {base:g} USDT. "
             f"Run on GitHub, fetched {payload['fetched']}.")

    if mdb.available():
        day_end = int(time.time()) // 86400 * 86400
        n = mdb.save_results([{
            "row_code": r["id"], "symbol": f"{r['coin']}_USDT",
            "timeframe": r["tf"], "signal": r["signal"], "tp": r["tp"],
            "sl": r["sl"], "sizing": r["sizing"],
            "data_start": day_end - days * 86400, "data_end": day_end,
            "code_version": f"signals{len(br.SIGNALS)}",
            "profit": r["profit"], "trades": r["trades"], "wins": r["wins"],
            "losses": r["losses"], "win_rate": r["winrate"],
            "worst_streak": r["dd"], "worst_streak_len": None,
            "months_json": json.dumps(r["monthly"]),
        } for r in payload["rows"]])
        print(f"saved {n:,} rows to backtest_results")
    else:
        print("WARNING: no database URL — rows not saved", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
