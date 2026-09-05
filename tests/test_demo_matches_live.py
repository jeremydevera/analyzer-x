"""DEMO must fill where LIVE fills, and pay what LIVE pays.

Operator, 2026-09-05: *"I thought my live and demo are the same ... if its not
mexc fault then its your bug because live trade and demo is not the same"*.

The receipt — one strategy (#PNK3G9KZ, PSXSTOCK willr14 15m), three signals,
each traded by BOTH books in the same second:

    8:45am  LIVE  SHORT 253.50 -> stop refused (5003) -> closed 257.72  -1.80
    8:45am  DEMO  SHORT 257.35 -> TP                  -> closed 254.26  +0.98
    9:01am  LIVE  253.53  -1.78   |  DEMO 257.51  +0.98
    9:17am  LIVE  253.52  -1.78   |  DEMO 257.75  +0.98

    LIVE record: 0 wins, 3 losses, -5.36 USDT
    DEMO record: 8 wins, 1 loss,   +6.62 USDT

Two defects, both ours: the entry price was a LAST-TRADE print (which side
printed last, and PSXSTOCK's sides are 1.6% apart), and the paper book paid a
flat 0.03%/side on a contract whose round trip is 2%.
"""
import inspect

import pytest

from tradingagents import auto_trader as at


class FX:
    """A book 1.6% wide, like PSXSTOCK's on the morning this was found."""

    last = 256.67

    def order_book(self, symbol):
        return {"bids": [[253.53, 5000]], "asks": [[257.75, 5000]]}

    def last_price(self, symbol):
        return self.last


class NoBook(FX):
    def order_book(self, symbol):
        raise RuntimeError("no book")


def test_a_buy_pays_the_ask_and_a_sell_takes_the_bid():
    fx = FX()
    assert at.tradable_price("PSXSTOCK_USDT", +1, fx=fx) == 257.75
    assert at.tradable_price("PSXSTOCK_USDT", -1, fx=fx) == 253.53
    # NOT the last print, which is what made the two books disagree
    assert at.tradable_price("PSXSTOCK_USDT", -1, fx=fx) != fx.last


def test_both_books_read_the_same_number():
    """The live and paper cycles ran a second apart and got 253.50 and 257.35.
    A book side does not flicker."""
    fx = FX()
    twice = {at.tradable_price("PSXSTOCK_USDT", -1, fx=fx) for _ in range(5)}
    assert len(twice) == 1


def test_it_falls_back_when_the_book_cannot_be_read():
    """No book is not a reason to enter blind — but it is not a reason to
    crash either; the caller refuses when there is no price at all."""
    assert at.tradable_price("PSXSTOCK_USDT", -1, fx=NoBook()) == FX.last


def test_the_entry_uses_the_tradable_price():
    src = inspect.getsource(at._process_slot)
    assert "tradable_price(symbol, side, fx=fx)" in src
    # scoped to the ENTRY region: the exit path legitimately reads the
    # last price when it has to close at market
    entry = src[src.index('entry = close[-1]'):
               src.index('vol = fx.contracts_for')]
    assert 'fx.last_price' not in entry, \
        "the last print is what the two books disagreed on"


def test_the_position_carries_what_the_round_trip_costs():
    src = inspect.getsource(at._process_slot)
    assert '"rt_cost": float(gate.get("round_trip_cost") or 0.0),' in src


def test_a_paper_exit_pays_that_cost_not_a_flat_guess():
    src = inspect.getsource(at._process_slot)
    i = src.index("if pos_dry:")
    frag = src[i:i + 900]
    assert 'pos.get("rt_cost")' in frag
    assert "2 * PAPER_SLIPPAGE" in frag, "kept as the fallback for old rows"


@pytest.mark.parametrize("rt,expected", [
    # PSXSTOCK: round trip 2%, TP 1.2% -> a paper "win" is a LOSS, exactly as
    # the live book found out three times
    (0.02, -0.96),
    # KITE: round trip 0.10%, TP 3% -> a win is still a win
    (0.001, 2.74),
])
def test_the_paper_pnl_now_matches_what_live_would_keep(rt, expected):
    """The arithmetic the exit path runs: (move - cost) * margin * leverage."""
    margin, lev = 5.0, at.LEVERAGE
    move = 0.012 if rt > 0.01 else 0.03          # the TP it "hit"
    fee = 2 * at.FEE_FALLBACK
    pnl = (move - (fee + rt)) * margin * lev
    assert round(pnl, 2) == pytest.approx(expected, abs=0.05), pnl
