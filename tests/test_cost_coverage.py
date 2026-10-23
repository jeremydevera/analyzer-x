"""COVERAGE FIRST (CLAUDE.md "Every backtest LOOKS AT THE COSTS"; Backtest v3
spec, Part 3): before a run, the share of its minutes the recorded order
books cover is measured and printed."""
import pytest

from tradingagents import book_history as bh, cost_store as cs

T0 = 1_790_000_000 - (1_790_000_000 % 3600)


def _reading(t):
    return {"t": t, "bid": 1.0, "ask": 1.1, "spread": 0.1, "buy": 0.001, "sell": 0.001,
            "exhausted": False, "source": "full"}


def test_a_book_read_every_minute_covers_the_whole_window():
    packed = bh.pack([_reading(T0 + 60 * k) for k in range(60)])
    assert cs.coverage(packed, T0, T0 + 3600) == pytest.approx(1.0)


def test_a_reading_answers_the_hour_after_it_and_no_more():
    packed = bh.pack([_reading(T0)])
    # one reading at T0 answers the minutes T0 .. T0+3600: 61 of the window's 120
    assert cs.coverage(packed, T0, T0 + 7200) == pytest.approx(61 / 120)


def test_no_book_covers_nothing():
    assert cs.coverage(cs.empty(), T0, T0 + 3600) == 0.0
    assert cs.coverage(None, T0, T0 + 3600) == 0.0, "not on Gate: engine_book is None"
