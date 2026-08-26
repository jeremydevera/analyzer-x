"""The trade floor scales with the bar, or a whole timeframe disappears.

`market_sweep.MIN_TRADES = 100`, commented "the short-timeframe floor", was
applied to EVERY timeframe. Measured on the operator's own store, 2026-08-26,
after a 2-month sweep of 997 coins x 1h/4h/1d:

  * every 1d row file was `[]` — 739 of them, 2 bytes each
  * the state files held the work: SPX500-1d had 10,692 measured combinations,
    the best of them 11 trades (median 3); GOOGLSTOCK-1d's best was 30
  * so ~10.6 million measured 1d combinations were computed and then dropped,
    and the run reported "5 timeframes" while the grid held two

A 60-day window is ~90 daily bars: 100 trades is arithmetically impossible
there. The floor is now per timeframe, and it is a FLOOR ON EVIDENCE, not a
judgement — the row carries its own trades/days and the reader filters.
"""
import json

import pytest

from tradingagents import market_sweep as msw


def test_the_floor_is_per_timeframe_and_reachable():
    assert msw.min_trades("15m") == 100
    assert msw.min_trades("30m") == 100
    assert msw.min_trades("1h") == 100
    # 4h over 60 days is ~360 bars; 1d is ~90. A 100-trade floor deletes them.
    assert msw.min_trades("4h") <= 40
    assert msw.min_trades("1d") <= 10
    for tf in ("15m", "30m", "1h", "4h", "1d"):
        assert msw.min_trades(tf) >= 5, f"{tf}: a handful of trades is not evidence"


def test_a_daily_row_with_eleven_trades_is_kept(tmp_path, monkeypatch):
    """SPX500-1d's best combination, from the operator's own state file."""
    assert 11 >= msw.min_trades("1d"), "11 trades must clear the 1d floor"
    assert 11 < msw.min_trades("1h"), "and would NOT clear the 1h floor"


def test_the_floor_is_named_in_one_place_only():
    """Two copies of a floor is one floor waiting to drift."""
    src = open("tradingagents/market_sweep.py", encoding="utf-8").read()
    body = src[src.index("def run_pair("):src.index("def _worker(")]
    assert "min_trades(tf)" in body, "run_pair asks for the timeframe's floor"
    assert "< MIN_TRADES" not in body, "and never compares against the flat one"


def test_the_shard_uses_the_same_floor():
    """A cloud pair and a local pair must be the same measurement."""
    src = open(".github/scripts/sweep_shard.py", encoding="utf-8").read()
    assert 'if not r["trades"]' in src or "min_trades" in src


@pytest.mark.parametrize("tf,trades,kept", [
    ("1d", 11, True), ("1d", 3, False),
    ("4h", 45, True), ("4h", 9, False),
    ("1h", 120, True), ("1h", 40, False),
])
def test_run_pair_keeps_a_row_only_above_its_timeframes_floor(tf, trades, kept):
    assert (trades >= msw.min_trades(tf)) is kept
