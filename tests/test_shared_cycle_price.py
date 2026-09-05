"""One price per coin per cycle, shared by both books.

Operator, 2026-09-05: *"read once, both books use that one number. Then luck
is out of it"* — after live sold PSXSTOCK at 253.50 while demo sold at 257.35
in the same second. Each book had read the price separately, and the coin's
two sides are 1.6% apart, so "the last price" was a coin-flip between them.
Three real losses (−5.36 USDT) sat beside three demo wins on the SAME signals.

Built with the harddev loop. Its one find is pinned here and in conftest: the
store is module state, so without a wipe a price cached by one test's fake
exchange would be handed to the next test's different fake.
"""
import pytest

from tradingagents import auto_trader as at


class FlickerFX:
    """A book that returns a DIFFERENT price on every read — the exact
    condition that split the two books."""

    def __init__(self):
        self.reads = 0

    def order_book(self, symbol):
        self.reads += 1
        base = 253.53 + self.reads * 2          # 255.53, 257.53, ...
        return {"bids": [[base, 100]], "asks": [[base + 4.2, 100]]}

    def last_price(self, symbol):
        return 999.0


class NoBookFX:
    def __init__(self, last=256.67):
        self.last = last
        self.book_calls = 0
        self.last_calls = 0

    def order_book(self, symbol):
        self.book_calls += 1
        raise RuntimeError("no book")

    def last_price(self, symbol):
        self.last_calls += 1
        return self.last


class DeadFX(NoBookFX):
    def last_price(self, symbol):
        self.last_calls += 1
        raise RuntimeError("no price at all")


@pytest.fixture(autouse=True)
def _fresh_store():
    at._CYCLE_PRICES.clear()
    yield
    at._CYCLE_PRICES.clear()


def test_both_books_get_the_same_number_even_when_the_book_moves():
    """The second read would have seen a different book; it must get the
    FIRST read's number, because both books are pricing the same signal."""
    fx = FlickerFX()
    first = at.tradable_price("PSXSTOCK_USDT", -1, fx=fx)
    second = at.tradable_price("PSXSTOCK_USDT", -1, fx=fx)
    assert first == second
    assert fx.reads == 1, "read ONCE — that is the whole point"


def test_a_buy_and_a_sell_are_cached_apart():
    """The ask and the bid are different numbers on purpose."""
    fx = FlickerFX()
    sell = at.tradable_price("X_USDT", -1, fx=fx)
    buy = at.tradable_price("X_USDT", +1, fx=fx)
    assert buy != sell, "a buy pays the ask, a sell takes the bid"


def test_run_cycle_wipes_the_store_even_when_it_does_nothing(monkeypatch):
    """The wipe is BEFORE the early return, so a cycle with nothing enabled
    still cannot leave last cycle's numbers behind."""
    at._CYCLE_PRICES[("X_USDT", 1)] = (0.0, 123.0)
    monkeypatch.setattr(at, "load_settings", lambda: {})
    at.run_cycle(fx=object())
    assert at._CYCLE_PRICES == {}


def test_the_backstop_age_refuses_a_stale_number():
    """For callers that are not run_cycle (tests, tools): a number older than
    the cap is read again, never reused."""
    import time

    fx = FlickerFX()
    at._CYCLE_PRICES[("PSXSTOCK_USDT", -1)] = (
        time.time() - at._CYCLE_PRICE_MAX_AGE_S - 1, 111.0)
    got = at.tradable_price("PSXSTOCK_USDT", -1, fx=fx)
    assert got != 111.0
    assert fx.reads == 1


def test_the_fallback_is_shared_too():
    """A fallback one book took while the other read the book fresh would be
    the same coin-flip again — so the fallback is cached like any price."""
    fx = NoBookFX()
    first = at.tradable_price("Y_USDT", -1, fx=fx)
    second = at.tradable_price("Y_USDT", -1, fx=fx)
    assert first == second == 256.67
    assert fx.last_calls == 1, "the second book reused it"


def test_nothing_is_cached_when_there_is_no_price_at_all():
    """No price = no entry, and no poison left behind for the next call."""
    fx = DeadFX()
    with pytest.raises(Exception):
        at.tradable_price("Z_USDT", -1, fx=fx)
    assert ("Z_USDT", -1) not in at._CYCLE_PRICES
    # the venue comes back: the next call reads fresh and works
    ok = NoBookFX(last=100.0)
    assert at.tradable_price("Z_USDT", -1, fx=ok) == 100.0


def test_the_wipe_is_the_first_thing_the_cycle_does():
    import inspect

    src = inspect.getsource(at.run_cycle)
    body = src[src.index("-> None:"):]
    assert body.index("_CYCLE_PRICES.clear()") < body.index("load_settings()")
