"""Forecast v4 (Nov 10, 2026): Forecast v2's streaks and "best rules" asked of Backtest v4's trades.

Every fixture puts its trades and the store's last candle on ONE timeline (CLAUDE.md, "A fill may
only see price the order was exposed to": a time-dependent test must share one clock), so the walk
these tests check is the walk a real build runs."""
import json
from datetime import datetime, timezone

import pytest

from tradingagents import forecast_v4 as f4, stores, v4_store as v4

H = 3_600_000
DAY = 24 * H


def ms(y, m, d, h=0):
    return int(datetime(y, m, d, h, tzinfo=timezone.utc).timestamp() * 1000)


END = ms(2026, 11, 5, 12)                     # the store's last candle: walk from Aug 01, 2026


def _pick(strategy, stop, target, trades, *, label=None):
    tr = [[en, ex, 1, "TP" if p > 0 else "SL", p] for en, ex, p in trades]
    return {"label": label or f"{strategy}(n=1) stop {stop * 100:g}%", "strategy": strategy,
            "params": {"n": 1}, "stop": stop, "target": target, "older": {}, "newer": {},
            "older_lost": False, "trades": tr}


def _line(coin, tf, picks, split):
    return {"coin": coin, "tf": tf, "fee": 0.00075, "slip": 0.001, "bars": 900, "combos": len(picks),
            "split_ms": split, "start_ms": ms(2026, 6, 1), "end_ms": END, "bar": 0.0, "picks": picks}


def daily(first, last, pnl_of, hour=10):
    """One trade a day opened at `hour`:00 and closed an hour later, from `first` to `last`."""
    out, t, i = [], first, 0
    while t <= last:
        out.append((t + hour * H, t + (hour + 1) * H, pnl_of(i)))
        t += DAY
        i += 1
    return out


@pytest.fixture()
def built(tmp_path, monkeypatch):
    folder = tmp_path / "acs"
    folder.mkdir()
    # AAA 1h: a win every day from Jul 01 to Nov 04 - passes every rule its trade count allows
    always = _pick("ta_ma_pullback", 0.015, 0.03, daily(ms(2026, 7, 1), ms(2026, 11, 4), lambda i: 1.0))
    # LLL 30m: three wins and a loss that all OPEN and CLOSE on Sep 10, then one win on Sep 11. A day's
    # pick may only read trades that closed BEFORE that day: nothing on Sep 10 can count.
    leak = _pick("ta_ma_pullback", 0.015, 0.03, [
        (ms(2026, 9, 10, 1), ms(2026, 9, 10, 2), 1.0), (ms(2026, 9, 10, 3), ms(2026, 9, 10, 4), 1.0),
        (ms(2026, 9, 10, 5), ms(2026, 9, 10, 6), 1.0), (ms(2026, 9, 10, 12), ms(2026, 9, 10, 13), -5.0),
        (ms(2026, 9, 11, 12), ms(2026, 9, 11, 13), 2.0)])
    # RRR 4h: wins every day, then three losses in a row Oct 01-03, then wins again
    runs = _pick("ta_ma_pullback", 0.03, 0.06, daily(ms(2026, 7, 1), ms(2026, 10, 20),
                                                     lambda i: -1.0 if 92 <= i <= 94 else 1.0))
    # SSS 1d: a loss, then six wins in a row ending at its last trade
    streak = _pick("bf_momentum", 0.015, None, daily(ms(2026, 10, 25), ms(2026, 11, 1),
                                                     lambda i: -1.0 if i == 1 else 1.0))
    # CCC 1h from the CHOSEN skill: split Oct 01 - its trades opened before then are left out
    chosen = _pick("sma_crossover", 0.03, None, daily(ms(2026, 9, 1), ms(2026, 10, 30), lambda i: 1.0))
    lines = {
        "AAA|1h": _line("AAA", "1h", [always], ms(2026, 10, 1)),
        "LLL|30m": _line("LLL", "30m", [leak], ms(2026, 10, 1)),
        "RRR|4h": _line("RRR", "4h", [runs], ms(2026, 10, 1)),
        "SSS|1d": _line("SSS", "1d", [streak], ms(2026, 10, 1)),
    }
    (folder / "skilltaall.json").write_text(json.dumps({"lines": lines}), encoding="utf-8")
    (folder / "skill.json").write_text(json.dumps({"lines": {"CCC|1h": _line("CCC", "1h", [chosen],
                                                                             ms(2026, 10, 1))}}),
                                       encoding="utf-8")
    db = tmp_path / "v4" / "rows.db"
    monkeypatch.setattr(stores, "V4", stores.Store(**{**stores.V4.__dict__, "home": tmp_path / "v4",
                                                      "rows_db": db}))
    v4.build(folder, target=db, log=lambda *_: None)
    f4._CACHE.update(key=None, doc=None)
    out = f4.build(log=lambda *_: None)
    return out


