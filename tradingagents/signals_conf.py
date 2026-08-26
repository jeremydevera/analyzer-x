"""The ten CONFLUENCE setups from the research ledger, each at three levels.

Where these come from: on 2026-08-25 the operator asked for deep research into
"the best confluence out there", from reliable sources only. Six researchers
swept indicator confluence, ICT/SMC, the academic evidence, volatility and
regime filters, crypto-native signals and the skeptic's case; a verifier graded
every candidate and dropped the ones that were not crisply codeable or whose
sources did not support the claim. Ten survived. They were then measured on
BTC_USDT 1h over 364 days (published artifact, 6,160 combinations) before being
brought in here.

A "confluence" setup is two or more independent conditions that must agree
before a trade is taken. Each of the ten is registered three times:

  ``cf_x``      the setup alone
  ``cf_x_l1``   LEVEL 1 -- and price must be on the right side of its 200-bar
                moving average, and an engulfing candle must have printed
                within the last three bars
  ``cf_x_l2``   LEVEL 2 -- level 1, and at least TWO of six independent things
                must agree within 0.3xATR(14) of the entry price: a swing high
                or low, a 50/200 moving average, a 0.5/0.618 Fibonacci
                retracement of the last 50-bar swing, a Bollinger band edge, a
                classic pivot level from the previous day, or the
                highest-volume price of the last 200 bars

Two measured facts shaped the code, both from the BTC study:

* **The engulfing pattern needed rewriting for a perpetual.** The textbook
  form requires the bar to OPEN past the previous close. Measured on BTC 1h,
  8,757 of 8,759 bars open EXACTLY at the previous close -- a perpetual trades
  continuously -- so the gap form fired once in a year and level 1 scored zero
  signals. The continuous-market form is used: opposite colours, the close
  beyond the previous bar's open, and a body at least as large as the one it
  engulfs (1,114 bullish occurrences in that year).
* **Every lookback here is <= 200 bars.** ``market_sweep.CONTEXT_BARS`` is 300,
  so an incremental pass hands a rule 300 bars of history before the first new
  bar. A rule reading further back would compute one thing on a full run and
  another on a resumed one -- the same key quietly meaning two different rules.
  The BTC study used a 720-bar (30-day) trend gate for ``cf_mom`` and a 480-bar
  one for ``cf_donch``; both are SMA(200) here, and that is why those two rows
  will not match the published BTC numbers to the cent. ``cf_ttm`` and the rest
  read 20-50 bars and do match.

Same contract as :mod:`signals_ext2`: ``(opens, high, low, close, volume, ts)``,
one direction per bar (1 long, -1 short, 0 nothing), a bar may read only itself
and the bars BEFORE it, and a rule whose stream is missing ABSTAINS with zeros
rather than guessing. Swing pivots are CONFIRMED: a pivot centred at bar i is
not known until i+L bars have printed, so it is published at i+L.
"""
from __future__ import annotations

import math

from tradingagents.signals_ext import _atr, _ema
from tradingagents.signals_ext2 import _ok, _sma, _stdev, _zeros

_DAY_MS = 86_400_000
_NAMES = ("mom", "donch", "maobv", "triple", "chan",
          "soup", "emarsi", "ttm", "soup1", "eqhl")


# --------------------------------------------------------------- small helpers
def _rma(vals, n):
    """Wilder's smoothing, as ATR and RSI use. NaN in, skipped."""
    out, e = [math.nan] * len(vals), None
    for i, v in enumerate(vals):
        if v is None or (isinstance(v, float) and math.isnan(v)):
            continue
        e = v if e is None else (e * (n - 1) + v) / n
        out[i] = e
    return out


def _rsi(close, n=14):
    up, dn = [math.nan] * len(close), [math.nan] * len(close)
    for i in range(1, len(close)):
        d = close[i] - close[i - 1]
        up[i], dn[i] = max(d, 0.0), max(-d, 0.0)
    au, ad = _rma(up, n), _rma(dn, n)
    out = [math.nan] * len(close)
    for i in range(len(close)):
        if math.isnan(au[i]) or math.isnan(ad[i]):
            continue
        out[i] = 100.0 if ad[i] == 0 else 100 - 100 / (1 + au[i] / ad[i])
    return out


