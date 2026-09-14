"""The demo book fills on a PRINT, not on a poll.

Operator, `Sep 14, 2026`: *"is it possible to make demo realtime? like watch
the realtime price of the coin"*.

What it cost to be late. NGAS `JKTTD9GC`, opened on BOTH books at
`Sep 10, 2026 2:00am` at 2.874. MEXC closed the live copy by hand at
`Sep 13, 2026 3:31pm` for +0.12. Price first touched the demo target of
2.96022 at `Sep 13, 2026 10:13pm` and the demo booked it at `10:14pm` —
a minute late, because the paper exit check ran every 60 seconds against
closed one-minute bars plus one REST price call.

Polling harder is not available. On `Aug 19, 2026` a 5-second poll produced
**77 scans in one minute**, **166** `code=510` refusals, **668** paper exit
checks that could not read a price at all, and a 106 MB log.

So `live_price.PriceFeed` subscribes to MEXC's public futures stream and
records every print. Measured on the operator's own coins, 30 seconds, four
contracts: **58 messages**, 12-13 ticks per coin, no reconnects.

The feed is a RECORDER. Every barrier rule stays in `_dry_fill`, which the
backtest and both books already share, and the feed sits between the closed
one-minute bars (older ground, authoritative) and the last-price fallback.

These tests pin the five properties that make it safe to have at all:

1. it can only make the demo book more right — every failure falls back;
2. it never touches the live book;
3. it never reads a print from before the order existed (RCA-2026-09-12-A);
4. it never raises into the runner's cycle;
5. it opens no socket under test.
"""
from __future__ import annotations

import time

import pandas as pd
import pytest

from tradingagents import auto_trader as at, live_price as lp

COIN = "NGAS_USDT"
KEY = "ultosc_1h_sl3tp3"
ENTRY = 2.874
TP = 2.96022
SL = 2.78778

HOUR = 3600
NOW = int(time.time())
# A LIVE FEED ONLY HOLDS MINUTES. These constants sit on the timeline a
# running runner actually sees — the trade opened ten minutes ago and the
# ticks are seconds old — because a fixture whose clock disagrees with its
# own data is how RCA-2026-09-12-A hid for eight days (CLAUDE.md, "A test of
# anything time-dependent must place its candles and its position on ONE
# timeline").
OPENED_AT = NOW - 600
SIG_BAR = OPENED_AT - HOUR - 11


# ------------------------------------------------------------------ helpers
def _feed(ticks=(), *, connected=True, fresh=True):
    """A feed with canned ticks and no socket. `_on_message` is the real
    parser, so these tests exercise MEXC's actual payload shapes."""
    f = lp.PriceFeed()
    f._connected = connected
    f._last_msg_at = time.time() if fresh else time.time() - 10 * lp.STALE_S
    for ts, px in ticks:
        f._on_message({"channel": "push.deal", "symbol": COIN,
                       "data": [{"p": px, "v": 1, "t": int(ts * 1000)}]})
    return f


def _pos(**kw):
    p = {"side": 1, "vol": 69, "entry": ENTRY, "tp": TP, "sl": SL,
         "margin": 1.0, "strategy": KEY, "entry_ts": SIG_BAR,
         "opened_at": OPENED_AT, "dry": True, "bracket": True, "step": 0,
         "rt_cost": 0.0, "trade_id": "JKTTD9GC"}
    p.update(kw)
    return p


def _bars(n=240, high=ENTRY, low=ENTRY, bar=HOUR):
    """Benign hourly history — nothing here may cross a barrier, so only the
    feed can decide these tests."""
    start = SIG_BAR - (n - 3) * bar
    ts = [start + i * bar for i in range(n)]
    return pd.DataFrame({"Date": pd.to_datetime(ts, unit="s"),
                         "Open": [ENTRY] * n, "High": [high] * n,
                         "Low": [low] * n, "Close": [ENTRY] * n,
                         "Volume": [1.0] * n})


def _minutes(n=120, high=ENTRY, low=ENTRY):
    ts = [SIG_BAR + i * 60 for i in range(n)]
    return pd.DataFrame({"Date": pd.to_datetime(ts, unit="s"),
                         "Open": [ENTRY] * n, "High": [high] * n,
                         "Low": [low] * n, "Close": [ENTRY] * n,
                         "Volume": [1.0] * n})


