"""THE CONFLUENCE RESEARCH'S BUILDING BLOCKS (Oct 21, 2026), prefix `cq_`.

The operator: "I want you to reasearch confluence for each coins and each time
frame, my goal is 2:1R", their approved Prompt 1 (research/cq/prompts.md) and
"use supwerpower to decide the recommended". Design:
docs/superpowers/specs/2026-10-21-confluence-research-design.md.

A name is one COMBINATION: a trigger (when to enter) and one or two
confirmations (only if ...), every part from a different family, written
cq_<trigger code>[-<confirmation code>[-<confirmation code>]]. A code is the
block's two letters and one digit per setting (digit 0 = the standard value),
the confirmations sorted, so one combination has exactly one name
(cq_fl00-ev-vs1: a flag, only while EMA 9 is above EMA 21 and price is on the
trade's side of New York's VWAP). The grid appends `_gh_<tf>`; a name is read
by its own grammar, never split on "_".

Whole entries take no confirmation: `ex` wraps one of the 55 existing
confluence setups (cf_*, cx_*; EXISTING is frozen here so an index never
moves) and `rn` is the luck bar, seeded random entries on 1% or 3% of candles.

ONE implementation for the runner (auto_trader.signal_for reads the last
candle) and the backtest (_dirs_for_backtest, every candle). Every indicator
is fixed-window (pro_indicators) and every block reads at most ~250 candles,
so the runner's 299 closed candles decide what the year-deep window decides.
A session the frame does not hold from its first candle is unknown: nothing
is read from part of one.

TWO ENTRY RULES on every name, at their standard values, inside the signal so
the runner skips the same candles (the person-like rules of the prompt): no
entry from 30 minutes before to 30 minutes after a US CPI release, FOMC
decision or jobs report (research/cq/us_news.json; an unreadable calendar, or
a candle outside the stretch it covers, allows no entry at all: unknown is not
ok), and no weekend (UTC) entry on a candle whose volume is under the average
of the 20 before it.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import itertools
import json
import logging
import re
import threading
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from tradingagents import pro_indicators as pi, signals_pro as sp

PREFIX = "cq_"
VERSION = "cq1"                    # the search version, hashed into every seed
LOG = logging.getLogger(__name__)
DAY_MS = 86_400_000
HOUR_MS = 3_600_000
INTRADAY_TFS = ("15m", "30m", "1h")
INTRADAY_MAX_MS = HOUR_MS          # a frame of 1h candles or finer reads sessions
ROLLING_VWAP = 20                  # 4h and 1d read the last 20 candles' VWAP
NY = ZoneInfo("America/New_York")
LONDON = ZoneInfo("Europe/London")
SESSION_HOURS = {"london": (LONDON, (8, 0), (16, 30)), "ny": (NY, (9, 30), (16, 0))}
SESSION_WORDS = {"utc": "UTC day", "london": "London", "ny": "New York"}
NY_ONLY_KINDS = ("stocks", "indices")      # their own market: New York's session only
NEWS_PATH = Path(__file__).resolve().parent.parent / "research" / "cq" / "us_news.json"
NEWS_WINDOW_MS = 30 * 60_000
QUIET_RATIO = 1.0                  # a weekend candle under its 20-candle average volume
RANDOM_SEEDS = 560                 # x 2 rates = 1,120 random entries, about the real space

# the 55 existing confluence setups (signals_conf.CONF_SIGNALS on Oct 21,
# 2026), frozen: `ex07` must name the same rule for ever
EXISTING = (
    "cf_bosfvg", "cf_bosfvg_l1", "cf_bosfvg_l2", "cf_chan", "cf_chan_l1", "cf_chan_l2",
    "cf_diadx", "cf_diadx_l1", "cf_diadx_l2", "cf_donch", "cf_donch_l1", "cf_donch_l2",
    "cf_emarsi", "cf_emarsi_l1", "cf_emarsi_l2", "cf_eqhl", "cf_eqhl_l1", "cf_eqhl_l2",
    "cf_fundfade", "cf_fundfade_l1", "cf_fundfade_l2", "cf_maobv", "cf_maobv_l1",
    "cf_maobv_l2", "cf_mom", "cf_mom_l1", "cf_mom_l2", "cf_obretest", "cf_obretest_l1",
    "cf_obretest_l2", "cf_soup", "cf_soup1", "cf_soup1_l1", "cf_soup1_l2", "cf_soup_l1",
    "cf_soup_l2", "cf_stflip", "cf_stflip_l1", "cf_stflip_l2", "cf_triple", "cf_triple_l1",
    "cf_triple_l2", "cf_ttm", "cf_ttm_l1", "cf_ttm_l2", "cx_4h", "cx_any2", "cx_both",
    "cx_esc", "cx_fast", "cx_first", "cx_firstr", "cx_lvl", "cx_maj3", "cx_veto")

TRIGGER, CONFIRM, WHOLE = "trigger", "confirm", "whole"


# ------------------------------------------------------------------ the frame

_IDENT_LOCK = threading.Lock()
_IDENT: list = []


def _ctx(o, h, lo, c, v, ts):
    """The frame's shared indicators (signals_pro's Ctx and its cache). The
    grid hands every rule of one pair the SAME list objects, so the frame is
    recognised by identity first (hashing 200,000 values for each rule is the
    slow part); anything else is found by its fingerprint, as pt_ does. The
    lists are held, so an id cannot be reused while it is remembered."""
    refs = (o, h, lo, c, v, ts)
    with _IDENT_LOCK:
        if _IDENT and all(a is b for a, b in zip(_IDENT[0][0], refs, strict=True)):
            return _IDENT[0][1]
    ctx = sp._ctx(o, h, lo, c, v, ts)
    with _IDENT_LOCK:
        _IDENT[:] = [(refs, ctx)]
    return ctx


def _m(ctx, key: tuple, make):
    return ctx.memo(("cq",) + key, make)


def _bar_ms(ctx) -> int:
    def make():
        if ctx.n < 2:
            return 0
        return int(np.median(np.diff(np.asarray(ctx.ts, dtype=np.int64))))
    return _m(ctx, ("bar",), make)


def _closes(ctx) -> np.ndarray:
    """Each candle's close in epoch ms, when its entry is bought: its open plus
    the frame's candle length (the median gap, so one missing candle never
    moves another candle's close)."""
    return _m(ctx, ("closes",), lambda: np.asarray(ctx.ts, dtype=np.int64) + _bar_ms(ctx))


