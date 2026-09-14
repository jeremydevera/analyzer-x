"""The runner waits for the venue to speak. It does not poll a clock.

Operator, `Sep 14, 2026`: *"there should be no refresh from now on i want demo
and live to be realtime meaning the formular to open a trade and close a trade
should be realtime websocket"*.

What it replaced: `main()` slept `next_sleep_seconds()` and then went looking.
Every entry waited for a timer to expire near the bar boundary and then pulled
candles over REST; every demo exit waited up to 60 seconds; a live fill at MEXC
was learned whenever the cycle next happened to ask.

Three pushes now wake the cycle, all on one socket to
`wss://contract.mexc.com/edge`, all measured against the real venue before
they were relied on:

| push | what it means | measured |
|---|---|---|
| `push.kline` | a bar closed, an entry may be due | 14 pushes / 72s, 2 coins |
| `push.deal` / `push.ticker` | a print crossed a demo barrier | 12-13 ticks / coin / 30s |
| `push.personal.*` | a LIVE position changed at MEXC | `rs.login: success`, then pushes for position 1494058536 |

Two things deliberately did NOT change, and both are load-bearing:

* **An entry still reads a CLOSED candle.** The push is the trigger; the
  signal is the same bar the backtest measured. Evaluating a half-formed
  candle on every tick would make the runner trade a strategy no grid in this
  repo has ever tested.
* **The timer survives as a BACKSTOP.** A feed that is down, logged out, or
  simply quiet on an illiquid contract must never be able to stop the runner
  trading. Every decision is still made from the exchange's own data when the
  backstop fires.

And a floor the websocket makes newly necessary: `MIN_CYCLE_GAP_S`. A burst of
ticks that each ran a cycle would rebuild the `Aug 19, 2026` failure — 77
scans in one minute, 166 `code=510 Requests are too frequent` refusals, 668
exit checks that could not read a price at all — with a socket in place of a
timer.
"""
from __future__ import annotations

import time

import pytest

from tradingagents import auto_trader as at, live_price as lp

COIN = "NGAS_USDT"
KEY = "ultosc_1h_sl3tp3"
SLOT = at.state_key(COIN, True, KEY)


def _feed():
    f = lp.PriceFeed()
    f._connected = True
    f._last_msg_at = time.time()
    return f


def _kline(f, t, interval="Min60", symbol=COIN):
    f._on_message({"channel": "push.kline", "symbol": symbol,
                   "data": {"symbol": symbol, "interval": interval, "t": t,
                            "o": 3.0, "c": 3.0, "h": 3.0, "l": 3.0}})


def _deal(f, price, ts=None, symbol=COIN):
    f._on_message({"channel": "push.deal", "symbol": symbol,
                   "data": [{"p": price, "t": int((ts or time.time()) * 1000)}]})


# ------------------------------------------------------- entries: the candle
def test_a_closed_candle_wakes_the_runner():
    """`t` moving on is the only signal MEXC gives that a bar is final."""
    f = _feed()
    _kline(f, 1_789_380_000)
    assert not f.wake.is_set(), "the FIRST push is only a baseline"
    assert f.drain_closed_bars() == set()

    _kline(f, 1_789_383_600)                     # the next hour opened
    assert f.wake.is_set()
    assert f.drain_closed_bars() == {(COIN, "Min60")}


def test_the_same_bar_pushed_again_is_not_a_close():
    """A forming bar is pushed over and over with `t` fixed at its open."""
    f = _feed()
    _kline(f, 1_789_380_000)
    f.wake.clear()
    for _ in range(5):
        _kline(f, 1_789_380_000)
    assert not f.wake.is_set()
    assert f.drain_closed_bars() == set()


def test_a_bar_that_goes_BACKWARDS_is_not_a_close():
    """Out-of-order delivery must not manufacture an entry check."""
    f = _feed()
    _kline(f, 1_789_383_600)
    f.wake.clear()
    _kline(f, 1_789_380_000)
    assert not f.wake.is_set()


def test_each_timeframe_closes_on_its_own():
    f = _feed()
    _kline(f, 1_789_380_000, "Min15")
    _kline(f, 1_789_380_000, "Min60")
    f.wake.clear()
    _kline(f, 1_789_380_900, "Min15")
    assert f.drain_closed_bars() == {(COIN, "Min15")}


# -------------------------------------------------------- exits: the print
def test_a_print_through_an_armed_barrier_wakes_the_runner():
    f = _feed()
    since = time.time() - 60
    f.arm(SLOT, COIN, 1, tp=3.10, sl=2.90, since_ts=since)
    _deal(f, 3.00)
    assert not f.wake.is_set(), "inside the barriers is not an event"
    _deal(f, 3.11)
    assert f.wake.is_set()
    hits = f.drain_hits()
    assert hits[SLOT][0] == "TP"