class Fx:
    SIDE_OPEN_LONG, SIDE_CLOSE_SHORT = 1, 2
    SIDE_OPEN_SHORT, SIDE_CLOSE_LONG = 3, 4
    max_vol = 0

    def __init__(self, minutes=None, hours=None, last=ENTRY):
        self.minutes = _minutes() if minutes is None else minutes
        self.hours = _bars() if hours is None else hours
        self._last = last
        self.orders: list = []
        self.stops: list = []
        self.closed: list = []

    def klines(self, symbol, interval, limit):
        return (self.minutes if interval == "Min1" else self.hours).copy()

    def contracts_for(self, symbol, notional, price=None):
        return int(notional)

    def contract_spec(self, symbol):
        return {"priceScale": 5, "maxVol": 0}

    def book_cost(self, symbol, notional_usd=200.0):
        return {"spread": 0.0002, "slippage": 0.0002, "book_exhausted": False}

    def position_history(self, symbol=None, page_size=20):
        return []

    def open_positions(self, symbol=None):
        return getattr(self, "positions", [])

    def last_price(self, symbol):
        return float(self._last)

    def submit(self, symbol, side, vol, *, leverage, dry_run=True):
        self.orders.append((symbol, side, vol, dry_run))
        self.closed.append(symbol)
        return {"dry_run": dry_run}

    def place_position_stop(self, *a, **kw):
        self.stops.append(kw)
        return {"dry_run": True}

    def verify_position_stop(self, symbol, position_id):
        return {"protected": True}


@pytest.fixture
def sandbox(monkeypatch):
    for name in ("_BAR_CACHE", "_GATE_CACHE", "_GATE_LOGGED",
                 "_CYCLE_PRICES", "_CYCLE_GATES"):
        cache = getattr(at, name, None)
        if hasattr(cache, "clear"):
            cache.clear()
    monkeypatch.setattr(at, "MAX_SIGNAL_AGE_FRACTION", float("inf"))


def _cycle(fx, pos, feed, monkeypatch, *, dry=True):
    monkeypatch.setattr(lp, "FEED", feed)
    slot = at.state_key(COIN, dry, KEY) if dry else at.state_key(COIN, False)
    state = {slot: {"step": 0, "last_ts": {}, "position": pos}}
    at.process_symbol(COIN, {"strategies": [KEY], "coins": [COIN],
                             "margin": 1.0},
                      state, fx=fx, dry=dry, tripped=frozenset({KEY}))
    return state[slot]


# --------------------------------------------------------------- it works
def test_a_print_through_the_target_closes_the_demo_trade(sandbox, monkeypatch):
    """The NGAS case: no closed bar has crossed, one tick has."""
    feed = _feed([(OPENED_AT + 120, 2.9612)])       # above the 2.96022 target
    slot = _cycle(Fx(), _pos(), feed, monkeypatch)
    assert slot["position"] is None, \
        "a print through the target must fill the demo trade"


def test_a_print_through_the_stop_closes_it_too(sandbox, monkeypatch):
    feed = _feed([(OPENED_AT + 120, 2.7801)])       # below the 2.78778 stop
    slot = _cycle(Fx(), _pos(), feed, monkeypatch)
    assert slot["position"] is None


def test_a_wick_that_retraces_is_still_a_fill(sandbox, monkeypatch):
    """What the 60-second snapshot missed: price stabs the barrier and comes
    straight back, so the LAST price shows nothing wrong."""
    feed = _feed([(OPENED_AT + 60, ENTRY),
                  (OPENED_AT + 61, 2.9700),        # the wick
                  (OPENED_AT + 62, ENTRY)])
    fx = Fx(last=ENTRY)                            # the fallback sees nothing
    slot = _cycle(fx, _pos(), feed, monkeypatch)
    assert slot["position"] is None, \
        "a real bracket fills on the wick; so must the demo"


def test_price_inside_the_barriers_leaves_it_open(sandbox, monkeypatch):
    feed = _feed([(OPENED_AT + 60, 2.90), (OPENED_AT + 90, 2.88)])
    slot = _cycle(Fx(), _pos(), feed, monkeypatch)
    assert slot["position"] is not None


