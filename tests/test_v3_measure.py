"""One coin's whole Backtest v3 measurement (decisions doc docs/superpowers/specs/
2026-10-23-backtest-v3-part2-decisions.md, "The window and the split", "What a
machine returns per coin"). Two small worlds on ONE timeline: every candle in
the window is BUILT from its own minutes (RCA-2026-09-12-A); the lead-in
before the window is flat candles the indicators read and nothing trades on.
The unseen days are shortened to 3 here (the real run's are 90)."""
import calendar
import time
import types

import numpy as np
import pandas as pd
import pytest

from tradingagents import book_history as bh, v3_families as vf, v3_measure as vm, v3_universe as vu

M = 60_000
H = 60 * M
DAY = 24 * H
FLAT = (100.1, 99.9)                    # a flat minute: high, low (it "closes" at 100.0)
IV = {"Min60": H, "Hour4": 4 * H, "Day1": DAY}
SPEC = {"contractSize": 0.01, "minVol": 1, "maintenanceMarginRate": 0.005, "maxLeverage": 20,
        "minLeverage": 1, "funding_interval_h": 8}


def _utc(*ymdh):
    return calendar.timegm((*ymdh, 0, 0)) * 1000


class FakeFx:
    """Minutes over [start, end) - flat except `special` {minute ms: (high, low)} - and the
    candles of every interval built from them; 700 flat candles before the window; funding at
    0% every 8 hours from 60 days before; Gate-like listing. `listed`: no candle before it."""

    def __init__(self, start, end, special, listed=None):
        self.start, self.end, self.listed = start, end, listed
        self.t = list(range(start, end, M))
        hl = [special.get(x, FLAT) for x in self.t]
        self.hi, self.lo = [x[0] for x in hl], [x[1] for x in hl]

    def contract_spec(self, sym):
        return dict(SPEC)

    def klines(self, sym, iv, limit):
        bar = IV[iv]
        rows = []
        for o in range(self.start - 700 * bar, self.end, bar):
            if self.listed is not None and o < self.listed:
                continue
            if o < self.start:
                rows.append((o, 100.0, 100.1, 99.9, 100.0))
                continue
            a, b = (o - self.start) // M, (o + bar - self.start) // M
            h, lo = self.hi[a:b], self.lo[a:b]
            rows.append((o, (h[0] + lo[0]) / 2, max(h), min(lo), (h[-1] + lo[-1]) / 2))
        df = pd.DataFrame(rows, columns=["t", "Open", "High", "Low", "Close"])
        df.insert(0, "Date", pd.to_datetime(df.pop("t"), unit="ms"))
        return df.assign(Volume=1.0).tail(limit).reset_index(drop=True)

    def minutes(self, sym, start_s, end_s):
        keep = [k for k, x in enumerate(self.t) if start_s * 1000 <= x <= end_s * 1000]
        return pd.DataFrame({"Date": pd.to_datetime([self.t[k] for k in keep], unit="ms"),
                             "High": [self.hi[k] for k in keep],
                             "Low": [self.lo[k] for k in keep], "Seconds": 60})

    def funding_history(self, sym, since_ms=None):
        return [{"settle_ms": x, "rate": 0.0, "cycle_h": 8}
                for x in range(self.start - 60 * DAY, self.end + 1, 8 * H)]

    def book_cost(self, sym, notional):
        raise AssertionError("the recorded book has minutes: no live read")


def _book(t_s):
    """One recorded reading, buying and selling $100 at 0.02% each: the coin's flat gap."""
    return bh.pack([{"t": t_s, "bid": 99.95, "ask": 100.05, "spread": 0.001, "buy": 0.0002,
                     "sell": 0.0002, "exhausted": False, "source": "full"}])


def _reading(t_s, cost, exhausted=False):
    """One recorded reading: buying and selling the book's $100 at `cost` a side."""
    return {"t": t_s, "bid": 99.95, "ask": 100.05, "spread": 0.001, "buy": cost, "sell": cost,
            "exhausted": exhausted, "source": "full"}


@pytest.fixture()
def gate_floors(monkeypatch):
    import tradingagents.auto_trader as at

    monkeypatch.setattr(at, "maker_fee_floor", lambda *a, **k: 0.0002)
    monkeypatch.setattr(at, "fee_floor", lambda *a, **k: 0.00075)
    monkeypatch.setattr(vm, "UNSEEN_DAYS", 3)


# ---- a calm metal whose hourly candles dip twice: once on the older days, once on the unseen

END_A = _utc(2026, 10, 4, 0)            # a Sunday; the window is Sep 24 - Oct 04, 2026
START_A, SPLIT_A = END_A - 10 * DAY, END_A - 3 * DAY
OLD_DIP, NEW_DIP = _utc(2026, 9, 25, 10), _utc(2026, 10, 3, 10)      # a Friday, a Saturday
EDGE_DIP = SPLIT_A - _utc(1970, 1, 1, 1)                             # the last older hour


def _dips(*hours, depth=0.0):
    """Each dip hour trades 99.2-99.4 (it opens and closes at 99.3); the next hour's first
    minute trades 99.25-99.35, then the market is back at 100."""
    out = {}
    for o in hours:
        out.update({o + m * M: (99.4 - depth, 99.2 - depth) for m in range(60)})
        out[o + H] = (99.35, 99.25)
    return out


def _plan(start, end, calm, liquid=None, strength=None, kinds=None):
    months = sorted(set(calm) | set(liquid or {}))
    return {"start_ms": start, "end_ms": end, "months": months,
            "calm": {m: calm.get(m, []) for m in months},
            "liquid": {m: (liquid or {}).get(m, []) for m in months},
            "strength": strength or {}, "mood": {"t": [], "up": []},
            "kinds": kinds or {"XAU_USDT": "metals"}}


