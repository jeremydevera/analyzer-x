"""The indicators of github.com/jeremydevera/Crypto-Predictor-Web, ported line
for line from the file its live trader runs (api/utils/indicators.ts), so a
strategy measured here reads the numbers that app computed (Oct 19, 2026).

Conventions kept on purpose, because the strategies were tuned on them:
* a value the TypeScript leaves `null` is None here; a NaN it can produce
  (ADX on a flat stretch) stays NaN, and NaN fails every comparison, as in
  JavaScript;
* EMAs are seeded with the SMA of their first `period` values, the RSI and
  ATR are Wilder-smoothed, the Stochastic's %K is an SMA of the raw %K;
* the detectors that read "the last bar" take `end` — the series length as
  the app saw it (bar i => end = i + 1) — instead of a sliced copy.
"""
from __future__ import annotations

import math

INF = float("inf")


def _num(x) -> bool:
    """TypeScript's `typeof x === 'number'`: None is not a number, NaN is."""
    return x is not None


def sma(data, period: int) -> list:
    out = [None] * len(data)
    s = 0.0
    for i, v in enumerate(data):
        s += v
        if i >= period:
            s -= data[i - period]
        if i >= period - 1:
            out[i] = s / period
    return out


def ema(data, period: int) -> list:
    n = len(data)
    out = [None] * n
    if n < period:
        return out
    k = 2.0 / (period + 1)
    last = sum(data[:period]) / period
    out[period - 1] = last
    for i in range(period, n):
        last = data[i] * k + last * (1 - k)
        out[i] = last
    return out


def ema_last_with(closed_ema: list, closed: list, x: float, period: int):
    """The EMA's last value over `closed + [x]` (a series whose final value is
    still forming), from the EMA already worked out over `closed` — what
    `calculateEMA(closes)[closes.length - 1]` returns, without recomputing."""
    m = len(closed)
    if m + 1 < period:
        return None
    if m + 1 == period:
        return (sum(closed) + x) / period
    prev = closed_ema[m - 1]
    k = 2.0 / (period + 1)
    return x * k + prev * (1 - k)


def rsi(data, period: int = 14) -> list:
    n = len(data)
    out = [None] * n
    gains = losses = 0.0
    for i in range(1, n):
        diff = data[i] - data[i - 1]
        gain = diff if diff > 0 else 0.0
        loss = -diff if diff < 0 else 0.0
        if i <= period:
            gains += gain
            losses += loss
            if i == period:
                rs = 100.0 if losses == 0 else (gains / period) / (losses / period)
                out[i] = 100 - 100 / (1 + rs)
        else:
            ag = (gains * (period - 1) + gain) / period
            al = (losses * (period - 1) + loss) / period
            gains, losses = ag, al
            out[i] = 100 - 100 / (1 + (100.0 if al == 0 else ag / al))
    return out


def true_ranges(h, lo, c) -> list:
    tr = [h[0] - lo[0]] if len(h) else []
    for i in range(1, len(h)):
        tr.append(max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1])))
    return tr


def atr(h, lo, c, period: int = 14) -> list:
    tr = true_ranges(h, lo, c)
    out = [None] * len(tr)
    s = 0.0
    for i, t in enumerate(tr):
        if i < period - 1:
            s += t
            continue
        if i == period - 1:
            s += t
            out[i] = s / period
            continue
        out[i] = (out[i - 1] * (period - 1) + t) / period
    return out


def kernel_one_sided(values, lookback: float, bandwidth: float) -> list:
    n = len(values)
    lb = max(2, int(math.floor(lookback)))
    bw = max(0.5, bandwidth)
    denom = 2 * bw * bw
    w = [math.exp(-(d * d) / denom) for d in range(lb)]
    out = [None] * n
    for i in range(n):
        start = max(0, i - lb + 1)
        ws = vs = 0.0
        for j in range(start, i + 1):
            wt = w[i - j]
            ws += wt
            vs += wt * values[j]
        out[i] = vs / ws if ws > 0 else values[i]
    return out