# ------------------------------------------------- it can only help, never hurt
def test_a_stale_feed_changes_nothing(sandbox, monkeypatch):
    """Stale means "I cannot help", never "nothing happened"."""
    feed = _feed([(OPENED_AT + 60, 2.9700)], fresh=False)
    assert feed.ticks_since(COIN, OPENED_AT) is None
    slot = _cycle(Fx(), _pos(), feed, monkeypatch)
    assert slot["position"] is not None, \
        "a stale feed must fall back, not decide"


def test_a_disconnected_feed_changes_nothing(sandbox, monkeypatch):
    feed = _feed([(OPENED_AT + 60, 2.9700)], connected=False)
    assert feed.ticks_since(COIN, OPENED_AT) is None
    slot = _cycle(Fx(), _pos(), feed, monkeypatch)
    assert slot["position"] is not None


def test_a_feed_that_raises_never_reaches_the_cycle(sandbox, monkeypatch):
    """Rule 4. The runner manages real money; a price feed may not stop it."""
    class Exploding:
        def ticks_since(self, *a, **k):
            raise RuntimeError("socket gone")

    slot = _cycle(Fx(), _pos(), Exploding(), monkeypatch)
    assert slot["position"] is not None


def test_the_closed_bars_still_win_when_they_crossed_first(sandbox, monkeypatch):
    """Precedence. A barrier crossed hours ago is the real exit; a tick from
    a minute ago must not overwrite it with the other outcome."""
    fx = Fx(minutes=_minutes(low=2.70))            # the STOP, hours of it
    feed = _feed([(OPENED_AT + 60, 2.9700)])       # the target, just now
    slot = _cycle(fx, _pos(), feed, monkeypatch)
    assert slot["position"] is None
    import json
    rows = [json.loads(x) for x in
            at.LEDGER_PATH.read_text(encoding="utf-8").strip().splitlines()]
    assert rows[-1]["why"] == "SL", \
        "the older closed-bar crossing decides, not the newer tick"


# -------------------------------------------------------- it never invents
def test_a_print_from_before_the_order_is_not_a_fill(sandbox, monkeypatch):
    """RCA-2026-09-12-A, in its tick form. The demo book has already booked a
    win on price from an hour before the trade; the feed may not repeat it."""
    feed = _feed([(OPENED_AT - 300, 2.9900),        # five minutes too early
                  (OPENED_AT - 1, 2.9900)])         # one second too early
    assert feed.ticks_since(COIN, OPENED_AT) is None
    slot = _cycle(Fx(), _pos(), feed, monkeypatch)
    assert slot["position"] is not None


def test_a_tick_exactly_at_the_order_is_refused(sandbox, monkeypatch):
    """Strictly after, never at: the order may not have been resting for the
    print that carries its own timestamp."""
    feed = _feed([(OPENED_AT, 2.9900)])
    assert feed.ticks_since(COIN, OPENED_AT) is None


def test_a_timestamp_we_cannot_believe_is_dropped_not_relabelled(sandbox):
    """The bug the harddev loop caught before this shipped.

    The first version stamped an implausible tick with `now`. That is
    manufacturing evidence: a print from BEFORE the order would have been
    relabelled into the window AFTER it and filled the trade — exactly
    RCA-2026-09-12-A, rebuilt out of ticks — and a tick older than `KEEP_S`
    would never have aged out. Dropping is the only safe answer.
    """
    f = _feed()
    f._on_message({"channel": "push.deal", "symbol": COIN,           # future
                   "data": [{"p": 2.99, "t": int((time.time() + 3600) * 1000)}]})
    f._on_message({"channel": "push.deal", "symbol": COIN,           # ancient
                   "data": [{"p": 9.99,
                             "t": int((time.time() - lp.KEEP_S - 60) * 1000)}]})
    assert f.ticks_since(COIN, 0) is None,         "an unbelievable timestamp must be dropped, never restamped as now"
    # ...while a message with NO timestamp is fairly stamped on arrival
    f._on_message({"channel": "push.ticker", "symbol": COIN,
                   "data": {"lastPrice": 3.0}})
    rows = f.ticks_since(COIN, 0)
    assert rows and abs(rows[-1][0] - time.time()) < 5


