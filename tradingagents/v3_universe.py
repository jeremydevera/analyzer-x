"""THE V3 UNIVERSE — which coins each Backtest v3 family may trade, month by
month, and the cross-coin data two families read (BTC's mood, the weekly
strength ranks).

Spec: docs/superpowers/specs/2026-10-22-backtest-v3-design.md (Part 2, the
universe words); decisions: docs/superpowers/specs/2026-10-23-backtest-v3-
part2-decisions.md ("The universe"). Built on this PC from daily candles
before a run and written as the run's plan file (`PLAN_FILE`), so every
machine reads the same universe.

* LIQUID crypto: kind "crypto", the top 50 by 30-day traded value at each
  month start. A day's traded value is its Volume (in contracts) x the
  contract size x its close — TODAY's contract size, said in the file.
* CALM contracts: kinds metals, indices and forex every month, plus the
  liquid crypto in the calmest third by 60-day realized volatility (the
  standard deviation of daily log returns) at each month start.
* LEFT OUT: a volatility index (BVOL, EVOL, GVZ, VOLX) is never calm — it
  jumps by design — and a stablecoin is never calm or liquid — it barely
  moves (Ruling A in the Part 2a build ledger). Each is named in the plan's
  `left_out` with why.
* BTC's MOOD: each daily close against its 50-day average, known only once
  that day's candle has closed.
* STRENGTH ranks: each Monday 00:00 UTC, that month's liquid crypto by 14-day
  return (the close at Monday 00:00 against the close 14 days before), best
  first.

Every number is worked from candles CLOSED before the instant it is used at,
so no coin is chosen with hindsight. Candidates are the contracts the
exchange trades TODAY: a coin delisted during the year is missing
(survivorship bias, said beside every verdict).
"""
from __future__ import annotations

import bisect
import calendar
import json
import math
import os
import statistics
import time
from pathlib import Path

DAY_MS = 86_400_000
WINDOW_DAYS = 365
LIQUID_TOP = 50
VALUE_DAYS = 30
VOL_DAYS = 60
STRENGTH_DAYS = 14
MOOD_DAYS = 50
CALM_KINDS = ("metals", "indices", "forex")
VOL_INDICES = ("BVOL_USDT", "EVOL_USDT", "GVZ_USDT", "VOLX_USDT")
STABLECOINS = ("USDC", "USDT", "FDUSD", "TUSD", "DAI", "USDE", "PYUSD", "USDD", "BUSD", "USD1",
               "RLUSD", "USDP", "FRAX", "GUSD", "USDS", "USDG")
BTC = "BTC_USDT"
VERSION = 1
PLAN_FILE = Path(__file__).resolve().parent.parent / "research" / "v3" / "plan.json"
SURVIVORSHIP = ("Candidates are the contracts the exchange trades today: a coin delisted "
                "during the year is missing (survivorship bias).")
SIZE_NOTE = ("A day's traded value is its volume in contracts x TODAY's contract size x "
             "its close.")
LEFT_OUT_NOTE = ("A volatility index is never calm (it jumps by design) and a stablecoin is never "
                 "calm or liquid (it barely moves): each is named in left_out.")


