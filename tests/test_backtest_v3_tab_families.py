"""The Backtest v3 tab runs the four v3 families on one coin, and shows the
3-coin check (operator, Oct 27, 2026: "go" to "both" - the tab had one of 130
stored ideas per press and an empty tested-ideas card).

A family run is the research's own pieces over the tab's window - the plan's
universe month by month, the filter's masks, the family's rule and its OWN
exit, one `v3_engine.walk` - and these tests hold the wiring on one hand-built
world, ON ONE TIMELINE: hours from Sep 06, 2026 to the run's own `now_ms`
(Nov 05, 2026), the plan ending Nov 01, 2026 00:00 UTC. The coin is calm
(a snap-back coin) in October only, so September's dips are masked out and
November's take October's membership (the plan's last month). Every 48 hours
the price dips to 98 and comes back: a v3_snap k1.5 long that fills on the
next hour and reaches its average the hour after.
"""
from __future__ import annotations

import calendar
import json

import pandas as pd
import pytest

from tradingagents import (
    backtest_report as br,
    v3_engine as ve,
    v3_families as vf,
    v3_filters as vfl,
    v3_page as vp,
    v3_research as vrs,
    v3_universe as vu,
)

H = 3_600_000
DAY = 86_400_000
NOW = calendar.timegm((2026, 11, 5, 0, 0, 0)) * 1000
PLAN_END = calendar.timegm((2026, 11, 1, 0, 0, 0)) * 1000
N = 60 * 24 + 400                       # 60 days of hours and a lead-in before them
T0 = NOW - N * H
DIPS = set(range(320, N - 3, 48))       # a dip every 48 hours, never on the last candles
SYM = "TEST_USDT"


@pytest.fixture(autouse=True)
def _never_the_real_verdict_store(monkeypatch, tmp_path):
    """The tab's tested-ideas section reads the verdict store: a test of the tab never reads the
    operator's own."""
    from tradingagents import v3_verdicts

    monkeypatch.setattr(v3_verdicts, "store_path", lambda: tmp_path / "no-verdicts.json")



def _frame():
    o, h, lo, c = [100.0] * N, [100.5] * N, [99.5] * N, [100.0] * N
    for i in DIPS:
        h[i], lo[i], c[i] = 100.2, 97.9, 98.0              # the signal candle
        o[i + 1], h[i + 1], lo[i + 1], c[i + 1] = 98.0, 99.2, 97.8, 99.0   # trades through 98
    return pd.DataFrame({"Date": pd.to_datetime([T0 + k * H for k in range(N)], unit="ms"),
                         "Open": o, "High": h, "Low": lo, "Close": c, "Volume": [1.0] * N})


class FakeFx:
    def __init__(self):
        self.df = _frame()

    def klines(self, sym, iv, limit):
        return self.df.tail(limit).reset_index(drop=True)

    def minutes(self, sym, start_s, end_s):
        return pd.DataFrame({"Date": pd.to_datetime([], unit="s"), "High": [], "Low": []})

    def funding_history(self, sym, since_ms=None):
        return []

    def book_cost(self, sym, notional):
        return {"slippage": 0.0003}

    def contract_spec(self, sym):
        return {"contractSize": 0.01, "minVol": 1, "maintenanceMarginRate": 0.005,
                "maxLeverage": 20, "minLeverage": 1}

    def trading_symbols(self):
        return ["BTC_USDT", SYM]


