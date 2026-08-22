"""Fifty-three more entry rules, researched wider at the operator's request.

The first expansion (:mod:`signals_ext`) added the classics the operator asked
for by name. This one adds the rest of the researched catalogue: trend systems
(Supertrend, PSAR, Ichimoku, ADX...), oscillators, mean reversion, breakouts,
the ICT/SMC set (order blocks, BOS, CHoCH, raids, Turtle Soup, OTE), candle
patterns, and — for the first time — VOLUME-based rules, which is why these
take the full candle: ``(opens, high, low, close, volume, ts)``.

``ts`` is epoch milliseconds per bar, needed by the session rules (opening
range, killzone, day-anchored VWAP). A rule that needs a stream the caller
could not provide returns all zeros — it abstains rather than guessing.

Every function returns a direction array — one entry per bar, ``1`` long,
``-1`` short, ``0`` nothing — and a bar may only read itself and the bars
BEFORE it. ``auto_trader._dirs_for_backtest`` dispatches by longest key
prefix, checking this registry before :mod:`signals_ext`.
"""
from __future__ import annotations

import math

from tradingagents.signals_ext import _atr, _ema

_DAY_MS = 86_400_000


def _zeros(close) -> list[int]:
    return [0] * len(close)


def _ok(stream, close) -> bool:
    return bool(stream) and len(stream) == len(close)


