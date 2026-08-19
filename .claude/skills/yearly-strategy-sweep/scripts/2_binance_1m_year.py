"""A full YEAR of 1-minute history, sourced from Binance, costed with MEXC.

MEXC serves only 30 days of 1m (measured). Binance serves 370+. But a Binance
candle is only a valid stand-in for a MEXC candle where the two books actually
agree -- on a thin contract they disagree about the minute's high/low by as
much as the whole bar is tall, which at a 0.10% stop flips the outcome more
than half the time. So every coin is gated on MEASURED agreement first.

Costs are always MEXC's: the operator trades on MEXC.
"""
import sys, os, json, time, itertools, urllib.request
sys.path.insert(0, "/Users/jeremydevera/Desktop/Trading Agents")
from tradingagents.dataflows import mexc_credentials as cred; cred.load_into_env()
from tradingagents.dataflows import mexc_futures as fx
import tradingagents.auto_trader as at
import pandas as pd

import os
# rstrip+add the separator: paths are concatenated as strings, and a
# SWEEP_DIR without a trailing slash silently produced "...4h1dsweep3tf_rows".
H = os.path.join(os.environ.get(
    "SWEEP_DIR", os.path.expanduser("~/.tradingagents/sweeps/latest")), "")
AGREE = H + "binance_agreement.json"
ROWS = H + "binance_1m_rows.jsonl"
DONE = H + "binance_1m_done.json"
LOG = H + "binance_1m.log"
UA = {"User-Agent": "Mozilla/5.0"}

BARRIERS = [(0.0010, 0.0030), (0.0015, 0.0045), (0.0020, 0.0080)]
TIGHTEST_SL = 0.0010
AGREE_MAX = 0.25            # median wick disagreement must be <=25% of that SL
SIGNALS = ["mom6", "mom15", "fade15", "trend50", "rsi14", "sweep30", "fvg"]
SIZINGS = ["martingale", "flat"]
THRESH = 0.0008
GATE_BLOCK = 0.50
MIN_TRADES = 25
DAYS = 365

def log(m):
    line = f"{time.strftime('%H:%M:%S')} {m}"
    print(line, flush=True)
    open(LOG, "a").write(line + "\n")

def jget(url, tries=5):
    for k in range(tries):
        try:
            r = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(r, timeout=30) as x:
                return json.loads(x.read())
        except Exception as e:
            if k == tries - 1:
                raise
            time.sleep(1.2 * (k + 1))

def bn_sym(m):
    return m.replace("_USDT", "") + "USDT"

book = json.load(open(H + "sweep_book.json"))
overlap = json.load(open(H + "binance_overlap.json"))

