"""The four Backtest v3 families (decisions doc docs/superpowers/specs/2026-10-23-
backtest-v3-part2-decisions.md, "The families"): each rule's signals worked by
hand on small candle series, their exits, their lead-ins, their universes, and
the count of combinations the luck correction divides by."""
import calendar
import random

import pytest

from tradingagents import v3_families as vf

DAY = 86_400_000
OCT1 = calendar.timegm((2026, 10, 1, 0, 0, 0)) * 1000        # a Thursday
MONDAYS = [OCT1 + k * DAY for k in (4, 11, 18, 25)]          # Oct 05, 12, 19, 26, 2026


def _bars(c, h=None, lo=None, t0=OCT1, bar=DAY):
    c = [float(x) for x in c]
    return {"t": [t0 + k * bar for k in range(len(c))], "o": c, "c": c,
            "h": [float(x) for x in (h if h is not None else c)],
            "l": [float(x) for x in (lo if lo is not None else c)]}


def test_seventy_combinations_and_thirty_verdicts_are_counted_whether_or_not_they_trade():
    # (3 + 2 + 2 + 2 settings) x their timeframes = 6 + 2 + 2 + 4 = 14, each alone and with each
    # of the 4 filters: 70 combinations (the luck correction's count); one verdict per family,
    # timeframe and filter: 10 + 5 + 5 + 10 = 30
    assert len(vf.combos()) == len(set(vf.combos())) == 70
    assert len(vf.judged()) == 30
    assert ("v3_trend", "n100", "4h", "funding_minutes") in vf.combos()
    assert ("v3_snap", "k1.5", "1h", "none") in vf.combos()
    assert vf.setting_key("v3_snap", 2.0) == "k2" and vf.setting_key("v3_strength", 3) == "k3"
    ids = {vf.verdict_id(*g) for g in vf.judged()}
    assert len(ids) == 30, "every verdict its own id"


def test_a_verdict_id_can_never_equal_a_v1_or_v2_id():
    from tradingagents import backtest_report as br

    for fam, tf, filt in vf.judged():
        mine = vf.verdict_id(fam, tf, filt)
        # the same combination hashed with no resolution (v1) or with v2's "1m" is another id
        assert mine != br.row_code("ALL", tf, fam, 0.0, 0.0, 0.0, "flat", plan=f"judged|{filt}")
        assert mine != br.row_code("ALL", tf, fam, 0.0, 0.0, 0.0, "flat", plan=f"judged|{filt}",
                                   res="1m")


def test_a_trend_longs_above_a_rising_average_and_calm_coins_short_the_mirror():
    # n = 3 on daily candles closing 1, 2, ... 10: the 3-day average at candle i is i, under the
    # close i + 1, and 5 days earlier it was i - 5 - but it exists only from candle 2, so the
    # first candle with both is 7
    assert vf.rule("v3_trend", 3, "1d", _bars(range(1, 11))) == [0] * 7 + [1] * 3
    # closing 10, 9, ... 1: the average 11 - i sits over the close and under its value 5 days
    # earlier - a short
    assert vf.rule("v3_trend", 3, "1d", _bars(range(10, 0, -1))) == [0] * 7 + [-1] * 3


def test_a_trend_on_4h_reads_six_candles_a_day():
    # n = 1 day on 4h candles is a 6-candle average, and "5 days earlier" is 30 candles: with
    # rising closes the first candle with both is 5 + 30 = 35
    assert vf.rule("v3_trend", 1, "4h", _bars(range(1, 41), bar=4 * 3_600_000)) == \
        [0] * 35 + [1] * 5


def test_a_trend_needs_its_average_to_be_moving_the_same_way_as_the_close():
    # n = 3, 5 days back. Closing 10 x7 then 4, 4, 6: the 3-day average is 10, then 8, 6 and 4.67.
    # Candles 7 and 8 sit under a FALLING average (8 and 6, each under its value 5 days earlier,
    # 10) - shorts. Candle 9's close 6 is above its average 4.67, but that average has fallen
    # from 10: not a long
    assert vf.rule("v3_trend", 3, "1d", _bars([10] * 7 + [4, 4, 6])) == [0] * 7 + [-1, -1, 0]
    # the mirror: closing 1 x7 then 7, 7, 5: the averages are 3, 5 and 6.33 over a 1 - longs at
    # candles 7 and 8; candle 9's close 5 is under its average, which has RISEN: not a short
    assert vf.rule("v3_trend", 3, "1d", _bars([1] * 7 + [7, 7, 5])) == [0] * 7 + [1, 1, 0]


