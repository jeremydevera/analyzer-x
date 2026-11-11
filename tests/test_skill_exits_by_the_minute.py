"""A stop or a target is settled by the MINUTE where the minutes are known (Nov 11, 2026).

Operator: *"if i will be using 1m candle do you think it will be more precise"* - *"okay then change
backtest and the practice rooms together, so they keep matching each other"*. The signal still reads
the closed candle; once a trade is open, each later candle's minutes are walked in order and the first
minute that touched the stop or the target ends it. Everything here is hand-made on one timeline: 1h
candles opening at T0 + k hours, the minutes under them 60 seconds apart.
"""
import numpy as np
import pandas as pd
import pytest

from tradingagents import skill_bt as sb

pytestmark = pytest.mark.unit

H = 3_600_000
T0 = 1_790_000_000_000 // H * H          # an hour boundary, so every candle opens on the hour
FEE, SLIP = 0.00075, 0.0003


class _Sig:
    def __init__(self, entry=False, exit=False, direction="long"):
        self.entry, self.exit, self.direction = entry, exit, direction


def _frame(closes):
    idx = pd.DatetimeIndex(pd.to_datetime([T0 + k * H for k in range(len(closes))], unit="ms"))
    c = np.asarray(closes, dtype=float)
    return pd.DataFrame({"open": c, "high": c, "low": c, "close": c, "volume": 1.0}, index=idx)


def _minutes(k, lows, highs=None, start_k=None, n_candles=1):
    """A Fine over candle(s) starting at candle `start_k` (default k): 60 minutes each; `lows` is a
    {minute_index_within_candle_k: low} map, everything else sits at 100.0."""
    start_k = k if start_k is None else start_k
    t, h, lo = [], [], []
    for kk in range(start_k, start_k + n_candles):
        for m in range(60):
            t.append(T0 + kk * H + m * 60_000)
            h.append((highs or {}).get((kk, m), 100.0))
            lo.append(lows.get((kk, m), 100.0))
    return sb.Fine(t, h, lo, T0 + start_k * H, T0 + (start_k + n_candles) * H)


def _enter_then(sig_after, fine, *, stop=0.01, target=None, closes=(100.0, 100.0, 100.0), tally=None):
    """Candle 0 buys at its close (100 + the gap); `sig_after` are the signals of the later candles."""
    df = _frame(list(closes))
    sigs = [_Sig(entry=True)] + list(sig_after)
    return sb.walk(df, sigs, stop=stop, fee=FEE, slip=SLIP, target=target, bar_ms=H, fine=fine, tally=tally)


def test_a_wick_through_the_stop_ends_the_trade_in_its_minute_though_the_candle_closes_back_up():
    """Candle 1 closes at 100 (above the stop) but minute 7 of it traded down to 98.9: the stop at
    1% below the 100.03 entry (99.0297) was touched at minute 7 - a real exchange stops it there."""
    fine = _minutes(1, {(1, 7): 98.9})
    tally: dict = {}
    got = _enter_then([_Sig(), _Sig()], fine, tally=tally)
    assert [t["why"] for t in got] == ["SL"]
    t = got[0]
    entry = 100.0 * (1 + SLIP)
    sl_px = entry * 0.99
    assert t["at"] == T0 + 1 * H + 7 * 60_000                         # the minute it ended in
    assert t["exit_ms"] == T0 + 1 * H                                  # the candle it ended in, as ever
    assert t["exit_px"] == pytest.approx(sl_px * (1 - SLIP))          # the stop's price plus the gap
    assert tally["minute"] == 1 and tally.get("unclear", 0) == 0


def test_the_same_trade_on_candles_only_is_not_stopped_at_all():
    """The rule of before, with no minutes: the close (100.0) never reached the stop, so the wick is
    invisible and the trade rides to the END - the optimism the minutes remove."""
    got = _enter_then([_Sig(), _Sig()], None)
    assert [t["why"] for t in got] == ["END"]


