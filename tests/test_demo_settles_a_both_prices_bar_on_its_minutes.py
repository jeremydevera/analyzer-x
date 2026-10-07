"""A practice trade left open through a power cut is settled on the MINUTES of
a candle that held both its target and its stop — never on "the stop wins"
(docs/RCA.md RCA-2026-10-07-H).

The receipt, from #4FC03172's own trade record and MEXC's own candles:

* `Oct 02, 2026 4:00pm` — the 3:30pm half-hour candle closed and BOTH
  stoch14_30m_sl1tp12 (`K96XNZSD`) and willr14_30m_sl1tp12 (`FYWQFLWV`) went
  SHORT NVD_USDT at 3.45 on the practice account: target 3.4086, stop 3.4845.
* `Oct 02, 2026 7:32pm` — the PC lost power (Windows event 6008). Every room
  stopped with it.
* `Oct 02, 2026 10:30pm` — the half-hour candle that ran to 11:00pm went as
  high as 3.66 and as low as 3.39: BOTH prices. Its one-minute candles say
  which came first — 10:51pm, low 3.39, the target; the stop was first
  touched at 10:55pm (high 3.52).
* `Oct 03, 2026 2:06am` — the runners came back. At 2:08am this room walked
  the strategy's OWN half-hour candles first, where a candle holding both
  prices is booked as the stop, and read the minutes only when those candles
  showed nothing: "EXIT NVD_USDT SHORT SL at 3.4845 -> pnl -1.30", twice.

A real bracket at MEXC, a runner that had looked at NVD between 10:51pm and
11:00pm, and Backtest v2's minute rule all say TARGET, +0.90 each: two wins
written down as two losses, 4.40 of practice money, in the win rate the
watcher switches rows on and off by. 113 of the 115 exits caught up after the
four power cuts agree with the minutes; these two did not.

THE RULE NOW is Backtest v2's (`backtest_strategy(fine=)`): a candle that held
both prices is walked minute by minute, the first price touched wins, both in
one minute is still the stop, minutes that touch neither keep the candle's
own rule, and a candle whose minutes are not all there keeps the stop — never
a guess. The Runner feed says which of those it was. No minute from before
the order can decide (RCA-2026-09-12-A), and the real-money book is never
touched.

ONE TIMELINE: the half-hour candles are built FROM the one-minute candles, the
venue hands the runner exactly what MEXC would at the fake clock, and the
positions carry the operator's real entry candle — the ids K96XNZSD and
FYWQFLWV are recomputed from it by the runner, not copied in.
"""
from __future__ import annotations

import json
import time

import pandas as pd
import pytest

from tradingagents import auto_trader as at, live_price as lp

COIN = "NVD_USDT"
STOCH, WILLR = "stoch14_30m_sl1tp12", "willr14_30m_sl1tp12"   # TP 1.2%, SL 1%
ENTRY, TP, SL = 3.45, 3.4086, 3.4845          # SHORT: the target sits BELOW
QUIET = (3.46, 3.44)                          # a minute that touches neither
MIN, HALF = 60, 1800

# Epoch seconds. The operator's clock is New York (EDT, UTC-4).
SIGNAL_BAR = 1_790_969_400          # Oct 02, 2026 3:30pm — the entry candle
OPENED_AT = SIGNAL_BAR + HALF + 4   # Oct 02, 2026 4:00pm — the order went out
BOTH_BAR = 1_790_994_600            # Oct 02, 2026 10:30pm — high 3.66, low 3.39
NOW = 1_791_007_680                 # Oct 03, 2026 2:08am — the catch-up exits
LAST_HALF = NOW // HALF * HALF - HALF   # 1:30am, the newest CLOSED candle
# The first minute a runner reads back at NOW: `PAPER_MINUTES` of them, the
# forming one included — Oct 02, 2026 9:09pm.
READ_FROM = NOW // MIN * MIN - (at.PAPER_MINUTES - 1) * MIN

