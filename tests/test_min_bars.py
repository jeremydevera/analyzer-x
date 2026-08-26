"""The bar floor scales with the timeframe — or 1d can never be measured.

`run_pair` refused any series under 500 bars. A year of 1d is at most ~395
bars (the window is days+30), and the 60-day sweep the operator started on
2026-08-25 gave 1d exactly ~90, so every one of the 997 1d pairs was being
excluded as "only 90 bars" — the fifth mandatory timeframe of the full grid,
dropped by a constant that was sized for 15m. The floor is now the technical
minimum per timeframe: enough bars for the longest lookback (trend50) plus a
half-split, not a statistical judgement — depth is the row's own `days` and
`bars`, and the reader filters on it in the artifact (CLAUDE.md, rule 20).
"""
import pandas as pd
import pytest

from tradingagents import market_sweep as msw


def _frame(n, step_s):
    ts = [1_780_000_000 + i * step_s for i in range(n)]
    return pd.DataFrame({"Date": pd.to_datetime(ts, unit="s"),
                         "Open": [1.0] * n, "High": [1.01] * n, "Low": [0.99] * n,
                         "Close": [1.0] * n, "Volume": [1.0] * n})


def test_intraday_keeps_its_floor_and_daily_gets_a_reachable_one():
    assert msw.min_bars("15m") == 500
    assert msw.min_bars("30m") == 500
    assert msw.min_bars("1h") == 500
    assert msw.min_bars("4h") == 500
    # a 60-day window is ~90 daily bars; a year is ~395. Both must pass.
    assert msw.min_bars("1d") == 60
    assert msw.min_bars("1d") <= 90


@pytest.mark.parametrize("tf,bars,step,short", [
    ("1d", 90, 86400, False),     # the 2-month sweep's 1d series: measured
    ("1d", 40, 86400, True),      # under the floor: named as too short
    ("15m", 480, 900, True),      # a 5-day-old coin at 15m: still too short
])
def test_run_pair_applies_the_timeframe_floor(monkeypatch, tf, bars, step, short):
    monkeypatch.setattr(msw, "refresh_candles",
                        lambda symbol, tf, days=365: (_frame(bars, step), bars, "cache"))
    # past the floor run_pair prices the pair, which asks the venue.
    # A unit test stubs its I/O; the floor is what is under test.
    from tradingagents.dataflows import mexc_futures as fx

    monkeypatch.setattr(fx, "funding_history", lambda symbol, **kw: [])
    r = msw.run_pair("APEX_USDT", tf, days=60)
    if short:
        assert r["rows"] == [] and r["why"] == f"only {bars} bars"
    else:
        # past the floor the pair goes on to price its costs; with no venue
        # reachable in a unit test that is where it stops — but NOT at the floor
        assert not r.get("why", "").startswith("only ")
