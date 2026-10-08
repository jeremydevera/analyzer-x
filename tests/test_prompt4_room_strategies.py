"""Prompt 4: find new winning room strategies and keep them (Oct 02, 2026).

Operator: "when i run the prompt #4 its up to you what kind of combination you
want, like last 15 days or last 7 days or last 30 days with Tp highger than sl
or 90%winrate ... look for all kinds of combination then add it in room
strategy", and before it started: "make sure to ask me if there will be
potential bugs or something that will hurt data".

Every test writes to tmp_path through ROOM_STRATEGIES_HOME — never the real,
never-delete store. Trades sit on one timeline: Jul 01 to Oct 02, 2026.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pytest

from tradingagents import forecast_rules as fr
from tradingagents import room_strategies as rst
from tradingagents import watcher_research as rs

ROOT = Path(__file__).resolve().parents[1]
REAL = {"took": 0.5, "gap": 0.1}
END = int(dt.datetime(2026, 10, 2, 12).timestamp() * 1000)


def ms(y, m, d, h=12):
    return int(dt.datetime(y, m, d, h).timestamp() * 1000)


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("ROOM_STRATEGIES_HOME", str(tmp_path / "store"))
    rst._KEPT.clear()
    rst._TABLE.clear()
    yield tmp_path / "store"
    rst._KEPT.clear()
    rst._TABLE.clear()


def test_every_shape_and_window_is_a_dial_and_old_ids_hold():
    assert set(rst.WINDOWS) == {7, 15, 30} and set(rst.SHAPES) == {"any", ">", "1.5x", "2x", "=", "<"}
    assert rst.LINES[0] == 40.0 and rst.LINES[-1] == 95.0 and 40 in rst.TRADES
    c = fr.cfg_of(30, 90, 40, ">", 2.0)
    assert fr.rule_id({**c, "min_tp": 0.0}) == fr.rule_id(c), "an unset floor never moves an id"
    assert fr.rule_id({**c, "min_tp": 2.0}) != fr.rule_id(c)
    ok, why = fr.deployable(rst.cfg(7, 60, 3, ">", 2.0))
    assert not ok and "7-day window" in why
    assert fr.deployable(rst.cfg(15, 70, 50, "=", 2.0, 1.0))[0], "rooms run '=' and a target floor"
    assert fr.tp_ok(np.array([1.0]), np.array([1.0]), "=").all()
    assert rs._tp_ok(np.array([3.0]), np.array([2.0]), "1.5x").all()


def test_round_one_is_every_known_rule_set_once_and_survives_the_file():
    r = rst.round1()
    ids = [rst.sid(c) for c in r]
    assert len(ids) == len(set(ids)) >= 8064
    assert {fr.rule_id(c) for c in fr.base_grid()} <= set(ids)
    p = rst.write_round("t-round", r)
    try:
        back = rst.read_round(str(p.relative_to(ROOT)).replace("\\", "/"))
        assert [rst.sid(c) for c in back] == ids
    finally:
        p.unlink()
    src = (ROOT / ".github/scripts/research_shard.py").read_text(encoding="utf-8")
    assert 'if scen.startswith("file:"):' in src and "rst.read_round(scen[5:])" in src


def test_new_rounds_never_repeat_a_tried_rule_set():
    b = rst.cfg(30, 70, 20, ">", 2.0)
    n = rst.neighbours([b], {rst.sid(b)})
    got = {rst.dials(c) for c in n}
    assert (15, 70.0, 20, ">", 2.0, 0.0) in got and (30, 65.0, 20, ">", 2.0, 0.0) in got
    assert (30, 70.0, 20, "<", 2.0, 0.0) in got and (30, 70.0, 20, ">", 2.0, 1.0) in got
    assert rst.sid(b) not in {rst.sid(c) for c in n}
    assert rst.neighbours([b], {rst.sid(c) for c in n} | {rst.sid(b)}) == [], "all tried: nothing new"


def _trades(spec):
    """[(y, m, d, pnl), ...] -> [entry, exit, pnl], one hour long."""
    return [[ms(y, m, d) - 3_600_000, ms(y, m, d), p] for y, m, d, p in spec]


def test_a_winner_makes_money_after_the_reality_check_in_every_month_and_the_newest_15_days():
    good = _trades([(2026, 7, 10, 1.0), (2026, 8, 10, 1.0), (2026, 9, 10, 1.0), (2026, 9, 25, 1.0)])
    m = rst.measure(good, END, REAL)
    assert [x["month"] for x in m["months"]] == ["2026-07", "2026-08", "2026-09"]
    assert all(x["complete"] for x in m["months"])
    assert m["months"][0]["corrected"] == round(0.5 * (1.0 - 0.1), 2)
    assert rst.is_winner(m) == (True, "")
    no_recent = rst.measure(good[:3], END, REAL)
    assert rst.is_winner(no_recent)[1] == "lost money in the newest 15 days after the reality check"
    bad_aug = rst.measure(good[:1] + _trades([(2026, 8, 10, -1.0)]) + good[2:], END, REAL)
    assert rst.is_winner(bad_aug)[1] == "lost money in 2026-08 after the reality check"
    # ranked by the WORST complete month, never the best
    assert rst.rank_key(m) > rst.rank_key(bad_aug)


def test_the_store_only_grows_and_the_page_reads_the_newest_line(store):
    c = rst.cfg(15, 70, 50, ">", 2.0)
    w = {"id": rst.sid(c), "cfg": c, "words": fr.words(c), "deployable": True, "deploy_why": "",
         "p4": rst.measure(_trades([(2026, 9, 25, 1.0)]), END, REAL),
         "trades": _trades([(2026, 9, 20, 1.0), (2026, 9, 25, 1.0)])}
    assert rst.keep([w], "r1", "RUN", now=1000) == 1
    assert rst.keep([w], "r1", "RUN", now=2000) == 0, "already kept: not new"
    w2 = {**w, "trades": _trades([(2026, 9, 20, 1.0), (2026, 9, 25, 1.0), (2026, 9, 28, -0.5)])}
    rst.keep([], "r2", "RUN", now=3000, remeasured=[w2])
    lines = (store / "room_strategies.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2, "a re-measure appends, never rewrites"
    k = rst.kept()
    assert len(k) == 1 and k[0]["found_at"] == 1000 and len(k[0]["trades"]) == 3


def test_the_table_re_measures_over_exactly_the_chosen_dates(store):
    c = rst.cfg(7, 60, 3, ">", 2.0)
    t = _trades([(2026, 9, 1, 1.0), (2026, 9, 20, -0.4), (2026, 9, 21, 1.0)])
    rst.keep([{"id": rst.sid(c), "cfg": c, "words": fr.words(c), "deployable": False,
               "deploy_why": "a 7-day window", "p4": rst.measure(t, END, REAL), "trades": t}],
             "r1", "RUN", now=1000)
    from tradingagents import forecast_v2 as f2
    import tradingagents.forecast_v2 as _f2
    _f2_live = f2.live
    try:
        f2.live = lambda *a, **k: {"reality": {"all": REAL}}
        all_ = rst.table(ms(2026, 9, 1, 0) / 1000, ms(2026, 9, 30, 23) / 1000)
        late = rst.table(ms(2026, 9, 15, 0) / 1000, ms(2026, 9, 30, 23) / 1000)
        only_7 = rst.table(ms(2026, 9, 1, 0) / 1000, ms(2026, 9, 30, 23) / 1000, window=15)
    finally:
        _f2.live = _f2_live
    assert all_["rows"][0]["trades"] == 3 and late["rows"][0]["trades"] == 2
    assert late["rows"][0]["profit"] == 0.6 and late["rows"][0]["worst_run"] == -0.4
    assert only_7["matched"] == 0 and only_7["kept"] == 1
    assert all_["rows"][0]["deployable"] is False


def test_the_page_shows_the_room_strategies_and_asks_the_server():
    src = (ROOT / "webapp/src/components/forecast/RoomForecasts.tsx").read_text(encoding="utf-8")
    assert "export function RoomStrategiesSection()" in src and ">Room strategies<" in src
    # shown on the Forecast page directly under Backtest a room (Oct 07, 2026)
    page = (ROOT / "webapp/src/app/(admin)/forecast-v2/page.tsx").read_text(encoding="utf-8")
    assert "<RoomBacktest /><RoomStrategiesSection />" in page
    # the server is asked with what was APPLIED, never with the boxes as typed
    assert "api.roomStrategies({ from_s: ask.from_s, to_s: ask.to_s, min_winrate: ask.min_winrate," in src
    api_py = (ROOT / "tradingagents/api.py").read_text(encoding="utf-8")
    assert '@app.get("/api/forecasts/room-strategies")' in api_py
    assert '@app.get("/api/forecasts/room-strategies/trades")' in api_py


# ------------------------------------------- Apply, last N days, a row's trades
# Operator, Oct 07, 2026 3:37pm: "i want a button to apply filters on this /
# also why do i have last 15 days and last 30 days dropdown? / what i want is
# for it to be textbox, if i input 3 days show me the room strat and its trade
# for past 3 days". Trades on the file's one timeline: every one closes by
# Oct 02, 2026 (END), as every trade prompt 4 saved does.
def _keep_two():
    """#A traded inside Sep 20-30 (2 wins, 1 loss); #B only in July."""
    a = rst.cfg(15, 70, 50, ">", 2.0)
    b = rst.cfg(30, 80, 20, ">", 2.0)
    ta = _trades([(2026, 9, 21, 1.0), (2026, 9, 22, -0.5), (2026, 9, 25, 1.0), (2026, 7, 5, 1.0)])
    ta.sort(key=lambda x: x[1])                              # saved by close, as the store is
    tb = _trades([(2026, 7, 10, 1.0), (2026, 7, 11, 1.0)])
    rst.keep([{"id": rst.sid(c), "cfg": c, "words": fr.words(c), "deployable": True, "deploy_why": "",
               "p4": rst.measure(t, END, REAL), "trades": t} for c, t in ((a, ta), (b, tb))],
             "r1", "RUN", now=1000)
    return rst.sid(a), rst.sid(b)


