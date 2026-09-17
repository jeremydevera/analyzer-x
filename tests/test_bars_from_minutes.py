"""Sixty one-minute candles ARE the hour candle.

Measured Sep 17, 2026 on XPIN_USDT: 666 of 666 hours identical to MEXC's own
Min60 bars on open/high/low/close. Backtest v2 rests on that, so the
resampler is held to it here on a recorded fixture, and the 1m frame must
never leak into a v1 list — no v1 job, cloud shard or completeness count may
see a 1m pair.
"""
import re
from pathlib import Path

import pandas as pd
import pytest

from tradingagents import backtest_report as br, capacity as cap, market_sweep as msw

REPO = Path(__file__).resolve().parent.parent
# Sep 16, 2026 00:00 UTC — on every boundary (20,712 days × 86,400 s). The
# first draft used 1_757_980_800_000, which is Sep 16, 2025: the fixture's
# clock and its own assertion disagreed by a year, exactly the two-clock
# fixture RCA-2026-09-12-A warns about.
MIDNIGHT = 1_789_516_800_000


def _minutes(start_ms: int, n: int, seed: int = 5):
    import random

    rng = random.Random(seed)
    px = 100.0
    rows = []
    for i in range(n):
        o = px
        px = px * (1 + rng.gauss(0, 0.001))
        h = max(o, px) * (1 + abs(rng.gauss(0, 0.0005)))
        l = min(o, px) * (1 - abs(rng.gauss(0, 0.0005)))
        rows.append((start_ms + i * 60_000, o, h, l, px, 10.0 + i % 7))
    df = pd.DataFrame(rows, columns=["t", "Open", "High", "Low", "Close", "Volume"])
    df["Date"] = pd.to_datetime(df["t"], unit="ms")
    return df.drop(columns="t")


def test_sixty_minutes_rebuild_the_hour_exactly():
    # 3 full hours + 17 minutes of a forming fourth, starting on an hour boundary
    m1 = _minutes(MIDNIGHT, 3 * 60 + 17)
    bars = msw.bars_from_1m(m1, "1h")
    assert len(bars) == 3, "the forming 4th hour is dropped, as v1 drops the forming bar"
    for k in range(3):
        chunk = m1.iloc[k * 60:(k + 1) * 60]
        row = bars.iloc[k]
        assert row["Open"] == chunk["Open"].iloc[0]
        assert row["High"] == chunk["High"].max()
        assert row["Low"] == chunk["Low"].min()
        assert row["Close"] == chunk["Close"].iloc[-1]
        assert row["Volume"] == pytest.approx(chunk["Volume"].sum())
        assert row["Date"] == chunk["Date"].iloc[0], "a bar is stamped at its OPEN, like MEXC"


def test_a_frame_that_does_not_start_on_the_boundary_drops_the_partial_first_bar():
    m1 = _minutes(MIDNIGHT + 23 * 60_000, 2 * 60 + 37)          # starts at 00:23
    bars = msw.bars_from_1m(m1, "1h")
    assert len(bars) == 2                       # 01:00 and 02:00 are complete; 00:xx is not
    assert bars["Date"].iloc[0] == pd.Timestamp("2026-09-16 01:00:00")


@pytest.mark.parametrize("tf,per", [("15m", 15), ("30m", 30), ("1h", 60),
                                    ("4h", 240), ("1d", 1440)])
def test_every_frame_needs_its_full_minute_count(tf, per):
    m1 = _minutes(MIDNIGHT, per * 2 + 3)        # two full bars + a forming one
    bars = msw.bars_from_1m(m1, tf)
    assert len(bars) == 2, (tf, len(bars))


def test_a_missing_minute_is_refused_not_papered_over():
    m1 = _minutes(MIDNIGHT, 180)
    m1 = m1.drop(index=[70]).reset_index(drop=True)   # one minute gone inside hour 2
    with pytest.raises(ValueError, match="missing minute"):
        msw.bars_from_1m(m1, "1h")


def test_a_frame_v2_does_not_rebuild_is_refused_by_name():
    with pytest.raises(ValueError, match="not a frame v2 rebuilds"):
        msw.bars_from_1m(_minutes(MIDNIGHT, 10), "1m")


def test_an_empty_frame_gives_an_empty_table_with_the_right_columns():
    out = msw.bars_from_1m(None, "1h")
    assert list(out.columns) == ["Date", "Open", "High", "Low", "Close", "Volume"]
    assert len(out) == 0


def test_the_1m_entry_exists_and_only_there():
    assert br.TFS["1m"] == ("Min1", 60, 44000)
    assert "1m" not in cap.ALL_TFS
    assert "1m" not in br.BARRIERS and "1m" not in br.THRESHOLDS and "1m" not in br.MIN_BARS


def test_asking_the_grid_for_1m_is_refused_by_name_not_by_keyerror():
    """Found by the harddev loop before it shipped: two places validated a
    frame with `in br.TFS`, so "1m" would have passed and died three calls
    later at BARRIERS["1m"] — after fetching the pair's candles."""
    with pytest.raises(ValueError, match="download frame only"):
        br.pairs_for("1m")
    src = (REPO / ".github/scripts/archive_backtest.py").read_text(encoding="utf-8")
    assert "in br.BARRIERS]" in src and "in br.TFS]" not in src, \
        "the cloud archive shard must filter frames on the GRID, not on TFS"


def test_the_cloud_dispatch_drops_a_frame_with_no_grid_before_it_leaves():
    """The shard reads TFS from its environment with no check; a "1m" there
    would fetch 30 days of minutes on twenty machines and then die at
    THRESHOLDS["1m"]. The dispatcher filters on the grid first."""
    from tradingagents import cloud_sweep as cs

    assert cs.grid_frames("1h,1m,4h") == "1h,4h"
    assert cs.grid_frames("1m") == ""
    assert cs.grid_frames("15m,30m") == "15m,30m"


def test_no_five_frame_list_grew_a_sixth():
    """Every hardcoded ("15m","30m","1h","4h","1d") tuple in the v1 modules is
    still exactly five. A sixth entry would put a 1m pair in front of a v1 job."""
    five = re.compile(r'\(\s*"15m",\s*"30m",\s*"1h",\s*"4h",\s*"1d"\s*\)')
    six = re.compile(r'"1m",\s*"15m",\s*"30m"|"15m",\s*"30m",\s*"1h",\s*"4h",\s*"1d",\s*"1m"')
    for name in ("tradingagents/db_jobs.py", "tradingagents/api.py",
                 "tradingagents/capacity.py", ".github/scripts/sweep_shard.py"):
        src = (REPO / name).read_text(encoding="utf-8")
        assert not six.search(src), f"{name}: a five-frame list grew a 1m entry"
    assert five.search((REPO / "tradingagents/db_jobs.py").read_text(encoding="utf-8"))