def supertrend(h, lo, c, atr_period: float, multiplier: float, use_kernel: bool = False,
               kernel_lookback: float = 20, kernel_bandwidth: float = 6) -> list:
    """Directions only ('bull' / 'bear' / None), as calculateSupertrend."""
    n = len(c)
    ap = max(2, int(math.floor(atr_period)))
    mult = max(0.1, multiplier)
    a = atr(h, lo, c, ap)
    hl2 = [(h[i] + lo[i]) / 2 for i in range(n)]
    src = kernel_one_sided(hl2, kernel_lookback, kernel_bandwidth) if use_kernel else hl2
    fu = [None] * n
    fl = [None] * n
    d = [None] * n
    for i in range(n):
        ai, s = a[i], src[i]
        if ai is None or s is None or not math.isfinite(ai) or not math.isfinite(s):
            continue
        bu, bl = s + mult * ai, s - mult * ai
        if i == 0:
            fu[i], fl[i] = bu, bl
            d[i] = "bull" if c[i] >= s else "bear"
            continue
        pfu, pfl, pc = fu[i - 1], fl[i - 1], c[i - 1]
        fu[i] = bu if (pfu is None or bu < pfu or pc > pfu) else pfu
        fl[i] = bl if (pfl is None or bl > pfl or pc < pfl) else pfl
        pd_ = d[i - 1]
        if pd_ is None:
            d[i] = "bull" if c[i] >= s else "bear"
        elif pd_ == "bear" and c[i] > fu[i]:
            d[i] = "bull"
        elif pd_ == "bull" and c[i] < fl[i]:
            d[i] = "bear"
        else:
            d[i] = pd_
    return d


def bollinger(data, period: int = 20, sd_mult: float = 2.0):
    mid = sma(data, period)
    up = [None] * len(data)
    low = [None] * len(data)
    for i, m in enumerate(mid):
        if m is None:
            continue
        sl = data[i - period + 1:i + 1]
        sd = math.sqrt(sum((v - m) ** 2 for v in sl) / period)
        up[i] = m + sd_mult * sd
        low[i] = m - sd_mult * sd
    return up, mid, low


def stochastic(h, lo, c, k_period: int = 14, d_period: int = 3, smooth_k: int = 3):
    n = len(c)
    raw = [None] * n
    for i in range(k_period - 1, n):
        hh = max(h[i - k_period + 1:i + 1])
        ll = min(lo[i - k_period + 1:i + 1])
        raw[i] = 50.0 if hh == ll else (c[i] - ll) / (hh - ll) * 100
    k = [None] * n
    first = next((i for i, v in enumerate(raw) if v is not None), -1)
    if first >= 0:
        for j, v in enumerate(sma([x for x in raw if x is not None], smooth_k)):
            k[first + j] = v
    d = [None] * n
    first_d = next((i for i, v in enumerate(k) if v is not None), -1)
    if first_d >= 0:
        for j, v in enumerate(sma([x for x in k if x is not None], d_period)):
            d[first_d + j] = v
    return k, d


def macd_hist(data, fast: int = 12, slow: int = 26, signal: int = 9) -> list:
    f, s = ema(data, fast), ema(data, slow)
    m = [f[i] - s[i] if f[i] is not None and s[i] is not None else None
         for i in range(len(data))]
    first = next((i for i, v in enumerate(m) if v is not None), -1)
    sig = [None] * len(data)
    if first >= 0:
        for j, v in enumerate(ema([x for x in m if x is not None], signal)):
            sig[first + j] = v
    return [m[i] - sig[i] if m[i] is not None and sig[i] is not None else None
            for i in range(len(data))]


def _dm(h, lo):
    n = len(h)
    p, m = [0.0], [0.0]
    for i in range(1, n):
        up, down = h[i] - h[i - 1], lo[i - 1] - lo[i]
        p.append(up if (up > down and up > 0) else 0.0)
        m.append(down if (down > up and down > 0) else 0.0)
    return p, m


