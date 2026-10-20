"""THE PRO TRADER FAMILIES (Oct 20, 2026), prefix `pt_`.

The operator: "think of your self as a professional trader, meaning you will
need to research on proven and working indicators out there", with the
approved prompt's rules: at most 12 families, each with a pre-registered
expectation and at most 3 knobs, digit 0 of every knob the literature's
default; one implementation for the runner (`auto_trader.signal_for`, last
bar) and the backtest (`_dirs_for_backtest`, every bar); no bar reads a later
one. The research behind each family: docs/research/2026-10-20-pro-trader-survey.md.

Every indicator is fixed-window (`pro_indicators`), and every family's whole
lookback stays within `pro_indicators.MAX_LOOKBACK` bars, so the runner's 299
closed candles and the backtest's deep window compute the same signal.

A name carries its settings: pt_<family>_<letter><digit>... — e.g.
pt_tsm_l0v1 is time-series momentum with lookback value 0 and volatility gate
value 1. Unknown names abstain (`spec_for` -> None).

`rand` is not a strategy: it is the luck baseline — seeded random entries at a
fixed rate, measured exactly like every family, so "beats random entries with
the same stop and target on the same coin" is a measured comparison.
"""
from __future__ import annotations

import hashlib
import itertools
import threading

import numpy as np

from tradingagents import pro_indicators as pi

PREFIX = "pt_"

# stop/target pairs (percent) that can pay 2:1 after a ~0.23% round trip, stop
# 3% or less (rows over 2% are flagged: the rooms cap stops at 2%); each must
# be a pair the grid measures (backtest_report.pairs_for)
BARRIERS_PCT = {
    "15m": ((0.4, 1.5), (0.4, 2.0), (0.6, 2.0), (0.6, 2.5), (0.8, 2.5), (1.0, 3.0)),
    "30m": ((0.5, 2.0), (0.6, 2.5), (0.8, 2.5), (1.0, 3.0), (1.2, 4.0), (1.5, 5.0)),
    "1h": ((0.7, 2.5), (1.0, 3.0), (1.2, 4.0), (1.5, 5.0), (2.0, 6.0), (3.0, 8.0)),
    "4h": ((1.0, 3.0), (1.5, 4.0), (1.5, 5.0), (2.0, 6.0), (2.5, 8.0), (3.0, 8.0)),
    "1d": ((1.5, 5.0), (2.0, 6.0), (2.5, 8.0), (3.0, 10.0)),
}


# ------------------------------------------------------------------ families
#
# Each family: title, knobs ((letter, setting, values) x <= 3, values[0] the
# literature's default), fn(ctx, settings) -> np.int8 directions per bar.

def _edge(cond_long: np.ndarray, cond_short: np.ndarray) -> np.ndarray:
    """+1 / -1 on the bar a condition BECOMES true (not every bar while it
    holds), 0 elsewhere."""
    out = np.zeros(len(cond_long), dtype=np.int8)
    cl = np.nan_to_num(cond_long, nan=0).astype(bool)
    cs = np.nan_to_num(cond_short, nan=0).astype(bool)
    prev_l = np.r_[False, cl[:-1]]
    prev_s = np.r_[False, cs[:-1]]
    out[cl & ~prev_l] = 1
    out[cs & ~prev_s & ~(cl & ~prev_l)] = -1
    return out


def _rand(ctx, s) -> np.ndarray:
    """Seeded random entries: each bar is an entry with probability `rate`,
    long or short at random, decided by a hash of the seed, the bar's own
    time and its close, so the runner and the backtest draw the same coin
    flip for the same bar whatever frame they hold, and two coins never share
    their draws (a room of random coins is not one bet)."""
    out = np.zeros(ctx.n, dtype=np.int8)
    rate = float(s["rate"])
    for i, t in enumerate(ctx.ts):
        # the close as a PYTHON float: numpy's own repr changed between major
        # versions ("100.0" -> "np.float64(100.0)"), which would re-deal the
        # draws (code review, Oct 20, 2026)
        h = hashlib.blake2b(f"{s['seed']}:{int(t)}:{float(ctx.c[i])!r}".encode(),
                            digest_size=8).digest()
        u = int.from_bytes(h[:4], "big") / 2 ** 32
        if u < rate:
            out[i] = 1 if h[4] & 1 else -1
    return out


