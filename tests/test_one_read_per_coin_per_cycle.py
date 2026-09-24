"""One order-book read and one price read per COIN per cycle (Sep 24, 2026).

The operator's Sep 24 deploy arms 537 practice slots on 64 coins — 135 on
GPNSTOCK. The screening gate read the order book once per SLOT every five
minutes and the practice exit read the last price once per open SLOT every
cycle: ~107 identical depth reads a minute on a single thread, against a
venue that has refused this runner for going too fast at 10-26 coins
(code 510, Sep 15-16, 2026). Inside the runner's loop both are now read once
per coin; the fresh read at a signal is never shared; outside the loop
nothing changes at all.
"""
from __future__ import annotations

import inspect
import json

import pytest

from tradingagents import api, auto_trader as at
from tests.test_auto_trader import FakeFx, _bars

COIN = "GPNSTOCK_USDT"
KEYS = ["keltner_30m_sl2tp2", "stoch14_30m_sl2tp2", "vwaprev_30m_sl2tp2",
        "willr14_30m_sl2tp2", "pivot_4h_sl3tp3"]


class CountingFx(FakeFx):
    def __init__(self, df, *, fail_first_book=False, last=None):
        super().__init__(df)
        self.book_reads = 0
        self.price_reads = 0
        self._fail = fail_first_book
        self._last = last

    def book_cost(self, symbol, notional_usd=200.0):
        self.book_reads += 1
        if self._fail:
            self._fail = False
            raise RuntimeError("code 510: too frequent")
        return super().book_cost(symbol, notional_usd)

    def last_price(self, symbol):
        self.price_reads += 1
        return float(self._last) if self._last is not None else super().last_price(symbol)


@pytest.fixture(autouse=True)
def clean():
    # _LAST_READING files one reading per coin per second, so the test before
    # this one, in the same second, would silence the reading asked about
    for name in ("_GATE_CACHE", "_CYCLE_GATES", "_CYCLE_PRICES", "_LAST_READING"):
        getattr(at, name).clear()
    yield
    assert at._CYCLE_READS is None, "nothing may be shared after a cycle"


def test_every_slot_on_a_coin_shares_one_book_read_inside_a_cycle():
    fx = CountingFx(_bars([100.0] * 60))
    with at.reads_once_per_cycle():
        verdicts = [at._edge_gate_cached(k, COIN, 5.0, fx=fx) for k in KEYS]
    assert fx.book_reads == 1, "five strategies, one coin, one book"
    assert {v["strategy"] for v in verdicts} == set(KEYS), \
        "each verdict is still its own strategy's"


def test_outside_the_runner_loop_every_call_reads_fresh():
    fx = CountingFx(_bars([100.0] * 60))
    for k in KEYS:
        at._edge_gate_cached(k, COIN, 5.0, fx=fx)
    assert fx.book_reads == len(KEYS), "tests, tools and the API are unchanged"


def test_the_read_at_a_signal_is_always_fresh_and_the_screen_then_uses_it():
    fx = CountingFx(_bars([100.0] * 60))
    with at.reads_once_per_cycle():
        at._edge_gate_cached(KEYS[0], COIN, 5.0, fx=fx)
        at._entry_gate(KEYS[1], COIN, 5.0, fx=fx, side=1)
        assert fx.book_reads == 2, "a signal never trades on a shared book"
        at._edge_gate_cached(KEYS[2], COIN, 5.0, fx=fx)
        assert fx.book_reads == 2, "the fresher read serves the rest of the cycle"


def test_a_read_that_fails_is_not_remembered():
    fx = CountingFx(_bars([100.0] * 60), fail_first_book=True)
    with at.reads_once_per_cycle():
        first = at._edge_gate_cached(KEYS[0], COIN, 5.0, fx=fx)
        second = at._edge_gate_cached(KEYS[1], COIN, 5.0, fx=fx)
    assert first["verdict"] == "unknown" and second["verdict"] == "ok"
    assert fx.book_reads == 2, "a throttled read is retried by the next slot"


def test_a_shared_book_is_filed_once_at_the_time_it_was_read():
    fx = CountingFx(_bars([100.0] * 60))
    with at.reads_once_per_cycle():
        for k in KEYS:
            at._edge_gate_cached(k, COIN, 5.0, fx=fx)
    lines = at.BOOK_READINGS_PATH.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["symbol"] == COIN


def test_open_practice_slots_on_one_coin_share_one_price_read():
    df = _bars([100.0] * 60)
    fx = CountingFx(df, last=100.0)
    settings = {"strategies": KEYS[:3], "strategy_coins": {k: [COIN] for k in KEYS[:3]},
                "strategy_books": {k: ["paper"] for k in KEYS[:3]}, "margin": 5.0}
    opened = int(df["Date"].iloc[-1].timestamp())
    state = {at.state_key(COIN, True, k): {
        "step": 0, "last_ts": {}, "position": {
            "side": 1, "entry": 100.0, "tp": 110.0, "sl": 90.0, "vol": 5,
            "margin": 5.0, "strategy": k, "entry_ts": opened,
            "opened_at": opened, "dry": True, "bracket": True, "step": 0}}
        for k in KEYS[:3]}
    with at.reads_once_per_cycle():
        at.process_symbol(COIN, settings, state, fx=fx, dry=True)
    assert all(state[at.state_key(COIN, True, k)]["position"] for k in KEYS[:3])
    assert fx.price_reads == 1, "three open trades on one coin, one price"


def test_the_runner_loop_and_the_one_shot_cycle_both_share_their_reads():
    for fn in (at.run_forever, at.main if hasattr(at, "main") else None):
        if fn is None:
            continue
        src = inspect.getsource(fn)
        if "run_cycle()" in src:
            assert "with reads_once_per_cycle():\n" in src, fn.__name__
    body = inspect.getsource(at)
    tail = body[body.index('if len(sys.argv) > 1 and sys.argv[1] == "once":'):]
    assert tail.split("\n")[1].strip() == "with reads_once_per_cycle():"


def test_the_positions_page_asks_one_price_per_coin(monkeypatch):
    from tradingagents.dataflows import mexc_credentials as cred, mexc_futures as fx

    asked = []
    monkeypatch.setattr(cred, "load_into_env", lambda: None)
    monkeypatch.setattr(fx, "last_price", lambda s: asked.append(s) or 100.0)
    monkeypatch.setattr(fx, "open_positions", lambda *a, **k: [])
    monkeypatch.setattr(fx, "contract_spec", lambda s: {"contractSize": 1.0,
                                                        "takerFeeRate": 0.0004})
    monkeypatch.setattr(at, "load_settings", lambda: {})
    now = 1_790_000_000
    monkeypatch.setattr(at, "load_state", lambda: {
        at.state_key(COIN, True, k): {"step": 0, "last_ts": {}, "position": {
            "side": 1, "entry": 99.0, "tp": 110.0, "sl": 90.0, "vol": 5,
            "margin": 5.0, "strategy": k, "entry_ts": now, "opened_at": now,
            "dry": True}} for k in KEYS})
    got = api.trade_positions()
    assert len(got["paper"]) == len(KEYS)
    assert asked == [COIN], f"{len(KEYS)} open rows, one coin: asked {asked}"
