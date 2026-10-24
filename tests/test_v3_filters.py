"""The four Backtest v3 filters (decisions doc docs/superpowers/specs/2026-10-23-
backtest-v3-part2-decisions.md, "The filters"), each judged at a candle's
ORDER minute and reading only what was known by then. Instants are real UTC
times: Oct 23, 2026 is a Friday, Oct 26 a Monday, and New York is on summer
time (UTC-4) until Nov 01, 2026."""
import calendar

import pytest

from tradingagents import v3_filters as vfl

H = 3_600_000
DAY = 24 * H
M = 60_000
F0 = calendar.timegm((2026, 6, 1, 0, 0, 0)) * 1000          # a UTC midnight


def _utc(*ymdhm):
    return calendar.timegm((*ymdhm, 0)) * 1000


def test_busy_hours_keeps_weekdays_for_crypto_and_new_york_hours_for_stock_tokens():
    fri, sat = _utc(2026, 10, 23, 23, 0), _utc(2026, 10, 24, 0, 0)
    sun, mon = _utc(2026, 10, 25, 23, 59), _utc(2026, 10, 26, 0, 0)
    for kind in ("crypto", "metals", "indices"):
        long_ok, short_ok, flag = vfl.masks("busy_hours", sym="X_USDT", kind=kind,
                                            order_ms=[fri, sat, sun, mon])
        assert long_ok == short_ok == [True, False, False, True], kind
        assert flag == [""] * 4
    # Monday Oct 26, 2026 in New York: 9:30am is 13:30 UTC, the 4:00pm close 20:00 UTC (out)
    at = [_utc(2026, 10, 26, 13, 29), _utc(2026, 10, 26, 13, 30), _utc(2026, 10, 26, 19, 59),
          _utc(2026, 10, 26, 20, 0), _utc(2026, 10, 24, 15, 0)]
    long_ok, _short, _flag = vfl.masks("busy_hours", sym="AAPL_USDT", kind="stocks", order_ms=at)
    assert long_ok == [False, True, True, False, False]


def _mood_plan():
    # BTC's daily closes known at F0 + 1 day (up), + 2 days (down), + 3 days (up)
    return {"mood": {"t": [F0 + DAY, F0 + 2 * DAY, F0 + 3 * DAY], "up": [1, 0, 1]}}


def test_btc_mood_lets_an_alts_longs_through_only_on_days_btc_closed_above_its_average():
    at = [F0 + DAY, F0 + 2 * DAY - 1, F0 + 2 * DAY, F0 + 3 * DAY + 5 * H, F0 + DAY - 1,
          F0 + 4 * DAY + 1]
    long_ok, short_ok, flag = vfl.masks("btc_mood", sym="ETH_USDT", kind="crypto", order_ms=at,
                                        plan=_mood_plan())
    # up, still the up day 1 ms before the down close, down, up again; before the first close
    # and more than a day after the last the mood is not known: the signal passes, counted
    assert long_ok == [True, True, False, True, True, True]
    assert flag == ["", "", "", "", "mood_unknown", "mood_unknown"]
    assert short_ok == [True] * 6, "shorts are never filtered by BTC's mood"
    for sym, kind in (("BTC_USDT", "crypto"), ("XAU_USDT", "metals")):
        long_ok, _s, _f = vfl.masks("btc_mood", sym=sym, kind=kind, order_ms=at,
                                    plan=_mood_plan())
        assert long_ok == [True] * 6, f"{sym} is not an alt-coin"


def _funding(n=120, spikes=None, offset_ms=0):
    """Settlements every 8 hours from F0 (+ offset), 0.01% each, `spikes` {index: rate}."""
    spikes = spikes or {}
    return [{"settle_ms": F0 + k * 8 * H + offset_ms, "rate": spikes.get(k, 0.0001),
             "cycle_h": 8} for k in range(n)]