def test_the_target_is_settled_by_the_minute_too():
    fine = _minutes(1, {}, highs={(1, 20): 102.5})
    got = _enter_then([_Sig(), _Sig()], fine, stop=0.01, target=0.02)
    assert [t["why"] for t in got] == ["TP"]
    entry = 100.0 * (1 + SLIP)
    assert got[0]["at"] == T0 + 1 * H + 20 * 60_000
    assert got[0]["exit_px"] == pytest.approx(entry * 1.02 * (1 - SLIP))


def test_both_barriers_in_one_minute_is_the_stop_and_is_counted_unclear():
    fine = _minutes(1, {(1, 5): 98.0}, highs={(1, 5): 103.0})
    tally: dict = {}
    got = _enter_then([_Sig(), _Sig()], fine, stop=0.01, target=0.02, tally=tally)
    assert got[0]["why"] == "SL" and got[0]["at"] == T0 + 1 * H + 5 * 60_000
    assert tally["unclear"] == 1


def test_the_first_minute_to_touch_wins_even_when_the_other_comes_later_in_the_candle():
    fine = _minutes(1, {(1, 40): 98.0}, highs={(1, 10): 103.0})
    got = _enter_then([_Sig(), _Sig()], fine, stop=0.01, target=0.02)
    assert got[0]["why"] == "TP" and got[0]["at"] == T0 + 1 * H + 10 * 60_000


def test_a_short_is_settled_the_mirror_way():
    """A short's stop is ABOVE its entry: a minute high of 101.5 touches 1% above 99.97."""
    df = _frame([100.0, 100.0, 100.0])
    sigs = [_Sig(entry=True, direction="short"), _Sig(), _Sig()]
    fine = _minutes(1, {}, highs={(1, 33): 101.5})
    got = sb.walk(df, sigs, stop=0.01, fee=FEE, slip=SLIP, bar_ms=H, fine=fine)
    entry = 100.0 * (1 - SLIP)
    assert got[0]["why"] == "SL" and got[0]["at"] == T0 + 1 * H + 33 * 60_000
    assert got[0]["exit_px"] == pytest.approx(entry * 1.01 * (1 + SLIP))


def test_a_candle_the_minutes_do_not_cover_keeps_the_candle_rule_and_is_counted():
    """Minutes only for candle 2: candle 1 is settled by its close (nothing touched), candle 2 by its
    minutes."""
    fine = _minutes(2, {(2, 3): 98.0})
    tally: dict = {}
    got = _enter_then([_Sig(), _Sig()], fine, tally=tally)
    assert got[0]["why"] == "SL" and got[0]["at"] == T0 + 2 * H + 3 * 60_000
    assert tally == {"candle": 1, "minute": 1, "unclear": 0}


def test_a_candle_only_partly_covered_is_not_settled_by_the_minute():
    t = [T0 + 1 * H + m * 60_000 for m in range(30)]           # the first half-hour only
    fine = sb.Fine(t, [100.0] * 30, [98.0] * 30, T0 + 1 * H, T0 + 1 * H + 30 * 60_000)
    assert not fine.covers(T0 + 1 * H, H)
    got = _enter_then([_Sig(), _Sig()], fine)
    assert [t_["why"] for t_ in got] == ["END"] and "at" not in got[0]


def test_the_signal_exit_at_the_close_is_unchanged_when_the_minutes_touch_nothing():
    fine = _minutes(1, {}, n_candles=2)
    got = _enter_then([_Sig(exit=True), _Sig()], fine, closes=(100.0, 100.4, 100.0))
    assert got[0]["why"] == "SIGNAL" and "at" not in got[0] and got[0]["exit_ms"] == T0 + 1 * H


def test_the_stop_beats_a_signal_exit_on_the_same_candle():
    fine = _minutes(1, {(1, 2): 98.0})
    got = _enter_then([_Sig(exit=True), _Sig()], fine)
    assert got[0]["why"] == "SL" and got[0]["at"] == T0 + 1 * H + 2 * 60_000


