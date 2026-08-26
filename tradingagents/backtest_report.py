"""Build a standalone backtest-grid page for one or more contracts.

Why this exists: the in-app backtest renders inside Streamlit, which cannot give
the operator a sortable 20-column grid with per-row trade logs, live filters and
a base-margin box that re-simulates. That page already existed as a one-off
script; this is the same page, parameterised, so **every** backtest run from the
app produces one and opens it in its own tab.

Rules it obeys (``CLAUDE.md`` 1-8 and the standard kit A-H):

* every mandated column, including PROFIT TOTAL, TP, SL, leverage, margin AND
  notional, WINS, LOSSES, trades and trades/day, plus the combination count
* stable row IDs assigned in canonical order, so ``#00042`` means the same row
  after any sort, filter or rescale
* the worst LOSING STREAK (summed, with its length) beside the worst single
  trade -- the run is what empties a laddered account, not one bad fill
* month-by-month profit on **every** row, stored as an array aligned to the
  month header rather than dropped from some rows to save bytes
* filters whose units match the column they filter (months green is a COUNT)
* liquidation modelled from MEXC's published maintenance margin, and slippage
  charged per side -- a zero-slippage backtest is fiction (rule 9)

Candles are fetched fresh on every run and their real depth is measured and
printed, because the operator re-runs this over time to see what changed.
"""
from __future__ import annotations

import itertools
import json
import math
import os
from collections.abc import Callable, Sequence
from html import escape as html_escape

# Every entry rule the engine implements. Seven shipped originally; fifteen
# were added 2026-08-19 when the operator asked why Fibonacci, support and
# resistance were missing -- they had simply never been written. Fifty-three
# more landed the same day from the wider research sweep (signals_ext2):
# trend systems, oscillators, mean reversion, breakouts, the ICT/SMC set,
# candle patterns and the first VOLUME-based rules.
SIGNALS = [
    # the original seven
    "mom6", "mom15", "fade15", "trend50", "rsi14", "sweep30", "fvg",
    # Fibonacci retracements
    "fib618", "fib382",
    # support / resistance and breakouts
    "sr_bounce", "sr_break", "donchian20", "pivot",
    # volatility bands
    "bb20", "bbbreak", "keltner", "atrbreak",
    # oscillators and crosses
    "macd", "emacross", "stoch14", "cci20", "engulf",
    # trend systems (signals_ext2)
    "supertrend", "psar", "ichimoku", "adx14", "aroon25", "vortex14",
    "hull20", "kama10", "trix15", "gmma", "heikin", "lrslope",
    # momentum / oscillators
    "willr14", "stochrsi", "ultosc", "ao", "fisher", "crsi", "tsi",
    "rsidiv", "macddiv", "elder",
    # mean reversion
    "zscore20", "rsi2", "ibs", "prank", "vwaprev", "gapfade",
    # breakouts
    "orb", "nr7", "squeeze", "fractal5", "nhigh50", "insidebrk",
    # ICT / SMC
    "orderblock", "bos", "choch", "eqraid", "turtle", "ote", "killzone",
    # candle patterns
    "hammer", "doji", "soldiers", "pinbar", "dbltop",
    # volume-based
    "obv20", "cmf20", "mfi14", "force13", "volspike", "volclimax",
    "relvolbrk",
]
THRESH_SIGNALS = {"mom6", "mom15", "fade15"}

# Timeframes, with the bar limit MEASURED against what MEXC serves (rule 13).
# The fewest bars a pair may have and still be measured. This was a flat 500
# inside market_sweep.run_pair, sized for 15m, and it made 1d IMPOSSIBLE: a
# year of daily bars is at most ~395 (the window is days+30) and the 60-day
# sweep of 2026-08-25 gave 1d exactly ~90, so all 997 1d pairs were excluded as
# "only 90 bars" -- the fifth mandatory timeframe of the full grid, dropped by a
# constant. The floor is the TECHNICAL minimum per timeframe (the longest
# lookback, trend50, plus room for a half-split); depth is the row's own
# `days`/`bars`, and filtering on it is the reader's decision in the artifact.
# One definition, used by the local sweep and the cloud shard alike.
MIN_BARS = {"15m": 500, "30m": 500, "1h": 500, "4h": 500, "1d": 60}


def min_bars(tf: str) -> int:
    return MIN_BARS.get(tf, 500)


TFS: dict[str, tuple[str, int, int]] = {
    "15m": ("Min15", 900, 36000),
    "30m": ("Min30", 1800, 20000),
    "1h": ("Min60", 3600, 10000),
    "4h": ("Hour4", 14400, 14000),
    "1d": ("Day1", 86400, 2400),
}

# THE GRID IS SHARED. This is the same barrier set the `analyze1hr4hr` skill
# sweeps, so a backtest clicked in the app and an analysis published as an
# artifact contain the SAME rows. They diverged once -- the artifact recommended
# 1.50/2.00 and the button's six-pair grid had never tested it, so the operator
# could not find a single recommended row in their own app. A wide grid costs
# minutes per click; a grid that disagrees with the analysis costs trust.
#
# ~10 stops, from well inside the noise to just under the liquidation move, and
# ~11 targets, from below round-trip cost to far above it. Scaled per bar: a
# 0.4% target is generous at 1 day and unreachable at 15 minutes once costs are
# paid.
def _grid(sls, tps):
    return sorted((sl, tp) for sl in sls for tp in tps)


BARRIERS: dict[str, list[tuple[float, float]]] = {
    "15m": _grid([.001, .002, .003, .004, .005, .006, .008, .010, .012, .015],
                 [.002, .003, .004, .006, .008, .010, .012, .015, .020, .025,
                  .030]),
    "30m": _grid([.002, .003, .004, .005, .006, .008, .010, .012, .015, .020],
                 [.003, .005, .008, .010, .012, .015, .020, .025, .030, .040,
                  .050]),
    "1h": _grid([.003, .005, .007, .010, .012, .015, .020, .025, .030, .040],
                [.004, .006, .010, .015, .020, .025, .030, .040, .050, .060,
                 .080]),
    # 1h and 4h share one list on purpose: these are the two timeframes the
    # `analyze1hr4hr` skill sweeps, and every row it publishes must exist here.
    # A "scaled" 4h list looked more principled and silently dropped
    # SL 1.00 / TP 3.00 -- a row that had just been recommended.
    "4h": _grid([.003, .005, .007, .010, .012, .015, .020, .025, .030, .040],
                [.004, .006, .010, .015, .020, .025, .030, .040, .050, .060,
                 .080]),
    "1d": _grid([.010, .015, .020, .025, .030, .040, .050, .060, .070, .080],
                [.020, .030, .040, .050, .060, .080, .100, .120, .150, .180,
                 .200]),
}
THRESHOLDS: dict[str, list[float]] = {
    "15m": [.001, .002, .003], "30m": [.002, .003, .004],
    "1h": [.002, .003, .005], "4h": [.004, .006, .008],
    "1d": [.008, .010, .015],
}

MIN_TRADES = 30          # the skill's floor: below this a row is noise
GATE_BLOCK = 0.50        # round-trip cost >= 50% of target -> cannot win


