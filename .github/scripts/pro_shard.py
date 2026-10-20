"""One GitHub machine of the PRO TRADER research (Oct 20, 2026).

The operator: "create different strategies for each coin ... think of your self
as a professional trader ... research on proven and working indicators", their
approved prompt (target at least 2:1 after fees), and "show me the results each
day per coin per time frame in artefact so i can review it if we can push to
prod". Design: docs/superpowers/specs/2026-10-20-pro-trader-research-design.md.

Every family in tradingagents/signals_pro.py (prefix pt_), every setting, at
the stop/targets that can pay 2:1 after fees, on every coin and timeframe, is
measured by the nightly grid's own function (`sweep_shard.run_pair` ->
`backtest_strategy`) over a DEEP window (15m/30m 180 days, 1h 365, 4h 730, 1d
1,095). The engine is asked for the trades that CLOSED in the last 30/60/90/120
days (br.SHORT_DAYS, set to those in THIS process only), so each row carries
four test months plus everything before them, from one walk.

Settings that give the SAME signals in a window are one strategy there: each
distinct signal set is measured once and its numbers credited to every setting
that produced it.

Outputs (artifacts), rewritten after every coin so a machine stopped at the
6-hour limit still hands over what it finished:
* out/pro-<N>.npz — one line per pair x setting x stop/target that traded: the
  numbers in FIELDS (whole window, the four test months, cost paid, 2:1 flag);
* out/pro-coins-<N>.json — per coin, measured on the days BEFORE the test
  months: daily volatility, trend vs. snap-back, correlation with BTC, cost,
  asset kind (for the coin groups);
* out/pro-report-<N>.json — per pair: settings, distinct signal sets, rows,
  seconds, or the error.

CHECK MODE (CHECK = a file under research/pro/, gzip JSON
{coin: {"pre": the search's minutes/book/usual-cost choices, "tfs": {tf:
{"last": the search's last bar, "keys": ["name:tf:sl:tp", ...]}}}}): those
settings measured again over the SAME bars with every trade kept ->
out/pro-trades-<N>.jsonl (one coin's lines appended at once).
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
# the per-minute order book is read for the newest FINE_DAYS (+2): beyond it a
# trade pays the coin's flat cost and is counted cost_unmeasured
FINE_DAYS = 45
os.environ["DAYS"] = str(FINE_DAYS)

import check_run as cr
import numpy as np
import pandas as pd
import sweep_shard as ss

import tradingagents.auto_trader as at
from tradingagents import backtest_report as br, signals_pro as sp, venue as _venue
from tradingagents.dataflows import exchange as fx

# THE FOUR TEST MONTHS, by the day each trade CLOSED (this process only: the
# research never writes the store, so no row with t30..p120 can reach it)
FOLDS = (30, 60, 90, 120)
br.SHORT_DAYS = FOLDS
br.RECENT_WINDOWS = FOLDS + (br.RECENT_DAYS,)      # recent_keys checks against it
WINDOW_DAYS = {"15m": 180, "30m": 180, "1h": 365, "4h": 730, "1d": 1095}
BARS_PER_DAY = {"15m": 96, "30m": 48, "1h": 24, "4h": 6, "1d": 1}
TFS = [t.strip() for t in (os.environ.get("TFS") or "15m,30m,1h,4h,1d").split(",")
       if t.strip() in WINDOW_DAYS]
NAMES = sp.variants()
NAME_IX = {n: k for k, n in enumerate(NAMES)}
BARRIERS = {tf: [b for b in (cr.barrier_of(tf, sl, tp) for sl, tp in sp.BARRIERS_PCT[tf])
                 if b is not None] for tf in TFS}
FIELDS = ("trades", "wins", "profit",
          "t30", "w30", "p30", "t60", "w60", "p60",
          "t90", "w90", "p90", "t120", "w120", "p120",
          "rt_paid", "pay2", "streak", "dd",
          # the round trips the trades closed in each window PAID, summed (%):
          # a choice made before a month reads the fees of its own days only
          "c30", "c60", "c90", "c120",
          "gate_blocked", "cost_unmeasured", "chase_skip", "closed_skipped", "unclear",
          "funding")
OUT_NPZ = os.path.join("out", f"pro-{ss.SHARD}.npz")
OUT_COINS = os.path.join("out", f"pro-coins-{ss.SHARD}.json")
REPORT_OUT = os.path.join("out", f"pro-report-{ss.SHARD}.json")
TRADES_OUT = os.path.join("out", f"pro-trades-{ss.SHARD}.jsonl")
CHECK = os.environ.get("CHECK") or ""
COIN_RETRIES = 2
PAIR_RETRIES = 2                 # a failed coin + timeframe is redone BY ITSELF
RETRY_CUTOFF_S = 4.8 * 3600      # no retry starts after this (runners die at 6 h)
DAY_MS = 86_400_000
T0 = time.time()


class Store:
    """Every measured line of this machine, saved after each coin."""

    def __init__(self):
        self.coins: list = []
        self.coin_ix: dict = {}
        self.pair_coin: list = []
        self.pair_tf: list = []
        self.var: list = []
        self.bar: list = []
        self.vals: list = []

    def add(self, coin: str, tf: str, name: str, k_bar: int, row: dict, rec: dict) -> None:
        c = self.coin_ix.setdefault(coin, len(self.coins))
        if c == len(self.coins):
            self.coins.append(coin)
        self.pair_coin.append(c)
        self.pair_tf.append(TFS.index(tf))
        self.var.append(NAME_IX[name])
        self.bar.append(k_bar)
        rt = row.get("rt_paid")
        sums = [float(((rec or {}).get(d) or {}).get("rt_sum") or 0.0) for d in FOLDS]
        self.vals.append([float(row.get(f) or 0) for f in FIELDS[:15]]
                         + [float(rt) if rt is not None else math.nan,
                            1.0 if br.pays_two_to_one(row) else 0.0,
                            float(row.get("streak") or 0), float(row.get("dd") or 0)]
                         + sums
                         + [float(row.get(f) or 0) for f in FIELDS[23:]])

    def save(self) -> None:
        os.makedirs("out", exist_ok=True)
        tmp = OUT_NPZ + ".tmp.npz"
        np.savez_compressed(
            tmp, names=np.array(NAMES), fields=np.array(FIELDS), coins=np.array(self.coins),
            tfs=np.array(TFS), coin=np.array(self.pair_coin, dtype=np.int32),
            tf=np.array(self.pair_tf, dtype=np.int8), var=np.array(self.var, dtype=np.int32),
            bar=np.array(self.bar, dtype=np.int8),
            vals=np.array(self.vals, dtype=np.float32).reshape(-1, len(FIELDS)),
            **{f"barriers_{tf}": np.array(BARRIERS[tf]) for tf in TFS})
        os.replace(tmp, OUT_NPZ)


def frame(sym: str, tf: str, end_s: int | None = None):
    """The deep window of one timeframe, closed candles only, with the lead-in
    the rules read: (whole frame, measured window, lead-in bars). `end_s` cuts
    it at the search's own last bar (the check run measures the SAME bars).
    A coin younger than the window has no lead-in: its rules sit idle until
    their lookback fills, never filled from bars that do not exist."""
    iv, bs, _cap = br.TFS[tf]
    need = WINDOW_DAYS[tf] * BARS_PER_DAY[tf] + ss.WARMUP_BARS + 20
    if end_s is not None:
        need += int(max(0, time.time() - end_s) // bs) + 2
    df = at._closed_bars(fx.klines(sym, iv, need), bs)
    if end_s is not None and len(df):
        df = df[df["Date"] <= pd.Timestamp(int(end_s), unit="s")].reset_index(drop=True)
    if not len(df):
        return df, df, 0
    cut = df["Date"].iloc[-1] - pd.Timedelta(days=WINDOW_DAYS[tf])
    measured = int((df["Date"] > cut).sum())
    warm = min(ss.WARMUP_BARS, len(df) - measured)
    dfw = df.iloc[len(df) - measured - warm:].reset_index(drop=True)
    return df, dfw, warm


def columns(df):
    o = [float(x) for x in df["Open"]]
    h = [float(x) for x in df["High"]]
    lo = [float(x) for x in df["Low"]]
    c = [float(x) for x in df["Close"]]
    v = [float(x) for x in df["Volume"]] if "Volume" in df.columns else [0.0] * len(c)
    ts = [int(x) for x in df["Date"].to_numpy().astype("datetime64[ms]").astype("int64")]
    return o, h, lo, c, v, ts


def groups_for(dfw, warm: int, fund) -> dict:
    """{signals in the window: [setting names]}; settings that never trade
    in the window are left out."""
    o, h, lo, c, v, ts = columns(dfw)
    out: dict = {}
    for name in NAMES:
        d = sp.dirs_for(sp.spec_for(name), o, h, lo, c, v, ts, fund)
        key = bytes(np.asarray(d[warm:], dtype=np.int8))
        if any(d[warm:]):
            out.setdefault(key, []).append(name)
    return out


def pro_pair(sym: str, tf: str, store: Store, pre: dict, done: int, total: int) -> dict:
    """Every setting of every family on one coin + timeframe. Lines reach the
    Store only after the whole pair measured: a pair that raises leaves
    nothing behind, so it can be redone by itself."""
    df, dfw, warm = frame(sym, tf)
    if len(dfw) - warm < br.min_bars(tf):
        return {"why": f"only {len(dfw) - warm} measurable bars"}
    groups = groups_for(dfw, warm, pre["fund"])
    reps = {names[0]: names for names in groups.values()}
    if not reps:
        return {"settings": len(NAMES), "distinct": 0, "rows": 0, "why": "no setting traded"}
    buf = io.StringIO()
    recs: dict = {}
    engine = at.backtest_strategy

    def keep(*a, **kw):
        # the engine's own window counts, fees included, kept on the way out
        r = engine(*a, **kw)
        sig = str(a[0]).rsplit("_gh_", 1)[0]
        recs[(sig, round(float(kw["sl"]), 6), round(float(kw["tp"]), 6))] = r.get("recents") or {}
        return r

    saved = (ss.window, br.pairs_for, at.backtest_strategy)
    ss.window = lambda _df: (dfw, warm)
    br.pairs_for = lambda _tf, _b=tuple(BARRIERS[tf]): list(_b)
    at.backtest_strategy = keep
    try:
        ss.run_pair(sym, tf, buf, i=done, n=total, signals=list(reps),
                    learned={**pre, "df": df})
    finally:
        ss.window, br.pairs_for, at.backtest_strategy = saved
    bix = {(round(b[0], 6), round(b[1], 6)): k for k, b in enumerate(BARRIERS[tf])}
    coin = sym.replace("_USDT", "")
    lines = []
    for line in buf.getvalue().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        rep = row.get("signal")
        if rep not in reps:
            continue
        bkey = (round(float(row["sl"]) / 100, 6), round(float(row["tp"]) / 100, 6))
        k = bix.get(bkey)
        if k is None:
            continue
        lines.append((rep, k, row, recs.get((rep,) + bkey)))
    for rep, k, row, rec in lines:
        for name in reps[rep]:
            store.add(coin, tf, name, k, row, rec)
    return {"settings": len(NAMES), "distinct": len(reps), "rows": len(lines),
            "days": int((dfw["Date"].iloc[-1] - dfw["Date"].iloc[warm]).days),
            "first": int(dfw["Date"].iloc[warm].timestamp()),
            "last": int(dfw["Date"].iloc[-1].timestamp())}


def usual_slip(book: dict) -> float | None:
    """A coin's usual one-side cost: the median of its recorded minutes' buy
    and sell costs (never one live reading, which at night is a stock token's
    closed-market spread). None when nothing was recorded."""
    if book is None or not len(book.get("t", [])):
        return None
    ok = ~np.asarray(book["exhausted"], dtype=bool)
    if not ok.any():
        return None
    both = (np.asarray(book["buy"], dtype=float)[ok] + np.asarray(book["sell"], dtype=float)[ok]) / 2
    both = both[np.isfinite(both)]
    return float(np.median(both)) if len(both) else None


def prefetch(sym: str, meta: dict | None = None) -> dict:
    """One coin's fee, liquidation distance, funding (Gate serves 180 days),
    minute order book and finest bars for the newest FINE_DAYS, and the usual
    cost every older trade pays. `meta` (the check run) replays the search's
    own choices of those — the fee, the liquidation distance, the usual cost
    and both ends of the book — so both walk the same thing. What cannot be
    frozen without copying it (readings Gate's record or the app published
    for older minutes after the search, minutes that moved from one source to
    another, the oldest funding falling out of Gate's 180 days) is caught by
    comparing every number of the two rows (pro_page.drift), never assumed
    away (code review, Oct 20, 2026)."""
    from tradingagents import cost_store

    now = int(time.time())
    meta = dict(meta or {})
    fee = float(meta["fee"]) if meta.get("fee") is not None else at.taker_fee(sym, fx=fx)
    liq = (float(meta["liq"]) if meta.get("liq") is not None
           else fx.liquidation_move_pct(sym, at.LEVERAGE))
    fund = fx.funding_history(sym)
    fine_from = int(meta.get("fine_from") or now - (FINE_DAYS + 1) * 86400)
    book_lo = int(meta.get("book_lo") or now - (FINE_DAYS + 2) * 86400)
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
    _t, _h, _l, _n5 = br.fine_bars(sym, fine_from, fx=fx)
    return {"fee": fee, "liq": liq, "fund": fund, "slip": float(slip), "fine": (_t, _h, _l),
            "meta": {"fine_from": fine_from, "book_lo": book_lo, "book_hi": book_hi,
                     "fee": fee, "liq": liq, "slip": float(slip), "slip_source": source}}


_BTC: dict = {}


def coin_stats(sym: str, pre: dict) -> dict:
    """What the coin IS, measured on its 1h candles BEFORE the four test
    months of every timeframe (no look-ahead into the days the choice is
    judged on): daily volatility and trending vs. snapping back decide its
    group (pro_report.groups); its usual cost and its correlation with BTC
    are reported beside them and decide nothing."""
    df = at._closed_bars(fx.klines(sym, "Min60", WINDOW_DAYS["1h"] * 24 + 40), 3600)
    if len(df) < 200:
        return {"why": f"only {len(df)} hourly candles"}
    ts = df["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
    # before EVERY timeframe's test months: the 1d frame's last closed candle
    # opened up to two days before the 1h frame's, so its months start that
    # much earlier (code review, Oct 20, 2026)
    cut = int(ts[-1]) - (max(FOLDS) + 2) * DAY_MS
    keep = ts < cut
    c = df["Close"].to_numpy(dtype=float)[keep]
    if len(c) < 200:
        return {"why": f"only {len(c)} hourly candles before the test months"}
    r = np.diff(np.log(c))
    var1 = float(np.var(r))
    r24 = np.log(c[24:] / c[:-24])
    vr = float(np.var(r24) / (24 * var1)) if var1 > 0 else math.nan
    out = {"vol": round(float(np.std(r)) * math.sqrt(24) * 100, 3), "vr": round(vr, 3),
           "kind": _venue.kind(sym), "hours": int(len(c)),
           "cost": round(br.round_trip_cost(pre["fee"], {"slippage": pre["slip"]}) * 100, 4)}
    try:
        if "t" not in _BTC:
            b = at._closed_bars(fx.klines("BTC_USDT", "Min60", WINDOW_DAYS["1h"] * 24 + 40), 3600)
            _BTC["t"] = b["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
            _BTC["c"] = b["Close"].to_numpy(dtype=float)
        common, ia, ib = np.intersect1d(ts[keep], _BTC["t"], return_indices=True)
        if len(common) > 200:
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
        save_json(REPORT_OUT, {"report": report, "names": len(NAMES), "tfs": TFS,
                               "window_days": WINDOW_DAYS, "folds": FOLDS})
        ss.report("testing", done, len(coins), note=f"{sym.replace('_USDT', '')} done")
    ss.log(f"done: {done} coin(s) in {(time.time() - T0) / 60:.0f} min")
    return 0


def each_tf(coin: str, tfs, work, report: list) -> None:
    """Run `work(tf) -> dict` for every timeframe; a timeframe that raises is
    redone BY ITSELF after the others, up to PAIR_RETRIES (CLAUDE.md: a
    failed coin is redone alone, never the whole run), and named if it never
    recovers."""
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
            ss.log(f"{coin} {tf}: {entry.get('distinct', entry.get('lines', 0))} / "
                   f"{entry.get('rows', '')} ({entry.get('why') or entry.get('error') or 'ok'}) "
                   f"in {entry['seconds']}s")
        if not again:
            return
        time.sleep(5 * (attempt + 1))
        pending = again


def search() -> int:
    ss.log(f"pro trader research: timeframes {TFS}, {len(NAMES)} settings of "
           f"{len(sp.FAMILIES)} families, stop/targets {[len(BARRIERS[t]) for t in TFS]}")
    store = Store()
    stats: dict = {}

    def per_coin(sym, report, done, total):
        coin = sym.replace("_USDT", "")
        pre = prefetch(sym)
        try:
            stats[coin] = coin_stats(sym, pre)
        except Exception as exc:                               # noqa: BLE001
            stats[coin] = {"error": f"{type(exc).__name__}: {str(exc)[:160]}"}
        stats[coin]["pre"] = pre["meta"]
        each_tf(coin, TFS, lambda tf: pro_pair(sym, tf, store, pre, done, total), report)
        store.save()
        save_json(OUT_COINS, stats)

    return run(per_coin)


def check() -> int:
    """The chosen settings, measured again over the SAME bars as the search
    (cut at the search's last bar, with the search's minutes, book and usual
    cost), with every trade kept. Plan: {coin: {"pre": meta, "tfs": {tf:
    {"last": unix s, "keys": ["name:tf:sl:tp", ...]}}}}."""
    with gzip.open(os.path.join(ROOT, CHECK), "rt", encoding="utf-8") as fh:
        plan = json.load(fh)
    ss.log(f"pro trader check run: "
           f"{sum(len(t['keys']) for c in plan.values() for t in c['tfs'].values())} "
           f"setting(s) on {len(plan)} coin(s)")

    def per_coin(sym, report, done, total):
        coin = sym.replace("_USDT", "")
        mine = plan.get(coin)
        if not mine:
            return
        pre = prefetch(sym, mine.get("pre"))
        lines: list = []

        def work(tf):
            spec = mine["tfs"][tf]
            cfgs = cr.parse_configs(",".join(spec["keys"]), sp.spec_for, "Pro Trader")
            df, dfw, warm = frame(sym, tf, end_s=int(spec["last"]))
            got = cr.verify_pair(sym, tf, df, pre, cfgs, done, total,
                                 window=lambda _df, _w=(dfw, warm): _w)
            lines.extend(got)
            return {"lines": len(got)}

        each_tf(coin, list(mine["tfs"]), work, report)
        # one coin's lines in one append: a machine killed mid-write leaves at
        # most one cut line, which the collect skips and names
        with open(TRADES_OUT, "a", encoding="utf-8") as out:
            out.write("".join(json.dumps(x, separators=(",", ":")) + "\n" for x in lines))

    if os.path.exists(TRADES_OUT):
        os.remove(TRADES_OUT)
    return run(per_coin)


def main() -> int:
    return check() if CHECK else search()


if __name__ == "__main__":
    raise SystemExit(main())
