"""One hour of Gate's order-book archive in, one cost reading per minute out
(phase 4, spec D11, Oct 10, 2026).

The file's rules, measured: a `set` snapshot first, then every change merged
per 100 ms; positive size = buy side, negative = sell side; `make` ADDS the
size and `take` SUBTRACTS it — BTC Oct 09, 2026 00:00-01:00 replayed this way
equals the 01:00 snapshot on 41,387 of 41,387 levels.
"""
import gzip

import pytest

from tradingagents import book_history as bh

T0 = 1791504000          # Oct 09, 2026 00:00 UTC


def hour(lines):
    return gzip.compress("\n".join(lines).encode())


SNAP = [f"{T0},set,99.5,5.0,1,0", f"{T0},set,99,8.0,1,0",
        f"{T0},set,100,-3.0,1,0", f"{T0},set,100.5,-4.0,1,0",
        f"{T0},set,0.1,1000.0,1,0"]            # a silly far bid, like the real files


def test_each_minute_reads_the_book_as_it_stood():
    raw = hour(SNAP + [f"{T0 + 70},take,100,-3.0,2,1",      # the 100 ask is eaten
                       f"{T0 + 130},make,99.8,2.0,3,1"])    # a new best bid
    got = bh.replay_hour(raw, hour_start=T0, contract_size=1.0, notional_usd=99.75 * 2)
    assert len(got) == 60 and [r["t"] for r in got] == [T0 + 60 * k for k in range(60)]
    m0, m1, m2, m3 = got[:4]
    assert (m0["bid"], m0["ask"]) == (99.5, 100.0)
    assert (m1["bid"], m1["ask"]) == (99.5, 100.0), "the take at +70s is after minute 1"
    assert (m2["bid"], m2["ask"]) == (99.5, 100.5)
    assert (m3["bid"], m3["ask"]) == (99.8, 100.5)
    assert m0["spread"] == pytest.approx(0.5 / 99.75)
    # $199.5 at mid 99.75 is 2 contracts: bought at 100, sold at 99.5
    assert m0["buy"] == pytest.approx(100 / 99.75 - 1)
    assert m0["sell"] == pytest.approx(99.75 / 99.5 - 1)
    assert m0["source"] == "full" and not m0["exhausted"]


def test_the_walk_goes_down_the_book_for_a_bigger_size():
    got = bh.replay_hour(hour(SNAP), hour_start=T0, contract_size=1.0,
                         notional_usd=99.75 * 5)
    # 3 @ 100 + 2 @ 100.5
    assert got[0]["buy"] == pytest.approx((300 + 201) / 5 / 99.75 - 1)


def test_a_book_that_cannot_fill_the_size_says_so():
    got = bh.replay_hour(hour(SNAP), hour_start=T0, contract_size=1.0,
                         notional_usd=99.75 * 50)
    assert got[0]["exhausted"]


def test_a_snapshot_only_hour_answers_every_minute_with_its_opening_book():
    """Sep 30 - Oct 08 12:00, 2026: the archive holds one book an hour."""
    got = bh.replay_hour(hour(SNAP), hour_start=T0, contract_size=1.0,
                         notional_usd=100.0)
    assert all(r["source"] == "snapshot" for r in got)
    assert {(r["bid"], r["ask"]) for r in got} == {(99.5, 100.0)}


def test_a_crossed_book_is_no_reading_never_a_negative_spread():
    raw = hour(SNAP + [f"{T0 + 5},make,100.2,3.0,2,1"])     # a bid above the ask
    got = bh.replay_hour(raw, hour_start=T0, contract_size=1.0, notional_usd=100.0)
    assert got[1] is None
    assert got[0] is not None, "minute 0 was read before the cross"


def test_a_level_taken_past_zero_is_removed_not_kept_negative():
    raw = hour(SNAP + [f"{T0 + 5},take,99.5,7.0,2,1"])      # takes 7 of 5
    got = bh.replay_hour(raw, hour_start=T0, contract_size=1.0, notional_usd=99.0)
    assert got[1]["bid"] == 99.0