def _obv(close, volume):
    out, run = [0.0] * len(close), 0.0
    for i in range(1, len(close)):
        if close[i] > close[i - 1]:
            run += volume[i]
        elif close[i] < close[i - 1]:
            run -= volume[i]
        out[i] = run
    return out


def _cmf(high, low, close, volume, n=20):
    """Chaikin Money Flow -- where in each bar's range it closed, volume-weighted."""
    mfv = [0.0] * len(close)
    for i in range(len(close)):
        rng = high[i] - low[i]
        mfv[i] = 0.0 if rng <= 0 else (
            ((close[i] - low[i]) - (high[i] - close[i])) / rng * volume[i])
    out = [math.nan] * len(close)
    for i in range(n - 1, len(close)):
        v = sum(volume[i - n + 1:i + 1])
        out[i] = 0.0 if v <= 0 else sum(mfv[i - n + 1:i + 1]) / v
    return out


def _pivots(high, low, L):
    """The newest CONFIRMED swing high/low as of each bar, and its index.

    A pivot centred at bar c is only knowable at c+L. Publishing it earlier is
    lookahead: the backtest would trade a level the market had not drawn yet.
    """
    ph = [math.nan] * len(high)
    pl = [math.nan] * len(low)
    last_h = last_l = math.nan
    for i in range(len(high)):
        c = i - L
        if c - L >= 0:
            if high[c] == max(high[c - L:c + L + 1]):
                last_h = high[c]
            if low[c] == min(low[c - L:c + L + 1]):
                last_l = low[c]
        ph[i], pl[i] = last_h, last_l
    return ph, pl


def _roll_max(vals, n, shift=1):
    """Highest of the n bars ENDING `shift` bars ago -- a breakout has to clear
    a level that already existed."""
    out = [math.nan] * len(vals)
    for i in range(len(vals)):
        a, b = i - shift - n + 1, i - shift + 1
        if a >= 0:
            out[i] = max(vals[a:b])
    return out


def _roll_min(vals, n, shift=1):
    out = [math.nan] * len(vals)
    for i in range(len(vals)):
        a, b = i - shift - n + 1, i - shift + 1
        if a >= 0:
            out[i] = min(vals[a:b])
    return out


