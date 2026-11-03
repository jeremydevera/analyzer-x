"""The "all" plan of Backtest v3 (operator, Nov 03, 2026: "can you run backtest for v3 for all
coins all time frame and all strategy"): every contract the exchange trades today is in EVERY
family's universe, both groups, in every month it has a closed daily candle - except the left-out
rules (a volatility index, a stablecoin), named as before. The Monday ranks are taken over that
month's whole "all" universe, and the plan's id covers its kind, so it can never be taken for the
universe plan. The universe plan (`build`) is untouched by it."""
import json
import types

import pandas as pd
import pytest

import tests.test_v3_universe as tu
from tradingagents import v3_families as vf, v3_universe as vu

DAY, END, FIRST, SEP1, OCT1 = tu.DAY, tu.END, tu.FIRST, tu.SEP1, tu.OCT1
OCT5 = tu.OCT5


def _world():
    """`tests/test_v3_universe._world` plus a metal, a stock token listed only on Oct 03 (day
    94), a volatility index and a stablecoin, every one with daily candles."""
    d, kinds, _sizes = tu._world()
    d["XAU_USDT"] = tu._daily(0, [2000.0 + k for k in range(123)], [5.0] * 123)
    d["AAPL_USDT"] = tu._daily(94, [200.0 + k for k in range(29)], [3.0] * 29)
    d["BVOL_USDT"] = tu._daily(0, [50.0] * 123, [1.0] * 123)
    d["USDC_USDT"] = tu._daily(0, [1.0] * 123, [9e9] * 123)
    kinds |= {"BVOL_USDT": "indices", "USDC_USDT": "crypto"}
    return d, kinds


@pytest.fixture()
def plan(monkeypatch):
    monkeypatch.setattr(vu, "WINDOW_DAYS", 61)        # Sep 01 - Nov 01, 2026: two months
    d, kinds = _world()
    return vu.build_all(d, kinds, END, built_s=END / 1000)


def test_every_coin_is_in_both_groups_in_every_month_it_has_a_closed_candle(plan):
    every = ["AAA_USDT", "BBB_USDT", "BTC_USDT", "CCC_USDT", "NEW_USDT", "XAU_USDT"]
    assert plan["kind"] == "all" and plan["months"] == ["2026-09", "2026-10"]
    assert plan["liquid"]["2026-09"] == every == plan["calm"]["2026-09"]
    # the stock token's first candle opens Oct 03: it is in October, never September
    assert plan["liquid"]["2026-10"] == sorted(every + ["AAPL_USDT"]) == plan["calm"]["2026-10"]
    assert plan["coins"] == sorted(every + ["AAPL_USDT"])
    assert plan["kinds"]["AAPL_USDT"] == "stocks" and plan["kinds"]["XAU_USDT"] == "metals"


def test_the_left_out_rules_still_name_a_volatility_index_and_a_stablecoin(plan):
    assert set(plan["left_out"]) == {"BVOL_USDT", "USDC_USDT"}
    assert "volatility index" in plan["left_out"]["BVOL_USDT"]
    assert "stablecoin" in plan["left_out"]["USDC_USDT"]
    assert not {"BVOL_USDT", "USDC_USDT"} & set(plan["coins"])


def test_the_monday_ranks_are_taken_over_the_whole_all_universe(plan):
    # Oct 05: NEW rose a dollar a day (110 to 124 over the 14 days, +12.7%), XAU +0.7%, the 100/110 coins 0;
    # AAPL listed Oct 03 has no close 14 days before, so it is not ranked
    ranked = plan["strength"][str(OCT5)]
    assert ranked[:2] == ["NEW_USDT", "XAU_USDT"] and "AAPL_USDT" not in ranked
    assert set(ranked) == set(plan["liquid"]["2026-10"]) - {"AAPL_USDT"}


def test_every_family_may_trade_every_coin_on_both_sides_where_its_group_allows(plan):
    at = [OCT1 + DAY]
    for fam in vf.FAMILIES:
        assert vf.applies(plan, fam, "AAPL_USDT")
    assert vf.sides_allowed("v3_trend", "AAA_USDT", plan, at) == ([True], [True])
    assert vf.sides_allowed("v3_snap", "BTC_USDT", plan, at) == ([True], [True])
    assert vf.sides_allowed("v3_strength", "XAU_USDT", plan, at) == ([True], [False])
    assert vf.sides_allowed("v3_trend", "AAPL_USDT", plan, [SEP1 + DAY]) == ([False], [False])


