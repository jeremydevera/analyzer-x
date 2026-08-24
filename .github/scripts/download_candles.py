"""Download candles on a GitHub runner and store them in the market database.

Candles are MEXC public data — the only secret this touches is the database
URL, which arrives via the TRADINGAGENTS_DB_URL environment secret and is
never printed. Sharding matches the sweep: shard k takes coins[k::N].
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.getcwd())

from tradingagents.dataflows import (
    market_db as mdb,  # noqa: E402
    mexc_futures as fx,  # noqa: E402
)


def main() -> int:
    coins_in = (os.environ.get("COINS") or "ALL").strip()
    tfs_in = (os.environ.get("TFS") or "15m,30m,1h,4h,1d").strip()
    shard = int(os.environ.get("SHARD") or 0)
    shards = int(os.environ.get("SHARDS") or 1)

    if coins_in.upper() == "ALL":
        coins = [c["symbol"] for c in fx.list_contracts()]
    else:
        coins = [c.strip() for c in coins_in.split(",") if c.strip()]
    coins = coins[shard::max(shards, 1)]
    ivs = [mdb.TIMEFRAMES[t.strip()] for t in tfs_in.split(",")
           if t.strip() in mdb.TIMEFRAMES]
    if not coins or not ivs:
        print(f"shard {shard}: nothing to do ({len(coins)} coins, "
              f"{len(ivs)} timeframes)")
        return 0
    if not mdb.available():
        print("FATAL: TRADINGAGENTS_DB_URL is not set", file=sys.stderr)
        return 1

    def progress(done, total, sym, iv):
        if done % 25 == 0 or done == total:
            print(f"shard {shard}: {done}/{total} · {sym} {iv}", flush=True)

    res = mdb.download(coins, ivs, progress=progress)
    print(f"shard {shard}: stored {res['bars_stored']:,} new bars across "
          f"{len(res['pairs'])} pairs, {len(res['errors'])} errors")
    for e in res["errors"][:20]:
        print("  ERROR", e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