def test_a_new_entry_on_the_candle_a_stop_ended_in_still_buys_at_that_close():
    """The candle's signal is the closed candle's: a stop in minute 5 frees the strategy, and the
    entry signal of that same candle buys at its close, as the rule of before did for a close stop."""
    fine = _minutes(1, {(1, 5): 98.0})
    df = _frame([100.0, 100.0, 100.0])
    sigs = [_Sig(entry=True), _Sig(entry=True), _Sig()]
    pos, trade = None, None
    pos, _ = sb.step(None, sigs[0], close=100.0, when_ms=T0, bar_ms=H, stop=0.01, fee=FEE, slip=SLIP)
    pos, trade = sb.step(pos, sigs[1], close=100.0, when_ms=T0 + H, bar_ms=H, stop=0.01, fee=FEE,
                         slip=SLIP, fine=fine)
    assert trade["why"] == "SL" and pos is not None and pos["t"] == T0 + H
    assert df is not None


def test_funding_is_charged_up_to_the_minute_the_trade_ended_in():
    """Settlements: one at minute 3 of candle 1, one at minute 30 (after the stop at minute 7).
    A stop in minute 7 pays only the first; an exit at the candle close would also pay the second,
    which the trade never held through."""
    rows = [{"settle_ms": T0 + 1 * H + 3 * 60_000, "rate": 0.001}, {"settle_ms": T0 + 1 * H + 30 * 60_000, "rate": 0.5}]
    fine = _minutes(1, {(1, 7): 98.0})
    got = sb.walk(_frame([100.0, 100.0, 100.0]), [_Sig(entry=True), _Sig(), _Sig()], stop=0.01, fee=FEE,
                  slip=SLIP, bar_ms=H, fine=fine, funding=sb.Funding(rows))
    assert got[0]["fund"] == pytest.approx(-0.001 * sb.NOTIONAL)      # a long paid +0.1% = a cost: -$0.10


def test_with_no_minutes_walk_is_byte_for_byte_what_it_was():
    df = _frame([100, 101, 99, 100, 102, 98, 100, 101])
    sigs = [_Sig(entry=True), _Sig(), _Sig(exit=True), _Sig(entry=True), _Sig(), _Sig(), _Sig(exit=True), _Sig()]
    a = sb.walk(df, sigs, stop=0.015, fee=FEE, slip=SLIP, bar_ms=H)
    b = sb.walk(df, sigs, stop=0.015, fee=FEE, slip=SLIP, bar_ms=H, fine=None, tally={})
    assert a == b and all("at" not in t for t in a)


def test_a_measured_trade_carries_its_minute_only_when_the_minutes_settled_it():
    fine = _minutes(1, {(1, 7): 98.9})
    combos = [{"strategy": "sma_crossover", "params": {"fast_period": 2, "slow_period": 3}, "stop": 0.01,
               "target": None}]
    df = _frame([100.0, 101.0, 102.0, 103.0, 99.0, 98.0, 101.0, 105.0])
    out = sb.measure(df, combos, fee=FEE, slip=SLIP, bar_ms=H, fine=fine)
    for trade in out[0]["trades"]:
        assert len(trade) in (5, 6)
        if len(trade) == 6:
            assert trade[3] in ("SL", "TP") and trade[5] % 60_000 == 0


def test_read_fine_drops_the_forming_minute_and_says_where_the_minutes_end(monkeypatch):
    import time

    now = int(time.time()) // 60 * 60
    base = now - 5 * 60
    frame = pd.DataFrame({"Date": pd.to_datetime([base + 60 * k for k in range(6)], unit="s"),
                          "High": [101.0] * 6, "Low": [99.0] * 6, "Seconds": [60] * 6})
    got = sb.read_fine("AAA_USDT", base * 1000, minutes=lambda *_a: frame)
    # the sixth minute opens at `now` and is still forming: five minutes are final
    assert len(got.t) == 5 and got.to_ms == now * 1000 and got.from_ms == base * 1000
    empty = sb.read_fine("AAA_USDT", base * 1000, minutes=lambda *_a: frame.iloc[0:0])
    assert len(empty.t) == 0 and not empty.covers(base * 1000, 60_000)


def test_the_minute_window_begins_a_fixed_distance_before_the_days_midnight():
    day = 1_794_355_200_000
    assert sb.fine_from_ms(day) == day - sb.MINUTE_DAYS * 86_400_000
    assert sb.MINUTE_DAYS >= 100        # Forecast v4 walks the 98 days before a day's list