def test_funding_side_skips_a_long_at_the_top_tenth_and_a_short_at_the_bottom_tenth():
    fund = _funding(spikes={100: 0.0010, 110: -0.0010})
    # an hour after settlement 100 (F0 + 801h) the 30 days before hold settlements 11..100:
    # 90 of them. Only 1 is >= 0.10% (itself): 1 <= 10% of 90 = 9, the top tenth - no long. 90
    # are <= it, so a short is fine
    after_spike = F0 + 801 * H
    # an hour after settlement 101 (back at 0.01%): all 90 are >= it and 89 <= it - neither tail:
    # the usual rate is never "the top", however many settlements tie with it
    after_calm = F0 + 809 * H
    # an hour after settlement 110 (-0.10%): only itself is <= it - no short
    after_dip = F0 + 881 * H
    long_ok, short_ok, flag = vfl.masks("funding_side", sym="X_USDT", kind="crypto",
                                        order_ms=[after_spike, after_calm, after_dip],
                                        funding=fund)
    assert (long_ok, short_ok) == ([False, True, True], [True, True, False])
    assert flag == ["", "", ""]


def test_funding_side_passes_and_counts_a_signal_whose_30_days_the_history_does_not_cover():
    fund = _funding()
    # the history answers from one cycle before its first settlement (F0 - 8h), so 30 days of it
    # end no earlier than F0 - 8h + 720h = F0 + 712h; and it answers to one cycle after its last
    # (F0 + 952h + 8h)
    at = [F0 + 711 * H, F0 + 712 * H, F0 + 960 * H, F0 + 960 * H + 1]
    long_ok, short_ok, flag = vfl.masks("funding_side", sym="X_USDT", kind="crypto",
                                        order_ms=at, funding=fund)
    assert flag == ["funding_unknown", "", "", "funding_unknown"]
    assert long_ok == short_ok == [True] * 4
    assert vfl.masks("funding_side", sym="X_USDT", kind="crypto", order_ms=[F0],
                     funding=[])[2] == ["funding_unknown"], "no history judges nothing"


def test_funding_minutes_blocks_orders_within_5_minutes_of_a_recorded_settlement():
    # Gate settles a few seconds after the hour (BTC_USDT, Oct 2026: 0-5 s); here 2 s
    fund = _funding(offset_ms=2000)
    s8 = F0 + 8 * H + 2000                                        # the settlement after F0 + 8h
    at = [F0 + 8 * H, s8 + 5 * M, s8 + 5 * M + 1, s8 - 5 * M, s8 - 5 * M - 1, F0 + 4 * H]
    ok, short_ok, flag = vfl.masks("funding_minutes", sym="X_USDT", kind="crypto", order_ms=at,
                                   funding=fund, cycle_h=8)
    assert ok == short_ok == [False, False, True, False, True, True]
    assert flag == [""] * 6


def test_funding_minutes_uses_the_contracts_cycle_where_no_settlement_was_recorded():
    # before the history: the 8-hour cycle from 00:00 UTC - F0 - 16h is a settlement, F0 - 12h
    # is not; a coin with no history at all on a 4-hour cycle: 04:00 UTC is, 3:55 and 4:05 are
    # inside 5 minutes of it, 3:54:59.999 is not
    fund = _funding(offset_ms=2000)
    ok, _s, flag = vfl.masks("funding_minutes", sym="X_USDT", kind="crypto",
                             order_ms=[F0 - 16 * H, F0 - 12 * H], funding=fund, cycle_h=8)
    assert ok == [False, True] and flag == ["settle_by_cycle"] * 2
    four = F0 + 4 * H
    ok, _s, flag = vfl.masks("funding_minutes", sym="X_USDT", kind="crypto",
                             order_ms=[four, four - 5 * M, four + 5 * M, four - 5 * M - 1,
                                       F0 + 2 * H], funding=[], cycle_h=4)
    assert ok == [False, False, False, True, True]
    # on daily candles every order goes in at 00:00 UTC, a settlement on every cycle there is
    ok, _s, _f = vfl.masks("funding_minutes", sym="X_USDT", kind="crypto",
                           order_ms=[F0 + k * DAY for k in range(5)], funding=[], cycle_h=8)
    assert ok == [False] * 5


def test_no_filter_lets_everything_through_and_an_unknown_one_is_refused():
    assert vfl.masks("none", sym="X_USDT", kind="crypto", order_ms=[F0, F0 + H]) == \
        ([True, True], [True, True], ["", ""])
    with pytest.raises(ValueError, match="crash_guard"):
        vfl.masks("crash_guard", sym="X_USDT", kind="crypto", order_ms=[F0])
    assert vfl.NAMES[1:] == ("btc_mood", "busy_hours", "funding_side", "funding_minutes")