def _intraday(ctx) -> bool:
    return 0 < _bar_ms(ctx) <= INTRADAY_MAX_MS


def _ema(ctx, n: int) -> np.ndarray:
    return _m(ctx, ("ema", n), lambda: pi.ema_fixed(ctx.c, n))


def _sma(ctx, n: int) -> np.ndarray:
    return _m(ctx, ("sma", n), lambda: pi.sma(ctx.c, n))


def _std(ctx, n: int) -> np.ndarray:
    return _m(ctx, ("std", n), lambda: pi.rolling_std(ctx.c, n))


def _atr(ctx, n: int) -> np.ndarray:
    return _m(ctx, ("atr", n), lambda: pi.atr(ctx.h, ctx.l, ctx.c, n))


def _rsi(ctx) -> np.ndarray:
    return _m(ctx, ("rsi", 14), lambda: pi.rsi(ctx.c, 14))


def _volr(ctx) -> np.ndarray:
    return _m(ctx, ("volr", 20), lambda: pi.vol_ratio(ctx.v, 20))


def _eff(ctx) -> np.ndarray:
    return _m(ctx, ("eff", 20), lambda: pi.efficiency(ctx.c, 20))


# ------------------------------------------------------------------- sessions

def _session(ctx, which: str):
    """(session id per candle, -1 outside it; the session's start, epoch ms;
    is that session whole in this frame): "utc" = the UTC day, "london" =
    8:00am-4:30pm London, "ny" = 9:30am-4pm New York, each on its own city's
    clock (daylight saving is never a fixed offset). A candle belongs to the
    session its OPEN falls in. A session that began before the frame's first
    candle is not whole, and nothing is read from it."""
    def make():
        t = np.asarray(ctx.ts, dtype=np.int64)
        n = len(t)
        if which == "utc":
            sid = t // DAY_MS
            start = sid * DAY_MS
        else:
            tz, (h0, m0), (h1, m1) = SESSION_HOURS[which]
            sid = np.full(n, -1, dtype=np.int64)
            start = np.zeros(n, dtype=np.int64)
            starts: dict = {}
            for i in range(n):
                d = _dt.datetime.fromtimestamp(int(t[i]) / 1000.0, tz)
                mins = d.hour * 60 + d.minute
                if h0 * 60 + m0 <= mins < h1 * 60 + m1:
                    day = d.date().toordinal()
                    if day not in starts:
                        starts[day] = int(_dt.datetime(d.year, d.month, d.day, h0, m0,
                                                       tzinfo=tz).timestamp() * 1000)
                    sid[i] = day
                    start[i] = starts[day]
        whole = (sid >= 0) & (start >= (int(t[0]) if n else 0))
        return sid, start, whole
    return _m(ctx, ("session", which), make)


def _sgroups(ctx, which: str) -> list:
    """[(first index, end index)] of each run of one session's candles."""
    def make():
        sid = _session(ctx, which)[0]
        n = len(sid)
        if not n:
            return []
        edges = np.r_[0, np.flatnonzero(np.diff(sid) != 0) + 1, n]
        return [(int(a), int(b)) for a, b in zip(edges[:-1], edges[1:], strict=True)
                if sid[a] >= 0]
    return _m(ctx, ("groups", which), make)


