"""One shard of the market sweep, for a GitHub runner.

Public data only — candles, funding, order book, contract detail. No API key is
read and none is needed, which is why this can run on someone else's machine.

The shard picks its slice of the eligible contracts by index, so N runners cover
the market without talking to each other.
"""
import itertools
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from tradingagents.dataflows import mexc_futures as fx          # noqa: E402
import tradingagents.auto_trader as at                          # noqa: E402
from tradingagents import backtest_report as br                 # noqa: E402

SHARD = int(os.environ.get("SHARD", "0"))
SHARDS = max(1, int(os.environ.get("SHARDS", "1")))
PER_SHARD = int(os.environ.get("COINS", "0"))
TFS = [t.strip() for t in os.environ.get("TFS", "15m,30m").split(",") if t.strip()]
MIN_DAYS = int(os.environ.get("MIN_DAYS", "365"))
BASE_MARGIN = 5.0
MIN_TRADES = 100
GATE_BLOCK = 0.50

OUT = os.path.join("out", f"rows-{SHARD}.jsonl")
os.makedirs("out", exist_ok=True)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from progress import Reporter                                   # noqa: E402

report = Reporter()


def log(msg):
    print(f"[shard {SHARD}] {msg}", flush=True)


def eligible():
    """Contracts at least MIN_DAYS old. Every shard screens the same list, in
    the same order, and then takes its own slice — cheap, and it needs no
    coordination between runners."""
    raw = fx._get_public(f"{fx.BASE}/api/v1/contract/detail").get("data") or []
    syms = sorted(x["symbol"] for x in raw
                  if str(x.get("symbol", "")).endswith("_USDT")
                  and int(x.get("state", 1)) == 0)
    mine = syms[SHARD::SHARDS]
    log(f"{len(syms)} contracts, {len(mine)} in this shard")
    keep = []
    report("screening", 0, len(mine), note="checking contract ages", force=True)
    for i, sym in enumerate(mine, 1):
        try:
            d = fx.klines(sym, "Day1", 500)
            if (d["Date"].iloc[-1] - d["Date"].iloc[0]).days >= MIN_DAYS:
                keep.append(sym)
        except Exception as exc:
            log(f"{sym}: age check failed ({str(exc)[:50]})")
        report("screening", i, len(mine),
               note=f"{len(keep)} old enough so far")
        time.sleep(0.05)
    log(f"{len(keep)} are at least {MIN_DAYS} days old")
    return keep[:PER_SHARD] if PER_SHARD else keep