def _metal(monkeypatch, special, calm=None):
    from tradingagents import cost_store

    monkeypatch.setattr(cost_store, "engine_book", lambda *a, **k: _book(START_A // 1000))
    calm = calm or {"2026-09": ["XAU_USDT"], "2026-10": ["XAU_USDT"]}
    return vm.measure_coin("XAU_USDT", _plan(START_A, END_A, calm), runs=3,
                           fx=FakeFx(START_A, END_A, special))


SNAP = vf.combo_key("v3_snap", "k1.5", "1h", "none")


def _snap_pnl():
    # the dip closes at 99.3 under its 20-hour average (19 x 100 + 99.3) / 20 = 99.965; ATR(20) is
    # (19 x 0.2 + 0.8) / 20 = 0.23 (the dip's true range runs from the 100.0 close to 99.2), so
    # the emergency stop is 3 x 0.23 = 0.69 under the entry: a 0.6949% stop, $1 risk = $143.91 of
    # coin = 144 lots of 0.01 x 99.3. Out at the resting 99.965 target: maker in and out
    return 144 * 0.993 * (99.965 / 99.3 - 1 - 2 * 0.0002)


def test_a_coin_is_measured_for_every_family_setting_timeframe_and_filter_it_can_trade(
        monkeypatch, gate_floors):
    rec = _metal(monkeypatch, _dips(OLD_DIP, EDGE_DIP, NEW_DIP))
    # a metal is calm every month: trend (3 settings x 1d, 4h), breakout (2 x 1d), snap
    # (2 x 1h, 4h) - 12 family-setting-timeframes x 5 filters, less funding_minutes on the 5 of
    # them that are 1d (not tried there): 55. Never strength (liquid only)
    assert rec["families"] == ["v3_trend", "v3_breakout", "v3_snap"]
    assert len(rec["combos"]) == 55 and rec["skipped"] == {}
    # funding_minutes is measured on 4h and 1h and in no record of a 1d combination (operator,
    # Oct 27, 2026: it blocks every daily order, so measuring it tests nothing)
    keys = [k.split("|") for k in rec["combos"]]
    assert not [k for k in keys if k[2] == "1d" and k[3] == "funding_minutes"]
    assert {(k[2]) for k in keys if k[3] == "funding_minutes"} == {"4h", "1h"}
    assert sorted(k[3] for k in keys if k[2] == "1d" and k[0] == "v3_trend") == sorted(
        ["none", "btc_mood", "busy_hours", "funding_side"] * 3)
    old, new = rec["combos"][SNAP]["older"], rec["combos"][SNAP]["unseen"]
    # each dip's waiting buy at 99.3 fills in the next hour's first minute (low 99.25) and the
    # second minute (high 100.1) trades through the target. The row ends with the stop and the
    # target the order went in with, as fractions of the 99.3 entry: 3 x ATR 0.23 = 0.69 under
    # it (0.69 / 99.3 = 0.00695) and the 99.965 average over it (0.665 / 99.3 = 0.0067)
    assert old["rows"] == [[OLD_DIP, OLD_DIP + H, OLD_DIP + H + M, 1, pytest.approx(_snap_pnl()),
                            "TP", 0.00695, 0.0067]]
    assert new["rows"] == [[NEW_DIP, NEW_DIP + H, NEW_DIP + H + M, 1,
                            pytest.approx(_snap_pnl()), "TP", 0.00695, 0.0067]]
    assert old["lev"] == [20, 20] and old["notional"] == [pytest.approx(142.99, abs=0.01)] * 2
    assert old["over_book"] == 1, "$143 of coin is more than the $100 a reading walks"
    # a flat market gives the trend and breakout rules nothing
    assert rec["combos"][vf.combo_key("v3_trend", "n20", "1d", "none")]["older"]["rows"] == []


def test_the_older_walk_cannot_see_a_price_after_the_split(monkeypatch, gate_floors):
    calm_world = _metal(monkeypatch, _dips(OLD_DIP, EDGE_DIP, NEW_DIP))
    # the same coin crashing to 50 on the first unseen day: everything older is unchanged, to the
    # bit - a walk that read even one candle past the split would see the crash candle
    crash = {**_dips(OLD_DIP, EDGE_DIP, NEW_DIP),
             **{SPLIT_A + m * M: (60.0, 50.0) for m in range(1440)}}
    crash_world = _metal(monkeypatch, crash)
    for key in calm_world["combos"]:
        assert crash_world["combos"][key]["older"] == calm_world["combos"][key]["older"], key
    assert crash_world["combos"][SNAP]["unseen"] != calm_world["combos"][SNAP]["unseen"]


def test_the_older_walks_data_is_cut_at_the_split():
    # by construction, not by a filter afterwards: the older walk is handed no minute, no order
    # book and no funding settlement after the split (a settlement AT the split is the last one a
    # trade closed there pays; a book stamped at the split is read 3 s after it, so it is out)
    s = SPLIT_A
    pre = {"fine": ([s - M, s, s + M], [1.0, 2.0, 3.0], [1.0, 2.0, 3.0]),
           "book": bh.pack([{"t": (s - M) // 1000, "bid": 1.0, "ask": 1.1, "spread": 0.1,
                             "buy": 0.001, "sell": 0.001, "exhausted": False, "source": "full"},
                            {"t": s // 1000, "bid": 1.0, "ask": 1.1, "spread": 0.1, "buy": 0.001,
                             "sell": 0.001, "exhausted": False, "source": "full"}]),
           "funding": [{"settle_ms": s - 8 * H}, {"settle_ms": s}, {"settle_ms": s + 8 * H}]}
    cut = vm._before(pre, s)
    assert cut["fine"] == ([s - M], [1.0], [1.0])
    assert list(cut["book"]["t"]) == [(s - M) // 1000]
    assert [f["settle_ms"] for f in cut["funding"]] == [s - 8 * H, s]


def test_a_signal_on_the_last_older_candle_trades_in_neither_walk(monkeypatch, gate_floors):
    # the hour before the split dips too: its order would go in AT the split, an unseen minute, so
    # the older walk has no candle to fill it in (counted no_next_bar), and in the unseen walk its
    # signal candle is lead-in, read by the indicators only. On 4h the same dip is the close of
    # the last older candle: (19 x 100 + 99.3) / 20 = 99.965 less 1.5 x (19 x 0.2 + 0.9) / 20 =
    # 99.6125 is over 99.3, a signal there too - and it trades nowhere either
    rec = _metal(monkeypatch, _dips(OLD_DIP, EDGE_DIP, NEW_DIP))
    for key in (SNAP, vf.combo_key("v3_snap", "k1.5", "4h", "none")):
        older, unseen = rec["combos"][key]["older"], rec["combos"][key]["unseen"]
        assert older["counts"]["no_next_bar"] == 1, key
        assert EDGE_DIP not in [r[0] for r in older["rows"] + unseen["rows"]], key
    assert [r[0] for r in rec["combos"][SNAP]["older"]["rows"]] == [OLD_DIP]
    assert [r[0] for r in rec["combos"][SNAP]["unseen"]["rows"]] == [NEW_DIP]


def test_signals_count_only_in_member_months_and_where_the_filter_lets_the_order_in(
        monkeypatch, gate_floors):
    rec = _metal(monkeypatch, _dips(OLD_DIP, EDGE_DIP, NEW_DIP))
    # the unseen dip's order would go in on Saturday Oct 03, 11:00am UTC: busy hours blocks it;
    # the older one is a Friday's
    busy = rec["combos"][vf.combo_key("v3_snap", "k1.5", "1h", "busy_hours")]
    assert len(busy["older"]["rows"]) == 1 and busy["unseen"]["rows"] == []
    assert busy["unseen"]["filter"] == {"signal_candles": 1, "blocked": 1}
    # funding settles at 00:00, 08:00 and 4:00pm UTC: an 11:00am order is never near one
    fm = rec["combos"][vf.combo_key("v3_snap", "k1.5", "1h", "funding_minutes")]
    assert len(fm["unseen"]["rows"]) == 1 and "blocked" not in fm["unseen"]["filter"]
    # calm in September only: the October dip is no signal at all, the September one trades - and
    # the edge dip of Sep 30, 11:00pm UTC, whose order would go in at Oct 01 00:00, is an OCTOBER
    # signal (a signal's month is the month its order goes in), so it is no signal either: no
    # no_next_bar this time
    sep_only = _metal(monkeypatch, _dips(OLD_DIP, EDGE_DIP, NEW_DIP),
                      calm={"2026-09": ["XAU_USDT"], "2026-10": []})
    assert sep_only["combos"][SNAP]["unseen"]["rows"] == []
    assert sep_only["combos"][SNAP]["unseen"]["filter"] == {}
    assert sep_only["combos"][SNAP]["older"]["rows"] == rec["combos"][SNAP]["older"]["rows"]
    assert rec["combos"][SNAP]["older"]["counts"]["no_next_bar"] == 1
    assert "no_next_bar" not in sep_only["combos"][SNAP]["older"]["counts"]


def test_the_coins_own_flat_gap_and_the_books_coverage_come_first(monkeypatch, gate_floors):
    rec = _metal(monkeypatch, _dips(OLD_DIP, EDGE_DIP, NEW_DIP))
    pre = rec["pre"]
    assert pre["flat_slip"] == pytest.approx(0.0002)
    # the one reading is stamped at the window's first second: before the split, on the older days
    assert pre["flat_slip_source"] == (
        "the median of its 1 recorded minutes whose book did not run out, 1 of them on the older days")
    # it answers its own minute and the 60 after it: 61 of the older days' 7 x 1,440 minutes;
    # nothing of the unseen days
    assert pre["coverage_older"] == pytest.approx(61 / (7 * 1440))
    assert pre["coverage_unseen"] == 0.0
    assert pre["contract"]["max_lev"] == 20 and pre["minutes"] == 10 * 1440
    assert rec["windows"]["1h"]["older_candles"] == 7 * 24
    assert rec["windows"]["1h"]["unseen_candles"] == 3 * 24
    assert rec["windows"]["1h"]["split"].endswith(("am", "pm"))
    # the unseen days, Oct 01 - Oct 04, 2026, fall in one month
    assert rec["unseen_months"] == ["2026-10"]


def test_the_flat_gaps_source_says_how_many_of_its_minutes_lie_on_the_older_days(
        monkeypatch, gate_floors):
    from tradingagents import cost_store

    plan = _plan(START_A, END_A, {"2026-09": ["XAU_USDT"], "2026-10": ["XAU_USDT"]})
    first, split, day = START_A // 1000, SPLIT_A // 1000, DAY // 1000

    def pre_of(readings):
        monkeypatch.setattr(cost_store, "engine_book", lambda *a, **k: bh.pack(readings))
        return vm.measure_coin("XAU_USDT", plan, runs=1, fx=FakeFx(START_A, END_A, {}))["pre"]

    # four readings: on the older days Sep 25 (0.02% a side) and Sep 26 (5%, but its book ran
    # out); on the unseen ones, one stamped AT the split (0.04%: the book 3 s after it, an unseen
    # price) and one an hour later (0.06%). The gap is the median of the three whose book did not
    # run out, 0.02% 0.04% 0.06%, which is 0.04%: a figure read partly off unseen days. The source
    # says ONE of those three minutes is on the older days: the book that ran out counts in
    # neither number, and the reading at the split is already unseen
    pre = pre_of([_reading(first + day, 0.0002), _reading(first + 2 * day, 0.05, True),
                  _reading(split, 0.0004), _reading(split + 3600, 0.0006)])
    assert pre["flat_slip"] == pytest.approx(0.0004)
    assert pre["flat_slip_source"] == (
        "the median of its 3 recorded minutes whose book did not run out, 1 of them on the older days")
    # what a real coin is today: the store's 61 days all lie after the split, so the gap every
    # older exit pays comes from minutes none of which is on the older days (the median of 0.04%
    # and 0.06% is 0.05%), and the older days have no reading of their own
    pre = pre_of([_reading(split, 0.0004), _reading(split + 3600, 0.0006)])
    assert pre["flat_slip"] == pytest.approx(0.0005)
    assert pre["flat_slip_source"] == (
        "the median of its 2 recorded minutes whose book did not run out, 0 of them on the older days")
    assert pre["coverage_older"] == 0.0
    # with no reading of their own, the older days keep the whole window's figure, and say so
    assert pre["flat_slip_older"] == pytest.approx(0.0005)
    assert pre["flat_slip_older_source"] == (
        "no reading of its own on the older days: the median of its 2 recorded minutes whose "
        "book did not run out, 0 of them on the older days")


def test_random_runs_are_seeded_and_entered_like_the_real_run(monkeypatch, gate_floors):
    rec = _metal(monkeypatch, _dips(OLD_DIP, EDGE_DIP, NEW_DIP))
    again = _metal(monkeypatch, _dips(OLD_DIP, EDGE_DIP, NEW_DIP))
    runs = rec["combos"][SNAP]["random"]
    assert len(runs) == 3 and runs == again["combos"][SNAP]["random"], "seeded"
    # the real unseen run placed one order (October, long), so each run places one, on an
    # October hour; on a flat hour a snap has no average to aim at and does not trade
    assert all(n in (0, 1) for n, _p in runs) and rec["combos"][SNAP]["random_short"] == 0
    # a filter that blocked the real order leaves the random runs nothing to match
    busy = rec["combos"][vf.combo_key("v3_snap", "k1.5", "1h", "busy_hours")]
    assert busy["random"] == [[0, 0.0]] * 3


def test_the_risk_reaches_every_walk_and_a_risk_under_one_lot_trades_nothing(monkeypatch,
                                                                            gate_floors):
    from tradingagents import cost_store

    monkeypatch.setattr(cost_store, "engine_book", lambda *a, **k: _book(START_A // 1000))
    plan = _plan(START_A, END_A, {"2026-09": ["XAU_USDT"], "2026-10": ["XAU_USDT"]})
    rec = vm.measure_coin("XAU_USDT", plan, runs=1, fx=FakeFx(START_A, END_A, _dips(OLD_DIP)))
    assert rec["risk_usd"] == 1.0, "the spec's $1 by default"
    # $2 risk: $287.82 of coin at the same 0.6949% stop = 289 lots of 0.993 (at $1 it was 144:
    # lots round down, which is why a risk is measured, never rescaled afterwards)
    two = vm.measure_coin("XAU_USDT", plan, runs=1, risk_usd=2.0,
                          fx=FakeFx(START_A, END_A, _dips(OLD_DIP)))
    (row,) = two["combos"][SNAP]["older"]["rows"]
    assert row[4] == pytest.approx(289 * 0.993 * (99.965 / 99.3 - 1 - 2 * 0.0002))
    # half a cent of risk is $0.72 of coin, under one $0.99 lot: no trade, and it is counted
    tiny = vm.measure_coin("XAU_USDT", plan, runs=1, risk_usd=0.005,
                           fx=FakeFx(START_A, END_A, _dips(OLD_DIP)))
    old = tiny["combos"][SNAP]["older"]
    assert old["rows"] == [] and old["counts"] == {"too_small": 1}


def test_a_young_coin_is_measured_on_what_exists_and_one_listed_after_the_split_is_named(
        monkeypatch, gate_floors):
    from tradingagents import cost_store
    from tradingagents.positions_view import fmt_when

    monkeypatch.setattr(cost_store, "engine_book", lambda *a, **k: _book(START_A // 1000))
    plan = _plan(START_A, END_A, {"2026-09": ["XAU_USDT"], "2026-10": ["XAU_USDT"]})
    # listed Sep 29, 2026: two older days (Sep 29, 30) and the three unseen ones - measured, its
    # window starting where its candles do, never at the plan's start
    young = vm.measure_coin("XAU_USDT", plan, runs=1,
                            fx=FakeFx(START_A, END_A, {}, listed=START_A + 5 * DAY))
    assert young["skipped"] == {} and young["windows"]["1d"]["older_candles"] == 2
    assert young["windows"]["1d"]["start"] == fmt_when((START_A + 5 * DAY) / 1000)
    # listed on the first unseen day: no older candle on any timeframe - nothing to choose a
    # setting on, so every timeframe is skipped and says why
    late = vm.measure_coin("XAU_USDT", plan, runs=1,
                           fx=FakeFx(START_A, END_A, {}, listed=SPLIT_A))
    assert late["combos"] == {}
    assert late["skipped"] == {"1h": "0 older and 72 unseen 1h candles",
                               "4h": "0 older and 18 unseen 4h candles",
                               "1d": "0 older and 3 unseen 1d candles"}


def test_a_coin_in_no_familys_universe_is_named_not_measured(monkeypatch, gate_floors):
    rec = vm.measure_coin("AAPL_USDT", _plan(START_A, END_A, {"2026-09": []},
                                             kinds={"AAPL_USDT": "stocks"}),
                          runs=3, fx=FakeFx(START_A, END_A, {}))
    assert rec["combos"] == {} and rec["why"] == "in no family's universe in any month of the plan"


def test_a_record_carries_the_build_of_its_plan_beside_the_plans_end(monkeypatch, gate_floors):
    # Fix round 1 of Task 9 (ruled Oct 24, 2026): every build of one UTC day ends on one instant, so
    # the end cannot say which plan a coin was measured under. A plan built or loaded carries its
    # own id; a hand-made one is fingerprinted by its content. The stamp is made before the coin's
    # universe is looked at, so a coin in no universe carries it too
    plan = _plan(START_A, END_A, {"2026-09": []}, kinds={"AAPL_USDT": "stocks"})
    fx = FakeFx(START_A, END_A, {})
    hand_made = vm.measure_coin("AAPL_USDT", plan, runs=3, fx=fx)
    assert hand_made["plan_id"] == vu.plan_id(plan) and hand_made["plan_end_ms"] == END_A
    loaded = vm.measure_coin("AAPL_USDT", {**plan, "id": "0123456789abcdef"}, runs=3, fx=fx)
    assert loaded["plan_id"] == "0123456789abcdef"
    # the same end and window with one group changed is another build, and so another stamp
    other = vm.measure_coin("AAPL_USDT", {**plan, "calm": {"2026-09": ["XAU_USDT"]}}, runs=3, fx=fx)
    assert other["plan_end_ms"] == END_A and other["plan_id"] != hand_made["plan_id"]


# ---- a liquid coin the Monday ranks pick, then drop: v3_strength's forced exit -----------

END_B = _utc(2026, 10, 7, 0)            # a Wednesday; the window is Sep 20 - Oct 07, 2026
START_B, SPLIT_B = END_B - 17 * DAY, END_B - 3 * DAY
SEP21, SEP28, OCT5 = _utc(2026, 9, 21, 0), _utc(2026, 9, 28, 0), _utc(2026, 10, 5, 0)


def test_strength_enters_at_a_monday_rank_and_is_forced_out_when_it_drops_past_the_top_2k(
        monkeypatch, gate_floors):
    from tradingagents import cost_store

    others = [f"C{k}_USDT" for k in range(9)]
    plan = _plan(START_B, END_B, {}, liquid={"2026-09": ["ABC_USDT"] + others,
                                             "2026-10": ["ABC_USDT"] + others},
                 strength={str(SEP21): ["ABC_USDT"] + others,          # 1st
                           str(SEP28): others[:8] + ["ABC_USDT"],      # 9th
                           str(OCT5): ["ABC_USDT"] + others},          # 1st
                 kinds={"ABC_USDT": "crypto"})
    # the book also holds a reading stamped AT the split - the book 3 s after it, an unseen
    # price - whose book ran out (so it is no part of the flat gap) and costs 5% to sell into
    split_book = {"t": SPLIT_B // 1000, "bid": 99.0, "ask": 101.0, "spread": 0.02, "buy": 0.05,
                  "sell": 0.05, "exhausted": True, "source": "full"}
    book = cost_store.merge(_book(START_B // 1000), bh.pack([split_book]))
    monkeypatch.setattr(cost_store, "engine_book", lambda *a, **k: book)
    # the unseen days, Oct 04 - Oct 06, trade 100.9-101.1: the order at Sunday Oct 04's 101.0 close
    # goes in at Monday Oct 05 00:00 - the instant Oct 05's rank is taken - and fills in that minute
    up = {SPLIT_B + m * M: (101.1, 100.9) for m in range(3 * 1440)}
    rec = vm.measure_coin("ABC_USDT", plan, runs=6, fx=FakeFx(START_B, END_B, up))
    assert rec["families"] == ["v3_trend", "v3_breakout", "v3_strength"]
    # 1st in the rank of Monday Sep 21 00:00, read off Sunday Sep 20's close (the window's first
    # candle): the order goes in at that instant and the flat day's 99.9 low fills it. ATR(20) of
    # flat days is 0.2: a 0.6 trail, a 0.6% stop, $1 risk = 166 lots of 0.01 x $100. 9th on Sep 28,
    # past 2K = 6: out at Sunday Sep 27's close - Monday 00:00 - 100.0, at the market: taker 0.075%
    # plus the coin's 0.02% gap, and the maker 0.02% in
    k3 = rec["combos"][vf.combo_key("v3_strength", "k3", "1d", "none")]
    # a 0.6 trail under a 100.0 entry is a 0.006 stop, and a trail has no target
    assert k3["older"]["rows"] == [[SEP21 - DAY, SEP21, SEP28, 1,
                                    pytest.approx(-166.0 * (0.0002 + 0.00075 + 0.0002)), "RANK",
                                    0.006, None]]
    # K = 5: 9th is inside 2K = 10, so the trade is still open at the split and closes there, at
    # the last older close, 100.0 - paying the coin's flat 0.02% gap, never the 5% of the reading
    # stamped at the split, which the older walk cannot see
    k5 = rec["combos"][vf.combo_key("v3_strength", "k5", "1d", "none")]
    assert k5["older"]["rows"] == [[SEP21 - DAY, SEP21, SPLIT_B, 1,
                                    pytest.approx(-166.0 * (0.0002 + 0.00075 + 0.0002)), "END",
                                    0.006, None]]
    assert k5["older"]["counts"]["cost_unmeasured"] == 1
    # unseen: 1st at Monday Oct 05's rank, read off Sunday Oct 04's close - in at Oct 05 00:00 at
    # 101.0, open at the window's end. An order a day late (the plan's first text) would have been
    # in at Oct 06 00:00
    assert [(r[0], r[1], r[5]) for r in k3["unseen"]["rows"]] == [(SPLIT_B, OCT5, "END")]
    # strength only ever enters on a candle closing at a Monday 00:00, and Sunday Oct 04's is the
    # unseen days' one: every random run enters exactly where the real one did, and makes what it
    # made
    real = k3["unseen"]["rows"][0][4]
    assert k3["random"] == [[1, pytest.approx(real)]] * 6


def _strength_rec(monkeypatch, up, runs):
    """World B's coin, ABC - 1st in the ranks of Sep 21 and Oct 05, 9th on Sep 28 - over the
    market `up`."""
    from tradingagents import cost_store

    others = [f"C{k}_USDT" for k in range(9)]
    plan = _plan(START_B, END_B, {}, liquid={"2026-09": ["ABC_USDT"] + others,
                                             "2026-10": ["ABC_USDT"] + others},
                 strength={str(SEP21): ["ABC_USDT"] + others,
                           str(SEP28): others[:8] + ["ABC_USDT"],
                           str(OCT5): ["ABC_USDT"] + others},
                 kinds={"ABC_USDT": "crypto"})
    monkeypatch.setattr(cost_store, "engine_book", lambda *a, **k: _book(START_B // 1000))
    return vm.measure_coin("ABC_USDT", plan, runs=runs, fx=FakeFx(START_B, END_B, up))


def test_random_strength_entries_are_drawn_only_on_the_candles_that_close_at_a_monday(
        monkeypatch, gate_floors):
    # Oct 04 and Oct 05 trade 100.9-101.1 (both close at 101.0); Oct 06 trades 101.4-101.6, ABOVE
    # them. The real order - Sunday Oct 04's close, in at Monday Oct 05 00:00 - fills in that
    # minute (the low 100.9 is under 101.0) and the trade is open when the window ends, at Oct 06's
    # close, 101.5. ATR(20) is (19 x 0.2 + 1.1) / 20 = 0.245 (Oct 04's true range runs from the
    # 100.0 close to the 101.1 high): a 0.735 trail, a 0.7277% stop, $1 risk = $137.42 of coin =
    # 136 lots of 0.01 x 101.0, and it makes 136 x 1.01 x (101.5 / 101.0 - 1 - 0.00115) = +$0.5220
    # (the maker 0.02% in; out, the taker 0.075% and the coin's 0.02% gap)
    up = {SPLIT_B + m * M: (101.1, 100.9) for m in range(2 * 1440)}
    up.update({SPLIT_B + 2 * DAY + m * M: (101.6, 101.4) for m in range(1440)})
    rec = _strength_rec(monkeypatch, up, runs=20)
    k3 = rec["combos"][vf.combo_key("v3_strength", "k3", "1d", "none")]
    real = k3["unseen"]["rows"][0][4]
    assert real == pytest.approx(136 * 1.01 * (101.5 / 101.0 - 1 - 0.00115))
    # a random entry may be drawn on two unseen candles, Oct 04's and Oct 05's (Oct 06's has no
    # next candle to fill in). Only Oct 04's closes at a Monday 00:00, where a rank is taken; an
    # order resting at Oct 05's 101.0 close would go in on Tuesday and never fill - Oct 06's low is
    # 101.4 - so a run drawn there would be [0, 0.0]. All 20 runs must enter where the real one did
    assert k3["random"] == [[1, pytest.approx(real)]] * 20


def test_every_walk_of_a_strength_combo_carries_the_rank_exit_flags_of_its_own_view(
        monkeypatch, gate_floors):
    # only strength is measured, so every walk below is one of its walks. 2 settings x 5 filters
    # = 10 combos less funding_minutes, which is not tried on 1d (00:00 UTC is a settlement hour):
    # 8 combos, each walked on the older days and on the unseen ones: 16 real walks. The real
    # unseen order (Monday Oct 05 00:00, 1st in the rank) gets in under every filter tried, so
    # all 8 combos draw 4 random runs each: 32 more. All 48 are handed the rank exit's flags, one
    # per candle of the view they walk
    monkeypatch.setattr(vf, "FAMILIES", {"v3_strength": vf.FAMILIES["v3_strength"]})
    seen = []
    real_walk = vm.ve.walk

    def spy(bars, dirs, spec, **kw):
        seen.append((len(bars["t"]), kw.get("forced")))
        return real_walk(bars, dirs, spec, **kw)

    monkeypatch.setattr(vm.ve, "walk", spy)
    up = {SPLIT_B + m * M: (101.1, 100.9) for m in range(3 * 1440)}
    _strength_rec(monkeypatch, up, runs=4)
    assert len(seen) == 16 + 8 * 4
    assert all(flags is not None and len(flags) == n for n, flags in seen)


# ---- a market falling $1.00 a day: who may sell short, and when ---------------------------------
# World A's calendar (Sep 24 - Oct 04, 2026). The market is flat at 100.0 for `flat_days`, then
# falls in a straight line, every minute trading its price +- 0.1: a day opens 1.00 under the last
# one's open and closes at 99.0007 less the days already fallen (the last minute's middle, 1,439 /
# 1,440 of a dollar down). The first day of the fall closes under its 20-day average, (19 x 100.0 +
# 99.0007) / 20 = 99.95, which is under the 100.0 it stood at five days earlier: v3_trend n=20 on
# 1d signals a short that day and every day after. v3_trend and v3_breakout may short only in the
# calm group.

def _fall(flat_days=0):
    out = {}
    for k in range(10 * 1440):
        p = 100.0 - max(0, k - flat_days * 1440) / 1440
        out[START_A + k * M] = (p + 0.1, p - 0.1)
    return out


def _fall_world(monkeypatch, kind, calm, liquid, flat_days=0):
    from tradingagents import cost_store

    monkeypatch.setattr(cost_store, "engine_book", lambda *a, **k: _book(START_A // 1000))
    plan = _plan(START_A, END_A, calm, liquid=liquid, kinds={"XYZ_USDT": kind})
    return vm.measure_coin("XYZ_USDT", plan, runs=1, fx=FakeFx(START_A, END_A, _fall(flat_days)))


def _trade_rows(rec):
    return [(key, row) for key, c in rec["combos"].items() for part in ("older", "unseen")
            for row in c[part]["rows"]]


def test_only_a_calm_coin_goes_short_in_a_falling_market(monkeypatch, gate_floors):
    months = ["2026-09", "2026-10"]
    calm = _fall_world(monkeypatch, "metals", {m: ["XYZ_USDT"] for m in months}, None)
    liquid = _fall_world(monkeypatch, "crypto", {}, {m: ["XYZ_USDT"] for m in months})
    # the calm coin sells short on the first day's signal: signal Thu Sep 24, the order in at Fri
    # Sep 25 00:00 (that minute trades up to 99.1, through the 99.0007 close) and the trade is
    # still open when the older days end, closed at the split (END) at 93.0007, six days down.
    # ATR(20) is (19 x 0.2 + 1.1993) / 20 = 0.24997 (the day's range, from its 100.1 high down to
    # its 98.9007 low, is the widest of the three true-range readings): a 0.7499 trail, a 0.7575%
    # stop, $1 risk = $132.02 of coin = 133 lots of 0.01 x 99.0007, and it makes
    # 133 x 0.990007 x (6 / 99.0007 - 0.00115) = +$7.83
    entry = 100 - 1439 / 1440
    first = calm["combos"][vf.combo_key("v3_trend", "n20", "1d", "none")]["older"]["rows"][0]
    assert first[:4] == [START_A, START_A + DAY, SPLIT_A, -1] and first[5] == "END"
    assert first[4] == pytest.approx(133 * 0.01 * entry * (6 / entry - 0.00115))
    # a coin that is liquid but not calm may only buy, and a fall gives it nothing to buy - though
    # its families are measured (trend and breakout apply to it)
    assert "v3_trend" in liquid["families"] and liquid["combos"]
    assert _trade_rows(liquid) == []


def test_busy_hours_holds_a_weekend_short(monkeypatch, gate_floors):
    # flat on Thursday Sep 24, falling from Friday. Friday's close gives the first short signal,
    # whose order would go in on Saturday 00:00; Saturday's gives one for Sunday 00:00 - busy_hours
    # holds both (2 of the 5 older signals: Fri, Sat, Sun, Mon, Tue - Wednesday's candle closes at
    # the split and has no next candle). Sunday's candle closes at Monday 00:00 and gives the
    # first order it lets in: signal Sunday Sep 27, in at Monday Sep 28 00:00, closed at the split
    months = ["2026-09", "2026-10"]
    rec = _fall_world(monkeypatch, "metals", {m: ["XYZ_USDT"] for m in months}, None, flat_days=1)
    busy = rec["combos"][vf.combo_key("v3_trend", "n20", "1d", "busy_hours")]["older"]
    assert [r[:4] for r in busy["rows"]] == [[START_A + 3 * DAY, START_A + 4 * DAY, SPLIT_A, -1]]
    assert busy["filter"] == {"signal_candles": 5, "blocked": 2}
    # and whatever the family and the bar, every order busy_hours lets in goes in on a weekday
    bar = {"1h": H, "4h": 4 * H, "1d": DAY}
    rows = [(key, row) for key, row in _trade_rows(rec) if key.endswith("|busy_hours")]
    assert rows and all(time.gmtime((row[0] + bar[key.split("|")[2]]) / 1000).tm_wday < 5
                        for key, row in rows)


def test_the_flat_gap_falls_back_to_a_live_read_then_to_the_paper_figure_and_says_so():
    import tradingagents.auto_trader as at
    from tradingagents import cost_store

    class Live:
        def __init__(self, slip):
            self.slip = slip

        def book_cost(self, sym, notional):
            if self.slip is None:
                raise RuntimeError("book unreadable")
            return {"slippage": self.slip}

    empty = cost_store.empty()
    assert vm.flat_gap("X_USDT", empty, fx=Live(0.0004)) == (
        0.0004, "one live reading of its book (no minute recorded)")
    assert vm.flat_gap("X_USDT", empty, fx=Live(0.0))[0] == at.PAPER_SLIPPAGE, "never a free 0"
    # and the figure then is the app's own, not a reading of the book: the words say so
    assert vm.flat_gap("X_USDT", empty, fx=Live(0.0))[1] == (
        "the app's paper figure: its one live reading said 0 (no minute recorded)")

    # a reading that is not a positive finite number - below 0, not a number, infinite, or none at
    # all - is no reading either: the paper figure again, never a None figure (the walk would die on
    # a bare TypeError) and never an infinite cost, and the words print what the book said
    class Silent:                           # a book that answers with no slippage at all
        def book_cost(self, sym, notional):
            return {}

    for fx, said in ((Live(-0.0001), "-0.0001"), (Live(float("nan")), "nan"),
                     (Live(float("inf")), "inf"), (Silent(), "None")):
        assert vm.flat_gap("X_USDT", empty, fx=fx) == (
            at.PAPER_SLIPPAGE,
            f"the app's paper figure: its one live reading said {said} (no minute recorded)")
    assert vm.flat_gap("X_USDT", None, fx=Live(None)) == (
        at.PAPER_SLIPPAGE, "the app's paper figure: no book could be read (RuntimeError)")


def test_usual_slip_is_the_median_of_the_minutes_whose_book_did_not_run_out():
    from tradingagents import cost_store

    rows = [{"t": 60 * k, "bid": 1.0, "ask": 1.1, "spread": 0.1, "buy": b, "sell": s,
             "exhausted": x, "source": "full"}
            for k, (b, s, x) in enumerate([(0.0001, 0.0003, False), (0.0002, 0.0004, False),
                                           (0.0005, 0.0007, False), (0.01, 0.01, True)])]
    # (buy + sell) / 2 of the three that did not run out: 0.0002, 0.0003, 0.0006 - median 0.0003
    assert cost_store.usual_slip(bh.pack(rows)) == (pytest.approx(0.0003), 3)
    assert cost_store.usual_slip(cost_store.empty()) == (None, 0)
    assert cost_store.usual_slip(None) == (None, 0)


def test_the_candles_are_cut_at_the_plans_end_never_at_the_clock():
    t = [END_A - 2 * H, END_A - H, END_A]
    df = pd.DataFrame({"Date": pd.to_datetime(t, unit="ms"), "Open": [1.0, 2.0, 3.0],
                       "High": [1.0, 2.0, 3.0], "Low": [1.0, 2.0, 3.0], "Close": [1.0, 2.0, 3.0]})
    got = vm.bars_of(df, H, END_A)
    assert got["t"] == [END_A - 2 * H, END_A - H] and got["c"] == [1.0, 2.0]
    assert np.int64(got["t"][0]) == END_A - 2 * H


# ---- wires the tests above leave open: funding, the risk, the random runs' seeds, draws and data

class SpikedFunding(FakeFx):
    """Funding at 0.01% every 8 hours, except Friday Sep 25's 08:00 settlement, at 0.09%."""

    def funding_history(self, sym, since_ms=None):
        return [{"settle_ms": x, "rate": 0.0009 if x == _utc(2026, 9, 25, 8) else 0.0001,
                 "cycle_h": 8}
                for x in range(self.start - 60 * DAY, self.end + 1, 8 * H)]


class FailingFunding(FakeFx):
    def funding_history(self, sym, since_ms=None):
        raise RuntimeError("funding history for XAU_USDT is incomplete: page 3 failed")


class DipLeadFx(FakeFx):
    """World A, but the two hours 30 and 29 before the window dip as well: a signal in the lead-in
    (the dip hour closes at 99.3, the next hour trades down through it and back to 100)."""

    def klines(self, sym, iv, limit):
        df = super().klines(sym, iv, limit)
        if iv != "Min60":
            return df
        t = df["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
        dip, after = df.index[t == self.start - 30 * H][0], df.index[t == self.start - 29 * H][0]
        df.loc[dip, ["Open", "High", "Low", "Close"]] = [99.3, 99.4, 99.2, 99.3]
        df.loc[after, ["Open", "High", "Low", "Close"]] = [99.3, 100.1, 99.25, 100.0]
        return df


def _world_a(monkeypatch, fx_cls, special, **kw):
    from tradingagents import cost_store

    monkeypatch.setattr(cost_store, "engine_book", lambda *a, **k: _book(START_A // 1000))
    plan = _plan(START_A, END_A, {"2026-09": ["XAU_USDT"], "2026-10": ["XAU_USDT"]})
    return vm.measure_coin("XAU_USDT", plan, fx=fx_cls(START_A, END_A, special), **kw)


def test_funding_side_holds_a_long_that_follows_the_highest_payment_of_30_days(
        monkeypatch, gate_floors):
    rec = _world_a(monkeypatch, SpikedFunding, _dips(OLD_DIP, EDGE_DIP, NEW_DIP), runs=1)
    # the older dip's order goes in on Friday Sep 25 at 11:00; the last settlement before it is
    # that day's 08:00, at 0.09%: of the 90 settlements of the 30 days before the order only that
    # one is at or above its own rate, and 1 is not over a tenth (9): the long is held. The unseen
    # dip's order (Saturday Oct 03, 11:00) follows a 0.01% payment that all 90 are at or above
    fs = rec["combos"][vf.combo_key("v3_snap", "k1.5", "1h", "funding_side")]
    assert fs["older"]["rows"] == []
    assert fs["older"]["filter"] == {"signal_candles": 1, "blocked": 1}
    assert len(fs["unseen"]["rows"]) == 1 and "blocked" not in fs["unseen"]["filter"]


def test_funding_reaches_both_walks_and_a_failed_funding_page_fails_the_coin(
        monkeypatch, gate_floors):
    # the fake's funding covers every hold: a walk handed none would count its hold as
    # funding_estimated
    snap = _world_a(monkeypatch, FakeFx, _dips(OLD_DIP, EDGE_DIP, NEW_DIP), runs=1)["combos"][SNAP]
    assert snap["older"]["rows"] and snap["unseen"]["rows"]
    assert "funding_estimated" not in snap["older"]["counts"]
    assert "funding_estimated" not in snap["unseen"]["counts"]
    # and a page that fails is the coin's failure, never a shorter history that makes trades cheap
    with pytest.raises(RuntimeError, match="page 3 failed"):
        _world_a(monkeypatch, FailingFunding, {}, runs=1)


def test_every_walk_gets_the_risk_the_gap_the_fees_and_the_coins_data(monkeypatch, gate_floors):
    monkeypatch.setattr(vf, "FAMILIES", {"v3_snap": vf.FAMILIES["v3_snap"]})
    seen = []
    real_walk = vm.ve.walk

    def spy(bars, dirs, spec, **kw):
        seen.append((len(bars["t"]), kw))
        return real_walk(bars, dirs, spec, **kw)

    monkeypatch.setattr(vm.ve, "walk", spy)
    # an unseen dip on Friday Oct 02 the busy-hours filter lets through: runs are drawn
    rec = _world_a(monkeypatch, FakeFx, _dips(OLD_DIP, _utc(2026, 10, 2, 10)), runs=3,
                   risk_usd=2.0)
    # 2 settings x 2 timeframes x 5 filters x (older + unseen) = 40 real walks, and 3 random runs
    # on each combination whose real unseen run placed an order
    assert len(seen) > 40
    for n, kw in seen:
        assert kw["risk_usd"] == 2.0 and kw["fees"] == rec["pre"]["fees"]
        assert kw["flat_slip"] == rec["pre"]["flat_slip"]
        assert kw["fine"] and kw["fine"][0] and kw["book"] is not None and kw["funding"]
        assert 0 < kw["start"] < n - 1


def test_a_random_runs_seed_names_the_coin_timeframe_family_filter_and_run(
        monkeypatch, gate_floors):
    calls = []
    real_seed = vm.vrn.seed_of

    def spy(*parts):
        calls.append(parts)
        return real_seed(*parts)

    monkeypatch.setattr(vm.vrn, "seed_of", spy)
    rec = _world_a(monkeypatch, FakeFx, _dips(OLD_DIP, EDGE_DIP, NEW_DIP), runs=3)
    want = set()
    for key in rec["combos"]:
        fam, _setting, tf, filt = key.split("|")
        want |= {("XAU_USDT", tf, fam, filt, k) for k in range(3)}
    # five parts, each its own: without the run number all 200 runs would be one draw
    assert set(calls) == want


def test_random_runs_are_drawn_only_on_candles_the_filter_lets_the_order_into(
        monkeypatch, gate_floors):
    monkeypatch.setattr(vf, "FAMILIES", {"v3_snap": vf.FAMILIES["v3_snap"]})
    monkeypatch.setattr(vf, "FILTERS", ("busy_hours",))
    calls = []
    real_candidates = vm.vrn.candidates

    def spy(t, bar_ms, start, long_ok, short_ok):
        calls.append((list(t), bar_ms, start, list(long_ok), list(short_ok)))
        return real_candidates(t, bar_ms, start, long_ok, short_ok)

    monkeypatch.setattr(vm.vrn, "candidates", spy)
    # the real unseen order goes in on Friday Oct 02, 11:00, so runs are drawn; the Saturday's
    # candles are ones busy_hours holds, for the long side and for the short
    _world_a(monkeypatch, FakeFx, _dips(OLD_DIP, _utc(2026, 10, 2, 10)), runs=2)
    assert calls
    weekdays = 0
    for t, bar_ms, start, long_ok, short_ok in calls:
        for i in range(start, len(t) - 1):
            weekday = time.gmtime((t[i] + bar_ms) / 1000).tm_wday < 5
            assert long_ok[i] == weekday and short_ok[i] == weekday, (bar_ms, i)
            weekdays += weekday
    assert weekdays


def test_the_older_walks_lead_in_can_never_open_a_trade(monkeypatch, gate_floors):
    rec = _world_a(monkeypatch, DipLeadFx, _dips(OLD_DIP, EDGE_DIP, NEW_DIP), runs=1)
    rows = [r for c in rec["combos"].values() for r in c["older"]["rows"]]
    assert rows, "the window's own dip still trades"
    assert all(r[0] >= START_A for r in rows), "an older trade signalled before the window"


def test_a_timeframe_with_one_unseen_candle_is_skipped_and_named(monkeypatch, gate_floors):
    monkeypatch.setattr(vm, "UNSEEN_DAYS", 1)
    rec = _world_a(monkeypatch, FakeFx, {}, runs=1)
    assert rec["skipped"] == {"1d": "9 older and 1 unseen 1d candles"}
    assert {k.split("|")[2] for k in rec["combos"]} == {"1h", "4h"}


# ---- what the seven above leave open: the unseen walk's lead-in, and the windows a coin is read over

def test_the_unseen_walks_lead_in_can_never_open_a_trade(monkeypatch, gate_floors):
    # DipLeadFx's two dipped hours, Sep 22 18:00 and 19:00, lie before the window and inside the
    # unseen walk's lead-in (300 hours before the split reach back to Sep 18 12:00): that walk
    # starts at the split, so what they signalled is read and never traded
    rec = _world_a(monkeypatch, DipLeadFx, _dips(OLD_DIP, EDGE_DIP, NEW_DIP), runs=1)
    rows = [r for c in rec["combos"].values() for r in c["unseen"]["rows"]]
    assert rows, "the unseen days' own dip still trades"
    assert all(r[0] >= SPLIT_A for r in rows), "an unseen trade signalled before the split"


class RecordingFx(FakeFx):
    """World A's fake, remembering every read it was asked for."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.asked = {"klines": [], "minutes": [], "funding": []}

    def klines(self, sym, iv, limit):
        self.asked["klines"].append((iv, limit))
        return super().klines(sym, iv, limit)

    def minutes(self, sym, start_s, end_s):
        self.asked["minutes"].append((start_s, end_s))
        return super().minutes(sym, start_s, end_s)

    def funding_history(self, sym, since_ms=None):
        self.asked["funding"].append(since_ms)
        return super().funding_history(sym, since_ms)


def _clock_at_the_plans_end(monkeypatch):
    """Stop v3_measure's clock at the plan's end, so the candle counts it asks for are exact."""
    monkeypatch.setattr(vm, "time", types.SimpleNamespace(time=lambda: END_A / 1000))


def test_a_coin_is_read_once_over_the_windows_it_needs(monkeypatch, gate_floors):
    from tradingagents import cost_store

    books = []
    monkeypatch.setattr(cost_store, "engine_book",
                        lambda *a, **k: books.append(a) or _book(START_A // 1000))
    _clock_at_the_plans_end(monkeypatch)
    fx = RecordingFx(START_A, END_A, {})
    plan = _plan(START_A, END_A, {"2026-09": ["XAU_USDT"], "2026-10": ["XAU_USDT"]})
    vm.measure_coin("XAU_USDT", plan, runs=1, fx=fx)
    # one read of each kind: the minutes and the order book of the whole window [start, end), and
    # the funding from 31 days before it - the 30 days funding_side looks back from the first
    # order, and one more - never from the window's start or the split
    assert fx.asked["minutes"] == [(START_A // 1000, END_A // 1000)]
    assert books == [("XAU_USDT", START_A // 1000, END_A // 1000)]
    assert fx.asked["funding"] == [START_A - 31 * DAY]
    # one candle read per timeframe, long enough for that timeframe's longest lead-in. The window
    # is 10 days: 240 1h candles, 60 4h, 10 1d. The longest lead-in is 300 candles on 1h (snap),
    # 630 on 4h (v3_trend n=100 reads 100 x 6 + 5 x 6) and 300 on 1d (no rule reads more than
    # 105); the code asks for two candles more
    assert sorted(fx.asked["klines"]) == [("Day1", 10 + 300 + 2), ("Hour4", 60 + 630 + 2),
                                           ("Min60", 240 + 300 + 2)]


def test_each_setting_walks_the_lead_in_it_needs_before_the_window_and_before_the_split(
        monkeypatch, gate_floors):
    monkeypatch.setattr(vf, "FAMILIES", {"v3_trend": vf.FAMILIES["v3_trend"]})
    monkeypatch.setattr(vf, "FILTERS", ("none",))
    _clock_at_the_plans_end(monkeypatch)
    seen = []
    real_walk = vm.ve.walk

    def spy(bars, dirs, spec, **kw):
        seen.append(((kw["bar_s"], spec["ma_n"]), kw["start"], len(bars["t"])))
        return real_walk(bars, dirs, spec, **kw)

    monkeypatch.setattr(vm.ve, "walk", spy)
    _world_a(monkeypatch, FakeFx, {}, runs=1)
    walked = {}
    for key, start, n in seen:
        walked.setdefault(key, []).append((start, n))       # the older walk, then the unseen one
    # (bar seconds, average length) -> [(first tradable candle, candles walked)] older, unseen.
    # On 4h the frozen clock makes the read 60 + 630 + 2 = 692 candles, 632 before the window, 42
    # older and 18 unseen after it. A setting's walk starts `lead` candles into its view - 300,
    # 330 and 630 for n = 20, 50 and 100 (6n + 30 where that is over 300) - so the older view is
    # the lead-in and the 42 older candles (342, 372, 672) and the unseen view the lead-in and the
    # 18 unseen ones (318, 348, 648). On 1d (7 older, 3 unseen) every setting's lead is 300
    four, day = 4 * 3600, 86400
    assert walked == {
        (four, 120): [(300, 342), (300, 318)],
        (four, 300): [(330, 372), (330, 348)],
        (four, 600): [(630, 672), (630, 648)],
        (day, 20): [(300, 307), (300, 303)],
        (day, 50): [(300, 307), (300, 303)],
        (day, 100): [(300, 307), (300, 303)]}


# ---- what kept the random runs' entries from trading (final review I1): kept, and counted where the
# walk skips them

def test_every_placed_random_entry_is_a_trade_a_drop_or_inside_an_open_trade():
    import random

    from tradingagents import v3_engine as ve

    rng = random.Random(7)
    t, o, h, lo, c, px = [], [], [], [], [], 100.0
    for k in range(400):
        step = rng.gauss(0, 0.6)
        t.append(_utc(2026, 9, 1, 0) + k * H)
        o.append(px)
        px = max(50.0, px + step)
        h.append(max(o[-1], px) + abs(rng.gauss(0, 0.3)))
        lo.append(min(o[-1], px) - abs(rng.gauss(0, 0.3)))
        c.append(px)
    bars = {"t": t, "o": o, "h": h, "l": lo, "c": c}
    contract = ve.contract_of(SPEC)
    inside_seen = 0
    for spec in (vf.exit_spec("v3_snap", 1.5, "1h"), vf.exit_spec("v3_trend", 20, "1d")):
        for seed in range(6):
            r = random.Random(seed)
            dirs = [r.choice((1, -1)) if r.random() < 0.3 else 0 for _ in range(400)]
            w = ve.walk(bars, dirs, spec, bar_s=3600, contract=contract,
                        fees={"maker": 0.0002, "taker": 0.00075}, flat_slip=0.0003,
                        start=30, cost_check=False)
            placed = sum(1 for d in dirs[30:] if d)
            inside = vm.inside_open_trades(w, dirs)
            assert placed == (len(w["trades"]) + sum(w["counts"][k] for k in vm.DROPS) + inside), (
                spec["kind"], seed)
            inside_seen += inside
    assert inside_seen > 0, "the world must hold entries inside open trades to test the count"


def test_inside_open_trades_counts_the_candles_after_each_signal_up_to_its_exit_or_the_end():
    dirs = [0, 1, 1, 0, -1, 0, 1, 1, 1]
    # a trade signalled at 1 closed in candle 4 (which signals again): 2 skipped (candles 2 and 3:
    # only 2 holds an entry); one signalled at 4 still open at the end: 6, 7 and 8 skipped
    walked = {"trades": [{"signal_bar": 1, "exit_bar": 4, "why": "TP"},
                         {"signal_bar": 4, "exit_bar": 8, "why": "END"}]}
    assert vm.inside_open_trades(walked, dirs) == 1 + 3


def test_a_random_run_keeps_why_its_entries_never_traded(monkeypatch, gate_floors):
    rec = _metal(monkeypatch, _dips(OLD_DIP, EDGE_DIP, NEW_DIP))
    combo = rec["combos"][SNAP]
    # each of the 3 runs places one October entry; a flat hour gives a snap no average to aim at, so
    # an entry there is refused no_levels - and every placed entry is a trade or a counted reason
    traded = sum(n for n, _p in combo["random"])
    assert combo["random_short"] == 0 and combo["random_in_trade"] == 0
    assert traded + sum(combo["random_refused"].values()) == 3
    assert set(combo["random_refused"]) <= {"no_levels"}
    assert combo["random_refused"].get("no_levels", 0) == 3 - traded
    # a filter that blocked the real order leaves the runs nothing to place, and nothing to refuse
    busy = rec["combos"][vf.combo_key("v3_snap", "k1.5", "1h", "busy_hours")]
    assert (busy["random_short"], busy["random_refused"], busy["random_in_trade"]) == (0, {}, 0)


# ---- Backtest v3 Part 2b: two flat gaps, one per walk ------------------------------------------

def test_the_older_walk_pays_the_older_days_own_flat_gap_once_they_have_readings(
        monkeypatch, gate_floors):
    from tradingagents import cost_store

    others = [f"C{k}_USDT" for k in range(9)]
    plan = _plan(START_B, END_B, {}, liquid={"2026-09": ["ABC_USDT"] + others,
                                             "2026-10": ["ABC_USDT"] + others},
                 strength={str(SEP21): ["ABC_USDT"] + others,
                           str(SEP28): others[:8] + ["ABC_USDT"],
                           str(OCT5): ["ABC_USDT"] + others},
                 kinds={"ABC_USDT": "crypto"})
    # one reading on the older days at 0.02% a side, two on the unseen days at 0.10%: the whole
    # window's median (of 0.02%, 0.10%, 0.10%) is 0.10%, the older days' own 0.02%
    book = bh.pack([_reading(START_B // 1000, 0.0002), _reading(SPLIT_B // 1000 + 3600, 0.0010),
                    _reading(SPLIT_B // 1000 + 7200, 0.0010)])
    monkeypatch.setattr(cost_store, "engine_book", lambda *a, **k: book)
    up = {SPLIT_B + m * M: (101.1, 100.9) for m in range(3 * 1440)}
    rec = vm.measure_coin("ABC_USDT", plan, runs=2, fx=FakeFx(START_B, END_B, up))
    pre = rec["pre"]
    assert pre["flat_slip"] == pytest.approx(0.0010)
    assert pre["flat_slip_older"] == pytest.approx(0.0002)
    assert pre["flat_slip_older_source"] == (
        "the median of its 1 recorded minutes on the older days whose book did not run out")
    # K = 5's trade is still open at the split and closes at the last older close at the market,
    # with no reading in the hour before it: it pays the OLDER days' 0.02%, never the 0.10% read
    # off the unseen days. 166 lots of 0.01 x $100, maker in, taker out
    k5 = rec["combos"][vf.combo_key("v3_strength", "k5", "1d", "none")]
    (row,) = k5["older"]["rows"]
    assert row[5] == "END" and row[4] == pytest.approx(-166.0 * (0.0002 + 0.00075 + 0.0002))