def _session_vwap(ctx, which: str) -> np.ndarray:
    """The session's volume-weighted average price through each candle
    (typical price x volume, summed fresh from the session's first candle);
    NaN outside the session, in one that is not whole, or before any volume."""
    def make():
        whole = _session(ctx, which)[2]
        tp = (ctx.h + ctx.l + ctx.c) / 3.0
        out = np.full(ctx.n, np.nan)
        for a, b in _sgroups(ctx, which):
            if not whole[a]:
                continue
            num = np.cumsum(tp[a:b] * ctx.v[a:b])
            den = np.cumsum(ctx.v[a:b])
            with np.errstate(invalid="ignore", divide="ignore"):
                out[a:b] = np.where(den > 0, num / den, np.nan)
        return out
    return _m(ctx, ("svwap", which), make)


def _vwap(ctx, which: str) -> np.ndarray:
    """The VWAP a block reads: the session's on 15m-1h, the last 20 candles'
    on 4h and 1d (a session is one to six candles there)."""
    if _intraday(ctx):
        return _session_vwap(ctx, which)
    return _m(ctx, ("rvwap",), lambda: pi.rolling_vwap(ctx.h, ctx.l, ctx.c, ctx.v, ROLLING_VWAP))


def _session_range(ctx, which: str):
    """(the session's highest high and lowest low BEFORE each candle; the
    session's first open): NaN on the session's first candle (no range yet),
    outside it, and in a session that is not whole."""
    def make():
        whole = _session(ctx, which)[2]
        hi = np.full(ctx.n, np.nan)
        lo = np.full(ctx.n, np.nan)
        op = np.full(ctx.n, np.nan)
        for a, b in _sgroups(ctx, which):
            if not whole[a]:
                continue
            if b - a > 1:
                hi[a + 1:b] = np.maximum.accumulate(ctx.h[a:b - 1])
                lo[a + 1:b] = np.minimum.accumulate(ctx.l[a:b - 1])
            op[a:b] = ctx.o[a]
        return hi, lo, op
    return _m(ctx, ("srange", which), make)


def _prev_day(ctx):
    """Yesterday's (UTC) high, low and close for each candle; NaN when the
    frame does not hold yesterday from its first candle, or skipped a day."""
    def make():
        sid, _start, whole = _session(ctx, "utc")
        hi = np.full(ctx.n, np.nan)
        lo = np.full(ctx.n, np.nan)
        cl = np.full(ctx.n, np.nan)
        prev = None
        for a, b in _sgroups(ctx, "utc"):
            if prev is not None and prev[2] and prev[3] == int(sid[a]) - 1:
                pa, pb = prev[0], prev[1]
                hi[a:b] = ctx.h[pa:pb].max()
                lo[a:b] = ctx.l[pa:pb].min()
                cl[a:b] = ctx.c[pb - 1]
            prev = (a, b, bool(whole[a]), int(sid[a]))
        return hi, lo, cl
    return _m(ctx, ("prevday",), make)


def _round_dist(ctx) -> np.ndarray:
    """How far each close is from the nearest round number: a multiple of
    10^(floor(log10 price) - 1) (BTC at 108,000 -> every 10,000; a 0.2534
    coin -> every 0.01)."""
    def make():
        c = ctx.c
        with np.errstate(invalid="ignore", divide="ignore"):
            step = 10.0 ** (np.floor(np.log10(np.where(c > 0, c, np.nan))) - 1.0)
            return np.abs(c - np.round(c / step) * step)
    return _m(ctx, ("round",), make)


# ------------------------------------------------------------------- triggers
#
# A trigger answers +1 / -1 / 0 for every candle; a confirmation answers
# (long allowed, short allowed). NaN anywhere means "not known": no entry.

def _t_fl(ctx, s) -> np.ndarray:
    """A bull (bear) flag: a pole of at least `pole` x ATR(14) inside 8 candles
    ending at candle p, then a flag of 3..`flag` candles that gives back at
    most half the pole and never passes its top (bottom), bought on the first
    close above (below) the flag."""
    k, longest = float(s["pole"]), int(s["flag"])
    c, h, lo = ctx.c, ctx.h, ctx.l
    a = _atr(ctx, 14)
    lo8, hi8 = pi.rolling_min(lo, 8), pi.rolling_max(h, 8)
    up, dn = c - lo8, hi8 - c
    with np.errstate(invalid="ignore"):
        bull = (up >= k * a).astype(float)
        bear = (dn >= k * a).astype(float)
    long = np.zeros(ctx.n, dtype=bool)
    short = np.zeros(ctx.n, dtype=bool)
    for f in range(3, longest + 1):
        g = f + 1                                  # the pole ends g candles back
        fh = pi.shift(pi.rolling_max(h, f), 1)     # the flag: the f candles before
        fl_ = pi.shift(pi.rolling_min(lo, f), 1)
        pc = pi.shift(c, g)
        with np.errstate(invalid="ignore"):
            long |= ((pi.shift(bull, g) == 1.0) & (fl_ >= pc - 0.5 * pi.shift(up, g))
                     & (fh <= pi.shift(hi8, g)) & (c > fh))
            short |= ((pi.shift(bear, g) == 1.0) & (fh <= pc + 0.5 * pi.shift(dn, g))
                      & (fl_ >= pi.shift(lo8, g)) & (c < fl_))
    return sp._edge(long, short)