_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"   # no 0/O/1/I


# ---------------------------------------------------------------- slice plans
# One position, several exits. A plan is (weight, TP multiple) per slice: the
# multiple scales the ROW's take-profit, and every slice keeps the row's stop.
# That keeps the barrier sweep exactly as it is and adds the split as ONE extra
# dimension with a handful of values, instead of squaring the grid — 110 barrier
# pairs against 110 would turn a 22-minute five-coin sweep into days.
#
# `None` is the single exit every existing row uses, and it must stay first: a
# page built without plans has to reproduce byte-for-byte what it did before.
SLICE_PLANS: dict = {
    None: None,
    "half 1x/3x": ((0.5, 1.0), (0.5, 3.0)),
    "70/30 1x/3x": ((0.7, 1.0), (0.3, 3.0)),
    "thirds 1x/2x/4x": ((1 / 3, 1.0), (1 / 3, 2.0), (1 / 3, 4.0)),
}


def slices_for(plan: str | None, sl: float, tp: float) -> list | None:
    """A plan name plus the row's barriers -> the slice list the engine takes.

    ``sl``/``tp`` are FRACTIONS, as the barrier grid stores them. Returns None
    for the single-exit plan so the caller passes nothing to the engine.
    """
    spec = SLICE_PLANS.get(plan)
    if not spec:
        return None
    out = [(float(w), float(tp) * float(m), float(sl)) for w, m in spec]
    # Float thirds must still sum to exactly 1 for the engine's check.
    drift = 1.0 - sum(x[0] for x in out)
    if abs(drift) > 1e-12:
        out[-1] = (out[-1][0] + drift, out[-1][1], out[-1][2])
    return out


def row_code(coin: str, tf: str, signal: str, th: float, sl: float,
             tp: float, sizing: str, plan: str | None = None) -> str:
    """A stable ID for one combination, identical on every page and every run.

    Sequential numbering was per-page: the same live APEX row was #05146 in one
    artifact, #02054 in another and something else again in the app, so "the ID"
    meant nothing across two tabs. This is derived from the combination itself,
    so the row carries its own name wherever it is drawn.
    """
    import hashlib

    # A signal with no threshold has been stored as 0.0 by one sweep and 0.3 by
    # another. Left alone that gave the SAME live strategy two different codes
    # on two pages -- which is the whole problem this function exists to end.
    thv = float(th) if signal in THRESH_SIGNALS else 0.0
    seed = "|".join([coin, tf, signal, f"{thv:.3f}", f"{float(sl):.3f}",
                     f"{float(tp):.3f}", sizing])
    # A slice plan is part of the combination, so it has to be part of the ID —
    # otherwise "half of it at 2%, half at 6%" and "all of it at 2%" are the
    # same row on the page, which is the #8ZFUXG8F / #5P3SYZDY confusion in a
    # new costume. Appended ONLY when a plan is present, so every code minted
    # before slices existed still hashes to itself.
    if plan:
        seed += "|" + str(plan)
    n = int.from_bytes(hashlib.blake2s(seed.encode(), digest_size=5).digest(),
                       "big")
    # 8 characters, spending the digest's full 40 bits. Six characters kept
    # only 30 of them, a ~1-billion space -- at 75 signals one coin's page is
    # 35,640 rows, a ~26% birthday-collision chance per page, and PROVE hit it
    # on 2026-08-19 (fade15 0.3/0.7/0.6 flat == kama10 3.0/8.0 flat, both
    # "Y4KXP3"). At 40 bits the same page is ~0.03%.
    out = ""
    for _ in range(8):          # 8 chars; the tolerant lookup still resolves the
                                # 6-character codes older artifacts quote
        out = _CODE_ALPHABET[n % 32] + out
        n //= 32
    return out


def _round_sig(x: float, sig: int = 8) -> float:
    """Keep price precision honest. Rounding candles to 4dp on a $0.56 coin
    moved a replayed total 0.6% away from the row it belonged to."""
    if x == 0 or not math.isfinite(x):
        return 0.0
    return round(x, max(0, sig - 1 - int(math.floor(math.log10(abs(x))))))


def pairs_for(tf: str, deployed: Sequence[dict] = ()) -> list:
    """The barrier pairs to test on ``tf``: the standing grid PLUS whatever is
    actually deployed there.

    Rule 21: the page must contain the exact combination that is running, and a
    live 0.80/2.40 pair is not in any grid of round numbers.
    """
    extra = {(round(float(d.get("sl", 0)) / 100, 6),
              round(float(d.get("tp", 0)) / 100, 6))
             for d in deployed if d.get("tf") == tf}
    return sorted(set(BARRIERS[tf]) | {p for p in extra if p[0] > 0 and p[1] > 0})


def _is_deployed(coin: str, tf: str, signal: str, th: float, sl: float,
                 tp: float, sizing: str, deployed: Sequence[dict],
                 plan: str | None = None) -> bool:
    """Is this combination one the operator is actually running?

    Matched on all seven fields with the same tolerances the page's own
    ``isDep`` uses, so a row the page will badge is a row this keeps.
    """
    for d in deployed or ():
        if (d.get("coin") == coin and d.get("tf") == tf
                and d.get("signal") == signal
                and abs(float(d.get("th", 0)) - th) < .01
                and abs(float(d.get("sl", 0)) - sl) < .01
                and abs(float(d.get("tp", 0)) - tp) < .01
                and d.get("sizing") == sizing
                and (d.get("plan") or None) == (plan or None)):
            return True
    return False