def test_a_row_with_no_trade_in_the_dates_passes_no_floor():
    """On the old "last 15 days" button 26 of the 992 kept had no trade and a
    90% floor listed 32 rows — those 26 beside the 6 that really won 90%
    (RCA-2026-10-07-N). No win rate cannot clear a win-rate floor, and making
    nothing in the dates cannot clear a profit floor."""
    a, b = _keep_two()
    lo, hi = ms(2026, 9, 20, 0) / 1000, ms(2026, 9, 30, 23) / 1000
    plain = rst.table(lo, hi, reality=REAL)
    assert plain["matched"] == 2 and plain["with_trades"] == 1, "no floor: every kept row, zeros and all"
    for floor in ({"min_winrate": 60}, {"min_profit": 0.0}, {"min_profit": -100.0}):
        got = rst.table(lo, hi, reality=REAL, **floor)
        assert [r["id"] for r in got["rows"]] == [a], floor
    assert rst.table(lo, hi, reality=REAL, min_winrate=90)["matched"] == 0, "#A won 2 of 3 = 66.7%"
    # where the saved trades begin and end rides with every answer
    assert plain["data_start"] == ms(2026, 7, 5) and plain["data_end"] == ms(2026, 9, 25)
    past = rst.table(ms(2026, 10, 4, 0) / 1000, ms(2026, 10, 7, 0) / 1000, reality=REAL, min_winrate=90)
    assert past["with_trades"] == 0 and past["matched"] == 0 and past["kept"] == 2