def _t_sb(ctx, s) -> np.ndarray:
    """A session break: after the session's first hour, a close above the
    highest high (below the lowest low) the session made before that candle;
    `first` = only the first break each way per session."""
    which = s["session"]
    sid, start, whole = _session(ctx, which)
    hi, lo, _op = _session_range(ctx, which)
    t = np.asarray(ctx.ts, dtype=np.int64)
    late = (sid >= 0) & whole & (t >= start + HOUR_MS)
    with np.errstate(invalid="ignore"):
        up = late & (ctx.c > hi)
        down = late & (ctx.c < lo)
    if not s["first"]:
        return sp._edge(up, down)
    out = np.zeros(ctx.n, dtype=np.int8)
    for a, b in _sgroups(ctx, which):
        iu = np.flatnonzero(up[a:b])
        idn = np.flatnonzero(down[a:b])
        if len(iu):
            out[a + iu[0]] = 1
        if len(idn) and out[a + idn[0]] == 0:
            out[a + idn[0]] = -1
    return out


def _t_ec(ctx, s) -> np.ndarray:
    """The fast EMA crossing the slow one (both fixed-window), on the candle
    it happens."""
    fast, slow = s["pair"]
    f, sl = _ema(ctx, fast), _ema(ctx, slow)
    with np.errstate(invalid="ignore"):
        above, below = f > sl, f < sl
    ok = ~np.isnan(f) & ~np.isnan(sl)
    prev_ok = np.r_[False, ok[:-1]]
    prev_above = np.r_[False, above[:-1]]
    prev_below = np.r_[False, below[:-1]]
    out = np.zeros(ctx.n, dtype=np.int8)
    out[above & prev_ok & ~prev_above] = 1
    out[below & prev_ok & ~prev_below] = -1
    return out


def _t_pb(ctx, s) -> np.ndarray:
    """A pullback in the trend: price above its 50-candle average dips to the
    level (the VWAP, or EMA 21) - touching it, or 0.25 x ATR past it - and
    closes back above it (mirrored for shorts)."""
    lvl = _vwap(ctx, "utc") if s["level"] == "vwap" else _ema(ctx, 21)
    a, m, d = _atr(ctx, 14), _sma(ctx, 50), float(s["depth"])
    with np.errstate(invalid="ignore"):
        long = (ctx.c > m) & (ctx.l <= lvl - d * a) & (ctx.c > lvl)
        short = (ctx.c < m) & (ctx.h >= lvl + d * a) & (ctx.c < lvl)
    return sp._edge(long, short)


def _t_sq(ctx, s) -> np.ndarray:
    """A squeeze release: Bollinger(20, 2) inside Keltner(20, 1.5 x ATR 20) on
    each of the `n` candles before, then a close outside the Bollinger bands,
    taken that way."""
    n = int(s["n"])
    m, sd, a = _sma(ctx, 20), _std(ctx, 20), _atr(ctx, 20)
    bu, bl = m + 2.0 * sd, m - 2.0 * sd
    ku, kl = m + 1.5 * a, m - 1.5 * a
    with np.errstate(invalid="ignore"):
        tight = ((bu < ku) & (bl > kl)).astype(float)
    tight[np.isnan(bu) | np.isnan(ku)] = np.nan
    run = pi.shift(pi.rolling_sum(tight, n), 1)
    with np.errstate(invalid="ignore"):
        ready = run == n
        long = ready & (ctx.c > bu)
        short = ready & (ctx.c < bl)
    return sp._edge(long, short)


# -------------------------------------------------------------- confirmations

def _c_ev(ctx, s):
    f, sl = _ema(ctx, 9), _ema(ctx, 21)
    with np.errstate(invalid="ignore"):
        return f > sl, f < sl


def _c_vs(ctx, s):
    w = _vwap(ctx, s["session"])
    with np.errstate(invalid="ignore"):
        return ctx.c > w, ctx.c < w


def _c_ht(ctx, s):
    m = _sma(ctx, int(s["n"]))
    with np.errstate(invalid="ignore"):
        return ctx.c > m, ctx.c < m


def _c_vo(ctx, s):
    with np.errstate(invalid="ignore"):
        ok = _volr(ctx) >= float(s["m"])
    return ok, ok


def _c_rs(ctx, s):
    r, x = _rsi(ctx), float(s["x"])
    with np.errstate(invalid="ignore"):
        return r > x, r < 100.0 - x


def _c_kp(ctx, s):
    d = float(s["d"]) * _atr(ctx, 14)
    hi, lo, cl = _prev_day(ctx)
    op = _session_range(ctx, "utc")[2]
    near = np.zeros(ctx.n, dtype=bool)
    with np.errstate(invalid="ignore"):
        for lvl in (hi, lo, cl, op, _vwap(ctx, "utc")):
            near |= np.abs(ctx.c - lvl) <= d
        near |= _round_dist(ctx) <= d
    return near, near