def _drift(step, jump):
    """110 daily candles drifting `step` a day from 100, candle 108 jumping to `jump`; every
    candle's high and low half a dollar either side of its close."""
    c = [100 + step * k for k in range(110)]
    c[108] = jump
    return _bars(c, [x + 0.5 for x in c], [x - 0.5 for x in c])


def test_a_breakout_closes_over_the_last_n_days_highs_only_while_the_100_day_average_rises():
    # N = 3. Candle i's close, 100 + 0.1i, is 0.4 UNDER the high of candle i - 1, so the drift
    # never breaks out; candle 108 jumps to 115.0 over that candle's 111.2. The 100-day average
    # at 108 against 103: (110.4 + 110.5 + 110.6 + 110.7 + 115.0 - 100.4 - 100.5 - 100.6 - 100.7
    # - 100.8) / 100 = +0.542, rising. (Before candle 104 the average 5 days back does not exist)
    assert vf.rule("v3_breakout", 3, "1d", _drift(0.1, 115.0)) == [0] * 108 + [1, 0]
    # the same jump while the average FALLS (a drift of -0.1: -0.242 over those 5 days): no long
    assert vf.rule("v3_breakout", 3, "1d", _drift(-0.1, 115.0)) == [0] * 110
    # the mirror: a falling drift whose candle 108 drops to 85.0, under the last 3 days' lows
    # (88.8 at the lowest), while the average falls by 0.542: a calm contract's short
    assert vf.rule("v3_breakout", 3, "1d", _drift(-0.1, 85.0)) == [0] * 108 + [-1, 0]


def test_a_breakout_shorts_only_under_a_falling_average_and_a_tie_is_no_breakout():
    # candle 108 drops to 85.0, under the last 3 days' lows, while the 100-day average RISES:
    # (110.4 + 110.5 + 110.6 + 110.7 + 85.0 - 100.4 - 100.5 - 100.6 - 100.7 - 100.8) / 100 =
    # +0.242 - no short
    assert vf.rule("v3_breakout", 3, "1d", _drift(0.1, 85.0)) == [0] * 110
    # a close exactly ON the highest high of the last 3 days (candle 107's, 110.7 + 0.5 = 111.2)
    # is not over it ...
    top = 100 + 0.1 * 107 + 0.5
    assert vf.rule("v3_breakout", 3, "1d", _drift(0.1, top)) == [0] * 110
    # ... and a hundredth above it is
    assert vf.rule("v3_breakout", 3, "1d", _drift(0.1, top + 0.01)) == [0] * 108 + [1, 0]


def _ranked_plan():
    a_to_g = [f"{x}_USDT" for x in "ABCDEFG"]
    return {"months": ["2026-10"], "liquid": {"2026-10": a_to_g}, "calm": {"2026-10": []},
            "strength": {str(MONDAYS[0]): a_to_g,                                     # D 4th
                         str(MONDAYS[1]): ["D_USDT"] + [s for s in a_to_g if s != "D_USDT"],
                         str(MONDAYS[2]): [s for s in a_to_g if s != "D_USDT"] + ["D_USDT"],
                         str(MONDAYS[3]): ["A_USDT"]}}                                # D unranked


def test_strength_longs_a_top_k_coin_at_its_monday_rank_and_forces_it_out_past_the_top_2k():
    plan, bars = _ranked_plan(), _bars([100.0] * 28)                  # Oct 01 - Oct 28, 2026
    # Monday Oct 05's rank is taken from the closes AT Oct 05 00:00, so its order goes in right
    # then: the signal candle is the one CLOSING at Oct 05 00:00 - Sunday Oct 04's, candle 3
    sundays = [3, 10, 17, 24]
    # K = 3: D is 4th (Oct 05), 1st (Oct 12), 7th (Oct 19), unranked (Oct 26)
    got = vf.rule("v3_strength", 3, "1d", bars, sym="D_USDT", plan=plan)
    assert [got[i] for i in sundays] == [0, 1, 0, 0] and sum(got) == 1
    out = vf.forced("v3_strength", 3, "1d", bars, sym="D_USDT", plan=plan)
    assert [out[i] for i in sundays] == [False, False, True, True], "7th > 2K = 6; unranked"
    assert sum(out) == 2, "only a candle closing at a Monday 00:00 forces anything"
    # K = 5: 4th is in, and 7th is inside 2K = 10
    got = vf.rule("v3_strength", 5, "1d", bars, sym="D_USDT", plan=plan)
    assert [got[i] for i in sundays] == [1, 1, 0, 0]
    out = vf.forced("v3_strength", 5, "1d", bars, sym="D_USDT", plan=plan)
    assert [out[i] for i in sundays] == [False, False, False, True]
    assert vf.forced("v3_trend", 20, "1d", bars) is None
    assert [i for i, x in enumerate(vf.entry_days("v3_strength", bars, "1d")) if x] == sundays
    # the Monday candles themselves open AT the rank: an order on one goes in a day late
    assert [got[i] for i in (4, 11, 18, 25)] == [0, 0, 0, 0]
    assert vf.entry_days("v3_trend", bars, "1d") == [True] * 28


