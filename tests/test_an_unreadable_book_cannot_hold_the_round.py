"""A coin whose order book cannot be read may not hold the whole round
(docs/RCA.md RCA-2026-10-07-I).

At `Oct 07, 2026 1:18am` this PC's network card dropped its link for 80
seconds. Three rooms were in the middle of a round, each on a coin with no
open trade — #55D32617 and #B2404C0B on FASTSTOCK, #4FC03172 on WDAYSTOCK —
and the cost check asked MEXC for that coin's order book once PER ARMED
STRATEGY: 125 of them on FASTSTOCK in #55D32617, each failed read about 3 s
(three tries, 1 s and 2 s apart). A failed read was never remembered inside
the round, every one of those strategies had already used its hourly log
line (12:33am-1:15am), so the Errors tab got 0 lines while the exit checks of
every coin after it waited.

The outage itself cost nothing — no price could be read anyway. The risk is
a coin whose book keeps failing while everything else works: ~6 minutes a
round on FASTSTOCK, every round, with at most one line per strategy an hour.

Now two failed reads of one coin's book in a row end the asking for the rest
of that round (ONE failure is still retried by the next strategy —
tests/test_one_read_per_coin_per_cycle.py holds that half), and the round
writes ONE line for the coin, with how many strategies it refused.

ONE TIMELINE: the candles, the open practice trade, the hourly log limit and
the cost of each failed read run on one fake clock, the one a running runner
sees. Driven through `run_cycle` inside `reads_once_per_cycle`, exactly the
way `run_forever` runs a round.
"""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pandas as pd
import pytest

from tests.test_auto_trader import FakeFx
from tradingagents import auto_trader as at, live_price, room_errors
from tradingagents.dataflows import mexc_futures as mexc

BOOKLESS = "FASTSTOCK_USDT"       # no open trade; its book cannot be read
HELD = "GPNSTOCK_USDT"            # holds a practice trade, scanned after it
_FIFTEEN = [k for k in at.STRATEGY_ORDER
            if at.STRATEGY_SPECS[k]["interval"] == "Min15"]
KEYS = _FIFTEEN[:20]              # armed on the coin whose book is down
HELD_KEY = _FIFTEEN[20]           # the open practice trade's own strategy
T0 = 1791350324                   # Oct 07, 2026 1:18am, second 44: the link drops
BAR = T0 // 900 * 900 - 900       # the 1:00am candle, the newest CLOSED one
OPENED = 1791348420               # Oct 07, 2026 12:47am, like #6B08FF64's GPNSTOCK pair
# what one failed read costs the round: three tries, 1 s and 2 s apart
READ_S = sum(mexc._PUBLIC_BACKOFF[:mexc._PUBLIC_RETRIES - 1])
DOWN = ("transport failure: <urlopen error [Errno 11001] getaddrinfo failed> "
        "after 3 attempts")
STEP = {"Min1": 60, "Min15": 900}


class Clock:
    def __init__(self, t):
        self.t = float(t)

    def __call__(self):
        return self.t


class Venue(FakeFx):
    """Candles of the asked size up to the clock (the forming one included,
    as MEXC sends it), a book that cannot be read for BOOKLESS while `down`,
    and a record of when each coin was asked for what."""

    def __init__(self, clock):
        super().__init__(None)
        self.clock, self.down = clock, True
        self.book_reads = {BOOKLESS: 0, HELD: 0}
        self.asked: list = []                     # (symbol, what, at)

    def klines(self, symbol, interval, limit):
        self.asked.append((symbol, interval, self.clock()))
        step = STEP[interval]
        last = int(self.clock()) // step * step
        opens = [last - step * i for i in range(limit)][::-1]
        px = 82.42 if symbol == HELD else 50.0    # GPNSTOCK traded 82.40-82.44
        return pd.DataFrame({"Date": pd.to_datetime(opens, unit="s"),
                             "Open": px, "High": px, "Low": px, "Close": px,
                             "Volume": 10.0})

    def contract_spec(self, symbol):
        return {"priceScale": 4, "contractSize": 1, "volUnit": 1, "minVol": 1,
                "maxVol": 25000, "maintenanceMarginRate": 0.005}

    def book_cost(self, symbol, notional_usd=200.0):
        self.book_reads[symbol] = self.book_reads.get(symbol, 0) + 1
        if symbol == BOOKLESS and self.down:
            self.clock.t += READ_S
            raise mexc.MexcFuturesError(DOWN)
        return super().book_cost(symbol, notional_usd)

    def last_price(self, symbol):
        self.asked.append((symbol, "last", self.clock()))
        return 82.42 if symbol == HELD else 50.0