def test_a_short_is_read_the_other_way_up():
    f = _feed()
    f.arm(SLOT, COIN, -1, tp=2.90, sl=3.10, since_ts=time.time() - 60)
    _deal(f, 3.11)
    assert f.drain_hits()[SLOT][0] == "SL"


def test_a_print_from_before_the_order_never_triggers():
    """The same floor as everywhere else (RCA-2026-09-12-A)."""
    f = _feed()
    since = time.time() - 60
    f.arm(SLOT, COIN, 1, tp=3.10, sl=2.90, since_ts=since)
    _deal(f, 3.50, ts=since - 30)
    assert not f.wake.is_set()
    assert f.drain_hits() == {}


def test_one_crossing_does_not_wake_every_cycle_for_ever():
    f = _feed()
    f.arm(SLOT, COIN, 1, tp=3.10, sl=2.90, since_ts=time.time() - 60)
    _deal(f, 3.11)
    f.wake.clear()
    for _ in range(10):
        _deal(f, 3.12)
    assert not f.wake.is_set(), \
        "the runner has already been told; repeating it is a spin"


def test_a_stale_hit_cannot_silence_a_NEW_trade_on_the_same_slot():
    """Found by the harddev loop. The slot is reused by the next trade, and
    a hit left over from the last one would mute it."""
    f = _feed()
    f.arm(SLOT, COIN, 1, tp=3.10, sl=2.90, since_ts=time.time() - 60)
    _deal(f, 3.11)
    assert f._hits.get(SLOT)
    f.arm(SLOT, COIN, -1, tp=2.50, sl=3.50, since_ts=time.time() - 1)
    assert not f._hits.get(SLOT), "re-arming with new barriers clears the hit"


def test_re_arming_the_SAME_trade_keeps_its_hit():
    """`_feed_follow` re-arms every cycle; that must not undo the mute."""
    f = _feed()
    args = dict(tp=3.10, sl=2.90, since_ts=time.time() - 60)
    f.arm(SLOT, COIN, 1, **args)
    _deal(f, 3.11)
    f.arm(SLOT, COIN, 1, **args)
    assert f._hits.get(SLOT)


def test_a_closed_position_stops_being_watched():
    f = _feed()
    f.arm(SLOT, COIN, 1, tp=3.10, sl=2.90, since_ts=time.time() - 60)
    f.keep_only([])
    _deal(f, 3.11)
    assert not f.wake.is_set()
    assert f.drain_hits() == {}


# ------------------------------------------------------------- live fills
def test_a_live_position_change_at_mexc_wakes_the_runner():
    f = _feed()
    f._on_message({"channel": "push.personal.position",
                   "data": {"positionId": 1494058536, "symbol": COIN}})
    assert f.wake.is_set()
    assert f.drain_personal()[0]["channel"] == "push.personal.position"


def test_liquidation_risk_is_recorded_but_does_not_spin_the_runner():
    """MEXC pushes this every few seconds while a position is open — it is
    news to keep, not a reason to run a cycle."""
    f = _feed()
    for _ in range(5):
        f._on_message({"channel": "push.personal.liquidate.risk",
                       "data": {"positionId": 1, "marginRatio": 0.14}})
    assert not f.wake.is_set()
    assert len(f.drain_personal()) == 5


def test_the_login_uses_the_projects_one_signer():
    """A second copy of the signing scheme is a copy that drifts."""
    import inspect

    src = inspect.getsource(lp.PriceFeed._sync_subs)
    assert "from tradingagents.dataflows.mexc_futures import sign" in src
    assert "hmac" not in src, "sign() is the only place that knows the scheme"


def test_a_refused_login_leaves_the_public_feed_working():
    f = _feed()
    f._on_message({"channel": "rs.login", "data": "failure"})
    assert f._logged_in is False
    _deal(f, 3.00)
    assert f.ticks_since(COIN, 0), "prices keep arriving without a login"


def test_credentials_are_never_in_the_status():
    f = _feed()
    f.use_credentials("MY_KEY", "MY_SECRET")
    blob = repr(f.status())
    assert "MY_KEY" not in blob and "MY_SECRET" not in blob


# ------------------------------------------------------------- the waiting
def test_the_cycle_waits_for_the_feed_not_the_clock(monkeypatch):
    feed = _feed()
    monkeypatch.setattr(lp, "FEED", feed)
    monkeypatch.setattr(at, "_LAST_CYCLE_AT", [0.0])
    feed.wake.set()
    t0 = time.time()
    why = at._wait_for_something(60.0)
    assert why == "feed"
    assert time.time() - t0 < 5, "an event must not wait out the timer"
    assert not feed.wake.is_set(), "the runner clears it, or it fires for ever"


def test_the_timer_is_still_the_backstop(monkeypatch):
    """A quiet or dead feed must never stop the runner trading."""
    feed = _feed()
    monkeypatch.setattr(lp, "FEED", feed)
    monkeypatch.setattr(at, "_LAST_CYCLE_AT", [0.0])
    assert at._wait_for_something(0.5) == "timer"


