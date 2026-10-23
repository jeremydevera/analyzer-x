"""The Backtest v3 universe (decisions doc docs/superpowers/specs/2026-10-23-
backtest-v3-part2-decisions.md, "The universe"): who is liquid and who is calm,
month by month, BTC's mood and the Monday ranks — each worked from daily
candles CLOSED before it is used. Every day here is a real UTC day; day k
opens at FIRST + k days (Jul 01, 2026 is day 0, Sep 01 day 62, Oct 01 day 92,
the window ends Nov 01, 2026 00:00 UTC, after day 122)."""
import calendar
import math

import pandas as pd
import pytest

from tradingagents import v3_universe as vu

DAY = 86_400_000
FIRST = calendar.timegm((2026, 7, 1, 0, 0, 0)) * 1000
END = calendar.timegm((2026, 11, 1, 0, 0, 0)) * 1000        # a Sunday
SEP1, OCT1 = FIRST + 62 * DAY, FIRST + 92 * DAY
OCT5, SEP7 = FIRST + 96 * DAY, FIRST + 68 * DAY             # two Mondays


def _daily(first_k, closes, vols):
    return {"t": [FIRST + (first_k + j) * DAY for j in range(len(closes))],
            "c": list(closes), "v": list(vols)}


def _alt(lo, hi, n=123):
    """Day k closes at `hi` when k is odd, `lo` when even."""
    return [hi if k % 2 else lo for k in range(n)]


def _world():
    """BTC v=100 closing 100/102 on alternate days; AAA v=50, 100/101; BBB v=20,
    100/110; CCC v=1 at 100; NEW only from Sep 10 (day 71), v=1000, closing
    100, 101, 102 ... (rising a dollar a day); XAU a metal; AAPL a stock. Every
    contract size is 1."""
    d = {"BTC_USDT": _daily(0, _alt(100.0, 102.0), [100.0] * 123),
         "AAA_USDT": _daily(0, _alt(100.0, 101.0), [50.0] * 123),
         "BBB_USDT": _daily(0, _alt(100.0, 110.0), [20.0] * 123),
         "CCC_USDT": _daily(0, [100.0] * 123, [1.0] * 123),
         "NEW_USDT": _daily(71, [100.0 + j for j in range(52)], [1000.0] * 52)}
    kinds = {**dict.fromkeys(d, "crypto"), "XAU_USDT": "metals", "AAPL_USDT": "stocks"}
    sizes = dict.fromkeys(d, 1.0)
    return d, kinds, sizes


@pytest.fixture()
def plan(monkeypatch):
    monkeypatch.setattr(vu, "WINDOW_DAYS", 61)        # Sep 01 - Nov 01, 2026: two months
    monkeypatch.setattr(vu, "LIQUID_TOP", 3)
    d, kinds, sizes = _world()
    return vu.build(d, kinds, sizes, END, built_s=END / 1000)


def test_traded_value_sums_the_30_days_that_closed_by_the_month_start():
    # 40 days from Aug 22 (day 52): 10 contracts of size 0.5 at 2.0 = $10 a day, except the
    # day that opens Sep 30 (closes at Oct 01 00:00, so it counts) at $100, and the day that
    # opens Oct 01 (still forming at the month start, so it never counts) at $1,000
    vols = [10.0] * 40
    vols[39] = 100.0                 # day 91, Sep 30 (index 39 from day 52)
    daily = _daily(52, [2.0] * 41, vols + [1000.0])
    # the 30 days opening Sep 01 - Sep 30: 29 x $10 + $100 x 0.5 x 2.0 = $390
    assert vu.traded_value(daily, 0.5, OCT1) == pytest.approx(29 * 10.0 + 100.0)


def test_realized_vol_needs_all_60_returns_and_unknown_is_never_calm():
    # 61 closes alternating 100/102: every log return is +/- ln(1.02), mean 0
    daily = _daily(0, _alt(100.0, 102.0, 92), [1.0] * 92)
    assert vu.realized_vol(daily, OCT1) == pytest.approx(math.log(1.02))
    # one of those 61 days missing: no 60-day figure
    hole = {k: v[:60] + v[61:] for k, v in daily.items()}
    assert vu.realized_vol(hole, OCT1) is None