def _d_at(place):
    """A ranking of the coins A-G with D in the given place (1 = best)."""
    others = ["A_USDT", "B_USDT", "C_USDT", "E_USDT", "F_USDT", "G_USDT"]
    return others[:place - 1] + ["D_USDT"] + others[place - 1:]


def test_strength_takes_the_kth_place_and_keeps_the_2kth_but_not_the_one_after():
    a_to_g = [f"{x}_USDT" for x in "ABCDEFG"]
    plan = {"months": ["2026-10"], "liquid": {"2026-10": a_to_g}, "calm": {"2026-10": []},
            "strength": {str(MONDAYS[0]): _d_at(3), str(MONDAYS[1]): _d_at(6),
                         str(MONDAYS[2]): _d_at(7)}}              # D is 3rd, 6th and 7th
    bars, sundays = _bars([100.0] * 28), [3, 10, 17]
    # K = 3: the 3rd place (Oct 05) is in; the 6th (Oct 12) and the 7th (Oct 19) are not
    got = vf.rule("v3_strength", 3, "1d", bars, sym="D_USDT", plan=plan)
    assert [got[i] for i in sundays] == [1, 0, 0]
    # 2K = 6: the 6th place is kept, the 7th goes
    out = vf.forced("v3_strength", 3, "1d", bars, sym="D_USDT", plan=plan)
    assert [out[i] for i in sundays] == [False, False, True]


def test_forced_reads_only_a_monday_the_plan_ranked():
    # 35 daily candles, Oct 01 - Nov 04. Candle 24 (Sunday Oct 25) closes at Monday Oct 26, which
    # the plan ranked without D: a ranking that no longer holds the coin forces it out. Candle 31
    # (Sunday Nov 01) closes at Monday Nov 02, which the plan never ranked (its last ranking is
    # Oct 26's - a window that ends on a Monday has none for its own end): no rank was taken
    # there, so nothing is forced, and a trade still open books END, not RANK
    plan, bars = _ranked_plan(), _bars([100.0] * 35)
    out = vf.forced("v3_strength", 3, "1d", bars, sym="D_USDT", plan=plan)
    assert out[24] is True and out[31] is False
    # Oct 19 (D 7th, past 2K = 6) and Oct 26 (D missing) - and nothing else
    assert [i for i, x in enumerate(out) if x] == [17, 24]
    # a ranking with nobody in it still forces: the coin is out of it
    empty = {**plan, "strength": {**plan["strength"], str(MONDAYS[3]): []}}
    assert vf.forced("v3_strength", 3, "1d", bars, sym="D_USDT", plan=empty)[24] is True
    # and a plan that ranked no Monday at all forces nothing
    assert not any(vf.forced("v3_strength", 3, "1d", bars, sym="D_USDT",
                             plan={**plan, "strength": {}}))


def test_the_strength_candle_is_the_one_closing_at_midnight_on_whatever_timeframe_it_is_asked():
    h4 = 4 * 3_600_000
    # 4h candles from Sat Oct 03 00:00: the one closing at Mon Oct 05 00:00 opens Sunday 20:00,
    # 44 hours in - candle 11
    four = _bars([100.0] * 18, t0=MONDAYS[0] - 12 * h4, bar=h4)
    assert [i for i, x in enumerate(vf.entry_days("v3_strength", four, "4h")) if x] == [11]
    # daily candles opening at 03:00 UTC close at Monday 03:00, which is no rank instant
    odd = _bars([100.0] * 4, t0=MONDAYS[0] - 2 * DAY + 3 * 3_600_000)
    assert not any(vf.entry_days("v3_strength", odd, "1d"))


