"""The seven entry rules of github.com/jeremydevera/Crypto-Predictor-Web, per
bar, ported from the function its live trader calls on every scan
(api/utils/signalEval.ts, `evaluateSignal`) — Oct 19, 2026, operator: "use the
strategy and switches and come up with best combination for all coins".

The app decides ONE bar (the last closed one) per scan; a backtest needs the
same decision at every bar. So each strategy is split in two:
* `raw_<s>(ctx)` — everything about a bar that no switch changes, worked out
  once per frame;
* `decide_<s>(ctx, raw, sw)` — the decision for one switch setting `sw`,
  which is cheap, so hundreds of settings can be tried on the same frame.

What is the app's, kept exactly: every threshold, every gate, the quality score
(average quality of the agreeing signals + their count - 1, capped at 8), the
chart pattern that adds a signal of its own, "best of buy and sell by quality,
buy on a tie", and the scanner's repeat block — one signal per coin, timeframe,
strategy and side per 4 hours (backgroundScanner.ts, SIGNAL_COOLDOWN_MS).

Where this differs from the app, and why (each is named where it happens):
1. BIGGER-TIMEFRAME CANDLES are built from this frame's own candles, as the
   live trader saw them at each close: the finished ones plus the one still
   forming, up to that close. Never the finished candle's later close (their
   browser backtest read that: look-ahead).
2. A bigger-timeframe AVERAGE that needs more bigger candles than the frame
   holds counts as AGREEING (both sides). The app always fetched 220 bigger
   candles, so it never met this case; read literally, its code would block
   every long there (FluxGate) or every B-grade break (the Elite rules).
3. INDICATORS run over the whole frame the backtest hands over (the window and
   300 bars before it), not the app's 199 bars — so the 200-bar averages exist
   (live, the app's "EMA200" signal could never be on).
4. Settings a switch never touches stay at the app's per-strategy preset
   (src/stores/tradingStore.ts DEFAULT_*_FILTERS): the values its scanner page
   sends when that strategy is picked.
Exits are not ported: the backtest's stop/target grid closes every trade.
"""
from __future__ import annotations

import bisect
import math

from tradingagents import cpw_indicators as ind

INF = float("inf")
H4_MS = 4 * 3600 * 1000


# --------------------------------------------------------------- the frame

