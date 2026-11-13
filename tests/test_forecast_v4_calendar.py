"""Forecast v4 -> Best switch-on rules: a calendar per rule set, and a clicked day's trades (Nov 13, 2026).

Operator: "when i click and id in Best switch-on rules this month currently you are showing months only i
want a calendar, when i click a day in calendar, show me the trades it made in that day".

A day is the walk's own: 12:00am to 12:00am UTC, its trades the ones OPENED that day. The boxes are filed
by the walk that counted the months; a day's list is the walk's own test asked of the walk's own filed
numbers - held equal for EVERY rule set below, so the list under a box can never add up to another figure.
The fixtures share tests/test_forecast_v4.py's one timeline."""
import json
import sqlite3
from pathlib import Path

import numpy as np
import pytest

from tests.test_forecast_v4 import DAY, H, _line, _make, _pick, daily, ms, rule
from tradingagents import forecast_v4 as f4

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture()
def built(tmp_path, monkeypatch):
    return _make(tmp_path, monkeypatch)


def _busy_day():
    """MMM 15m: a $1 win every day Jul 01 - Nov 04 at 10:00, and on Oct 15 twelve more trades from
    1:00am, one an hour, the 5th and 9th losing $2."""
    base = daily(ms(2026, 7, 1), ms(2026, 11, 4), lambda i: 1.0)
    burst = [(ms(2026, 10, 15, 1 + i), ms(2026, 10, 15, 1 + i) + H // 2, -2.0 if i in (4, 8) else 1.0)
             for i in range(12)]
    pick = _pick("ta_ma_pullback", 0.015, 0.03, sorted(base + burst))
    return {"MMM|15m": _line("MMM", "15m", [pick], ms(2026, 10, 1))}


@pytest.fixture()
def busy(tmp_path, monkeypatch):
    return _make(tmp_path, monkeypatch, extra_taall=_busy_day())


def _all_filed(doc):
    folder, index, pos = f4._walk_files(doc)
    t = {"tfc": f4._read(folder, index, "s_tfc"), "skc": f4._read(folder, index, "s_skc"),
         "tpf": f4._read(folder, index, "s_tpf").astype(bool), "slc": f4._read(folder, index, "s_slc").astype(bool)}
    sid = f4._read(folder, index, "sid").astype(np.int64)
    trades = {k: v[sid] for k, v in t.items()}
    for W in f4.WINDOWS:
        trades[f"n{W}"] = f4._read(folder, index, f"n{W}")
        trades[f"w{W}"] = f4._read(folder, index, f"w{W}")
    flags = f4._read(folder, index, "flags")
    for bit, name in enumerate(index["flags"]):
        trades[name] = (flags >> bit) & 1 == 1
    offsets = np.array(index["offsets"])
    day = np.searchsorted(offsets, np.arange(index["rows"]), side="right") - 1
    return folder, index, pos, trades, day, f4._read(folder, index, "p4").astype(np.int64)


def test_every_rule_sets_days_add_up_to_its_months_and_total(built):
    doc = f4.load()
    checked = 0
    for r in doc["rules"]:
        got = f4.rule_days(r["id"])
        assert got["found"] and got["trades"] == r["trades"], r["id"]
        assert got["profit"] == pytest.approx(r["profit"], abs=1e-6)
        assert sum(v["trades"] for v in got["days"].values()) == r["trades"]
        assert sum(v["wins"] for v in got["days"].values()) == r["wins"]
        for i, m in enumerate(doc["walk"]["months"]):
            inside = [v for k, v in got["days"].items() if k[:7] == m["key"]]
            assert sum(v["trades"] for v in inside) == r["months"][i]["trades"]
            assert sum(v["pnl"] for v in inside) == pytest.approx(r["months"][i]["profit"], abs=1e-6)
        checked += bool(r["trades"])
    assert checked > 20, "the fixture must walk rule sets that traded"


def test_a_days_list_is_the_walks_own_trades_for_every_rule_set(busy):
    """The list under a box is `_takes` over the filed trades; the box is the walk. Every rule set, every
    day: the same count and the same dollars - so a second copy of the switch-on test cannot drift."""
    doc = f4.load()
    folder, index, pos, t, day, p4 = _all_filed(doc)
    D = index["D"]
    for r in doc["rules"]:
        m = f4._takes(t, r)
        n = np.bincount(day[m], minlength=D)
        p = np.bincount(day[m], weights=p4[m], minlength=D) / 10_000
        i = pos[r["id"]]
        box_n = f4._read(folder, index, "days_trades", i * D, D)
        box_p = f4._read(folder, index, "days_profit", i * D, D)
        assert (n == box_n).all(), r["id"]
        assert np.allclose(p, box_p, atol=1e-6), r["id"]


def test_a_day_lists_its_trades_oldest_first_ten_a_page_with_the_whole_days_total(busy):
    r = rule(7, 50, 3, tf="15m")
    got = f4.rule_day(r["id"], "2026-10-15")
    # the 12 of the burst and the daily 10:00 win: 13 trades, 11 won: 11 x $1 - 2 x $2 = +7.00
    assert (got["total"], got["wins"], got["losses"]) == (13, 11, 2)
    assert got["profit"] == pytest.approx(7.0)
    assert got["agrees"] and got["box"] == {"trades": 13, "profit": 7.0}
    assert got["pages"] == 2 and len(got["rows"]) == 10
    opened = [x["opened_s"] for x in got["rows"]]
    assert opened == sorted(opened) and opened[0] == ms(2026, 10, 15, 1) // 1000
    row = got["rows"][0]
    assert (row["coin"], row["tf"], row["side"], row["closed_by"]) == ("MMM", "15m", "long", "target (TP)")
    assert row["closed_s"] == (ms(2026, 10, 15, 1) + H // 2) // 1000 and row["id"]
    assert sum(1 for x in got["rows"] if x["profit"] < 0) == 2            # 5:00am and 9:00am
    second = f4.rule_day(r["id"], "2026-10-15", page=2)
    assert second["profit"] == got["profit"]                               # the day's, not the page's
    # 10:00am daily win (closes 11:00am, after the 10:00am burst trade that closed 10:30am), 11am, 12pm
    assert [x["profit"] for x in second["rows"]] == [1.0, 1.0, 1.0]
    assert second["rows"][0]["closed_s"] == ms(2026, 10, 15, 11) // 1000


def test_the_base_margin_scales_every_dollar_and_no_count(busy):
    r = rule(7, 50, 3, tf="15m")
    five, ten = f4.rule_day(r["id"], "2026-10-15"), f4.rule_day(r["id"], "2026-10-15", base_margin=10)
    assert ten["total"] == five["total"] and ten["profit"] == pytest.approx(2 * five["profit"])
    assert [x["profit"] for x in ten["rows"]] == pytest.approx([2 * x["profit"] for x in five["rows"]])
    d5, d10 = f4.rule_days(r["id"]), f4.rule_days(r["id"], base_margin=10)
    assert d10["days"]["2026-10-15"]["pnl"] == pytest.approx(2 * d5["days"]["2026-10-15"]["pnl"])
    assert d10["days"]["2026-10-15"]["trades"] == d5["days"]["2026-10-15"]["trades"]


def test_the_calendar_is_the_walks_utc_days_with_the_span_it_covers(built):
    r = rule(7, 90, 5, tf="1h", tp=">")             # AAA: a $1 win every day
    got = f4.rule_days(r["id"])
    assert got["from"] == "2026-08-01" and got["to"] == "2026-11-05"
    assert got["days"]["2026-08-08"] == {"pnl": 1.0, "trades": 1, "wins": 1, "losses": 0, "coins": []}
    assert "2026-11-05" not in got["days"]                         # AAA's last trade is Nov 04


def test_a_day_that_is_not_a_day_is_refused_and_one_outside_the_walk_says_so(built):
    r = rule(7, 90, 5, tf="1h", tp=">")
    for bad in ("2026-13-01", "Oct 15", "", "2026-10-15T00:00"):
        with pytest.raises(f4.BadAsk):
            f4.rule_day(r["id"], bad)
    got = f4.rule_day(r["id"], "2026-01-01")
    assert got["rows"] == [] and "outside the days walked" in got["why"]


def test_an_unknown_rule_set_says_so_and_a_twin_finds_the_one_listed(built):
    assert f4.rule_days("ZZZZZZZZ")["found"] is False
    assert f4.rule_day("ZZZZZZZZ", "2026-10-15")["found"] is False
    doc = f4.load()
    twin, listed = next(iter(doc["same_as"].items()))
    assert f4.rule_days(twin)["id"] == listed


def test_a_forecast_from_before_the_calendar_says_when_it_comes(built):
    doc = f4.load()
    r = rule(7, 90, 5, tf="1h", tp=">")
    name = doc.pop("walk_dir")
    try:
        assert "next build" in f4.rule_days(r["id"])["why"]
        assert "next build" in f4.rule_day(r["id"], "2026-10-15")["why"]
    finally:
        doc["walk_dir"] = name


def test_a_store_rebuilt_after_the_forecast_names_no_strategy_and_says_why(busy):
    r = rule(7, 50, 3, tf="15m")
    db = f4.v4_store.db_path()
    con = sqlite3.connect(db)
    con.execute("UPDATE meta SET v = '1' WHERE k = 'built_s'")
    con.commit()
    con.close()
    got = f4.rule_day(r["id"], "2026-10-15")
    assert got["total"] == 13 and got["rows"][0]["id"] is None       # the trades still list, unnamed
    assert "rebuilt after this forecast" in got["names_why"]


def test_a_build_keeps_its_folder_and_the_one_before_and_removes_older_ones(built, tmp_path):
    home = f4.out_path().parent
    first = f4.load()["walk_dir"]
    old = home / "walk-1"
    old.mkdir()
    (old / "sid.bin").write_bytes(b"x")
    f4._CACHE.update(key=None, doc=None)
    import time
    time.sleep(1.1)                                   # a build is named by its second
    f4.build(log=lambda *_: None)
    now = f4.load()["walk_dir"]
    left = sorted(p.name for p in home.glob("walk-*"))
    assert now != first and left == sorted([first, now]) and not old.exists()


def test_the_routes_serve_the_calendar_and_refuse_a_bad_day():
    api = (REPO / "tradingagents/api.py").read_text(encoding="utf-8")
    assert '@app.get("/api/forecast-v4/rules/{rule_id}/days")' in api
    assert '@app.get("/api/forecast-v4/rules/{rule_id}/day")' in api
    assert "except forecast_v4.BadAsk as exc:" in api


def test_the_rule_panel_opens_a_calendar_and_a_day_opens_its_trades():
    page = (REPO / "webapp/src/components/forecast/ForecastV4.tsx").read_text(encoding="utf-8")
    cal = (REPO / "webapp/src/components/trade/PnlPanel.tsx").read_text(encoding="utf-8")
    assert "<DayCalendar" in page and "/api/forecast-v4/rules/${" in page
    assert "/day`" in page or '/day"' in page
    assert "onPick?.(k)" in cal and "onPick={onPick}" in page
    # the day's table: every trade's strategy, side, times, what closed it, its profit, and a TOTAL PROFIT
    for word in ("TOTAL PROFIT", "closed by", "opened", "PROFIT $", "fmtWhen("):
        assert word in page, word
    # the server cuts the day; the browser filters nothing it was served
    day_part = page[page.index("function RuleDayTrades"):]
    assert ".filter(" not in day_part[:day_part.index("\n}\n")]
