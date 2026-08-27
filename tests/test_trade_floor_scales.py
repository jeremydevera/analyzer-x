"""The trade floor scales with the WINDOW, and says what it dropped.

Aug 27, 2026, reading the finished 1h/4h 2-month sweep: 9,439,792 rows over
893 coins, and only 58 of the 105 signals in it. Missing: 26 of the 30
confluence rules the operator had just asked to measure — cf_ttm, cf_donch,
cf_emarsi, every level-2 — plus 21 older ones (supertrend, ichimoku, adx14,
obv20, volspike...).

Nothing failed. The floor did it. `min_trades` was a flat 100 at 1h and 40 at
4h whatever the window, and the window was 60 DAYS: 1,440 bars at 1h, so 100
trades means one every 14 hours, and 4h has only ~360 bars for 40. Every
selective rule — which is what a confluence rule IS — was computed in full and
then dropped at the last step, exactly as a flat 100 deleted the whole 1d
timeframe on 2026-08-26.

So the floor is a RATE, scaled to the days actually measured, with an absolute
"not noise" minimum; and the count of rows it drops is reported, because a
grid that cuts something has to say so (rule 20).
"""
import math

import pytest

from tradingagents import market_sweep as msw


def test_a_year_keeps_the_floors_that_were_tuned_for_a_year():
    assert msw.min_trades("1h", days=365) == 100
    assert msw.min_trades("4h", days=365) == 40
    assert msw.min_trades("15m", days=365) == 100
    assert msw.min_trades("1d", days=365) == 10


def test_a_two_month_window_asks_for_two_months_worth():
    """60 days is a sixth of a year, so a sixth of the evidence — not the same
    absolute count on a sixth of the bars."""
    assert msw.min_trades("1h", days=60) == 16
    assert msw.min_trades("4h", days=60) == 10       # the absolute floor bites
    assert msw.min_trades("1d", days=60) == 10


def test_the_absolute_floor_still_rejects_noise():
    """However short the window, a handful of trades is not evidence."""
    for tf in ("15m", "30m", "1h", "4h", "1d"):
        assert msw.min_trades(tf, days=7) >= 10
        assert msw.min_trades(tf, days=1) >= 10
    assert msw.MIN_TRADES_ABS == 10


def test_no_days_means_the_old_behaviour():
    """Callers that do not know their window get the per-timeframe floor, so
    nothing silently loosens."""
    assert msw.min_trades("1h") == msw.MIN_TRADES_BY_TF["1h"]
    assert msw.min_trades("4h") == msw.MIN_TRADES_BY_TF["4h"]


def test_run_pair_uses_its_own_window_and_counts_what_it_dropped():
    """The floor call must carry `days`, and the pair must report the rows it
    threw away — a sweep that drops 26 of 30 rules in silence is how this
    incident happened."""
    import inspect

    src = inspect.getsource(msw.run_pair)
    assert "min_trades(tf, days=days)" in src, \
        "the floor must be scaled by the window the pair measured"
    i = src.index("min_trades(tf, days=days)")
    window = src[i:i + 260]
    assert "thin" in window, "the dropped rows must be counted"
    assert '"thin": thin' in src, "and returned to the caller"


def test_the_grid_reports_the_dropped_rows(monkeypatch, tmp_path):
    """grid_from_store must surface the count, so the page can say it."""
    from tradingagents import backtest_report as br

    monkeypatch.setattr(msw, "HOME", tmp_path)
    monkeypatch.setattr(msw, "ROWDIR", tmp_path / "rows")
    monkeypatch.setattr(msw, "STATES", tmp_path / "state")
    row = {"coin": "APEX", "tf": "1h", "signal": "mom6", "th": 0.0, "sl": 1.0,
           "tp": 4.0, "rr": 4.0, "sizing": "flat", "lev": 20, "base": 5.0,
           "notional": 100.0, "trades": 120, "wins": 50, "losses": 70,
           "winrate": 41.7, "profit": 12.0, "h1": 6.0, "h2": 6.0, "green": 8,
           "months": 12, "worst": -2.0, "dd": 9.0, "liqs": 0, "days": 60,
           "bars": 1440, "monthly": {"2026-08": 12.0}, "cost_of_tp": 5.0,
           "rt": 0.2, "gate": "ok"}
    msw.save_pair_rows("APEX", "1h", [row])
    monkeypatch.setattr(msw, "run_pair", lambda sym, tf, **kw: {
        "coin": "APEX", "tf": "1h", "rows": [row], "added": 0, "source": "cache",
        "why": None, "incremental": False, "new_bars": 1440, "fee": 0.0004,
        "liq": 4.0, "rt": 0.002, "bars": 1440, "days": 60, "thin": 137})
    p = br.grid_from_store(["APEX_USDT"], ["1h"], days=60, embed_limit=0)
    assert p["thin_rows"] == 137, "the page must know what the floor cut"


def test_the_page_says_what_the_floor_cut():
    """Rule 20: a grid that cuts something says so, in the same breath as the
    count. The floor's cut used to be invisible."""
    from tradingagents import backtest_report as br

    payload = {"rows": [{"coin": "APEX"}], "rows_total": 1, "thin_rows": 4137}
    note = br._capped_note(payload)
    assert "4,137" in note and "trade floor" in note
    # and when nothing was dropped, nothing is claimed
    assert br._capped_note({"rows": [{"coin": "APEX"}], "rows_total": 1,
                            "thin_rows": 0}) == ""
