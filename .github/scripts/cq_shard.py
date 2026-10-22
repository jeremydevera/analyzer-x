"""One GitHub machine of the CONFLUENCE RESEARCH (Prompt 1, Oct 21, 2026).

The operator: "I want you to reasearch confluence for each coins and each time
frame, my goal is 2:1R", their approved Prompt 1 (research/cq/prompts.md), and
"then start the prompt ... instead of waiting for me, use supwerpower to
decide the recommended". Design:
docs/superpowers/specs/2026-10-21-confluence-research-design.md.

For every claimed coin and every timeframe the search (tradingagents/cq_core)
looks for the combination of building blocks (tradingagents/signals_cq,
prefix cq_) and the stop/target that win most often in the worst case, per
payout (2:1, 3:1, 4:1, 5:1 after the coin's usual round trip). Every
candidate is measured by the nightly grid's own function
(`sweep_shard.run_pair` -> `backtest_strategy`: minute exits over the whole
window, the order book of each minute where one exists, the runner's
refusals) over a deep window, and ONE walk gives the three stretches by the
day each trade CLOSED: tuning (the oldest), check, and test (the newest),
which the search never reads.

The luck bar: on the coins in LUCK ("all", or a list), the same search over
seeded random entries (cq_rn...), chosen the same way.

Outputs (artifacts), rewritten after every coin so a machine stopped at the
6-hour limit still hands over what it finished:
* out/cq-<N>.json.gz - per coin: what the coin is, and per timeframe the
  search (and the luck search): seed, space, candidates tried, why it
  stopped, the round curve, each round's best 10, every payout's pick and
  the final pick, each pick measured again with every trade kept;
* out/cq-report-<N>.json - per coin + timeframe: seconds and candidates, or
  why it was skipped, or the error.
"""
# ruff: noqa: E402  (the imports must follow the RES/MODE/DAYS environment below)
from __future__ import annotations

import gzip
import io
import json
import math
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.environ["RES"] = "1m"
os.environ["MODE"] = "full"
# the per-minute order book is read for the newest BOOK_DAYS (+2): an older
# trade pays the coin's usual cost and is counted cost_unmeasured
BOOK_DAYS = 45
os.environ["DAYS"] = str(BOOK_DAYS)

import check_run as cr
import numpy as np
import pandas as pd
import sweep_shard as ss

import tradingagents.auto_trader as at
from tradingagents import backtest_report as br, cq_core as cq, signals_cq as sq, venue as _venue
from tradingagents.dataflows import exchange as fx

HISTORY = {"15m": 365, "30m": 365, "1h": 365, "4h": 730, "1d": 1095}
CHECK_DAYS = {"15m": 60, "30m": 60, "1h": 60, "4h": 120, "1d": 180}
TEST_DAYS = {"15m": 120, "30m": 120, "1h": 120, "4h": 240, "1d": 365}
BARS_PER_DAY = {"15m": 96, "30m": 48, "1h": 24, "4h": 6, "1d": 1}
MIN_TUNE_DAYS = 30
MAX_SL = 0.02                       # the rooms' stop cap
TFS = [t.strip() for t in (os.environ.get("TFS") or "15m,30m,1h,4h,1d").split(",")
       if t.strip() in HISTORY]
_S = [int(x) for x in (os.environ.get("SEARCH") or "500,100,10").split(",") if x.strip()]
ROUND_SIZE, MAX_ROUNDS, PATIENCE = (_S + [500, 100, 10][len(_S):])[:3]
MIN_TRADES = int(os.environ.get("MIN_TRADES") or cq.MIN_TUNE_TRADES)   # tests only
LUCK = (os.environ.get("LUCK") or "").strip()
LUCK_COINS = ({c.strip().upper().replace("_USDT", "") for c in LUCK.split(",") if c.strip()}
              if LUCK.lower() != "all" else set())
OUT = os.path.join("out", f"cq-{ss.SHARD}.json.gz")
REPORT_OUT = os.path.join("out", f"cq-report-{ss.SHARD}.json")
COIN_RETRIES = 2
PAIR_RETRIES = 2                 # a failed coin + timeframe is redone BY ITSELF
RETRY_CUTOFF_S = 4.8 * 3600      # no retry starts after this (runners die at 6 h)
DEADLINE_S = 5.6 * 3600          # a search still running stops its rounds here
STATS_BEFORE_DAYS = max(TEST_DAYS.values())   # a coin's numbers come from before every
                                              # timeframe's test days, whatever was dispatched