def test_events_before_the_hour_or_after_it_change_nothing():
    raw = hour(SNAP + [f"{T0 + 3600},make,99.9,9.0,2,1"])
    got = bh.replay_hour(raw, hour_start=T0, contract_size=1.0, notional_usd=100.0)
    assert got[-1]["bid"] == 99.5


def test_readings_pack_to_arrays_and_back():
    got = bh.replay_hour(hour(SNAP + [f"{T0 + 70},take,100,-3.0,2,1"]),
                         hour_start=T0, contract_size=1.0, notional_usd=100.0)
    packed = bh.pack(got)
    assert packed["t"].dtype.kind == "i" and len(packed["t"]) == 60
    back = bh.reading_at(packed, T0 + 125)
    assert back["ask"] == 100.5 and back["age_s"] == 5
    assert bh.reading_at(packed, T0 - 1) is None
    assert bh.reading_at(packed, T0 + 60 * 59 + 3600 + 1) is None, "older than an hour"


def test_a_day_names_its_missing_failed_and_broken_hours_apart():
    """Final review, Oct 10, 2026 (RCA-2026-10-10-F): every non-200 hour was
    dropped the same way, so a 503 left a day with a hole that was then
    counted as measured for ever, and a truncated file raised and failed the
    coin on every run. Now: 404 = Gate never published it (final), anything
    else that failed = `hours_failed` (the day must be read again), a file
    that does not parse = `hours_bad` (named, the rest of the day kept)."""
    good = hour(SNAP)

    def fetch(u):
        h = int(u.rsplit("-", 1)[1][8:10])
        if h == 3:
            return 404, b""
        if h == 5:
            return 503, b""
        if h == 7:
            raise OSError("connection reset")
        if h == 9:
            return 200, good[: len(good) // 2]          # cut mid-file
        return 200, good
    got = bh.day_readings("BTC_USDT", T0, contract_size=1.0, notional_usd=100,
                          fetch=fetch)
    assert got["hours_read"] == 20
    assert got["hours_missing"] == [T0 + 3 * 3600]
    assert got["hours_failed"] == [T0 + 5 * 3600, T0 + 7 * 3600]
    assert [h for h, _why in got["hours_bad"]] == [T0 + 9 * 3600]


def test_a_decimal_size_level_taken_to_float_dust_is_gone():
    """ETH_USDT Oct 08, 2026 07:00 UTC (RCA-2026-10-30-B): Gate lets 15 contracts
    trade in tenths (ETH, XRP, SOL ...), and a level emptied by tenths keeps a
    float crumb - 2565.15's bid was 60422.5 and ended at 6.5e-12, above the
    old 1e-12 cut - so the dead bid stayed best, the book read CROSSED from
    minute 1 and 59 of 60 minutes gave no reading. Here: 60422.5 less 60000.1,
    422.2 and 0.2 is 1.47e-12 in floats, then the price falls under it."""
    assert 60422.5 - 60000.1 - 422.2 - 0.2 > 1e-12           # the crumb is real
    raw = hour([f"{T0},set,100.5,60422.5,1,0", f"{T0},set,100.3,5.0,1,0",
                f"{T0},set,100.6,-5.0,1,0",
                f"{T0 + 20},take,100.5,60000.1,2,1", f"{T0 + 21},take,100.5,422.2,2,1",
                f"{T0 + 22},take,100.5,0.2,2,1",            # the 100.5 bid is gone
                f"{T0 + 30},make,100.4,-5.0,3,1"])          # a new ask under it
    got = bh.replay_hour(raw, hour_start=T0, contract_size=1.0, notional_usd=100.0)
    assert all(r is not None for r in got), \
        f"{sum(r is None for r in got)} of 60 minutes read as a crossed book"
    assert (got[1]["bid"], got[1]["ask"]) == (100.3, 100.4)


def test_a_real_tenth_of_a_contract_is_kept():
    """The crumb cut must never eat a real level: 0.1 is the smallest size Gate's
    decimal contracts print (ETH's Oct 08, 2026 07:00 UTC file)."""
    raw = hour(SNAP + [f"{T0 + 5},make,99.9,0.1,2,1"])
    got = bh.replay_hour(raw, hour_start=T0, contract_size=1.0, notional_usd=10.0)
    assert got[1]["bid"] == 99.9