def _c_tr(ctx, s):
    with np.errstate(invalid="ignore"):
        ok = _eff(ctx) >= float(s["e"])
    return ok, ok


# -------------------------------------------------------------- whole entries

def _w_ex(ctx, rule: str, o, h, lo, c, v, ts, funding) -> np.ndarray:
    """An existing confluence setup, exactly as the grid and the runner read it
    (signals_conf.CONF_SIGNALS); a name that registry no longer holds abstains."""
    def make():
        from tradingagents.signals_conf import CONF_SIGNALS

        fn = CONF_SIGNALS.get(rule)
        if fn is None:
            return np.zeros(ctx.n, dtype=np.int8)
        vol = v if v is not None else []
        d = (fn(o, h, lo, c, vol, ts, funding or [])
             if getattr(fn, "needs_funding", False) else fn(o, h, lo, c, vol, ts))
        return np.asarray(d, dtype=np.int8)
    return _m(ctx, ("ex", rule), make)


def _w_rn(ctx, seed: int, rate: float) -> np.ndarray:
    """Seeded random entries: each candle is an entry with probability `rate`,
    long or short at random, from a hash of the seed, the candle's own time and
    its close - the same coin flip for the same candle in any frame, never
    shared with another coin, never with pt_'s streams ("cq:" in the hash)."""
    def make():
        out = np.zeros(ctx.n, dtype=np.int8)
        for i, t in enumerate(ctx.ts):
            hsh = hashlib.blake2b(f"cq:{seed}:{int(t)}:{float(ctx.c[i])!r}".encode(),
                                  digest_size=8).digest()
            if int.from_bytes(hsh[:4], "big") / 2 ** 32 < rate:
                out[i] = 1 if hsh[4] & 1 else -1
        return out
    return _m(ctx, ("rn", int(seed), float(rate)), make)


# --------------------------------------------------------------------- blocks

BLOCKS = {
    "fl": {"role": TRIGGER, "family": "structure", "title": "bull/bear flag",
           "knobs": (("pole", (3.0, 2.0)), ("flag", (10, 6))), "fn": _t_fl,
           "say": lambda s: (f"a flag: a pole of {s['pole']:g}x the average range inside 8 "
                             f"candles, then a pause of 3 to {s['flag']} candles giving back at "
                             f"most half, bought on the break")},
    "sb": {"role": TRIGGER, "family": "time", "title": "session break",
           "knobs": (("session", ("utc", "london", "ny")), ("first", (True, False))),
           "fn": _t_sb,
           "say": lambda s: (f"{'the first' if s['first'] else 'each new'} close past the "
                             f"{SESSION_WORDS[s['session']]} session's high or low after its "
                             f"first hour")},
    "ec": {"role": TRIGGER, "family": "trend", "title": "EMA cross",
           "knobs": (("pair", ((9, 21), (20, 50))),), "fn": _t_ec,
           "say": lambda s: f"EMA {s['pair'][0]} crossing EMA {s['pair'][1]}"},
    "pb": {"role": TRIGGER, "family": "structure", "title": "pullback to a level",
           "knobs": (("level", ("vwap", "ema21")), ("depth", (0.0, 0.25))), "fn": _t_pb,
           "say": lambda s: (f"a dip to the {'VWAP' if s['level'] == 'vwap' else 'EMA 21'}"
                             f"{' and 0.25x the average range past it' if s['depth'] else ''} "
                             f"that closes back on the trend side (price vs its 50-candle "
                             f"average)")},
    "sq": {"role": TRIGGER, "family": "volatility", "title": "squeeze release",
           "knobs": (("n", (3, 6)),), "fn": _t_sq,
           "say": lambda s: (f"a squeeze release: Bollinger bands inside Keltner channels for "
                             f"{s['n']}+ candles, then a close outside the bands")},
    "ev": {"role": CONFIRM, "family": "trend", "title": "EMA 9 vs 21", "knobs": (),
           "fn": _c_ev, "say": lambda s: "only while EMA 9 is on the trade's side of EMA 21"},
    "vs": {"role": CONFIRM, "family": "volume", "title": "VWAP side",
           "knobs": (("session", ("utc", "ny")),), "fn": _c_vs,
           "say": lambda s: (f"only on the trade's side of the {SESSION_WORDS[s['session']]} "
                             f"VWAP (the last 20 candles' on 4h and 1d)")},
    "ht": {"role": CONFIRM, "family": "trend", "title": "bigger picture",
           "knobs": (("n", (240, 120)),), "fn": _c_ht,
           "say": lambda s: f"only on the trade's side of the {s['n']}-candle average"},
    "vo": {"role": CONFIRM, "family": "volume", "title": "volume burst",
           "knobs": (("m", (1.5, 2.0)),), "fn": _c_vo,
           "say": lambda s: f"only on a candle with {s['m']:g}x the volume of the 20 before"},
    "rs": {"role": CONFIRM, "family": "momentum", "title": "RSI side",
           "knobs": (("x", (50, 55)),), "fn": _c_rs,
           "say": lambda s: f"only with RSI(14) past {s['x']} the trade's way"},
    "kp": {"role": CONFIRM, "family": "structure", "title": "near a key price",
           "knobs": (("d", (0.5, 1.0)),), "fn": _c_kp,
           "say": lambda s: (f"only within {s['d']:g}x the average range of a key price "
                             f"(yesterday's high, low or close, the day's open, its VWAP, a "
                             f"round number)")},
    "tr": {"role": CONFIRM, "family": "volatility", "title": "trending",
           "knobs": (("e", (0.3, 0.4)),), "fn": _c_tr,
           "say": lambda s: (f"only when the last 20 candles went {s['e']:g}+ straight "
                             f"(Kaufman efficiency)")},
    "ex": {"role": WHOLE, "family": "existing", "title": "an existing confluence setup",
           "knobs": (("rule", EXISTING),), "widths": (2,),
           "say": lambda s: f"the existing setup {s['rule']}"},
    "rn": {"role": WHOLE, "family": "random", "title": "random entries (the luck bar)",
           "knobs": (("seed", range(10_000)), ("rate", (0.01, 0.03))), "widths": (4, 1),
           "say": lambda s: f"a coin flip on {s['rate'] * 100:g}% of candles (seed {s['seed']})"},
}
TRIGGER_ORDER = ("fl", "sb", "ec", "pb", "sq")
CONFIRM_ORDER = ("ev", "vs", "ht", "vo", "rs", "kp", "tr")