# ------------------------------------------------------ it is demo-only
def test_the_live_book_never_exits_on_the_feed(sandbox, monkeypatch):
    """Rule 2, and CLAUDE.md rule 14: a real exit is the exchange's bracket.
    Price prints through the target, MEXC still reports the position open —
    nothing here may book that as a fill."""
    fx = Fx()
    fx.positions = [{"symbol": COIN, "holdVol": 69}]
    feed = _feed([(OPENED_AT + 60, 2.9700)])
    pos = _pos(dry=False, position_id=1, bracket=True)
    slot = _cycle(fx, pos, feed, monkeypatch, dry=False)
    assert slot["position"] is not None, \
        "the exchange is the source of truth for a live position"


def test_only_coins_holding_a_demo_position_are_listened_to(sandbox, monkeypatch):
    """Subscribing to all 993 contracts to serve a handful of demo trades is
    traffic nobody asked for — and a live-only coin is none of the feed's
    business."""
    tracked: list = []

    class Spy:
        def track(self, coins):
            tracked.append(set(coins))

        def start(self):
            return False

        def ticks_since(self, *a, **k):
            return None

    monkeypatch.setattr(lp, "FEED", Spy())
    at._feed_follow({
        at.state_key(COIN, True, KEY): {"position": _pos()},
        at.state_key("KITE_USDT", True, KEY): {"position": None},
        "PSXSTOCK_USDT": {"position": _pos(dry=False)},
    })
    assert tracked == [{COIN}]


def test_following_the_book_never_breaks_the_cycle(sandbox, monkeypatch):
    class Exploding:
        def track(self, coins):
            raise RuntimeError("no network")

        def start(self):
            raise RuntimeError("no network")

    monkeypatch.setattr(lp, "FEED", Exploding())
    at._feed_follow({at.state_key(COIN, True, KEY): {"position": _pos()}})


# ------------------------------------------------------------- the feed itself
def test_no_socket_is_ever_opened_under_test():
    """Rule 5, the same guard `live_ingest.ensure()` carries."""
    import os

    assert os.environ.get("PYTEST_CURRENT_TEST")
    assert lp.PriceFeed().start() is False


def test_both_of_mexcs_shapes_are_read():
    """`push.deal` is a LIST of trades, `push.ticker` a single dict — the
    first probe crashed on exactly that difference."""
    f = _feed()
    f._on_message({"channel": "push.deal", "symbol": COIN,
                   "data": [{"p": 3.01, "t": int(time.time() * 1000)},
                            {"p": 3.02, "t": int(time.time() * 1000)}]})
    f._on_message({"channel": "push.ticker", "symbol": COIN,
                   "data": {"lastPrice": 3.03}, "ts": int(time.time() * 1000)})
    assert f.extremes_since(COIN, 0) == (3.03, 3.01)


def test_rubbish_in_a_message_is_dropped_not_recorded():
    """MEXC answers a rate limit with a 200 and no data; a price of 0 is below
    every stop and above no target. It must never reach the deque."""
    f = _feed()
    for bad in ({"p": 0}, {"p": None}, {"p": "abc"}, {}):
        f._on_message({"channel": "push.deal", "symbol": COIN, "data": [bad]})
    f._on_message({"channel": "push.ticker", "symbol": COIN, "data": {}})
    assert f.ticks_since(COIN, 0) is None


def test_history_is_bounded_by_age_and_count():
    f = _feed()
    old = time.time() - lp.KEEP_S - 60
    f._on_message({"channel": "push.deal", "symbol": COIN,
                   "data": [{"p": 9.99, "t": int(old * 1000)}]})
    f._on_message({"channel": "push.deal", "symbol": COIN,
                   "data": [{"p": 3.00, "t": int(time.time() * 1000)}]})
    rows = f.ticks_since(COIN, 0)
    assert rows and all(p != 9.99 for _t, p in rows), \
        "a tick older than KEEP_S must be pruned"


def test_status_says_what_it_is_doing():
    f = _feed([(time.time(), 3.0)])
    s = f.status()
    for field in ("connected", "stale", "tracking", "subscribed", "ticks",
                  "messages", "seconds_since_message", "last_error"):
        assert field in s, field
    assert s["ticks"][COIN] == 1