def test_the_14_day_return_reads_the_close_at_the_instant_and_14_days_before():
    # NEW closes 100 + (k - 71); at Oct 05 00:00 the candle that just closed is day 95 (124),
    # 14 days earlier day 81 (110): 124 / 110 - 1
    d, _kinds, _sizes = _world()
    assert vu.return_14(d["NEW_USDT"], OCT5) == pytest.approx(124 / 110 - 1)
    assert vu.return_14(d["NEW_USDT"], SEP7) is None, "day 67 is before NEW's first, day 71"


def test_the_liquid_list_is_the_top_by_value_at_each_month_start(plan):
    # Sep 01 (days 32-61): BTC 100 x (15 x 100 + 15 x 102) = 303,000; AAA 50 x 3,015 = 150,750;
    # BBB 20 x 3,150 = 63,000; CCC 3,000; NEW has no candles yet. The top 3:
    assert plan["liquid"]["2026-09"] == ["BTC_USDT", "AAA_USDT", "BBB_USDT"]
    assert plan["value"]["2026-09"] == [303_000, 150_750, 63_000]
    # Oct 01 (days 62-91): NEW traded 1,000 x (100 + 101 + ... + 120) = 2,310,000 over its 21
    # days and goes first; BBB drops out
    assert plan["liquid"]["2026-10"] == ["NEW_USDT", "BTC_USDT", "AAA_USDT"]
    assert plan["value"]["2026-10"][0] == 2_310_000


def test_calm_is_the_calm_kinds_plus_the_quietest_third_of_the_liquid(plan):
    # Sep: vols AAA ln(1.01) < BTC ln(1.02) < BBB ln(1.1); a third of 3 is 1: AAA, after the metal
    assert plan["calm"]["2026-09"] == ["XAU_USDT", "AAA_USDT"]
    assert plan["vol"]["2026-09"]["AAA_USDT"] == pytest.approx(math.log(1.01), abs=1e-6)
    # Oct: NEW has 21 days, not 61 - no 60-day vol, so it cannot be calm; of AAA and BTC the
    # third (rounded up) is AAA
    assert plan["calm"]["2026-10"] == ["XAU_USDT", "AAA_USDT"]
    assert "NEW_USDT" not in plan["vol"]["2026-10"]
    # a stock and a coin that never ranked are in no group
    assert plan["coins"] == ["AAA_USDT", "BBB_USDT", "BTC_USDT", "NEW_USDT", "XAU_USDT"]


def test_volatility_indices_and_stablecoins_are_named_and_never_in_a_group(monkeypatch):
    monkeypatch.setattr(vu, "WINDOW_DAYS", 61)
    monkeypatch.setattr(vu, "LIQUID_TOP", 3)
    d, kinds, sizes = _world()
    # a volatility index and a stablecoin the venue files under calm kinds, and a stablecoin it
    # files as crypto that trades the most of all and never moves - the quietest coin there is
    d["USDE_USDT"] = _daily(0, [1.0] * 123, [10_000_000.0] * 123)
    kinds.update({"BVOL_USDT": "indices", "USDC_USDT": "forex", "USDE_USDT": "crypto",
                  "USDP_USDT": "stocks"})       # a stock is in no group: never named
    sizes["USDE_USDT"] = 1.0
    plan = vu.build(d, kinds, sizes, END, built_s=END / 1000)
    assert plan["left_out"] == {
        "BVOL_USDT": "a volatility index: it jumps by design, so it is never calm",
        "USDC_USDT": "a stablecoin: it barely moves, so it is never calm or liquid",
        "USDE_USDT": "a stablecoin: it barely moves, so it is never calm or liquid"}
    # the groups are the world's own, as if none of the three were listed
    assert plan["liquid"]["2026-09"] == ["BTC_USDT", "AAA_USDT", "BBB_USDT"]
    assert plan["calm"]["2026-09"] == ["XAU_USDT", "AAA_USDT"]
    assert plan["calm"]["2026-10"] == ["XAU_USDT", "AAA_USDT"]
    assert "USDE_USDT" not in plan["coins"] and "USDE_USDT" not in plan["sizes"]
    assert vu.LEFT_OUT_NOTE in plan["notes"]


def test_membership_is_by_the_month_an_instant_falls_in(plan):
    mid_sep, mid_oct, mid_nov = SEP1 + 14 * DAY, OCT1 + 14 * DAY, END + 14 * DAY
    assert vu.member_mask(plan, ("liquid",), "BBB_USDT", [mid_sep, mid_oct]) == [True, False]
    assert vu.member_mask(plan, ("liquid", "calm"), "XAU_USDT",
                          [mid_sep, mid_oct, mid_nov]) == [True, True, False]
    assert vu.member_mask(plan, (), "BTC_USDT", [mid_sep]) == [False]