# ---------------------------------------------------------------------- names

def _widths(block: str) -> tuple:
    b = BLOCKS[block]
    return b.get("widths") or (1,) * len(b["knobs"])


def _settings(block: str, digits) -> dict:
    return {name: values[d] for (name, values), d in zip(BLOCKS[block]["knobs"], digits,
                                                          strict=True)}


def _digits(block: str) -> list:
    return list(itertools.product(*[range(len(v)) for _n, v in BLOCKS[block]["knobs"]]))


def code_of(block: str, digits=()) -> str:
    """("fl", (0, 1)) -> "fl01"; ("rn", (7, 0)) -> "rn00070"."""
    return block + "".join(f"{int(d):0{w}d}" for d, w in zip(digits, _widths(block),
                                                              strict=True))


def name_of(trigger, confirms=()) -> str:
    """("fl", (0, 0)), [("vs", (1,)), ("ev", ())] -> "cq_fl00-ev-vs1": the
    confirmations sorted by code, so one combination has one name."""
    codes = sorted(code_of(b, d) for b, d in confirms)
    return PREFIX + "-".join([code_of(*trigger), *codes])


def _part(code: str):
    block, digs = code[:2], code[2:]
    if block not in BLOCKS:
        return None
    widths = _widths(block)
    if len(digs) != sum(widths) or (digs and not digs.isdigit()):
        return None
    out, at_ = [], 0
    for (_name, values), w in zip(BLOCKS[block]["knobs"], widths, strict=True):
        d = int(digs[at_:at_ + w])
        at_ += w
        if d >= len(values):
            return None
        out.append(d)
    return block, tuple(out)


# a name is read by its own grammar - prefix, the codes joined by "-", then
# nothing or the grid's `_gh_<tf>` - never split on "_" (RCA-2026-09-24-G)
_NAME = re.compile(r"cq_([a-z]{2}\d*)((?:-[a-z]{2}\d*){0,2})(?=_|$)")


def spec_for(key: str) -> dict | None:
    """The parts a name holds, or None: a trigger with one or two
    confirmations of other families (or a whole entry alone), every code
    known, every digit in range, and the confirmations in their sorted order
    - any other spelling is not a name. Anything after the codes (the grid's
    `_gh_<tf>`) is ignored."""
    m = _NAME.match(str(key))
    if m is None:
        return None
    trig = _part(m.group(1))
    confs = [_part(x) for x in m.group(2).split("-")[1:]]
    if trig is None or any(x is None for x in confs):
        return None
    role = BLOCKS[trig[0]]["role"]
    if role == CONFIRM or (role == WHOLE and confs) or (role == TRIGGER and not confs):
        return None
    if any(BLOCKS[b]["role"] != CONFIRM for b, _d in confs):
        return None
    fams = [BLOCKS[b]["family"] for b, _d in [trig, *confs]]
    if len(set(fams)) != len(fams):
        return None
    name = name_of(trig, confs)
    if name != m.group(0):
        return None
    return {"name": name, "trigger": trig, "confirms": tuple(confs),
            "settings": {b: _settings(b, d) for b, d in [trig, *confs]}}