def test_a_snap_back_signals_a_close_k_atrs_past_its_20_candle_average():
    # 20 flat candles (high 100.5, low 99.5, close 100: a true range of 1.0), then candle 20 with
    # high 100.0, low 98.0, close 98.3 (true range 2.0). Its 20-candle average is
    # (19 x 100 + 98.3) / 20 = 99.915 and ATR(20) (19 x 1.0 + 2.0) / 20 = 1.05: k = 1.5 needs a
    # close at or under 99.915 - 1.575 = 98.34 (98.3 is), k = 2.0 under 97.815 (it is not)
    h, lo = [100.5] * 20 + [100.0], [99.5] * 20 + [98.0]
    dip = _bars([100.0] * 20 + [98.3], h, lo, bar=3_600_000)
    assert vf.rule("v3_snap", 1.5, "1h", dip) == [0] * 20 + [1]
    assert vf.rule("v3_snap", 2.0, "1h", dip) == [0] * 21
    # the mirror: high 102.0, low 100.0, close 101.7 - over 100.085 + 1.575 = 101.66, a short
    pop = _bars([100.0] * 20 + [101.7], [100.5] * 20 + [102.0], [99.5] * 20 + [100.0],
                bar=3_600_000)
    assert vf.rule("v3_snap", 1.5, "1h", pop) == [0] * 20 + [-1]
    # a market that never moved has no range to measure a snap by
    assert vf.rule("v3_snap", 1.5, "1h", _bars([100.0] * 21, bar=3_600_000)) == [0] * 21


def _snap_tape(last_h, last_lo, last_c):
    """20 flat candles (high 100.5, low 99.5, close 100: a true range of 1.0), then one more."""
    return _bars([100.0] * 20 + [last_c], [100.5] * 20 + [last_h], [99.5] * 20 + [last_lo],
                 bar=3_600_000)


def test_a_snap_is_a_close_at_or_past_the_band_and_k_is_read_as_written():
    # every number here is exact in binary. Candle 20: high 100.0, low 95.25, close 97.5 (a true
    # range of 4.75): the 20-candle average is (19 x 100 + 97.5) / 20 = 99.875, ATR(20) is
    # (19 x 1.0 + 4.75) / 20 = 1.1875, and k = 2.0 puts the band at 99.875 - 2.375 = 97.5 - the
    # close is ON it, which counts
    assert vf.rule("v3_snap", 2.0, "1h", _snap_tape(100.0, 95.25, 97.5)) == [0] * 20 + [1]
    # the mirror: high 104.75, low 100.0, close 102.5 - average 100.125, band 100.125 + 2.375
    assert vf.rule("v3_snap", 2.0, "1h", _snap_tape(104.75, 100.0, 102.5)) == [0] * 20 + [-1]
    # k = 1.5 is not k = 1: high 100.0, low 98.0, close 98.5 (a true range of 2.0) - average
    # 99.925, ATR 1.05: under the k = 1 band (98.875) but not under the k = 1.5 band (98.35)
    assert vf.rule("v3_snap", 1.5, "1h", _snap_tape(100.0, 98.0, 98.5)) == [0] * 21


def test_each_family_exits_by_its_own_rule():
    assert vf.exit_spec("v3_trend", 50, "4h") == {"kind": "trail", "atr_mult": 3.0, "ma_n": 300}
    assert vf.exit_spec("v3_trend", 20, "1d")["ma_n"] == 20
    assert vf.exit_spec("v3_breakout", 20, "1d") == {"kind": "trail", "atr_mult": 3.0,
                                                     "ma_n": None}
    assert vf.exit_spec("v3_strength", 3, "1d")["ma_n"] is None
    assert vf.exit_spec("v3_snap", 1.5, "1h") == {"kind": "snap", "mean_n": 20,
                                                  "stop_atr": 3.0, "max_bars": 24}


def test_the_lead_in_is_300_candles_or_the_rules_own_lookback_when_longer():
    # v3_trend n = 100 on 4h: a 600-candle average and 30 candles back = 630; n = 50: 330
    assert vf.lead("v3_trend", 100, "4h") == 630 and vf.lead("v3_trend", 50, "4h") == 330
    assert vf.lead("v3_trend", 20, "4h") == 300 and vf.lead("v3_trend", 100, "1d") == 300
    assert vf.lookback("v3_breakout", 50, "1d") == 105 and vf.lead("v3_snap", 2.0, "1h") == 300