def test_the_monday_ranks_order_the_months_liquid_coins_by_14_day_return(plan):
    # Oct 05: NEW +12.7%; BTC and AAA alternate with an even 14-day lag, so 0 (ties by name)
    assert plan["strength"][str(OCT5)] == ["NEW_USDT", "AAA_USDT", "BTC_USDT"]
    assert vu.rank_at(plan, "NEW_USDT", OCT5) == 1 and vu.rank_at(plan, "BTC_USDT", OCT5) == 3
    assert vu.rank_at(plan, "BBB_USDT", OCT5) is None, "not liquid in October"
    # Sep 07: September's liquid three, all at 0
    assert plan["strength"][str(SEP7)] == ["AAA_USDT", "BBB_USDT", "BTC_USDT"]
    # Aug 31 is before the plan's months: no one is liquid there
    assert plan["strength"][str(SEP7 - 7 * DAY)] == []


def test_btcs_mood_is_known_only_once_its_day_has_closed(plan):
    # the 50-day average of closes alternating 100/102 is 101: an odd day (102) is up. Day 63
    # (Sep 02, 102) closes at FIRST + 64 days
    close_63 = FIRST + 64 * DAY
    assert vu.mood_at(plan, [close_63, close_63 - 1]) == [True, False], \
        "a millisecond before day 63 closes, the last close is day 62's 100"
    assert vu.mood_at(plan, [END + 2 * DAY]) == [None], "no close of the last day: unknown"


def test_the_plan_round_trips_and_an_old_version_is_refused(plan, tmp_path):
    p = vu.save(plan, tmp_path / "v3" / "plan.json")
    assert vu.load(p) == plan
    p.write_text(p.read_text(encoding="utf-8").replace('"version":1', '"version":0'),
                 encoding="utf-8")
    with pytest.raises(ValueError, match="version"):
        vu.load(p)


def test_the_plan_names_its_window_and_its_limits(plan):
    assert plan["end"].endswith(("am", "pm")) and ", 2026 " in plan["end"]
    assert plan["months"] == ["2026-09", "2026-10"]
    assert any("survivorship" in n for n in plan["notes"])
    assert any("TODAY's contract size" in n for n in plan["notes"])
    assert plan["left_out"] == {}, "the test world lists no index or stablecoin"


class FakeFx:
    """Daily frames of the world above plus the forming day (Nov 01, volume 0)."""

    def __init__(self):
        self.d, _k, _s = _world()

    def trading_symbols(self):
        return ["AAA_USDT", "BAD_USDT", "BTC_USDT", "NIL_USDT", "XAU_USDT"]

    def contract_spec(self, sym):
        return {"contractSize": 0.0 if sym == "NIL_USDT" else 1.0}

    def klines(self, sym, iv, limit):
        if sym == "BAD_USDT":
            raise RuntimeError("no Day1 candles for BAD_USDT")
        d = self.d[sym]
        t = d["t"] + [END]
        return pd.DataFrame({"Date": pd.to_datetime(t, unit="ms"), "Close": d["c"] + [d["c"][-1]],
                             "Volume": d["v"] + [0.0]})


def test_collect_cuts_the_forming_day_and_names_every_coin_it_could_not_read(monkeypatch):
    monkeypatch.setattr(vu, "WINDOW_DAYS", 61)
    kinds = {"AAA_USDT": "crypto", "BAD_USDT": "crypto", "BTC_USDT": "crypto",
             "NIL_USDT": "crypto", "XAU_USDT": "metals"}
    got = vu.collect(fx=FakeFx(), end_ms=END, kind_of=kinds.get, log=lambda *a: None)
    assert got["skipped"] == {"BAD_USDT": "RuntimeError: no Day1 candles for BAD_USDT",
                              "NIL_USDT": "contract size 0: its traded value cannot be worked out"}
    # the forming Nov 01 candle never counts: BTC's last mood is day 122's close, at END
    assert got["mood"]["t"][-1] == END
    assert got["liquid"]["2026-10"] == ["BTC_USDT", "AAA_USDT"]
    assert got["calm"]["2026-10"] == ["XAU_USDT", "AAA_USDT"]