def test_a_rows_trades_are_exactly_the_ones_its_row_counts():
    """Click an id: its trades that OPENED AND CLOSED in the same dates,
    oldest first, the running total, the TOTAL for the dates — and the row's
    own numbers."""
    a, _ = _keep_two()
    lo, hi = ms(2026, 9, 20, 0) / 1000, ms(2026, 9, 30, 23) / 1000
    row = rst.table(lo, hi, reality=REAL, find=a)["rows"][0]
    got = rst.trades("#" + a.lower(), lo, hi)
    assert (got["trades"], got["wins"], got["losses"], got["profit"], got["winrate"]) == \
        (row["trades"], row["wins"], row["losses"], row["profit"], row["winrate"]) == (3, 2, 1, 1.5, 66.7)
    assert [t["closed"] for t in got["rows"]] == [ms(2026, 9, 21), ms(2026, 9, 22), ms(2026, 9, 25)]
    assert [t["total"] for t in got["rows"]] == [1.0, 0.5, 1.5], "a running total, oldest first"
    assert got["rows"][0]["opened"] == ms(2026, 9, 21) - 3_600_000 and got["saved"] == 4
    assert got["first"] == ms(2026, 7, 5) and got["last"] == ms(2026, 9, 25)
    paged = rst.trades(a, lo, hi, page=2, per=2)
    assert paged["pages"] == 2 and [t["n"] for t in paged["rows"]] == [3]
    assert paged["rows"][0]["total"] == 1.5, "the running total runs across pages"
    none = rst.trades(a, ms(2026, 10, 4, 0) / 1000, ms(2026, 10, 7, 0) / 1000)
    assert none["trades"] == 0 and none["rows"] == [] and none["profit"] == 0.0 and none["saved"] == 4
    with pytest.raises(KeyError):
        rst.trades("NOSUCHID", lo, hi)


def test_a_trade_counts_only_when_it_opened_and_closed_inside_the_dates():
    """Operator, Oct 08, 2026, on "last 1 day": "i want to see the trades for
    past 1 day only because currently i see all past trades". The list held
    every trade that CLOSED in the day, so one opened Oct 05, 2026 7:30pm
    showed in a day starting Oct 07, 2026 7:58pm. A row and its list now
    count a trade only when it opened AND closed inside the dates."""
    def at(d, h, mi=0):
        return int(dt.datetime(2026, 10, d, h, mi).timestamp() * 1000)
    c = rst.cfg(15, 70, 40, "1.5x", 2.0, 2.0)
    t = [[at(5, 19, 30), at(7, 20), -2.24],        # opened two days before: out
         [at(7, 19), at(7, 20), 1.75],             # opened a minute before the day: out
         [at(7, 20, 0), at(7, 20, 45), -1.38],     # opened as the day starts: in
         [at(8, 10), at(8, 11), 1.69],             # in
         [at(8, 19, 30), at(8, 20, 30), 2.0]]      # still open when the day ends: out
    t.sort(key=lambda r: r[1])
    rst.keep([{"id": rst.sid(c), "cfg": c, "words": fr.words(c), "deployable": True, "deploy_why": "",
               "p4": rst.measure(t, END, REAL), "trades": t}], "r1", "RUN", now=1000)
    lo, hi = at(7, 20) / 1000, at(8, 20) / 1000
    row = rst.table(lo, hi, reality=REAL)["rows"][0]
    got = rst.trades(rst.sid(c), lo, hi)
    assert (row["trades"], row["wins"], row["profit"]) == (got["trades"], got["wins"], got["profit"]) \
        == (2, 1, 0.31)
    assert [r["opened"] for r in got["rows"]] == [at(7, 20), at(8, 10)]


