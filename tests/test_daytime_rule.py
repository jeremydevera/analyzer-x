"""The daytime rule (Oct 07, 2026; trial on #4FC03172).

Operator: "so what do you think is the correct, because its seems like i
cannot rely on winrate for past 30 days", then "yes" to building the best rule
of the walk-forward test as a room rule. Spec:
docs/superpowers/specs/2026-10-07-daytime-rule-design.md

Measured: today's rule 14,010 takeable bets, 53.4% won, -$672.37; the daytime
rule 1,655 bets, 60.1% won, +$394.82, green on 16 of 16 test days.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from tradingagents import daytime_rule as dr

NY = ZoneInfo("America/New_York")
DAY = 86_400_000


def _ny(y, m, d, h, mi=0) -> float:
    return dt.datetime(y, m, d, h, mi, tzinfo=NY).timestamp()


def _ms(y, m, d, h, mi=0) -> int:
    return int(_ny(y, m, d, h, mi) * 1000)


# ------------------------------------------------------------- market hours
def test_market_hours_are_new_york_weekdays_9_30_to_4():
    assert dr.in_market_hours(_ny(2026, 10, 5, 9, 30))       # Monday open
    assert dr.in_market_hours(_ny(2026, 10, 5, 15, 59))
    assert not dr.in_market_hours(_ny(2026, 10, 5, 16, 0))   # the close
    assert not dr.in_market_hours(_ny(2026, 10, 5, 9, 29))
    assert not dr.in_market_hours(_ny(2026, 10, 6, 22, 15))  # Oct 06 night
    assert not dr.in_market_hours(_ny(2026, 10, 3, 11, 0))   # Saturday


def test_market_hours_follow_daylight_saving():
    # Nov 02, 2026 is after the clocks go back: 9:30am New York is 14:30 UTC
    utc = dt.datetime(2026, 11, 2, 14, 30, tzinfo=dt.timezone.utc).timestamp()
    assert dr.in_market_hours(utc)
    assert not dr.in_market_hours(utc - 60)


def test_a_stock_token_is_named_stock():
    assert dr.is_stock("FWDISTOCK_USDT") and dr.is_stock("INNOLUXSTOCK")
    assert not dr.is_stock("BB_USDT") and not dr.is_stock("ZINC")


# ------------------------------------------------------- pays after fees
def test_a_win_must_pay_a_loss_after_the_rows_own_fee():
    assert dr.pays_a_loss({"tp": 1.5, "sl": 1.0, "rt": 0.22})       # 1.28 vs 1.22
    assert not dr.pays_a_loss({"tp": 1.0, "sl": 0.8, "rt": 0.22})   # 0.78 vs 1.02
    # #TBGNFDCE FWDISTOCK 15m willr14: +$0.38 against -$0.72
    assert not dr.pays_a_loss({"tp": 0.6, "sl": 0.5, "rt": 0.22})


def test_the_fee_comes_from_cost_of_tp_when_rt_is_missing():
    assert dr.fee_of({"tp": 2.0, "sl": 1.0, "cost_of_tp": 11.0}) == pytest.approx(0.22)
    assert dr.pays_a_loss({"tp": 2.0, "sl": 1.0, "cost_of_tp": 11.0})


def test_an_unknown_fee_never_passes():
    assert dr.fee_of({"tp": 2.0, "sl": 1.0}) is None
    assert not dr.pays_a_loss({"tp": 2.0, "sl": 1.0})
    assert not dr.pays_a_loss({"tp": 2.0, "sl": 1.0, "cost_of_tp": 0})


# ------------------------------------------------------------- list checks
def _t(entry_ms, pnl):
    # [entry_ms, known_ms, pnl, closed, exit_ms, why, side]
    return [entry_ms, entry_ms + 600_000, pnl, True, entry_ms + 600_000,
            "TP" if pnl > 0 else "SL", "LONG"]


END = _ms(2026, 10, 2, 20)            # the list's last candle, a Friday night


def _days(n_day, wins_day, n_night, wins_night, *, days_back=10):
    """Trades spread over the 10 weekdays before END: daytime at 11:00am New
    York, night at 10:00pm."""
    out = []
    d = dt.datetime(2026, 10, 2, tzinfo=NY)
    picked = 0
    while picked < days_back:
        if d.weekday() < 5:
            picked += 1
            for i in range(n_day):
                out.append(_t(int(d.replace(hour=11, minute=i % 60).timestamp() * 1000),
                              0.8 if i < wins_day else -1.0))
            for i in range(n_night):
                out.append(_t(int(d.replace(hour=22, minute=i % 60).timestamp() * 1000),
                              0.8 if i < wins_night else -1.0))
        d -= dt.timedelta(days=1)
    return out


def test_a_stock_strategy_that_wins_only_at_night_fails():
    # 3 a day in daytime, 1 won (33%); 5 a night, all won
    why = dr.list_checks(_days(3, 1, 5, 5), "FWDISTOCK", END, 70.0)
    assert "daytime" in why and "33.3%" in why


def test_a_stock_strategy_that_wins_in_daytime_passes():
    assert dr.list_checks(_days(3, 3, 5, 1), "GPNSTOCK", END, 70.0) == ""


def test_too_few_daytime_trades_fail():
    why = dr.list_checks(_days(1, 1, 5, 5), "GPNSTOCK", END, 70.0)   # 10 daytime
    assert "10 daytime trades" in why


def test_crypto_is_judged_on_every_hour():
    assert dr.list_checks(_days(0, 0, 3, 3), "BB", END, 70.0) == ""


def test_the_last_7_days_must_still_win():
    # 30 weekdays of daytime wins, so the 30-day daytime record stays 70%+ ...
    trades = _days(3, 3, 0, 0, days_back=30)
    # ... and the last 7 days before END lose: every trade after END - 7 days
    trades = [t if t[4] < END - 7 * DAY else [*t[:2], -1.0, *t[3:]] for t in trades]
    why = dr.list_checks(trades, "GPNSTOCK", END, 70.0)
    assert "last 7 days" in why


def test_windows_end_at_the_lists_last_candle_not_the_clock():
    """A pair measured a day behind: its 7 days end at ITS last candle."""
    assert dr.list_checks(_days(3, 3, 0, 0), "GPNSTOCK", END, 70.0) == ""


# ------------------------------------------------------------------ screen
CFG = {"on_winrate": 70.0}


def _row(rid, coin="GPNSTOCK", tp=1.5, sl=1.0, rt=0.22):
    return {"id": rid, "coin": coin, "tf": "15m", "signal": "willr14", "th": 0.0,
            "tp": tp, "sl": sl, "rt": rt, "winrate": 80.0, "trades": 90}


def test_screen_fails_the_fee_check_without_building_a_list():
    asked = []

    def lists_for(rows):
        asked.extend(r["id"] for r in rows)
        return {r["id"]: {"trades": _days(3, 3, 0, 0), "end_ms": END} for r in rows}
    passed, failed = dr.screen([_row("A"), _row("B", tp=1.0, sl=0.8)], CFG,
                               lists_for=lists_for)
    assert [r["id"] for r in passed] == ["A"]
    assert "B" in failed and "after fees" in failed["B"]
    assert asked == ["A"], "no list is built for a row the fee check already failed"


def test_screen_fails_a_row_with_no_trade_list():
    passed, failed = dr.screen([_row("A")], CFG, lists_for=lambda rows: {})
    assert passed == [] and "no trade list" in failed["A"]


def test_the_flag_is_the_since_time():
    assert dr.enabled({"daytime_rule": {"since": 1791360000}}) == 1791360000
    assert dr.enabled({}) is None and dr.enabled({"daytime_rule": {}}) is None