def words(name: str) -> str:
    """The combination in plain words (the results page); "" for a name that
    is not ours."""
    spec = spec_for(name)
    if spec is None:
        return ""
    tb, td = spec["trigger"]
    out = BLOCKS[tb]["say"](_settings(tb, td))
    if spec["confirms"]:
        out += ", " + " and ".join(BLOCKS[b]["say"](_settings(b, d)) for b, d in spec["confirms"])
    return out


def families(name: str) -> list:
    """The families a name's parts come from, trigger first."""
    spec = spec_for(name)
    if spec is None:
        return []
    return [BLOCKS[b]["family"] for b, _d in [spec["trigger"], *spec["confirms"]]]


# ---------------------------------------------------------------- entry rules

_NEWS: dict = {}
_NEWS_LOCK = threading.Lock()


def news_times():
    """(every US CPI, FOMC and jobs-report release in research/cq/us_news.json
    as sorted epoch ms; the (first, end) epoch ms the calendar covers), or
    (None, None) when the file is missing or unreadable."""
    with _NEWS_LOCK:
        if "t" not in _NEWS:
            try:
                d = json.loads(NEWS_PATH.read_text(encoding="utf-8"))
                tz = ZoneInfo(d.get("timezone") or "America/New_York")

                def ms(day: str, hhmm: str = "00:00") -> int:
                    return int(_dt.datetime.fromisoformat(f"{day}T{hhmm}").replace(tzinfo=tz)
                               .timestamp() * 1000)

                t = np.array(sorted(ms(e["date"], e["time"]) for e in d["events"]),
                             dtype=np.int64)
                _NEWS.update(t=t, span=(ms(d["from"]), ms(d["through"]) + DAY_MS))
            except Exception as exc:                                  # noqa: BLE001
                LOG.warning("the US news calendar %s could not be read (%s): no confluence "
                            "entry is allowed until it can", NEWS_PATH, exc)
                _NEWS.update(t=None, span=None)
        return _NEWS["t"], _NEWS["span"]