def test_the_trades_route_pages_ten_and_names_a_missing_id():
    from fastapi import HTTPException

    from tradingagents import api
    from tradingagents import forecast_v2_api as f2a

    a, _ = _keep_two()
    lo, hi = ms(2026, 7, 1, 0) / 1000, ms(2026, 9, 30, 23) / 1000
    got = api.room_strategy_trades_route(a, lo, hi)
    assert got["per"] == f2a.PER_PAGE and got["trades"] == 4
    # the pop-up's CSV export asks for every trade in one page, never past the cap
    every = api.room_strategy_trades_route(a, lo, hi, per=100_000)
    assert len(every["rows"]) == 4 and every["pages"] == 1
    assert api.room_strategy_trades_route(a, lo, hi, per=10 ** 9)["per"] == api.TRADES_EXPORT_MAX == 100_000
    with pytest.raises(HTTPException) as e:
        api.room_strategy_trades_route("NOSUCHID", lo, hi)
    assert e.value.status_code == 404 and "NOSUCHID" in e.value.detail
    with pytest.raises(HTTPException) as e:
        api.room_strategy_trades_route(a, hi, lo)
    assert e.value.status_code == 400


def _section() -> str:
    src = (ROOT / "webapp/src/components/forecast/RoomForecasts.tsx").read_text(encoding="utf-8")
    return src.split("export function RoomStrategiesSection()")[1].split("\nfunction StrategyTrades(")[0]


def test_nothing_is_asked_until_apply():
    """Every box is a draft. Apply (or Enter in a box) sends them together;
    the boxes never ask the server or move the page while being typed in."""
    s = _section()
    assert 'onSubmit={(e) => { e.preventDefault(); apply(); }}' in s
    assert '<button type="submit"' in s and '"Loading…" : "Apply"}' in s and ">clear</button>" in s
    for line in [l for l in s.splitlines() if "onChange=" in l]:
        assert "setPage" not in line and "reset()" not in line and "api." not in line, line
    assert "useLiveRefresh(load, 60_000, [load])" in s and "}, [applied, page]);" in s
    assert "changed — press Apply to use it" in s, "a box typed in but not applied says so"
    # a box typed in but not a number is refused out loud, never sent as no filter
    assert "min win % takes a number" in _src_all() and "last N days takes a number of days above 0" in _src_all()


def _src_all() -> str:
    return (ROOT / "webapp/src/components/forecast/RoomForecasts.tsx").read_text(encoding="utf-8")


def test_an_answer_is_shown_only_if_it_answers_what_was_applied():
    """Oct 07, 2026 3:37pm: the boxes said min win 90 over "992 of 992 kept"
    — an answer to an earlier ask (the server answers 2 of 992 for 90%)."""
    s = _section()
    assert "if (key === want.current) { setShown({ key, ask, d: x });" in s
    assert "const waiting = !err && (!shown || shown.key !== wantKey);" in s
    # the line above the table names the filters of the ANSWER, not the boxes
    assert "const words = asked ? rsFilterWords(asked) : [];" in s
    assert "{words.length > 0 && ` · ${words.join(\" · \")}`}" in s


def test_apply_shows_loading_and_cannot_be_pressed_until_its_answer_lands():
    """Operator, Oct 07, 2026: "when i click apply, i want to see loading,
    then make apply button disabled". `waiting` is true from the press until
    the answer to what was applied is on screen, and false again on an
    error, so a failed ask never leaves the button dead."""
    s = _section()
    assert '<button type="submit" disabled={waiting} aria-busy={waiting}' in s
    assert '{waiting ? "Loading…" : "Apply"}' in s and "animate-spin" in s
    assert "loading the room strategies…" in s
    assert "${waiting ? \"opacity-50\" : \"\"}" in s, "the old rows are dimmed while the new ones load"
    assert '<button type="button" className={btn} onClick={clear}>clear</button>' in s, \
        "clear is never disabled"


def test_judged_on_room_can_run_it_and_sort_are_gone():
    """Operator, Oct 07, 2026: "also remove these fields its not needed" —
    the three dropdowns. The list keeps one order: the dates' profit, highest
    first, since the worst month went on Oct 08, 2026."""
    s = _section()
    assert "<select" not in s, "no dropdown is left in the filter row"
    for gone in (">judged on", ">a room can run it", ">sort", "draft.win", "draft.dep", "draft.sort",
                 "deployable: ask.deployable", "window: ask.window", "sort: ask.sort"):
        assert gone not in s, gone
    head = _src_all().split("export function RoomStrategiesSection()")[0]
    assert "win: string; dep: string" not in head and "judged on ${a.window}" not in head
    # the server's own default order is the one the list keeps
    assert 'sort: q.sort ?? "profit"' in (ROOT / "webapp/src/lib/api.ts").read_text(encoding="utf-8")