def test_the_kind_is_in_the_id_and_the_universe_plan_keeps_its_shape(plan, monkeypatch):
    assert plan["id"] == vu.plan_id(plan) and vu.kind_of(plan) == "all"
    other = {k: v for k, v in plan.items() if k not in ("kind", "id")}
    assert vu.plan_id(other) != plan["id"], "the plan id covers the kind"
    d, kinds, sizes = tu._world()
    universe = vu.build(d, kinds, sizes, END, built_s=END / 1000)
    assert "kind" not in universe and vu.kind_of(universe) == "universe"


def test_the_all_plan_round_trips_and_is_found_by_its_id(plan, tmp_path):
    p = vu.save(plan, tmp_path / "plan-all.json")
    assert vu.load(p) == json.loads(p.read_text(encoding="utf-8"))
    assert vu.find_plan(plan["id"], tmp_path) == p
    assert vu.find_plan("0" * 16, tmp_path) is None
    (tmp_path / "plan-bad.json").write_text("{", encoding="utf-8")   # unreadable: passed over
    assert vu.find_plan(plan["id"], tmp_path) == p


def test_find_plan_prefers_the_universe_plan_file_name_and_looks_only_at_plan_files(tmp_path):
    a = {"version": vu.VERSION, "end_ms": END, "start_ms": END - DAY, "coins": []}
    a["id"] = vu.plan_id(a)
    vu.save(a, tmp_path / "plan.json")
    vu.save(a, tmp_path / "plan-all.json")
    vu.save(a, tmp_path / "notes.json")
    assert vu.find_plan(a["id"], tmp_path) == tmp_path / "plan.json"
    (tmp_path / "plan.json").unlink()
    (tmp_path / "plan-all.json").unlink()
    assert vu.find_plan(a["id"], tmp_path) is None, "only plan*.json files are plans"


class AllFx:
    """Every kind of contract has daily candles; BAD's cannot be read."""

    def __init__(self):
        self.d, self.kinds = _world()
        self.kinds["BAD_USDT"] = "stocks"
        self.asked = []

    def trading_symbols(self):
        return sorted(self.kinds)

    def contract_spec(self, sym):
        raise AssertionError("the all plan needs no contract size")

    def klines(self, sym, iv, limit):
        self.asked.append(sym)
        if sym == "BAD_USDT":
            raise RuntimeError("no Day1 candles for BAD_USDT")
        d = self.d[sym]
        return pd.DataFrame({"Date": pd.to_datetime(d["t"] + [END], unit="ms"),
                             "Close": d["c"] + [d["c"][-1]], "Volume": d["v"] + [0.0]})


def test_collect_all_reads_every_kind_and_names_what_it_could_not_read(monkeypatch):
    monkeypatch.setattr(vu, "WINDOW_DAYS", 61)
    monkeypatch.setattr(vu, "time", types.SimpleNamespace(time=lambda: END / 1000 + 60,
                                                           gmtime=__import__("time").gmtime))
    fx = AllFx()
    got = vu.collect(fx=fx, end_ms=END, kind_of=fx.kinds.get, log=lambda *a: None, kind="all")
    assert got["kind"] == "all" and got["skipped"] == {
        "BAD_USDT": "RuntimeError: no Day1 candles for BAD_USDT"}
    assert "AAPL_USDT" in got["coins"] and "XAU_USDT" in got["coins"]
    assert "BVOL_USDT" not in fx.asked and "USDC_USDT" not in fx.asked, \
        "a left-out contract is named, never read"
    assert got["mood"]["t"][-1] == END


def test_an_unknown_plan_kind_is_refused_by_name():
    with pytest.raises(ValueError, match="plan kind 'most'"):
        vu.collect(fx=AllFx(), end_ms=END, kind_of=str, log=lambda *a: None, kind="most")


def test_the_plan_command_builds_the_all_plan_into_its_own_file(monkeypatch, tmp_path, capsys):
    from tradingagents import v3_research as vr

    asked = {}

    def fake(**k):
        asked.update(k)
        d, kinds = _world()
        return vu.build_all(d, kinds, END, built_s=END / 1000)

    monkeypatch.setattr(vu, "WINDOW_DAYS", 61)
    monkeypatch.setattr(vu, "collect", fake)
    monkeypatch.setattr(vu, "ALL_FILE", tmp_path / "plan-all.json")
    monkeypatch.setattr(vu, "PLAN_FILE", tmp_path / "plan.json")
    assert vr.main(["plan", "--kind", "all"]) == 0
    assert asked["kind"] == "all" and not (tmp_path / "plan.json").exists()
    built = vu.load(tmp_path / "plan-all.json")
    assert vu.kind_of(built) == "all"
    out = capsys.readouterr().out
    assert f"(all, id {built['id']})" in out and "left out BVOL_USDT" in out