def run_grid(coins: Sequence[str], tfs: Sequence[str], *,
             base_margin: float = 5.0, days: int = 365,
             deployed: Sequence[dict] | None = None,
             plans: Sequence = (None,),
             signals: Sequence[str] | None = None,
             min_trades: int = MIN_TRADES, rec_min_trades: int = 100,
             progress: Callable[[str, float], None] | None = None) -> dict:
    """Fetch fresh candles and test every combination on them.

    One combination is coin x timeframe x signal x threshold x SL x TP x
    sizing, and every one of those seven fields varies.

    ``min_trades`` drops rows below the floor and ``rec_min_trades`` is the
    bar a row must clear to earn RECOMMENDED in the page. Both default to the
    1h/4h skill's values; the 15m/30m skill raises them (100 and 300) because
    a year of 15m hands one config ~795 trades and the low bars filter nothing.
    """
    import pandas as pd

    from tradingagents import auto_trader as at
    from tradingagents.dataflows import mexc_futures as fx

    signals = list(signals or SIGNALS)
    # A signal with no threshold is stored at th=0. A deployed entry naming a
    # threshold for such a signal would then match no row, and the page would
    # show nothing as DEPLOYED — the exact ambiguity row IDs exist to kill.
    deployed = [dict(d, th=(d.get("th", 0.0)
                            if d.get("signal") in THRESH_SIGNALS else 0.0))
                for d in (deployed or [])]
    # Rule 21: the page must contain the EXACT combination that is deployed,
    # not a neighbouring one. The standing barrier grid is a set of round
    # numbers, so a live 2.50/4.00 pair simply is not in it -- inject every
    # deployed barrier and threshold into the grid for its own timeframe.
    extra_th: dict[tuple, set] = {}
    for d in deployed:
        tf = d.get("tf")
        if tf not in TFS:
            continue
        if d.get("signal") in THRESH_SIGNALS and d.get("th"):
            extra_th.setdefault((tf, d["signal"]), set()).add(
                round(float(d["th"]) / 100, 6))
    rows: list[dict] = []
    meta: dict[str, dict] = {}
    series: dict[str, dict] = {}
    excluded: list[dict] = []
    cut = pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(days=days)
    total = max(1, len(coins) * len(tfs))
    done = 0
    from tradingagents.market_sweep import fmt_stamp
    fetched_at = fmt_stamp()

    for coin in coins:
        show = coin.replace("_USDT", "")
        try:
            fee = at.taker_fee(coin, fx=fx)
        except Exception:
            fee = 0.0004
        try:
            book = fx.book_cost(coin, base_margin * at.LEVERAGE)
            # Round trip = 2 x (taker fee + slippage). `book_cost` measures
            # slippage as the average fill price against MID, so half the
            # spread is ALREADY inside it — adding spread/2 again charged it
            # twice. On APEX that printed 0.376% (12.5% of a 3% target) where
            # the measured cost was 0.130% (4.3%), and rule 11 asks the
            # operator to judge a strategy by exactly that ratio.
            rt = 2 * (fee + float(book.get("slippage") or 0))
        except Exception:
            rt = None
        try:
            liq = fx.liquidation_move_pct(coin, at.LEVERAGE)
        except Exception:
            liq = None
        # The third cost of a perpetual: what it charges for HOLDING. Fetched
        # once per coin and applied per settlement inside each trade's window.
        try:
            fund = fx.funding_history(coin)
        except Exception:
            fund = []
        for tf in tfs:
            iv, bs, cap = TFS[tf]
            # Ask for the whole window, never a fixed bar count: 2,000 bars is
            # 333 days at 4h but 83 days at 1h.
            want = int(days * 86400 / bs * 1.15)
            limit = max(300, min(want, cap))
            if progress:
                progress(f"{show} {tf}: fetching {limit} bars", done / total)
            try:
                df = fx.klines(coin, iv, limit)
            except Exception as exc:
                excluded.append({"coin": show, "tf": tf,
                                 "why": f"fetch failed: {str(exc)[:70]}"})
                done += 1
                continue
            df = df[df["Date"] >= cut].reset_index(drop=True)
            if len(df) < 60:
                excluded.append({
                    "coin": show, "tf": tf,
                    "why": f"only {len(df)} bars inside the last {days} days"})
                done += 1
                continue
            hist_days = int((df["Date"].iloc[-1] - df["Date"].iloc[0]).days)
            _ms = df["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
            first_ms, last_ms = int(_ms[0]), int(_ms[-1])
            hi = [float(x) for x in df["High"]]
            lo = [float(x) for x in df["Low"]]
            cl = [float(x) for x in df["Close"]]
            op = [float(x) for x in df["Open"]]
            skey = f"{show}|{tf}"
            meta[skey] = {"bars": len(df), "days": hist_days,
                          "rt": None if rt is None else round(rt * 100, 4),
                          "liq": 0.0 if liq is None else round(liq, 3),
                          "fee": fee, "last_bar": str(df["Date"].iloc[-1])[:16],
                          "fetched": fetched_at}
            series[skey] = {"o": [_round_sig(x) for x in op],
                            "h": [_round_sig(x) for x in hi],
                            "l": [_round_sig(x) for x in lo],
                            "c": [_round_sig(x) for x in cl],
                            "t": [str(x)[:16] for x in df["Date"]],
                            "fee": fee, "liq": meta[skey]["liq"], "d": {},
                            # settlements the page needs to replay funding
                            # itself, trimmed to this frame's own window
                            "fund": [[int(f["settle_ms"]), round(f["rate"], 8)]
                                     for f in fund
                                     if first_ms <= int(f["settle_ms"])
                                     <= last_ms]}
            n = len(df)
            half = n // 2
            pairs = pairs_for(tf, deployed)
            # Once per frame, for the fast path: funding as cumulative-rate
            # arrays, and each bar's month resolved to an index so no trade
            # ever formats a timestamp.
            _fms, _frate = [], []
            for _f in sorted(fund or [], key=lambda d: d["settle_ms"]):
                _fms.append(int(_f["settle_ms"]))
                _frate.append(float(_f["rate"]))
            _fcum = [0.0]
            for _r_ in _frate:
                _fcum.append(_fcum[-1] + _r_)
            _mo_codes = df["Date"].to_numpy().astype("datetime64[M]")
            _mo_labels: list[str] = []
            _mo_seen: dict = {}
            _mo_idx: list[int] = []
            for _v in _mo_codes:
                _k = _mo_seen.get(_v)
                if _k is None:
                    _k = _mo_seen[_v] = len(_mo_labels)
                    _mo_labels.append(str(_v)[:7])
                _mo_idx.append(_k)
            for sig in signals:
                ths = (sorted(set(THRESHOLDS[tf])
                              | extra_th.get((tf, sig), set()))
                       if sig in THRESH_SIGNALS else [None])
                for th in ths:
                    key = f"{sig}_rpt_{tf}"
                    at.STRATEGY_SPECS[key] = {
                        "interval": iv, "bar_seconds": bs, "tp": .02,
                        "sl": .01, "threshold": .003 if th is None else th}
                    try:
                        dkey = "rsi14_1h" if sig == "rsi14" else key
                        dirs = at._dirs_for_backtest(
                            dkey, hi, lo, cl, opens=op,
                            volume=([float(x) for x in df["Volume"]]
                                    if "Volume" in df.columns else None),
                            ts=[int(x) for x in _ms])
                    except Exception:
                        at.STRATEGY_SPECS.pop(key, None)
                        continue
                    thp = 0.0 if th is None else round(th * 100, 3)
                    series[skey]["d"][f"{sig}|{thp:g}"] = "".join(
                        "u" if d > 0 else "d" if d < 0 else "n" for d in dirs)
                    import numpy as _np

                    from tradingagents import fast_grid as _fg
                    _dirs_idx = [int(x) for x in _np.flatnonzero(
                        _np.asarray(dirs, dtype=_np.int8))]
                    for (sl, tp) in pairs:
                        # ONE walk per barrier pair: entries and exits do not
                        # depend on sizing, the first half is a prefix of the
                        # full run, and only the second half needs its own
                        # walk (it starts flat at the boundary). Six engine
                        # runs become two walks + scaling — pinned to the
                        # cent against the engine in tests/test_fast_grid.py.
                        _fastr = None
                        if any(_pl is None for _pl in plans):
                            try:
                                _fastr = _fg.combo_six(
                                    _dirs_idx, dirs, op, hi, lo, cl,
                                    tp=tp, sl=sl,
                                    liq=(None if liq is None
                                         else abs(liq) / 100.0),
                                    half=half, base=base_margin,
                                    lev=at.LEVERAGE, fee=fee + 0.0003,
                                    ladder=at.ladder_margin,
                                    mo_idx=_mo_idx, mo_labels=_mo_labels,
                                    f_ms=_fms, f_cum=_fcum, bar_ms=_ms)
                            except Exception:
                                _fastr = None
                        for sz, pl in itertools.product(
                                ("flat", "martingale"), plans):
                            # One position, several exits. `plans` defaults to
                            # (None,) — the single exit every existing row
                            # uses — so a page built without asking for splits
                            # reproduces exactly what it produced before.
                            _slx = slices_for(pl, sl, tp)
                            if _slx is None and _fastr is not None:
                                r = _fastr[sz]["full"]
                            else:
                                try:
                                    r = at.backtest_strategy(
                                        key, df, base_margin, fee=fee,
                                        sizing=sz, dirs=dirs, tp=tp, sl=sl,
                                        liq_move_pct=liq, funding=fund,
                                        slices=_slx)
                                except Exception:
                                    continue
                        # The DEPLOYED row is never dropped, whatever its
                        # trade count. Rule 21 says the page must contain the
                        # exact combination that is running, and the trade
                        # floor was quietly deleting it: on the 19-day August
                        # sweep every one of the five live rows took fewer than
                        # 30 trades in the window, so the page badged NOTHING
                        # as deployed and the operator could not find their own
                        # strategy in their own results.
                            if r["trades"] < min_trades and not _is_deployed(
                                    show, tf, sig, thp, sl * 100, tp * 100,
                                    sz, deployed, pl):
                                continue
                            if _slx is None and _fastr is not None:
                                a = _fastr[sz]["h1"]
                                b = _fastr[sz]["h2"]
                            else:
                                a = at.backtest_strategy(
                                    key, df.iloc[:half], base_margin, fee=fee,
                                    sizing=sz, dirs=dirs[:half], tp=tp, sl=sl,
                                    liq_move_pct=liq, funding=fund,
                                    slices=_slx)
                                b = at.backtest_strategy(
                                    key, df.iloc[half:], base_margin, fee=fee,
                                    sizing=sz, dirs=dirs[half:], tp=tp, sl=sl,
                                    liq_move_pct=liq, funding=fund,
                                    slices=_slx)
                            ratio = None if rt is None else rt / tp
                            rows.append({
                                "coin": show, "tf": tf, "signal": sig,
                                "th": thp, "sl": round(sl * 100, 3),
                                "tp": round(tp * 100, 3),
                                "rr": round(tp / sl, 2),
                                "sizing": sz, "lev": at.LEVERAGE,
                                # None on a single-exit row, so the field is
                                # on EVERY row rather than only the split ones
                                # (rule F: never drop a field from a subset).
                                "plan": pl,
                                "exits": 1 if not _slx else len(_slx),
                                "base": base_margin,
                                "notional": round(base_margin * at.LEVERAGE,
                                                  2),
                                "trades": r["trades"], "wins": r["wins"],
                                "losses": r["losses"],
                                "winrate": round(100 * r["wins"]
                                                 / r["trades"], 2),
                                "profit": round(r["profit"], 2),
                                "h1": round(a["profit"], 2),
                                "h2": round(b["profit"], 2),
                                "green": r["months_green"],
                                "months": r["months_total"],
                                "worst": round(r["worst_trade"], 2),
                            "wstreak": r.get("worst_streak"),
                            "wstreakn": r.get("worst_streak_len"),
                            "funding": round(r.get("funding_total") or 0, 2),
                                "dd": round(r["max_dd"], 2),
                                # both the engine and the fast path count
                                # liquidations directly; the log-scan needed
                                # keep_log and broke on logless results
                                "liqs": r["liqs"],
                                "stop_reachable": bool(liq is None
                                                       or sl * 100 < liq),
                                "days": hist_days,
                                "monthly": {k: round(v, 2)
                                            for k, v in r["monthly"].items()},
                                "cost_of_tp": (0.0 if ratio is None
                                               else round(ratio * 100, 1)),
                                "gate": ("unknown" if ratio is None
                                         else "block" if ratio >= GATE_BLOCK
                                         else "warn" if ratio >= .2
                                         else "ok"),
                            })
                    at.STRATEGY_SPECS.pop(key, None)
            done += 1
            if progress:
                progress(f"{show} {tf}: {len(rows)} combinations", done / total)

    months = sorted({m for r in rows for m in r["monthly"]}, reverse=True)
    # Month columns as an ARRAY aligned to the header: same coverage, a quarter
    # of the bytes. Never drop the field from a subset of rows (kit item F).
    for r in rows:
        r["mon"] = [r["monthly"].get(m) for m in months]
        r.pop("monthly", None)
    # IDs derived from the combination, never from position: the same row keeps
    # its code across pages, sorts, filters and future runs.
    for r in rows:
        r["id"] = row_code(r["coin"], r["tf"], r["signal"], r["th"], r["sl"],
                           r["tp"], r["sizing"], r.get("plan"))
    seen = {}
    for r in rows:                       # a collision would make two rows share
        seen.setdefault(r["id"], []).append(r)   # a name; say so rather than hide it
    dupes = {k: v for k, v in seen.items() if len(v) > 1}
    if dupes:
        raise RuntimeError(f"row-code collision on {sorted(dupes)[:3]}")
    return {"rows": rows, "meta": meta, "series": series, "months": months,
            "cur": months[0] if months else "",
            "lev": at.LEVERAGE,
            "slip": 0.0003, "base": base_margin,
            "ladder": [1, 1, 2, 2, 4, 4, 8],
            "min_trades": min_trades, "rec_min_trades": rec_min_trades,
            "deployed": list(deployed or []), "excluded": excluded,
            "days_asked": days, "fetched": fetched_at}


def _pack(payload: dict) -> dict:
    """Shrink the payload's ENCODING without dropping any row's fields.

    Reversed in the template in two lines. Verified by
    `test_packing_preserves_every_field_of_every_row`.
    """

    p = dict(payload)
    rows = p.get("rows") or []
    if rows and not p.get("cols"):
        cols = list(rows[0].keys())
        keyset = set(cols)
        for i, r in enumerate(rows):      # a row with a different shape would
            if set(r.keys()) != keyset:   # silently lose fields to the header
                # Name the difference. This used to raise a bare "rows have
                # inconsistent keys", which told the operator nothing and left a
                # ZERO-BYTE report on disk — a click that produced a blank page.
                # Measured 2026-08-20 19:51 on an archive run for PI.
                miss = sorted(keyset - set(r.keys()))
                extra = sorted(set(r.keys()) - keyset)
                raise RuntimeError(
                    "rows have inconsistent keys; cannot pack. "
                    f"row {i} ({r.get('coin')} {r.get('tf')} {r.get('signal')} "
                    f"{r.get('sizing')}) is missing {miss or 'nothing'} and adds "
                    f"{extra or 'nothing'}. Row 0 defines "
                    f"{len(cols)} columns.")
        p["cols"] = cols
        p["rows"] = [[r[c] for c in cols] for r in rows]
    ser = {}
    for k, s in (p.get("series") or {}).items():
        s = dict(s)
        t = s.get("t") or []
        if len(t) > 2:
            import datetime as _dt

            fmt = "%Y-%m-%d %H:%M"
            a = _dt.datetime.strptime(t[0], fmt)
            b = _dt.datetime.strptime(t[1], fmt)
            step = int((b - a).total_seconds())
            # Only drop the strings when the grid really is regular; a frame
            # with a gap keeps them rather than being silently re-timed.
            last = a + _dt.timedelta(seconds=step * (len(t) - 1))
            if step > 0 and last.strftime(fmt) == t[-1]:
                s["t0"], s["step"] = t[0], step
                s.pop("t", None)
        # Direction arrays run-length encoded: "nnnnnuuu" -> "n5u3". Signals
        # persist for stretches, so this is 32% of the original 3.32 MB and is
        # exactly reversible. Encoding, not coverage -- every bar still has its
        # direction after the template expands it.
        s["d"] = {k2: _rle(v) for k2, v in (s.get("d") or {}).items()}
        s["rle"] = 1
        ser[k] = s
    p["series"] = ser
    return p


def _rle(text: str) -> str:
    """"nnnnnuuu" -> "n5u3". Reversed in the template by one regex.

    The run lengths are digits, so the alphabet must not contain any -- "u3d"
    would encode to itself and decode to "uuud". Directions are only ever
    u/d/n, so this cannot happen today; the check exists because a future
    signal adding a fourth symbol would corrupt silently rather than fail.
    """
    import itertools

    bad = set(text) - set("udn")
    if bad:
        raise ValueError(
            f"direction alphabet must be u/d/n, got {sorted(bad)} -- run-length "
            f"encoding is ambiguous once a digit can appear")
    out = []
    for ch, grp in itertools.groupby(text):
        n = sum(1 for _ in grp)
        out.append(ch if n == 1 else f"{ch}{n}")
    return "".join(out)


def _tested(payload: dict) -> int:
    """How many combinations were MEASURED — not how many this page shows.

    The fold streams the market to a snapshot and keeps a bounded selection in
    memory, so `len(payload["rows"])` is the size of the TABLE. Printing that
    as "combinations tested" would be a true number under a false label: on
    2026-08-26 the 2-month sweep measured 21,278,772 of them and a page
    capped at 250,000 would have claimed 250,000.
    """
    return int(payload.get("rows_total") or len(payload["rows"]))


def _capped_note(payload: dict) -> str:
    """Say what was capped, in the same breath as the count (rule 20)."""
    total = _tested(payload)
    shown = len(payload["rows"])
    if not payload.get("rows_capped") or shown >= total:
        return ""
    where = payload.get("grid_path") or "the run's grid snapshot"
    return (f" &mdash; this page shows the <b>{shown:,}</b> most profitable of "
            f"them; every one of the {total:,} is in {where}")


def render(payload: dict, *, title: str, headline: str = "",
           note: str = "") -> str:
    """Wrap the payload in the standalone grid page."""
    from tradingagents.report_template import TEMPLATE

    coins = sorted({r["coin"] for r in payload["rows"]})
    tfs = [t for t in TFS if any(r["tf"] == t for r in payload["rows"])]
    nsig = len({r["signal"] for r in payload["rows"]})
    hist = " &middot; ".join(
        f"{k.replace('|', ' ')} {v['days']}d ({v['bars']} bars)"
        for k, v in sorted(payload["meta"].items()))
    liqs = " &middot; ".join(
        f"{k.split('|')[0]} {v['liq']:.2f}%"
        for k, v in sorted(payload["meta"].items())
        if k.endswith("|" + (tfs[0] if tfs else "")))
    prov = (
        f"{len(coins)} contract(s) &times; {len(tfs)} timeframe(s) &times; "
        f"{nsig} signals &times; up to 3 momentum thresholds &times; the "
        f"barrier grid &times; 2 sizings = <b>{_tested(payload):,} "
        f"combinations</b>{_capped_note(payload)}, all at {payload['lev']}x on a "
        f"{payload['base']:g} USDT base ({payload['base'] * payload['lev']:g} "
        f"notional). Candles fetched <b>{payload['fetched']}</b> for the past "
        f"{payload['days_asked']} days &mdash; measured depth: {hist}. "
        f"Worst-case fills: stop checked before target inside a bar, MEXC "
        f"taker fee plus 0.03%/side slippage. <b>Liquidation modelled</b> from "
        f"MEXC's published maintenance margin ({liqs}), so a stop wider than "
        f"that is marked STOP UNREACHABLE and excluded from survivors. Rows "
        f"under {payload.get('min_trades', MIN_TRADES)} trades dropped "
        f"(RECOMMENDED needs {payload.get('rec_min_trades', 100)}+). "
        # Derived, never a literal: this sentence once said "Fibonacci is not
        # here" and stayed true only until signals_ext added fib618/fib382.
        + (f"<b>Fibonacci, support/resistance, bands and oscillators are all "
           f"in the grid</b> &mdash; the engine implements "
           f"{len(SIGNALS)} signals."
           if any(s.startswith("fib") for s in SIGNALS) else
           f"<b>Fibonacci is not in the engine</b> &mdash; it implements "
           f"{len(SIGNALS)} signals.")
        + (f" Excluded: {len(payload['excluded'])} coin/timeframe pair(s)."
           if payload["excluded"] else "")
        + ((lambda z: f" <b>Store: {z['stored_rows']:,} rows reused &middot; "
                      f"{z['new_bars']:,} new bars tested &middot; "
                      f"{z['recomputed_rows']:,} rows recomputed"
                      + (f" &middot; {z['deployed_computed']} deployed "
                         f"combination(s) computed" if z['deployed_computed']
                         else "")
                      + (f" &middot; fresh: {', '.join(z['fresh_pairs'])}"
                         if z['fresh_pairs'] else "") + ".")
           (payload["reuse"]) if payload.get("reuse") else ""))
    foot = headline or (
        "<b>A survivor is not a recommendation.</b> A row earns RECOMMENDED "
        "only by being a survivor, top-20 by BALANCED, backed by 100+ trades, "
        "AND having a worst dip under half the wallet you typed. Change the "
        "wallet box and the badges recompute.<br><br>"
        "<b>Read WORST STREAK, not worst single trade.</b> On a ladder the "
        "losses grow, so an unbroken run is what empties the account: the "
        "streak column is the sum of that run and the column beside it is how "
        "many trades it took.<br><br>"
        "<b>Flat is how the signal is measured.</b> The DEEP ladder multiplies "
        "whatever edge exists, including a negative one, so a row that only "
        "wins on martingale is telling you about the sizing rather than the "
        "strategy.<br><br>"
        "<b>This month is not evidence.</b> Two or three weeks cannot separate "
        "a better strategy from a luckier one &mdash; check the month count "
        "and the trade count before believing a hot column.")
    if note:
        foot = note + "<br><br>" + foot
    opts = ('<option value="">all</option>'
            + "".join(f'<option value="{c}">{c}</option>' for c in coins))
    topts = ('<option value="">all</option>'
             + "".join(f'<option value="{t}">{t}</option>' for t in tfs))
    # The heading and subtitle are DERIVED, never literals: the template once
    # hardcoded "PI & APEX ... 11,440 combinations" and every later page --
    # any coin set, any grid size -- kept wearing it.
    _tf_words = {"15m": "15 minutes", "30m": "30 minutes", "1h": "1 hour",
                 "4h": "4 hours", "1d": "1 day"}
    _named = [_tf_words.get(t, t) for t in tfs]
    sub = (" and ".join(_named) + (", searched equally" if len(_named) > 1
                                   else "")
           + f". {len(payload['rows']):,} combinations.")
    return (TEMPLATE
            .replace("__SUB__", html_escape(sub))
            .replace("__TITLE__", html_escape(title))
            .replace("__COIN_OPTS__", opts)
            .replace("__TF_OPTS__", topts)
            .replace("__PROV__", json.dumps(prov))
            .replace("__FOOT__", json.dumps(foot))
            # Packed at the point of injection, never earlier: the provenance
            # lines above still read rows as dicts. The 16 MB artifact ceiling
            # is real on a 28,600-row year, and the rule (kit item F) is to
            # compress the ENCODING and never the coverage -- rows become arrays
            # aligned to `cols`, timestamps become (t0, step). Both reversed in
            # the template; every row keeps every field.
            .replace("__DATA__", json.dumps(_pack(payload),
                                            separators=(",", ":"))))


def write_report(path: str, payload: dict, *, title: str, headline: str = "",
                 note: str = "") -> str:
    """Render and write the page, ATOMICALLY. Returns the path written.

    `open(path, "w")` truncates the moment it is called, so rendering INSIDE the
    with-block meant any failure left a zero-byte file behind — a link the
    operator could click that opened a blank page. Measured 2026-08-20: an
    archive run for PI raised "rows have inconsistent keys" from _pack and left
    `archive-91239ab0-20260820.html` at 0 bytes, which read as "the backtest
    produced no result".

    So: render first, write to a temp file, then rename over the target. A
    failed build now leaves the PREVIOUS report intact and raises, instead of
    replacing it with nothing.
    """
    html = render(payload, title=title, headline=headline, note=note)
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, f".{os.path.basename(path)}.part")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(html)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return path