def test_worst_month_money_needed_and_most_open_are_gone():
    """Operator, Oct 08, 2026: "in forecast room strategies i dont need worst
    month no need to compute it, money needed, most open". Not hidden: not
    worked out, not sent, not drawn — and the one order they set became the
    dates' profit. #Y made more in the dates while #X had the better worst
    month, so the old order and the new one disagree here."""
    x = rst.cfg(15, 70, 50, ">", 2.0)
    y = rst.cfg(30, 80, 20, ">", 2.0)
    tx = _trades([(2026, 7, 10, 1.0), (2026, 8, 10, 1.0), (2026, 9, 10, 1.0), (2026, 9, 25, 1.0)])
    ty = _trades([(2026, 7, 10, 0.3), (2026, 8, 10, 0.3), (2026, 9, 22, 3.0)])
    rst.keep([{"id": rst.sid(c), "cfg": c, "words": fr.words(c), "deployable": True, "deploy_why": "",
               "p4": rst.measure(t, END, REAL), "trades": t} for c, t in ((x, tx), (y, ty))],
             "r1", "RUN", now=1000)
    assert rst.rank_key(rst.measure(tx, END, REAL)) > rst.rank_key(rst.measure(ty, END, REAL)),         "the fixture must put #X first by worst month"
    lo, hi = ms(2026, 9, 20, 0) / 1000, ms(2026, 9, 30, 23) / 1000
    got = rst.table(lo, hi, reality=REAL)
    assert [r["id"] for r in got["rows"]] == [rst.sid(y), rst.sid(x)], "profit, highest first"
    assert [r["profit"] for r in got["rows"]] == [3.0, 1.0]
    for row in got["rows"]:
        for gone in ("worst_month", "money_needed", "max_open"):
            assert gone not in row, gone
    assert not hasattr(rst, "_max_open"), "most open is not worked out at all"
    # a page still open from before the change asks for the old order
    old_page = rst.table(lo, hi, reality=REAL, sort="worst_month")
    assert [r["id"] for r in old_page["rows"]] == [r["id"] for r in got["rows"]]
    sec = _section()
    for gone in ('"Most open"', '"Money needed"', '"Worst month"', "r.max_open", "r.money_needed",
                 "r.worst_month"):
        assert gone not in sec, gone
    ts = (ROOT / "webapp/src/lib/api.ts").read_text(encoding="utf-8")
    rows_type = ts.split("export type RoomStrategies = {")[1].split("}[];")[0]
    for gone in ("max_open", "money_needed", "worst_month"):
        assert gone not in rows_type, gone


def test_last_n_days_is_one_box_not_two_buttons():
    src = _src_all()
    assert ">last 15 days</button>" not in src and ">last 30 days</button>" not in src
    assert "const quick = " not in src
    s = _section()
    assert ">or last N days<input" in s and 'placeholder="e.g. 3"' in s
    # the last N x 24 hours up to the moment Apply is pressed
    assert "from_s: days ? nowS - Math.round(days * 86_400) : dayStart(f.from)," in src
    assert "to_s: days ? nowS : dayStart(f.to) + 86_399," in src
    assert "disabled={byDays}" in s, "the dates wait while a number of days decides"


def test_a_range_past_the_saved_trades_says_where_they_end():
    """Every saved trade closes by Oct 02, 2026 8:00am, so "last 3 days" holds
    none: the page names what it examined and how to get newer trades,
    instead of 992 rows of zeros reading as strategies that did nothing."""
    s = _section()
    assert "d.to * 1000 > d.data_end" in s and "d.with_trades === 0" in s
    assert "their trades are measured up to ${fmtWhenMs(d.data_end)}" in s
    # re-tested every day since Oct 07, 2026 (room_strategies_daily): the box
    # says the next re-test brings them up to date, never "run prompt 4"
    assert "the next one brings them up to last night" in s and "run it again" not in s
    trades = _src_all().split("\nfunction StrategyTrades(")[1]
    assert "TOTAL PROFIT" in trades
    # the coin behind every trade since Sep 01, 2026; a trade without one says why
    assert "the replay names the strategy behind a trade only from ${fmtWhenMs(d.named_from)} on." in trades
    assert '<td className={`${td} font-medium`}>{t.coin ?? "—"}</td>' in trades
    assert '"#", "Coin", "Timeframe", "Signal", "TP %", "SL %", "Opened", "Closed", "Held",' in trades
    assert "api.roomStrategyTrades({ id, from_s, to_s, page })" in trades
    assert '<StrategyTrades id={open.id} words={open.words} from_s={d.from} to_s={d.to} />' in s, \
        "a row's trades are read over the dates its row was measured on"


def test_the_id_opens_a_pop_up_with_its_trades_and_export_csv():
    """Operator, Oct 08, 2026: "when i click the id, i want it on pop up then
    i should have option to export via csv"."""
    from tradingagents import api

    src = _src_all()
    s = _section()
    assert 'import { Modal } from "@/components/ui/modal";' in src
    assert 'onClick={(e) => { e.stopPropagation(); setOpen({ id: r.id, words: r.words }); }}>#{r.id}</button>' in s
    assert '<Modal isOpen={!!open} onClose={() => setOpen(null)}' in s
    assert "<td colSpan={cols.length}" not in s, "no trade list opens inside the table any more"
    trades = src.split("\nfunction StrategyTrades(")[1].split("\nfunction CopyId(")[0]
    assert '"Exporting…" : "Export CSV"' in trades and "<CopyId id={d.id} />" in trades
    assert "api.roomStrategyTrades({ id, from_s, to_s, page: 1, per: EXPORT_MAX })" in trades
    # every date as the screen prints it, each cell quoted: "Oct 07, 2026 8:00pm" holds a comma
    assert "fmtWhenMs(t.opened), fmtWhenMs(t.closed)" in trades
    assert """const q = (v: string | number) => `"${String(v).replace(/"/g, '""')}"`;""" in trades
    assert 'q("TOTAL PROFIT")' in trades and "that opened and closed between" in trades
    # the dates' own win rate in the pop-up, and as the CSV's LAST row (Oct 08,
    # 2026: "when i export the csv, show me the winrate for last row")
    assert "lost, win rate {pct(d.winrate)})" in trades
    rows = [ln.strip() for ln in trades.split("const lines = ")[1].split("const url")[0].splitlines()
            if "lines.push(" in ln]
    assert 'q("TOTAL PROFIT")' in rows[-2] and 'q("WIN RATE")' in rows[-1], rows
    assert "a.download = `room-strategy-${id}-${dateBoxAt(from_s)}-to-${dateBoxAt(to_s)}.csv`;" in trades
    assert "const EXPORT_MAX = 100_000;" in src and api.TRADES_EXPORT_MAX == 100_000
    # the page behind stays readable (Oct 08, 2026: "when it pop up why cant i
    # see the contents behind?") — a light dim here; every other pop-up keeps
    # its own blur, the shared component's default
    assert 'backdropClassName="bg-gray-900/20"' in s and "backdrop-blur" not in s
    modal = (ROOT / "webapp/src/components/ui/modal/index.tsx").read_text(encoding="utf-8")
    assert 'backdropClassName = "bg-gray-400/50 backdrop-blur-[32px]",' in modal
    assert "className={`fixed inset-0 h-full w-full ${backdropClassName}`}" in modal


