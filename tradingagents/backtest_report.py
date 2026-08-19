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
import time
from html import escape as html_escape
from typing import Callable, Iterable, Sequence

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
    fetched_at = time.strftime("%Y-%m-%d %H:%M")

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
                    for (sl, tp), sz, pl in itertools.product(
                            pairs, ("flat", "martingale"), plans):
                        # One position, several exits. `plans` defaults to
                        # (None,) — the single exit every existing row uses —
                        # so a page built without asking for splits reproduces
                        # exactly what it produced before.
                        _slx = slices_for(pl, sl, tp)
                        try:
                            r = at.backtest_strategy(
                                key, df, base_margin, fee=fee, sizing=sz,
                                dirs=dirs, tp=tp, sl=sl, liq_move_pct=liq,
                                funding=fund, slices=_slx)
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
                                show, tf, sig, thp, sl * 100, tp * 100, sz,
                                deployed, pl):
                            continue
                        a = at.backtest_strategy(
                            key, df.iloc[:half], base_margin, fee=fee,
                            sizing=sz, dirs=dirs[:half], tp=tp, sl=sl,
                            liq_move_pct=liq, funding=fund, slices=_slx)
                        b = at.backtest_strategy(
                            key, df.iloc[half:], base_margin, fee=fee,
                            sizing=sz, dirs=dirs[half:], tp=tp, sl=sl,
                            liq_move_pct=liq, funding=fund, slices=_slx)
                        ratio = None if rt is None else rt / tp
                        rows.append({
                            "coin": show, "tf": tf, "signal": sig,
                            "th": thp, "sl": round(sl * 100, 3),
                            "tp": round(tp * 100, 3), "rr": round(tp / sl, 2),
                            "sizing": sz, "lev": at.LEVERAGE,
                            # None on a single-exit row, so the field is on
                            # EVERY row rather than only the split ones
                            # (rule F: never drop a field from a subset).
                            "plan": pl,
                            "exits": 1 if not _slx else len(_slx),
                            "base": base_margin,
                            "notional": round(base_margin * at.LEVERAGE, 2),
                            "trades": r["trades"], "wins": r["wins"],
                            "losses": r["losses"],
                            "winrate": round(100 * r["wins"] / r["trades"], 2),
                            "profit": round(r["profit"], 2),
                            "h1": round(a["profit"], 2),
                            "h2": round(b["profit"], 2),
                            "green": r["months_green"],
                            "months": r["months_total"],
                            "worst": round(r["worst_trade"], 2),
                            "dd": round(r["max_dd"], 2),
                            "liqs": sum(1 for t in r["log"]
                                        if t["why"] == "LIQ"),
                            "stop_reachable": bool(liq is None
                                                   or sl * 100 < liq),
                            "days": hist_days,
                            "monthly": {k: round(v, 2)
                                        for k, v in r["monthly"].items()},
                            "cost_of_tp": (0.0 if ratio is None
                                           else round(ratio * 100, 1)),
                            "gate": ("unknown" if ratio is None
                                     else "block" if ratio >= GATE_BLOCK
                                     else "warn" if ratio >= .2 else "ok"),
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
    import copy

    p = dict(payload)
    rows = p.get("rows") or []
    if rows and not p.get("cols"):
        cols = list(rows[0].keys())
        keyset = set(cols)
        for r in rows:                    # a row with a different shape would
            if set(r.keys()) != keyset:   # silently lose fields to the header
                raise RuntimeError("rows have inconsistent keys; cannot pack")
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
        f"barrier grid &times; 2 sizings = <b>{len(payload['rows'])} "
        f"combinations</b>, all at {payload['lev']}x on a "
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
           if payload["excluded"] else ""))
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
    """Render and write the page. Returns the path written."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render(payload, title=title, headline=headline, note=note))
    return path