DAY_MS = 86_400_000
T0 = time.time()
STORE: dict = {}


def whole_days(tf: str) -> int:
    """A window longer than everything measured: its count is every trade."""
    return HISTORY[tf] + 400


def lucky(coin: str) -> bool:
    return LUCK.lower() == "all" or coin in LUCK_COINS


def frame(sym: str, tf: str, end_s: int | None = None):
    """The deep window of one timeframe, closed candles only, with the 300
    candles of lead-in the rules read: (whole frame, measured window, lead-in
    candles). A coin younger than the window has less lead-in, never one
    made up."""
    iv, bs, _cap = br.TFS[tf]
    need = HISTORY[tf] * BARS_PER_DAY[tf] + ss.WARMUP_BARS + 20
    if end_s is not None:
        need += int(max(0, time.time() - end_s) // bs) + 2
    df = at._closed_bars(fx.klines(sym, iv, need), bs)
    if end_s is not None and len(df):
        df = df[df["Date"] <= pd.Timestamp(int(end_s), unit="s")].reset_index(drop=True)
    if not len(df):
        return df, df, 0
    cut = df["Date"].iloc[-1] - pd.Timedelta(days=HISTORY[tf])
    measured = int((df["Date"] > cut).sum())
    warm = min(ss.WARMUP_BARS, len(df) - measured)
    dfw = df.iloc[len(df) - measured - warm:].reset_index(drop=True)
    return df, dfw, warm


def barriers_for(tf: str, c: float, liq) -> tuple[list, list]:
    """The grid's own stop/targets (br.pairs_for) a candidate may use: stop 2%
    or less and inside 80% of the liquidation distance (run_pair's own rule
    for a research name), target above the stop, paying at least 2:1 after
    the coin's usual round trip `c`. (stop/targets, the payout of each)."""
    out, ks = [], []
    for sl, tp in br.pairs_for(tf):
        if sl > MAX_SL + 1e-12 or tp <= sl:
            continue
        if liq is not None and sl * 100 >= 0.8 * abs(float(liq)):
            continue
        k = cq.bucket(cq.payout_of(sl, tp, c))
        if k is not None:
            out.append((sl, tp))
            ks.append(k)
    return out, ks


def stats_from(r: dict, tf: str, errors: list | None = None) -> cq.Stats:
    """The engine's window counts (the trades that CLOSED in the last W days)
    cut into the three stretches: tuning = whole - (test + check), check =
    (test + check) - test, test = the last test days."""
    rec = r.get("recents") or {}

    def part(d):
        x = rec.get(d) or rec.get(str(d)) or {}
        return cq.Part(int(x.get("trades") or 0), int(x.get("wins") or 0),
                       float(x.get("profit") or 0.0), float(x.get("rt_sum") or 0.0))

    t = part(TEST_DAYS[tf])
    tc = part(TEST_DAYS[tf] + CHECK_DAYS[tf])
    w = part(whole_days(tf))
    if errors is not None and w.trades != int(r.get("trades") or 0):
        errors.append(f"the whole window counted {w.trades} trades, the engine {r.get('trades')}")
    return cq.Stats(cq.minus(w, tc), cq.minus(tc, t), t)


def measure(sym: str, tf: str, fr, pre: dict, want: dict, errors: list) -> dict:
    """Each name in `want` at ITS OWN stop/targets, through the nightly grid's
    own function: {(name, sl, tp): the engine's result}. run_pair asks
    br.pairs_for(tf) once per name, right after it reads that name's signals
    (at._dirs_for_backtest), which is how the name being measured is known."""
    df, dfw, warm = fr
    tdays = TEST_DAYS[tf]
    got: dict = {}
    current: list = [None]
    engine, dirs_fn = at.backtest_strategy, at._dirs_for_backtest

    def keep(*a, **kw):
        key = (str(a[0]).rsplit("_gh_", 1)[0], round(float(kw["sl"]), 6),
               round(float(kw["tp"]), 6))
        try:
            r = engine(*a, **kw)
        except Exception as exc:                               # noqa: BLE001
            errors.append(f"{key}: {type(exc).__name__}: {str(exc)[:120]}")
            raise
        got[key] = r
        return r

    def dirs(key, *a, **kw):
        current[0] = str(key).rsplit("_gh_", 1)[0]
        try:
            return dirs_fn(key, *a, **kw)
        except Exception as exc:                               # noqa: BLE001
            # run_pair skips a name whose signals raise; counted here, so a
            # broken rule is an error on the page, never a quiet "no trade"
            errors.append(f"{current[0]} signals: {type(exc).__name__}: {str(exc)[:120]}")
            raise

    saved = (ss.window, br.pairs_for, at.backtest_strategy, at._dirs_for_backtest,
             br.SHORT_DAYS, br.RECENT_WINDOWS)
    ss.window = lambda _df: (dfw, warm)
    br.pairs_for = lambda _tf: list(want.get(current[0], ()))
    at.backtest_strategy = keep
    at._dirs_for_backtest = dirs
    br.SHORT_DAYS = (tdays, tdays + CHECK_DAYS[tf], whole_days(tf))
    br.RECENT_WINDOWS = br.SHORT_DAYS + (br.RECENT_DAYS,)
    try:
        ss.run_pair(sym, tf, io.StringIO(), signals=list(want), learned={**pre, "df": df})
    finally:
        (ss.window, br.pairs_for, at.backtest_strategy, at._dirs_for_backtest,
         br.SHORT_DAYS, br.RECENT_WINDOWS) = saved
    return got


def evaluator(sym: str, tf: str, fr, pre: dict, entries: list, bars: list, errors: list):
    """The search's `evaluate`: one run_pair call per round, each entry at the
    stop/targets the round asked of it."""
    def evaluate(cands):
        want: dict = {}
        for e, b in cands:
            want.setdefault(entries[e], []).append(bars[b])
        got = measure(sym, tf, fr, pre, want, errors)
        out = {}
        for e, b in cands:
            sl, tp = bars[b]
            r = got.get((entries[e], round(sl, 6), round(tp, 6)))
            out[(e, b)] = stats_from(r, tf, errors) if r and r.get("trades") else None
        return out
    return evaluate


ROW_KEEP = ("trades", "wins", "losses", "profit", "streak", "streak_len", "dd", "worst",
            "green", "months", "monthly", "rt_paid", "gate_blocked", "cost_unmeasured",
            "chase_skip", "closed_skipped", "unclear", "funding", "days", "bars", "last_ms")


def picked(sym: str, tf: str, fr, pre: dict, name: str, bar, st: cq.Stats) -> dict:
    """One pick measured again with every trade kept (check_run.verify_pair:
    the same function over the same bars): its row and its trades as [entry
    ms, exit ms, side, why, profit $, round trip %]; `drift` names a trade
    count that is not the search's (it must never be)."""
    df, dfw, warm = fr
    sl, tp = bar
    cfg = {"key": f"{name}:{tf}:{sl * 100:g}:{tp * 100:g}", "name": name, "tf": tf,
           "sl": sl * 100, "tp": tp * 100, "barrier": bar}
    lines = cr.verify_pair(sym, tf, df, pre, [cfg], window=lambda _df: (dfw, warm))
    if not lines:
        return {"row": None, "trades": [], "drift": "no trade when measured again"}
    ln = lines[0]
    out = {"row": {k: ln["row"].get(k) for k in ROW_KEEP}, "trades": ln["trades"]}
    n = st.tun.trades + st.chk.trades + st.tst.trades
    if int(ln["row"].get("trades") or 0) != n:
        out["drift"] = f"{ln['row'].get('trades')} trades measured again, {n} in the search"
    return out


def run_search(sym: str, tf: str, fr, pre: dict, entries: list, bars: list, ks: list,
               c_usual: float, seed: int, deadline: float) -> dict:
    """One search (the real one, or the luck one over random entries) and
    what it found, written by name."""
    errors: list = []
    evaluate = evaluator(sym, tf, fr, pre, entries, bars, errors)
    pool = set(entries)
    ix = {n: k for k, n in enumerate(entries)}
    near: dict = {}

    def neighbours_of(e):
        if e not in near:
            near[e] = [ix[n] for n in sq.neighbours(entries[e], pool)]
        return near[e]

    t1 = time.time()
    res = cq.search(len(entries), bars, ks, evaluate, seed=seed, neighbours_of=neighbours_of,
                    c_usual=c_usual, round_size=ROUND_SIZE, max_rounds=MAX_ROUNDS,
                    patience=PATIENCE, min_trades=MIN_TRADES, deadline=deadline)
    st = res["stats"]

    def row(cd):
        e, b = cd
        s = st[cd]
        return [entries[e], round(bars[b][0] * 100, 4), round(bars[b][1] * 100, 4), ks[b],
                list(s.tun), list(s.chk), list(s.tst)]

    picks = {str(k): {"cand": row(cd), "trades": picked(sym, tf, fr, pre, entries[cd[0]],
                                                        bars[cd[1]], st[cd])}
             for k, cd in sorted(res["picks"].items())}
    return {"seed": seed, "entries": len(entries), "space": res["space"], "tried": res["tried"],
            "stop": res["stop"], "seconds": round(time.time() - t1, 1),
            "n_errors": len(errors), "errors": errors[:20],
            "rounds": [{"n": rd["n"], "tried": rd["tried"],
                        "best": [row(cd) for cd in rd["best"]],
                        "champ": {str(k): row(cd) for k, cd in sorted(rd["champ"].items())}}
                       for rd in res["rounds"]],
            "picks": picks, "final": str(res["final"][0]) if res["final"] else None}


def cq_pair(sym: str, tf: str, pre: dict, rec: dict) -> dict:
    """The search (and on a luck coin the random search) on one coin +
    timeframe. The record reaches the coin only once the whole pair
    finished: a pair that raises leaves nothing behind and is redone by
    itself."""
    coin = sym.replace("_USDT", "")
    fr = frame(sym, tf)
    _df, dfw, warm = fr
    if not len(dfw) or len(dfw) - warm < br.min_bars(tf):
        return {"why": f"only {max(0, len(dfw) - warm)} measurable candles"}
    days = int((dfw["Date"].iloc[-1] - dfw["Date"].iloc[warm]).days)
    if days < TEST_DAYS[tf] + CHECK_DAYS[tf] + MIN_TUNE_DAYS:
        return {"why": f"only {days} days: {MIN_TUNE_DAYS}+ tuning days must come before the "
                       f"{CHECK_DAYS[tf]} check and {TEST_DAYS[tf]} test days"}
    c_usual = br.round_trip_cost(pre["fee"], {"slippage": pre["slip"]})
    bars, ks = barriers_for(tf, c_usual, pre["liq"])
    if not bars:
        return {"why": "no stop/target pays 2:1 at this coin's usual round trip"}
    deadline = T0 + DEADLINE_S
    out = {"days": days, "first": int(dfw["Date"].iloc[warm].timestamp()),
           "last": int(dfw["Date"].iloc[-1].timestamp()), "c": round(c_usual * 100, 4),
           "barriers": [[round(sl * 100, 4), round(tp * 100, 4), k]
                        for (sl, tp), k in zip(bars, ks, strict=True)]}
    entries = sq.entries_for(tf, _venue.kind(sym))
    out["search"] = run_search(sym, tf, fr, pre, entries, bars, ks, c_usual,
                               cq.seed_of(coin, tf, sq.VERSION), deadline)
    if lucky(coin):
        out["luck"] = run_search(sym, tf, fr, pre, sq.random_entries(), bars, ks, c_usual,
                                 cq.seed_of(coin, tf, sq.VERSION, "luck"), deadline)
    rec["tfs"][tf] = out
    s = out["search"]
    return {"entries": len(entries), "tried": s["tried"], "rounds": len(s["rounds"]),
            "stop": s["stop"], "days": days, "last": out["last"],
            **({"luck_tried": out["luck"]["tried"]} if "luck" in out else {})}


def usual_slip(book: dict) -> float | None:
    """A coin's usual one-side cost: the median of its recorded minutes' buy
    and sell costs (never one live reading). None when nothing was recorded."""
    if book is None or not len(book.get("t", [])):
        return None
    ok = ~np.asarray(book["exhausted"], dtype=bool)
    if not ok.any():
        return None
    both = (np.asarray(book["buy"], dtype=float)[ok]
            + np.asarray(book["sell"], dtype=float)[ok]) / 2
    both = both[np.isfinite(both)]
    return float(np.median(both)) if len(both) else None


def prefetch(sym: str, days: int, meta: dict | None = None) -> dict:
    """One coin's fee, liquidation distance, funding (Gate serves 180 days),
    minute order book for the newest BOOK_DAYS, the usual cost every older
    trade pays, and the finest bars for the whole `days` (every exit settled
    by the minute; a candle with no minute under it settles by the candle's
    own rule). `meta` replays an earlier run's choices."""
    from tradingagents import cost_store

    now = int(time.time())
    meta = dict(meta or {})
    fee = float(meta["fee"]) if meta.get("fee") is not None else at.taker_fee(sym, fx=fx)
    liq = (float(meta["liq"]) if meta.get("liq") is not None
           else fx.liquidation_move_pct(sym, at.LEVERAGE))
    fund = fx.funding_history(sym)
    fine_from = int(meta.get("fine_from") or now - (days + 2) * 86400)
    book_lo = int(meta.get("book_lo") or now - (BOOK_DAYS + 2) * 86400)
    book_hi = int(meta.get("book_hi") or now)
    try:
        book = cost_store.with_app_books(sym, cost_store.book_for(sym, book_lo, book_hi),
                                         book_lo, book_hi)
    except Exception as exc:                                   # noqa: BLE001
        ss.log(f"{sym}: the per-minute costs could not be read ({exc}); every trade pays "
               f"the usual cost and is counted unmeasured")
        book = cost_store.empty()
    ss.COST_BOOKS[sym] = book            # run_pair's cost_book(sym) reads this one
    slip = meta.get("slip")
    source = meta.get("slip_source")
    if slip is None:
        slip = usual_slip(book)
        source = "median of the recorded minutes"
        if slip is None:
            live = fx.book_cost(sym, ss.BASE_MARGIN * at.LEVERAGE)
            slip = br.charged_slippage([float(live.get("slippage") or 0.0) or 0.0003])
            source = "one live reading (no minutes recorded)"
    _t, _h, _l, n5 = br.fine_bars(sym, fine_from, fx=fx)
    return {"fee": fee, "liq": liq, "fund": fund, "slip": float(slip), "fine": (_t, _h, _l),
            "meta": {"fine_from": fine_from, "book_lo": book_lo, "book_hi": book_hi,
                     "fee": fee, "liq": liq, "slip": float(slip), "slip_source": source,
                     "minutes": len(_t), "five_minute": int(n5 or 0)}}


_BTC: dict = {}


def coin_stats(sym: str, pre: dict, before_days: int) -> dict:
    """What the coin IS, measured on its 1h candles in the year BEFORE every
    timeframe's test days (no look-ahead into the days a pick is judged on):
    daily volatility and trending vs. snapping back decide its group in the
    second stage; its usual cost and its correlation with BTC ride beside."""
    hours = (before_days + 2 + 365) * 24 + 40
    df = at._closed_bars(fx.klines(sym, "Min60", hours), 3600)
    if len(df) < 200:
        return {"why": f"only {len(df)} hourly candles"}
    ts = df["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
    keep = ts < int(ts[-1]) - (before_days + 2) * DAY_MS
    c = df["Close"].to_numpy(dtype=float)[keep]
    if len(c) < 200:
        return {"why": f"only {len(c)} hourly candles before the test days"}
    r = np.diff(np.log(c))
    var1 = float(np.var(r))
    r24 = np.log(c[24:] / c[:-24])
    vr = float(np.var(r24) / (24 * var1)) if var1 > 0 else math.nan
    out = {"vol": round(float(np.std(r)) * math.sqrt(24) * 100, 3), "vr": round(vr, 3),
           "kind": _venue.kind(sym), "hours": int(len(c)),
           "cost": round(br.round_trip_cost(pre["fee"], {"slippage": pre["slip"]}) * 100, 4)}
    try:
        if "t" not in _BTC:
            b = at._closed_bars(fx.klines("BTC_USDT", "Min60", hours), 3600)
            _BTC["t"] = b["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
            _BTC["c"] = b["Close"].to_numpy(dtype=float)
        _common, ia, ib = np.intersect1d(ts[keep], _BTC["t"], return_indices=True)
        if len(ia) > 200:
            ra, rb = np.diff(np.log(c[ia])), np.diff(np.log(_BTC["c"][ib]))
            out["btc_corr"] = round(float(np.corrcoef(ra, rb)[0, 1]), 3)
    except Exception as exc:                                   # noqa: BLE001
        out["btc_corr_error"] = str(exc)[:120]
    return out


def save_json(path: str, obj) -> None:
    os.makedirs("out", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, separators=(",", ":"), default=str)
    os.replace(tmp, path)


def save_out() -> None:
    """Every coin this machine finished, in one file swapped whole."""
    os.makedirs("out", exist_ok=True)
    tmp = OUT + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump({"version": sq.VERSION, "tfs": TFS, "history": HISTORY,
                   "check": CHECK_DAYS, "test": TEST_DAYS,
                   "search": {"round_size": ROUND_SIZE, "max_rounds": MAX_ROUNDS,
                              "patience": PATIENCE, "min_trades": MIN_TRADES},
                   "luck": LUCK, "base": ss.BASE_MARGIN, "lev": at.LEVERAGE,
                   "coins": STORE}, fh, separators=(",", ":"), default=str)
    os.replace(tmp, OUT)


def late() -> bool:
    """No retry starts this late: a runner is killed at 6 hours."""
    return time.time() - T0 > RETRY_CUTOFF_S


def run(per_coin) -> int:
    """Claim coins off the board one at a time; a coin that raises is tried
    again by itself up to COIN_RETRIES (never past the cutoff), then named."""
    os.makedirs("out", exist_ok=True)
    coins = ss.eligible()
    ss.report.board = len(coins)
    report: list = []
    failed: dict = {}
    done = 0
    stream = ss.coin_stream(coins, T0)
    queue: list = []
    while True:
        sym = next(stream, None)
        if sym is None:
            if not queue or late():
                for q in queue:
                    report.append({"coin": q.replace("_USDT", ""), "tf": "*",
                                   "error": "not redone: out of time"})
                break
            sym = queue.pop(0)
        try:
            per_coin(sym, report, done, len(coins))
            done += 1
        except Exception as exc:                               # noqa: BLE001
            n = failed.get(sym, 0) + 1
            failed[sym] = n
            ss.log(f"{sym}: FAILED ({type(exc).__name__}: {exc}) try {n}")
            if n <= COIN_RETRIES:
                queue.append(sym)
            else:
                report.append({"coin": sym.replace("_USDT", ""), "tf": "*",
                               "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
        save_json(REPORT_OUT, {"report": report, "tfs": TFS, "history": HISTORY})
        ss.report("testing", done, len(coins), note=f"{sym.replace('_USDT', '')} done")
    ss.log(f"done: {done} coin(s) in {(time.time() - T0) / 60:.0f} min")
    return 0


def each_tf(coin: str, tfs, work, report: list) -> None:
    """Run `work(tf) -> dict` for every timeframe; one that raises is redone BY
    ITSELF after the others, up to PAIR_RETRIES (CLAUDE.md: a failed coin is
    redone alone), and named if it never recovers."""
    pending = list(tfs)
    for attempt in range(PAIR_RETRIES + 1):
        again = []
        for tf in pending:
            t1 = time.time()
            entry = {"coin": coin, "tf": tf}
            try:
                entry.update(work(tf))
            except Exception as exc:                           # noqa: BLE001
                entry["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
                ss.log(f"{coin} {tf}: FAILED (try {attempt + 1}) {entry['error']}")
                ss.log(traceback.format_exc()[-800:])
                if attempt < PAIR_RETRIES and not late():
                    again.append(tf)
                    continue
            entry["seconds"] = round(time.time() - t1, 1)
            if attempt:
                entry["tries"] = attempt + 1
            report.append(entry)
            ss.log(f"{coin} {tf}: {entry.get('tried', '-')} tried, "
                   f"{entry.get('why') or entry.get('error') or entry.get('stop')} "
                   f"in {entry['seconds']}s")
        if not again:
            return
        time.sleep(5 * (attempt + 1))
        pending = again


def measure_coin(sym: str, report: list, done: int, total: int) -> None:
    """One coin: its costs, what it is, then every timeframe - each one saved
    the moment it finishes, so a machine killed in the middle of a coin still
    hands over the timeframes it finished (review, Oct 22, 2026)."""
    coin = sym.replace("_USDT", "")
    pre = prefetch(sym, max(HISTORY[t] for t in TFS))
    rec = {"coin": coin, "kind": _venue.kind(sym), "pre": pre["meta"], "tfs": {}}
    try:
        rec["stats"] = coin_stats(sym, pre, STATS_BEFORE_DAYS)
    except Exception as exc:                                   # noqa: BLE001
        rec["stats"] = {"error": f"{type(exc).__name__}: {str(exc)[:160]}"}
    STORE[coin] = rec

    def work(tf):
        got = cq_pair(sym, tf, pre, rec)
        save_out()
        return got

    each_tf(coin, TFS, work, report)
    save_out()


def search() -> int:
    ss.log(f"confluence research: timeframes {TFS}, rounds of {ROUND_SIZE} up to "
           f"{MAX_ROUNDS}, patience {PATIENCE}, luck "
           f"{'every coin' if LUCK.lower() == 'all' else f'{len(LUCK_COINS)} coin(s)'}")

    return run(measure_coin)


def main() -> int:
    return search()


if __name__ == "__main__":
    raise SystemExit(main())