def test_the_merge_scores_every_rule_set_and_keeps_trades_for_winners_only(tmp_path, monkeypatch):
    from tradingagents import research_merge as rmg
    monkeypatch.setattr(rmg.rc, "merge_reports", lambda dirs: {"write": {}})
    monkeypatch.setattr(rmg.rs, "OUT_DIR", tmp_path / "out")
    grid = [rst.cfg(15, 70, 5, ">", 2.0), rst.cfg(30, 80, 5, ">", 2.0)]
    to_min = lambda m: (m // 60_000) - rmg.T0_MIN                       # noqa: E731
    days = {"train": [ms(2026, 7, 10), ms(2026, 8, 10)], "test": [ms(2026, 9, 10), ms(2026, 9, 25)]}
    arrays, meta = {}, {"shard": 0, "chunk": 0, "chunks": 1, "end_ms": END, "books": 10,
                        "rules": [], "strategies": [["S", "VUG", "1h", "macddiv", 0.0, 1.0, 0.5]]}
    for j, c in enumerate(grid):
        meta["rules"].append({"cfg": c, "train": {"slots": 1, "open": 0}, "test": {"slots": 1, "open": 0}})
        sign = 1.0 if j == 0 else -1.0                 # rule 0 wins every month, rule 1 loses
        for part, xs in days.items():
            arrays[f"{j}_{part}_e"] = np.array([to_min(x - 3_600_000) for x in xs], np.int32)
            arrays[f"{j}_{part}_x"] = np.array([to_min(x) for x in xs], np.int32)
            arrays[f"{j}_{part}_p"] = np.array([sign] * len(xs), np.float32)
        arrays[f"{j}_test_s"] = np.zeros(2, np.int32)
    d = tmp_path / "art" / "research-0"
    d.mkdir(parents=True)
    np.savez_compressed(d / "research-0.npz", **arrays)
    (d / "research-0.json").write_text(json.dumps(meta), encoding="utf-8")
    out = json.loads(Path(rmg.merge("t", str(tmp_path / "art"), str(tmp_path), reality=REAL))
                     .read_text(encoding="utf-8"))
    a, b = out["rows"]
    assert a["p4"]["winner"] is True and len(a["p4_trades"]) == 4
    assert b["p4"]["winner"] is False and "p4_trades" not in b, "a loser keeps no trade list"


def test_the_daily_totals_give_the_same_months_as_the_trades():
    """research_shard OUT=daily (Oct 02, 2026): ~1.5 KB a rule set instead of
    its trades — measured on replay-0, 40 rule sets: months identical, the
    same winner verdict for all 40, 63 KB against 4.6 MB."""
    import datetime as _dt
    from tradingagents import watcher_replay as wr
    t = np.asarray(_trades([(2026, 7, 10, 1.0), (2026, 8, 10, -0.2), (2026, 8, 11, 0.9),
                            (2026, 9, 10, 1.0), (2026, 9, 25, 1.0)]), dtype=np.float64)
    mids = wr.local_midnights(int(_dt.datetime(2026, 7, 1).timestamp() * 1000), END)
    edges = np.asarray(mids + [mids[-1] + 86_400_000], dtype=np.int64)
    k = np.searchsorted(edges, t[:, 1], "right") - 1
    n = np.bincount(k, minlength=len(edges) - 1)
    w = np.bincount(k, weights=(t[:, 2] > 0).astype(float), minlength=len(edges) - 1)
    p = np.bincount(k, weights=t[:, 2], minlength=len(edges) - 1)
    a, b = rst.measure(t, END, REAL), rst.measure_days(edges, n, w, p, END, REAL)
    assert [m["corrected"] for m in a["months"]] == [m["corrected"] for m in b["months"]]
    assert rst.is_winner(a) == rst.is_winner(b) and b["total"]["trades"] == 5
    src = (ROOT / ".github/scripts/research_shard.py").read_text(encoding="utf-8")
    assert 'daily = os.environ.get("OUT", "full").strip() == "daily"' in src
    wf = (ROOT / ".github/workflows/research.yml").read_text(encoding="utf-8")
    assert "OUT: ${{ github.event.inputs.output }}" in wf and wf.count("description:") <= 10


def test_a_round_with_a_missing_job_is_never_scored(tmp_path):
    """Replay run 37007971331 put its 1,098 coins on 20 of 40 machines; the
    research plan leaves the 20 empty ones out. A job that is MISSING from
    the coins' shards would add up to a smaller number with nothing saying
    so — the round must refuse, naming it."""
    import pytest
    rep = tmp_path / "reports"
    for shard, coins in ((0, 0), (1, 45), (2, 65)):
        d = rep / f"replay-report-{shard}"
        d.mkdir(parents=True)
        (d / f"replay-report-{shard}.json").write_text(json.dumps({"coins_done": coins}), encoding="utf-8")
    art = tmp_path / "art"

    def job(shard, chunk, books):
        d = art / f"research-{shard}-{chunk}"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"research-{shard}-{chunk}.json").write_text(json.dumps(
            {"shard": str(shard), "chunk": chunk, "chunks": 2, "books": books}), encoding="utf-8")

    job(1, 0, 900), job(1, 1, 900), job(2, 0, 1200)
    with pytest.raises(ValueError, match=r"1 job\(s\) missing .*\(2, 1\)"):
        rst.check_complete(str(art), "x", reports=str(rep))
    job(2, 1, 1100)
    with pytest.raises(ValueError, match=r"shard 2 read \[1100, 1200\] combinations"):
        rst.check_complete(str(art), "x", reports=str(rep))
    job(2, 1, 1200)
    got = rst.check_complete(str(art), "x", reports=str(rep))
    assert got == {"shards": [1, 2], "chunks": 2, "combinations": 2100}, "the empty shard 0 is not asked for"