def adx(h, lo, c, period: int = 14) -> list:
    n = len(h)
    out = [None] * n
    if n < period * 2 - 1:
        return out
    pdm, mdm = _dm(h, lo)
    tr = true_ranges(h, lo, c)
    s_tr = [0.0] * n
    s_p = [0.0] * n
    s_m = [0.0] * n
    s_tr[period - 1] = sum(tr[:period])
    s_p[period - 1] = sum(pdm[:period])
    s_m[period - 1] = sum(mdm[:period])
    for i in range(period, n):
        s_tr[i] = s_tr[i - 1] - s_tr[i - 1] / period + tr[i]
        s_p[i] = s_p[i - 1] - s_p[i - 1] / period + pdm[i]
        s_m[i] = s_m[i - 1] - s_m[i - 1] / period + mdm[i]
    dx = [0.0] * n
    for i in range(period - 1, n):
        dp = _div(s_p[i], s_tr[i]) * 100
        dm = _div(s_m[i], s_tr[i]) * 100
        dx[i] = _div(abs(dp - dm), dp + dm) * 100
    out[period * 2 - 2] = sum(dx[period - 1:period * 2 - 1]) / period
    for i in range(period * 2 - 1, n):
        out[i] = (out[i - 1] * (period - 1) + dx[i]) / period
    return out


def _div(a: float, b: float) -> float:
    """JavaScript division: x/0 is +-Infinity, 0/0 is NaN."""
    if b == 0:
        if a == 0 or (isinstance(a, float) and math.isnan(a)):
            return float("nan")
        return math.copysign(INF, a)
    return a / b


def di(h, lo, c, period: int = 14):
    n = len(h)
    p = max(2, int(math.floor(period)))
    pdm, mdm = _dm(h, lo)
    tr = true_ranges(h, lo, c)
    s_tr = [0.0] * n
    s_p = [0.0] * n
    s_m = [0.0] * n
    if n >= p:
        s_tr[p - 1] = sum(tr[:p])
        s_p[p - 1] = sum(pdm[:p])
        s_m[p - 1] = sum(mdm[:p])
        for i in range(p, n):
            s_tr[i] = s_tr[i - 1] - s_tr[i - 1] / p + tr[i]
            s_p[i] = s_p[i - 1] - s_p[i - 1] / p + pdm[i]
            s_m[i] = s_m[i - 1] - s_m[i - 1] / p + mdm[i]
    plus = [None] * n
    minus = [None] * n
    for i in range(p - 1, n):
        den = s_tr[i]
        if not (den > 0) or not math.isfinite(den):
            continue
        dp, dm = s_p[i] / den * 100, s_m[i] / den * 100
        plus[i] = dp if math.isfinite(dp) else None
        minus[i] = dm if math.isfinite(dm) else None
    return plus, minus


# ------------------------------------------------------------- detectors
# Each reads the series as the app saw it at one bar: `end` = its length.

def order_blocks(o, h, lo, c, end: int, lookback: int = 40):
    """(bull, bear) order blocks as dicts {low, high} or None. A bull block
    exists only when the LAST close is above the highest high of the window
    before it (detectOrderBlocks)."""
    n = end
    if n < 10:
        return None, None
    start = max(0, n - lookback)
    if n - 1 <= start:
        return None, None
    sh = h[start:n - 1]
    sl = lo[start:n - 1]
    sw_h = start + max(range(len(sh)), key=lambda j: (sh[j], -j))
    sw_l = start + min(range(len(sl)), key=lambda j: (sl[j], j))
    bull = bear = None
    if c[n - 1] > h[sw_h] and sw_h > start:
        for k in range(sw_h - 1, start - 1, -1):
            if c[k] < o[k]:
                bull = {"low": lo[k], "high": h[k]}
                break
    if c[n - 1] < lo[sw_l] and sw_l > start:
        for k in range(sw_l - 1, start - 1, -1):
            if c[k] > o[k]:
                bear = {"low": lo[k], "high": h[k]}
                break
    return bull, bear


