"""THE V3 IDEA FAMILIES — four rules whose settings were fixed BEFORE any test.

Spec: docs/superpowers/specs/2026-10-22-backtest-v3-design.md (Part 2);
decisions: docs/superpowers/specs/2026-10-23-backtest-v3-part2-decisions.md
("The families"). Each family has its own timeframes, its own exit and its
own universe:

| family | settings, simplest first | timeframes | longs / shorts in |
|---|---|---|---|
| v3_trend | n = 20, 50, 100 days (6n candles on 4h) | 1d, 4h | liquid or calm / calm |
| v3_breakout | N = 20, 50 days | 1d | liquid or calm / calm |
| v3_strength | K = 3, 5 | 1d | liquid / none |
| v3_snap | k = 1.5, 2.0 | 1h, 4h | calm / calm |

A signal holds on EVERY candle its rule holds; the engine places a waiting
order on the first one and, after an exit, on the next candle that still
signals — what a trend follower does. The averages and ranges are
`v3_rules`' own (`sma`, `atr`), the ones the engine's exits read, so a signal
and its exit never read two numbers for one average.

The proof test judges each family on each timeframe with each filter (a
"judged" group, 30 of them) and chooses its setting there; every family x
setting x timeframe x filter measured (`combos`, 70) counts toward the luck
correction.
"""
from __future__ import annotations

from tradingagents import pro_indicators as pi, v3_rules as vr, v3_universe as vu

LEAD_BARS = 300          # sweep_shard.WARMUP_BARS: the lead-in every stored rule reads
BARS_PER_DAY = {"1h": 24, "4h": 6, "1d": 1}
TREND_LAG_DAYS = 5       # "...and that average is above its value 5 days ago"
BREAKOUT_MA_DAYS = 100   # "...only while the 100-day average is rising"
SNAP_N = 20
SNAP_MAX_BARS = 24

FAMILIES = {
    "v3_trend": {"param": "n", "settings": (20, 50, 100), "tfs": ("1d", "4h"),
                 "long": ("liquid", "calm"), "short": ("calm",)},
    "v3_breakout": {"param": "n", "settings": (20, 50), "tfs": ("1d",),
                    "long": ("liquid", "calm"), "short": ("calm",)},
    "v3_strength": {"param": "k", "settings": (3, 5), "tfs": ("1d",),
                    "long": ("liquid",), "short": ()},
    "v3_snap": {"param": "k", "settings": (1.5, 2.0), "tfs": ("1h", "4h"),
                "long": ("calm",), "short": ("calm",)},
}
FILTERS = ("none", "btc_mood", "busy_hours", "funding_side", "funding_minutes")


def setting_key(family: str, value) -> str:
    """"n20", "n100", "k3", "k1.5" — the setting as the output names it."""
    return f"{FAMILIES[family]['param']}{float(value):g}"


def combo_key(family: str, key: str, tf: str, filt: str) -> str:
    return f"{family}|{key}|{tf}|{filt}"


def combos() -> list[tuple[str, str, str, str]]:
    """Every (family, setting, timeframe, filter) measured — the luck
    correction's count, whether or not a combination trades."""
    return [(f, setting_key(f, v), tf, filt) for f, d in FAMILIES.items() for tf in d["tfs"]
            for v in d["settings"] for filt in FILTERS]


def judged() -> list[tuple[str, str, str]]:
    """Every (family, timeframe, filter) the proof test gives a verdict: it
    chooses the setting inside each."""
    return [(f, tf, filt) for f, d in FAMILIES.items() for tf in d["tfs"] for filt in FILTERS]


def verdict_id(family: str, tf: str, filt: str) -> str:
    """A judged group's stable id (standard kit H): hashed from the group with
    res="v3", so it can never equal a v1 or v2 id."""
    from tradingagents import backtest_report as br

    return br.row_code("ALL", tf, family, 0.0, 0.0, 0.0, "flat", plan=f"judged|{filt}", res="v3")


def lookback(family: str, value, tf: str) -> int:
    """How many candles the rule reads before its first signal can hold."""
    d = BARS_PER_DAY[tf]
    if family == "v3_trend":
        return int(value) * d + TREND_LAG_DAYS * d
    if family == "v3_breakout":
        return max(int(value) * d + 1, (BREAKOUT_MA_DAYS + TREND_LAG_DAYS) * d)
    if family in ("v3_strength", "v3_snap"):
        # snap: its 20-candle average and ATR(20); strength reads only the plan, and its trail
        # needs ATR(20)'s 20 candles
        return max(SNAP_N, vr.ATR_N)
    raise ValueError(f"unknown family {family!r}")


def lead(family: str, value, tf: str) -> int:
    """The candles read before a walk's first tradable one: LEAD_BARS, or the
    rule's own lookback where it is longer (v3_trend n=50 on 4h: 330, n=100:
    630), so the first unseen candle can already signal."""
    return max(LEAD_BARS, lookback(family, value, tf))


def exit_spec(family: str, value, tf: str) -> dict:
    """The family's own exit, in `v3_engine.walk`'s shape."""
    if family == "v3_trend":
        return {"kind": "trail", "atr_mult": vr.TRAIL_ATR,
                "ma_n": int(value) * BARS_PER_DAY[tf]}
    if family in ("v3_breakout", "v3_strength"):
        return {"kind": "trail", "atr_mult": vr.TRAIL_ATR, "ma_n": None}
    if family == "v3_snap":
        return {"kind": "snap", "mean_n": SNAP_N, "stop_atr": vr.TRAIL_ATR,
                "max_bars": SNAP_MAX_BARS}
    raise ValueError(f"unknown family {family!r}")


