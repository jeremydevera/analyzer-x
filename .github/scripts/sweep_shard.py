"""One shard of the market sweep, for a GitHub runner.

Public data only — candles, funding, order book, contract detail. No API key is
read and none is needed, which is why this can run on someone else's machine.

WORK IS CLAIMED, NOT SLICED. The shards used to take a fixed slice each
(`syms[SHARD::SHARDS]`) and exit when it was done; on run 34004227228
(Sep 06, 2026) four machines sat idle 12-21 minutes while the slowest was at
30 of 52 coins, because the slices are equal in COUNT but not in WORK — a 15m
coin with three years of history costs many times a young 4h coin. The
operator: *"did not i mentioned if the machine is 100% take a new job"*.

Each shard now claims ONE COIN at a time from a shared board on the
sweep-progress branch (progress.ClaimBoard — an atomic create per coin, so no
coin can be measured twice) and keeps claiming until the board is empty. The
run ends when the WORK ends, not when the unluckiest slice does. Without a
token (local runs, tests) it falls back to the old static slice.
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
from tradingagents.positions_view import fmt_when  # noqa: E402

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
# The operator's stake, sent by the dispatch. It was hardcoded at 5.0 while
# the local job took `base` from the Backtest screen, so after the move to
# GitHub (Sep 05, 2026) every dollar figure would have been measured at a
# stake nobody chose. Same default as before when the input is absent.
BASE_MARGIN = float(os.environ.get("BASE_MARGIN") or 5.0)
GATE_BLOCK = 0.50

OUT = os.path.join("out", f"rows-{SHARD}.jsonl")
os.makedirs("out", exist_ok=True)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from progress import ClaimBoard, Reporter  # noqa: E402

report = Reporter()
board = ClaimBoard()

# Stop CLAIMING here, even though the hard stop is later: the last claimed coin
# still has to finish and upload before GitHub kills the runner at six hours.
CLAIM_CUTOFF_S = 4.8 * 3600

# A retried pair is not re-attempted inside this many seconds of its failure.
# The old design queued every pair up front, so a retry landed minutes later,
# behind the whole slice; claiming one coin at a time can bring it back around
# in SECONDS — straight into the same venue blip, burning both redos on one
# outage. The pair prefers to WAIT BEHIND other work (the queue rotates), and
# only sleeps when there is nothing else left to do.
RETRY_COOLDOWN_S = 30.0


def log(msg):
    print(f"[shard {SHARD}] {msg}", flush=True)


def eligible():
    """The WHOLE market's contracts, sorted — the same list on every shard.

    No slice here any more: the claim board decides who measures what, one
    coin at a time. The MIN_DAYS age screen moved to `old_enough`, checked per
    CLAIMED coin — screening the whole list per shard would be ~1,000 Day1
    fetches times twenty machines for coins most shards will never touch."""
    raw = fx._get_public(f"{fx.BASE}/api/v1/contract/detail").get("data") or []
    syms = sorted(x["symbol"] for x in raw
                  if str(x.get("symbol", "")).endswith("_USDT")
                  and int(x.get("state", 1)) == 0)
    log(f"{len(syms)} contracts on the board")
    return syms


def old_enough(sym):
    """The MIN_DAYS screen, for ONE claimed coin.

    A coin whose age check RAISES is kept, not dropped. It used to be dropped,
    so one timeout deleted a contract from the sweep with nothing but a log
    line to say so — the row's own `days` column is the honest place to report
    a short history, not silent removal from the search."""
    if MIN_DAYS <= 0:
        return True
    try:
        d = fx.klines(sym, "Day1", 500)
        return (d["Date"].iloc[-1] - d["Date"].iloc[0]).days >= MIN_DAYS
    except Exception as exc:
        log(f"{sym}: age check failed ({str(exc)[:50]}), keeping it anyway")
        return True


def coin_stream(coins, t0):
    """Yield the coins THIS shard measures: one claim at a time off the board.

    The walk starts at this shard's own region of the sorted list, so at the
    start the twenty shards claim in twenty different places and almost never
    race; a shard that finishes its region walks on into the next one — which
    is exactly the moment the old design went idle.

    Without a token (local runs, tests) it yields the old static slice, and
    ONLY then: a shard whose board breaks MID-RUN stops rather than guessing,
    because measuring a coin someone else owns writes the same rows twice and
    the collector appends duplicates.
    """
    if not board.enabled:
        mine = coins[SHARD::SHARDS]
        log(f"no claim board (no token) — static slice of {len(mine)}")
        yield from (mine[:PER_SHARD] if PER_SHARD else mine)
        return
    start = (SHARD * len(coins)) // SHARDS
    order = coins[start:] + coins[:start]
    # spread the first burst: twenty first-claims in the same second is
    # twenty commits racing one branch ref
    time.sleep((SHARD % SHARDS) * 0.7)
    seen_taken: set = set()
    claimed = 0
    dead = 0
    for sym in order:
        if PER_SHARD and claimed >= PER_SHARD:
            log(f"COINS cap reached ({PER_SHARD}) — stopping")
            return
        if time.time() - t0 > CLAIM_CUTOFF_S:
            log("claim cutoff reached — finishing what is queued, "
                "claiming nothing new so the artifact survives the 6h kill")
            return
        if sym in seen_taken:
            continue
        # refresh the board over git (free) so a taken coin costs no API call;
        # the PUT's own 422 is still the real lock for the race window
        seen_taken |= board.taken()
        if sym in seen_taken:
            continue
        got = board.claim(sym)
        if got is None:
            # Unreachable is not the same as contended. One dead answer skips
            # ONE coin (someone else probably has it anyway); three in a row is
            # a network that is actually down, and then the shard stops with
            # what it measured rather than risking a double-measured coin.
            dead += 1
            if dead >= 3:
                log("the claim board is unreachable (3 coins in a row) — "
                    "stopping with what is measured rather than risking a "
                    "double-measured coin")
                return
            log(f"claim of {sym} got no answer — skipping it, not stopping")
            continue
        dead = 0
        if not got:
            seen_taken.add(sym)
            continue
        claimed += 1
        yield sym


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
           # WITH THE DATES. The tile said "18,959 bars, testing 120 rules"
           # and the operator could not answer their own question about it:
           # "i dont see what dates are being tested like is aug 3 - sept 27
           # being tested?" (2026-09-09). The span is THIS PAIR's real first
           # and last bar after the window cut — a young coin's span is
           # honestly shorter — via the one date formatter (CLAUDE.md).
           note=(f"{coin} {tf}: {nbars:,} bars · "
                 f"{fmt_when(df['Date'].iloc[0].timestamp())} → "
                 f"{fmt_when(df['Date'].iloc[-1].timestamp())} · "
                 f"{len(br.SIGNALS)} rules"))
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
    # ONE MARKER PER MEASURED PAIR, rows or no rows. A thin coin whose every
    # combination fell under the trade floor wrote NOTHING, so the collect
    # could never know it was measured: ROAM_USDT 15m (35,764 bars) survived
    # two whole-market sweeps on Sep 06, 2026 and stayed "pending" — every
    # future run re-measured it for nothing. The marker carries the same
    # coin/tf keys as a row so the collector's pair grouping sees it, and
    # last_ms so the pair gets a real watermark.
    lines.append(json.dumps({"coin": coin, "tf": tf, "pair_done": True,
                             "last_ms": int(ts[-1]) if len(ts) else 0,
                             "rows": kept, "bars": nbars}) + "\n")
    out.write("".join(lines))
    out.flush()
    return kept


def main():
    from collections import deque

    t0 = time.time()
    coins = eligible()
    log(f"window: last {DAYS} days (+30 lookback), floors {br.MIN_BARS}")
    total, redos, young = 0, 0, 0
    failed: list = []
    # The queue is PUMPED one claimed coin at a time — the next coin is only
    # claimed when the queue runs dry, so a shard never sits on coins it is
    # not measuring. A pair the venue failed still goes to the BACK and is
    # redone by itself; the other pairs keep going, the shard never restarts.
    stream = coin_stream(coins, t0)
    queue = deque()
    # Failed pairs wait HERE, not in the main queue: a retry runs only when
    # there is no fresh work left to claim — the same "after the others" the
    # up-front slice used to give it — so one venue blip is never re-entered
    # seconds later, burning both redos on the same outage.
    retries = deque()
    tries: dict = {}
    failed_at: dict = {}
    done_pairs = 0
    claimed = 0
    with open(OUT, "w") as out:
        while True:
            if not queue:
                sym = next(stream, None)
                if sym is not None:
                    if not old_enough(sym):
                        young += 1
                        log(f"{sym}: younger than {MIN_DAYS} days, screened out")
                        continue
                    claimed += 1
                    queue.extend((claimed, sym, tf) for tf in TFS)
                elif retries:
                    i2, s2, t2 = retries.popleft()
                    wait = RETRY_COOLDOWN_S - (time.time()
                                               - failed_at.get((s2, t2), 0.0))
                    if wait > 0:
                        time.sleep(wait)
                    queue.append((i2, s2, t2))
                else:
                    break
            i, sym, tf = queue.popleft()
            try:
                total += run_pair(sym, tf, out, i=i, n=claimed,
                                  rows_so_far=total)
                done_pairs += 1
            except PairFailed as exc:
                n = tries.get((sym, tf), 0)
                if n < PAIR_RETRIES:
                    tries[(sym, tf)] = n + 1
                    failed_at[(sym, tf)] = time.time()
                    redos += 1
                    log(f"{exc} · nothing written, redoing {n + 1}/{PAIR_RETRIES} "
                        f"after the others")
                    retries.append((i, sym, tf))
                    continue
                failed.append(f"{sym} {tf}: {exc}")
                done_pairs += 1
                log(f"{exc} · gave up after {PAIR_RETRIES} redos")
                # publish it NOW: a runner killed at six hours never reaches
                # the "done" report, and its named losses would die with it
                report("testing", done_pairs // len(TFS), claimed, rows=total,
                       note=f"{len(failed)} pair(s) lost so far",
                       force=True, failed=failed)
            el = time.time() - t0
            if tf == TFS[-1]:
                log(f"{i}/{claimed} {sym} · {total:,} rows · "
                    f"{el / 60:.0f} min elapsed · "
                    f"{el / max(1, done_pairs) * len(TFS) / 60:.1f} min/coin")
            # A runner is killed at six hours with no artifact, so stop early
            # and keep what has been measured.
            if el > 5.2 * 3600:
                log(f"stopping at {i}/{claimed} coins to protect the artifact")
                break
    report("done", claimed, claimed, rows=total,
           note=(f"{total:,} rows · {claimed} coin(s) claimed · {redos} pair "
                 f"redo(s) · {len(failed)} pair(s) lost"
                 + (f" · {young} younger than {MIN_DAYS}d" if young else "")),
           force=True, failed=failed)
    log(f"done: {total:,} rows in {(time.time() - t0) / 60:.0f} min · "
        f"{redos} redo(s) · lost: {failed or 'none'}")
    log("PARITY: every threshold and every row, winners and losers, exactly "
        "as market_sweep.run_pair measures them — a cloud pair and a local "
        "pair are the same measurement and can be compared row for row.")


if __name__ == "__main__":
    main()