class Ctx:
    """One frame of candles (oldest first, `ts` = open time in ms) and what
    every strategy reads from it, worked out once and kept."""

    def __init__(self, o, h, lo, c, v, ts):
        self.o, self.h, self.l, self.c = list(o), list(h), list(lo), list(c)
        self.n = n = len(self.c)
        self.v = list(v) if v is not None and len(v) == n else [0.0] * n
        self.ts = [int(t) for t in ts] if ts is not None and len(ts) == n else [0] * n
        self.tf_s = _bar_seconds(self.ts)
        self._memo: dict = {}
        c_ = self.c
        r14 = ind.rsi(c_, 14)
        e20, e50, e200 = ind.ema(c_, 20), ind.ema(c_, 50), ind.ema(c_, 200)
        mh = ind.macd_hist(c_)
        ax = ind.adx(self.h, self.l, c_, 14)
        at = ind.atr(self.h, self.l, c_, 14)
        self.e20, self.e50, self.e200 = e20, e50, e200
        self.adx_raw = ax
        self.rsi = [r if r is not None else 50.0 for r in r14]
        self.rsi_raw = r14
        self.cur_e20 = [e20[i] if e20[i] is not None else c_[i] for i in range(n)]
        self.cur_e50 = [e50[i] if e50[i] is not None else c_[i] for i in range(n)]
        self.cur_e200 = [e200[i] if e200[i] is not None else c_[i] for i in range(n)]
        self.mh = [x if x is not None else 0.0 for x in mh]
        self.adx = [x if x is not None else 20.0 for x in ax]
        self.atr = [at[i] if at[i] is not None else c_[i] * 0.01 for i in range(n)]
        v_ = self.v
        # bars.slice(max(0, len - 20), len - 1): the 19 bars before this one
        pre = [0.0]
        for x in v_:
            pre.append(pre[-1] + x)
        self.avgvol = []
        for i in range(n):
            a = max(0, i - 19)
            self.avgvol.append((pre[i] - pre[a]) / (i - a) if i > a else v_[i])
        self.vpre = pre
        self.bull = [c_[i] > self.o[i] for i in range(n)]
        self.bear = [c_[i] < self.o[i] for i in range(n)]
        self.regime = []
        for i in range(n):
            p = self.atr[i] / c_[i] * 100 if c_[i] else 0.0
            self.regime.append("low" if p < 0.4 else ("medium" if p < 1.2 else "high"))
        self.utc_min = [((t // 1000) % 86400) // 60 for t in self.ts]
        # 5-bar pivots (two lower bars each side), and the newest one at or
        # before each index — the swing every breakout rule starts from
        self.last_ph5, self.last_pl5 = _last_pivots5(self.h, self.l)

    def memo(self, key, fn):
        if key not in self._memo:
            self._memo[key] = fn()
        return self._memo[key]

    def elite_session(self, i: int) -> bool:
        m = self.utc_min[i]
        return 480 <= m < 660 or 780 <= m < 1020

    def pattern(self, i: int):
        pats = self.memo("patterns", lambda: _patterns(self))
        return pats[i]

    def htf(self) -> "Htf":
        return self.memo("htf", lambda: Htf(self))


def _bar_seconds(ts) -> int:
    gaps = sorted(ts[k + 1] - ts[k] for k in range(len(ts) - 1) if ts[k + 1] > ts[k])
    if not gaps:
        return 3600
    return int(gaps[len(gaps) // 2] // 1000)


def _last_pivots5(h, lo):
    n = len(h)
    lph = [-1] * n
    lpl = [-1] * n
    ph = pl = -1
    for k in range(n):
        if 2 <= k <= n - 3:
            if h[k] > h[k - 1] and h[k] > h[k - 2] and h[k] > h[k + 1] and h[k] > h[k + 2]:
                ph = k
            if lo[k] < lo[k - 1] and lo[k] < lo[k - 2] and lo[k] < lo[k + 1] and lo[k] < lo[k + 2]:
                pl = k
        lph[k] = ph
        lpl[k] = pl
    return lph, lpl


def _swing(ctx: Ctx, i: int, lookback: int):
    """(high, high index, low, low index): the newest 5-bar swing high and low
    between `lookback` bars back and three bars back (the app's loop from
    i - 3 down to max(2, i - lookback)). -1 / 0 / inf when none."""
    floor_ = max(2, i - lookback)
    k = ctx.last_ph5[i - 3] if i - 3 >= 0 else -1
    hi_idx = k if k >= floor_ else -1
    k = ctx.last_pl5[i - 3] if i - 3 >= 0 else -1
    lo_idx = k if k >= floor_ else -1
    return (ctx.h[hi_idx] if hi_idx >= 0 else 0.0, hi_idx,
            ctx.l[lo_idx] if lo_idx >= 0 else INF, lo_idx)


def _patterns(ctx: Ctx) -> list:
    """The chart pattern at every bar, computed from precomputed 3-bar-window
    swing points so each bar costs a few lookups (same answer as
    cpw_indicators.chart_pattern, which the tests hold it to)."""
    out = [None] * ctx.n
    for i in range(ctx.n):
        out[i] = ind.chart_pattern(ctx.h, ctx.l, ctx.c, i + 1) if i >= 29 else None
    return out


# ------------------------------------------------------ the bigger timeframe

# backgroundScanner.ts htfFor: 1m->15m, 5m/15m->1h, 1h->4h, 4h->1d, else 1d
_HTF_OF = {60: 900, 300: 3600, 900: 3600, 3600: 14400, 14400: 86400}


class Htf:
    """The bigger-timeframe candles the app fetched at each bar's close, built
    from this frame: every finished bigger candle, then the forming one —
    aggregated from this frame's bars so far, or flat at the close when this
    bar just finished one (the next one has only begun)."""

    def __init__(self, ctx: Ctx):
        self.ctx = ctx
        tf = ctx.tf_s or 3600
        self.per = per = _HTF_OF.get(tf, 86400)
        starts: list = []
        po, ph, pl, pc = [], [], [], []
        self.pidx = [0] * ctx.n
        self.part = [None] * ctx.n      # (o, h, l, c) of the forming candle
        self.closed = [0] * ctx.n       # finished bigger candles before it
        cur = None
        for i in range(ctx.n):
            t = ctx.ts[i] // 1000
            st = t - t % per
            if cur != st:
                cur = st
                starts.append(st)
                po.append(ctx.o[i])
                ph.append(ctx.h[i])
                pl.append(ctx.l[i])
                pc.append(ctx.c[i])
            else:
                ph[-1] = max(ph[-1], ctx.h[i])
                pl[-1] = min(pl[-1], ctx.l[i])
                pc[-1] = ctx.c[i]
            p = len(starts) - 1
            self.pidx[i] = p
            ends = (t + tf) % per == 0
            if ends:
                self.closed[i] = p + 1
                x = ctx.c[i]
                self.part[i] = (x, x, x, x)
            else:
                self.closed[i] = p
                self.part[i] = (po[p], ph[p], pl[p], ctx.c[i])
        # a candle's values once it is finished (the running values above end
        # at its last bar; a candle still forming at the frame's end is never
        # read as finished)
        self.o, self.h, self.l, self.c = po, ph, pl, pc
        self.e50 = ind.ema(pc, 50)
        self.e200 = ind.ema(pc, 200)
        self.atr = ind.atr(ph, pl, pc, 14) if len(pc) else []
        self._struct = _htf_structure(ph, pl)

    def length(self, i: int) -> int:
        """How many bigger candles the app had at bar i (finished + forming)."""
        return self.closed[i] + 1

    def last_close(self, i: int) -> float:
        return self.part[i][3]

    def ema_side(self, i: int, which: int, need: int):
        """(bull, bear) of the forming candle's close against the bigger
        EMA`which` worked out over the finished closes and that close; (True,
        True) - agreeing - when fewer than `need` bigger candles exist
        (difference 2 in the module docstring)."""
        m = self.closed[i]
        if m + 1 < max(need, which):
            return True, True
        x = self.last_close(i)
        if m + 1 == which:
            e = (sum(self.c[:m]) + x) / which
        else:
            k = 2.0 / (which + 1)
            e = x * k + (self.e50 if which == 50 else self.e200)[m - 1] * (1 - k)
        return x > e, x < e

    def structure(self, i: int):
        """(bull, bear): the last two bigger swing highs and lows both rising
        (bull) or both falling (bear); needs 20 bigger candles."""
        if self.length(i) < 20:
            return False, False
        return self._struct(self.closed[i])

    def arrays(self, i: int, tail: int):
        """The last `tail` finished bigger candles and the forming one, as
        (o, h, l, c) lists — what a detector reading the bigger frame sees."""
        m = self.closed[i]
        a = max(0, m - tail)
        p = self.part[i]
        return (self.o[a:m] + [p[0]], self.h[a:m] + [p[1]],
                self.l[a:m] + [p[2]], self.c[a:m] + [p[3]])

    def atr_last(self, i: int):
        """The bigger ATR(14) with the forming candle as its last value."""
        m = self.closed[i]
        if m < 13:
            return None
        p = self.part[i]
        pc_ = self.c[m - 1] if m >= 1 else p[3]
        tr = max(p[1] - p[2], abs(p[1] - pc_), abs(p[2] - pc_))
        if m == 13:
            trs = ind.true_ranges(self.h[:13], self.l[:13], self.c[:13])
            return (sum(trs) + tr) / 14
        return (self.atr[m - 1] * 13 + tr) / 14


def _htf_structure(ph, pl):
    """For every count of finished bigger candles m: the app's swing loop over
    the bigger frame (1-bar pivots, newest first, from length - 3 down)."""
    n = len(ph)
    piv_h = [k for k in range(1, n - 1) if ph[k] > ph[k - 1] and ph[k] > ph[k + 1]]
    piv_l = [k for k in range(1, n - 1) if pl[k] < pl[k - 1] and pl[k] < pl[k + 1]]

    def at(m: int):
        # bigger frame length L = m + 1; pivots k with 2 <= k <= L - 3 = m - 2,
        # the two newest of each (the app walks back from L - 3)
        top = m - 2
        hi = bisect.bisect_right(piv_h, top)
        lo_ = bisect.bisect_right(piv_l, top)
        ks_h = [k for k in piv_h[max(0, hi - 3):hi] if k >= 2][-2:]
        ks_l = [k for k in piv_l[max(0, lo_ - 3):lo_] if k >= 2][-2:]
        if len(ks_h) < 2 or len(ks_l) < 2:
            return False, False
        h0, h1 = ph[ks_h[1]], ph[ks_h[0]]
        l0, l1 = pl[ks_l[1]], pl[ks_l[0]]
        return h0 > h1 and l0 > l1, h0 < h1 and l0 < l1
    return at


# --------------------------------------------------------------- scoring

def _quality(qs: list) -> int:
    """makeSignal's score: average quality + (count - 1), floored, max 8."""
    return min(8, int(math.floor(sum(qs) / len(qs) + (len(qs) - 1))))


def _best(buy, sell) -> int:
    """`buy && sell ? (buy.quality >= sell.quality ? buy : sell) : buy ?? sell`."""
    if buy is not None and sell is not None:
        return 1 if buy >= sell else -1
    if buy is not None:
        return 1
    if sell is not None:
        return -1
    return 0


def _with_pattern(ctx: Ctx, i: int, buy: list, sell: list):
    """The chart pattern adds one signal (quality 4) to its own side."""
    p = ctx.pattern(i)
    if p is not None:
        (buy if p[0] == "buy" else sell).append(4)
    return buy, sell


def dedup_4h(ctx: Ctx, dirs: list) -> list:
    """The scanner sends a coin + timeframe + strategy + side at most once per
    4 hours (backgroundScanner.ts SIGNAL_COOLDOWN_MS); a repeat inside that is
    never traded."""
    out = list(dirs)
    last = {1: -10 ** 18, -1: -10 ** 18}
    for i, d in enumerate(dirs):
        if not d:
            continue
        if ctx.ts[i] - last[d] < H4_MS:
            out[i] = 0
        else:
            last[d] = ctx.ts[i]
    return out


# ----------------------------------------------------- Elite (ECB and ERR)

def raw_elite(ctx: Ctx, strategy: str) -> list:
    """Per bar, everything the two Elite rules read that no switch changes."""
    htf = ctx.htf()
    out = []
    a_body_high = 70 if strategy == "ecb" else 65
    for i in range(ctx.n):
        if i < 50:
            out.append(None)
            continue
        h, lo, c, o, v = ctx.h, ctx.l, ctx.c, ctx.o, ctx.v
        atr = ctx.atr[i]
        reg = ctx.regime[i]
        med = reg == "medium"
        sh, sh_i, sl, sl_i = _swing(ctx, i, 60)
        ext = 0.005 if med else 0.003
        fresh_lim = 4 if med else 6

        def pool(idx, ref, up):
            if idx < 4:
                return False
            for k in range(idx - 3, max(2, idx - 40) - 1, -1):
                if up:
                    if h[k] > h[k - 1] and h[k] > h[k + 1] and abs(h[k] - ref) / ref <= 0.002:
                        return True
                elif lo[k] < lo[k - 1] and lo[k] < lo[k + 1] and abs(lo[k] - ref) / ref <= 0.002:
                    return True
            return False

        def crange(idx):
            if idx < 8:
                return atr * 8
            return max(h[idx - 8:idx]) - min(lo[idx - 8:idx])

        def cbars(idx):
            if idx < 8:
                return 0
            return sum(1 for k in range(idx - 8, idx) if h[k] - lo[k] <= atr * 0.8)

        cr_b, cr_s = crange(sh_i), crange(sl_i)
        cmult = 0.8 if med else 1.0

        def breakout(idx, level, up):
            if idx < 0:
                return -1
            for k in range(max(idx + 1, i - 20), i + 1):
                if up and c[k] > level * (1 + ext):
                    return k
                if not up and c[k] < level * (1 - ext):
                    return k
            return -1

        b_b, b_s = breakout(sh_i, sh, True), breakout(sl_i, sl, False)
        avg = ctx.avgvol[i]
        a_body = a_body_high if reg == "high" else 65
        b_body = 55 if med else 45
        b_vol = 2.0 if med else 1.5

        def grade(k, up, crng):
            if k < 0:
                return 0
            rng = h[k] - lo[k]
            body_pct = abs(c[k] - o[k]) / rng * 100 if rng > 0 else 0.0
            vm = v[k] / avg if avg > 0 else 1.0
            if rng > atr * 4 or (up and c[k] <= o[k]) or (not up and c[k] >= o[k]):
                return 0
            if up and c[k] < lo[k] + rng * 0.75:
                return 0
            if not up and c[k] > lo[k] + rng * 0.25:
                return 0
            if k >= 3:
                ra = (v[k - 1] + v[k - 2] + v[k - 3]) / 3
                if ra > 0 and v[k] <= ra:
                    return 0
            tight = crng < atr * 8 * 0.8
            if body_pct >= a_body and vm >= 2.5 and tight:
                return 2
            if body_pct >= b_body and vm >= b_vol:
                return 1
            return 0

        g_b, g_s = grade(b_b, True, cr_b), grade(b_s, False, cr_s)

        def retest(k0, level, up):
            # (retest, ema-aligned, volume-ok, breakout volume)
            if not (0 <= k0 < i):
                return False, False, False, 0.0
            bv = v[k0]
            for k in range(k0 + 1, i + 1):
                if up:
                    near = level > 0 and level - atr * 0.3 <= lo[k] <= level + atr * 0.3
                    hold = c[k] >= level
                    edge = lo[k]
                else:
                    near = level < INF and level - atr * 0.3 <= h[k] <= level + atr * 0.3
                    hold = c[k] <= level
                    edge = h[k]
                if near and hold:
                    e = ctx.e20[k]
                    al = e is not None and abs(edge - e) / e <= 0.003
                    return True, al, bv > 0 and v[k] <= bv * 0.7, bv
            return False, False, False, bv

        rt_b = retest(b_b, sh, True)
        rt_s = retest(b_s, sl, False)
        rng_i = h[i] - lo[i]
        body_i = abs(c[i] - o[i]) / rng_i * 100 if rng_i > 0 else 100.0
        e20 = ctx.e20[i]
        rev_b = (b_b >= 0 and sh > 0 and sh - atr * 0.3 <= lo[i] <= sh + atr * 0.3
                 and c[i] > sh and ctx.bull[i] and body_i >= 50)
        rev_s = (b_s >= 0 and sl < INF and sl - atr * 0.3 <= h[i] <= sl + atr * 0.3
                 and c[i] < sl and ctx.bear[i] and body_i >= 50)
        bob, beob = ind.order_blocks(o, h, lo, c, i + 1, 60)
        zones = ind.fvg_zones(h, lo, i + 1, 60)
        st_b, st_s = htf.structure(i)
        he_b, he_s = htf.ema_side(i, 50, 55)
        out.append({
            "reg": reg, "sh": sh, "sl": sl, "b_b": b_b, "b_s": b_s,
            "fresh_b": b_b >= 0 and i - b_b <= fresh_lim,
            "fresh_s": b_s >= 0 and i - b_s <= fresh_lim,
            "g_b": g_b, "g_s": g_s,
            "pool_b": pool(sh_i, sh, True), "pool_s": pool(sl_i, sl, False),
            "cons_b": cr_b < atr * 8 * cmult, "cons_s": cr_s < atr * 8 * cmult,
            "cbars_b": cbars(sh_i), "cbars_s": cbars(sl_i),
            "rt_b": rt_b[0], "rta_b": rt_b[1], "rtv_b": rt_b[2],
            "rt_s": rt_s[0], "rta_s": rt_s[1], "rtv_s": rt_s[2],
            "rev_b": rev_b, "rev_s": rev_s,
            "revv_b": rev_b and rt_b[3] > 0 and v[i] <= rt_b[3] * 0.7,
            "revv_s": rev_s and rt_s[3] > 0 and v[i] <= rt_s[3] * 0.7,
            "reva_b": rev_b and e20 is not None and abs(lo[i] - e20) / e20 <= 0.003,
            "reva_s": rev_s and e20 is not None and abs(h[i] - e20) / e20 <= 0.003,
            "ob_b": bob is not None, "ob_s": beob is not None,
            "fvg_b": any(z[0] == "bull" and z[1] < c[i] for z in zones),
            "fvg_s": any(z[0] == "bear" and z[2] > c[i] for z in zones),
            "st_b": st_b, "st_s": st_s, "he_b": he_b, "he_s": he_s,
        })
    return out


def _vol_ok(sw_vol: str, reg: str) -> bool:
    if sw_vol == "medium" and reg == "low":
        return False
    if sw_vol == "high" and reg != "high":
        return False
    return True


def decide_ecb(ctx: Ctx, raw: list, sw: dict) -> list:
    """Elite Context Breakout (signalEval.ts 651-1021, 1771-1802, 2148-2237).
    Switches: session, vol, ob, fvg, htfema, retest. Preset: min quality 4,
    no confluence count, liquidity sweep / EMA-distance / entry confirm off."""
    dirs = [0] * ctx.n
    for i, r in enumerate(raw):
        if r is None:
            continue
        sess = ctx.elite_session(i) if sw["session"] else True
        if not sess or not (r["st_b"] or r["st_s"]) or (r["g_b"] == 0 and r["g_s"] == 0):
            continue
        res = []
        for up in (True, False):
            s = "_b" if up else "_s"
            qs = [q for ok, q in (
                (r["b" + s] >= 0, 4), (r["g" + s] == 2, 5), (r["fresh" + s], 5),
                (r["pool" + s], 5), (r["cons" + s], 4), (r["st" + s], 5), (r["he" + s], 5),
                (r["rt" + s], 5), (r["rtv" + s], 4), (r["rta" + s], 5),
                (ctx.c[i] > ctx.cur_e50[i] if up else ctx.c[i] < ctx.cur_e50[i], 4),
                (ctx.c[i] > ctx.cur_e200[i] if up else ctx.c[i] < ctx.cur_e200[i], 5),
                ((45 <= ctx.rsi[i] <= 70) if up else (30 <= ctx.rsi[i] <= 55), 4),
                (ctx.mh[i] > 0 if up else ctx.mh[i] < 0, 4)) if ok]
            res.append(qs)
        buy, sell = _with_pattern(ctx, i, res[0], res[1])
        dirs[i] = _best(_make_ecb(ctx, r, sw, i, True, buy),
                        _make_ecb(ctx, r, sw, i, False, sell))
    return dedup_4h(ctx, dirs)


def _make_ecb(ctx, r, sw, i, up, qs):
    if not qs:
        return None
    q = _quality(qs)
    if q < 4:
        return None
    if sw["session"] and not ctx.elite_session(i):
        return None
    reg = r["reg"]
    if not _vol_ok(sw["vol"], reg):
        return None
    s = "_b" if up else "_s"
    if sw["ob"] and not r["ob" + s]:
        return None
    if sw["fvg"] and not r["fvg" + s]:
        return None
    lvl = r["sh"] if up else r["sl"]
    price = ctx.c[i]
    if (up and price < lvl) or (not up and price > lvl):
        return None
    retest = r["rt" + s]
    if not r["fresh" + s] and not retest:
        return None
    g = r["g" + s]
    if reg == "medium" and g == 2 and not r["pool" + s]:
        return None
    if not r["st" + s] or not r["cons" + s] or r["cbars" + s] < 5 or g == 0:
        return None
    he = r["he" + s]
    if not he and g < 2:
        return None
    if sw["htfema"] and not he:
        return None
    if not retest and g < 2:
        return None
    if sw["retest"] and not retest:
        return None
    if retest and not r["rta" + s]:
        return None
    if reg == "medium":
        rmin, rmax = (55, 45) if g == 2 else (52, 48)
    else:
        rmin, rmax = 50, 50
    if up and ctx.rsi[i] < rmin:
        return None
    if not up and ctx.rsi[i] > rmax:
        return None
    sl_mult = (1.2 if reg == "high" else 1.0) if g == 2 else 1.5
    sl = lvl - ctx.atr[i] * sl_mult if up else lvl + ctx.atr[i] * sl_mult
    if (up and sl >= price) or (not up and sl <= price):
        return None
    return q


def decide_err(ctx: Ctx, raw: list, sw: dict) -> list:
    """Elite Retest Reversal (signalEval.ts 951-973, 1736-1769, 2042-2146).
    Switches: session, ob, agrade, htfema50, stoch, maxbars. Preset: min
    quality 6, volatility 'medium', gap / sweep / multi-retest off."""
    dirs = [0] * ctx.n
    k_arr = None
    if sw["stoch"]:
        k_arr = ctx.memo("stoch1433", lambda: ind.stochastic(ctx.h, ctx.l, ctx.c, 14, 3, 3))[0]
    for i, r in enumerate(raw):
        if r is None:
            continue
        sess = ctx.elite_session(i) if sw["session"] else True
        if not sess or not (r["st_b"] or r["st_s"]) or not (r["rev_b"] or r["rev_s"]):
            continue
        res = []
        for up in (True, False):
            s = "_b" if up else "_s"
            qs = [q for ok, q in (
                (r["rev" + s], 6), (r["revv" + s], 4), (r["reva" + s], 5),
                (r["g" + s] == 2, 5), (r["pool" + s], 5), (r["cons" + s], 4),
                (r["st" + s], 5), (r["he" + s], 5),
                (ctx.c[i] > ctx.cur_e50[i] if up else ctx.c[i] < ctx.cur_e50[i], 4),
                (ctx.c[i] > ctx.cur_e200[i] if up else ctx.c[i] < ctx.cur_e200[i], 5),
                ((45 <= ctx.rsi[i] <= 70) if up else (30 <= ctx.rsi[i] <= 55), 4),
                (ctx.mh[i] > 0 if up else ctx.mh[i] < 0, 4)) if ok]
            res.append(qs)
        buy, sell = _with_pattern(ctx, i, res[0], res[1])
        dirs[i] = _best(_make_err(ctx, r, sw, i, True, buy, k_arr),
                        _make_err(ctx, r, sw, i, False, sell, k_arr))
    return dedup_4h(ctx, dirs)


def _make_err(ctx, r, sw, i, up, qs, k_arr):
    if not qs:
        return None
    q = _quality(qs)
    if q < 6:
        return None
    if sw["session"] and not ctx.elite_session(i):
        return None
    if not _vol_ok("medium", r["reg"]):
        return None
    s = "_b" if up else "_s"
    if not r["rev" + s] or not r["st" + s]:
        return None
    if sw["ob"] and not r["ob" + s]:
        return None
    if sw["agrade"] and r["g" + s] != 2:
        return None
    if sw["htfema50"] and not r["he" + s]:
        return None
    if sw["maxbars"]:
        b = r["b" + s]
        if b < 0 or i - b > 8:
            return None
    if sw["stoch"]:
        last_k = k_arr[i] if i < len(k_arr) else None
        prev_k = k_arr[i - 3] if i >= 3 else None
        if last_k is None or prev_k is None:
            return None
        if up and not (prev_k < 30 and last_k > prev_k):
            return None
        if not up and not (prev_k > 70 and last_k < prev_k):
            return None
    lvl = r["sh"] if up else r["sl"]
    mult = 1.0 if r["reg"] == "high" else 0.7
    sl = lvl - ctx.atr[i] * mult if up else lvl + ctx.atr[i] * mult
    price = ctx.c[i]
    if (up and sl >= price) or (not up and sl <= price):
        return None
    return q


# --------------------------------------------------------- Breakout Retest

def raw_br(ctx: Ctx) -> list:
    """Breakout Retest's per-bar facts, for both volume settings (the volume
    switch changes which candle counts as the breakout)."""
    htf = ctx.htf()
    h, lo, c, v = ctx.h, ctx.l, ctx.c, ctx.v
    out = []
    for i in range(ctx.n):
        if i < 50:
            out.append(None)
            continue
        atr = ctx.atr[i]
        sh, sh_i, sl, sl_i = _swing(ctx, i, 50)
        avg = ctx.avgvol[i]
        res = {}
        for mult in (1.8, 1.0):
            def brk(idx, level, up):
                if idx < 0:
                    return -1
                for k in range(max(idx + 1, i - 20), i + 1):
                    vm = v[k] / avg if avg > 0 else 1.0
                    if (c[k] > level if up else c[k] < level) and vm >= mult:
                        return k
                return -1

            def retest(b, level, up):
                if b < 0 or b >= i:
                    return False
                move = (c[b] - level) if up else (level - c[b])
                if move <= 0:
                    return False
                buf = atr * 0.2      # preset: ATR entry buffer on, 0.2 x ATR
                bv = v[b]
                for k in range(b + 1, min(i, b + 12) + 1):
                    depth = ((c[b] - lo[k]) if up else (h[k] - c[b])) / move
                    vol_ok = bv > 0 and v[k] <= bv * 0.7
                    edge = lo[k] if up else h[k]
                    if level - buf <= edge <= level + buf and 0 <= depth <= 0.618 and vol_ok:
                        return True
                return False

            bb, bs = brk(sh_i, sh, True), brk(sl_i, sl, False)
            res[mult] = (bb, bs, retest(bb, sh, True), retest(bs, sl, False))
        he_b, he_s = htf.ema_side(i, 50, 55)
        part = htf.part[i]
        big = htf.length(i) >= 20
        e_now, e_prev = ctx.e50[i], ctx.e50[max(0, i - 10)]
        rng = h[i] - lo[i]
        body = abs(c[i] - ctx.o[i]) / rng * 100 if rng > 0 else 100.0
        out.append({
            "sh": sh, "sl": sl, "res": res,
            "bias_b": he_b or (big and part[3] > part[0]),
            "bias_s": he_s or (big and part[3] < part[0]),
            "slope_b": e_now is not None and e_prev is not None and e_now > e_prev,
            "slope_s": e_now is not None and e_prev is not None and e_now < e_prev,
            "atr_ok": (atr / c[i] * 100) > 0.4,
            "range_ok": not (math.isfinite(rng) and rng > atr * 3),
            "strong": body >= 50,
        })
    return out


def decide_br(ctx: Ctx, raw: list, sw: dict) -> list:
    """Breakout Retest (signalEval.ts 292-366, 1028-1102, 1953-2007).
    Switches: model (breakout_close / retest_hold / retest_confirm), htf, adx,
    volume, retest. Preset: min quality 5, strong close 50%, ATR buffer 0.2,
    min ATR 0.4%, max range 3 ATR, ADX 25, volatility 'medium', session off."""
    dirs = [0] * ctx.n
    mult = 1.8 if sw["volume"] else 1.0
    for i, r in enumerate(raw):
        if r is None:
            continue
        bb, bs, rb, rs = r["res"][mult]
        buy = []
        sell = []
        ready = False
        if r["range_ok"] and r["atr_ok"] and not (sw["adx"] and ctx.adx[i] < 25):
            conf_b = ctx.bull[i] and r["strong"]
            conf_s = ctx.bear[i] and r["strong"]
            model = sw["model"]
            if model == "breakout_close":
                rd_b, rd_s = bb == i, bs == i
            elif model == "retest_hold":
                rd_b, rd_s = rb, rs
            else:
                rd_b, rd_s = rb and conf_b, rs and conf_s
            if sw["htf"]:
                rd_b = rd_b and r["bias_b"] and r["slope_b"]
                rd_s = rd_s and r["bias_s"] and r["slope_s"]
            ready = rd_b or rd_s
            if ready:
                rsi = ctx.rsi[i]
                buy = [q for ok, q in ((bb >= 0, 5), (rb, 6), (conf_b, 5), (r["bias_b"], 4),
                                       (ctx.c[i] > ctx.cur_e50[i], 4), (45 <= rsi <= 70, 4),
                                       (ctx.mh[i] > 0, 4)) if ok]
                sell = [q for ok, q in ((bs >= 0, 5), (rs, 6), (conf_s, 5), (r["bias_s"], 4),
                                        (ctx.c[i] < ctx.cur_e50[i], 4), (30 <= rsi <= 55, 4),
                                        (ctx.mh[i] < 0, 4)) if ok]
        if r["range_ok"]:
            # the chart pattern still counts when nothing above is ready —
            # the app only returns early on an oversized candle
            buy, sell = _with_pattern(ctx, i, buy, sell)
        dirs[i] = _best(_make_br(ctx, r, sw, i, True, buy, bb, rb),
                        _make_br(ctx, r, sw, i, False, sell, bs, rs))
    return dedup_4h(ctx, dirs)


def _make_br(ctx, r, sw, i, up, qs, brk, ret):
    if not qs:
        return None
    q = _quality(qs)
    if q < 5:
        return None
    if not _vol_ok("medium", ctx.regime[i]):
        return None
    if brk < 0:
        return None
    if sw["retest"] and not ret:
        return None
    lvl = r["sh"] if up else r["sl"]
    price = ctx.c[i]
    sl = lvl - ctx.atr[i] * 0.5 if up else lvl + ctx.atr[i] * 0.5
    if (up and sl >= price) or (not up and sl <= price):
        return None
    return q


# ------------------------------------------------------ Confirmation Model

_CM_WINDOW = {60: 60, 300: 48, 900: 32, 3600: 24, 14400: 12, 86400: 6}


def raw_cm(ctx: Ctx) -> dict:
    """Per bar e, the Confirmation Model's checks of a setup at e (preset:
    strong close 50%, volume ratio 1.1); and per bar i, the bigger-timeframe
    gap delivery the app reads at the time of the scan."""
    o, h, lo, c, v = ctx.o, ctx.h, ctx.l, ctx.c, ctx.v
    n = ctx.n
    htf = ctx.htf()
    cisd = [None] * n
    sweep = [(False, False)] * n
    isweep = [(False, False)] * n
    div = [(False, False)] * n
    tgt = [(False, False)] * n
    obs = [(False, False)] * n
    volok = [False] * n
    for e in range(n):
        if e < 50:
            continue
        res = []
        for up in (True, False):
            cnt, k = 0, e - 1
            while k >= 1 and cnt < 6:
                opp = c[k] < o[k] if up else c[k] > o[k]
                if not opp:
                    break
                cnt += 1
                k -= 1
            ok, lvl = False, 0.0
            if cnt >= 2:
                start, end = k + 1, e - 1
                if start <= end:
                    rng = max(h[e] - lo[e], 1e-8)
                    body = abs(c[e] - o[e]) / rng * 100
                    if body >= 50 and ((up and c[e] > o[e]) or (not up and c[e] < o[e])):
                        if up:
                            lvl = max(h[start:end + 1])
                            ok = c[e] > lvl
                        else:
                            lvl = min(lo[start:end + 1])
                            ok = c[e] < lvl
            res.append((ok, lvl))
        cisd[e] = res
        now = ind.liquidity_sweep(h, lo, c, o, e + 1, 25)
        prev = ind.liquidity_sweep(h, lo, c, o, e, 25) if e + 1 > 55 else (False, False)
        sweep[e] = (now[0] or prev[0], now[1] or prev[1])
        isweep[e] = ind.liquidity_sweep(h, lo, c, o, e + 1, 10)
        div[e] = ind.rsi_divergence(c, ctx.rsi_raw, e + 1, 60, 5)
        w = max(0, e + 1 - 120)
        hi_, lo_ = max(h[w:e + 1]), min(lo[w:e + 1])
        tgt[e] = (hi_ > c[e] * 1.005, lo_ < c[e] * 0.995)
        bo, be = ind.order_blocks(o, h, lo, c, e + 1, 40)
        obs[e] = (bo is not None, be is not None)
        a0 = max(0, e - 20)
        avg = (ctx.vpre[e] - ctx.vpre[a0]) / (e - a0) if e > a0 else v[e]
        volok[e] = (v[e] >= avg * 1.1) if avg > 0 else True
    deliv = [(False, False)] * n
    for i in range(n):
        if i < 50:
            continue
        if htf.length(i) >= 10:
            so, sh_, sl_, sc = htf.arrays(i, 90)
        else:
            a = max(0, i + 1 - 90)
            sh_, sl_, sc = h[a:i + 1], lo[a:i + 1], c[a:i + 1]
        if len(sc) < 10:
            continue
        zones = ind.fvg_zones(sh_, sl_, len(sc), 80)
        if not zones:
            continue
        last = len(sc) - 1
        got = [False, False]
        for k in range(last, max(2, last - 5) - 1, -1):
            for zi in range(len(zones) - 1, max(0, len(zones) - 10) - 1, -1):
                z = zones[zi]
                if abs(k - z[4]) < 2:
                    continue
                tapped = sl_[k] <= z[1] and sh_[k] >= z[2]
                if z[0] == "bull" and tapped and sc[k] > z[3]:
                    got[0] = True
                if z[0] == "bear" and tapped and sc[k] < z[3]:
                    got[1] = True
        deliv[i] = (got[0], got[1])
    return {"cisd": cisd, "sweep": sweep, "isweep": isweep, "div": div, "tgt": tgt,
            "ob": obs, "vol": volok, "deliv": deliv}


def decide_cm(ctx: Ctx, raw: dict, sw: dict) -> list:
    """Confirmation Model (signalEval.ts 370-649): at each scan, the newest
    setup in the last 24 bars (1h; 32 on 15m, 12 on 4h, 6 on 1d) that passes,
    entered at the current price. Switches: sweep, fvg, cisdretest, ob,
    volume, session. Preset: min quality 4 (checks out of 7), strong close."""
    n = ctx.n
    dirs = [0] * n
    win = _CM_WINDOW.get(ctx.tf_s, 24)
    cisd = raw["cisd"]
    for i in range(50, n):
        price = ctx.c[i]
        for e in range(i, max(50, i - win) - 1, -1):
            if sw["session"] and not ctx.elite_session(e):
                continue
            cs = cisd[e]
            if cs is None:
                continue
            (bok, blvl), (sok, slvl) = cs
            if not bok and not sok:
                continue
            up = True if (bok and not sok) else (False if (sok and not bok) else ctx.bull[e])
            lvl = blvl if up else slvl
            j = 0 if up else 1
            if sw["cisdretest"]:
                if e >= i:
                    continue
                a = ctx.atr[e]
                found = False
                for rr in range(e + 1, min(e + 5, i) + 1):
                    if up and ctx.l[rr] <= lvl + a * 0.5 and ctx.c[rr] >= lvl - a * 0.15:
                        found = True
                        break
                    if not up and ctx.h[rr] >= lvl - a * 0.5 and ctx.c[rr] <= lvl + a * 0.15:
                        found = True
                        break
                if not found:
                    continue
            has_sweep = raw["sweep"][e][j]
            deliv = raw["deliv"][i][j]
            if sw["sweep"] and not has_sweep:
                continue
            if sw["fvg"] and not deliv:
                continue
            if sw["ob"] and not raw["ob"][e][j]:
                continue
            if sw["volume"] and not raw["vol"][e]:
                continue
            checks = (has_sweep + deliv + 1 + raw["div"][e][j] + raw["isweep"][e][j]
                      + raw["tgt"][e][j])
            if checks < 4:
                continue
            a = ctx.atr[e]
            w0 = max(0, e - 20)
            if up:
                sl = min(ctx.l[w0:e + 1]) - a * 0.2
                if sl >= price:
                    continue
            else:
                sl = max(ctx.h[w0:e + 1]) + a * 0.2
                if sl <= price:
                    continue
            dirs[i] = 1 if up else -1
            break
    return dedup_4h(ctx, dirs)


# ------------------------------------------------------- FluxGate Dual Engine

def raw_fg(ctx: Ctx) -> list:
    """FluxGate's per-bar facts (preset: engine 48/64, guide 14, k 1.1/1.3,
    ADX 22, session 08-12 UTC, structure tolerance 0.25 bigger ATR, RSI
    divergence + extreme Stochastic cross (30/70), volume 1.5x and rising)."""
    o, h, lo, c, v = ctx.o, ctx.h, ctx.l, ctx.c, ctx.v
    htf = ctx.htf()
    lc, sc = ind.flux_scores(o, h, lo, c)
    k, d = ctx.memo("stoch1433", lambda: ind.stochastic(h, lo, c, 14, 3, 3))
    out = []
    for i in range(ctx.n):
        if i < 66:
            out.append(None)
            continue
        price = c[i]
        if htf.length(i) >= 60:
            ho, hh, hl, hc = htf.arrays(i, 90)
            hatr = htf.atr_last(i)
            hatr = hatr if hatr is not None else ctx.atr[i]
            bias = htf.ema_side(i, 200, 200)
        else:
            a = max(0, i + 1 - 90)
            ho, hh, hl, hc = o[a:i + 1], h[a:i + 1], lo[a:i + 1], c[a:i + 1]
            hatr = ctx.atr[i]
            e = ctx.e200[i]
            bias = (True, True) if e is None else (price > e, price < e)
        tol = hatr * 0.25
        bo, be = ind.order_blocks(ho, hh, hl, hc, len(hc), 60)
        zones = ind.fvg_zones(hh, hl, len(hc), 80)
        near_b = any(z[0] == "bull" and z[2] - tol <= price <= z[1] + tol for z in zones)
        near_s = any(z[0] == "bear" and z[2] - tol <= price <= z[1] + tol for z in zones)
        dem = (bo["low"] - tol <= price <= bo["high"] + tol) if bo else near_b
        sup = (be["low"] - tol <= price <= be["high"] + tol) if be else near_s
        dv = ind.rsi_divergence(c, ctx.rsi_raw, i + 1, 40, 5)
        pk, pd_, ck, cd = k[i - 1], d[i - 1], k[i], d[i]
        have = None not in (pk, pd_, ck, cd)
        up_x = have and pk <= pd_ and ck > cd and min(pk, pd_) <= 30
        dn_x = have and pk >= pd_ and ck < cd and max(pk, pd_) >= 70
        a20 = max(0, i - 20)
        sma20 = (ctx.vpre[i] - ctx.vpre[a20]) / (i - a20) if i > a20 else v[i]
        a5 = max(0, i - 5)
        sma5 = (ctx.vpre[i] - ctx.vpre[a5]) / (i - a5) if i > a5 else v[i]
        ratio = v[i] / sma20 if sma20 > 0 else 1.0
        vol_ok = ratio >= 1.5 and (v[i] > v[i - 1] and sma5 >= sma20)
        hour = (ctx.ts[i] // 1000 % 86400) // 3600
        out.append({
            "lx": lc[i], "sx": sc[i], "adx": ctx.adx[i] >= 22, "sess": 8 <= hour < 12,
            "dem": dem, "sup": sup, "mom_b": dv[0] and up_x, "mom_s": dv[1] and dn_x,
            "vol": vol_ok, "bias_b": bias[0], "bias_s": bias[1],
        })
    return out


def decide_fg(ctx: Ctx, raw: list, sw: dict) -> list:
    """FluxGate Dual Engine (signalEval.ts 1386-1538, 1920-1951). Switches:
    session, adx, structure, momentum, volume, htf, and min quality (the
    app's preset 0 lets a chart pattern alone open a trade; 5 does not)."""
    dirs = [0] * ctx.n
    labels = [4, 4, 6, 5, 4, 4, 3, 4, 3]
    for i, r in enumerate(raw):
        if r is None:
            continue
        common = ((not sw["adx"] or r["adx"]) and (not sw["session"] or r["sess"])
                  and (not sw["volume"] or r["vol"]))
        long_all = (common and r["lx"] and (not sw["structure"] or r["dem"])
                    and (not sw["momentum"] or r["mom_b"]) and (not sw["htf"] or r["bias_b"]))
        short_all = (common and r["sx"] and (not sw["structure"] or r["sup"])
                     and (not sw["momentum"] or r["mom_s"]) and (not sw["htf"] or r["bias_s"]))
        buy = list(labels) if long_all else []
        sell = list(labels) if short_all else []
        buy, sell = _with_pattern(ctx, i, buy, sell)
        mq = sw["minq"]
        qb = _quality(buy) if buy else None
        qs = _quality(sell) if sell else None
        dirs[i] = _best(qb if qb is not None and qb >= mq else None,
                        qs if qs is not None and qs >= mq else None)
    return dedup_4h(ctx, dirs)


# --------------------------------------------------------- Supertrend + RelVol

def raw_st(ctx: Ctx) -> list:
    """Supertrend + RelVol's per-bar facts (preset: ATR 10 x 3.0, relative
    volume 20 bars >= 1.5x, bigger EMA 200, ADX 14 >= 22, DI 14, impulse body
    55% / wick 30%)."""
    h, lo, c, v, o = ctx.h, ctx.l, ctx.c, ctx.v, ctx.o
    htf = ctx.htf()
    d = ind.supertrend(h, lo, c, 10, 3.0)
    plus, minus = ind.di(h, lo, c, 14)
    out = []
    for i in range(ctx.n):
        if i < 2:
            out.append(None)
            continue
        a = max(0, i - 20)
        avg = (ctx.vpre[i] - ctx.vpre[a]) / (i - a) if i > a else 0.0
        now = v[i]
        has = avg > 0 and now > 0
        rel = now / avg if has else 1.0
        if htf.length(i) >= 205:
            hb = htf.ema_side(i, 200, 200)
            hbull = hb[0]
        else:
            e = ctx.e200[i]
            hbull = None if e is None else c[i] > e
        rng = h[i] - lo[i]
        if rng > 0:
            body = abs(c[i] - o[i]) / rng * 100
            uw = (h[i] - max(o[i], c[i])) / rng * 100
            lw = (min(o[i], c[i]) - lo[i]) / rng * 100
            imp_b = ctx.bull[i] and body >= 55 and uw <= 30
            imp_s = ctx.bear[i] and body >= 55 and lw <= 30
        else:
            imp_b = imp_s = True
        ax = ctx.adx_raw[i]
        p_, m_ = plus[i], minus[i]
        out.append({
            "flip_b": d[i - 1] == "bear" and d[i] == "bull",
            "flip_s": d[i - 1] == "bull" and d[i] == "bear",
            "tr_b": d[i] == "bull", "tr_s": d[i] == "bear",
            "rv": has and rel >= 1.5, "hbull": hbull,
            "adx": ax is not None and math.isfinite(ax) and ax >= 22,
            "di_have": p_ is not None and m_ is not None,
            "di_b": p_ is not None and m_ is not None and p_ > m_,
            "di_s": p_ is not None and m_ is not None and m_ > p_,
            "imp_b": imp_b, "imp_s": imp_s,
        })
    return out


def decide_st(ctx: Ctx, raw: list, sw: dict) -> list:
    """Supertrend + RelVol (signalEval.ts 1104-1384, 2009-2040), in the
    app's preset confluence mode: the flip (or trend) plus at least one more
    agreeing signal (min confluence 2, min quality 5). Switches: flip, relvol,
    htf, adx, impulse, di — each one a signal that MAY count."""
    dirs = [0] * ctx.n
    for i, r in enumerate(raw):
        if r is None:
            continue
        gl = r["flip_b"] if sw["flip"] else r["tr_b"]
        gs = r["flip_s"] if sw["flip"] else r["tr_s"]
        buy, sell = [], []
        for up, gate in ((True, gl), (False, gs)):
            if not gate:
                continue
            s = "_b" if up else "_s"
            qs = [6]
            if sw["relvol"] and r["rv"]:
                qs.append(4)
            if sw["htf"] and r["hbull"] is (True if up else False):
                qs.append(4)
            if sw["adx"] and r["adx"]:
                qs.append(4)
            if sw["di"] and r["di_have"] and r["di" + s]:
                qs.append(3)
            if sw["impulse"] and r["imp" + s]:
                qs.append(3)
            (buy if up else sell).extend(qs)
        buy, sell = _with_pattern(ctx, i, buy, sell)
        dirs[i] = _best(_conf_ok(buy, 5, 2), _conf_ok(sell, 5, 2))
    return dedup_4h(ctx, dirs)


def _conf_ok(qs, min_q, min_conf):
    if not qs:
        return None
    q = _quality(qs)
    if q < min_q or len(qs) < min_conf:
        return None
    return q


# -------------------------------------------------------------- BB Stoch S/D

def raw_bb(ctx: Ctx) -> list:
    """BB Stoch S/D's per-bar facts (preset: Bollinger 20 / 2.0, Stochastic
    14/3/3 with 20/80, 3-bar lookback, zones of an 80-bar window with a leg of
    2 ATR, fresh = 2 retests or fewer, tolerance 0.3 ATR, order block / gap
    fallback on, hammer wick 70%, RSI 30-45 / 55-70, ADX cap 22)."""
    o, h, lo, c, v = ctx.o, ctx.h, ctx.l, ctx.c, ctx.v
    htf = ctx.htf()
    up_, mid, low_ = ind.bollinger(c, 20, 2.0)
    k, d = ind.stochastic(h, lo, c, 14, 3, 3)
    sweeps = ctx.memo("elite_sweep", lambda: _elite_sweeps(ctx))
    out = []
    for i in range(ctx.n):
        if i < 50 or up_[i] is None:
            out.append(None)
            continue
        price = c[i]
        atr = ctx.atr[i]
        tag_rj = [False, False]
        tag_t = [False, False]
        for kk in range(max(0, i - 2), i + 1):
            lo_b, up_b = low_[kk], up_[kk]
            if lo_b is not None and lo[kk] <= lo_b and c[kk] > lo_b:
                tag_rj[0] = True
            if up_b is not None and h[kk] >= up_b and c[kk] < up_b:
                tag_rj[1] = True
            if kk > 0:
                plo, pup = low_[kk - 1], up_[kk - 1]
                if plo is not None and lo[kk - 1] <= plo and lo_b is not None and c[kk] > lo_b:
                    tag_rj[0] = True
                if pup is not None and h[kk - 1] >= pup and up_b is not None and c[kk] < up_b:
                    tag_rj[1] = True
            if lo_b is not None and lo[kk] <= lo_b:
                tag_t[0] = True
            if up_b is not None and h[kk] >= up_b:
                tag_t[1] = True
        xu = xd = osh = obh = False
        for kk in range(max(1, i - 2), i + 1):
            pk, pd_, ck, cd = k[kk - 1], d[kk - 1], k[kk], d[kk]
            if None in (pk, pd_, ck, cd):
                continue
            if pk <= pd_ and ck > cd and min(pk, pd_) <= 20:
                xu = True
            if pk >= pd_ and ck < cd and max(pk, pd_) >= 80:
                xd = True
            if pk <= 20:
                osh = True
            if pk >= 80:
                obh = True
        tol = atr * 0.3
        dem, sup = _in_zones(ctx, i, atr, tol)
        bo, be = ind.order_blocks(o, h, lo, c, i + 1, 60)
        fz = ind.fvg_zones(h, lo, i + 1, 60)
        in_bob = bo is not None and bo["low"] - tol <= price <= bo["high"] + tol
        in_beob = be is not None and be["low"] - tol <= price <= be["high"] + tol
        in_bf = any(z[0] == "bull" and z[2] - tol <= price <= z[1] + tol for z in fz)
        in_bef = any(z[0] == "bear" and z[2] - tol <= price <= z[1] + tol for z in fz)
        rng = h[i] - lo[i]
        body = abs(c[i] - o[i])
        rev_b = rev_s = False
        if rng > 0:
            lw = min(o[i], c[i]) - lo[i]
            uw = h[i] - max(o[i], c[i])
            ham = lw >= rng * 0.7 and body <= rng * 0.4 and c[i] >= o[i]
            star = uw >= rng * 0.7 and body <= rng * 0.4 and c[i] <= o[i]
            eng_b = i >= 1 and c[i - 1] < o[i - 1] and c[i] > o[i] and c[i] >= o[i - 1] and o[i] <= c[i - 1]
            eng_s = i >= 1 and c[i - 1] > o[i - 1] and c[i] < o[i] and c[i] <= o[i - 1] and o[i] >= c[i - 1]
            rev_b, rev_s = ham or eng_b, star or eng_s
        hb = htf.ema_side(i, 200, 200)
        out.append({
            "rj_b": tag_rj[0], "rj_s": tag_rj[1], "tg_b": tag_t[0], "tg_s": tag_t[1],
            "xu": xu, "xd": xd, "os": osh, "ob": obh,
            "loc_b": dem or in_bob or in_bf, "loc_s": sup or in_beob or in_bef,
            "rev_b": rev_b, "rev_s": rev_s, "hb_b": hb[0], "hb_s": hb[1],
            "rsi_b": 30 <= ctx.rsi[i] <= 45, "rsi_s": 55 <= ctx.rsi[i] <= 70,
            "vol12": (v[i] / ctx.avgvol[i] if ctx.avgvol[i] > 0 else 1.0) >= 1.2,
            "sw_b": sweeps[i][0], "sw_s": sweeps[i][1],
            "low_band": low_[i], "up_band": up_[i],
        })
    return out


def _elite_sweeps(ctx: Ctx) -> list:
    """signalEval.ts 976-1000: a 3-bar swing low in the last 20 bars that a
    later bar wicked below and closed back above (bull), or the mirror."""
    h, lo, c = ctx.h, ctx.l, ctx.c
    out = [(False, False)] * ctx.n
    for i in range(ctx.n):
        start = max(2, i - 20)
        bull = bear = False
        for k in range(start, i - 1):
            if not bull and lo[k] < lo[k - 1] and lo[k] < lo[k + 1]:
                sw = lo[k]
                if any(lo[j] < sw and c[j] > sw for j in range(k + 1, i + 1)):
                    bull = True
            if not bear and h[k] > h[k - 1] and h[k] > h[k + 1]:
                sw = h[k]
                if any(h[j] > sw and c[j] < sw for j in range(k + 1, i + 1)):
                    bear = True
            if bull and bear:
                break
        out[i] = (bull, bear)
    return out


def _in_zones(ctx: Ctx, i: int, atr: float, tol: float):
    """(in demand, in supply): detectSupplyDemandZones over the last 80 bars
    with this bar's ATR, a zone counting only with 2 retests or fewer."""
    o, h, lo, c = ctx.o, ctx.h, ctx.l, ctx.c
    n = i + 1
    if n < 10 or not (atr > 0) or not math.isfinite(atr):
        return False, False
    price = c[i]
    start = max(2, n - 80)
    dem = sup = False
    for k in range(start, n - 2):
        base_len = min(3, k - start)
        for bl in range(1, base_len + 1):
            bs = k - bl + 1
            bh, blo = max(h[bs:k + 1]), min(lo[bs:k + 1])
            if bh - blo > atr * 1.4:
                continue
            leg = k + 1
            body = abs(c[leg] - o[leg])
            if body < atr * 2.0:
                continue
            bull_leg = c[leg] > o[leg] and c[leg] > bh
            bear_leg = c[leg] < o[leg] and c[leg] < blo
            if bull_leg:
                if not dem and bh + tol >= price >= blo - tol:
                    rt = 0
                    for j in range(leg + 1, n):
                        if bh + atr * 0.2 >= lo[j] >= blo - atr * 0.2:
                            rt += 1
                        if c[j] < blo - atr * 0.5:
                            rt = 99
                            break
                    if rt <= 2:
                        dem = True
                break
            if bear_leg:
                if not sup and blo - tol <= price <= bh + tol:
                    rt = 0
                    for j in range(leg + 1, n):
                        if blo - atr * 0.2 <= h[j] <= bh + atr * 0.2:
                            rt += 1
                        if c[j] > bh + atr * 0.5:
                            rt = 99
                            break
                    if rt <= 2:
                        sup = True
                break
        if dem and sup:
            break
    return dem, sup


def decide_bb(ctx: Ctx, raw: list, sw: dict) -> list:
    """BB Stoch S/D (signalEval.ts 1540-1734, 1835-1918), preset confluence
    mode: min quality 5 and at least 4 agreeing signals. Switches: zone,
    reject (close back inside the band, else a touch is enough), stochx
    (a cross, else just oversold/overbought), revcandle, maxadx, htf200."""
    dirs = [0] * ctx.n
    for i, r in enumerate(raw):
        if r is None:
            continue
        buy, sell = [], []
        if not (sw["maxadx"] and ctx.adx[i] > 22):
            for up in (True, False):
                s = "_b" if up else "_s"
                tag = r[("rj" if sw["reject"] else "tg") + s]
                stoch_ok = (r["xu"] if up else r["xd"]) if sw["stochx"] else (r["os"] if up else r["ob"])
                ok = ((not sw["zone"] or r["loc" + s]) and tag and stoch_ok
                      and (not sw["revcandle"] or r["rev" + s])
                      and (not sw["htf200"] or r["hb" + s]) and r["rsi" + s])
                if not ok:
                    continue
                qs = [q for good, q in (
                    (r["loc" + s], 6), (tag, 5), (stoch_ok, 5), (r["rev" + s], 4),
                    (r["hb" + s], 4), (r["vol12"], 3), (ctx.adx[i] < 25, 3),
                    (r["sw" + s], 5)) if good]
                (buy if up else sell).extend(qs)
        buy, sell = _with_pattern(ctx, i, buy, sell)
        qb, qs_ = _conf_ok(buy, 5, 4), _conf_ok(sell, 5, 4)
        if qb is not None and not _bb_sl_ok(ctx, r, i, True):
            qb = None
        if qs_ is not None and not _bb_sl_ok(ctx, r, i, False):
            qs_ = None
        dirs[i] = _best(qb, qs_)
    return dedup_4h(ctx, dirs)


def _bb_sl_ok(ctx, r, i, up) -> bool:
    """The app drops a BB Stoch S/D signal whose stop (beyond the band, less
    0.7 ATR, or beyond a matched zone when that is further) would sit on the
    wrong side of the entry. Read against the band alone: a zone only moves the
    stop further away, so this can only keep a signal the app would keep."""
    price = ctx.c[i]
    a = ctx.atr[i]
    if up:
        return r["low_band"] - a * 0.7 < price
    return r["up_band"] + a * 0.7 > price