def fvg_zones(h, lo, end: int, lookback: int = 60) -> list:
    """[(type, top, bottom, mid, index)] in the app's order (detectFVGZones)."""
    n = end
    out = []
    for k in range(max(1, n - lookback), n - 1):
        if h[k - 1] < lo[k + 1]:
            b, t = h[k - 1], lo[k + 1]
            out.append(("bull", t, b, (b + t) / 2, k))
        if lo[k - 1] > h[k + 1]:
            t, b = lo[k - 1], h[k + 1]
            out.append(("bear", t, b, (t + b) / 2, k))
    return out


def liquidity_sweep(h, lo, c, o, end: int, lookback: int = 25):
    """(bull, bear) — two or more equal lows (within 0.3%) swept by the last
    bar, which closes back above them in a green candle (detectLiquiditySweep)."""
    n = end
    if n < lookback + 2:
        return False, False
    start = n - lookback - 1
    rl = lo[start:n - 1]
    rh = h[start:n - 1]
    min_l, max_h = min(rl), max(rh)
    eq_l = sum(1 for x in rl if x > 0 and abs(x - min_l) / min_l < 0.003) if min_l else 0
    eq_h = sum(1 for x in rh if x > 0 and abs(x - max_h) / max_h < 0.003) if max_h else 0
    bull = eq_l >= 2 and lo[n - 1] < min_l and c[n - 1] > min_l and c[n - 1] > o[n - 1]
    bear = eq_h >= 2 and h[n - 1] > max_h and c[n - 1] < max_h and c[n - 1] < o[n - 1]
    return bull, bear


def rsi_divergence(c, r, end: int, lookback: int = 40, min_swing: int = 5):
    """(bull, bear), detectSwingRSIDivergence — note it returns at the FIRST
    bullish divergence and only then looks for a bearish one."""
    n = end
    if n < lookback:
        return False, False
    start = max(2, n - lookback)
    p_lp, p_lr, p_li = INF, 50.0, -1
    for i in range(start, n - 2):
        if c[i] < c[i - 1] and c[i] < c[i - 2] and c[i] < c[i + 1] and c[i] < c[i + 2]:
            rv = r[i] if r[i] is not None else 50.0
            if p_li >= 0 and i - p_li >= min_swing and c[i] < p_lp and rv > p_lr:
                return True, False
            if p_li < 0 or c[i] < p_lp:
                p_lp, p_lr, p_li = c[i], rv, i
    p_hp, p_hr, p_hi = 0.0, 50.0, -1
    for i in range(start, n - 2):
        if c[i] > c[i - 1] and c[i] > c[i - 2] and c[i] > c[i + 1] and c[i] > c[i + 2]:
            rv = r[i] if r[i] is not None else 50.0
            if p_hi >= 0 and i - p_hi >= min_swing and c[i] > p_hp and rv < p_hr:
                return False, True
            if p_hi < 0 or c[i] > p_hp:
                p_hp, p_hr, p_hi = c[i], rv, i
    return False, False


def _jsround(x: float) -> int:
    """JavaScript's Math.round: halves go up (66.5 -> 67); Python's round()
    sends them to the even number (66), which would change which chart
    pattern wins a tie."""
    return int(math.floor(x + 0.5))


def _pct_diff(a: float, b: float) -> float:
    base = max(abs(a), abs(b))
    return abs(a - b) / base * 100 if base > 0 else 0.0


def _swing_highs(h, start: int, end: int, win: int = 3) -> list:
    out = []
    for i in range(start + win, end - win):
        hi = h[i]
        if all(h[j] < hi for j in range(i - win, i + win + 1) if j != i):
            out.append((i, hi))
    return out


def _swing_lows(lo, start: int, end: int, win: int = 3) -> list:
    out = []
    for i in range(start + win, end - win):
        lv = lo[i]
        if all(lo[j] > lv for j in range(i - win, i + win + 1) if j != i):
            out.append((i, lv))
    return out