def _sma(vals, n):
    out = [math.nan] * len(vals)
    s = 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= n:
            s -= vals[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def _wma(vals, n):
    out = [math.nan] * len(vals)
    denom = n * (n + 1) / 2
    for i in range(n - 1, len(vals)):
        s = 0.0
        for j in range(n):
            s += vals[i - j] * (n - j)
        out[i] = s / denom
    return out


def _stdev(vals, n):
    out = [math.nan] * len(vals)
    for i in range(n - 1, len(vals)):
        w = vals[i - n + 1:i + 1]
        m = sum(w) / n
        out[i] = math.sqrt(sum((x - m) ** 2 for x in w) / n)
    return out


def _rsi_series(close, n=14):
    out = [math.nan] * len(close)
    if len(close) <= n:
        return out
    g = l = 0.0
    for i in range(1, n + 1):
        ch = close[i] - close[i - 1]
        if ch > 0:
            g += ch
        else:
            l -= ch
    ag, al = g / n, l / n
    out[n] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(n + 1, len(close)):
        ch = close[i] - close[i - 1]
        ag = (ag * (n - 1) + max(ch, 0)) / n
        al = (al * (n - 1) + max(-ch, 0)) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def _fractals(high, low):
    """Confirmed 2-2 swing points. Entry i lists swings CONFIRMED at bar i,
    i.e. the swing sits at bar i-2 and bars i-1, i closed without exceeding
    it — so reading the list at bar i never peeks forward."""
    n = len(high)
    highs: list[list[tuple[int, float]]] = [[] for _ in range(n)]
    lows: list[list[tuple[int, float]]] = [[] for _ in range(n)]
    for i in range(4, n):
        j = i - 2
        if high[j] == max(high[j - 2:j + 3]):
            highs[i].append((j, high[j]))
        if low[j] == min(low[j - 2:j + 3]):
            lows[i].append((j, low[j]))
    return highs, lows


# ------------------------------------------------------------------- trend
def supertrend(opens, high, low, close, volume, ts, n=10, mult=3.0):
    """ATR trailing band; emits on the flip bar."""
    atr = _atr(high, low, close, n)
    out = _zeros(close)
    trend = 0
    fu = fl = math.nan
    for i in range(len(close)):
        if math.isnan(atr[i]):
            continue
        mid = (high[i] + low[i]) / 2
        bu = mid + mult * atr[i]
        bl = mid - mult * atr[i]
        fu = bu if math.isnan(fu) or bu < fu or close[i - 1] > fu else fu
        fl = bl if math.isnan(fl) or bl > fl or close[i - 1] < fl else fl
        new = trend
        if trend <= 0 and close[i] > fu:
            new = 1
        elif trend >= 0 and close[i] < fl:
            new = -1
        if new != trend and trend != 0:
            out[i] = new
        if new != trend:
            fu, fl = bu, bl
        trend = new
    return out


def psar(opens, high, low, close, volume, ts, step=0.02, cap=0.2):
    """Parabolic SAR; emits on the reversal bar."""
    n = len(close)
    out = _zeros(close)
    if n < 3:
        return out
    up = close[1] > close[0]
    sar, ep, af = (low[0], high[1], step) if up else (high[0], low[1], step)
    for i in range(2, n):
        sar = sar + af * (ep - sar)
        if up:
            sar = min(sar, low[i - 1], low[i - 2])
            if high[i] > ep:
                ep, af = high[i], min(af + step, cap)
            if low[i] < sar:
                up, sar, ep, af = False, ep, low[i], step
                out[i] = -1
        else:
            sar = max(sar, high[i - 1], high[i - 2])
            if low[i] < ep:
                ep, af = low[i], min(af + step, cap)
            if high[i] > sar:
                up, sar, ep, af = True, ep, high[i], step
                out[i] = 1
    return out


def ichimoku(opens, high, low, close, volume, ts):
    """Tenkan/kijun cross on the right side of the cloud."""
    n = len(close)
    out = _zeros(close)

    def line(k, i):
        if i + 1 < k:
            return math.nan
        return (max(high[i - k + 1:i + 1]) + min(low[i - k + 1:i + 1])) / 2

    ten = [line(9, i) for i in range(n)]
    kij = [line(26, i) for i in range(n)]
    for i in range(27, n):
        j = i - 26                       # cloud drawn from 26 bars back
        sa = (ten[j] + kij[j]) / 2 if not math.isnan(ten[j]) else math.nan
        sb = line(52, j)
        if any(math.isnan(x) for x in (ten[i], kij[i], ten[i - 1],
                                       kij[i - 1], sa, sb)):
            continue
        top, bot = max(sa, sb), min(sa, sb)
        if ten[i - 1] <= kij[i - 1] and ten[i] > kij[i] and close[i] > top:
            out[i] = 1
        elif ten[i - 1] >= kij[i - 1] and ten[i] < kij[i] and close[i] < bot:
            out[i] = -1
    return out


def adx14(opens, high, low, close, volume, ts, n=14, floor=20.0):
    """+DI/-DI cross while ADX says there IS a trend."""
    m = len(close)
    out = _zeros(close)
    if m <= 2 * n:
        return out
    trs, pdms, ndms = [0.0], [0.0], [0.0]
    for i in range(1, m):
        trs.append(max(high[i] - low[i], abs(high[i] - close[i - 1]),
                       abs(low[i] - close[i - 1])))
        upm = high[i] - high[i - 1]
        dnm = low[i - 1] - low[i]
        pdms.append(upm if upm > dnm and upm > 0 else 0.0)
        ndms.append(dnm if dnm > upm and dnm > 0 else 0.0)
    tr = sum(trs[1:n + 1])
    pdm = sum(pdms[1:n + 1])
    ndm = sum(ndms[1:n + 1])
    pdi = [math.nan] * m
    ndi = [math.nan] * m
    adx = [math.nan] * m
    dxs = []
    for i in range(n, m):
        if i > n:
            tr = tr - tr / n + trs[i]
            pdm = pdm - pdm / n + pdms[i]
            ndm = ndm - ndm / n + ndms[i]
        pdi[i] = 100 * pdm / tr if tr else 0.0
        ndi[i] = 100 * ndm / tr if tr else 0.0
        s = pdi[i] + ndi[i]
        dxs.append(100 * abs(pdi[i] - ndi[i]) / s if s else 0.0)
        if len(dxs) == n:
            adx[i] = sum(dxs) / n
        elif len(dxs) > n:
            adx[i] = (adx[i - 1] * (n - 1) + dxs[-1]) / n
    for i in range(n + 1, m):
        if math.isnan(adx[i]) or adx[i] < floor:
            continue
        if pdi[i - 1] <= ndi[i - 1] and pdi[i] > ndi[i]:
            out[i] = 1
        elif pdi[i - 1] >= ndi[i - 1] and pdi[i] < ndi[i]:
            out[i] = -1
    return out


def aroon25(opens, high, low, close, volume, ts, n=25):
    """Aroon-up crossing aroon-down."""
    m = len(close)
    out = _zeros(close)
    au = [math.nan] * m
    ad = [math.nan] * m
    for i in range(n, m):
        w_h = high[i - n:i + 1]
        w_l = low[i - n:i + 1]
        au[i] = 100 * (n - (n - w_h.index(max(w_h)))) / n
        ad[i] = 100 * (n - (n - w_l.index(min(w_l)))) / n
    for i in range(n + 1, m):
        if math.isnan(au[i - 1]):
            continue
        if au[i - 1] <= ad[i - 1] and au[i] > ad[i]:
            out[i] = 1
        elif au[i - 1] >= ad[i - 1] and au[i] < ad[i]:
            out[i] = -1
    return out


def vortex14(opens, high, low, close, volume, ts, n=14):
    """VI+ crossing VI-."""
    m = len(close)
    out = _zeros(close)
    vp, vm, tr = [0.0], [0.0], [0.0]
    for i in range(1, m):
        vp.append(abs(high[i] - low[i - 1]))
        vm.append(abs(low[i] - high[i - 1]))
        tr.append(max(high[i] - low[i], abs(high[i] - close[i - 1]),
                      abs(low[i] - close[i - 1])))
    vip = [math.nan] * m
    vin = [math.nan] * m
    for i in range(n, m):
        t = sum(tr[i - n + 1:i + 1])
        if t:
            vip[i] = sum(vp[i - n + 1:i + 1]) / t
            vin[i] = sum(vm[i - n + 1:i + 1]) / t
    for i in range(n + 1, m):
        if math.isnan(vip[i - 1]) or math.isnan(vip[i]):
            continue
        if vip[i - 1] <= vin[i - 1] and vip[i] > vin[i]:
            out[i] = 1
        elif vip[i - 1] >= vin[i - 1] and vip[i] < vin[i]:
            out[i] = -1
    return out


def hull20(opens, high, low, close, volume, ts, n=20):
    """Hull MA slope flip."""
    half = _wma(close, n // 2)
    full = _wma(close, n)
    raw = [2 * a - b if not (math.isnan(a) or math.isnan(b)) else math.nan
           for a, b in zip(half, full, strict=False)]
    k = int(math.sqrt(n))
    hma = [math.nan] * len(close)
    for i in range(len(close)):
        w = raw[max(0, i - k + 1):i + 1]
        if len(w) == k and not any(math.isnan(x) for x in w):
            denom = k * (k + 1) / 2
            hma[i] = sum(v * (j + 1) for j, v in enumerate(w)) / denom
    out = _zeros(close)
    for i in range(2, len(close)):
        if any(math.isnan(x) for x in (hma[i - 2], hma[i - 1], hma[i])):
            continue
        was, now = hma[i - 1] - hma[i - 2], hma[i] - hma[i - 1]
        if was <= 0 < now:
            out[i] = 1
        elif was >= 0 > now:
            out[i] = -1
    return out


def kama10(opens, high, low, close, volume, ts, n=10):
    """Price crossing Kaufman's adaptive MA."""
    m = len(close)
    out = _zeros(close)
    if m <= n + 1:
        return out
    fast, slow = 2 / 3, 2 / 31
    kama = [math.nan] * m
    kama[n] = close[n]
    for i in range(n + 1, m):
        change = abs(close[i] - close[i - n])
        vol_sum = sum(abs(close[j] - close[j - 1])
                      for j in range(i - n + 1, i + 1))
        er = change / vol_sum if vol_sum else 0.0
        sc = (er * (fast - slow) + slow) ** 2
        kama[i] = kama[i - 1] + sc * (close[i] - kama[i - 1])
        if close[i - 1] <= kama[i - 1] and close[i] > kama[i]:
            out[i] = 1
        elif close[i - 1] >= kama[i - 1] and close[i] < kama[i]:
            out[i] = -1
    return out


def trix15(opens, high, low, close, volume, ts, n=15):
    """1-bar rate of change of a triple EMA, zero cross."""
    e3 = _ema(_ema(_ema(close, n), n), n)
    out = _zeros(close)
    for i in range(3 * n, len(close)):
        was = e3[i - 1] - e3[i - 2]
        now = e3[i] - e3[i - 1]
        if was <= 0 < now:
            out[i] = 1
        elif was >= 0 > now:
            out[i] = -1
    return out


def gmma(opens, high, low, close, volume, ts):
    """Guppy: every fast EMA above every slow EMA (event on alignment)."""
    fast = [_ema(close, k) for k in (3, 5, 8, 10, 12, 15)]
    slow = [_ema(close, k) for k in (30, 35, 40, 45, 50, 60)]
    out = _zeros(close)
    state = 0
    for i in range(60, len(close)):
        fmin = min(e[i] for e in fast)
        fmax = max(e[i] for e in fast)
        smin = min(e[i] for e in slow)
        smax = max(e[i] for e in slow)
        new = 1 if fmin > smax else -1 if fmax < smin else 0
        if new != 0 and new != state:
            out[i] = new
        if new != 0:
            state = new
    return out


def heikin(opens, high, low, close, volume, ts):
    """Heikin-Ashi colour flip."""
    if not _ok(opens, close):
        return _zeros(close)
    n = len(close)
    out = _zeros(close)
    if n < 2:
        return out
    ha_o = opens[0]
    ha_c = (opens[0] + high[0] + low[0] + close[0]) / 4
    color = 0
    for i in range(1, n):
        ha_o = (ha_o + ha_c) / 2
        ha_c = (opens[i] + high[i] + low[i] + close[i]) / 4
        new = 1 if ha_c > ha_o else -1 if ha_c < ha_o else color
        if color != 0 and new != color:
            out[i] = new
        color = new
    return out


def lrslope(opens, high, low, close, volume, ts, n=20):
    """Sign flip of the 20-bar least-squares slope."""
    m = len(close)
    out = _zeros(close)
    xs = list(range(n))
    xm = sum(xs) / n
    den = sum((x - xm) ** 2 for x in xs)
    prev = math.nan
    for i in range(n - 1, m):
        w = close[i - n + 1:i + 1]
        ym = sum(w) / n
        s = sum((x - xm) * (y - ym) for x, y in zip(xs, w, strict=False)) / den
        if not math.isnan(prev):
            if prev <= 0 < s:
                out[i] = 1
            elif prev >= 0 > s:
                out[i] = -1
        prev = s
    return out


# --------------------------------------------------------------- momentum
def willr14(opens, high, low, close, volume, ts, n=14):
    """Williams %R at its extremes (level rule, like stoch14)."""
    out = _zeros(close)
    for i in range(n, len(close)):
        hh = max(high[i - n + 1:i + 1])
        ll = min(low[i - n + 1:i + 1])
        if hh == ll:
            continue
        r = -100 * (hh - close[i]) / (hh - ll)
        if r < -80:
            out[i] = 1
        elif r > -20:
            out[i] = -1
    return out


def stochrsi(opens, high, low, close, volume, ts, n=14):
    """Stochastic of RSI crossing out of its extremes."""
    rsi = _rsi_series(close, n)
    m = len(close)
    k = [math.nan] * m
    for i in range(2 * n, m):
        w = [r for r in rsi[i - n + 1:i + 1] if not math.isnan(r)]
        if len(w) < n:
            continue
        hi_, lo_ = max(w), min(w)
        k[i] = 50.0 if hi_ == lo_ else 100 * (rsi[i] - lo_) / (hi_ - lo_)
    out = _zeros(close)
    for i in range(2 * n + 1, m):
        if math.isnan(k[i - 1]) or math.isnan(k[i]):
            continue
        if k[i - 1] <= 20 < k[i]:
            out[i] = 1
        elif k[i - 1] >= 80 > k[i]:
            out[i] = -1
    return out


def ultosc(opens, high, low, close, volume, ts):
    """Ultimate Oscillator under 30 / over 70 (level rule)."""
    m = len(close)
    out = _zeros(close)
    bp, tr = [0.0], [0.0]
    for i in range(1, m):
        lo_ = min(low[i], close[i - 1])
        hi_ = max(high[i], close[i - 1])
        bp.append(close[i] - lo_)
        tr.append(hi_ - lo_)
    for i in range(29, m):
        sums = []
        for k in (7, 14, 28):
            t = sum(tr[i - k + 1:i + 1])
            sums.append(sum(bp[i - k + 1:i + 1]) / t if t else 0.5)
        uo = 100 * (4 * sums[0] + 2 * sums[1] + sums[2]) / 7
        if uo < 30:
            out[i] = 1
        elif uo > 70:
            out[i] = -1
    return out


def ao(opens, high, low, close, volume, ts):
    """Awesome Oscillator zero cross."""
    med = [(h + l) / 2 for h, l in zip(high, low, strict=False)]
    f = _sma(med, 5)
    s = _sma(med, 34)
    out = _zeros(close)
    for i in range(34, len(close)):
        was = f[i - 1] - s[i - 1]
        now = f[i] - s[i]
        if was <= 0 < now:
            out[i] = 1
        elif was >= 0 > now:
            out[i] = -1
    return out


def fisher(opens, high, low, close, volume, ts, n=10):
    """Fisher transform turning at an extreme."""
    m = len(close)
    out = _zeros(close)
    med = [(h + l) / 2 for h, l in zip(high, low, strict=False)]
    v = 0.0
    fish = [0.0] * m
    for i in range(n, m):
        w = med[i - n + 1:i + 1]
        hi_, lo_ = max(w), min(w)
        raw = 0.0 if hi_ == lo_ else 2 * ((med[i] - lo_) / (hi_ - lo_) - .5)
        v = .33 * raw + .67 * v
        v = max(-0.999, min(0.999, v))
        fish[i] = .5 * math.log((1 + v) / (1 - v)) + .5 * fish[i - 1]
        if i <= n + 1:
            continue
        if fish[i - 1] < -1.5 and fish[i] > fish[i - 1] <= fish[i - 2]:
            out[i] = 1
        elif fish[i - 1] > 1.5 and fish[i] < fish[i - 1] >= fish[i - 2]:
            out[i] = -1
    return out


def crsi(opens, high, low, close, volume, ts):
    """Connors RSI at its extremes (level rule)."""
    m = len(close)
    out = _zeros(close)
    r3 = _rsi_series(close, 3)
    streak = [0.0] * m
    for i in range(1, m):
        if close[i] > close[i - 1]:
            streak[i] = streak[i - 1] + 1 if streak[i - 1] > 0 else 1
        elif close[i] < close[i - 1]:
            streak[i] = streak[i - 1] - 1 if streak[i - 1] < 0 else -1
    r2 = _rsi_series(streak, 2)
    for i in range(101, m):
        if math.isnan(r3[i]) or math.isnan(r2[i]):
            continue
        rets = [(close[j] - close[j - 1]) / close[j - 1]
                for j in range(i - 99, i + 1) if close[j - 1]]
        if not rets:
            continue
        cur = rets[-1]
        pr = 100 * sum(1 for x in rets[:-1] if x < cur) / max(1, len(rets) - 1)
        c = (r3[i] + r2[i] + pr) / 3
        if c < 10:
            out[i] = 1
        elif c > 90:
            out[i] = -1
    return out


def tsi(opens, high, low, close, volume, ts):
    """True Strength Index crossing its signal line."""
    m = len(close)
    mom = [0.0] + [close[i] - close[i - 1] for i in range(1, m)]
    num = _ema(_ema(mom, 25), 13)
    den = _ema(_ema([abs(x) for x in mom], 25), 13)
    t = [100 * a / b if b else 0.0 for a, b in zip(num, den, strict=False)]
    sig = _ema(t, 7)
    out = _zeros(close)
    for i in range(40, m):
        if t[i - 1] <= sig[i - 1] and t[i] > sig[i]:
            out[i] = 1
        elif t[i - 1] >= sig[i - 1] and t[i] < sig[i]:
            out[i] = -1
    return out


def rsidiv(opens, high, low, close, volume, ts, look=40, n=14):
    """Price makes a new extreme, RSI refuses — classic divergence."""
    rsi = _rsi_series(close, n)
    out = _zeros(close)
    for i in range(look + n, len(close)):
        w = close[i - look:i]
        j_lo = i - look + w.index(min(w))
        j_hi = i - look + w.index(max(w))
        if (close[i] < close[j_lo] and not math.isnan(rsi[j_lo])
                and rsi[i] > rsi[j_lo] + 3):
            out[i] = 1
        elif (close[i] > close[j_hi] and not math.isnan(rsi[j_hi])
                and rsi[i] < rsi[j_hi] - 3):
            out[i] = -1
    return out


def macddiv(opens, high, low, close, volume, ts, look=40):
    """MACD-histogram divergence against a new price extreme."""
    f = _ema(close, 12)
    s = _ema(close, 26)
    line = [a - b for a, b in zip(f, s, strict=False)]
    hist = [a - b for a, b in zip(line, _ema(line, 9), strict=False)]
    out = _zeros(close)
    for i in range(look + 35, len(close)):
        w = close[i - look:i]
        span = max(hist[i - look:i + 1]) - min(hist[i - look:i + 1]) + 1e-12
        j_lo = i - look + w.index(min(w))
        j_hi = i - look + w.index(max(w))
        if close[i] < close[j_lo] and hist[i] > hist[j_lo] + .05 * span:
            out[i] = 1
        elif close[i] > close[j_hi] and hist[i] < hist[j_hi] - .05 * span:
            out[i] = -1
    return out


def elder(opens, high, low, close, volume, ts):
    """Elder impulse: EMA13 and MACD histogram turn together."""
    e = _ema(close, 13)
    f = _ema(close, 12)
    s = _ema(close, 26)
    line = [a - b for a, b in zip(f, s, strict=False)]
    hist = [a - b for a, b in zip(line, _ema(line, 9), strict=False)]
    out = _zeros(close)
    state = 0
    for i in range(36, len(close)):
        eu = e[i] > e[i - 1]
        hu = hist[i] > hist[i - 1]
        new = 1 if eu and hu else -1 if (not eu and not hu) else 0
        if new != 0 and new != state:
            out[i] = new
        if new != 0:
            state = new
    return out


# ----------------------------------------------------------- mean reversion
def zscore20(opens, high, low, close, volume, ts, n=20, k=2.0):
    """Close stretched k sigmas from its mean snaps back (event)."""
    ma = _sma(close, n)
    sd = _stdev(close, n)
    out = _zeros(close)
    prev = math.nan
    for i in range(n, len(close)):
        if not sd[i]:
            continue
        z = (close[i] - ma[i]) / sd[i]
        if not math.isnan(prev):
            if prev >= -k > z:
                out[i] = 1
            elif prev <= k < z:
                out[i] = -1
        prev = z
    return out


def rsi2(opens, high, low, close, volume, ts):
    """Connors RSI(2) under 5 / over 95 (level rule)."""
    r = _rsi_series(close, 2)
    out = _zeros(close)
    for i in range(3, len(close)):
        if math.isnan(r[i]):
            continue
        if r[i] < 5:
            out[i] = 1
        elif r[i] > 95:
            out[i] = -1
    return out


def ibs(opens, high, low, close, volume, ts):
    """Internal bar strength: close pinned to the bar's own extreme."""
    out = _zeros(close)
    for i in range(1, len(close)):
        rng = high[i] - low[i]
        if rng <= 0:
            continue
        v = (close[i] - low[i]) / rng
        if v < 0.15:
            out[i] = 1
        elif v > 0.85:
            out[i] = -1
    return out


def prank(opens, high, low, close, volume, ts, n=100):
    """Close in the extreme tail of its own last-100 distribution."""
    out = _zeros(close)
    for i in range(n, len(close)):
        w = close[i - n:i]
        r = sum(1 for x in w if x < close[i]) / n
        if r < 0.05:
            out[i] = 1
        elif r > 0.95:
            out[i] = -1
    return out


def vwaprev(opens, high, low, close, volume, ts, n=50, k=2.0):
    """Stretch from the day-anchored VWAP beyond k sigmas snaps back."""
    if not (_ok(volume, close) and _ok(ts, close)):
        return _zeros(close)
    m = len(close)
    out = _zeros(close)
    devs = [math.nan] * m
    day = None
    pv = vv = 0.0
    for i in range(m):
        d = ts[i] // _DAY_MS
        if d != day:
            day, pv, vv = d, 0.0, 0.0
        typ = (high[i] + low[i] + close[i]) / 3
        pv += typ * volume[i]
        vv += volume[i]
        if vv:
            devs[i] = (close[i] - pv / vv) / (pv / vv)
    prev = math.nan
    for i in range(n, m):
        w = [x for x in devs[i - n + 1:i + 1] if not math.isnan(x)]
        if len(w) < n // 2 or math.isnan(devs[i]):
            continue
        mu = sum(w) / len(w)
        sd = math.sqrt(sum((x - mu) ** 2 for x in w) / len(w))
        if not sd:
            continue
        z = (devs[i] - mu) / sd
        if not math.isnan(prev):
            if prev >= -k > z:
                out[i] = 1
            elif prev <= k < z:
                out[i] = -1
        prev = z
    return out


def gapfade(opens, high, low, close, volume, ts, mult=1.5):
    """An open far from the last close tends to fill — fade it."""
    if not _ok(opens, close):
        return _zeros(close)
    atr = _atr(high, low, close, 14)
    out = _zeros(close)
    for i in range(15, len(close)):
        if math.isnan(atr[i - 1]) or not atr[i - 1]:
            continue
        gap = opens[i] - close[i - 1]
        if gap > mult * atr[i - 1]:
            out[i] = -1
        elif gap < -mult * atr[i - 1]:
            out[i] = 1
    return out


# ---------------------------------------------------------------- breakout
def orb(opens, high, low, close, volume, ts):
    """Opening-range breakout on the UTC day (first ~6 hours)."""
    if not _ok(ts, close):
        return _zeros(close)
    m = len(close)
    out = _zeros(close)
    if m < 3:
        return out
    bar_ms = ts[1] - ts[0]
    if bar_ms <= 0:
        return _zeros(close)
    k = max(1, int(6 * 3_600_000 // bar_ms))
    day = None
    cnt = 0
    hi_ = lo_ = math.nan
    fired = False
    for i in range(m):
        d = ts[i] // _DAY_MS
        if d != day:
            day, cnt, hi_, lo_, fired = d, 0, math.nan, math.nan, False
        cnt += 1
        if cnt <= k:
            hi_ = high[i] if math.isnan(hi_) else max(hi_, high[i])
            lo_ = low[i] if math.isnan(lo_) else min(lo_, low[i])
            continue
        if fired or math.isnan(hi_):
            continue
        if close[i] > hi_:
            out[i] = 1
            fired = True
        elif close[i] < lo_:
            out[i] = -1
            fired = True
    return out


def nr7(opens, high, low, close, volume, ts):
    """Narrowest range of 7 then a break of that quiet bar."""
    out = _zeros(close)
    for i in range(8, len(close)):
        rngs = [high[j] - low[j] for j in range(i - 7, i)]
        if rngs[-1] == min(rngs):
            if close[i] > high[i - 1]:
                out[i] = 1
            elif close[i] < low[i - 1]:
                out[i] = -1
    return out


def squeeze(opens, high, low, close, volume, ts, n=20):
    """TTM squeeze: Bollinger inside Keltner, fire on release."""
    ma = _sma(close, n)
    sd = _stdev(close, n)
    atr = _atr(high, low, close, n)
    ema_ = _ema(close, n)
    out = _zeros(close)
    run = 0
    for i in range(n + 1, len(close)):
        if math.isnan(sd[i]) or math.isnan(atr[i]):
            continue
        inside = (ma[i] + 2 * sd[i] < ema_[i] + 1.5 * atr[i]
                  and ma[i] - 2 * sd[i] > ema_[i] - 1.5 * atr[i])
        if inside:
            run += 1
            continue
        if run >= 6:
            out[i] = 1 if close[i] > ma[i] else -1 if close[i] < ma[i] else 0
        run = 0
    return out


def fractal5(opens, high, low, close, volume, ts):
    """Break of the last confirmed Williams fractal."""
    highs, lows = _fractals(high, low)
    out = _zeros(close)
    fh = fl = math.nan
    for i in range(len(close)):
        if not math.isnan(fh) and close[i] > fh:
            out[i] = 1
            fh = math.nan
        elif not math.isnan(fl) and close[i] < fl:
            out[i] = -1
            fl = math.nan
        for _, v in highs[i]:
            fh = v
        for _, v in lows[i]:
            fl = v
    return out


def nhigh50(opens, high, low, close, volume, ts, n=50):
    """A close beyond the 50-bar extreme keeps going (momentum)."""
    out = _zeros(close)
    for i in range(n, len(close)):
        w = close[i - n:i]
        if close[i] > max(w):
            out[i] = 1
        elif close[i] < min(w):
            out[i] = -1
    return out


def insidebrk(opens, high, low, close, volume, ts):
    """Inside bar, then a break of the mother bar."""
    out = _zeros(close)
    for i in range(2, len(close)):
        if high[i - 1] <= high[i - 2] and low[i - 1] >= low[i - 2]:
            if close[i] > high[i - 2]:
                out[i] = 1
            elif close[i] < low[i - 2]:
                out[i] = -1
    return out


# ---------------------------------------------------------------- ICT / SMC
def orderblock(opens, high, low, close, volume, ts, life=40):
    """Last opposite candle before an impulse; entry on the retest."""
    if not _ok(opens, close):
        return _zeros(close)
    atr = _atr(high, low, close, 14)
    m = len(close)
    out = _zeros(close)
    bull = bear = None            # (top, bottom, born)
    for i in range(17, m):
        if bull and i - bull[2] <= life and low[i] <= bull[0] \
                and close[i] > bull[1]:
            out[i] = 1
            bull = None
        elif bear and i - bear[2] <= life and high[i] >= bear[1] \
                and close[i] < bear[0]:
            out[i] = -1
            bear = None
        if math.isnan(atr[i]) or not atr[i]:
            continue
        bodies = [close[j] - opens[j] for j in (i - 2, i - 1, i)]
        if all(b > 0 for b in bodies) and sum(bodies) > 2 * atr[i]:
            for j in range(i - 3, max(i - 10, 0), -1):
                if close[j] < opens[j]:
                    bull = (high[j], low[j], i)
                    break
        elif all(b < 0 for b in bodies) and -sum(bodies) > 2 * atr[i]:
            for j in range(i - 3, max(i - 10, 0), -1):
                if close[j] > opens[j]:
                    bear = (high[j], low[j], i)
                    break
    return out


def bos(opens, high, low, close, volume, ts):
    """Break of structure: continuation through the last swing."""
    highs, lows = _fractals(high, low)
    out = _zeros(close)
    sh = sl = math.nan
    trend = 0
    for i in range(len(close)):
        if not math.isnan(sh) and close[i] > sh:
            if trend == 1:
                out[i] = 1
            trend = 1
            sh = math.nan
        elif not math.isnan(sl) and close[i] < sl:
            if trend == -1:
                out[i] = -1
            trend = -1
            sl = math.nan
        for _, v in highs[i]:
            sh = v
        for _, v in lows[i]:
            sl = v
    return out


def choch(opens, high, low, close, volume, ts):
    """Change of character: the first break AGAINST the standing trend."""
    highs, lows = _fractals(high, low)
    out = _zeros(close)
    sh = sl = math.nan
    trend = 0
    for i in range(len(close)):
        if not math.isnan(sh) and close[i] > sh:
            if trend == -1:
                out[i] = 1
            trend = 1
            sh = math.nan
        elif not math.isnan(sl) and close[i] < sl:
            if trend == 1:
                out[i] = -1
            trend = -1
            sl = math.nan
        for _, v in highs[i]:
            sh = v
        for _, v in lows[i]:
            sl = v
    return out


def eqraid(opens, high, low, close, volume, ts, tol=0.001):
    """Equal highs/lows swept by a wick that closes back inside."""
    highs, lows = _fractals(high, low)
    out = _zeros(close)
    hlist: list[float] = []
    llist: list[float] = []
    for i in range(len(close)):
        if len(hlist) >= 2 and abs(hlist[-1] - hlist[-2]) <= tol * hlist[-1]:
            level = max(hlist[-1], hlist[-2])
            if high[i] > level and close[i] < level:
                out[i] = -1
                hlist.clear()
        if len(llist) >= 2 and abs(llist[-1] - llist[-2]) <= tol * llist[-1]:
            level = min(llist[-1], llist[-2])
            if low[i] < level and close[i] > level:
                out[i] = 1
                llist.clear()
        for _, v in highs[i]:
            hlist.append(v)
        for _, v in lows[i]:
            llist.append(v)
    return out


def turtle(opens, high, low, close, volume, ts, n=20):
    """Turtle Soup: a 20-bar breakout that closes back inside is fake."""
    out = _zeros(close)
    for i in range(n + 1, len(close)):
        ph = max(high[i - n:i])
        pl = min(low[i - n:i])
        if high[i] > ph and close[i] < ph:
            out[i] = -1
        elif low[i] < pl and close[i] > pl:
            out[i] = 1
    return out


def ote(opens, high, low, close, volume, ts, life=30):
    """Optimal trade entry: retrace 62-79% into the last impulse swing."""
    highs, lows = _fractals(high, low)
    out = _zeros(close)
    m = len(close)
    lasth = lastl = None          # (bar, price)
    zone = None                   # (dir, top, bottom, born)
    for i in range(m):
        if zone:
            d, top, bot, born = zone
            if i - born > life:
                zone = None
            elif bot <= close[i] <= top:
                out[i] = d
                zone = None
        for j, v in highs[i]:
            if lastl and j > lastl[0] and v > lastl[1]:
                lo_, hi_ = lastl[1], v
                zone = (1, hi_ - 0.62 * (hi_ - lo_),
                        hi_ - 0.79 * (hi_ - lo_), i)
            lasth = (j, v)
        for j, v in lows[i]:
            if lasth and j > lasth[0] and v < lasth[1]:
                hi_, lo_ = lasth[1], v
                zone = (-1, lo_ + 0.79 * (hi_ - lo_),
                        lo_ + 0.62 * (hi_ - lo_), i)
                zone = (-1, zone[2], zone[1], i) if zone[1] < zone[2] else zone
            lastl = (j, v)
    return out


def killzone(opens, high, low, close, volume, ts, thresh=0.003):
    """Momentum, but only inside the 12:00-16:00 UTC killzone."""
    if not _ok(ts, close):
        return _zeros(close)
    out = _zeros(close)
    for i in range(6, len(close)):
        hour = (ts[i] // 3_600_000) % 24
        if not 12 <= hour < 16:
            continue
        if not close[i - 6]:
            continue
        r = close[i] / close[i - 6] - 1
        if r > thresh:
            out[i] = 1
        elif r < -thresh:
            out[i] = -1
    return out


# ------------------------------------------------------------ candle shapes
def hammer(opens, high, low, close, volume, ts):
    """Hammer after a slide, shooting star after a climb."""
    if not _ok(opens, close):
        return _zeros(close)
    out = _zeros(close)
    for i in range(4, len(close)):
        rng = high[i] - low[i]
        if rng <= 0:
            continue
        body = abs(close[i] - opens[i])
        lower = min(close[i], opens[i]) - low[i]
        upper = high[i] - max(close[i], opens[i])
        slid = close[i - 1] < close[i - 2] < close[i - 3]
        rose = close[i - 1] > close[i - 2] > close[i - 3]
        if slid and lower >= 2 * body and close[i] >= low[i] + 0.6 * rng:
            out[i] = 1
        elif rose and upper >= 2 * body and close[i] <= high[i] - 0.6 * rng:
            out[i] = -1
    return out


def doji(opens, high, low, close, volume, ts):
    """A wide doji after a directional run fades the run."""
    if not _ok(opens, close):
        return _zeros(close)
    atr = _atr(high, low, close, 14)
    out = _zeros(close)
    for i in range(15, len(close)):
        rng = high[i] - low[i]
        if math.isnan(atr[i]) or rng <= atr[i]:
            continue
        if abs(close[i] - opens[i]) > 0.1 * rng:
            continue
        if close[i - 1] > close[i - 2] > close[i - 3]:
            out[i] = -1
        elif close[i - 1] < close[i - 2] < close[i - 3]:
            out[i] = 1
    return out


def soldiers(opens, high, low, close, volume, ts):
    """Three white soldiers / three black crows."""
    if not _ok(opens, close):
        return _zeros(close)
    out = _zeros(close)
    for i in range(3, len(close)):
        up = dn = True
        for j in (i - 2, i - 1, i):
            rng = high[j] - low[j]
            if rng <= 0:
                up = dn = False
                break
            body = close[j] - opens[j]
            if not (body > 0.5 * rng and close[j] >= high[j] - 0.3 * rng):
                up = False
            if not (-body > 0.5 * rng and close[j] <= low[j] + 0.3 * rng):
                dn = False
        if up and close[i] > close[i - 1] > close[i - 2]:
            out[i] = 1
        elif dn and close[i] < close[i - 1] < close[i - 2]:
            out[i] = -1
    return out


def pinbar(opens, high, low, close, volume, ts):
    """A long rejection wick on an outsized bar."""
    if not _ok(opens, close):
        return _zeros(close)
    atr = _atr(high, low, close, 14)
    out = _zeros(close)
    for i in range(15, len(close)):
        rng = high[i] - low[i]
        if math.isnan(atr[i]) or rng < 1.2 * atr[i] or rng <= 0:
            continue
        lower = min(close[i], opens[i]) - low[i]
        upper = high[i] - max(close[i], opens[i])
        if lower > 0.66 * rng:
            out[i] = 1
        elif upper > 0.66 * rng:
            out[i] = -1
    return out


def dbltop(opens, high, low, close, volume, ts, tol=0.0025, gap=5):
    """Double top/bottom confirmed by the neckline giving way."""
    highs, lows = _fractals(high, low)
    out = _zeros(close)
    m = len(close)
    hswing: list[tuple[int, float]] = []
    lswing: list[tuple[int, float]] = []
    neck_dn = neck_up = None
    for i in range(m):
        if neck_dn is not None and close[i] < neck_dn:
            out[i] = -1
            neck_dn = None
        if neck_up is not None and close[i] > neck_up:
            out[i] = 1
            neck_up = None
        for j, v in highs[i]:
            if (hswing and abs(v - hswing[-1][1]) <= tol * v
                    and j - hswing[-1][0] >= gap):
                neck_dn = min(low[hswing[-1][0]:j + 1])
            hswing.append((j, v))
        for j, v in lows[i]:
            if (lswing and abs(v - lswing[-1][1]) <= tol * v
                    and j - lswing[-1][0] >= gap):
                neck_up = max(high[lswing[-1][0]:j + 1])
            lswing.append((j, v))
    return out


# ------------------------------------------------------------------ volume
def obv20(opens, high, low, close, volume, ts, n=20):
    """On-balance volume crossing its own average."""
    if not _ok(volume, close):
        return _zeros(close)
    m = len(close)
    obv = [0.0] * m
    for i in range(1, m):
        obv[i] = obv[i - 1] + (volume[i] if close[i] > close[i - 1]
                               else -volume[i] if close[i] < close[i - 1]
                               else 0.0)
    ma = _sma(obv, n)
    out = _zeros(close)
    for i in range(n + 1, m):
        if math.isnan(ma[i - 1]):
            continue
        if obv[i - 1] <= ma[i - 1] and obv[i] > ma[i]:
            out[i] = 1
        elif obv[i - 1] >= ma[i - 1] and obv[i] < ma[i]:
            out[i] = -1
    return out


def cmf20(opens, high, low, close, volume, ts, n=20):
    """Chaikin money flow zero cross."""
    if not _ok(volume, close):
        return _zeros(close)
    m = len(close)
    mfv = [0.0] * m
    for i in range(m):
        rng = high[i] - low[i]
        if rng:
            mfv[i] = volume[i] * ((close[i] - low[i]) - (high[i] - close[i])) / rng
    out = _zeros(close)
    prev = math.nan
    for i in range(n, m):
        v = sum(volume[i - n + 1:i + 1])
        if not v:
            continue
        c = sum(mfv[i - n + 1:i + 1]) / v
        if not math.isnan(prev):
            if prev <= 0 < c:
                out[i] = 1
            elif prev >= 0 > c:
                out[i] = -1
        prev = c
    return out


def mfi14(opens, high, low, close, volume, ts, n=14):
    """Money-flow index (volume-weighted RSI) at its extremes."""
    if not _ok(volume, close):
        return _zeros(close)
    m = len(close)
    out = _zeros(close)
    typ = [(high[i] + low[i] + close[i]) / 3 for i in range(m)]
    for i in range(n + 1, m):
        pos = neg = 0.0
        for j in range(i - n + 1, i + 1):
            flow = typ[j] * volume[j]
            if typ[j] > typ[j - 1]:
                pos += flow
            elif typ[j] < typ[j - 1]:
                neg += flow
        if not pos + neg:
            continue
        mfi = 100 * pos / (pos + neg)
        if mfi < 20:
            out[i] = 1
        elif mfi > 80:
            out[i] = -1
    return out


def force13(opens, high, low, close, volume, ts, n=13):
    """Elder's force index zero cross."""
    if not _ok(volume, close):
        return _zeros(close)
    m = len(close)
    raw = [0.0] + [(close[i] - close[i - 1]) * volume[i] for i in range(1, m)]
    f = _ema(raw, n)
    out = _zeros(close)
    for i in range(n + 1, m):
        if f[i - 1] <= 0 < f[i]:
            out[i] = 1
        elif f[i - 1] >= 0 > f[i]:
            out[i] = -1
    return out


def volspike(opens, high, low, close, volume, ts, mult=3.0):
    """A conviction bar: outsized volume behind a directional body."""
    if not (_ok(volume, close) and _ok(opens, close)):
        return _zeros(close)
    ma = _sma(volume, 20)
    out = _zeros(close)
    for i in range(21, len(close)):
        rng = high[i] - low[i]
        if math.isnan(ma[i - 1]) or not ma[i - 1] or rng <= 0:
            continue
        if volume[i] > mult * ma[i - 1] and abs(close[i] - opens[i]) > 0.6 * rng:
            out[i] = 1 if close[i] > opens[i] else -1
    return out


def volclimax(opens, high, low, close, volume, ts, mult=3.0):
    """Exhaustion: a huge-volume reversal bar after a one-way run."""
    if not (_ok(volume, close) and _ok(opens, close)):
        return _zeros(close)
    ma = _sma(volume, 20)
    out = _zeros(close)
    for i in range(25, len(close)):
        if math.isnan(ma[i - 1]) or not ma[i - 1]:
            continue
        if volume[i] <= mult * ma[i - 1]:
            continue
        rose = all(close[j] > close[j - 1] for j in range(i - 3, i))
        slid = all(close[j] < close[j - 1] for j in range(i - 3, i))
        if rose and close[i] < opens[i]:
            out[i] = -1
        elif slid and close[i] > opens[i]:
            out[i] = 1
    return out


def relvolbrk(opens, high, low, close, volume, ts, n=20, mult=2.0):
    """A 20-bar breakout only counts when volume shows up for it."""
    if not _ok(volume, close):
        return _zeros(close)
    ma = _sma(volume, n)
    out = _zeros(close)
    for i in range(n + 1, len(close)):
        if math.isnan(ma[i - 1]) or not ma[i - 1]:
            continue
        if volume[i] < mult * ma[i - 1]:
            continue
        if close[i] > max(high[i - n:i]):
            out[i] = 1
        elif close[i] < min(low[i - n:i]):
            out[i] = -1
    return out


EXTRA_SIGNALS2 = {
    # trend
    "supertrend": supertrend, "psar": psar, "ichimoku": ichimoku,
    "adx14": adx14, "aroon25": aroon25, "vortex14": vortex14,
    "hull20": hull20, "kama10": kama10, "trix15": trix15, "gmma": gmma,
    "heikin": heikin, "lrslope": lrslope,
    # momentum
    "willr14": willr14, "stochrsi": stochrsi, "ultosc": ultosc, "ao": ao,
    "fisher": fisher, "crsi": crsi, "tsi": tsi, "rsidiv": rsidiv,
    "macddiv": macddiv, "elder": elder,
    # mean reversion
    "zscore20": zscore20, "rsi2": rsi2, "ibs": ibs, "prank": prank,
    "vwaprev": vwaprev, "gapfade": gapfade,
    # breakout
    "orb": orb, "nr7": nr7, "squeeze": squeeze, "fractal5": fractal5,
    "nhigh50": nhigh50, "insidebrk": insidebrk,
    # ICT / SMC
    "orderblock": orderblock, "bos": bos, "choch": choch, "eqraid": eqraid,
    "turtle": turtle, "ote": ote, "killzone": killzone,
    # candles
    "hammer": hammer, "doji": doji, "soldiers": soldiers, "pinbar": pinbar,
    "dbltop": dbltop,
    # volume
    "obv20": obv20, "cmf20": cmf20, "mfi14": mfi14, "force13": force13,
    "volspike": volspike, "volclimax": volclimax, "relvolbrk": relvolbrk,
}