def run_pair(sym, tf, out, *, i=0, n=0, rows_so_far=0):
    iv, bs, cap = br.TFS[tf]
    report("testing", i, n, rows=rows_so_far,
           note=f"{sym.replace('_USDT', '')} {tf}: downloading candles")
    try:
        fee = at.taker_fee(sym, fx=fx)
        liq = fx.liquidation_move_pct(sym, at.LEVERAGE)
        fund = fx.funding_history(sym)
        book = fx.book_cost(sym, BASE_MARGIN * at.LEVERAGE)
        rt = 2 * (fee + float(book.get("spread") or 0) / 2
                  + float(book.get("slippage") or 0))
        df = at._closed_bars(fx.klines(sym, iv, cap), bs)
    except Exception as exc:
        log(f"{sym} {tf}: {str(exc)[:60]}")
        return 0
    if len(df) < 2000:
        return 0
    coin = sym.replace("_USDT", "")
    days = int((df["Date"].iloc[-1] - df["Date"].iloc[0]).days)
    hi = [float(x) for x in df["High"]]
    lo = [float(x) for x in df["Low"]]
    cl = [float(x) for x in df["Close"]]
    op = [float(x) for x in df["Open"]]
    vol = [float(x) for x in df["Volume"]] if "Volume" in df.columns else None
    ts = list(df["Date"].to_numpy().astype("datetime64[ms]").astype("int64"))
    nbars = len(df)
    half = nbars // 2
    kept = 0
    report("testing", i, n, rows=rows_so_far,
           note=f"{coin} {tf}: {nbars:,} bars, testing {len(br.SIGNALS)} rules")
    for si, sig in enumerate(br.SIGNALS, 1):
        key = f"{sig}_gh_{tf}"
        th = br.THRESHOLDS[tf][1] if sig in br.THRESH_SIGNALS else None
        at.STRATEGY_SPECS[key] = {"interval": iv, "bar_seconds": bs, "tp": .02,
                                  "sl": .01,
                                  "threshold": .003 if th is None else th}
        try:
            dk = "rsi14_1h" if sig == "rsi14" else key
            dirs = at._dirs_for_backtest(dk, hi, lo, cl, opens=op, volume=vol,
                                         ts=ts)
        except Exception:
            at.STRATEGY_SPECS.pop(key, None)
            continue
        thp = 0.0 if th is None else round(th * 100, 3)
        for (sl, tp), sz in itertools.product(br.pairs_for(tf),
                                              ("flat", "martingale")):
            if liq is not None and sl * 100 >= liq:
                continue
            if rt / tp >= GATE_BLOCK:
                continue
            try:
                r = at.backtest_strategy(key, df, BASE_MARGIN, fee=fee,
                                         sizing=sz, dirs=dirs, tp=tp, sl=sl,
                                         liq_move_pct=liq, funding=fund,
                                         keep_log=False)
            except Exception:
                continue
            if r["trades"] < MIN_TRADES or r["profit"] <= 0:
                continue
            a = at.backtest_strategy(key, df.iloc[:half], BASE_MARGIN, fee=fee,
                                     sizing=sz, dirs=dirs[:half], tp=tp, sl=sl,
                                     liq_move_pct=liq, funding=fund,
                                     keep_log=False)
            b = at.backtest_strategy(key, df.iloc[half:], BASE_MARGIN, fee=fee,
                                     sizing=sz, dirs=dirs[half:], tp=tp, sl=sl,
                                     liq_move_pct=liq, funding=fund,
                                     keep_log=False)
            m = r["monthly"]
            out.write(json.dumps({
                "coin": coin, "tf": tf, "signal": sig, "th": thp,
                "sl": round(sl * 100, 3), "tp": round(tp * 100, 3),
                "rr": round(tp / sl, 2), "sizing": sz, "lev": at.LEVERAGE,
                "base": BASE_MARGIN, "notional": BASE_MARGIN * at.LEVERAGE,
                "trades": r["trades"], "wins": r["wins"], "losses": r["losses"],
                "winrate": round(100 * r["wins"] / r["trades"], 2),
                "profit": round(r["profit"], 2),
                "funding": round(r["funding_total"], 2),
                "h1": round(a["profit"], 2), "h2": round(b["profit"], 2),
                "green": r["months_green"], "months": r["months_total"],
                "worst": round(r["worst_trade"], 2), "dd": round(r["max_dd"], 2),
                "liqs": r["liqs"], "stop_reachable": True, "days": days,
                "bars": nbars, "monthly": {k: round(v, 2) for k, v in m.items()},
                "cost_of_tp": round(rt / tp * 100, 1), "rt": round(rt * 100, 4),
                "gate": "warn" if rt / tp >= .2 else "ok"}) + "\n")
            kept += 1
        at.STRATEGY_SPECS.pop(key, None)
        report("testing", i, n, rows=rows_so_far + kept,
               note=f"{coin} {tf}: rule {si}/{len(br.SIGNALS)} ({sig})")
    out.flush()
    return kept


def main():
    t0 = time.time()
    coins = eligible()
    total = 0
    with open(OUT, "w") as out:
        for i, sym in enumerate(coins, 1):
            for tf in TFS:
                total += run_pair(sym, tf, out, i=i, n=len(coins),
                                  rows_so_far=total)
            el = time.time() - t0
            log(f"{i}/{len(coins)} {sym} · {total:,} rows · "
                f"{el / 60:.0f} min elapsed · "
                f"ETA {el / i * (len(coins) - i) / 60:.0f} min")
            # A runner is killed at six hours with no artifact, so stop early
            # and keep what has been measured.
            if el > 5.2 * 3600:
                log(f"stopping at {i}/{len(coins)} coins to protect the artifact")
                break
    report("done", len(coins), len(coins), rows=total,
           note=f"{total:,} rows", force=True)
    log(f"done: {total:,} rows in {(time.time() - t0) / 60:.0f} min")


if __name__ == "__main__":
    main()
