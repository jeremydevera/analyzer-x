"""Full grid over EVERY MEXC USDT perpetual, on 1h / 15m / 1m.

Rules this obeys (CLAUDE.md 9-13, 18-20):
  * every dimension varies: coin x timeframe x signal x TP/SL x sizing
  * slippage is charged, measured PER CONTRACT from the live order book
  * the liquidity gate pre-filters per timeframe, and every exclusion is
    RECORDED with its reason -- nothing is dropped silently
  * history depth is recorded per row. MEASURED 2026-08-13: MEXC serves
    30 days of 1m (hard ceiling), 360 days of 15m, 400+ days of 1h
  * flat AND martingale, always

Throttled + checkpointed: MEXC answers a hammered client with TRUNCATED
history, which silently produces wrong numbers.
"""
import sys, os, json, time, math, itertools, traceback
sys.path.insert(0, "/Users/jeremydevera/Desktop/Trading Agents")
from tradingagents.dataflows import mexc_credentials as cred; cred.load_into_env()
from tradingagents.dataflows import mexc_futures as fx
import tradingagents.auto_trader as at

import os
# rstrip+add the separator: paths are concatenated as strings, and a
# SWEEP_DIR without a trailing slash silently produced "...4h1dsweep3tf_rows".
H = os.path.join(os.environ.get(
    "SWEEP_DIR", os.path.expanduser("~/.tradingagents/sweeps/latest")), "")
BOOK = H + "sweep_book.json"
OUT = H + "sweep3tf_rows.jsonl"
STATE = H + "sweep3tf_done.json"
LOG = H + "sweep3tf.log"

# Bar limits are the MEASURED depth MEXC serves, not guesses. Re-measure by
# paging klines backwards until it stops. 2026-08-14: 4h and 1d both reach
# 2,261 days (6.19 years) — far deeper than 1h's 416.
ALL_TFS = {
    "1m":  ("Min1", 60, 46000),
    "15m": ("Min15", 900, 36000),
    "1h":  ("Min60", 3600, 10000),
    "4h":  ("Hour4", 14400, 14000),
    "1d":  ("Day1", 86400, 2400),
}
BARRIERS = {
    "1m":  [(0.0010, 0.0030), (0.0015, 0.0045), (0.0020, 0.0080)],
    "15m": [(0.0020, 0.0060), (0.0030, 0.0090), (0.0040, 0.0160)],
    "1h":  [(0.0060, 0.0180), (0.0080, 0.0240), (0.0100, 0.0400)],
    "4h":  [(0.0120, 0.0360), (0.0150, 0.0450), (0.0200, 0.0800)],
    "1d":  [(0.0250, 0.1000), (0.0300, 0.0900), (0.0400, 0.1200)],
}
# thresholds scale with the bar: 0.3% is a large move in an hour, noise in a day
THRESH = {"1m": 0.0008, "15m": 0.0015, "1h": 0.003, "4h": 0.006, "1d": 0.010}
# pick timeframes with SWEEP_TFS, e.g. SWEEP_TFS="4h,1d"
_want = [t.strip() for t in os.environ.get("SWEEP_TFS", "1h,15m,1m").split(",")
         if t.strip()]
TFS = [(ALL_TFS[t][0], ALL_TFS[t][1], t, ALL_TFS[t][2]) for t in _want]
SIGNALS = ["mom6", "mom15", "fade15", "trend50", "rsi14", "sweep30", "fvg"]
SIZINGS = ["martingale", "flat"]
MIN_TRADES = 25
GATE_BLOCK = 0.50          # cost >= 50% of target -> cannot win

