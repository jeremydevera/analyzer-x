"""`v3_research plan --end YYYY-MM-DD` builds an earlier plan (another year's window) — plan
docs/superpowers/plans/2026-11-04-daily-trend-long-window-and-funding-carry.md. No default changes."""
import argparse

import pytest

from tradingagents import v3_research as vr


def test_end_day_is_that_utc_midnight_in_ms():
    assert vr._day_arg("2025-11-02") == 1_762_041_600_000


def test_a_bad_day_is_refused_by_name():
    with pytest.raises(argparse.ArgumentTypeError, match="YYYY-MM-DD"):
        vr._day_arg("Nov 02, 2025")