def _plan():
    months = ["2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05",
              "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
    plan = {"version": vu.VERSION, "venue": "Gate", "start_ms": PLAN_END - 365 * DAY,
            "end_ms": PLAN_END, "months": months,
            "liquid": {m: [] for m in months},
            "calm": {**{m: [] for m in months}, "2026-10": [SYM]},
            "kinds": {SYM: "metals"}, "strength": {}, "mood": {"t": [], "up": []}}
    plan["id"] = vu.plan_id(plan)
    return plan


@pytest.fixture()
def world(monkeypatch):
    import tradingagents.auto_trader as at
    from tradingagents import cost_store

    monkeypatch.setattr(cost_store, "engine_book", lambda *a, **k: cost_store.empty())
    monkeypatch.setattr(at, "maker_fee_floor", lambda *a, **k: 0.0002)
    monkeypatch.setattr(at, "fee_floor", lambda *a, **k: 0.00075)
    return FakeFx()


BODY = {"sym": SYM, "tf": "1h", "signal": "v3_snap", "setting": "k1.5", "filter": "none",
        "days": 60, "risk_usd": 1}


def _run(fx, **over):
    return vp.run_family(dict(BODY, **over), fx=fx, plan=_plan(), now_ms=NOW)


def _month(ms):
    return vu.month_key(ms)


def test_a_family_signals_only_where_the_plan_lets_the_coin_trade(world):
    got = _run(world)
    rows = got["trades"]
    assert rows, "the snap-back dips trade"
    months = {_month(r["signal_ms"] + H) for r in rows}
    # September: the coin is in no universe; October: calm; November: after the plan's end,
    # October's membership stands in
    assert months == {"2026-10", "2026-11"}
    assert all(r["side"] == "long" for r in rows)
    in_window = [i for i in DIPS if T0 + i * H >= NOW - 60 * DAY]
    member = [i for i in in_window if _month(T0 + (i + 1) * H) in ("2026-10", "2026-11")]
    assert got["summary"]["filter"]["signal_candles"] == len(member)
    assert len(rows) == len(member), "every allowed dip filled and came back before the next"
    s = got["summary"]
    assert s["wins"] + s["losses"] == s["trades"] == len(rows)
    assert s["profit"] == pytest.approx(sum(r["pnl"] for r in rows))
    p = got["provenance"]
    assert s["trades_per_day"] == pytest.approx(len(rows) / ((p["end_ms"] - p["start_ms"]) / DAY))


def test_the_universe_and_the_plans_end_are_said_on_the_provenance_line(world):
    p = _run(world)["provenance"]
    assert p["universe"][0].startswith(f"{SYM} is in v3_snap's universe in 2 of the window's 3 "
                                       "months")
    from tradingagents.positions_view import fmt_when
    assert p["universe"][1] == (f"membership after {fmt_when(PLAN_END / 1000)} (the plan's end) "
                                "is 2026-10's")
    assert p["plan_id"] == _plan()["id"] and p["plan_end_ms"] == PLAN_END
    assert "never the proof" in p["look"]
    assert p["risk_usd"] == 1 and p["start_ms"] >= NOW - 60 * DAY and p["end_ms"] == NOW


def test_strength_says_it_has_no_ranks_after_the_plans_end():
    words = vp.universe_words(_plan(), "v3_strength", SYM, NOW - 30 * DAY, NOW)
    assert any("v3_strength has no Monday ranks after" in w for w in words)
    assert not any("no Monday ranks" in w
                   for w in vp.universe_words(_plan(), "v3_snap", SYM, NOW - 30 * DAY, NOW))


def test_the_filter_blocks_and_is_counted(world):
    plain, busy = _run(world), _run(world, filter="busy_hours")
    weekend = [r for r in plain["trades"] if vu.weekday(r["signal_ms"] + H) >= 5]
    assert weekend, "the world has dips whose order goes in on a weekend"
    assert len(busy["trades"]) == len(plain["trades"]) - len(weekend)
    assert all(vu.weekday(r["signal_ms"] + H) < 5 for r in busy["trades"])
    f = busy["summary"]["filter"]
    assert f["blocked"] == len(weekend) and f["signal_candles"] == len(plain["trades"])
    assert busy["summary"]["filter_words"].startswith(
        f"filter blocked {len(weekend)} of {f['signal_candles']} signal candles")
    assert "blocked" not in plain["summary"]["filter"]


def test_the_exit_is_the_familys_own(world, monkeypatch):
    seen = []
    real = ve.walk

    def spy(bars, dirs, spec, **kw):
        seen.append((spec, kw.get("forced"), kw["flat_slip"], kw["risk_usd"]))
        return real(bars, dirs, spec, **kw)

    monkeypatch.setattr(ve, "walk", spy)
    got = _run(world, risk_usd=2.5)
    assert len(seen) == 1, "one walk over the window: no older / unseen split, no random runs"
    spec, forced, slip, risk = seen[0]
    assert spec == vf.exit_spec("v3_snap", 1.5, "1h")
    assert forced is None and risk == 2.5
    assert slip == pytest.approx(0.0003), "the coin's own gap: one live reading (none recorded)"
    target, stop = vrs.exit_words("v3_snap", "k1.5", "1h")
    p = got["provenance"]
    assert (p["target"], p["stop"]) == (target, stop)
    assert {r["why"] for r in got["trades"]} <= {"TP", "SL", "TIME", "END"}


def test_the_id_is_stable_and_differs_by_setting_and_filter(world):
    a = _run(world)["id"]
    assert a == _run(world, risk_usd=5)["id"], "the risk changes dollars, never which strategy"
    assert a == br.row_code(SYM, "1h", "v3_snap", 0.0, 0.0, 0.0, "flat",
                            plan=vf.combo_key("v3_snap", "k1.5", "1h", "none"), res="v3")
    ids = {vp.family_id(vp.parse_family(dict(BODY, **o))) for o in
           ({}, {"setting": "k2"}, {"filter": "busy_hours"}, {"tf": "4h"})}
    assert len(ids) == 4
    assert a != br.row_code(SYM, "1h", "v3_snap", 0.0, 0.0, 0.0, "flat",
                            plan=vf.combo_key("v3_snap", "k1.5", "1h", "none"), res="1m")


def test_the_run_button_reaches_the_family_path(world, monkeypatch):
    monkeypatch.setattr(vp, "load_plan", lambda path=None: _plan())
    monkeypatch.setattr(vp, "run_family",
                        lambda body, **k: {"family": body["signal"], "setting": body["setting"]})
    assert vp.run(dict(BODY), fx=world) == {"family": "v3_snap", "setting": "k1.5"}


@pytest.mark.parametrize("bad, words", [
    ({"tf": "1d"}, ["timeframe", "1h, 4h"]),
    ({"setting": "k9"}, ["setting", "k1.5, k2"]),
    ({"setting": True}, ["setting"]),
    ({"filter": "magic"}, ["filter"]),
    ({"signal": "v3_trend", "tf": "1d", "setting": "n50", "filter": "funding_minutes"},
     ["filter", "funding_minutes is not tried on 1d"]),
    ({"sym": "NOPE_USDT"}, ["NOPE_USDT"]),
    ({"sym": ""}, ["coin"]),
    ({"days": 45}, ["days"]),
    ({"risk_usd": 0}, ["risk"]),
])
def test_a_bad_family_pick_is_refused_naming_its_box(world, bad, words):
    with pytest.raises(ValueError) as e:
        _run(world, **bad)
    for w in words:
        assert w in str(e.value)


def test_a_setting_is_read_by_its_key_or_its_value():
    assert vp.parse_family(dict(BODY, setting=2))["setting"] == "k2"
    assert vp.parse_family(dict(BODY, signal="v3_trend", tf="1d", setting="n50"))["value"] == 50


def test_the_options_offer_each_familys_own_boxes(world, monkeypatch):
    monkeypatch.setattr(vp, "load_plan", lambda path=None: _plan())
    o = vp.options(fx=world)
    fams = {f["name"]: f for f in o["families"]}
    assert list(fams) == list(vf.FAMILIES)
    for name, d in vf.FAMILIES.items():
        f = fams[name]
        assert f["tfs"] == list(d["tfs"])
        assert [x["key"] for x in f["settings"]] == [vf.setting_key(name, v)
                                                     for v in d["settings"]]
        for tf in d["tfs"]:
            assert [x["key"] for x in f["filters"][tf]] == list(vf.filters_for(tf))
            for x in f["settings"]:
                assert (x["exit"][tf]["target"], x["exit"][tf]["stop"]) == \
                    vrs.exit_words(name, x["key"], tf)
    assert fams["v3_trend"]["not_tried"]["1d"][0]["key"] == "funding_minutes"
    assert fams["v3_trend"]["not_tried"]["4h"] == []
    assert fams["v3_trend"]["settings"][1]["words"] == "n = 50 days"
    assert o["plan"]["end_ms"] == PLAN_END and o["plan"]["last_month"] == "2026-10"
    assert set(vp.FILTER_WORDS) == set(vfl.NAMES)


def test_the_options_say_why_when_the_plan_cannot_be_read(world, monkeypatch, tmp_path):
    monkeypatch.setattr(vp, "load_plan", lambda path=None: vu.load(tmp_path / "missing.json"))
    o = vp.options(fx=world)
    assert o["plan"] is None and "FileNotFoundError" in o["plan_error"]
    assert o["families"], "the boxes still list the families"


# ------------------------------------------------------------------ the check
def _verdicts():
    passed = {"id": "AAAA1111", "family": "v3_snap", "tf": "1h", "filter": "none",
              "setting": "k2", "passed": True, "failed": "",
              "unseen": {"trades": 320, "wins": 200, "losses": 120, "win_rate": 0.625,
                         "profit": 64.004, "worst_run_usd": -4.2, "worst_run_trades": 5},
              "random_runs": {"median_trades": 290, "real_trades": 320},
              "lev": [12, 20], "notional": [40.0, 130.0]}
    chose = {"id": "BBBB2222", "family": "v3_trend", "tf": "1d", "filter": "btc_mood",
             "setting": None, "passed": False, "failed": "choose",
             "why": "no setting had 30 trades on the older days"}
    idle = {"id": "CCCC3333", "family": "v3_breakout", "tf": "1d", "filter": "none",
            "setting": "n20", "passed": False, "failed": "profit",
            "unseen": {"trades": 0, "wins": 0, "losses": 0, "win_rate": None, "profit": 0.0,
                       "worst_run_usd": 0.0, "worst_run_trades": 0},
            "random_runs": {"median_trades": 0, "real_trades": 0}, "lev": None,
            "notional": None}
    return [passed, chose, idle]


def test_the_check_is_read_with_its_provenance_and_every_cell_says_something(tmp_path):
    f = tmp_path / "verdicts.json"
    f.write_text(json.dumps({"plan_id": "abc", "plan_end": PLAN_END, "risk_usd": 5.0,
                             "runs": 200, "coins": ["BTC_USDT", "ETH_USDT", "XAU_USDT"],
                             "judged_at": 1_793_000_000.0, "verdicts": _verdicts()}),
                 encoding="utf-8")
    t = vp.tested(tmp_path / "rows.db", check_file=f)
    assert t["state"] == "not_run", "Part 2b's store is still not run"
    c = t["check"]
    assert c["state"] == "ok" and c["coins"] == ["BTC_USDT", "ETH_USDT", "XAU_USDT"]
    assert (c["risk_usd"], c["runs"], c["plan_end"]) == (5.0, 200, PLAN_END)
    assert c["lev"] == [12, 20] and c["notional"] == [40.0, 130.0]
    ok, chose, idle = c["verdicts"]
    assert ok["verdict"] == "PASSED" and ok["profit"] == 64.0 and ok["trades"] == 320
    assert (ok["random_median_trades"], ok["real_trades"]) == (290, 320)
    assert ok["blank"] == "" and ok["why"] == "chose k2 on the older days"
    assert chose["verdict"] == "FAILED at choose" and chose["trades"] is None
    assert chose["blank"] == "not judged: no setting was chosen"
    assert chose["why"] == "no setting had 30 trades on the older days"
    assert idle["verdict"] == "FAILED at profit" and idle["trades"] == 0
    assert idle["win_rate"] is None and idle["blank"] == "no trade on the unseen days"
    for row in c["verdicts"]:
        for k, v in row.items():
            assert v is not None or row["blank"], f"{row['id']} {k} is empty with no reason"


def test_an_old_bare_list_says_to_judge_again(tmp_path):
    f = tmp_path / "verdicts.json"
    f.write_text(json.dumps(_verdicts()), encoding="utf-8")
    c = vp.tested(tmp_path / "rows.db", check_file=f)["check"]
    assert c["state"] == "old" and "run judge again" in c["words"]
    assert "verdicts" not in c or not isinstance(c["verdicts"], list)


def test_no_check_and_an_unreadable_check_each_say_so(tmp_path):
    assert vp.check(tmp_path / "none.json")["state"] == "none"
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    c = vp.check(bad)
    assert c["state"] == "unreadable" and "JSONDecodeError" in c["words"]