# Inside the 10:30pm candle. The touching prices are MEXC's own, as the
# verifier fetched them (10:51pm low 3.39, 10:55pm high 3.52, the candle's
# 3.66 high); each minute's other half, and 10:58pm for the 3.66, are assumed.
INCIDENT = {BOTH_BAR + 21 * MIN: (3.43, 3.39),   # 10:51pm: low 3.39 — target
            BOTH_BAR + 25 * MIN: (3.52, 3.45),   # 10:55pm: high 3.52 — stop
            BOTH_BAR + 28 * MIN: (3.66, 3.50)}   # the candle's high, later


def _minutes(touches=None, start=SIGNAL_BAR):
    """{minute open: (high, low)} from the entry candle to the minute still
    forming at NOW — quiet, except for `touches`."""
    touches = INCIDENT if touches is None else touches
    return {t: touches.get(t, QUIET)
            for t in range(start, NOW // MIN * MIN + 1, MIN)}


class Venue:
    """What MEXC hands a runner at the fake clock: the newest `limit` candles
    of the asked size, the forming one included — every size built from the
    SAME minutes, so a half-hour candle and its minutes cannot disagree."""

    SIDE_OPEN_LONG, SIDE_CLOSE_SHORT, SIDE_OPEN_SHORT, SIDE_CLOSE_LONG = 1, 2, 3, 4
    TYPE_LIMIT = 1
    STEP = {"Min1": MIN, "Min30": HALF}

    def __init__(self, minutes):
        self.minutes = minutes
        self.asked: list[str] = []
        self.orders: list = []

    def klines(self, symbol, interval, limit):
        self.asked.append(interval)
        step = self.STEP[interval]
        last = int(time.time()) // step * step
        rows = []
        for t in range(last - (int(limit) - 1) * step, last + 1, step):
            inside = [self.minutes[m] for m in range(t, t + step, MIN)
                      if m in self.minutes]
            rows.append((t, max((h for h, _l in inside), default=QUIET[0]),
                         min((lo for _h, lo in inside), default=QUIET[1])))
        return pd.DataFrame({
            "Date": pd.to_datetime([r[0] for r in rows], unit="s"),
            "Open": [ENTRY] * len(rows), "High": [r[1] for r in rows],
            "Low": [r[2] for r in rows], "Close": [ENTRY] * len(rows),
            "Volume": [1.0] * len(rows)})

    def contract_spec(self, symbol):
        return {"priceScale": 4, "contractSize": 1, "maxVol": 0,
                "takerFeeRate": 0.0002, "maintenanceMarginRate": 0.005}

    def book_cost(self, symbol, notional_usd=200.0):
        return {"spread": 0.0002, "slippage": 0.0002, "book_exhausted": False}

    def funding_now(self, symbol):
        return {"symbol": symbol, "rate": 0.0, "cycle_h": 8,
                "next_settle_ms": 0, "per_day": 0.0}

    def open_positions(self, symbol=None):
        return []

    def position_history(self, symbol=None, page_size=20):
        return []

    def last_price(self, symbol):
        self.asked.append("last")
        return ENTRY

    def contracts_for(self, symbol, notional, price=None):
        return int(notional)

    def submit(self, symbol, side, vol, **kw):
        self.orders.append((symbol, side, vol))
        return {"dry_run": kw.get("dry_run", True)}


_CACHES = ("_BAR_CACHE", "_GATE_CACHE", "_GATE_LOGGED", "_CYCLE_PRICES",
           "_CYCLE_GATES", "_FUNDING_CACHE")


def _clear_caches():
    for name in _CACHES:
        cache = getattr(at, name, None)
        if hasattr(cache, "clear"):
            cache.clear()


@pytest.fixture
def clock(monkeypatch):
    """ONE clock for every reader: the venue's candles, the closed-candle cut,
    the feed's staleness and the trade record's stamps. The module caches are
    emptied on the way in AND out, so nothing stamped on this fake clock is
    served to a test running on the real one."""
    monkeypatch.setattr(time, "time", lambda: float(NOW))
    _clear_caches()
    monkeypatch.setattr(at, "_SAID", {})
    # a runner just back from a power cut: its socket holds nothing yet, so
    # the minutes come from the REST read every room on the PC shares
    monkeypatch.setattr(lp, "FEED", lp.PriceFeed())
    yield NOW
    _clear_caches()


@pytest.fixture
def said(monkeypatch):
    """Every Runner-feed line about a candle that held both prices, counted at
    the logger itself — not through caplog: another test in the suite runs
    the module as __main__ and re-plumbs logging, so capture depends on test
    order (tests/test_a_switched_off_practice_trade_is_finished.py)."""
    lines: list[str] = []
    for level in ("info", "warning"):
        real = getattr(at.logger, level)

        def record(msg, *a, _real=real, **k):
            if "held both the target and the stop" in str(msg):
                lines.append(str(msg) % a)
            return _real(msg, *a, **k)

        monkeypatch.setattr(at.logger, level, record)
    return lines


def _when(ts):
    """The feed's own stamp for `ts` — THE format, in this PC's clock."""
    return at._pv_fmt(ts)


def _short(key, *, opened_at=OPENED_AT, entry_ts=SIGNAL_BAR):
    """The practice position as the runner stored it. `rt_cost` is the cost
    both real exits were charged: -1.30 = (-1% - 0.3%) x $100 of coin."""
    return {"side": -1, "vol": 29, "entry": ENTRY, "tp": TP, "sl": SL,
            "margin": 5.0, "strategy": key, "entry_ts": entry_ts,
            "opened_at": opened_at, "dry": True, "bracket": True, "step": 0,
            "rt_cost": 0.003}


def _run(minutes, positions: dict) -> Venue:
    """ONE `run_cycle` — the runner's own entry — for a room whose practice
    slots hold `positions` ({strategy: position}), armed on practice the way
    the watcher arms a row. The newest closed candle is already considered,
    so this cycle is about the exits alone."""
    keys = list(positions)
    at._write_json(at.SETTINGS_PATH, {
        "strategies": keys, "strategy_coins": {k: [COIN] for k in keys},
        "strategy_books": {at.book_slot(k, COIN): ["paper"] for k in keys},
        "margin": 5.0, "enabled": False, "dry_run": True})
    at._write_json(at.STATE_PATH, {
        at.state_key(COIN, True, k): {"step": 0,
                                      "last_ts": {"Min30": LAST_HALF},
                                      "position": p}
        for k, p in positions.items()})
    venue = Venue(minutes)
    at.run_cycle(fx=venue)
    return venue


def _exits():
    if not at.LEDGER_PATH.exists():
        return []
    rows = [json.loads(x) for x in
            at.LEDGER_PATH.read_text(encoding="utf-8").splitlines() if x]
    return [r for r in rows if r.get("action") == "exit"]


def _booked():
    return [(r["why"], r["exit"], r["pnl_est"]) for r in _exits()]


# --------------------------------------------------------------- the bug
def test_the_power_cut_trades_are_settled_on_their_minutes(clock, said):
    """K96XNZSD and FYWQFLWV themselves: the 10:30pm candle held both prices
    and its minutes touched the target at 10:51pm, four minutes before the
    stop."""
    venue = _run(_minutes(), {STOCH: _short(STOCH), WILLR: _short(WILLR)})
    got = {r["trade_id"]: (r["why"], r["exit"], r["pnl_est"])
           for r in _exits()}
    assert got == {"K96XNZSD": ("TP", TP, 0.9),
                   "FYWQFLWV": ("TP", TP, 0.9)}, (
        "the candle held both prices and its minutes say the target came "
        "first — booking the stop is how two wins became 'SL at 3.4845 -> "
        f"pnl -1.30' twice: {got}")
    state = at.load_state()
    assert not any((state.get(at.state_key(COIN, True, k)) or {})
                   .get("position") for k in (STOCH, WILLR))
    assert "Min1" in venue.asked, "the minutes were never read"
    assert sorted(said) == [
        f"{COIN} {k}: the {_when(BOTH_BAR)} candle held both the target and "
        "the stop — its one-minute candles say TP came first."
        for k in (STOCH, WILLR)], said


def test_a_long_is_settled_the_same_way(clock):
    """The same candle mirrored for a LONG — made-up numbers, NVD's real pair
    was short: target 3.4914 reached at 10:51pm, stop 3.4155 at 10:55pm."""
    touches = {BOTH_BAR + 21 * MIN: (3.51, 3.47),   # high 3.51 — target
               BOTH_BAR + 25 * MIN: (3.45, 3.38)}   # low 3.38 — stop
    pos = dict(_short(STOCH), side=1, tp=3.4914, sl=3.4155)
    _run(_minutes(touches), {STOCH: pos})
    assert _booked() == [("TP", 3.4914, 0.9)]


# ------------------------------------------------- never a guess
@pytest.mark.parametrize("bar, missing", [
    (BOTH_BAR - 4 * HALF, 30),     # 8:30pm: every minute older than the read
    (BOTH_BAR - 3 * HALF, 9),      # 9:00pm: 9:00-9:08pm older than the read
], ids=["no-minutes", "first-nine-minutes-missing"])
def test_a_candle_whose_minutes_are_not_all_there_keeps_the_stop(
        clock, said, bar, missing):
    """The Oct 02, 2026 outage was 394 minutes and a runner reads back 300:
    at 2:08am nothing before 9:09pm was read. A candle the read only partly
    covers could have reached the stop in a minute nobody saw — so the stop
    stands, even with the target minute in hand (9:21pm in the second case),
    and the feed counts the minutes it could not see."""
    assert sum(1 for t in range(bar, bar + HALF, MIN) if t < READ_FROM) \
        == missing, "the fixture's hole is not where this test says it is"
    touches = {bar + 21 * MIN: (3.43, 3.39), bar + 25 * MIN: (3.52, 3.45)}
    _run(_minutes(touches), {STOCH: _short(STOCH)})
    assert _booked() == [("SL", SL, -1.3)]
    assert said == [
        f"{COIN} {STOCH}: the {_when(bar)} candle held both the target and "
        f"the stop, and {missing} of the 30 minute(s) it ran with the order "
        f"open are not readable (a runner reads back {at.PAPER_MINUTES}) — "
        "booked as the stop, the candle's worst case."], said


@pytest.mark.parametrize("touches, line", [
    ({BOTH_BAR + 21 * MIN: (3.52, 3.45), BOTH_BAR + 25 * MIN: (3.43, 3.39)},
     " — its one-minute candles say SL came first."),
    ({BOTH_BAR + 21 * MIN: (3.52, 3.39)},
     f", and so did its {_when(BOTH_BAR + 21 * MIN)} minute, which cannot "
     "say which came first — booked as the stop, the worst case."),
], ids=["stop-first", "both-in-one-minute"])
def test_minutes_that_reach_the_stop_first_keep_the_stop(clock, said,
                                                         touches, line):
    """The minutes decide in BOTH directions, and both prices inside one
    minute is still the stop — Backtest v2's worst case, counted there as
    `unclear`.

    THE LINE SAYS WHICH. A tie inside one minute has no order: the stop is
    booked by the worst-case rule, so the Runner feed may not print "its
    one-minute candles say SL came first" for it — a first draft of this fix
    did, from this very candle (10:51pm, 3.52 to 3.39; docs/RCA.md
    RCA-2026-10-07-H)."""
    _run(_minutes(touches), {STOCH: _short(STOCH)})
    assert _booked() == [("SL", SL, -1.3)]
    assert said == [f"{COIN} {STOCH}: the {_when(BOTH_BAR)} candle held both "
                    f"the target and the stop{line}"], said


# 10:44:30pm: the 10:00pm candle's order, 14.5 minutes late — inside the
# 15-minute stale limit of a half-hour strategy — so the order went out
# halfway through the candle that then held both prices
LATE = BOTH_BAR + 14 * MIN + 30


@pytest.mark.parametrize("before, after, want", [
    ((3.43, 3.39), (3.52, 3.45), ("SL", SL, -1.3)),
    ((3.52, 3.45), (3.43, 3.39), ("TP", TP, 0.9)),
], ids=["a-target-print-before-the-order", "a-stop-print-before-the-order"])
def test_no_minute_before_the_order_decides(clock, before, after, want):
    """RCA-2026-09-12-A's rule holds inside the candle too: a print from
    BEFORE the order existed can neither win the trade nor lose it."""
    touches = {BOTH_BAR + 5 * MIN: before,       # 10:35pm: no order yet
               BOTH_BAR + 22 * MIN: after}       # 10:52pm
    pos = _short(STOCH, opened_at=LATE, entry_ts=BOTH_BAR - HALF)
    _run(_minutes(touches), {STOCH: pos})
    assert _booked() == [want]


def test_minutes_that_touch_neither_keep_the_stop_and_say_so(clock, said):
    """Both prices printed at 10:35pm, before the 10:44:30pm order: the
    candle holds both, and the 16 minutes it ran with the order open touch
    neither. Backtest v2 keeps its bar rule when a bar's minutes touch
    neither price (`_settle_fine` answers "NONE"), so the stop stands as the
    candle's worst case — and the feed says that, never that the minutes saw
    a stop."""
    touches = {BOTH_BAR + 5 * MIN: (3.52, 3.39)}     # 10:35pm: no order yet
    pos = _short(STOCH, opened_at=LATE, entry_ts=BOTH_BAR - HALF)
    _run(_minutes(touches), {STOCH: pos})
    assert _booked() == [("SL", SL, -1.3)]
    assert said == [
        f"{COIN} {STOCH}: the {_when(BOTH_BAR)} candle held both the target "
        "and the stop, but none of the 16 minute(s) it ran with the order "
        "open touched either — booked as the stop, the candle's worst "
        "case."], said


# --------------------------------------------------- one source of minutes
def test_the_feeds_own_minutes_settle_it_the_same_way(clock, monkeypatch):
    """A runner that stayed up but whose round never reached NVD between
    10:51pm and 11:00pm holds the minutes on its own socket: the settle reads
    them first, exactly like every practice exit, and asks MEXC for none."""
    truth = _minutes()
    feed = lp.PriceFeed()
    feed._connected, feed._last_msg_at = True, float(NOW)
    feed.track_minutes([COIN])
    for t in range(READ_FROM - MIN, NOW // MIN * MIN + 1, MIN):
        hi, lo = truth[t]
        feed._on_message({"channel": "push.kline", "symbol": COIN,
                          "data": {"symbol": COIN, "interval": "Min1", "t": t,
                                   "o": ENTRY, "c": ENTRY, "h": hi, "l": lo}})
    monkeypatch.setattr(lp, "FEED", feed)
    venue = _run(truth, {STOCH: _short(STOCH)})
    assert _booked() == [("TP", TP, 0.9)]
    assert "Min1" not in venue.asked, \
        "the feed held every minute and the room still asked MEXC"
    assert feed.status()["minutes"]["served"] >= 1


# ------------------------------------------------------ real money untouched
def test_a_real_money_position_is_never_settled_on_minutes(clock, said):
    """The real book's exit is MEXC's own resting bracket (rule 14). The
    candles only tell the runner to look; nothing may ask the minutes to
    re-decide a real trade — through `run_cycle`, so neither the live pass
    nor the practice pass can pick it up."""
    pos = dict(_short(STOCH), dry=False, position_id=1)
    at._write_json(at.SETTINGS_PATH, {
        "strategies": [STOCH], "strategy_coins": {STOCH: [COIN]},
        "strategy_books": {at.book_slot(STOCH, COIN): ["real"]},
        "margin": 5.0, "enabled": True, "dry_run": False})
    at._write_json(at.STATE_PATH, {
        at.state_key(COIN, False): {"step": 0,
                                    "last_ts": {"Min30": LAST_HALF},
                                    "position": pos}})
    venue = Venue(_minutes())
    at.run_cycle(fx=venue)
    assert "Min1" not in venue.asked
    assert [(r["why"], r["dry_run"]) for r in _exits()] == [("SL", False)]
    assert said == [] and venue.orders == []