def _bars_per_day(ts) -> int:
    """How many bars a day holds, from the bars' own spacing."""
    if not ts or len(ts) < 3:
        return 0
    gaps = sorted(int(ts[i + 1]) - int(ts[i]) for i in range(min(50, len(ts) - 1)))
    step = gaps[len(gaps) // 2]
    if step <= 0:
        return 0
    return max(1, round(_DAY_MS / step))


# ------------------------------------------------------------------- the bundle
# 30 registered rules would otherwise recompute the same indicators 30 times per
# pair. The bundle is built once and memoised on the series itself.
_CACHE: dict = {}
_CACHE_MAX = 6


def _bundle(opens, high, low, close, volume, ts):
    key = (len(close), close[0], close[-1], high[-1], low[0],
           (volume[-1] if volume else 0), (int(ts[0]) if ts else 0))
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    b = {}
    b["a14"] = _atr(high, low, close, 14)
    b["a20"] = _atr(high, low, close, 20)
    b["a200"] = _atr(high, low, close, 200)
    b["rsi14"] = _rsi(close, 14)
    b["s5"] = _sma(close, 5)
    b["s20"] = _sma(close, 20)
    b["s50"] = _sma(close, 50)
    b["s200"] = _sma(close, 200)
    b["e20"] = _ema(close, 20)
    b["e50"] = _ema(close, 50)
    b["e200"] = _ema(close, 200)
    b["sd20"] = _stdev(close, 20)
    b["hh20"] = _roll_max(high, 20)
    b["ll20"] = _roll_min(low, 20)
    b["hh50"] = _roll_max(high, 50)
    b["ll50"] = _roll_min(low, 50)
    b["ph10"], b["pl10"] = _pivots(high, low, 10)
    b["ph5"], b["pl5"] = _pivots(high, low, 5)
    b["ph3"], b["pl3"] = _pivots(high, low, 3)
    if volume:
        b["v20"] = _sma(volume, 20)
        b["cmf20"] = _cmf(high, low, close, volume, 20)
        ob = _obv(close, volume)
        b["obv5"], b["obv50"] = _sma(ob, 5), _sma(ob, 50)
    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.clear()
    _CACHE[key] = b
    return b


def _nan(*vals) -> bool:
    return any(v is None or (isinstance(v, float) and math.isnan(v)) for v in vals)


# ----------------------------------------------------------------- the ten
def _mom(opens, high, low, close, volume, ts, b):
    """Momentum with a trend gate: a 48-bar move past 3%, in the SMA200's
    direction. (The published BTC study gated on a 30-day SMA; 200 bars here,
    for the incremental-lookback reason in the module docstring.)"""
    out = _zeros(close)
    L, TH = 48, 0.03
    for i in range(L, len(close)):
        if _nan(b["s200"][i]) or close[i - L] <= 0:
            continue
        ret = close[i] / close[i - L] - 1
        if ret > TH and close[i] > b["s200"][i]:
            out[i] = 1
        elif ret < -TH and close[i] < b["s200"][i]:
            out[i] = -1
    return out


def _donch(opens, high, low, close, volume, ts, b):
    """Trend gate + 20-bar Donchian breakout + volume or money-flow behind it."""
    if not _ok(volume, close):
        return _zeros(close)
    out = _zeros(close)
    for i in range(len(close)):
        if _nan(b["s200"][i], b["hh20"][i], b["ll20"][i], b["v20"][i], b["cmf20"][i]):
            continue
        pushed = volume[i] >= 1.5 * b["v20"][i]
        if close[i] > b["s200"][i] and close[i] > b["hh20"][i] and (pushed or b["cmf20"][i] > 0.05):
            out[i] = 1
        elif close[i] < b["s200"][i] and close[i] < b["ll20"][i] and (pushed or b["cmf20"][i] < -0.05):
            out[i] = -1
    return out


def _maobv(opens, high, low, close, volume, ts, b):
    """A 5/50 moving-average cross that on-balance volume agrees with."""
    if not _ok(volume, close):
        return _zeros(close)
    out = _zeros(close)
    for i in range(1, len(close)):
        if _nan(b["s5"][i], b["s50"][i], b["s5"][i - 1], b["s50"][i - 1],
                b["obv5"][i], b["obv50"][i]):
            continue
        up = b["s5"][i] > b["s50"][i] * 1.001 and b["s5"][i - 1] <= b["s50"][i - 1] * 1.001
        dn = b["s5"][i] < b["s50"][i] * 0.999 and b["s5"][i - 1] >= b["s50"][i - 1] * 0.999
        if up and b["obv5"][i] > b["obv50"][i]:
            out[i] = 1
        elif dn and b["obv5"][i] < b["obv50"][i]:
            out[i] = -1
    return out


def _triple(opens, high, low, close, volume, ts, b):
    """All three moving averages agreeing (20 > 50 > 200), on the flip into it."""
    out = _zeros(close)
    for i in range(1, len(close)):
        if _nan(b["s20"][i], b["s50"][i], b["s200"][i], b["s20"][i - 1]):
            continue
        up = (close[i] > b["s20"][i] > b["s50"][i] > b["s200"][i])
        dn = (close[i] < b["s20"][i] < b["s50"][i] < b["s200"][i])
        was_up = close[i - 1] > b["s20"][i - 1]
        if up and not was_up:
            out[i] = 1
        elif dn and was_up:
            out[i] = -1
    return out


def _chan(opens, high, low, close, volume, ts, b):
    """A quiet 50-bar channel broken and HELD for a second bar."""
    out = _zeros(close)
    for i in range(2, len(close)):
        if _nan(b["hh50"][i], b["ll50"][i], b["hh50"][i - 1], b["ll50"][i - 1]) \
                or b["ll50"][i] <= 0:
            continue
        if (b["hh50"][i] - b["ll50"][i]) / b["ll50"][i] > 0.05:
            continue                                   # not quiet: no setup
        if close[i] > b["hh50"][i] * 1.002 and close[i - 1] > b["hh50"][i - 1] * 1.002:
            out[i] = 1
        elif close[i] < b["ll50"][i] * 0.998 and close[i - 1] < b["ll50"][i - 1] * 0.998:
            out[i] = -1
    return out


def _soup(opens, high, low, close, volume, ts, b):
    """ICT Turtle Soup: a confirmed swing is swept, price closes back inside,
    then it turns and leaves a fair-value gap behind, within five bars."""
    out = _zeros(close)
    for i in range(3, len(close)):
        for k in range(max(3, i - 5), i + 1):
            if _nan(b["ph10"][k], b["pl10"][k]):
                continue
            swept_h = high[k] > b["ph10"][k] and close[k] < b["ph10"][k]
            swept_l = low[k] < b["pl10"][k] and close[k] > b["pl10"][k]
            gap_dn = high[i] < low[i - 2]
            gap_up = low[i] > high[i - 2]
            if swept_h and close[i] < close[k] and gap_dn:
                out[i] = -1
                break
            if swept_l and close[i] > close[k] and gap_up:
                out[i] = 1
                break
    return out


def _emarsi(opens, high, low, close, volume, ts, b):
    """The EMA stack, an RSI pullback that re-crosses 50, and money flow."""
    if not _ok(volume, close):
        return _zeros(close)
    out = _zeros(close)
    r = b["rsi14"]
    for i in range(6, len(close)):
        if _nan(b["e20"][i], b["e50"][i], b["e200"][i], r[i], r[i - 1], b["cmf20"][i]):
            continue
        win = [r[j] for j in range(i - 5, i) if not _nan(r[j])]
        if not win:
            continue
        up_stack = b["e20"][i] > b["e50"][i] > b["e200"][i] and close[i] > b["e200"][i]
        dn_stack = b["e20"][i] < b["e50"][i] < b["e200"][i] and close[i] < b["e200"][i]
        if up_stack and 40.0 <= min(win) <= 50.0 and r[i - 1] <= 50 < r[i] \
                and b["cmf20"][i] > 0.05:
            out[i] = 1
        elif dn_stack and 50.0 <= max(win) <= 60.0 and r[i - 1] >= 50 > r[i] \
                and b["cmf20"][i] < -0.05:
            out[i] = -1
    return out


def _ttm(opens, high, low, close, volume, ts, b):
    """TTM squeeze: Bollinger inside Keltner for at least three bars, then the
    release, taken in the direction price leaves the band."""
    out = _zeros(close)
    on = [False] * len(close)
    for i in range(len(close)):
        if _nan(b["s20"][i], b["sd20"][i], b["e20"][i], b["a20"][i]):
            continue
        on[i] = (b["s20"][i] + 2 * b["sd20"][i] < b["e20"][i] + 1.5 * b["a20"][i]
                 and b["s20"][i] - 2 * b["sd20"][i] > b["e20"][i] - 1.5 * b["a20"][i])
    for i in range(4, len(close)):
        if _nan(b["s20"][i], b["sd20"][i]):
            continue
        if on[i] or not all(on[i - k] for k in (1, 2, 3)):
            continue                                   # still squeezed, or never was
        up = b["s20"][i] + 2 * b["sd20"][i]
        dn = b["s20"][i] - 2 * b["sd20"][i]
        if close[i] > b["s20"][i] and close[i] > up:
            out[i] = 1
        elif close[i] < b["s20"][i] and close[i] < dn:
            out[i] = -1
    return out


def _soup1(opens, high, low, close, volume, ts, b):
    """Connors-Raschke Turtle Soup +1: a new 20-bar low whose previous 20-bar
    low is at least four bars old, rejected on the bar."""
    out = _zeros(close)
    for i in range(25, len(close)):
        if _nan(b["ll20"][i], b["ll20"][i - 4], b["hh20"][i], b["hh20"][i - 4]):
            continue
        if low[i] < b["ll20"][i] and close[i] > low[i] and b["ll20"][i - 4] >= b["ll20"][i]:
            out[i] = 1
        elif high[i] > b["hh20"][i] and close[i] < high[i] and b["hh20"][i - 4] <= b["hh20"][i]:
            out[i] = -1
    return out


def _eqhl(opens, high, low, close, volume, ts, b):
    """Equal highs or lows -- a pool of stops -- swept, then a gap the other way.

    The sweep may be up to three bars back. The BTC study required the sweep
    and the gap on the SAME bar, which asks a bar to poke above the newest
    swing high AND close below the low of two bars earlier: it fired 4 times in
    a year, and mostly by coincidence. A pool is taken and THEN the market
    turns -- the same shape as Turtle Soup, which allows five bars.
    """
    out = _zeros(close)
    for i in range(4, len(close)):
        if _nan(b["a200"][i]):
            continue
        gap_dn = high[i] < low[i - 2]
        gap_up = low[i] > high[i - 2]
        if not (gap_dn or gap_up):
            continue
        for k in range(max(4, i - 3), i + 1):
            tol = 0.1 * b["a200"][k]
            if _nan(b["a200"][k]):
                continue
            pool_h = (not _nan(b["ph3"][k]) and abs(high[k] - b["ph3"][k]) <= tol
                      and high[k] > b["ph3"][k] and close[k] < b["ph3"][k])
            pool_l = (not _nan(b["pl3"][k]) and abs(low[k] - b["pl3"][k]) <= tol
                      and low[k] < b["pl3"][k] and close[k] > b["pl3"][k])
            if pool_h and gap_dn and close[i] < close[k]:
                out[i] = -1
                break
            if pool_l and gap_up and close[i] > close[k]:
                out[i] = 1
                break
    return out


_SETUPS = {"mom": _mom, "donch": _donch, "maobv": _maobv, "triple": _triple,
           "chan": _chan, "soup": _soup, "emarsi": _emarsi, "ttm": _ttm,
           "soup1": _soup1, "eqhl": _eqhl}


# ------------------------------------------------------------------ the levels
def _level1(opens, high, low, close, b):
    """A moving-average side, plus an engulfing candle within three bars.

    The continuous-market engulfing: opposite colours, the close beyond the
    previous bar's OPEN, body at least as large. The textbook form needs the
    bar to open past the previous close, which a perpetual almost never does
    (8,757 of 8,759 BTC 1h bars opened exactly AT the previous close).
    """
    n = len(close)
    bull = [False] * n
    bear = [False] * n
    for i in range(1, n):
        body, prev = abs(close[i] - opens[i]), abs(close[i - 1] - opens[i - 1])
        bull[i] = (close[i] > opens[i] and close[i - 1] < opens[i - 1]
                   and close[i] > opens[i - 1] and body >= prev)
        bear[i] = (close[i] < opens[i] and close[i - 1] > opens[i - 1]
                   and close[i] < opens[i - 1] and body >= prev)
    out = [0] * n
    for i in range(3, n):
        if _nan(b["s200"][i]):
            continue
        if close[i] > b["s200"][i] and (bull[i] or bull[i - 1] or bull[i - 2]):
            out[i] = 1
        elif close[i] < b["s200"][i] and (bear[i] or bear[i - 1] or bear[i - 2]):
            out[i] = -1
    return out


def _level2_hits(opens, high, low, close, volume, ts, b):
    """How many of six independent things sit within 0.3xATR of this close."""
    n = len(close)
    per_day = _bars_per_day(ts)
    piv = [None] * n
    if per_day:
        for i in range(per_day * 2, n):
            a, z = i - per_day * 2, i - per_day
            H, L, C = max(high[a:z]), min(low[a:z]), close[z - 1]
            P = (H + L + C) / 3
            piv[i] = (P, 2 * P - L, 2 * P - H)          # pivot, R1, S1
    poc = [math.nan] * n
    for i in range(200, n):
        lo_, hi_ = min(low[i - 200:i]), max(high[i - 200:i])
        if hi_ <= lo_:
            continue
        step = (hi_ - lo_) / 40.0
        buckets: dict = {}
        for j in range(i - 200, i):
            k = int((close[j] - lo_) / step) if step > 0 else 0
            buckets[k] = buckets.get(k, 0.0) + (volume[j] if volume else 1.0)
        best = max(buckets, key=buckets.get)
        poc[i] = lo_ + (best + 0.5) * step
    out = [0] * n
    for i in range(n):
        if _nan(b["a14"][i]) or b["a14"][i] <= 0:
            continue
        tol, p, hits = 0.3 * b["a14"][i], close[i], 0
        if (not _nan(b["ph5"][i]) and abs(p - b["ph5"][i]) <= tol) or \
           (not _nan(b["pl5"][i]) and abs(p - b["pl5"][i]) <= tol):
            hits += 1                                   # support / resistance
        if (not _nan(b["s50"][i]) and abs(p - b["s50"][i]) <= tol) or \
           (not _nan(b["s200"][i]) and abs(p - b["s200"][i]) <= tol):
            hits += 1                                   # a moving average
        if not _nan(b["hh50"][i], b["ll50"][i]) and b["hh50"][i] > b["ll50"][i]:
            span = b["hh50"][i] - b["ll50"][i]
            if any(abs(p - (b["hh50"][i] - f * span)) <= tol for f in (0.5, 0.618)):
                hits += 1                               # Fibonacci retracement
        if not _nan(b["s20"][i], b["sd20"][i]) and (
                p >= b["s20"][i] + 2 * b["sd20"][i] or p <= b["s20"][i] - 2 * b["sd20"][i]):
            hits += 1                                   # a Bollinger band edge
        if piv[i] and any(abs(p - lv) <= tol for lv in piv[i]):
            hits += 1                                   # a classic pivot level
        if not _nan(poc[i]) and abs(p - poc[i]) <= tol:
            hits += 1                                   # a volume cluster
        out[i] = hits
    return out


# ------------------------------------------------------------------ dispatch
def _gated(name, level):
    def rule(opens, high, low, close, volume, ts):
        if not _ok(opens, close) or len(close) < 5:
            return _zeros(close)                        # no opens: abstain
        b = _bundle(opens, high, low, close, volume, ts)
        dirs = _SETUPS[name](opens, high, low, close, volume, ts, b)
        if level == 0:
            return dirs
        l1 = _level1(opens, high, low, close, b)
        if level == 1:
            return [d if d and l1[i] == d else 0 for i, d in enumerate(dirs)]
        if not ts:
            return _zeros(close)     # level 2 needs the clock for pivot levels
        hits = _level2_hits(opens, high, low, close, volume, ts, b)
        return [d if d and l1[i] == d and hits[i] >= 2 else 0
                for i, d in enumerate(dirs)]
    rule.__name__ = f"cf_{name}" + (f"_l{level}" if level else "")
    rule.__doc__ = (_SETUPS[name].__doc__ or "").strip()
    return rule


CONF_SIGNALS = {}
for _n in _NAMES:
    CONF_SIGNALS[f"cf_{_n}"] = _gated(_n, 0)
    CONF_SIGNALS[f"cf_{_n}_l1"] = _gated(_n, 1)
    CONF_SIGNALS[f"cf_{_n}_l2"] = _gated(_n, 2)