# ---------- phase A: does Binance agree with MEXC on this contract? ----------
agree = json.load(open(AGREE)) if os.path.exists(AGREE) else {}
todo = [c for c in overlap if c not in agree]
log(f"agreement scan: {len(todo)} of {len(overlap)} contracts left")
for i, coin in enumerate(todo, 1):
    try:
        df = fx.klines(coin, "Min1", 400)
        m = {int(d.timestamp()): (float(h), float(l))
             for d, h, l in zip(df["Date"], df["High"], df["Low"])}
        k = jget("https://fapi.binance.com/fapi/v1/klines?symbol="
                 f"{bn_sym(coin)}&interval=1m&limit=500")
        b = {int(c[0]) // 1000: (float(c[2]), float(c[3])) for c in k}
        common = sorted(set(m) & set(b))
        if len(common) < 60:
            agree[coin] = {"ok": False, "why": "too few matching minutes"}
        else:
            d = sorted(max(abs(m[t][0] - b[t][0]) / m[t][0],
                           abs(m[t][1] - b[t][1]) / m[t][1]) for t in common)
            med = d[len(d) // 2]
            agree[coin] = {"ok": med <= TIGHTEST_SL * AGREE_MAX,
                           "median_pct": round(med * 100, 5),
                           "n": len(common),
                           "why": (f"wicks differ by {med*100:.4f}% = "
                                   f"{med/TIGHTEST_SL*100:.0f}% of the tightest "
                                   f"stop")}
    except Exception as e:
        agree[coin] = {"ok": False, "why": f"error: {str(e)[:70]}"}
    if i % 25 == 0:
        json.dump(agree, open(AGREE, "w"))
        log(f"  agreement {i}/{len(todo)} | passing so far "
            f"{sum(1 for v in agree.values() if v.get('ok'))}")
    time.sleep(0.22)
json.dump(agree, open(AGREE, "w"))
passing = sorted(c for c, v in agree.items() if v.get("ok"))
log(f"agreement done: {len(passing)} of {len(overlap)} contracts agree closely "
    f"enough to use Binance candles")

# ---------- phase B: a year of 1m, per passing contract ----------
def binance_year(coin):
    end = int(time.time() * 1000)
    start = end - DAYS * 86400 * 1000
    rows, cur = [], start
    while cur < end:
        k = jget("https://fapi.binance.com/fapi/v1/klines?symbol="
                 f"{bn_sym(coin)}&interval=1m&limit=1500&startTime={cur}")
        if not k:
            break
        rows.extend(k)
        time.sleep(0.09)          # ~11 req/s: under Binance's weight ceiling
        nxt = int(k[-1][0]) + 60_000
        if nxt <= cur:
            break
        cur = nxt
        if len(k) < 1500:
            break
    if not rows:
        return None
    return pd.DataFrame({
        "Date": pd.to_datetime([int(c[0]) // 1000 for c in rows], unit="s"),
        "Open": [float(c[1]) for c in rows], "High": [float(c[2]) for c in rows],
        "Low": [float(c[3]) for c in rows], "Close": [float(c[4]) for c in rows],
        "Volume": [float(c[5]) for c in rows]})

done = set(json.load(open(DONE))) if os.path.exists(DONE) else set()
out = open(ROWS, "a")
log(f"year-of-1m grid over {len(passing)} contracts")
for i, coin in enumerate(passing, 1):
    if coin in done:
        continue
    b = book.get(coin) or {}
    if "error" in b:
        done.add(coin); continue
    rt = 2 * (b["fee"] + b["spread"] / 2 + b["slippage"])
    usable = [(sl, tp) for sl, tp in BARRIERS if rt / tp < GATE_BLOCK]
    if not usable:
        done.add(coin); continue
    df = None
    for attempt in range(6):
        try:
            df = binance_year(coin)
            break
        except Exception as e:
            msg = str(e)
            transient = ("429" in msg or "418" in msg or "Too Many" in msg
                         or "timed out" in msg.lower() or "reset" in msg.lower())
            if not transient:
                log(f"  {coin} fetch failed permanently: {msg[:70]}")
                break
            wait = 20 * (attempt + 1)
            log(f"  {coin} rate limited, backing off {wait}s "
                f"(attempt {attempt+1}/6)")
            time.sleep(wait)
    if df is None:
        # NOT marked done: a coin lost to a rate limit must come back on the
        # next run rather than vanish from the result set unannounced.
        log(f"  {coin} SKIPPED this pass, will be retried")
        continue
    if df is None or len(df) < 20000:
        done.add(coin); continue
    days = (df["Date"].iloc[-1] - df["Date"].iloc[0]).days
    hi = [float(x) for x in df["High"]]
    lo = [float(x) for x in df["Low"]]
    cl = [float(x) for x in df["Close"]]
    dc = {}
    n = len(df); h = n // 2
    for sig, (sl, tp), sizing in itertools.product(SIGNALS, usable, SIZINGS):
        key = f"{sig}_by_1m"
        at.STRATEGY_SPECS[key] = {"interval": "Min1", "bar_seconds": 60,
                                  "tp": tp, "sl": sl, "threshold": THRESH}
        if sig not in dc:
            dc[sig] = at._dirs_for_backtest(key, hi, lo, cl)
        try:
            r = at.backtest_strategy(key, df, 5.0, fee=b["fee"],
                                     sizing=sizing, dirs=dc[sig])
        except Exception:
            continue
        if r["trades"] < MIN_TRADES or r["profit"] <= 0:
            continue
        a = at.backtest_strategy(key, df.iloc[:h], 5.0, fee=b["fee"],
                                 sizing=sizing, dirs=dc[sig][:h])
        z = at.backtest_strategy(key, df.iloc[h:], 5.0, fee=b["fee"],
                                 sizing=sizing, dirs=dc[sig][h:])
        m = r["monthly"]
        out.write(json.dumps({
            "coin": coin, "tf": "1m", "source": "binance", "signal": sig,
            "sl": sl * 100, "tp": tp * 100, "sizing": sizing,
            "lev": at.LEVERAGE, "margin": 5.0, "notional": 100.0,
            "fee": b["fee"] * 100, "rt_cost": rt * 100,
            "cost_of_tp": rt / tp * 100, "days": days, "bars": n,
            "agree_pct": agree[coin]["median_pct"],
            "trades": r["trades"], "wins": r["wins"],
            "losses": r["trades"] - r["wins"],
            "winrate": round(100 * r["wins"] / max(1, r["trades"]), 1),
            "profit": round(r["profit"], 2),
            "h1": round(a["profit"], 2), "h2": round(z["profit"], 2),
            "green": sum(1 for v in m.values() if v > 0), "months": len(m),
            "worst_month": round(min(m.values()), 2) if m else 0,
            "worst_trade": round(r["worst_trade"], 2),
            "max_dd": round(r["max_dd"], 2),
        }) + "\n")
    out.flush()
    done.add(coin)
    json.dump(sorted(done), open(DONE, "w"))
    if i % 5 == 0:
        log(f"  {i}/{len(passing)} contracts | rows "
            f"{sum(1 for _ in open(ROWS))}")
out.close()
log("DONE binance 1m year")