def _level(cond_long: np.ndarray, cond_short: np.ndarray) -> np.ndarray:
    """+1 / -1 on EVERY bar a condition holds (after an exit the engine buys
    again at the next close while it still holds), 0 elsewhere."""
    out = np.zeros(len(cond_long), dtype=np.int8)
    cl = np.nan_to_num(cond_long, nan=0).astype(bool)
    cs = np.nan_to_num(cond_short, nan=0).astype(bool)
    out[cl] = 1
    out[cs & ~cl] = -1
    return out


TREND_BARS = 200              # the trend every gated family agrees with


def _trend(ctx, n: int = TREND_BARS) -> np.ndarray:
    """+1 where the close is above the close n bars before, -1 below, 0 where
    there is no such bar: the sign of time-series momentum (Moskowitz, Ooi &
    Pedersen 2012)."""
    return ctx.memo(("trend", n), lambda: np.sign(np.nan_to_num(pi.roc(ctx.c, n), nan=0.0)))


def _closing_break(ctx, n: int):
    """(close above every close of the n bars before it, close below every
    one): a new n-bar closing high / low — the channel on CLOSES (Zarattini,
    Pagani & Barbon 2025), so a wick alone never counts."""
    def make():
        hi = pi.shift(pi.rolling_max(ctx.c, n), 1)
        lo = pi.shift(pi.rolling_min(ctx.c, n), 1)
        with np.errstate(invalid="ignore"):
            return ctx.c > hi, ctx.c < lo
    return ctx.memo(("cbrk", n), make)


def _calm(ctx, q: float, n: int = 20, m: int = 200) -> np.ndarray:
    """Bars whose last-n-bar volatility sits in the lowest q of its own last
    m readings. The hold-time gate (survey #3): a fixed stop and target stay
    open long enough to collect a trend only while the coin is quiet."""
    def make():
        # simple returns, not logs: a division is exact on every machine, a
        # log's last bit may differ between GitHub's Linux and this PC
        r = pi.roc(ctx.c, 1)
        with np.errstate(invalid="ignore"):
            return pi.pct_rank(pi.rolling_std(r, n), m) <= q
    return ctx.memo(("calm", q, n, m), make)


def _closes(ctx):
    """Each candle's CLOSE in epoch ms — the moment the entry is bought, where
    the spread is paid (survey #7) — as its open plus its own length (the
    gap to the candle before; the first candle takes the next gap). None when
    the frame carries no times: a rule that needs the clock then abstains."""
    def make():
        if ctx.n < 2 or len(ctx.ts) != ctx.n:
            return None
        t = np.asarray(ctx.ts, dtype=np.int64)
        step = np.diff(t, prepend=t[0] - (t[1] - t[0]))
        return t + step
    return ctx.memo("closes", make)