def test_the_plan_leaves_out_only_the_shards_with_no_coins():
    import importlib.util
    spec = importlib.util.spec_from_file_location("research_plan", ROOT / ".github/scripts/research_plan.py")
    rp_ = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rp_)
    sizes = {"replay-0": 618, "replay-1": 597_955_220, "replay-2": 622, "replay-report-0": 496}
    # replay-3 is not listed at all: KEPT, so its download fails by name
    assert rp_.pick(4, sizes) == ([1, 3], [0, 2])
    assert rp_.pick(4, None) == ([0, 1, 2, 3], []), "an unreadable listing keeps every shard"


def test_the_round_finds_the_replays_own_reports_by_itself(tmp_path, monkeypatch):
    """finish_daily calls check_complete with no folder: the first draft
    looked under the sweep's HOME (~/.tradingagents/backtest/replay), where
    no report has ever been saved, and refused every real round."""
    from tradingagents import replay_collect as rc
    monkeypatch.setattr(rc, "OUT_DIR", tmp_path)
    d = tmp_path / "reports-37007971331" / "replay-report-1"
    d.mkdir(parents=True)
    (d / "replay-report-1.json").write_text(json.dumps({"coins_done": 45}), encoding="utf-8")
    art = tmp_path / "art" / "research-1-0"
    art.mkdir(parents=True)
    (art / "research-1-0.json").write_text(json.dumps({"shard": "1", "chunk": 0, "chunks": 1, "books": 9}),
                                           encoding="utf-8")
    assert rst._reports_dir("37007971331") == tmp_path / "reports-37007971331"
    assert rst.check_complete(str(tmp_path / "art"), "37007971331")["shards"] == [1]


def test_the_table_is_remembered_until_the_store_changes(store, monkeypatch):
    """The page asks every minute; round 1 kept 673 winners holding 2,427,758
    trades. The same dates are measured once — and a new winner is on the
    very next ask."""
    from tradingagents import forecast_v2 as f2
    monkeypatch.setattr(f2, "live", lambda *a, **k: {"reality": {"all": REAL}})
    calls = []
    real = rst._measured
    monkeypatch.setattr(rst, "_measured", lambda *a: calls.append(a) or real(*a))
    t = _trades([(2026, 9, 1, 1.0), (2026, 9, 21, 1.0)])

    def win(c):
        return {"id": rst.sid(c), "cfg": c, "words": fr.words(c), "deployable": True,
                "deploy_why": "", "p4": rst.measure(t, END, REAL), "trades": t}
    rst.keep([win(rst.cfg(30, 80, 20, ">", 2.0))], "r1", "RUN", now=1000)
    a, b = ms(2026, 9, 1, 0) / 1000, ms(2026, 9, 30, 23) / 1000
    first = rst.table(a, b)
    again = rst.table(a, b, sort="profit")
    assert first["kept"] == again["kept"] == 1 and len(calls) == 1, "measured once"
    assert isinstance(rst.kept()[0]["trades"], np.ndarray), "trades held as one array"
    rst.keep([win(rst.cfg(15, 75, 30, ">", 2.0))], "r2", "RUN", now=2000)
    assert rst.table(a, b)["kept"] == 2 and len(calls) == 2, "a new winner shows at once"


