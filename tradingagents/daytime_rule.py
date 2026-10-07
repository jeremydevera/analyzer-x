"""The daytime rule: a room switches on only what kept winning in hours it can
trade (Oct 07, 2026; trial on #4FC03172).

Operator: "so what do you think is the correct, because its seems like i
cannot rely on winrate for past 30 days" — #4FC03172 had won 9 of 40 practice
trades on the night of Oct 06, 2026, every one opened 7pm-3am New York — then
"yes" to building the best rule of the walk-forward test. Measured over 20,604
saved Backtest v2 trade lists (picks on 16 days, Sep 17 - Oct 02, 2026, each
followed 3 days, takeable trades only): today's rule 14,010 bets, 53.4% won,
-$672.37; this rule 1,655 bets, 60.1% won, +$394.82, green 16 of 16 days.
Spec: docs/superpowers/specs/2026-10-07-daytime-rule-design.md

On top of the room's own line, a strategy is switched on only when:

1. a win pays a loss after the row's own fee: (TP - fee) >= (SL + fee);
2. for a stock token, its trades ENTERED 9:30am-4pm New York, Mon-Fri, over
   the 30 days of its list number >= 20 and won >= the room's line;
3. over the last 7 days of its list (daytime trades only for a stock token)
   it has >= 5 trades and won >= the line.

One flag in the room's settings, `daytime_rule: {"since": <epoch s>}`, read by
the watcher's switch-on pass, the runner's entry loop and Backtest a room.
"""
from __future__ import annotations

import datetime as _dt
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
DAY_MS = 86_400_000
WINDOW_DAYS = 30
RECENT_DAYS = 7
MIN_DAYTIME_TRADES = 20
MIN_RECENT_TRADES = 5


def enabled(settings: dict | None) -> float | None:
    """When the room switched the rule on (epoch seconds), or None."""
    v = (settings or {}).get("daytime_rule")
    if isinstance(v, dict) and v.get("since"):
        try:
            return float(v["since"])
        except (TypeError, ValueError):
            return None
    return None


def is_stock(name: str) -> bool:
    """A tokenized US stock: MEXC names every one with a STOCK suffix."""
    return str(name or "").upper().removesuffix("_USDT").endswith("STOCK")


# US-LISTED ETF TOKENS keep the same hours (final review, Oct 07, 2026:
# #4FC03172 opened VUG_USDT four times on the night of Oct 06, 2026, and an
# ETF's book at night is a stock token's book). Taken from the coins this
# PC's Backtest v2 store holds. NAS100, SPX500 and US30 are NOT here: they
# are priced off index futures that trade nearly round the clock.
US_ETFS = frozenset({
    "ARKK", "DIA", "EWJ", "EWZ", "GDX", "GLD", "IGV", "IWM", "MSTU", "NVDL",
    "SMH", "SOXL", "SOXX", "SPY", "SQQQ", "TLT", "TQQQ", "TSLL", "USO", "VUG",
    "XBI", "XLE", "XLK"})


def us_hours(name: str) -> bool:
    """Does this token follow US market hours under the rule: a stock token,
    or a US-listed ETF token."""
    base = str(name or "").upper().removesuffix("_USDT")
    return is_stock(base) or base in US_ETFS


def in_market_hours(ts_s: float) -> bool:
    """Mon-Fri 9:30am-4:00pm New York (the close itself is out), judged in New
    York's own clock at that instant, so daylight saving is never a fixed
    offset. No holiday calendar."""
    t = _dt.datetime.fromtimestamp(float(ts_s), NY)
    if t.weekday() >= 5:
        return False
    minutes = t.hour * 60 + t.minute
    return 9 * 60 + 30 <= minutes < 16 * 60


def fee_of(row: dict) -> float | None:
    """The row's own round-trip cost in percent of the trade: `rt`, else
    `cost_of_tp` (percent of the target) times the target. None when unknown."""
    rt = row.get("rt")
    if rt is not None:
        try:
            return float(rt)
        except (TypeError, ValueError):
            return None
    k = row.get("cost_of_tp")
    try:
        k = float(k)
    except (TypeError, ValueError):
        return None
    if k <= 0:
        return None
    return k * float(row["tp"]) / 100.0


def pays_a_loss(row: dict) -> bool:
    """(TP - fee) >= (SL + fee). An unknown fee never passes (rule 12)."""
    fee = fee_of(row)
    if fee is None:
        return False
    return float(row["tp"]) - fee >= float(row["sl"]) + fee - 1e-9