def chart_pattern(h, lo, c, n: int):
    """The strongest pattern at the series' last bar, as ('buy'|'sell', name)
    or None (detectChartPatterns: double top/bottom, head and shoulders and
    its inverse, ascending/descending triangle; highest confidence wins, the
    first found on a tie)."""
    if n < 30:
        return None
    end = n - 2
    start = max(0, end - 100)
    cur = c[n - 1]
    cands = []
    sh80 = _swing_highs(h, max(0, end - 80), end)
    sl80 = _swing_lows(lo, max(0, end - 80), end)
    if len(sh80) >= 2:
        (i1, p1), (i2, p2) = sh80[-2], sh80[-1]
        if _pct_diff(p1, p2) <= 2.0 and i2 > i1 + 3:
            between = lo[i1 + 1:i2]
            if len(between) >= 2:
                neck, top = min(between), max(p1, p2)
                rt = _pct_diff(top, neck)
                if 3 <= rt <= 30 and cur <= neck * 1.005:
                    cands.append((min(90, _jsround(55 + (2 - _pct_diff(p1, p2)) * 12
                                                + min(rt - 3, 5) * 2)), "sell", "Double Top"))
    if len(sl80) >= 2:
        (i1, p1), (i2, p2) = sl80[-2], sl80[-1]
        if _pct_diff(p1, p2) <= 2.0 and i2 > i1 + 3:
            between = h[i1 + 1:i2]
            if len(between) >= 2:
                neck, bot = max(between), min(p1, p2)
                bn = _pct_diff(neck, bot)
                if 3 <= bn <= 30 and cur >= neck * 0.995:
                    cands.append((min(90, _jsround(55 + (2 - _pct_diff(p1, p2)) * 12
                                                + min(bn - 3, 5) * 2)), "buy", "Double Bottom"))
    sh100 = _swing_highs(h, start, end)
    sl100 = _swing_lows(lo, start, end)
    if len(sh100) >= 3:
        (li, lp), (hi_, hp), (ri, rp) = sh100[-3], sh100[-2], sh100[-1]
        if hp > lp and hp > rp and ri > hi_ + 2 and hi_ > li + 2:
            sd = _pct_diff(lp, rp)
            if sd <= 4:
                t1, t2 = lo[li + 1:hi_], lo[hi_ + 1:ri]
                if t1 and t2:
                    neck = (min(t1) + min(t2)) / 2
                    ha = _pct_diff(hp, neck)
                    if ha >= 3 and cur <= neck * 1.01:
                        cands.append((min(90, _jsround(60 + (4 - sd) * 5 + min(ha - 3, 5) * 2)),
                                      "sell", "Head & Shoulders"))
    if len(sl100) >= 3:
        (li, lp), (hi_, hp), (ri, rp) = sl100[-3], sl100[-2], sl100[-1]
        if hp < lp and hp < rp and ri > hi_ + 2 and hi_ > li + 2:
            sd = _pct_diff(lp, rp)
            if sd <= 4:
                p1_, p2_ = h[li + 1:hi_], h[hi_ + 1:ri]
                if p1_ and p2_:
                    neck = (max(p1_) + max(p2_)) / 2
                    hb = _pct_diff(neck, hp)
                    if hb >= 3 and cur >= neck * 0.99:
                        cands.append((min(90, _jsround(60 + (4 - sd) * 5 + min(hb - 3, 5) * 2)),
                                      "buy", "Inv. Head & Shoulders"))
    sht = _swing_highs(h, max(0, end - 60), end)
    slt = _swing_lows(lo, max(0, end - 60), end)
    if len(sht) >= 2 and len(slt) >= 2:
        (_, h1), (_, h2) = sht[-2], sht[-1]
        (_, l1), (_, l2) = slt[-2], slt[-1]
        if (_pct_diff(h1, h2) < 0.8 and l2 > l1 and _pct_diff(l1, l2) >= 0.5
                and cur >= (h1 + h2) / 2 * 0.997):
            cands.append((68, "buy", "Ascending Triangle"))
        if (h2 < h1 and _pct_diff(h1, h2) >= 0.5 and _pct_diff(l1, l2) < 0.8
                and cur <= (l1 + l2) / 2 * 1.003):
            cands.append((68, "sell", "Descending Triangle"))
    if not cands:
        return None
    best = cands[0]
    for cand in cands[1:]:
        if cand[0] > best[0]:
            best = cand
    return best[1], best[2]