def test_each_family_trades_only_the_sides_its_universe_allows_in_each_month():
    sep, octo = calendar.timegm((2026, 9, 15, 0, 0, 0)) * 1000, OCT1 + 14 * DAY
    plan = {"months": ["2026-09", "2026-10"], "liquid": {"2026-09": ["X_USDT"], "2026-10": []},
            "calm": {"2026-09": [], "2026-10": ["X_USDT"]}}
    # liquid in September (longs), calm in October (both sides)
    assert vf.sides_allowed("v3_trend", "X_USDT", plan, [sep, octo]) == ([True, True],
                                                                         [False, True])
    assert vf.sides_allowed("v3_strength", "X_USDT", plan, [sep, octo]) == ([True, False],
                                                                            [False, False])
    assert vf.sides_allowed("v3_snap", "X_USDT", plan, [sep, octo]) == ([False, True],
                                                                        [False, True])
    assert vf.applies(plan, "v3_snap", "X_USDT") and not vf.applies(plan, "v3_snap", "Y_USDT")
    assert not vf.applies({**plan, "calm": {"2026-09": [], "2026-10": []}}, "v3_snap", "X_USDT")


def test_the_atr_families_read_20_candles_and_a_breakout_trades_the_sides_a_trend_does():
    # snap reads its 20-candle average and ATR(20); strength reads only the plan, and its trail
    # needs ATR(20)'s 20 candles
    assert vf.lookback("v3_snap", 1.5, "1h") == vf.lookback("v3_snap", 2.0, "4h") == 20
    assert vf.lookback("v3_strength", 3, "1d") == 20
    sep, octo = calendar.timegm((2026, 9, 15, 0, 0, 0)) * 1000, OCT1 + 14 * DAY
    plan = {"months": ["2026-09", "2026-10"], "liquid": {"2026-09": ["X_USDT"], "2026-10": []},
            "calm": {"2026-09": [], "2026-10": ["X_USDT"]}}
    # liquid in September (longs), calm in October (both sides) - the trend's own row
    assert vf.sides_allowed("v3_breakout", "X_USDT", plan, [sep, octo]) == ([True, True],
                                                                            [False, True])


def test_an_unknown_family_is_refused_by_name():
    with pytest.raises(ValueError, match="v3_nope"):
        vf.exit_spec("v3_nope", 1, "1d")
    with pytest.raises(ValueError, match="v3_nope"):
        vf.rule("v3_nope", 1, "1d", _bars([1.0]))
    with pytest.raises(ValueError, match="v3_nope"):
        vf.lookback("v3_nope", 1, "1d")
    with pytest.raises(ValueError, match="v3_nope"):
        vf.lead("v3_nope", 1, "1d")
    # v3_strength is decided by the plan's Monday ranks and nothing else: without them it says so
    bars = _bars([100.0] * 28)
    for plan in (None, {}, {"months": ["2026-10"]}):
        with pytest.raises(ValueError, match="needs the plan's Monday ranks"):
            vf.rule("v3_strength", 3, "1d", bars, sym="D_USDT", plan=plan)
        with pytest.raises(ValueError, match="needs the plan's Monday ranks"):
            vf.forced("v3_strength", 3, "1d", bars, sym="D_USDT", plan=plan)