def _rate(trades: list) -> tuple[int, float]:
    n = len(trades)
    return n, (100.0 * sum(1 for t in trades if float(t[2]) > 0) / n) if n else 0.0


def list_checks(trades: list, coin: str, end_ms: int, line: float) -> str:
    """"" when the strategy's own trade list passes checks 2 and 3, else why.
    `trades` are room_replay lists ([entry_ms, known_ms, pnl, closed, exit_ms,
    why, side]); windows end at the list's own last candle `end_ms`, so a pair
    measured a day behind is judged on its own days, not emptied by the clock."""
    end = int(end_ms)
    closed = [t for t in trades if t[3] and int(t[4]) <= end]
    stock = us_hours(coin)

    def kept(t):
        return not stock or in_market_hours(int(t[0]) / 1000)

    if stock:
        month = [t for t in closed if int(t[4]) >= end - WINDOW_DAYS * DAY_MS and kept(t)]
        n, wr = _rate(month)
        if n < MIN_DAYTIME_TRADES:
            return (f"{n} daytime trades (9:30am-4pm New York) in {WINDOW_DAYS} days, "
                    f"fewer than {MIN_DAYTIME_TRADES}")
        if wr < line:
            return f"its daytime trades won {wr:.1f}%, under {line:g}% ({n} trades)"
    week = [t for t in closed if int(t[4]) >= end - RECENT_DAYS * DAY_MS and kept(t)]
    n, wr = _rate(week)
    what = "daytime trades" if stock else "trades"
    if n < MIN_RECENT_TRADES:
        return f"the last {RECENT_DAYS} days hold {n} {what}, fewer than {MIN_RECENT_TRADES}"
    if wr < line:
        return f"the last {RECENT_DAYS} days' {what} won {wr:.1f}%, under {line:g}% ({n} trades)"
    return ""


UNREAD = "unread: "


def is_unread(why: str) -> bool:
    """A failure that says nothing about the strategy - its list could not be
    built or reads old days. Never a switch-on; never a switch-off either:
    an unreadable file keeps a running row (CLAUDE.md, the watcher)."""
    return str(why or "").startswith(UNREAD)


def check_of(why: str) -> str:
    """Which check a reason belongs to, for the per-check counts."""
    w = str(why or "")
    if is_unread(w):
        return "unread"
    if "after fees" in w or "fee is unknown" in w:
        return "fee"
    if "daytime trades (9:30am" in w or "its daytime trades won" in w:
        return "daytime record"
    return "last 7 days"


def screen(rows: list, cfg: dict, *, lists_for) -> tuple[list, dict]:
    """(rows that pass, {id: why} for the rest). The fee check first, from the
    row alone; trade lists (`lists_for(rows) -> {id: {"trades", "end_ms",
    "why"}}`) are asked only for the rows it lets through. A row with no list,
    or a list ending a day or more before its row's own last bar
    (`measured_ms`), fails as UNREAD (`is_unread`)."""
    line = float(cfg["on_winrate"])
    failed: dict = {}
    survivors = []
    for r in rows:
        if pays_a_loss(r):
            survivors.append(r)
            continue
        fee = fee_of(r)
        failed[r["id"]] = (
            "its fee is unknown, so a win cannot be shown to pay a loss" if fee is None
            else f"a win pays {float(r['tp']) - fee:.2f}% against a "
                 f"{float(r['sl']) + fee:.2f}% loss after fees")
    lists = lists_for(survivors) if survivors else {}
    passed = []
    for r in survivors:
        rec = lists.get(r["id"]) or {}
        trades = rec.get("trades") or []
        if not trades:
            failed[r["id"]] = (f"{UNREAD}no trade list could be built for it"
                               + (f" ({rec['why']})" if rec.get("why") else ""))
            continue
        end = int(rec.get("end_ms") or max(int(t[4]) for t in trades))
        bar = r.get("measured_ms")
        if bar and end < float(bar) - DAY_MS:
            from tradingagents.positions_view import fmt_when

            failed[r["id"]] = (f"{UNREAD}its trade list ends {fmt_when(end / 1000)}, more "
                               f"than a day before its own last bar "
                               f"{fmt_when(float(bar) / 1000)}")
            continue
        why = list_checks(trades, r["coin"], end, line)
        if why:
            failed[r["id"]] = why
        else:
            passed.append(r)
    return passed, failed
