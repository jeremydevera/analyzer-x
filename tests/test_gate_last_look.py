"""The gate blocks a stop that cannot rest, and looks FRESH before real money.

What happened (2026-09-05, the operator's own account):

    8:45am  short PSXSTOCK fills at 253.53 (the bid)
            stop = +1% = 256.06 — but the coin's two prices are 1.66% apart,
            and MEXC checks the stop against its side: 257.7. Already passed.
            5003 -> forced close at 257.72 -> -1.80
    9:01am  same again  -1.78
    9:17am  same again  -1.78          total -5.36 USDT

Two holes, both fixed here:
* the gate never checked the GAP against the STOP — SL 1% inside a 1.66% gap
  is dead on arrival, at any cost/TP ratio;
* the gate's 5-minute cache waved real orders through on a book that flickers
  between 0.3% and 2% wide. A signal now gets a FRESH look at entry, and the
  verdict is stored per cycle so demo shares the same one.
"""
import inspect

import pytest

from tradingagents import auto_trader as at


class FX:
    """PSXSTOCK's book on the morning it cost $5.36."""

    def __init__(self, bid=253.53, ask=257.75, fee=0.0002):
        self.bid, self.ask, self.fee = bid, ask, fee
        self.book_calls = 0

    def order_book(self, symbol):
        self.book_calls += 1
        return {"asks": [[self.ask, 99999]], "bids": [[self.bid, 99999]]}

    def book_cost(self, symbol, notional):
        self.book_calls += 1
        mid = (self.ask + self.bid) / 2
        return {"symbol": symbol, "mid": mid,
                "spread": (self.ask - self.bid) / mid,
                "slippage": self.ask / mid - 1.0,
                "book_exhausted": False, "notional_tested": notional}

    def contract_spec(self, symbol):
        return {"contractSize": 1, "takerFeeRate": self.fee}


@pytest.fixture(autouse=True)
def _fresh():
    at._CYCLE_GATES.clear()
    at._GATE_CACHE.clear()
    yield
    at._CYCLE_GATES.clear()
    at._GATE_CACHE.clear()


def test_a_stop_inside_the_gap_is_blocked_whatever_the_cost_ratio():
    """willr14_15m_sl1tp12: SL 1.0%, and the gap is 1.66%."""
    got = at.edge_check("willr14_15m_sl1tp12", "PSXSTOCK_USDT", 5.0, fx=FX())
    assert got["verdict"] == "block"
    assert "wider than the 1.00% stop" in got["reason"], got["reason"]
    assert "already passed when it is placed" in got["reason"]


def test_a_gap_smaller_than_the_stop_is_not_blocked_by_this_rule():
    """KITE's shape: gap 0.01%, SL 3%."""
    got = at.edge_check("squeeze_1h_sl3tp3", "KITE_USDT", 5.0,
                        fx=FX(bid=0.13420, ask=0.13421, fee=0.0002))
    assert got["verdict"] == "ok", got["reason"]


def test_the_exact_trade_that_lost_5_36_is_refused_now():
    """The gap equal to or above the stop blocks — 1.66% vs 1.0%."""
    fx = FX(bid=253.53, ask=257.75)
    for key in ("willr14_15m_sl1tp12", "stoch14_15m_sl1tp12",
                "willr14_15m_sl12tp12", "stoch14_15m_sl12tp12"):
        assert at.edge_check(key, "PSXSTOCK_USDT", 5.0, fx=fx)["verdict"] \
            == "block", key


def test_the_last_look_measures_once_and_both_books_share_it(monkeypatch):
    calls = []

    def fake_edge(key, symbol, margin, *, fx=None):
        calls.append(key)
        return {"verdict": "block", "reason": "x"}

    monkeypatch.setattr(at, "edge_check", fake_edge)
    first = at._entry_gate("k1", "X_USDT", 5.0, fx=object())
    second = at._entry_gate("k1", "X_USDT", 5.0, fx=object())
    assert first is second, "the demo book must get the SAME verdict"
    assert calls == ["k1"], "measured once per cycle"
    # and the screen cache learns it, so the next cycle blocks early
    assert at._GATE_CACHE[("k1", "X_USDT")][1] is first


def test_the_cycle_wipes_the_verdicts_with_the_prices(monkeypatch):
    at._CYCLE_GATES[("k", "X_USDT")] = {"verdict": "ok"}
    monkeypatch.setattr(at, "load_settings", lambda: {})
    at.run_cycle(fx=object())
    assert at._CYCLE_GATES == {}


def test_the_entry_refuses_unknown_too():
    """Rule 12: a book you cannot read is never an ok."""
    src = inspect.getsource(at._process_slot)
    i = src.index("THE LAST LOOK")
    frag = src[i:src.index("vol = fx.contracts_for", i)]
    assert 'not in ("ok", "warn")' in frag, "block AND unknown refuse"
    assert '"at_entry": True' in frag, "the ledger says which gate said no"


def test_an_entry_block_does_not_eat_the_bar_for_the_other_strategies():
    """The real book shares one slot per coin: marking the candle seen here
    would skip every other strategy on the same timeframe (harddev find)."""
    src = inspect.getsource(at._process_slot)
    i = src.index("THE LAST LOOK")
    frag = src[i:src.index("vol = fx.contracts_for", i)]
    assert 'st["last_ts"]' not in frag, frag
    assert "continue" in frag, "this strategy steps aside; the others still run"