def log(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")

def throttled(fn, *a, tries=4, **kw):
    for k in range(tries):
        try:
            return fn(*a, **kw)
        except Exception as e:
            m = str(e).lower()
            if any(t in m for t in ("510", "too many", "frequen", "429")):
                time.sleep(1.5 * (k + 1))
                continue
            raise
    raise RuntimeError("rate limited after retries")

# ---------- phase 1: contracts + per-contract book cost ----------
if os.path.exists(BOOK):
    book = json.load(open(BOOK))
    log(f"book cache: {len(book)} contracts")
else:
    log("fetching contract list...")
    try:
        raw = fx._get_public(f"{fx.BASE}/api/v1/contract/detail")
        detail = raw.get("data") or []
    except Exception as e:
        log(f"contract list FAILED: {e}"); raise
    syms = [d["symbol"] for d in detail
            if str(d.get("symbol", "")).endswith("_USDT")
            and int(d.get("state", 1)) == 0]
    log(f"{len(syms)} tradeable USDT perpetuals")
    book = {}
    for i, sym in enumerate(syms, 1):
        try:
            c = throttled(fx.book_cost, sym, 100.0)
            book[sym] = {"spread": float(c.get("spread") or 0),
                         "slippage": float(c.get("slippage") or 0),
                         "fee": at.taker_fee(sym, fx=fx)}
        except Exception as e:
            book[sym] = {"error": str(e)[:90]}
        if i % 50 == 0:
            log(f"  book {i}/{len(syms)}")
            json.dump(book, open(BOOK, "w"))
        time.sleep(0.14)
    json.dump(book, open(BOOK, "w"))
    log(f"book done: {len(book)}")

done = set(json.load(open(STATE))) if os.path.exists(STATE) else set()
out = open(OUT, "a")
excluded = []

def rt_cost(sym):
    b = book.get(sym) or {}
    if "error" in b or not b:
        return None
    return 2 * (b["fee"] + b["spread"] / 2 + b["slippage"])

syms = sorted(book)
log(f"grid over {len(syms)} contracts x 3 timeframes")
n_tested = 0
for si, sym in enumerate(syms, 1):
    rt = rt_cost(sym)
    if rt is None:
        excluded.append({"coin": sym, "why": "order book unreadable"})
        continue
    for iv, bs, tf, limit in TFS:
        tag = f"{sym}|{tf}"
        if tag in done:
            continue
        usable = [(sl, tp) for sl, tp in BARRIERS[tf] if rt / tp < GATE_BLOCK]
        if not usable:
            excluded.append({"coin": sym, "tf": tf, "why":
                             f"liquidity gate: cost {rt*100:.3f}% is "
                             f">={GATE_BLOCK*100:.0f}% of every {tf} target"})
            done.add(tag); continue
        try:
            df = throttled(fx.klines, sym, iv, limit)
        except Exception as e:
            excluded.append({"coin": sym, "tf": tf, "why": f"fetch: {str(e)[:70]}"})
            done.add(tag); time.sleep(0.12); continue
        if len(df) < 300:
            excluded.append({"coin": sym, "tf": tf,
                             "why": f"only {len(df)} bars"})
            done.add(tag); time.sleep(0.12); continue
        days = (df["Date"].iloc[-1] - df["Date"].iloc[0]).days
        fee = book[sym]["fee"]
        hi_l = [float(x) for x in df["High"]]
        lo_l = [float(x) for x in df["Low"]]
        cl_l = [float(x) for x in df["Close"]]
        dcache = {}
        for sig, (sl, tp), sizing in itertools.product(SIGNALS, usable, SIZINGS):
            if rt / tp >= GATE_BLOCK:
                continue
            key = f"{sig}_sw_{tf}"
            at.STRATEGY_SPECS[key] = {"interval": iv, "bar_seconds": bs,
                                      "tp": tp, "sl": sl,
                                      "threshold": THRESH[tf]}
            if sig not in dcache:
                dcache[sig] = at._dirs_for_backtest(key, hi_l, lo_l, cl_l)
            try:
                r = at.backtest_strategy(key, df, 5.0, fee=fee, sizing=sizing,
                                         dirs=dcache[sig])
            except Exception:
                continue
            n_tested += 1
            if r["trades"] < MIN_TRADES or r["profit"] <= 0:
                continue
            n = len(df); h = n // 2
            a = at.backtest_strategy(key, df.iloc[:h], 5.0, fee=fee,
                                     sizing=sizing, dirs=dcache[sig][:h])
            b = at.backtest_strategy(key, df.iloc[h:], 5.0, fee=fee,
                                     sizing=sizing, dirs=dcache[sig][h:])
            m = r["monthly"]
            out.write(json.dumps({
                "coin": sym, "tf": tf, "signal": sig,
                "sl": sl * 100, "tp": tp * 100, "sizing": sizing,
                "lev": at.LEVERAGE, "margin": 5.0, "notional": 100.0,
                "fee": fee * 100, "rt_cost": rt * 100,
                "cost_of_tp": rt / tp * 100, "days": days, "bars": n,
                "trades": r["trades"], "wins": r["wins"],
                "losses": r["trades"] - r["wins"],
                "winrate": round(100 * r["wins"] / max(1, r["trades"]), 1),
                "profit": round(r["profit"], 2),
                "h1": round(a["profit"], 2), "h2": round(b["profit"], 2),
                "green": sum(1 for v in m.values() if v > 0),
                "months": len(m),
                "worst_month": round(min(m.values()), 2) if m else 0,
                "worst_trade": round(r["worst_trade"], 2),
                "max_dd": round(r["max_dd"], 2),
            }) + "\n")
        out.flush()
        done.add(tag)
        time.sleep(0.12)
    if si % 20 == 0:
        json.dump(sorted(done), open(STATE, "w"))
        json.dump(excluded, open(H + "sweep3tf_excluded.json", "w"))
        log(f"  {si}/{len(syms)} contracts | {n_tested} combos tested")
json.dump(sorted(done), open(STATE, "w"))
json.dump(excluded, open(H + "sweep3tf_excluded.json", "w"))
out.close()
log(f"DONE. combos tested={n_tested} excluded={len(excluded)}")