def round_trip_cost(fee: float, book: dict) -> float:
    """What one full trade costs, in and out, as a FRACTION.

    ONE definition, called by the local sweep and the GitHub shards alike.
    They each had their own and the two disagreed, which meant a coin measured
    on the Mac and the same coin measured in the cloud were scored against
    different costs.

    `mexc_futures.book_cost` returns slippage as the average fill price versus
    MID, so half the spread is ALREADY inside that number. Adding `spread / 2`
    on top charges the top of the book twice. Measured on live books
    2026-08-25: APEX slippage 0.0689% against a spread of 0.1379% — exactly
    half, as the definition implies — so the extra term made the round trip
    0.3558% instead of 0.2179%, a factor of 1.63. PROVE ran 1.42x. BTC, whose
    spread is a rounding error, was unaffected, which is why this survived.

    It matters twice over: the figure is printed as COST/TP beside every
    recommendation, and the liquidity gate SKIPS a combination whose cost
    reaches half its target — so an inflated cost silently withheld
    combinations that are in fact viable.
    """
    return 2.0 * (float(fee) + float(book.get("slippage") or 0.0))


def _prog_takes_counts(progress) -> bool:
    """Does this progress callback want the real (done, total) as well as the
    fraction? A UI that prints a counter needs the counts: rescaling 16/3960 to
    a 0-100 bar rounds to `0/100`, which sits beside a message saying 16/3960
    and reads as a stalled run."""
    import inspect
    try:
        ps = [x for x in inspect.signature(progress).parameters.values()
              if x.kind in (x.POSITIONAL_ONLY, x.POSITIONAL_OR_KEYWORD)]
        return len(ps) >= 4 or any(x.kind == x.VAR_POSITIONAL
                                   for x in inspect.signature(progress).parameters.values())
    except (TypeError, ValueError):
        return False