def rule(window, wr, n, tf="", skill="", tp="any", cap=0.0):
    rid = f4.rule_id(window, wr, n, tp, cap, tf, skill)
    got = f4.rules_page({"q": rid})["rows"]
    assert got, f"rule set {rid} not walked"
    return got[0]


def test_the_walk_starts_three_whole_months_before_the_last_candle(built):
    w = built["walk"]
    assert w["from_s"] == ms(2026, 8, 1) // 1000
    assert [m["key"] for m in w["months"]] == ["2026-08", "2026-09", "2026-10", "2026-11"]
    assert [m["complete"] for m in w["months"]] == [True, True, True, False]


def test_a_days_pick_never_reads_a_trade_that_closed_that_day(built):
    r = rule(7, 50, 3, tf="30m")
    # Sep 10: nothing closed before 12:00am, so no trade of Sep 10 counts (the -5 loss would);
    # Sep 11: 3 wins + 1 loss closed before it, 75% -> its +2 win counts
    assert (r["trades"], r["wins"], r["profit"]) == (1, 1, 2.0)


def test_months_add_up_to_the_total_and_wins_plus_losses_are_the_trades(built):
    for r in f4.rules_page({"traded": True, "page": 1})["rows"]:
        assert r["wins"] + r["losses"] == r["trades"]
        assert round(sum(m["profit"] for m in r["months"]), 4) == pytest.approx(r["profit"])
        assert sum(m["trades"] for m in r["months"]) == r["trades"]


def test_this_month_is_predicted_from_the_whole_months_only(built):
    r = rule(7, 90, 5, tf="1h", tp=">")
    # AAA wins $1 a day: August and October 31 days, September 30 - November so far is not used
    assert r["predicted"]["months"] == 3
    assert r["predicted"]["low"] == 30.0 and r["predicted"]["high"] == 31.0
    assert r["predicted"]["profit"] == pytest.approx((31 + 30 + 31) / 3, abs=1e-3)
    assert r["months"][3]["complete"] is False and r["months"][3]["trades"] == 4   # Nov 01-04


def test_the_worst_losing_run_is_its_sum_and_its_length_in_closing_order(built):
    r = rule(30, 50, 3, tf="4h")
    assert (r["worst_run"], r["worst_run_n"]) == (-3.0, 3)


def test_the_chosen_skills_trades_before_its_split_are_left_out(built):
    s = f4.summary()
    assert s["used"]["left_out"] == 30                     # Sep 01-30: opened before the Oct 01 split
    assert "chosen" in s["used"]["left_out_why"]
    r = rule(7, 50, 3, tf="1h", skill="backtesting-trading-strategies")
    # its first usable trade is Oct 01, so its first pick with 3 trades in the window is Oct 04
    first = min(m for m in range(4) if r["months"][m]["trades"])
    assert r["months"][first]["trades"] == 27              # Oct 04-30


def test_one_strategy_alone_is_its_own_random_pick_and_could_be_luck(built):
    r = rule(7, 90, 5, tf="1h", tp=">")
    assert r["random_profit"] == pytest.approx(r["profit"])
    assert r["luck"] is True and r["beat_days"] == 0


def test_a_streak_is_the_run_ending_at_the_newest_trade(built):
    page = f4.streaks_page({"kind": "win", "min": 3, "recent": 0})
    s = next(x for x in page["rows"] if x["coin"] == "SSS")
    assert s["length"] == 6 and s["profit"] == 6.0 and s["trades"] == 8 and s["wins"] == 7
    assert s["follow"]["k"] == 6 and s["follow"]["cases"] >= 1
    assert f4.streaks_page({"kind": "win", "min": 7, "recent": 0, "q": "SSS"})["total"] == 0


def test_a_streak_whose_last_trade_is_old_is_left_out_by_recent_and_said(built):
    rec = f4.streaks_page({"kind": "win", "min": 3, "recent": 7})
    assert "RRR" not in {x["coin"] for x in rec["rows"]}          # last trade Oct 20
    assert any("last 7 days" in t for t in rec["filters"])