def flux_scores(o, h, lo, c, base_long: int = 48, base_short: int = 64, vol_len: int = 20,
                pers_len: int = 8, curv_len: int = 14, guide_len: int = 14,
                k_long: float = 1.1, k_short: float = 1.3):
    """(long_cross, short_cross) per bar of computeFluxGateDualEngine, each
    bar judged on the series up to it. The score is causal, so it is worked
    out once; only the thresholds read the trailing window. A bar the engine
    returns null for (too little history) is (False, False)."""
    n = len(c)
    lc = [False] * n
    sc = [False] * n
    if n < 60:
        return lc, sc
    eps = 1e-12
    w_dir, w_pers, w_curv = 0.45, 0.35, 0.2
    typ = [(h[i] + lo[i] + c[i]) / 3 for i in range(n)]
    k = 2 / (guide_len + 1)
    guide = [0.0] * n
    last = sum(typ[:guide_len]) / guide_len
    for i in range(n):
        if i < guide_len - 1:
            guide[i] = typ[i]
        elif i == guide_len - 1:
            guide[i] = last
        else:
            last = typ[i] * k + last * (1 - k)
            guide[i] = last
    ret = [0.0] * n
    for i in range(1, n):
        p, cur = c[i - 1], c[i]
        ret[i] = math.log(cur / p) if (p > 0 and cur > 0) else 0.0

    def stdev_at(e: int, ln: int) -> float:
        s0 = e - ln + 1
        if s0 < 1:
            return 0.0
        seg = ret[s0:e + 1]
        m = sum(seg) / ln
        return math.sqrt(sum((x - m) ** 2 for x in seg) / ln)

    def linreg_last(e: int, ln: int) -> float:
        s0 = e - ln + 1
        if s0 < 0:
            return typ[e]
        sx = sy = sxx = sxy = 0.0
        for j in range(ln):
            x, y = j + 1, typ[s0 + j]
            sx += x
            sy += y
            sxx += x * x
            sxy += x * y
        den = ln * sxx - sx * sx
        if abs(den) < eps:
            return typ[e]
        slope = (ln * sxy - sx * sy) / den
        return (sy - slope * sx) / ln + slope * ln

    score = [0.0] * n
    fits = [linreg_last(i, curv_len) for i in range(n)]
    for i in range(2, n):
        vol = stdev_at(i, vol_len)
        d = math.tanh(((guide[i] - guide[i - 1]) / (vol + eps)) * 2.0)
        ps = max(1, i - pers_len + 1)
        pers = 0
        for j in range(ps, i + 1):
            dd = c[j] - c[j - 1]
            pers += 1 if dd > 0 else (-1 if dd < 0 else 0)
        pers = pers / min(pers_len, i)
        curv = (fits[i] - 2 * fits[i - 1] + fits[i - 2]) / (vol + eps)
        score[i] = w_dir * d + w_pers * pers + w_curv * math.tanh(curv)

    def mean_sd(e: int, ln: int):
        s0 = e - ln + 1
        if s0 < 0:
            return 0.0, 0.0
        seg = score[s0:e + 1]
        m = sum(seg) / ln
        return m, math.sqrt(sum((x - m) ** 2 for x in seg) / max(1, ln - 1))

    need = max(base_long, base_short, 10)
    for i in range(need + 1, n):
        ln_now, ld_now = mean_sd(i, base_long)
        ln_prev, ld_prev = mean_sd(i - 1, base_long)
        sn_now, sd_now = mean_sd(i, base_short)
        sn_prev, sd_prev = mean_sd(i - 1, base_short)
        lt_now, lt_prev = ln_now + k_long * ld_now, ln_prev + k_long * ld_prev
        st_now, st_prev = sn_now - k_short * sd_now, sn_prev - k_short * sd_prev
        lc[i] = score[i - 1] <= lt_prev and score[i] > lt_now
        sc[i] = score[i - 1] >= st_prev and score[i] < st_now
    return lc, sc