def _allowed(ctx) -> np.ndarray:
    """The candles an entry may be bought on: not from 30 minutes before to 30
    minutes after a US release, never outside the stretch the calendar covers
    (and none at all without it), and not a quiet weekend candle (closing on a
    UTC Saturday or Sunday with volume under the average of the 20 before;
    no average yet counts as quiet)."""
    def make():
        closes = _closes(ctx)
        t, span = news_times()
        if t is None:
            return np.zeros(ctx.n, dtype=bool)
        ok = (closes >= span[0]) & (closes < span[1])
        if len(t):
            j = np.searchsorted(t, closes)
            after = t[np.minimum(j, len(t) - 1)]
            before = t[np.maximum(j - 1, 0)]
            near = (((j < len(t)) & (after - closes <= NEWS_WINDOW_MS))
                    | ((j > 0) & (closes - before <= NEWS_WINDOW_MS)))
            ok &= ~near
        weekend = ((closes // DAY_MS) + 3) % 7 >= 5          # 1970-01-01 was a Thursday
        with np.errstate(invalid="ignore"):
            quiet = ~(_volr(ctx) >= QUIET_RATIO)
        return ok & ~(weekend & quiet)
    return _m(ctx, ("allowed",), make)


def entry_allowed(o, h, lo, c, v, ts) -> np.ndarray:
    """Which candles an entry may be bought on by the two entry rules."""
    if ts is None or len(ts) != len(c) or not len(c):
        return np.zeros(len(c), dtype=bool)
    return _allowed(_ctx(o, h, lo, c, v, ts)).copy()


def reset() -> None:
    """Forget the calendar and every cached frame (for a test that swaps the
    calendar)."""
    with _NEWS_LOCK:
        _NEWS.clear()
    with _IDENT_LOCK:
        _IDENT.clear()
    with sp._LOCK:
        sp._FRAMES.clear()


# ------------------------------------------------------------------ the signal

def _trigger(ctx, block: str, digits) -> np.ndarray:
    return _m(ctx, ("trig", block, tuple(digits)),
              lambda: BLOCKS[block]["fn"](ctx, _settings(block, digits)))


def _confirm(ctx, block: str, digits):
    return _m(ctx, ("conf", block, tuple(digits)),
              lambda: BLOCKS[block]["fn"](ctx, _settings(block, digits)))


def part_dirs(code: str, o, h, lo, c, v, ts):
    """One block's own answer on a frame (tests, the results page): a
    trigger's +1 / -1 / 0 per candle, a confirmation's (long ok, short ok)."""
    got = _part(code)
    if got is None or BLOCKS[got[0]]["role"] == WHOLE:
        raise ValueError(f"{code}: not a trigger or confirmation code")
    ctx = _ctx(o, h, lo, c, v, ts)
    if BLOCKS[got[0]]["role"] == TRIGGER:
        return _trigger(ctx, *got)
    return _confirm(ctx, *got)


def dirs_for(spec: dict, o, h, lo, c, v, ts, funding=None) -> list[int]:
    """+1 / -1 / 0 for every candle of the frame - the runner reads the last.
    A frame without its candles' times abstains (the entry rules need them)."""
    n = len(c)
    if spec is None or not n or ts is None or len(ts) != n:
        return [0] * n
    ctx = _ctx(o, h, lo, c, v, ts)
    blk, digits = spec["trigger"]
    if blk == "ex":
        raw = _w_ex(ctx, EXISTING[digits[0]], o, h, lo, c, v, ts, funding).copy()
    elif blk == "rn":
        s = _settings("rn", digits)
        raw = _w_rn(ctx, s["seed"], s["rate"]).copy()
    else:
        raw = _trigger(ctx, blk, digits).copy()
        for cb, cd in spec["confirms"]:
            ok_long, ok_short = _confirm(ctx, cb, cd)
            raw[(raw == 1) & ~ok_long] = 0
            raw[(raw == -1) & ~ok_short] = 0
    raw[~_allowed(ctx)] = 0
    return [int(x) for x in raw]


# ------------------------------------------------------------------ the space

def _usable(block: str, digits, intraday: bool, ny_only: bool) -> bool:
    s = _settings(block, digits)
    if block == "sb":
        return intraday and (not ny_only or s["session"] == "ny")
    if block == "vs":
        if not intraday:
            return tuple(digits) == (0,)           # one rolling VWAP on 4h and 1d
        return not ny_only or s["session"] == "ny"
    return True


def entries_for(tf: str, kind: str = "crypto") -> list[str]:
    """Every name the search may try on one timeframe for one asset kind
    (venue.kind): each trigger setting with one confirmation, and with two of
    different families, never a part of the trigger's own family; New York's
    session only for stock tokens and indices; no session break on 4h and 1d
    (and one VWAP there). Then the existing setups, as whole entries."""
    from tradingagents.signals_conf import CONF_SIGNALS

    intraday = tf in INTRADAY_TFS
    ny_only = kind in NY_ONLY_KINDS
    trig = [(b, d) for b in TRIGGER_ORDER for d in _digits(b) if _usable(b, d, intraday, ny_only)]
    conf = [(b, d) for b in CONFIRM_ORDER for d in _digits(b) if _usable(b, d, intraday, ny_only)]
    out = []
    for t in trig:
        fam = BLOCKS[t[0]]["family"]
        ok = [x for x in conf if BLOCKS[x[0]]["family"] != fam]
        out += [name_of(t, [x]) for x in ok]
        out += [name_of(t, [x, y]) for x, y in itertools.combinations(ok, 2)
                if BLOCKS[x[0]]["family"] != BLOCKS[y[0]]["family"]]
    out += [name_of(("ex", (k,))) for k, rule in enumerate(EXISTING) if rule in CONF_SIGNALS]
    return out


def random_entries(n_seeds: int = RANDOM_SEEDS) -> list[str]:
    """The luck search's space: `n_seeds` seeds x both rates."""
    return [name_of(("rn", (s, r))) for s in range(n_seeds) for r in (0, 1)]


def neighbours(name: str, pool) -> list[str]:
    """The names one step from `name` that are in `pool` (the coin and
    timeframe's own space, which also decides what is legal): one setting one
    step away, one confirmation swapped, one added, one dropped; an existing
    setup's other levels; a random stream's next seeds and its other rate."""
    spec = spec_for(name)
    if spec is None:
        return []
    out: list = []
    seen: set = {name}

    def add(other: str) -> None:
        if other not in seen and other in pool:
            seen.add(other)
            out.append(other)

    tb, td = spec["trigger"]
    if tb == "rn":
        seed, rate = td
        for s2 in (seed - 1, seed + 1):
            if 0 <= s2 < 10_000:
                add(name_of(("rn", (s2, rate))))
        add(name_of(("rn", (seed, 1 - rate))))
        return out
    if tb == "ex":
        base = re.sub(r"_l[12]$", "", EXISTING[td[0]])
        for k, other in enumerate(EXISTING):
            if re.sub(r"_l[12]$", "", other) == base:
                add(name_of(("ex", (k,))))
        return out
    confs = list(spec["confirms"])
    parts = [(tb, td), *confs]
    for j, (b, d) in enumerate(parts):
        for q in range(len(d)):
            for step in (-1, 1):
                v = d[q] + step
                if 0 <= v < len(BLOCKS[b]["knobs"][q][1]):
                    p2 = parts[:j] + [(b, d[:q] + (v,) + d[q + 1:])] + parts[j + 1:]
                    add(name_of(p2[0], p2[1:]))
    every = [(b, d) for b in CONFIRM_ORDER for d in _digits(b)]
    for j in range(len(confs)):
        for x in every:
            if x[0] != confs[j][0]:
                add(name_of((tb, td), confs[:j] + [x] + confs[j + 1:]))
    if len(confs) == 1:
        for x in every:
            add(name_of((tb, td), confs + [x]))
    if len(confs) == 2:
        for j in range(2):
            add(name_of((tb, td), [confs[1 - j]]))
    return out