def test_ten_a_page_the_id_search_overrides_and_the_base_margin_scales_dollars(built):
    p = f4.rules_page({"traded": True})
    assert len(p["rows"]) <= 10 and p["per_page"] == 10
    one = p["rows"][0]
    got = f4.rules_page({"q": "#" + one["id"].lower(), "tf": "1d", "min_profit": 99999})
    assert [r["id"] for r in got["rows"]] == [one["id"]]
    two = f4.rules_page({"q": one["id"], "base_margin": 10})["rows"][0]
    assert two["profit"] == pytest.approx(one["profit"] * 2) and two["worst_run"] == pytest.approx(one["worst_run"] * 2)


def test_tp_and_sl_ceilings_read_the_widest_the_rule_can_switch_on(built):
    cap = f4.rules_page({"max_sl": 1.5, "traded": False})
    assert cap["total"] and all(r["widest_sl"] <= 1.5 for r in cap["rows"])
    tp = f4.rules_page({"max_tp": 3, "traded": False})
    assert all(r["widest_tp"] is not None and r["widest_tp"] <= 3 for r in tp["rows"])
    assert any("TP 3% or smaller" in t for t in tp["filters"])


def test_an_empty_answer_names_what_was_examined(built):
    p = f4.rules_page({"min_profit": 10 ** 9})
    assert p["total"] == 0 and "every rule set was examined" in p["why"] and str(p["of"]) in p["why"].replace(",", "")


def test_no_forecast_says_how_to_build_one(tmp_path, monkeypatch):
    monkeypatch.setattr(stores, "V4", stores.Store(**{**stores.V4.__dict__, "home": tmp_path / "none"}))
    f4._CACHE.update(key=None, doc=None)
    s = f4.summary()
    assert s["ready"] is False and "forecast_v4 build" in s["why"]
    assert f4.rules_page({})["rows"] == [] and f4.streaks_page({})["rows"] == []


def test_the_rule_id_is_hashed_from_the_rule_and_is_stable():
    a = f4.rule_id(15, 70, 10, ">", 1.5, "1h", "")
    assert a == f4.rule_id(15, 70.0, 10, ">", 1.5, "1h", "") and len(a) == 8
    assert a != f4.rule_id(15, 70, 10, ">", 0.0, "1h", "")


# ------------------------------------------------------------------ the page
REPO = __import__("pathlib").Path(__file__).resolve().parents[1]


def _panel():
    return (REPO / "webapp/src/components/forecast/ForecastV4.tsx").read_text(encoding="utf-8")


def test_forecast_v4_is_under_auto_trade_once():
    assert (REPO / "webapp/src/app/(admin)/forecast-v4/page.tsx").is_file()
    nav = (REPO / "webapp/src/layout/AppSidebar.tsx").read_text(encoding="utf-8")
    assert nav.count('path: "/forecast-v4"') == 1 and 'name: "Forecast v4"' in nav
    auto = nav[nav.index('name: "Auto Trade"'):nav.index('name: "Candles"')]
    assert 'path: "/forecast-v4"' in auto


def test_the_rules_table_carries_every_required_column_and_the_count_tested_above_it():
    p = _panel()
    for col in ('"ID"', '"PROFIT / TOTAL $"', '"TP"', '"SL"', '"leverage"', '"trades"', '"wins / losses"',
                '"worst losing run"', '"beat random"', "a day", "TOTAL PROFIT", "rule sets tested",
                "margin a trade at", "of coin"):
        assert col in p, col
    for box in ("max TP %", "max SL %", "min win rate %", "min trades", "min profit $", "find #id",
                "base margin $", "clear all", "made money"):
        assert box in p, box


def test_the_page_filters_nothing_itself_and_prints_dates_one_way():
    p = _panel()
    assert not __import__("re").search(r"rows\??\.filter\(", p)
    assert "new Date(" not in p and "toLocaleDateString" not in p and "toLocaleTimeString" not in p
    assert "fmtWhen" in p


def test_the_api_serves_the_summary_the_rules_and_the_streaks():
    api = (REPO / "tradingagents/api.py").read_text(encoding="utf-8")
    for route in ('"/api/forecast-v4"', '"/api/forecast-v4/rules"', '"/api/forecast-v4/streaks"'):
        assert f"@app.get({route})" in api, route


def test_best_worst_month_first_lists_rule_sets_with_every_whole_month_before_thin_ones(built):
    rows = []
    page = 1
    while True:
        p = f4.rules_page({"sort": "rank", "page": page})
        rows += p["rows"]
        if page >= p["pages"]:
            break
        page += 1
    thin = [bool((r["predicted"] or {}).get("thin")) for r in rows if r["rank"] is not None]
    assert thin == sorted(thin)                       # every False (3 whole months) before any True