def _trend(c, n: int, lag: int) -> list[int]:
    ma = vr.sma(c, n)
    out = [0] * len(c)
    for i in range(lag, len(c)):
        now, then = ma[i], ma[i - lag]
        if now is None or then is None:
            continue
        if c[i] > now > then:
            out[i] = 1
        elif c[i] < now < then:
            out[i] = -1
    return out


def _breakout(h, lo, c, n: int, ma_n: int, lag: int) -> list[int]:
    top, bottom = pi.donchian(h, lo, n)            # the n candles BEFORE each one
    ma = vr.sma(c, ma_n)
    out = [0] * len(c)
    for i in range(lag, len(c)):
        now, then = ma[i], ma[i - lag]
        if now is None or then is None:
            continue
        if c[i] > top[i] and now > then:            # a NaN channel compares False
            out[i] = 1
        elif c[i] < bottom[i] and now < then:
            out[i] = -1
    return out


def _monday_close(ms: int, tf: str) -> int | None:
    """The Monday 00:00 UTC a candle CLOSES at, or None. That Monday's rank
    is taken from closes at that instant, so v3_strength's signal candle is
    the one closing then and its order goes in at the rank (the decisions
    doc, "The families", corrected Oct 23, 2026; the spec: "Each Monday 00:00
    UTC rank liquid crypto by 14-day return; long the top K")."""
    close = int(ms) + vu.DAY_MS // BARS_PER_DAY[tf]
    return close if close % vu.DAY_MS == 0 and vu.weekday(close) == 0 else None


def _need_ranks(plan) -> None:
    """v3_strength is decided by the plan's Monday ranks and by nothing else:
    without them, say so by name."""
    if plan is None or "strength" not in plan:
        raise ValueError("v3_strength needs the plan's Monday ranks")


def _strength(t, tf: str, sym: str, plan: dict, k: int) -> list[int]:
    _need_ranks(plan)
    out = [0] * len(t)
    for i, ms in enumerate(t):
        monday = _monday_close(ms, tf)
        if monday is not None:
            r = vu.rank_at(plan, sym, monday)
            if r is not None and r <= k:
                out[i] = 1
    return out


def _snap(h, lo, c, k: float) -> list[int]:
    ma, atr = vr.sma(c, SNAP_N), vr.atr(h, lo, c, vr.ATR_N)
    out = [0] * len(c)
    for i in range(len(c)):
        if ma[i] is None or not atr[i]:
            continue
        if c[i] <= ma[i] - k * atr[i]:
            out[i] = 1
        elif c[i] >= ma[i] + k * atr[i]:
            out[i] = -1
    return out


def rule(family: str, value, tf: str, bars: dict, *, sym: str = "", plan=None) -> list[int]:
    """+1 / -1 / 0 per candle where the family's rule holds — before the
    universe and the filters, which `v3_measure` lays on top. Reads only
    candles up to each one (a closed candle), never after it."""
    h, lo, c, t = bars["h"], bars["l"], bars["c"], bars["t"]
    d = BARS_PER_DAY[tf]
    if family == "v3_trend":
        return _trend(c, int(value) * d, TREND_LAG_DAYS * d)
    if family == "v3_breakout":
        return _breakout(h, lo, c, int(value) * d, BREAKOUT_MA_DAYS * d, TREND_LAG_DAYS * d)
    if family == "v3_strength":
        return _strength(t, tf, sym, plan, int(value))
    if family == "v3_snap":
        return _snap(h, lo, c, float(value))
    raise ValueError(f"unknown family {family!r}")


def forced(family: str, value, tf: str, bars: dict, *, sym: str = "", plan=None):
    """v3_strength's forced exit, as `walk(forced=)` flags: out at the close
    of a candle ending at a Monday 00:00 UTC whose rank no longer has the coin
    in the top 2K (or does not rank it at all). A Monday the plan holds no
    ranking for (past its end) forces nothing: no rank was taken there. None
    for every other family."""
    if family != "v3_strength":
        return None
    _need_ranks(plan)
    k = int(value)
    out = [False] * len(bars["t"])
    for i, ms in enumerate(bars["t"]):
        monday = _monday_close(ms, tf)
        if monday is not None and str(monday) in plan["strength"]:
            r = vu.rank_at(plan, sym, monday)
            out[i] = r is None or r > 2 * k
    return out


def entry_days(family: str, bars: dict, tf: str) -> list[bool]:
    """The candles the family can ever enter on: for v3_strength the candles
    closing at a Monday 00:00 UTC (it ranks once a week), every candle for the
    others — the candles its random entries are drawn from."""
    if family == "v3_strength":
        return [_monday_close(ms, tf) is not None for ms in bars["t"]]
    return [True] * len(bars["t"])


def sides_allowed(family: str, sym: str, plan: dict, at_ms) -> tuple[list[bool], list[bool]]:
    """Per instant (each candle's ORDER minute): may this coin go long, may it
    go short, by its universe membership in that month."""
    f = FAMILIES[family]
    return (vu.member_mask(plan, f["long"], sym, at_ms),
            vu.member_mask(plan, f["short"], sym, at_ms))


def applies(plan: dict, family: str, sym: str) -> bool:
    """Is the coin in any of the family's groups in any month of the plan."""
    f = FAMILIES[family]
    groups = set(f["long"]) | set(f["short"])
    return any(sym in plan[g].get(m, ()) for g in groups for m in plan["months"])