def month_key(ms: int) -> str:
    """"YYYY-MM" of the UTC month an instant falls in."""
    g = time.gmtime(int(ms) // 1000)
    return f"{g.tm_year:04d}-{g.tm_mon:02d}"


def month_start(ms: int) -> int:
    g = time.gmtime(int(ms) // 1000)
    return calendar.timegm((g.tm_year, g.tm_mon, 1, 0, 0, 0)) * 1000


def _next_month(ms: int) -> int:
    g = time.gmtime(int(ms) // 1000)
    y, m = g.tm_year + (g.tm_mon == 12), g.tm_mon % 12 + 1
    return calendar.timegm((y, m, 1, 0, 0, 0)) * 1000


def months_between(start_ms: int, end_ms: int) -> list[int]:
    """The UTC month starts of every month that overlaps [start_ms, end_ms)."""
    out, m = [], month_start(start_ms)
    while m < int(end_ms):
        out.append(m)
        m = _next_month(m)
    return out


def weekday(ms: int) -> int:
    """Monday 0 ... Sunday 6, in UTC (Jan 01, 1970 was a Thursday)."""
    return (int(ms) // DAY_MS + 3) % 7


def mondays_between(start_ms: int, end_ms: int) -> list[int]:
    """Every Monday 00:00 UTC in [start_ms, end_ms)."""
    d = -(-int(start_ms) // DAY_MS)
    while weekday(d * DAY_MS):
        d += 1
    out = []
    while d * DAY_MS < int(end_ms):
        out.append(d * DAY_MS)
        d += 7
    return out


def daily_of(df, end_ms: int) -> dict:
    """A Date/Close/Volume frame -> {"t": opens ms, "c", "v"}, CLOSED candles
    only: the ones that ended by `end_ms`."""
    t = df["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
    keep = t + DAY_MS <= int(end_ms)
    return {"t": [int(x) for x in t[keep]],
            "c": [float(x) for x in df["Close"].to_numpy()[keep]],
            "v": [float(x) for x in df["Volume"].to_numpy()[keep]]}


def _span(daily: dict, lo_ms: int, hi_ms: int) -> tuple[int, int]:
    """The candles OPENING in [lo_ms, hi_ms)."""
    t = daily["t"]
    return bisect.bisect_left(t, int(lo_ms)), bisect.bisect_left(t, int(hi_ms))


def traded_value(daily: dict, contract_size: float, at_ms: int) -> float:
    """What traded in the VALUE_DAYS daily candles that closed by `at_ms`, in
    dollars: the sum of volume x contract size x close."""
    a, b = _span(daily, at_ms - VALUE_DAYS * DAY_MS, at_ms)
    return sum(daily["v"][k] * contract_size * daily["c"][k] for k in range(a, b))


def realized_vol(daily: dict, at_ms: int) -> float | None:
    """The standard deviation of the VOL_DAYS daily log returns that closed by
    `at_ms` (VOL_DAYS + 1 closes); None when any of those days is missing:
    unknown is never calm."""
    a, b = _span(daily, at_ms - (VOL_DAYS + 1) * DAY_MS, at_ms)
    closes = daily["c"][a:b]
    if len(closes) < VOL_DAYS + 1 or min(closes) <= 0:
        return None
    rets = [math.log(y / x) for x, y in zip(closes, closes[1:], strict=False)]
    return statistics.pstdev(rets)


def _close_at(daily: dict, close_ms: int) -> float | None:
    """The close of the daily candle that ENDED at `close_ms`, or None."""
    k = bisect.bisect_left(daily["t"], int(close_ms) - DAY_MS)
    if k < len(daily["t"]) and daily["t"][k] == int(close_ms) - DAY_MS:
        return daily["c"][k]
    return None


def return_14(daily: dict, at_ms: int) -> float | None:
    """The STRENGTH_DAYS return at `at_ms`: the close at that instant against
    the close STRENGTH_DAYS before it; None when either candle is missing."""
    now, then = _close_at(daily, at_ms), _close_at(daily, at_ms - STRENGTH_DAYS * DAY_MS)
    if now is None or then is None or then <= 0:
        return None
    return now / then - 1.0


def mood_of(daily: dict, from_ms: int) -> dict:
    """BTC's mood at each daily close from `from_ms` on: {"t": close ms, "up":
    1 when that close is above the average of the MOOD_DAYS closes ending with
    it, else 0} — only closes with MOOD_DAYS of history."""
    t, c = daily["t"], daily["c"]
    out_t, out_up, total = [], [], 0.0
    for k, close in enumerate(c):
        total += close
        if k >= MOOD_DAYS:
            total -= c[k - MOOD_DAYS]
        if k >= MOOD_DAYS - 1 and t[k] + DAY_MS >= int(from_ms):
            out_t.append(t[k] + DAY_MS)
            out_up.append(int(close > total / MOOD_DAYS))
    return {"t": out_t, "up": out_up}


def left_out_why(sym: str) -> str:
    """Why a contract may never be in a group, or "" (Ruling A): a
    volatility index is never calm, a stablecoin (by its base) never calm or
    liquid."""
    if sym in VOL_INDICES:
        return "a volatility index: it jumps by design, so it is never calm"
    if sym.split("_")[0] in STABLECOINS:
        return "a stablecoin: it barely moves, so it is never calm or liquid"
    return ""


def build(dailies: dict, kinds: dict, sizes: dict, end_ms: int, *, skipped=None,
          venue_name: str = "", built_s: float | None = None) -> dict:
    """The plan: membership per month, BTC's mood and the Monday ranks over
    the WINDOW_DAYS before `end_ms` (a UTC midnight: every daily candle used
    closed by then). `dailies` {symbol: daily_of(...)}, `kinds` {symbol:
    venue kind} for every candidate, `sizes` {symbol: contract size}."""
    from tradingagents.positions_view import fmt_when

    end_ms = int(end_ms)
    start_ms = end_ms - WINDOW_DAYS * DAY_MS
    left_out = {s: why for s, k in sorted(kinds.items())
                if (k == "crypto" or k in CALM_KINDS) and (why := left_out_why(s))}
    crypto = sorted(s for s in dailies
                    if kinds.get(s) == "crypto" and sizes.get(s) and s not in left_out)
    calm_kind = sorted(s for s, k in kinds.items() if k in CALM_KINDS and s not in left_out)
    liquid, value, calm, vol = {}, {}, {}, {}
    for m in months_between(start_ms, end_ms):
        key = month_key(m)
        ranked = sorted(((traded_value(dailies[s], sizes[s], m), s) for s in crypto),
                        key=lambda x: (-x[0], x[1]))
        top = [(v, s) for v, s in ranked if v > 0][:LIQUID_TOP]
        liquid[key] = [s for _v, s in top]
        value[key] = [round(v) for v, _s in top]
        vols = []
        for s in liquid[key]:
            v = realized_vol(dailies[s], m)
            if v is not None:
                vols.append((v, s))
        vols.sort()
        calmest = vols[:math.ceil(len(vols) / 3)]
        calm[key] = calm_kind + [s for _v, s in calmest]
        vol[key] = {s: round(v, 6) for v, s in vols}
    strength = {}
    for monday in mondays_between(start_ms - 7 * DAY_MS, end_ms):
        rets = [(return_14(dailies[s], monday), s) for s in liquid.get(month_key(monday), [])]
        strength[str(monday)] = [s for r, s in sorted(((r, s) for r, s in rets if r is not None),
                                                      key=lambda x: (-x[0], x[1]))]
    if BTC not in dailies:
        raise ValueError(f"{BTC} has no daily candles: its mood cannot be worked out")
    coins = sorted({s for g in (liquid, calm) for members in g.values() for s in members})
    built = time.time() if built_s is None else float(built_s)
    return {"version": VERSION, "venue": venue_name, "built": fmt_when(built),
            "built_s": built, "start_ms": start_ms, "end_ms": end_ms,
            "start": fmt_when(start_ms / 1000), "end": fmt_when(end_ms / 1000),
            "months": sorted(liquid), "liquid": liquid, "value": value, "calm": calm,
            "vol": vol, "strength": strength,
            "mood": mood_of(dailies[BTC], start_ms - 7 * DAY_MS),
            "kinds": {s: kinds[s] for s in sorted(set(coins) | {BTC}) if s in kinds},
            "sizes": {s: sizes[s] for s in crypto},
            "coins": coins, "skipped": dict(skipped or {}), "left_out": left_out,
            "notes": [SURVIVORSHIP, SIZE_NOTE, LEFT_OUT_NOTE]}


def collect(*, fx=None, end_ms: int | None = None, kind_of=None, log=print) -> dict:
    """Read every candidate's daily candles from the exchange and build the
    plan. A candidate whose candles or listing cannot be read is NAMED in
    `skipped`, never dropped quietly."""
    from tradingagents import venue

    if fx is None:
        from tradingagents.dataflows import exchange as fx
    kind_of = kind_of or venue.kind
    now_ms = int(time.time() * 1000)
    end_ms = int(end_ms) if end_ms is not None else now_ms - now_ms % DAY_MS
    first = month_start(end_ms - WINDOW_DAYS * DAY_MS) - (VOL_DAYS + 2) * DAY_MS
    days = -(-(now_ms - first) // DAY_MS) + 2
    syms = sorted(fx.trading_symbols())
    kinds = {s: kind_of(s) for s in syms}
    dailies, sizes, skipped = {}, {}, {}
    crypto = [s for s in syms if kinds[s] == "crypto"]
    for n, s in enumerate(crypto, 1):
        try:
            sizes[s] = float(fx.contract_spec(s).get("contractSize") or 0.0)
            if sizes[s] <= 0:
                skipped[s] = "contract size 0: its traded value cannot be worked out"
                continue
            dailies[s] = daily_of(fx.klines(s, "Day1", days), end_ms)
        except Exception as exc:                               # noqa: BLE001
            skipped[s] = f"{type(exc).__name__}: {str(exc)[:160]}"
        if n % 100 == 0:
            log(f"  daily candles: {n} of {len(crypto)} crypto contracts")
    return build(dailies, kinds, sizes, end_ms, skipped=skipped, venue_name=venue.name())


def save(plan: dict, path: Path | str = PLAN_FILE) -> Path:
    """Write the plan whole (a temp file swapped in)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(plan, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    os.replace(tmp, p)
    return p


def load(path: Path | str = PLAN_FILE) -> dict:
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    if plan.get("version") != VERSION:
        raise ValueError(f"{path}: plan version {plan.get('version')!r}, this code reads {VERSION}")
    return plan


def member_mask(plan: dict, groups, sym: str, at_ms) -> list[bool]:
    """Per instant: is `sym` in any of `groups` ("liquid", "calm") in the
    month that instant falls in. An instant outside the plan's months is no
    member."""
    months = {m for m in plan["months"] if any(sym in plan[g].get(m, ()) for g in groups)}
    return [month_key(ms) in months for ms in at_ms]


def mood_at(plan: dict, at_ms) -> list[bool | None]:
    """Per instant: BTC's mood from its last daily candle CLOSED by then —
    True above its 50-day average, False not, None when no close of the last
    day is in the plan (unknown)."""
    t, up = plan["mood"]["t"], plan["mood"]["up"]
    out = []
    for ms in at_ms:
        k = bisect.bisect_right(t, int(ms)) - 1
        out.append(bool(up[k]) if k >= 0 and int(ms) - t[k] < DAY_MS else None)
    return out


def rank_at(plan: dict, sym: str, monday_ms: int) -> int | None:
    """`sym`'s place (1 = best) in the strength ranking taken at that Monday
    00:00 UTC, or None when it is not ranked there."""
    ranked = plan["strength"].get(str(int(monday_ms)))
    if not ranked or sym not in ranked:
        return None
    return ranked.index(sym) + 1
