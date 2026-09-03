"""One shard of the market sweep, for a GitHub runner.

Public data only — candles, funding, order book, contract detail. No API key is
read and none is needed, which is why this can run on someone else's machine.

The shard picks its slice of the eligible contracts by index, so N runners cover
the market without talking to each other.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

import tradingagents.auto_trader as at  # noqa: E402
from tradingagents import (
    backtest_report as br,  # noqa: E402
    fast_grid as fg,  # noqa: E402
)
from tradingagents.dataflows import mexc_futures as fx  # noqa: E402

SHARD = int(os.environ.get("SHARD", "0"))
SHARDS = max(1, int(os.environ.get("SHARDS", "1")))
PER_SHARD = int(os.environ.get("COINS", "0"))
TFS = [t.strip() for t in os.environ.get("TFS", "15m,30m").split(",") if t.strip()]
MIN_DAYS = int(os.environ.get("MIN_DAYS", "0"))
# The history window, in days -- the same knob the Backtest screen sends the
# local job ("Previous 2 months" = 60). Default a year, as before.
DAYS = int(os.environ.get("DAYS", "365"))
# How many times ONE pair is redone before the shard gives up on it. The
# local sweep's rule (market_sweep.PAIR_RETRIES), and the operator's words on
# 2026-08-25: "if the backtest failed for certain coin make sure to stop the
# process for that specific coin and retry it". Never the whole shard.
PAIR_RETRIES = 2
BASE_MARGIN = 5.0
GATE_BLOCK = 0.50

OUT = os.path.join("out", f"rows-{SHARD}.jsonl")
os.makedirs("out", exist_ok=True)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from progress import Reporter  # noqa: E402

report = Reporter()


def log(msg):
    print(f"[shard {SHARD}] {msg}", flush=True)


def eligible():
    """Contracts at least MIN_DAYS old. Every shard screens the same list, in
    the same order, and then takes its own slice — cheap, and it needs no
    coordination between runners.

    MIN_DAYS = 0 means measure everything, and then the screen is skipped
    entirely: it would fetch a Day1 series per coin (about a thousand requests
    across twenty shards) only to keep every one of them.

    A coin whose age check RAISES is kept, not dropped. It used to be dropped,
    so one timeout deleted a contract from the sweep with nothing but a log
    line to say so — the row's own `days` column is the honest place to report
    a short history, not silent removal from the search."""
    raw = fx._get_public(f"{fx.BASE}/api/v1/contract/detail").get("data") or []
    syms = sorted(x["symbol"] for x in raw
                  if str(x.get("symbol", "")).endswith("_USDT")
                  and int(x.get("state", 1)) == 0)
    mine = syms[SHARD::SHARDS]
    log(f"{len(syms)} contracts, {len(mine)} in this shard")
    if MIN_DAYS <= 0:
        log(f"MIN_DAYS=0: no age screen, measuring all {len(mine)}")
        return mine[:PER_SHARD] if PER_SHARD else mine
    keep, young, unknown = [], 0, 0
    report("screening", 0, len(mine), note="checking contract ages", force=True)
    for i, sym in enumerate(mine, 1):
        try:
            d = fx.klines(sym, "Day1", 500)
            if (d["Date"].iloc[-1] - d["Date"].iloc[0]).days >= MIN_DAYS:
                keep.append(sym)
            else:
                young += 1
        except Exception as exc:
            log(f"{sym}: age check failed ({str(exc)[:50]}), keeping it anyway")
            keep.append(sym)
            unknown += 1
        report("screening", i, len(mine),
               note=f"{len(keep)} old enough so far")
        time.sleep(0.05)
    log(f"{len(keep)} kept ({unknown} age unknown), "
        f"{young} dropped as younger than {MIN_DAYS} days")
    return keep[:PER_SHARD] if PER_SHARD else keep


class PairFailed(Exception):
    """The venue failed this pair part-way. Nothing of it was written."""


def window(df):
    """The cut market_sweep.refresh_candles makes -- everything newer than
    DAYS+30 days ago -- so a cloud pair and a local pair see the same bars."""
    import pandas as pd

    cut = pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(days=DAYS + 30)
    return df[df["Date"] >= cut].reset_index(drop=True)


def run_pair(sym, tf, out, *, i=0, n=0, rows_so_far=0):
    """Measure one pair. Rows are BUFFERED and written only when the pair
    completes, so a pair that raises leaves nothing behind to mix with its
    redo. A venue failure raises PairFailed for main() to requeue."""
    iv, bs, cap = br.TFS[tf]
    report("testing", i, n, rows=rows_so_far,
           note=f"{sym.replace('_USDT', '')} {tf}: downloading candles")
    try:
        fee = at.taker_fee(sym, fx=fx)
        liq = fx.liquidation_move_pct(sym, at.LEVERAGE)
        fund = fx.funding_history(sym)
        book = fx.book_cost(sym, BASE_MARGIN * at.LEVERAGE)
        # ONE definition, shared with the local sweep — see
        # backtest_report.round_trip_cost for why spread/2 must not be added.
        rt = br.round_trip_cost(fee, book)
        df = at._closed_bars(fx.klines(sym, iv, cap), bs)
    except Exception as exc:
        raise PairFailed(f"{sym} {tf}: {str(exc)[:60]}") from exc
    df = window(df)
    # the shared floor (backtest_report.MIN_BARS), never a private 2000: that
    # rejected 1h at 60 days and 1d always, while the local sweep measured them
    if len(df) < br.min_bars(tf):
        log(f"{sym} {tf}: only {len(df)} bars, skipped")
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
    lines = []                  # written only when the pair completes
    # Once per frame, for fast_grid: funding as cumulative-rate arrays and
    # each bar's month as an index, so no trade ever formats a timestamp.
    f_ms, f_rate = [], []
    for f_ in sorted(fund or [], key=lambda d: d["settle_ms"]):
        f_ms.append(int(f_["settle_ms"]))
        f_rate.append(float(f_["rate"]))
    f_cum = [0.0]
    for r_ in f_rate:
        f_cum.append(f_cum[-1] + r_)
    mo_codes = df["Date"].to_numpy().astype("datetime64[M]")
    mo_labels, mo_seen, mo_idx = [], {}, []
    for v_ in mo_codes:
        k_ = mo_seen.get(v_)
        if k_ is None:
            k_ = mo_seen[v_] = len(mo_labels)
            mo_labels.append(str(v_)[:7])
        mo_idx.append(k_)
    report("testing", i, n, rows=rows_so_far,
           note=f"{coin} {tf}: {nbars:,} bars, testing {len(br.SIGNALS)} rules")
    for si, sig in enumerate(br.SIGNALS, 1):
        key = f"{sig}_gh_{tf}"
        # EVERY threshold, exactly as market_sweep.run_pair does with
        # thresholds=3. Taking only the middle one made the cloud grid a third
        # as wide as the Mac's for every momentum and fade rule, so a coin
        # measured here and the same coin measured locally were not the same
        # search — and the operator asked for a store they can trust.
        ths = br.THRESHOLDS[tf] if sig in br.THRESH_SIGNALS else [None]
        for th in ths:
            at.STRATEGY_SPECS[key] = {"interval": iv, "bar_seconds": bs, "tp": .02,
                                      "sl": .01,
                                      "threshold": .003 if th is None else th}
            try:
                dk = "rsi14_1h" if sig == "rsi14" else key
                dirs = at._dirs_for_backtest(dk, hi, lo, cl, opens=op, volume=vol,
                                             funding=fund,
                                             ts=ts)
            except Exception:
                at.STRATEGY_SPECS.pop(key, None)
                continue          # this threshold only, not the whole rule
            thp = 0.0 if th is None else round(th * 100, 3)
            # One walk per combination (fast_grid): sizing never moves an exit
            # and the halves derive from the full walk, so six engine runs
            # collapse into two walks — parity-pinned in tests/test_fast_grid.py.
            # ~3x more market per 6-hour runner.
            dirs_idx = [k2 for k2, v2 in enumerate(dirs) if v2]
            for (sl, tp) in br.pairs_for(tf):
                if liq is not None and sl * 100 >= liq:
                    continue
                if rt / tp >= GATE_BLOCK:
                    continue
                try:
                    six = fg.combo_six(
                        dirs_idx, dirs, op, hi, lo, cl, tp=tp, sl=sl,
                        liq=None if liq is None else abs(liq) / 100.0,
                        half=half, base=BASE_MARGIN, lev=at.LEVERAGE,
                        fee=fee + 0.0003, ladder=at.ladder_margin,
                        mo_idx=mo_idx, mo_labels=mo_labels,
                        f_ms=f_ms, f_cum=f_cum, bar_ms=ts)
                except Exception:
                    continue
                for sz in ("flat", "martingale"):
                    r = six[sz]["full"]
                    # EVERY row, winners and losers alike. This used to drop
                    # `profit <= 0 or trades < 100`, so a merged pair held only
                    # its profitable slice: "how many combinations were tested"
                    # became unanswerable, win/loss across the grid was
                    # meaningless, and a "profitable only" filter was a no-op
                    # because the losers were never written. The local sweep
                    # writes them; the cloud has to as well or the two stores
                    # are not the same measurement.
                    if not r["trades"]:
                        continue          # no trade at all is not a row
                    a = six[sz]["h1"]
                    b = six[sz]["h2"]
                    m = r["monthly"]
                    lines.append(json.dumps({
                        "coin": coin, "tf": tf, "signal": sig, "th": thp,
                        "sl": round(sl * 100, 3), "tp": round(tp * 100, 3),
                        "rr": round(tp / sl, 2), "sizing": sz, "lev": at.LEVERAGE,
                        "base": BASE_MARGIN, "notional": BASE_MARGIN * at.LEVERAGE,
                        "trades": r["trades"], "wins": r["wins"], "losses": r["losses"],
                        "winrate": (round(100 * r["wins"] / r["trades"], 2)
                                    if r["trades"] else 0.0),
                        "profit": round(r["profit"], 2),
                        "funding": round(r["funding_total"], 2),
                        "h1": round(a["profit"], 2), "h2": round(b["profit"], 2),
                        "green": r["months_green"], "months": r["months_total"],
                        "worst": round(r["worst_trade"], 2), "dd": round(r["max_dd"], 2),
                        # a cloud row and a local row sit side by side in the
                        # store, so the mandatory streak columns must match
                        "streak": round(r["worst_streak"], 2),
                        "streak_len": r["worst_streak_len"],
                        # honest when liquidation could not be read: unreachable
                        # stops are only screened out when liq is known
                        "liqs": r["liqs"], "stop_reachable": liq is not None,
                        "days": days,
                        # the last bar this pair was measured through, so the
                        # merge can record freshness instead of guessing
                        # int(), because ts comes from a numpy array and a
                        # numpy.int64 is not JSON serializable — every shard
                        # of run 32801805912 died on that at the first row it
                        # tried to write, 93 seconds in.
                        #
                        # And NO *1000: `ts` is already MILLISECONDS
                        # (datetime64[ms]). Multiplying gave 1787623200000000,
                        # a watermark a thousand times too large, which would
                        # have printed "measured through" a date in the year
                        # 58,000 and made every freshness comparison nonsense.
                        "last_ms": int(ts[-1]) if len(ts) else 0,
                        "bars": nbars, "monthly": {k: round(v, 2) for k, v in m.items()},
                        "cost_of_tp": round(rt / tp * 100, 1), "rt": round(rt * 100, 4),
                        "gate": "warn" if rt / tp >= .2 else "ok"}) + "\n")
                    kept += 1
        at.STRATEGY_SPECS.pop(key, None)
        report("testing", i, n, rows=rows_so_far + kept,
               note=f"{coin} {tf}: rule {si}/{len(br.SIGNALS)} ({sig})")
    out.write("".join(lines))
    out.flush()
    return kept


def main():
    from collections import deque

    t0 = time.time()
    coins = eligible()
    log(f"window: last {DAYS} days (+30 lookback), floors {br.MIN_BARS}")
    total, redos, failed = 0, 0, []
    # a queue, not a nested loop: a pair the venue failed goes to the BACK and
    # is redone by itself -- the other pairs keep going, the shard never restarts
    queue = deque((i, sym, tf) for i, sym in enumerate(coins, 1) for tf in TFS)
    tries: dict = {}
    with open(OUT, "w") as out:
        while queue:
            i, sym, tf = queue.popleft()
            try:
                total += run_pair(sym, tf, out, i=i, n=len(coins),
                                  rows_so_far=total)
            except PairFailed as exc:
                n = tries.get((sym, tf), 0)
                if n < PAIR_RETRIES:
                    tries[(sym, tf)] = n + 1
                    redos += 1
                    log(f"{exc} · nothing written, redoing {n + 1}/{PAIR_RETRIES} "
                        f"after the others")
                    queue.append((i, sym, tf))
                    continue
                failed.append(f"{sym} {tf}: {exc}")
                log(f"{exc} · gave up after {PAIR_RETRIES} redos")
                # publish it NOW: a runner killed at six hours never reaches
                # the "done" report, and its named losses would die with it
                report("testing", i, len(coins), rows=total,
                       note=f"{len(failed)} pair(s) lost so far",
                       force=True, failed=failed)
            el = time.time() - t0
            if tf == TFS[-1]:
                log(f"{i}/{len(coins)} {sym} · {total:,} rows · "
                    f"{el / 60:.0f} min elapsed · "
                    f"ETA {el / i * (len(coins) - i) / 60:.0f} min")
            # A runner is killed at six hours with no artifact, so stop early
            # and keep what has been measured.
            if el > 5.2 * 3600:
                log(f"stopping at {i}/{len(coins)} coins to protect the artifact")
                break
    report("done", len(coins), len(coins), rows=total,
           note=f"{total:,} rows · {redos} pair redo(s) · {len(failed)} pair(s) lost",
           force=True, failed=failed)
    log(f"done: {total:,} rows in {(time.time() - t0) / 60:.0f} min · "
        f"{redos} redo(s) · lost: {failed or 'none'}")
    log("PARITY: every threshold and every row, winners and losers, exactly "
        "as market_sweep.run_pair measures them — a cloud pair and a local "
        "pair are the same measurement and can be compared row for row.")


if __name__ == "__main__":
    main()