def _settings():
    keys = KEYS + [HELD_KEY]
    return {"strategies": keys,
            "strategy_coins": {**{k: [BOOKLESS] for k in KEYS}, HELD_KEY: [HELD]},
            "strategy_books": {k: ["paper"] for k in keys},
            "margin": 5.0, "enabled": False, "dry_run": True}


def _held_trade():
    """A practice LONG on GPNSTOCK at 82.44, stop 81.95, target 83.10 —
    nothing between them is touched, so it must stay open and be CHECKED."""
    return {at.state_key(HELD, True, HELD_KEY): {
        "step": 0, "last_ts": {"Min15": BAR}, "position": {
            "side": 1, "vol": 1, "entry": 82.44, "tp": 83.10, "sl": 81.95,
            "margin": 5.0, "strategy": HELD_KEY,
            "entry_ts": OPENED // 900 * 900 - 900, "opened_at": OPENED,
            "dry": True, "bracket": True, "step": 0}}}


def _ledger():
    path = at.LEDGER_PATH
    return ([json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
            if path.exists() else [])


@pytest.fixture
def room(monkeypatch):
    clock = Clock(T0)
    monkeypatch.setattr(time, "time", clock)
    for name in ("_BAR_CACHE", "_GATE_CACHE", "_GATE_LOGGED", "_FUNDING_CACHE",
                 "_SAID", "_LAST_READING"):
        monkeypatch.setattr(at, name, {}, raising=False)
    # a feed that never connected: the REST minutes and the last price decide
    # the practice exit, as they did at 1:19am with the socket down
    monkeypatch.setattr(live_price, "FEED", live_price.PriceFeed())
    # every strategy on the coin had already written its hourly cost line —
    # that night between 12:33am and 1:15am
    for k in KEYS:
        at._GATE_LOGGED[(k, BOOKLESS, True)] = T0 - 600
    # Counted at the logger itself, not through caplog: another test in the
    # suite runs the module as __main__ and re-plumbs logging, so capture
    # depends on test order (tests/test_a_switched_off_practice_trade_is_finished.py).
    said: list = []
    real = at.logger.warning

    def warning(msg, *a, **k):
        said.append(str(msg) % a if a else str(msg))
        return real(msg, *a, **k)

    monkeypatch.setattr(at.logger, "warning", warning)
    at._write_json(at.SETTINGS_PATH, _settings())
    at._write_json(at.STATE_PATH, _held_trade())
    yield SimpleNamespace(clock=clock, venue=Venue(clock), said=said)
    assert at._CYCLE_READS is None, "nothing may outlive a round"


def _round(room):
    """One round, the way `run_forever` runs it."""
    with at.reads_once_per_cycle():
        at.run_cycle(fx=room.venue)


def _book_lines(room):
    return [m for m in room.said
            if BOOKLESS in m and "order book could not be read" in m]


def test_a_coin_whose_book_cannot_be_read_does_not_hold_the_round(room):
    _round(room)
    v = room.venue
    assert v.book_reads[BOOKLESS] == 2, \
        f"MEXC asked {v.book_reads[BOOKLESS]} times for one coin's book in one round"
    assert not [r for r in _ledger() if r.get("action") == "enter"], \
        "an unreadable book is never permission to trade (rule 12)"
    assert v.orders == []
    state = at.load_state()
    for k in KEYS:
        st = state[at.state_key(BOOKLESS, True, k)]
        # NOT marked seen: the next round tries the candle again...
        assert st["last_ts"].get("Min15", 0) < BAR, k
        # ...and every strategy's refused candle is still COUNTED — the line
        # is per coin, the count stays per strategy (RCA-2026-10-02-C)
        assert st["gate_pending"][k]["bars"] == [BAR], k
        assert st["gate_pending"][k]["unread"] == [BAR], k
    # the coin after it had its exit checked in the SAME round, after two
    # failed reads (6 s) — not after twenty (60 s)
    checked = [t for s, what, t in v.asked if s == HELD and what == "Min1"]
    assert checked, "the practice trade's exit was never checked this round"
    assert checked[0] - T0 <= 2 * READ_S, \
        f"GPNSTOCK's exit check waited {checked[0] - T0:.0f} s behind FASTSTOCK's book"
    assert state[at.state_key(HELD, True, HELD_KEY)]["position"], \
        "nothing was crossed, so the trade stays open"
    # ONE line for the coin, never one per strategy, and its number is the
    # strategies the check really refused
    lines = _book_lines(room)
    assert len(lines) == 1, lines
    assert "refused 20 practice strategies on it this round" in lines[0], lines[0]
    assert DOWN in lines[0]
    assert room_errors.classify("WARNING", lines[0]) == ("error", "book_unreadable"), \
        "the Errors tab must file it under 'Order book could not be read'"
    # an unknown is still never remembered past the round (rule 12)
    assert not [k for k in at._GATE_CACHE if k[1] == BOOKLESS]


def test_the_next_round_asks_again(room):
    _round(room)
    asked = room.venue.book_reads[BOOKLESS]
    room.venue.down = False
    room.clock.t = T0 + 90            # 1:20am: the link came back at second 4
    _round(room)
    assert room.venue.book_reads[BOOKLESS] > asked, \
        "a failure remembered past its round would refuse the coin for good"
    assert len(_book_lines(room)) == 1, "a book that was read says nothing"
    state = at.load_state()
    judged = [k for k in KEYS
              if state[at.state_key(BOOKLESS, True, k)]["gate_pending"][k]["unread"] == []]
    assert judged, "no strategy was judged on the book once it could be read"


def test_one_failure_is_retried_two_end_the_asking_and_a_signal_reads_fresh(room):
    v = room.venue
    with at.reads_once_per_cycle():
        got = [at._edge_gate_cached(k, BOOKLESS, 5.0, fx=v) for k in KEYS[:5]]
        assert v.book_reads[BOOKLESS] == 2, "the second strategy still asks"
        assert all(g["verdict"] == "unknown" and DOWN in g["reason"] for g in got)
        # the signal's own last look always asks MEXC, memory or not
        at._entry_gate(KEYS[0], BOOKLESS, 5.0, fx=v, side=1)
        assert v.book_reads[BOOKLESS] == 3
        # a book read at a signal is a reading: the screen uses it, and the
        # coin's failures are forgotten
        v.down = False
        assert at._entry_gate(KEYS[1], BOOKLESS, 5.0, fx=v, side=1)["verdict"] != "unknown"
        assert at._edge_gate_cached(KEYS[2], BOOKLESS, 5.0, fx=v)["verdict"] != "unknown"
        assert v.book_reads[BOOKLESS] == 4


def test_a_round_that_dies_part_way_leaves_no_memory_behind(room, monkeypatch):
    """The round's last step, the state save, is where a runner has really
    died — PermissionError [WinError 5] on the state file swap, nine
    tracebacks in the room logs, #55D32617's at Oct 01, 2026 5:10pm. A failure
    count that outlived such a round would refuse the coin without ever
    asking MEXC again."""
    real = at.save_state

    def refused(*a, **k):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(at, "save_state", refused)
    with pytest.raises(PermissionError):
        _round(room)
    assert at._CYCLE_READS is None
    first = room.venue.book_reads[BOOKLESS]
    monkeypatch.setattr(at, "save_state", real)
    room.clock.t += 90                # the book is still down
    _round(room)
    again = room.venue.book_reads[BOOKLESS] - first
    assert again == 2, f"the next round asked MEXC {again} time(s) for the book"