def test_two_cycles_are_never_closer_than_the_floor(monkeypatch):
    """Without this a burst of ticks is the Aug 19, 2026 rate-limit failure
    with a socket in place of a timer."""
    feed = _feed()
    monkeypatch.setattr(lp, "FEED", feed)
    monkeypatch.setattr(at, "_LAST_CYCLE_AT", [time.time()])
    feed.wake.set()
    t0 = time.time()
    at._wait_for_something(60.0)
    assert time.time() - t0 >= at.MIN_CYCLE_GAP_S - 0.3


def test_a_hundred_events_are_one_cycle(monkeypatch):
    """One Event, however many pushes land against it."""
    feed = _feed()
    feed.arm(SLOT, COIN, 1, tp=3.10, sl=2.90, since_ts=time.time() - 60)
    for i in range(100):
        _kline(feed, 1_789_380_000 + i * 3600)
    monkeypatch.setattr(lp, "FEED", feed)
    monkeypatch.setattr(at, "_LAST_CYCLE_AT", [0.0])
    assert at._wait_for_something(60.0) == "feed"
    assert not feed.wake.is_set()


def test_a_stop_request_is_not_ignored_while_waiting(monkeypatch):
    feed = _feed()
    monkeypatch.setattr(lp, "FEED", feed)
    monkeypatch.setattr(at, "_LAST_CYCLE_AT", [0.0])
    t0 = time.time()
    at._wait_for_something(60.0, {"flag": True})
    assert time.time() - t0 < 5, "the operator stopping the runner wins"


# ------------------------------------------------------- what it subscribes to
def test_the_runner_asks_for_every_armed_timeframe(monkeypatch, tmp_path):
    """Entries can only be push-driven on bars the feed is listening to."""
    seen: dict = {}

    class Spy:
        def track(self, coins):
            seen["coins"] = set(coins)

        def track_klines(self, pairs):
            seen["klines"] = set(pairs)

        def arm(self, slot, sym, side, tp, sl, since):
            seen.setdefault("armed", []).append((slot, sym, side, since))

        def keep_only(self, keys):
            seen["kept"] = set(keys)

        def use_credentials(self, k, s):
            seen["creds"] = True

        def start(self):
            return False

    monkeypatch.setattr(lp, "FEED", Spy())
    monkeypatch.setattr(at, "SETTINGS_PATH", tmp_path / "s.json")
    at.SETTINGS_PATH.write_text(
        '{"strategies": ["%s"], "coins": ["%s"], "margin": 1.0,'
        ' "strategy_books": {"%s": ["paper"]},'
        ' "strategy_coins": {"%s": ["%s"]}}' % (KEY, COIN, KEY, KEY, COIN),
        encoding="utf-8")
    pos = {"side": 1, "entry": 3.0, "tp": 3.1, "sl": 2.9, "dry": True,
           "strategy": KEY, "entry_ts": 1, "opened_at": 1_789_000_000}
    at._feed_follow({SLOT: {"position": pos}})

    assert seen["coins"] == {COIN}
    assert seen["klines"] == {(COIN, at.STRATEGY_SPECS[KEY]["interval"])}
    assert seen["armed"] and seen["armed"][0][0] == SLOT
    assert seen["armed"][0][3] == 1_789_000_000, \
        "armed on the ORDER's time, not the signal candle's"
    assert seen["kept"] == {SLOT}
    assert "creds" not in seen, \
        "a paper-only book has no live fills to be told about"


def test_a_wake_storm_says_so_out_loud(monkeypatch, caplog):
    """A websocket cannot be rate limited; the CYCLE it wakes can. The floor
    caps the rate, and this is the alarm if anything ever pushes against it."""
    import logging

    monkeypatch.setattr(at, "_WAKES", [])
    at._say_once.__globals__.get("_SAID", {}).clear() if hasattr(
        at._say_once, "__globals__") else None
    with caplog.at_level(logging.WARNING, logger=at.logger.name):
        for _ in range(at.WAKE_WARN_PER_MIN):
            at._note_wake()
    assert any("woke the runner" in r.getMessage() for r in caplog.records), \
        "a storm must be visible, not just survived"


def test_a_quiet_minute_never_warns(monkeypatch, caplog):
    import logging

    monkeypatch.setattr(at, "_WAKES", [])
    with caplog.at_level(logging.WARNING, logger=at.logger.name):
        for _ in range(3):
            at._note_wake()
    assert not [r for r in caplog.records if "woke the runner" in r.getMessage()]


def test_a_feed_with_no_wake_degrades_to_the_timer(monkeypatch):
    """Rule 4 applied to the waiter itself: a feed double, an old pickle, or
    no feed at all must not raise into the runner's loop."""
    class Useless:
        pass

    monkeypatch.setattr(lp, "FEED", Useless())
    monkeypatch.setattr(at, "_LAST_CYCLE_AT", [0.0])
    assert at._wait_for_something(0.3) == "timer"