def _walk_bars(n, bar, seed):
    """n candles of a seeded random walk from Oct 01, 2026 00:00 UTC, `bar` ms long, in drift
    regimes of 150 candles (+0.4% a candle, then -0.4%) so every rule fires both ways: each close
    is the last one moved by a 2%-sigma step, with a high and a low up to 1% either side."""
    rnd = random.Random(seed)
    px, close, high, low = 100.0, [], [], []
    for k in range(n):
        new = px * (1 + rnd.gauss(0.004 if (k // 150) % 2 == 0 else -0.004, 0.02))
        high.append(max(px, new) * (1 + 0.01 * rnd.random()))
        low.append(min(px, new) * (1 - 0.01 * rnd.random()))
        close.append(new)
        px = new
    return _bars(close, high, low, bar=bar)


def _ranked_series(bars, seed):
    """A plan whose Monday ranks cover the daily series: D's place in a 12-coin list is drawn
    from 1-12 or absent, and one Monday in ten is not ranked at all - so top-K membership, the 2K
    band, a coin missing from a ranking and an unranked Monday all occur."""
    rnd = random.Random(seed)
    others = [f"{x}_USDT" for x in "ABCEFGHIJKL"]
    ranks, monday = {}, MONDAYS[0]
    while monday <= bars["t"][-1] + DAY:
        place = rnd.choice([*range(1, 13), None])
        if rnd.random() >= 0.1:
            ranks[str(monday)] = (others if place is None
                                  else others[:place - 1] + ["D_USDT"] + others[place - 1:])
        monday += 7 * DAY
    return {"months": [], "liquid": {}, "calm": {}, "strength": ranks}


def _plan_at(plan, now, later):
    """The plan as it stood at `now` (a candle's close): the Mondays ranked by then; the later
    ones either gone ("cut") or with their ranking turned upside down ("replaced")."""
    ranks = {}
    for key, ranking in plan["strength"].items():
        if int(key) <= now:
            ranks[key] = ranking
        elif later == "replaced":
            ranks[key] = ranking[::-1]
    return {**plan, "strength": ranks}


def _scaled_after(col, k):
    """The column with every candle from the cut on moved: x3, x0.3, x3, ... - one factor a
    candle, the same for its open, high, low and close."""
    return col[:k] + [x * (0.3 if j % 2 else 3.0) for j, x in enumerate(col[k:])]


def _same(what, got, want):
    assert len(got) == len(want), f"{what}: {len(got)} values where {len(want)} were expected"
    first = next((i for i, (a, b) in enumerate(zip(got, want, strict=True)) if a != b), None)
    assert first is None, f"{what}: candle {first} changes with what comes after the cut"


def test_no_rule_reads_a_candle_after_the_one_it_signals_on():
    """Every family, setting and timeframe, on a seeded random walk long enough for its lookback:
    the rule, the forced exit and the entry days of the series CUT at about ten points equal the
    whole series' first part, AND that first part does not move when everything after the cut is
    REPLACED (each later candle x3 or x0.3, each later Monday's ranking upside down). Neither
    alone is enough: a decision is mostly 0, and a peek at a smooth average rarely flips one (the
    Crypto-Predictor port's planted peek moved 0 of 13 decisions and was caught by comparing the
    readings) - so the replacement; and it leaves the candle times alone - so the cut. Some cuts
    end ON a candle the series decides on, where a peek one candle past the cut changes that
    very decision."""
    bar = {"1h": 3_600_000, "4h": 4 * 3_600_000, "1d": DAY}
    series = {}
    for seed, tf in enumerate(bar, start=1):
        # the longest lookback of any setting that runs on this timeframe (trend n = 100 on 4h: 630)
        longest = max(vf.lookback(f, v, tf) for f, d in vf.FAMILIES.items() if tf in d["tfs"]
                      for v in d["settings"])
        series[tf] = _walk_bars(longest + 250, bar[tf], seed)
    plan = _ranked_series(series["1d"], seed=7)
    for fam, spec in vf.FAMILIES.items():
        for tf in spec["tfs"]:
            bars, n = series[tf], len(series[tf]["t"])
            for value in spec["settings"]:
                what = f"{fam} {vf.setting_key(fam, value)} {tf}"
                whole = vf.rule(fam, value, tf, bars, sym="D_USDT", plan=plan)
                out = vf.forced(fam, value, tf, bars, sym="D_USDT", plan=plan)
                days = vf.entry_days(fam, bars, tf)
                decided = [i for i in range(n) if whole[i] or (out and out[i])]
                assert len(decided) >= 8, (
                    f"{what}: only {len(decided)} candles decided - nothing to cut at")
                spread = [decided[round(j * (len(decided) - 1) / 3)] for j in range(4)]
                # just past the lookback, the middle of what can signal, the last-but-one candle,
                # ON four decided candles and just before three of them
                lb = vf.lookback(fam, value, tf)
                cuts = {lb + 1, (lb + n) // 2, n - 1} | {i + 1 for i in spread} | set(spread[1:])
                for k in sorted(cuts):
                    now = bars["t"][k - 1] + bar[tf]
                    cut = {name: col[:k] for name, col in bars.items()}
                    moved = {name: _scaled_after(col, k)
                             for name, col in bars.items() if name != "t"}
                    moved["t"] = bars["t"]
                    for kind, part in (("cut", cut), ("replaced", moved)):
                        plan_k = _plan_at(plan, now, kind)
                        where = f"{what}, {kind} at {k}"
                        got = vf.rule(fam, value, tf, part, sym="D_USDT", plan=plan_k)
                        _same(f"{where}, rule", got[:k], whole[:k])
                        got = vf.forced(fam, value, tf, part, sym="D_USDT", plan=plan_k)
                        if out is None:
                            assert got is None, f"{where}: forced is only for strength"
                        else:
                            _same(f"{where}, forced", got[:k], out[:k])
                        got = vf.entry_days(fam, part, tf)
                        _same(f"{where}, entry days", got[:k], days[:k])