def _window(ctx, w: str) -> np.ndarray:
    """Candles that CLOSE inside a trading window, any day of the week:
    "us" = 9:30am-4pm New York, on New York's own clock (daytime_rule.NY, so
    daylight saving is never a fixed offset); "eu-us" = 12:00pm-9:00pm UTC,
    when spreads are lowest (Dyhrberg, Foley & Svec 2018). With the weekday
    filter, "us" is the daytime rule's market hours at the entry minute."""
    def make():
        closes = _closes(ctx)
        if closes is None:
            return np.zeros(ctx.n, dtype=bool)
        if w == "us":
            import datetime as _dt

            from tradingagents import daytime_rule as _dr

            out = np.zeros(ctx.n, dtype=bool)
            for i, t in enumerate(closes):
                d = _dt.datetime.fromtimestamp(int(t) / 1000.0, _dr.NY)
                out[i] = 9 * 60 + 30 <= d.hour * 60 + d.minute < 16 * 60
            return out
        hours = (closes // 3_600_000) % 24
        return (hours >= 12) & (hours < 21)
    return ctx.memo(("win", w), make)


def _weekday(ctx) -> np.ndarray:
    """Candles that close Monday to Friday (UTC)."""
    def make():
        closes = _closes(ctx)
        if closes is None:
            return np.zeros(ctx.n, dtype=bool)
        # 1970-01-01 was a Thursday: day 0 -> weekday 3
        return ((closes // 86_400_000) + 3) % 7 < 5
    return ctx.memo("weekday", make)


def _brk(ctx, s) -> np.ndarray:
    """#1: a new n-bar closing high (low), long (short), with the 200-bar
    trend agreeing when `gate`, and only in a quiet stretch when `calm`."""
    up, dn = _closing_break(ctx, int(s["bars"]))
    if s["gate"]:
        tr = _trend(ctx)
        up, dn = up & (tr > 0), dn & (tr < 0)
    if s["calm"]:
        quiet = _calm(ctx, 0.5)
        up, dn = up & quiet, dn & quiet
    return _level(up, dn)


def _tsm(ctx, s) -> np.ndarray:
    """#2: long while every chosen lookback's return is up, short while every
    one is down; `entry` "hold" buys again after an exit while that holds,
    "flip" only when the state turns."""
    signs = [_trend(ctx, int(n)) for n in s["lookbacks"]]
    up = np.logical_and.reduce([x > 0 for x in signs])
    dn = np.logical_and.reduce([x < 0 for x in signs])
    if s["sides"] == "long":
        dn = np.zeros_like(dn)
    return _level(up, dn) if s["entry"] == "hold" else _edge(up, dn)


def _ses(ctx, s) -> np.ndarray:
    """#7: the #1 breakout (20 bars, trend agreeing) taken only on candles
    that close inside a trading window, and never at the weekend when
    `weekdays`."""
    up, dn = _closing_break(ctx, 20)
    tr = _trend(ctx)
    ok = _window(ctx, s["window"])
    if s["weekdays"]:
        ok = ok & _weekday(ctx)
    return _level(up & (tr > 0) & ok, dn & (tr < 0) & ok)


SQUEEZE_ONCE = 10             # one entry a side per squeeze: none in the 10 bars before


def _first_in(cond, w: int) -> np.ndarray:
    """True on a bar where `cond` holds and held on none of the w bars before
    it — fixed-window, so the runner's candles decide it the same way."""
    c = np.nan_to_num(cond, nan=0).astype(bool)
    prev = np.zeros_like(c)
    for j in range(1, w + 1):
        prev[j:] |= c[:-j]
    return c & ~prev


def _sqz(ctx, s) -> np.ndarray:
    """#9: within 5 bars after the Bollinger bandwidth (20 bars, 2 deviations)
    sat in the lowest q of its last 120 readings, a close beyond the k-bar box
    (the highs and lows of the k bars before it); the 200-bar trend agreeing
    when `gate`. Once per squeeze: a break counts only when the same side had
    no break in the SQUEEZE_ONCE candles before it (code review, Oct 20, 2026:
    the first cut re-entered within one squeeze 58 times on one pair)."""
    q, k = float(s["q"]), int(s["box"])

    def squeezed():
        mid = pi.sma(ctx.c, 20)
        with np.errstate(invalid="ignore", divide="ignore"):
            bw = 4.0 * pi.rolling_std(ctx.c, 20) / mid
            return pi.pct_rank(bw, 120) <= q
    sq = ctx.memo(("squeeze", q), squeezed)
    recent = np.zeros(ctx.n, dtype=bool)
    for j in range(1, 6):                          # a squeeze 1..5 bars before
        recent |= np.nan_to_num(pi.shift(sq.astype(float), j), nan=0).astype(bool)
    hi, lo = pi.donchian(ctx.h, ctx.l, k)
    with np.errstate(invalid="ignore"):
        up, dn = recent & (ctx.c > hi), recent & (ctx.c < lo)
    if s["gate"]:
        tr = _trend(ctx)
        up, dn = up & (tr > 0), dn & (tr < 0)
    return _level(_first_in(up, SQUEEZE_ONCE), _first_in(dn, SQUEEZE_ONCE))


def _abn(ctx, s) -> np.ndarray:
    """#10: a candle that moved more than k of the coin's usual moves (the
    standard deviation of the 60 candles BEFORE it), in that direction;
    with `volume`, only on at least 1.5x the volume of the 20 before."""
    k = float(s["k"])

    def make():
        r = pi.roc(ctx.c, 1)
        sd = pi.shift(pi.rolling_std(r, 60), 1)
        return r, sd
    r, sd = ctx.memo("abn", make)
    with np.errstate(invalid="ignore"):
        up, dn = r >= k * sd, r <= -k * sd
        if s["volume"]:
            loud = pi.vol_ratio(ctx.v, 20) >= 1.5
            up, dn = up & loud, dn & loud
    return _level(up & (sd > 0), dn & (sd > 0))


def _ma(ctx, s) -> np.ndarray:
    """Dual moving averages (Brock, Lakonishok & LeBaron 1992; Szakmary,
    Shen & Sharma 2010): long when the fast average crosses above the slow,
    short below; `entry` "hold" buys again after an exit while fast stays
    above slow."""
    fast, slow = (int(x) for x in s["pair"])
    f = ctx.memo(("sma", fast), lambda: pi.sma(ctx.c, fast))
    sl = ctx.memo(("sma", slow), lambda: pi.sma(ctx.c, slow))
    with np.errstate(invalid="ignore"):
        up, dn = f > sl, f < sl
    return _level(up, dn) if s["entry"] == "hold" else _edge(up, dn)


def _pull(ctx, s) -> np.ndarray:
    """A pullback inside the trend (Connors & Alvarez): with the trend up over
    `trend` bars, long on the candle the 2-bar RSI drops to `rsi` or below;
    short, mirrored, when it rises to 100 - `rsi` in a downtrend."""
    x = float(s["rsi"])
    r2 = ctx.memo("rsi2", lambda: pi.rsi(ctx.c, 2))
    tr = _trend(ctx, int(s["trend"]))
    with np.errstate(invalid="ignore"):
        return _edge((r2 <= x) & (tr > 0), (r2 >= 100 - x) & (tr < 0))


def _vwm(ctx, s) -> np.ndarray:
    """Volume-weighted time-series momentum (Huang, Sangiorgi & Urquhart
    2024): the sign of the last n candles' returns weighted by their volume;
    "hold" buys again while it holds, "flip" only when it turns."""
    n = int(s["bars"])

    def make():
        r = pi.roc(ctx.c, 1)
        num = pi.rolling_sum(np.nan_to_num(r, nan=0.0) * ctx.v, n)
        den = pi.rolling_sum(ctx.v, n)
        # a window holding bar 0 (no return) is not a full window
        num[:n] = np.nan
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(den > 0, num / den, np.nan)
    m = ctx.memo(("vwm", n), make)
    with np.errstate(invalid="ignore"):
        up, dn = m > 0, m < 0
    return _level(up, dn) if s["entry"] == "hold" else _edge(up, dn)


FAMILIES: dict = {
    "brk": {"title": "Closing breakout with the trend (survey #1)",
            "knobs": (("n", "bars", (20, 55)), ("g", "gate", (True, False)),
                      ("c", "calm", (False, True))),
            "fn": _brk, "lookback": 220,
            "say": lambda s: (f"buy when a candle closes above every close of the last {s['bars']} "
                              f"candles" + (", only while the price is above where it was 200 "
                                            "candles ago" if s["gate"] else "")
                              + (", only in a quiet stretch" if s["calm"] else "")
                              + "; sell short on the mirror image"),
            "expect": "4h and 1d, wide stops (2%) on calm, liquid coins: win 30-36% at TP 4.7% "
                      "(break-even 33%), longs better than shorts; loses its fees in ranges"},
    "tsm": {"title": "Time-series momentum (survey #2)",
            "knobs": (("l", "lookbacks", ((90,), (30,), (30, 90), (30, 90, 180))),
                      ("e", "entry", ("hold", "flip")), ("s", "sides", ("both", "long"))),
            "fn": _tsm, "lookback": 182,
            "say": lambda s: ("buy while the price is above where it was "
                              + " and ".join(str(n) for n in s["lookbacks"]) + " candles ago"
                              + ("" if s["sides"] == "long" else ", sell short while below")
                              + ("; buys again after a trade closes" if s["entry"] == "hold"
                                 else "; only when that turns")),
            "expect": "1d on metals, indices, forex and calm stocks: win 33-37% at SL 2% / "
                      "TP 4.7%; on wild coins about the random rate"},
    "ses": {"title": "Breakout in the busy hours (survey #7)",
            "knobs": (("w", "window", ("eu-us", "us")), ("d", "weekdays", (True, False))),
            "fn": _ses, "lookback": 201,
            "say": lambda s: ("the closing breakout (20 candles, with the 200-candle trend), only on "
                              "candles that open "
                              + ("12:00pm-9:00pm UTC" if s["window"] == "eu-us"
                                 else "9:30am-4pm New York")
                              + (", Monday to Friday" if s["weekdays"] else ", any day")),
            "expect": "the same win rate as the plain breakout, a few hundredths of a percent "
                      "cheaper a trade, 30-60% fewer trades"},
    "sqz": {"title": "Squeeze breakout with the trend (survey #9)",
            "knobs": (("q", "q", (0.2, 0.1)), ("k", "box", (20, 10)), ("g", "gate", (True, False))),
            "fn": _sqz, "lookback": 211,
            "say": lambda s: (f"after the price goes unusually quiet (the narrowest {int(s['q'] * 100)}% "
                              f"of the last 120 candles), buy the close above the last {s['box']} "
                              "candles' highs" + (" with the 200-candle trend up" if s["gate"] else "")
                              + "; sell short on the mirror image"),
            "expect": "1h and 4h: the random win rate to +4 points; many false breaks back into "
                      "the box"},
    "abn": {"title": "Big-candle continuation (survey #10)",
            "knobs": (("k", "k", (2.0, 1.5, 2.5)), ("v", "volume", (False, True))),
            "fn": _abn, "lookback": 62,
            "say": lambda s: (f"buy after a candle rises more than {s['k']:g} times the coin's usual "
                              "move" + (" on at least 1.5x the usual volume" if s["volume"] else "")
                              + "; sell short after a fall that size"),
            "expect": "1d on big, liquid coins: the random win rate to +3 points; fails after "
                      "liquidation spikes, which partly snap back"},
    "ma": {"title": "Moving-average crossover",
           "knobs": (("p", "pair", ((50, 200), (20, 100), (10, 50))), ("e", "entry", ("flip", "hold"))),
           "fn": _ma, "lookback": 201,
           "say": lambda s: (f"buy when the {s['pair'][0]}-candle average crosses above the "
                             f"{s['pair'][1]}-candle average, sell short below"
                             + ("; buys again after a trade closes while it stays above"
                                if s["entry"] == "hold" else "")),
           "expect": "a slower, noisier cousin of time-series momentum: about the random rate "
                     "intraday, a little better on 1d"},
    "pull": {"title": "Pullback inside the trend (Connors RSI 2)",
             "knobs": (("x", "rsi", (10, 5)), ("t", "trend", (200, 100))),
             "fn": _pull, "lookback": 202,
             "say": lambda s: (f"with the price above where it was {s['trend']} candles ago, buy the "
                               f"candle the 2-candle RSI falls to {s['rsi']:g} or below; sell short, "
                               "mirrored, in a downtrend"),
             "expect": "made for small targets and wide stops, the opposite of 2:1: expected to "
                       "fail at 2:1, kept as the comparison"},
    "vwm": {"title": "Volume-weighted momentum",
            "knobs": (("n", "bars", (100, 50, 200)), ("e", "entry", ("hold", "flip"))),
            "fn": _vwm, "lookback": 202,
            "say": lambda s: (f"buy while the last {s['bars']} candles' moves, weighted by their "
                              "volume, add up to a rise; sell short while they add up to a fall"
                              + ("; buys again after a trade closes" if s["entry"] == "hold"
                                 else "; only when that turns")),
            "expect": "like time-series momentum, slightly better where volume confirms the "
                      "trend; about the random rate on thin coins"},
    # the luck baseline: measured like every family, never chosen as a strategy
    "rand": {"title": "Random entries (the luck baseline)", "baseline": True,
             "knobs": (("s", "seed", (0, 1, 2)), ("r", "rate", (0.01, 0.03))),
             "fn": _rand, "lookback": 1,
             "say": lambda s: f"a coin flip on {s['rate'] * 100:g}% of candles (seed {s['seed']})",
             "expect": "loses about its own fees every trade: the bar every family must clear"},
}


def is_baseline(name: str) -> bool:
    """Is this setting the luck baseline (never a strategy to trade)?"""
    spec = spec_for(name)
    return bool(spec and FAMILIES[spec["family"]].get("baseline"))


# ------------------------------------------------------------------- names

def name_of(family: str, digits) -> str:
    kn = FAMILIES[family]["knobs"]
    return PREFIX + family + "_" + "".join(f"{k[0]}{d}" for k, d in zip(kn, digits, strict=True))


def variants(families=None) -> list[str]:
    out = []
    for fam in families or FAMILIES:
        kn = FAMILIES[fam]["knobs"]
        out += [name_of(fam, d) for d in itertools.product(*[range(len(k[2])) for k in kn])]
    return out


def spec_for(key: str) -> dict | None:
    """The family and settings a name holds, or None. Anything after the code
    (the grid's `_gh_<tf>`) is ignored."""
    k = str(key)
    if not k.startswith(PREFIX):
        return None
    parts = k[len(PREFIX):].split("_")
    if len(parts) < 2 or parts[0] not in FAMILIES:
        return None
    fam, code = parts[0], parts[1]
    kn = FAMILIES[fam]["knobs"]
    if len(code) != 2 * len(kn):
        return None
    settings, digits = {}, []
    for j, (letter, setting, values) in enumerate(kn):
        if code[2 * j] != letter or not code[2 * j + 1].isdigit():
            return None
        d = int(code[2 * j + 1])
        if d >= len(values):
            return None
        settings[setting] = values[d]
        digits.append(d)
    return {"family": fam, "name": name_of(fam, digits), "settings": settings,
            "digits": tuple(digits)}


def describe(spec: dict) -> str:
    fam = FAMILIES[spec["family"]]
    return fam["title"] + " · " + ", ".join(f"{k} {v}" for k, v in spec["settings"].items())


def words(name: str) -> str:
    """The setting in plain words, for the results page; "" for a name that
    is not ours."""
    spec = spec_for(name)
    if spec is None:
        return ""
    return FAMILIES[spec["family"]]["say"](spec["settings"])


# ------------------------------------------------------------- the frame

class Ctx:
    """One frame's candles, and the indicators every setting shares. No
    funding: the live runner does not hand `signal_for` the funding history,
    so a family that read it would trade a signal the backtest never saw."""

    def __init__(self, o, h, lo, c, v, ts):
        self.o = np.asarray(o, dtype=float)
        self.h = np.asarray(h, dtype=float)
        self.l = np.asarray(lo, dtype=float)
        self.c = np.asarray(c, dtype=float)
        self.v = np.asarray(v, dtype=float) if v is not None and len(v) else np.zeros(len(c))
        self.ts = [int(x) for x in ts]
        self.n = len(self.c)
        self._memo: dict = {}

    def memo(self, key, make):
        if key not in self._memo:
            self._memo[key] = make()
        return self._memo[key]


_LOCK = threading.Lock()
_FRAMES: dict = {}
_KEEP = 4


def _fingerprint(o, h, lo, c, v, ts) -> bytes:
    """Every value of the frame, hashed: two frames that differ anywhere are
    two cache entries (the first context must never answer for another)."""
    d = hashlib.blake2b(digest_size=16)
    for a in (o, h, lo, c, v, ts):
        d.update(np.asarray(a if a is not None else [], dtype=float).tobytes())
        d.update(b"|")
    return d.digest()


def _ctx(o, h, lo, c, v, ts) -> Ctx:
    key = _fingerprint(o, h, lo, c, v, ts)
    with _LOCK:
        hit = _FRAMES.get(key)
        if hit is None:
            hit = Ctx(o, h, lo, c, v, ts)
            _FRAMES[key] = hit
            while len(_FRAMES) > _KEEP:
                _FRAMES.pop(next(iter(_FRAMES)))
        return hit


def dirs_for(spec: dict, o, h, lo, c, v, ts, funding=None) -> list[int]:
    """+1 / -1 / 0 for every bar of the frame — the runner reads the last."""
    if spec is None or spec.get("family") not in FAMILIES:
        return [0] * len(c)
    ctx = _ctx(o, h, lo, c, v, ts)
    out = FAMILIES[spec["family"]]["fn"](ctx, spec["settings"])
    return [int(x) for x in out]
