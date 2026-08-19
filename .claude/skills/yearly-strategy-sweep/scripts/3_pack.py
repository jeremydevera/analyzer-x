"""Pack the sweep's rows + trade logs for the top rows into one artifact file."""
import sys, json, os, time
sys.path.insert(0, "/Users/jeremydevera/Desktop/Trading Agents")
from tradingagents.dataflows import mexc_credentials as cred; cred.load_into_env()
from tradingagents.dataflows import mexc_futures as fx
import tradingagents.auto_trader as at

import os
# rstrip+add the separator: paths are concatenated as strings, and a
# SWEEP_DIR without a trailing slash silently produced "...4h1dsweep3tf_rows".
H = os.path.join(os.environ.get(
    "SWEEP_DIR", os.path.expanduser("~/.tradingagents/sweeps/latest")), "")
IV = {"1h": ("Min60", 3600, 10000), "15m": ("Min15", 900, 36000),
      "1m": ("Min1", 60, 46000), "4h": ("Hour4", 14400, 14000),
      "1d": ("Day1", 86400, 2400)}
TH = {"1h": 0.003, "15m": 0.0015, "1m": 0.0008, "4h": 0.006, "1d": 0.010}
LOGS_PER_TF = 14

rows = [json.loads(l) for l in open(H + "sweep3tf_rows.jsonl")]
done = json.load(open(H + "sweep3tf_done.json"))
exc = json.load(open(H + "sweep3tf_excluded.json"))
book = json.load(open(H + "sweep_book.json"))
coins_done = len({d.split("|")[0] for d in done})

def survives(r):
    return (r["h1"] > 0 and r["h2"] > 0 and r["months"] > 0
            and r["green"] / r["months"] >= 0.70)
for r in rows:
    r["survivor"] = survives(r)

# pick which rows get a full trade log: best by profit AND best survivors
want, seen = [], set()
for tf in sorted({r["tf"] for r in rows}):
    pool = [r for r in rows if r["tf"] == tf]
    # FLAT survivors are the short list — the rows whose SIGNAL is proven —
    # and they were being left without trade logs because top-by-profit is
    # dominated by martingale. Capture them first, and the deep-history ones
    # explicitly, before the headline rows.
    flat_surv = sorted([x for x in pool
                        if x["survivor"] and x["sizing"] == "flat"],
                       key=lambda r: -r["profit"])
    deep = sorted([x for x in pool if x["survivor"] and x["days"] >= 1000],
                  key=lambda r: -r["profit"])
    for lst in (flat_surv[:LOGS_PER_TF],
                deep[:LOGS_PER_TF],
                sorted([x for x in pool if x["survivor"]],
                       key=lambda r: -r["profit"])[:LOGS_PER_TF],
                sorted(pool, key=lambda r: -r["profit"])[:LOGS_PER_TF]):
        for r in lst:
            k = (r["coin"], r["tf"], r["signal"], r["sl"], r["tp"], r["sizing"])
            if k in seen:
                continue
            seen.add(k); want.append(r)

logs, frames = {}, {}
for i, r in enumerate(want, 1):
    fk = (r["coin"], r["tf"])
    if fk not in frames:
        iv, bs, lim = IV[r["tf"]]
        try:
            frames[fk] = fx.klines(r["coin"], iv, lim)
        except Exception as e:
            frames[fk] = None
            print("fetch fail", fk, e)
        time.sleep(0.35)
    df = frames[fk]
    if df is None:
        continue
    iv, bs, lim = IV[r["tf"]]
    key = f"{r['signal']}_pk_{r['tf']}"
    at.STRATEGY_SPECS[key] = {"interval": iv, "bar_seconds": bs,
                              "tp": r["tp"] / 100, "sl": r["sl"] / 100,
                              "threshold": TH[r["tf"]]}
    res = at.backtest_strategy(key, df, 5.0, fee=r["fee"] / 100,
                               sizing=r["sizing"])
    lk = "|".join([r["coin"], r["tf"], r["signal"], f'{r["sl"]:.2f}',
                   f'{r["tp"]:.2f}', r["sizing"]])
    logs[lk] = {"log": res["log"][:400],
                "monthly": {k: round(v, 2) for k, v in res["monthly"].items()}}
    if i % 10 == 0:
        print(f"  logs {i}/{len(want)}")

out = {"rows": rows, "logs": logs, "coins_done": coins_done,
       "coins_total": len(book), "excluded": exc[:400],
       "excluded_total": len(exc),
       "stamp": time.strftime("%Y-%m-%d %H:%M")}
json.dump(out, open(H + "sweep_pack.json", "w"), separators=(",", ":"))
print("rows:", len(rows), "logs:", len(logs), "coins:", coins_done,
      "bytes:", os.path.getsize(H + "sweep_pack.json"))
