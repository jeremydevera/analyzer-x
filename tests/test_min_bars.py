"""The bar floor is gone — a pair is tested with the candles it HAS.

Operator, Sep 09, 2026: *"why are you making bar floor if i told you to test
4hr then test it the available candles / its like use what's available"*. The
500-bar floor was the code's judgement, not theirs: it held 622 young pairs
"pending" for weeks while the button could honestly offer only 25.

TWO bars is the physical minimum — one bar cannot contain a trade. A signal
whose lookback exceeds the history simply makes no trades (both sweeps skip a
raising signal per-signal), depth is the row's own `days`/`bars`, and the
min-trades filter is where trust is decided — by the reader, not by a
constant in the sweep.

History kept below because it explains the 1d=60 era this replaced: a flat
500 once made 1d impossible (a 60-day window is ~90 daily bars), so the floor
became per-timeframe on 2026-08-26 — and per-operator, zero, on 2026-09-09.
"""
import pandas as pd
import pytest

from tradingagents import market_sweep as msw


def _frame(n, step_s):
    ts = [1_780_000_000 + i * step_s for i in range(n)]
    return pd.DataFrame({"Date": pd.to_datetime(ts, unit="s"),
                         "Open": [1.0] * n, "High": [1.01] * n, "Low": [0.99] * n,
                         "Close": [1.0] * n, "Volume": [1.0] * n})


def test_the_floor_is_the_physical_minimum_everywhere():
    for tf in ("15m", "30m", "1h", "4h", "1d"):
        assert msw.min_bars(tf) == 2, (tf, "use what's available — operator,"
                                       " Sep 09, 2026")


@pytest.mark.parametrize("tf,bars,step,skipped", [
    ("1d", 90, 86400, False),     # the 2-month sweep's 1d series: measured
    ("1d", 40, 86400, False),     # 40 daily bars: MEASURED now (was refused)
    ("15m", 480, 900, False),     # a 5-day-old coin at 15m: MEASURED now
    ("4h", 10, 14400, False),     # a days-old listing: measured with what it has
    ("1h", 1, 3600, True),        # one bar cannot contain a trade
])
def test_run_pair_uses_whats_available(monkeypatch, tf, bars, step, skipped):
    monkeypatch.setattr(msw, "refresh_candles",
                        lambda symbol, tf, days=365: (_frame(bars, step), bars, "cache"))
    # past the floor run_pair prices the pair, which asks the venue.
    # A unit test stubs its I/O; the floor is what is under test.
    from tradingagents.dataflows import mexc_futures as fx

    monkeypatch.setattr(fx, "funding_history", lambda symbol, **kw: [])
    r = msw.run_pair("APEX_USDT", tf, days=60)
    if skipped:
        assert r["rows"] == [] and r["why"] == f"only {bars} bars"
    else:
        # past the floor the pair goes on to price its costs; with no venue
        # reachable in a unit test that is where it stops — but NOT at the floor
        assert not r.get("why", "").startswith("only ")


def test_the_shard_shares_the_same_floor():
    """One definition: the cloud shard reads br.min_bars too, so a pair the
    Mac would measure is never skipped by a runner (and the other way round)."""
    s = open(".github/scripts/sweep_shard.py", encoding="utf-8").read()
    assert "br.min_bars(tf)" in s
    import re

    assert not re.search(r"len\(df\) < \d", s), "no private numeric floor"