# How many rows the PAGE keeps. The snapshot always keeps every row; this
# bounds only what is held in memory and handed to the renderer. A
# market-wide 2-month sweep measured 21,278,772 combinations by
# 2026-08-26 -- about 30 GB as Python dicts -- and the fold died with
# MemoryError on a 17.1 GB machine after 2,367 pairs of correct measuring.
# Per-coin and few-coin runs (the app's own buttons, ~8k rows a pair) stay
# far under this, so their pages are unchanged; a market run is capped and
# SAYS SO (rule 20: a capped grid says what it capped).
DEFAULT_ROW_CAP = 250_000


def grid_from_store(coins: Sequence[str], tfs: Sequence[str], *,
                    base_margin: float = 5.0, days: int = 365,
                    thresholds: int = 3,
                    deployed: Sequence[dict] | None = None,
                    progress: Callable[[str, float], None] | None = None,
                    embed_limit: int = 4,
                    workers: int = 0, fresh: bool = False,
                    row_cap: int = DEFAULT_ROW_CAP,
                    grid_label: str = "grid") -> dict:
    """A ``run_grid``-shaped payload that READS THE STORE FIRST.

    The operator's rule: "when doing analysis its not doing from scratch."
    Each (coin, timeframe) is served by ``market_sweep.run_pair`` — rows on
    disk, per-combination resume state, only new bars computed.

    ``thresholds`` defaults to 3 and MUST match every other caller: the store
    stamps its version as ``signals<N>-th<K>``, so two paths using different
    K reset each other's store on every alternation — BACKTEST at th1 and
    UPDATE at th3 would silently recompute the world each time. Deployed
    combinations missing from the store are computed once (rule 21) and folded
    in. The payload carries a ``reuse`` block so every page can SAY what was
    reused versus fresh — a cached number the reader cannot trace is a wrong
    number waiting to happen.
    """

    import tradingagents.auto_trader as at
    from tradingagents import market_sweep as msw

    deployed = [dict(d, th=(d.get("th", 0.0)
                            if d.get("signal") in THRESH_SIGNALS else 0.0))
                for d in (deployed or [])]
    rows: list = []
    meta: dict = {}
    series: dict = {}
    excluded: list = []
    reuse = {"stored_rows": 0, "new_bars": 0, "recomputed_rows": 0,
             "fresh_pairs": [], "deployed_computed": 0}
    total = max(1, len(coins) * len(tfs))
    done = 0
    # ---- MEASURE. One pair per core: this was a serial nested loop, so a
    # 27-pair sweep used one of the machine's eight cores. Pairs are
    # independent (own row file, own state file, per-pair lock before either
    # write), and PROCESSES rather than threads because each pair mutates
    # at.STRATEGY_SPECS, which is not thread-safe. One core is left free: the
    # trading runner and the API live on this machine too.
    #
    # Only the MEASURING is parallel. The folding below stays single-threaded
    # and unchanged, so the parallel and serial paths cannot drift.
    pairs = [(sym, tf) for sym in coins for tf in tfs]
    # PAIRS ALREADY MEASURED COUNT TOWARD DONE.
    #
    # `done` used to start at zero every run, so it reported progress for THIS
    # PROCESS rather than for the sweep. When the supervisor resumed a crashed
    # job the bar restarted from 0: on 2026-08-23 it read "204 of 3960 (5.2%)"
    # while 2,947 pairs -- 74.4% -- were measured and on disk, and the operator
    # had watched it go BACKWARDS from an earlier run's 466.
    #
    # Seeded once at startup (113s over 3,960 pairs, one tail read per state
    # file), never per tick. A from-scratch run starts at zero by definition.
    _counts = _prog_takes_counts(progress) if progress else False
    _seen: set = set() if fresh else msw.completed_pairs(pairs)
    done = len(_seen)
    if progress:
        # publish the seeded figure at once, or the bar shows 0 until the
        # first pair of THIS run finishes -- minutes on a big sweep
        _m = f"resuming: {done} of {total} pairs already measured"
        if _counts:
            progress(_m, done / total, done, total)
        else:
            progress(_m, done / total)
    n_workers = workers if workers > 0 else max(1, (os.cpu_count() or 2) - 1)
    n_workers = max(1, min(n_workers, len(pairs)))
    measured: list = []

    if n_workers > 1:
        import concurrent.futures as _cf

        msw.worker_clear()
        # NOT `with pool:`. The with-block's exit is shutdown(wait=True), which
        # waits for EVERY queued pair -- 4,985 were submitted up front -- before
        # an exception can leave the block. On 2026-08-25 the STOP button raised
        # _StopRequested at pair 129 and the job then sat in __exit__ for the
        # rest of the sweep (py-spy: MainThread in shutdown/join, exc_val
        # _StopRequested), still measuring, `done` frozen, unstoppable except by
        # killing it. A stop, a hand-off or an error now CANCELS the queue and
        # waits only for the pairs already in a worker -- "finish the current
        # task", exactly as the operator asked -- then propagates.
        pool = _cf.ProcessPoolExecutor(max_workers=n_workers,
                                       initializer=msw.be_polite)
        try:
            if True:
                # no slot= : `i % n_workers` labelled the TASK, not the
                # worker, so a finished task's line sat on screen as an idle
                # core. Each worker publishes under its own pid.
                def _submit(sym, tf):
                    return pool.submit(msw.run_pair, sym, tf, slot=None,
                                       base_margin=base_margin, days=days,
                                       thresholds=thresholds, fresh=fresh)

                def _say(msg):
                    if not progress:
                        return
                    if _counts:
                        progress(msg, done / total, done, total)
                    else:
                        progress(msg, done / total)

                # A dict rather than as_completed(): a failed pair is put back
                # into the SAME pool, so the work set grows while the run does.
                futs = {_submit(sym, tf): (sym, tf) for sym, tf in pairs}
                tries: dict = {}
                while futs:
                    ready, _ = _cf.wait(list(futs),
                                        return_when=_cf.FIRST_COMPLETED)
                    for fut in ready:
                        sym, tf = futs.pop(fut)
                        show = sym.replace("_USDT", "")
                        try:
                            res = fut.result()
                        except Exception as exc:   # one pair dying is not the run
                            # Operator, 2026-08-25: "if a coin fails, delete the
                            # backtest then redo again the last failed job (not
                            # the whole)". Delete FIRST -- a pair that raised
                            # part-way has rows on disk and a state file whose
                            # watermark is stale, and measuring on top of that
                            # leaves one coin holding a mixture of two runs.
                            n = tries.get((sym, tf), 0)
                            if n < msw.PAIR_RETRIES:
                                tries[(sym, tf)] = n + 1
                                msw.discard_pair(show, tf)
                                futs[_submit(sym, tf)] = (sym, tf)
                                _say(f"{show} {tf}: failed "
                                     f"({str(exc)[:40]}) · discarded, redoing "
                                     f"{n + 1}/{msw.PAIR_RETRIES}")
                                continue
                            # out of retries: it is excluded, and only NOW does
                            # it count as done
                            excluded.append({"coin": show, "tf": tf,
                                             "why": f"worker: {str(exc)[:60]}"})
                            _seen.add((sym, tf))
                            done = len(_seen)
                            _say(f"{show} {tf}: gave up after "
                                 f"{msw.PAIR_RETRIES} retries ({done}/{total})")
                            continue
                        _seen.add((sym, tf))
                        done = len(_seen)     # DISTINCT pairs, so one that was
                                              # already measured is not counted twice
                        _say(f"{show} {tf}: done ({done}/{total})")
                        measured.append((sym, tf, res))
        except _cf.process.BrokenProcessPool:
            pool.shutdown(wait=False, cancel_futures=True)
            # The pool itself could not start — spawn needs an importable
            # __main__, so a caller running from stdin or a REPL has none. Fall
            # back to measuring in-process rather than returning a ZERO-ROW
            # backtest, which is the failure mode that looks like success.
            #
            # ONLY that. This was `except Exception`, which also swallowed
            # everything the progress callback raises on purpose —
            # _StopRequested (the STOP button), _HandOff (switch to GitHub),
            # _LowDisk — and, on 2026-08-25 on Windows, a PermissionError from
            # the progress file. Each became "measured, done = [], 0" followed
            # by the with-block's exit, which waits for EVERY pending pair: the
            # job ran to the end with `done` frozen at 64 of 4,985 and no button
            # could stop it. Anything else now propagates to the job runner,
            # which names it.
            measured, done = [], 0
            n_workers = 1
        except BaseException:
            # drop the queue, let the pairs already running checkpoint, go
            pool.shutdown(wait=True, cancel_futures=True)
            raise
        else:
            pool.shutdown(wait=True)
        msw.worker_clear()

    if n_workers <= 1 and not measured:
        for sym, tf in pairs:
            if progress:
                _msg = f"{sym.replace('_USDT', '')} {tf}: reading the store"
                if _counts:
                    progress(_msg, done / total, done, total)
                else:
                    progress(_msg, done / total)
            measured.append((sym, tf, msw.run_pair(
                sym, tf, base_margin=base_margin, days=days,
                thresholds=thresholds, fresh=fresh)))
            _seen.add((sym, tf))
            done = len(_seen)

    # ---- FOLD, STREAMING. Every row goes to the snapshot as its pair is read
    # and is then let go; only a bounded selection stays in memory for the
    # page. `rows += pair_rows(...)` over the whole market is what died with
    # MemoryError at 5:20am on 2026-08-26 -- 15.40 GB of row JSON on a 17.1 GB
    # machine -- after the measuring itself had gone perfectly.
    import heapq

    from tradingagents import parquet_store as pqs

    cap = int(row_cap) if row_cap and int(row_cap) > 0 else 0
    sink = pqs.GridSink(label=grid_label)

    def _combo(r: dict) -> tuple:
        return (r["coin"], r["tf"], r["signal"], round(float(r.get("th") or 0), 3),
                round(float(r["sl"]), 3), round(float(r["tp"]), 3), r["sizing"])

    want_deployed = {_combo(d) for d in deployed}
    seen_deployed: set = set()
    must_keep: list = []      # the operator's own rows: never capped away
    heap: list = []           # the best `cap` of the rest, by profit
    months_seen: set = set()
    rows_total = profitable_total = trades_total = 0
    order = 0

    def _take(row: dict) -> None:
        nonlocal order
        k = _combo(row)
        if k in want_deployed:
            seen_deployed.add(k)
            must_keep.append(row)          # rule 21: it must be on the page
            return
        if not cap:
            must_keep.append(row)
            return
        order += 1
        item = (float(row.get("profit") or 0.0), order, row)
        if len(heap) < cap:
            heapq.heappush(heap, item)
        elif item[0] > heap[0][0]:
            heapq.heapreplace(heap, item)

    for sym, tf, r in measured:
        show = sym.replace("_USDT", "")
        # "no new bars" is SUCCESS — the store answers in full. Only a why
        # with nothing behind it (fetch failed, too young, venue error)
        # excludes the pair.
        if r.get("why") not in (None, "", "no new bars") and not r.get("rows"):
            excluded.append({"coin": show, "tf": tf, "why": r["why"]})
            continue
        pair = msw.pair_rows(show, tf)
        sink.add(pair)                     # the snapshot keeps EVERY row
        rows_total += len(pair)
        for row in pair:
            trades_total += int(row.get("trades") or 0)
            if (row.get("profit") or 0) > 0:
                profitable_total += 1
            months_seen.update(row.get("monthly") or {})
            _take(row)
        if r.get("incremental"):
            fresh_n = (0 if r.get("why") == "no new bars"
                       else len(r.get("rows") or []))
            reuse["stored_rows"] += max(0, len(pair) - fresh_n)
            reuse["new_bars"] += int(r.get("new_bars") or 0)
            reuse["recomputed_rows"] += fresh_n
        else:
            reuse["fresh_pairs"].append(f"{show} {tf}")
        meta[f"{show}|{tf}"] = {
            "bars": r.get("bars", 0), "days": r.get("days", 0),
            "rt": (None if r.get("rt") is None
                   else round(r["rt"] * 100, 4)),
            "liq": round(r.get("liq") or 0, 3),
            "fee": r.get("fee") or 0}
    # rule 21: the exact live combination must exist on the page. Computed
    # before the snapshot closes, so the record holds it too.
    for d in deployed:
        if _combo(d) in seen_deployed or d["tf"] not in tfs:
            continue
        got = msw.compute_combos(f"{d['coin']}_USDT", d["tf"], [d],
                                 base_margin=base_margin, days=days)
        sink.add(got)
        rows_total += len(got)
        for row in got:
            months_seen.update(row.get("monthly") or {})
            trades_total += int(row.get("trades") or 0)
            if (row.get("profit") or 0) > 0:
                profitable_total += 1
            must_keep.append(row)
        reuse["deployed_computed"] += len(got)
    grid_path = sink.close()
    rows = must_keep + [it[2] for it in sorted(heap, key=lambda it: -it[0])]
    rows_capped = rows_total > len(rows)
    months = sorted(months_seen, reverse=True)
    for r in rows:
        if "mon" not in r:
            r["mon"] = [(r.get("monthly") or {}).get(m) for m in months]
        r.pop("monthly", None)
        r["id"] = row_code(r["coin"], r["tf"], r["signal"], r.get("th", 0),
                           r["sl"], r["tp"], r["sizing"])
        r.setdefault("tpd", round(r["trades"] / max(r.get("days", 1), 1), 2))
        r.setdefault("stop_reachable", True)
        r.setdefault("gate", "ok")
    # Store rows come from different eras — some carry funding/wstreak, some
    # 'why', some neither — and the payload packer refuses ragged rows rather
    # than silently dropping fields. Normalise to the UNION of keys, absent
    # values None, and pad month arrays to the shared header. One crash on
    # 2026-08-20 finished 100% of PI's compute and then died exactly here.
    all_keys: list = []
    seen_keys = set()
    for r in rows:
        for k in r:
            if k not in seen_keys:
                seen_keys.add(k)
                all_keys.append(k)
    for r in rows:
        for k in all_keys:
            r.setdefault(k, None)
        m = r.get("mon") or []
        if len(m) < len(months):
            r["mon"] = list(m) + [None] * (len(months) - len(m))
    # candles for in-page replay, from the cache — but only for small pages;
    # a market-wide payload would blow the size cap (kit item F's lesson)
    if 0 < len(meta) <= embed_limit:
        for key in meta:
            show, tf = key.split("|")
            df = msw.cached_candles(f"{show}_USDT", tf)
            if df is None or not len(df):
                continue
            hi = [float(x) for x in df["High"]]
            lo = [float(x) for x in df["Low"]]
            cl = [float(x) for x in df["Close"]]
            op = [float(x) for x in df["Open"]]
            vol = ([float(x) for x in df["Volume"]]
                   if "Volume" in df.columns else None)
            ts = list(df["Date"].to_numpy().astype("datetime64[ms]")
                      .astype("int64"))
            fund = []
            try:
                from tradingagents.dataflows import mexc_futures as fx

                fund = [[int(f["settle_ms"]), round(f["rate"], 8)]
                        for f in fx.funding_history(f"{show}_USDT")
                        if int(ts[0]) <= int(f["settle_ms"]) <= int(ts[-1])]
            except Exception:
                pass
            sd = {"o": [_round_sig(x) for x in op],
                  "h": [_round_sig(x) for x in hi],
                  "l": [_round_sig(x) for x in lo],
                  "c": [_round_sig(x) for x in cl],
                  "t": [str(x)[:16] for x in df["Date"]],
                  "fee": meta[key]["fee"], "liq": meta[key]["liq"],
                  "fund": fund, "d": {}}
            wanted = {(r["signal"], r.get("th", 0)) for r in rows
                      if r["coin"] == show and r["tf"] == tf}
            iv, bs, cap = TFS[tf]
            for sig, thp in wanted:
                k2 = f"{sig}_gfs_{tf}"
                at.STRATEGY_SPECS[k2] = {"interval": iv, "bar_seconds": bs,
                                         "tp": .02, "sl": .01,
                                         "threshold": (thp / 100) or .003}
                try:
                    dk = "rsi14_1h" if sig == "rsi14" else k2
                    dirs = at._dirs_for_backtest(dk, hi, lo, cl, opens=op,
                                                 volume=vol, ts=ts)
                    sd["d"][f"{sig}|{thp:g}"] = "".join(
                        "u" if x > 0 else "d" if x < 0 else "n" for x in dirs)
                except Exception:
                    pass
                at.STRATEGY_SPECS.pop(k2, None)
            series[key] = sd
    return {"rows": rows, "rows_total": rows_total,
            "rows_capped": rows_capped, "row_cap": cap,
            "grid_path": (str(grid_path) if grid_path else ""),
            "profitable_total": profitable_total,
            "trades_total": trades_total,
            "schema_extra": list(sink.extra_keys),
            "meta": meta, "series": series, "months": months,
            "cur": months[0] if months else "", "lev": at.LEVERAGE,
            "slip": 0.0003, "base": base_margin,
            "ladder": [1, 1, 2, 2, 4, 4, 8], "deployed": list(deployed),
            "excluded": excluded, "days_asked": days,
            "fetched": __import__("tradingagents.market_sweep", fromlist=["fmt_stamp"]).fmt_stamp(), "reuse": reuse}