def test_the_route_uses_the_forecast_pages_own_reality_check(store, monkeypatch):
    """Working the reality check out again took 14 s a request (122 s on the
    first after a restart, Oct 02, 2026) while the page asks every minute;
    the route hands in the Forecast page's kept copy instead."""
    from tradingagents import api
    from tradingagents import forecast_v2 as f2
    from tradingagents import forecast_v2_api as f2a

    def boom(*a, **k):
        raise AssertionError("worked the reality check out again")
    monkeypatch.setattr(f2, "live", boom)
    monkeypatch.setitem(f2a._LIVE, "value", {"reality": {"all": REAL}, "at": 0})
    got = api.room_strategies_route(ms(2026, 9, 1, 0) / 1000, ms(2026, 9, 30, 23) / 1000)
    assert got["reality"] == REAL and got["kept"] == 0 and got["reality_pending"] is False


def test_the_first_ask_after_a_restart_answers_at_once(store, monkeypatch):
    """Oct 07, 2026: while the first kept copy after a restart was being
    made, the route worked the reality check out itself — 82 s — and the
    page's proxy cut it ("Load failed" in Safari). Now it answers at once with
    the check marked as still being worked out, and never computes it."""
    from tradingagents import api
    from tradingagents import forecast_v2 as f2
    from tradingagents import forecast_v2_api as f2a

    def boom(*a, **k):
        raise AssertionError("worked the reality check out in the request")
    monkeypatch.setattr(f2, "live", boom)
    monkeypatch.setattr(f2a, "live", boom)
    monkeypatch.setitem(f2a._LIVE, "value", None)
    monkeypatch.setitem(f2a._LIVE, "busy", True)          # the first copy is being made
    c = rst.cfg(30, 80, 20, ">", 2.0)
    t = _trades([(2026, 9, 10, 1.0), (2026, 9, 12, -0.5)])
    rst.keep([{"id": rst.sid(c), "cfg": c, "words": fr.words(c), "deployable": True, "deploy_why": "",
               "p4": rst.measure(t, END, REAL), "trades": t}], "r1", "RUN", now=1000)
    got = api.room_strategies_route(ms(2026, 9, 1, 0) / 1000, ms(2026, 9, 30, 23) / 1000)
    assert got["reality_pending"] is True and got["kept"] == 1
    row = got["rows"][0]
    assert row["trades"] == 2 and row["corrected"] is None, "the column waits, the rows do not"
    src = (ROOT / "webapp/src/components/forecast/RoomForecasts.tsx").read_text(encoding="utf-8")
    assert "d.reality_pending" in src and "still being worked out" in src


def test_a_round_is_dealt_across_every_account(monkeypatch):
    """Operator, Oct 02, 2026: "moving forward i want 40 machines to be used
    always". Two accounts, 20 machines each: each gets a share of the
    replay's shards, balanced by size, every shard once — and a list the
    plan can never read as a count."""
    import importlib.util
    from tradingagents import cloud_sweep as cs
    sizes = {1: 597, 2: 613, 3: 549, 8: 788, 11: 851, 15: 779, 30: 434, 39: 541}
    a, b = rst.split_shards(sizes, 2)
    assert sorted(a + b) == sorted(sizes) and not set(a) & set(b)
    assert abs(sum(sizes[s] for s in a) - sum(sizes[s] for s in b)) <= max(sizes.values())
    spec = importlib.util.spec_from_file_location("research_plan", ROOT / ".github/scripts/research_plan.py")
    rp_ = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rp_)
    assert rp_.wanted("40") == list(range(40))
    assert rp_.wanted("[5]") == [5], "one shard sent as a list, never read as a count of 5"
    assert rp_.wanted("1,4,9") == [1, 4, 9]
    calls = []

    def gh(*args, **kw):
        calls.append(args)
        if args[:2] == ("api", "repos/jeremydevera/analyzer-x/actions/runs/37007971331/artifacts?per_page=100"):
            return "\n".join(f"replay-{s} {n * 2 ** 20}" for s, n in sizes.items()) + "\nreplay-0 618\n"
        if args[:2] == ("run", "list"):
            n = sum(1 for c in calls if c[:2] == ("workflow", "run") and args[3] in c)
            return json.dumps([{"databaseId": 100 + i} for i in range(n)])
        return ""
    monkeypatch.setattr(cs, "_gh", gh)
    monkeypatch.setattr(rst.time, "sleep", lambda s: None)
    got = rst.dispatch("research/p4/round9.json", "daily", 4, "37007971331", "jeremydevera/analyzer-x",
                       1790942400000, fleets=["jeremydvera/analyzer-x", "jeremydevera/analyzer-x"])
    assert [g["repo"] for g in got] == ["jeremydvera/analyzer-x", "jeremydevera/analyzer-x"]
    assert sorted(got[0]["shards"] + got[1]["shards"]) == sorted(sizes), "the empty shard 0 is left out"
    runs = [c for c in calls if c[:2] == ("workflow", "run")]
    assert len(runs) == 2 and all("source_repo=jeremydevera/analyzer-x" in c for c in runs)
    assert all(any(x.startswith("shards=[") for x in c) for c in runs)
    assert all(g["run"] is not None for g in got)
    # 8 shards dealt 4 a side, asked for 4 slices: 16 jobs an account would
    # leave 4 of its 20 machines idle — raised to 5 slices, the same on both
    assert {g["chunks"] for g in got} == {5} and all(g["jobs"] >= 20 for g in got)
    assert all("chunks=5" in c for c in runs)
