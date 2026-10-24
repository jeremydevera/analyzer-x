"""Random entries, the luck bar (decisions doc docs/superpowers/specs/2026-10-23-
backtest-v3-part2-decisions.md, "Random entries"): as many entries per month
and side as the real run placed, on candles the combination could have
entered on, seeded so every machine draws the same runs."""
import calendar
import random

from tradingagents import v3_random as vrn

H = 3_600_000
OCT31_22 = calendar.timegm((2026, 10, 31, 22, 0, 0)) * 1000   # the last hours of October


def test_a_seed_is_the_same_on_every_machine():
    # blake2b with digest_size=8 of "BTC_USDT|1d|v3_trend|none|0", read big-endian: not the
    # first 8 bytes of the default 64-byte digest (that one reads 6932095940997299596)
    assert vrn.seed_of("BTC_USDT", "1d", "v3_trend", "none", 0) == 9232730103163168985
    assert vrn.seed_of("BTC_USDT", "1d", "v3_trend", "none", 1) != \
        vrn.seed_of("BTC_USDT", "1d", "v3_trend", "none", 0)


def test_a_draw_is_pinned_to_its_seed_and_takes_longs_then_shorts():
    s = vrn.seed_of("X_USDT", "1h", "v3_snap", "none", 7)
    # Python keeps random()'s sequence for an int seed from version to version: 0.9503..., 0.4640...,
    # 0.1798... The longs' partial shuffle of candles 0-9 swaps 0 with 0 + int(0.9503 x 10) = 9,
    # then 1 with 1 + int(0.4640 x 9) = 5, then 2 with 2 + int(0.1798 x 8) = 3: longs at 9, 5, 3.
    # The two shorts are drawn from the seven candles left
    assert round(random.Random(s).random(), 4) == 0.9503
    cands = {("2026-10", 1): list(range(10)), ("2026-10", -1): list(range(10))}
    wanted = {("2026-10", 1): 3, ("2026-10", -1): 2}
    got = vrn.draw(10, wanted, cands, s)
    assert got == ([0, 0, 0, 1, -1, 1, 0, 0, -1, 1], 0)
    assert vrn.draw(10, wanted, cands, s) == got, "the same seed, the same run"
    assert vrn.draw(10, wanted, cands, s + 1)[0] != got[0]


def test_a_draw_places_only_where_allowed_and_counts_what_it_could_not_place():
    # October: 2 longs wanted, 3 candles allowed; November: 2 shorts wanted, 1 allowed
    cands = {("2026-10", 1): [1, 4, 6], ("2026-11", -1): [8]}
    wanted = {("2026-10", 1): 2, ("2026-11", -1): 2}
    for run in range(20):
        dirs, short_of = vrn.draw(10, wanted, cands, vrn.seed_of("X", run))
        assert sorted(i for i, d in enumerate(dirs) if d == 1) in ([1, 4], [1, 6], [4, 6])
        assert [i for i, d in enumerate(dirs) if d == -1] == [8] and short_of == 1


def test_the_real_runs_entries_are_counted_by_the_month_their_order_went_in():
    # hourly candles from Oct 31, 2026 10:00pm UTC: candle 1's (11:00pm) order goes in at
    # midnight, November 1 - a November entry, though its signal candle is October's
    t = [OCT31_22 + k * H for k in range(6)]
    walked = {"trades": [{"signal_bar": 0, "side": 1}, {"signal_bar": 1, "side": 1}],
              "missed": [{"signal_bar": 3, "side": -1}, {"signal_bar": 4, "side": 1}]}
    assert vrn.entries_by_month(walked, t, H) == {("2026-10", 1): 1, ("2026-11", 1): 2,
                                                  ("2026-11", -1): 1}


def test_candidates_are_the_walks_tradable_candles_by_order_month_and_side():
    t = [OCT31_22 + k * H for k in range(6)]
    long_ok = [True, True, False, True, True, True]
    short_ok = [False, True, True, False, False, True]
    # from candle 1 (the walk's start) to candle 4 (candle 5 has no next candle to fill in)
    assert vrn.candidates(t, H, 1, long_ok, short_ok) == {
        ("2026-11", 1): [1, 3, 4], ("2026-11", -1): [1, 2]}


def test_a_draw_walks_the_months_in_order_longs_then_shorts_on_one_stream():
    # two months, both sides allowed on every candle of the month. The dicts are built OUT of
    # order, so only the module's own ordering can put October before November and longs
    # before shorts; one random() stream runs through all four blocks
    s = vrn.seed_of("Y_USDT", "1d", "v3_trend", "none", 3)
    cands = {("2026-11", -1): list(range(6, 12)), ("2026-10", -1): list(range(6)),
             ("2026-11", 1): list(range(6, 12)), ("2026-10", 1): list(range(6))}
    wanted = {("2026-11", -1): 2, ("2026-10", -1): 1, ("2026-11", 1): 1, ("2026-10", 1): 2}
    assert vrn.draw(12, wanted, cands, s) == ([1, 0, -1, 1, 0, 0, 1, 0, 0, -1, 0, -1], 0)
