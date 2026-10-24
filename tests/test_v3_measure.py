"""One coin's whole Backtest v3 measurement (decisions doc docs/superpowers/specs/
2026-10-23-backtest-v3-part2-decisions.md, "The window and the split", "What a
machine returns per coin"). Two small worlds on ONE timeline: every candle in
the window is BUILT from its own minutes (RCA-2026-09-12-A); the lead-in
before the window is flat candles the indicators read and nothing trades on.
The unseen days are shortened to 3 here (the real run's are 90)."""
import calendar

import numpy as np
import pandas as pd
import pytest

from tradingagents import book_history as bh, v3_families as vf, v3_measure as vm

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
    # (2 x 1h, 4h) - 12 family-setting-timeframes x 5 filters. Never strength (liquid only)
    assert rec["families"] == ["v3_trend", "v3_breakout", "v3_snap"]
    assert len(rec["combos"]) == 60 and rec["skipped"] == {}
    old, new = rec["combos"][SNAP]["older"], rec["combos"][SNAP]["unseen"]
    # each dip's waiting buy at 99.3 fills in the next hour's first minute (low 99.25) and the
    # second minute (high 100.1) trades through the target
    assert old["rows"] == [[OLD_DIP, OLD_DIP + H, OLD_DIP + H + M, 1, pytest.approx(_snap_pnl()),
                            "TP"]]
    assert new["rows"] == [[NEW_DIP, NEW_DIP + H, NEW_DIP + H + M, 1,
                            pytest.approx(_snap_pnl()), "TP"]]
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
    assert pre["flat_slip_source"] == "the median of its 1 recorded minutes"
    # the one reading (at the window's first second) answers its own minute and the 60 after
    # it: 61 of the older days' 7 x 1,440 minutes; nothing of the unseen days
    assert pre["coverage_older"] == pytest.approx(61 / (7 * 1440))
    assert pre["coverage_unseen"] == 0.0
    assert pre["contract"]["max_lev"] == 20 and pre["minutes"] == 10 * 1440
    assert rec["windows"]["1h"]["older_candles"] == 7 * 24
    assert rec["windows"]["1h"]["unseen_candles"] == 3 * 24
    assert rec["windows"]["1h"]["split"].endswith(("am", "pm"))
    # the unseen days, Oct 01 - Oct 04, 2026, fall in one month
    assert rec["unseen_months"] == ["2026-10"]


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
    assert k3["older"]["rows"] == [[SEP21 - DAY, SEP21, SEP28, 1,
                                    pytest.approx(-166.0 * (0.0002 + 0.00075 + 0.0002)), "RANK"]]
    # K = 5: 9th is inside 2K = 10, so the trade is still open at the split and closes there, at
    # the last older close, 100.0 - paying the coin's flat 0.02% gap, never the 5% of the reading
    # stamped at the split, which the older walk cannot see
    k5 = rec["combos"][vf.combo_key("v3_strength", "k5", "1d", "none")]
    assert k5["older"]["rows"] == [[SEP21 - DAY, SEP21, SPLIT_B, 1,
                                    pytest.approx(-166.0 * (0.0002 + 0.00075 + 0.0002)), "END"]]
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
