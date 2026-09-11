"""A rule may not be blind over the start of its own measured window.

Sep 11, 2026. The shard cut candles to the window it measured and traded
from bar zero. Every confluence rule reads 200 bars (its 200-bar average),
so it ABSTAINED over the first 200 bars of that window — silently, because
an abstention looks exactly like "no trade".

Measured on the operator's store, same coins, same 30 days:

    MAV 4h   cx_4h    0 signals cold -> 11 warm   (180 bars, ALL warm-up)
    PUNDIX 1h cx_veto 47 signals cold -> 39 warm  (different signals, not
                                                   merely fewer)
    BAND 30m cx_4h   49 signals cold -> 59 warm

and the trades it missed were real: PUNDIX's published row said 17 wins /
0 losses / +$66.32 while the replay over the same candles found 15 wins,
2 LOSSES and +$48.07 — both losses dated Jul 11 and Jul 13, the first two
days of the window. Of 12 rows replayed, 12 disagreed and 4 flipped from
profit to loss.
"""
import pathlib
import re

SHARD = pathlib.Path(".github/scripts/sweep_shard.py")


def _src() -> str:
    return SHARD.read_text(encoding="utf-8")


def test_the_window_keeps_warmup_BARS_not_spare_days():
    """30 calendar days was 2,880 spare bars at 15m and not enough at 4h. A
    lookback is counted in bars, so bars are what is kept."""
    s = _src()
    assert "WARMUP_BARS = 300" in s
    assert "timedelta(days=DAYS + 30)" not in s, "the calendar buffer is gone"
    assert "Timedelta(days=DAYS)" in s, "the window is the window asked for"


def test_window_returns_how_many_bars_are_warm_up_only():
    s = _src()
    assert "return df.iloc[start:].reset_index(drop=True), warm" in s
    assert "df, warm = window(df)" in s


def test_no_signal_may_fire_inside_the_warm_up():
    """The one line that makes the difference: a signal whose indicators are
    still filling is not a trade."""
    s = _src()
    assert "if v2 and k2 >= warm" in s


def test_days_and_bars_describe_the_MEASURED_region():
    """A row saying 59 days while 33 of them only fed averages is a label
    over the wrong number (label-must-match-data)."""
    s = _src()
    assert 'df["Date"].iloc[warm]' in s, "days must start where trading starts"
    assert "nbars = len(df) - warm" in s
    assert "half = warm + (nbars // 2)" in s


def test_the_bar_floor_counts_measurable_bars():
    s = _src()
    assert "if len(df) - warm < br.min_bars(tf)" in s


def test_the_warmup_matches_what_the_local_sweep_uses():
    """One number, two engines. The local sweep hands a rule CONTEXT_BARS of
    history before the first new bar; the cloud must not be stingier, or the
    same rule means two different things depending on which machine ran it."""
    from tradingagents import market_sweep as msw

    m = re.search(r"WARMUP_BARS = (\d+)", _src())
    assert m and int(m.group(1)) >= msw.CONTEXT_BARS, (
        f"shard warm-up {m and m.group(1)} < market_sweep.CONTEXT_BARS "
        f"{msw.CONTEXT_BARS}")
