"""Auto Trade -> Forecast: every definition and every one of the 15 features
(operator, Oct 01, 2026: "go run this / Build ALL 15 Forecast features on
Auto Trade -> Forecast, and make sure there is no bug").

ONE TIMELINE: every trade, open position and forecast below is placed on the
same clock, NOW, the way a running site sees them. A test whose trades sat on
a different clock from its "now" could pass with a days-window bug in it
(CLAUDE.md, "a fill may only see price the order was exposed to").
"""
import json
import re
import time
from pathlib import Path

import pytest

from tradingagents import api, auto_trader as at, profiles, room_forecasts as rf, room_stats as rs

ROOT = Path(__file__).resolve().parents[1]
NOW = 1790900000.0               # Oct 02, 2026 — every timestamp below is relative to it
DAY = 86400.0
ROOM = "4FC03172"


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    """Main's and every room's files under tmp_path; caches cleared."""
    monkeypatch.setattr(at, "LEDGER_PATH", tmp_path / "auto_trade_ledger.jsonl")
    monkeypatch.setattr(at, "STATE_PATH", tmp_path / "auto_trade_state.json")
    monkeypatch.setattr(rs, "rules_of", lambda room: {"window_days": 30, "on_winrate": 70,
                                                      "off_winrate": 70, "min_trades": 50,
                                                      "tp_rule": ">", "max_sl": 2.0})
    monkeypatch.setattr(rs, "research", lambda: {"rooms": {}})
    rs._LEDGERS.clear()
    rs._STATES.clear()
    yield tmp_path
    rs._LEDGERS.clear()
    rs._STATES.clear()


def _ledger(room=ROOM):
    return Path(profiles.path(at.LEDGER_PATH, room))


def _state(room=ROOM):
    return Path(profiles.path(at.STATE_PATH, room))


def _trades(pnls, room=ROOM, start=NOW - 10 * DAY, step=600.0, dry=True, symbol="KKRSTOCK_USDT",
            side="LONG"):
    """An enter and an exit row per pnl, in time order, booked the way the
    paper exit books them: pnl = (move - cost) * $5 * 20."""
    rows = []
    for i, pnl in enumerate(pnls):
        t = start + i * step
        tid = f"T{room[:2]}{i:05d}"
        cost = 0.002                       # 0.2% charged at the exit
        move = pnl / 100.0 + cost          # so (move - cost) * 100 == pnl
        sign = -1 if side == "SHORT" else 1
        entry = 100.0
        exit_ = entry * (1 + sign * move)
        rows.append({"ts": t, "symbol": symbol, "action": "enter", "trade_id": tid,
                     "opened_at": t, "side": side, "margin": 5.0, "leverage": 20,
                     "dry_run": dry, "entry": entry})
        rows.append({"ts": t + 300, "symbol": symbol, "action": "exit", "trade_id": tid,
                     "opened_at": t, "entry_ts": t, "side": side, "entry": entry,
                     "exit": exit_, "pnl_est": round(pnl, 2), "dry_run": dry, "why": "TP"})
    return rows


def _write(rows, room=ROOM, mode="w", refusals=0):
    p = _ledger(room)
    with p.open(mode, encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
            for _ in range(refusals):
                fh.write(json.dumps({"ts": r["ts"], "action": "gate_blocked",
                                     "why": "cost too high for the target"}) + "\n")


def _open(positions, room=ROOM):
    st = {f"{p.get('symbol', 'VUG_USDT')}#paper#k{i}": {"position": p} for i, p in enumerate(positions)}
    _state(room).write_text(json.dumps(st), encoding="utf-8")


# ---------------------------------------------------------------- definitions
def test_break_even_is_average_loss_over_average_win_plus_loss():
    _write(_trades([1.00] * 20 + [-1.60] * 20))
    p = rs.room(ROOM, NOW)["practice"]
    assert p["breakeven"] == round(100 * 1.6 / 2.6, 1) == 61.5
    assert p["winrate"] == 50.0 and p["vs_breakeven"] == -11.5


def test_under_20_wins_or_losses_there_is_no_break_even():
    _write(_trades([1.00] * 19 + [-1.60] * 30))
    p = rs.room(ROOM, NOW)["practice"]
    assert p["breakeven"] is None and p["vs_breakeven"] is None
    assert "needs 20 wins and 20 losses, has 19 and 30" in p["breakeven_why"]


def test_a_win_is_more_than_zero_and_the_worst_run_is_the_biggest_losing_sum():
    _write(_trades([1.0, -1.0, -2.0, 0.0, 1.0, -0.5]))
    p = rs.room(ROOM, NOW)["practice"]
    assert (p["wins"], p["losses"]) == (2, 4), "$0.00 is not a win"
    assert (p["worst_run"], p["worst_run_trades"]) == (-3.0, 3)


def test_the_cost_is_the_price_move_less_what_was_booked():
    _write(_trades([0.70, -2.19], side="SHORT"))
    c = rs.room(ROOM, NOW)["costs"]
    assert c["matched"] == c["of"] == 2
    assert c["per_trade"] == pytest.approx(0.20, abs=0.006)        # 0.2% of $100
    assert c["without_costs"] == pytest.approx(0.70 - 2.19 + 0.40, abs=0.01)


def test_too_early_until_100_trades_and_7_days():
    _write(_trades([0.5] * 99, start=NOW - 8 * DAY))
    assert rs.room(ROOM, NOW)["practice"]["too_early_why"] == ["99 of 100 closed trades"]
    _write(_trades([0.5] * 120, start=NOW - 2 * DAY, step=60))
    p = rs.room(ROOM, NOW)["practice"]
    assert p["too_early"] and p["too_early_why"] == ["2.0 of 7 days"]
    _write(_trades([0.5] * 120, start=NOW - 8 * DAY, step=60))
    assert not rs.room(ROOM, NOW)["practice"]["too_early"]


def test_practice_and_real_money_are_counted_apart():
    _write(_trades([1.0, -1.0, 1.0]) + _trades([-5.0], dry=False, start=NOW - DAY))
    r = rs.room(ROOM, NOW)
    assert r["practice"]["closed"] == 3 and r["practice"]["profit"] == 1.0
    assert r["real"]["trades"] == 1 and r["real"]["profit"] == -5.0


# ----------------------------------------------------------------- features
def test_1_every_room_best_first_by_profit_a_trade(monkeypatch):
    _write(_trades([0.10] * 5), room="4FC03172")
    _write(_trades([0.90] * 5), room="CC94D9FB")
    _write(_trades([-0.50] * 5), room="B52662ED")          # turned off: always last
    got = [r["id"] for r in rs.rooms(NOW)]
    assert got[:2] == ["CC94D9FB", "4FC03172"]
    assert got[-1] == "B52662ED" or profiles.retired(got[-1])
    assert set(got) == set(profiles.ids())


def test_5_the_profit_line_has_every_day_to_today():
    _write(_trades([1.0, -0.5], start=NOW - 3 * DAY, step=60))
    d = rs.room(ROOM, NOW)["daily"]
    assert len(d) == 4 and d[-1]["day"] == time.strftime("%Y-%m-%d", time.localtime(NOW))
    assert d[0]["profit"] == 0.5 and [x["total"] for x in d] == [0.5, 0.5, 0.5, 0.5]


def test_8_9_3_the_alarms(monkeypatch):
    monkeypatch.setattr(rs, "research", lambda: {"rooms": {ROOM: {
        "profit": 4967.44, "closed": 15345, "wins": 10305, "losses": 5040, "winrate": 67.16,
        "worst_run": -30.07, "worst_run_trades": 23, "max_open": 2, "prior_profit": 1.0}}})
    _write(_trades([-1.6] * 25 + [1.0] * 10))
    _open([{"side": 1, "entry": 100, "sl": 98, "margin": 5, "dry": True}] * 3)
    kinds = {a["kind"]: a["text"] for a in rs.room(ROOM, NOW)["alarms"]}
    assert "-$40.00 over 25 trades" in kinds["losing_run"] and "-$30.07 over 23" in kinds["losing_run"]
    assert "3 open" in kinds["too_many_open"] and "most at once was 2" in kinds["too_many_open"]
    assert "+$4,967.44" in kinds["far_below"]


def test_10_worst_case_books_every_open_trade_at_its_stop():
    _write(_trades([1.0]))
    _open([{"side": 1, "entry": 100.0, "sl": 98.0, "margin": 5.0, "dry": True,
            "rt_cost": 0.002, "book_slippage": 0.0002},
           {"side": -1, "entry": 50.0, "sl": 51.0, "margin": 5.0, "dry": True,
            "rt_cost": 0.002, "book_slippage": 0.0002},
           {"side": 1, "entry": 10.0, "sl": 9.0, "margin": 5.0, "dry": False}])   # real: not here
    w = rs.room(ROOM, NOW)["worst_case"]
    assert w["open"] == 2
    assert w["up_to"] == pytest.approx((-0.02 - 0.0018) * 100 + (-0.02 - 0.0018) * 100, abs=0.01)


def test_12_stock_coins_split_by_new_york_market_hours():
    import datetime as dt
    from zoneinfo import ZoneInfo

    thu_10am = dt.datetime(2026, 9, 24, 10, 0, tzinfo=ZoneInfo("America/New_York")).timestamp()
    sat = thu_10am + 2 * DAY
    assert dt.datetime.fromtimestamp(thu_10am, ZoneInfo("America/New_York")).weekday() == 3
    rows = (_trades([1.0], start=thu_10am, symbol="ELSTOCK_USDT")
            + _trades([-1.0], start=sat, symbol="ELSTOCK_USDT")
            + _trades([5.0], start=thu_10am, symbol="BTC_USDT"))
    for i, r in enumerate(rows):
        r["trade_id"] = f"X{i // 2}"
    _write(rows)
    h = rs.room(ROOM, NOW)["hours"]
    assert h["stock_trades"] == 2 and h["other_trades"] == 1
    assert h["market"]["profit"] == 1.0 and h["off"]["profit"] == -1.0
    assert rs.market_hours(thu_10am) and not rs.market_hours(sat)
    assert not rs.market_hours(thu_10am + 6.5 * 3600)          # 4:30pm


def test_13_the_five_coins_losing_most():
    rows = []
    for i, (coin, pnl) in enumerate([("A", -1), ("B", -6), ("C", -3), ("D", -2), ("E", -5),
                                     ("F", -4), ("G", 2)]):
        t = _trades([pnl], symbol=f"{coin}_USDT", start=NOW - DAY + i * 900)
        for r in t:
            r["trade_id"] = f"C{i}"
        rows += t
    _write(rows)
    assert [x["coin"] for x in rs.room(ROOM, NOW)["losers"]] == ["B", "E", "F", "C", "D"]


def test_14_15_ready_badge_and_turn_off_note(monkeypatch):
    monkeypatch.setattr(rs, "research", lambda: {"rooms": {ROOM: {
        "profit": 100, "closed": 100, "wins": 70, "losses": 30, "winrate": 70.0,
        "worst_run": -20.0, "worst_run_trades": 10, "max_open": 50, "prior_profit": 1}}})
    _write(_trades(([1.0] * 3 + [-1.0]) * 60, start=NOW - 15 * DAY, step=1800))
    r = rs.room(ROOM, NOW)
    assert r["ready"]["ok"], r["ready"]["missing"]
    assert not r["turn_off"]["ok"]
    _write(_trades(([1.0] + [-1.0] * 2) * 70, start=NOW - 15 * DAY, step=1800))
    r = rs.room(ROOM, NOW)
    assert not r["ready"]["ok"] and r["turn_off"]["ok"]
    assert "after 210 closed trades" in r["turn_off"]["why"]


# ---------------------------------------------------------------- forecasts
def test_6_the_pick_rule():
    def fake(i, closed, days, wr, be, per, retired=False):
        return {"id": i, "name": f"#{i}", "retired": retired, "rules": "", "research": None,
                "practice": {"closed": closed, "wins": 0, "losses": 0, "winrate": wr,
                             "breakeven": be, "breakeven_why": "", "vs_breakeven":
                             (wr - be) if be is not None else None, "profit": per * closed,
                             "per_trade": per, "worst_run": 0, "worst_run_trades": 0,
                             "open": 0, "days": days, "first_at": 1,
                             "too_early": closed < 100 or days < 7, "too_early_why": []}}
    v = rs.verdict([fake("A", 300, 9, 65, 60, 0.10), fake("B", 300, 9, 70, 60, 0.20),
                    fake("C", 50, 1, 90, None, 0.90), fake("D", 900, 30, 90, 50, 0.95, True)])
    assert v["verdict"] == "pick" and v["pick"] == "B", "C is too early, D is turned off"
    v = rs.verdict([fake("A", 30, 1, 65, None, 0.10)])
    assert v["verdict"] == "too early" and not v["pick"]
    v = rs.verdict([fake("A", 300, 9, 40, 60, -0.10)])
    assert v["verdict"] == "none proven" and "40" in v["pick_why"]


def test_6_a_forecast_built_here_is_one_the_tab_can_save(tmp_path):
    _write(_trades([1.0, -1.0]))
    entry = rs.forecast_entry(rs.rooms(NOW), NOW, "button")
    assert rf.problems(entry) == []
    rf.add(entry, path=tmp_path / "f.jsonl")
    assert rf.saved(tmp_path / "f.jsonl")[0][0]["source"] == "button"


def test_4_each_pick_is_checked_against_what_happened_since():
    _write(_trades([1.0] * 120, start=NOW - 9 * DAY, step=1800))
    early = {"at": NOW - 2 * DAY, "pick": ROOM, "verdict": "pick"}
    old = {"at": NOW - 9 * DAY - 60, "pick": ROOM, "verdict": "pick"}
    none = {"at": NOW - DAY, "pick": None, "verdict": "too early"}
    out, score = rs.check([early, old, none], NOW)
    assert out[0]["since"]["result"] == "too early"
    assert out[1]["since"]["result"] == "right" and out[1]["since"]["trades"] == 120
    assert out[2]["since"] is None
    assert score == {"right": 1, "judged": 1, "saved": 3, "with_pick": 2}


def test_an_unknown_room_is_never_created_to_answer(sandbox):
    assert rs.since("NOTAROOM", 0, NOW) is None
    with pytest.raises(ValueError):
        rs.room("NOTAROOM", NOW)
    assert not any(p.name == "NOTAROOM" for p in sandbox.rglob("*"))
    bad = rs.forecast_entry([], NOW, "button") | {"rooms": [{"id": "NOTAROOM", "real": dict.fromkeys(rf.REAL_KEYS, 0)}]}
    assert any("no such room" in m for m in rf.problems(bad))


def test_a_saved_number_must_be_a_number():
    _write(_trades([1.0]))
    entry = rs.forecast_entry(rs.rooms(NOW), NOW, "prompt")
    entry["rooms"][0]["real"]["days"] = "two"
    assert any("must be number" in m for m in rf.problems(entry))


# --------------------------------------------------------- the daily forecast
def _update(monkeypatch, when, runs, collected):
    monkeypatch.setattr(rf, "_update", lambda: {"when": when, "runs": runs,
                                                "collected": collected})


def test_7_once_a_day_after_the_update_is_collected(tmp_path, monkeypatch):
    f = tmp_path / "f.jsonl"
    monkeypatch.setattr(rf, "AUTO", {"why": "", "error": "", "failed_at": 0.0, "made_at": 0.0})
    _write(_trades([1.0]))
    _update(monkeypatch, NOW - 3600, [1, 2], [1])
    got = rf.daily_tick(NOW, path=f)
    assert not got["made"] and "1 of 2 runs in" in got["why"]
    _update(monkeypatch, NOW - 3600, [1, 2], [1, 2])
    assert rf.daily_tick(NOW, path=f)["made"]
    assert not rf.daily_tick(NOW + 60, path=f)["made"], "never twice in one day"
    assert "made at" in rf.daily_tick(NOW + 120, path=f)["why"]
    saved, _ = rf.saved(f)
    assert len(saved) == 1 and saved[0]["source"] == "auto"


def test_7_a_failure_is_named_and_tried_again_later(tmp_path, monkeypatch):
    f = tmp_path / "f.jsonl"
    monkeypatch.setattr(rf, "AUTO", {"why": "", "error": "", "failed_at": 0.0, "made_at": 0.0})
    _update(monkeypatch, NOW - 3600, [1], [1])

    def boom(source, now=None, path=None):
        raise RuntimeError("disk said no")

    monkeypatch.setattr(rf, "make", boom)
    got = rf.daily_tick(NOW, path=f)
    assert not got["made"] and "FAILED" in got["why"] and "disk said no" in got["why"]
    assert rf.daily_tick(NOW + 60, path=f)["why"] == got["why"], "not retried every 30 s"
    monkeypatch.setattr(rf, "make", lambda source, now=None, path=None: rf.add(
        rs.forecast_entry(rs.rooms(now), now, source), path=path))
    _write(_trades([1.0]))
    assert rf.daily_tick(NOW + rf.AUTO_RETRY_S + 1, path=f)["made"]


def test_7_never_under_a_test_run_against_the_real_file():
    assert rf.daily_tick()["why"] == "never under a test run"


# ----------------------------------------------------- reading the big records
def test_a_record_rewritten_in_place_to_a_longer_size_is_read_again():
    """Same file, same id, bigger: carrying on from the old offset would read
    the middle of the new content."""
    _write(_trades([0.5] * 10, start=NOW - 8 * DAY))
    assert len(rs.ledger(_ledger())["exits"]) == 10
    _write(_trades([-0.5] * 30, start=NOW - 2 * DAY))      # truncate + longer
    got = rs.ledger(_ledger())["exits"]
    assert len(got) == 30 and all(e["pnl"] == -0.5 for e in got)


def test_the_record_is_read_incrementally_and_a_half_line_waits(sandbox):
    _write(_trades([1.0] * 3), refusals=50)
    assert len(rs.ledger(_ledger())["exits"]) == 3
    with _ledger().open("a", encoding="utf-8") as fh:
        line = json.dumps(_trades([2.0], start=NOW - DAY)[1])
        fh.write(line[:20])                         # a write caught half way
    assert len(rs.ledger(_ledger())["exits"]) == 3
    with _ledger().open("a", encoding="utf-8") as fh:
        fh.write(line[20:] + "\n")
    assert len(rs.ledger(_ledger())["exits"]) == 4
    _write(_trades([1.0]))                          # replaced by a shorter file
    assert len(rs.ledger(_ledger())["exits"]) == 1


# ------------------------------------------------------------ research file
def test_the_research_file_matches_the_table_in_trading_rooms_md():
    doc = (ROOT / "docs/TRADING-ROOMS.md").read_text(encoding="utf-8")
    data = json.loads(rs.RESEARCH_FILE.read_text(encoding="utf-8"))
    rows = {}
    for m in re.finditer(r"^\| (#\w+|Main's rules) \| \*\*\+\$([\d,.]+)\*\* \| ([\d,]+) / ([\d,]+) "
                         r"\| ([\d.]+)% \| ([\d,]+) \| (\d+) \| −\$([\d.]+) over (\d+) trades", doc, re.M):
        rid = "main" if m.group(1) == "Main's rules" else m.group(1)[1:]
        rows[rid] = m.groups()[1:]
    assert set(rows) == set(data["rooms"]) == {"main", "55D32617", "4FC03172", "B2404C0B",
                                               "6B08FF64", "CC94D9FB"}
    num = lambda s: float(s.replace(",", ""))                       # noqa: E731
    for rid, (profit, w, l, wr, n, mx, run, run_n) in rows.items():
        r = data["rooms"][rid]
        assert abs(r["profit"] - num(profit)) <= 0.05, rid          # the doc rounds by a cent or two
        assert (r["wins"], r["losses"], r["closed"], r["max_open"], r["worst_run_trades"]) == (
            int(num(w)), int(num(l)), int(num(n)), int(mx), int(run_n)), rid
        assert abs(r["winrate"] - num(wr)) <= 0.05 and r["worst_run"] == -num(run), rid
    assert data["source"] == "https://claude.ai/artifact/UUNAie322TPyjJU8MaZtQo"


# -------------------------------------------------------------- the API + page
def test_the_live_route_answers_every_room_with_every_feature():
    _write(_trades([1.0, -1.0]))
    got = api.forecasts_live_route()
    assert {r["id"] for r in got["rooms"]} == set(profiles.ids())
    one = next(r for r in got["rooms"] if r["id"] == ROOM)
    for key in ("practice", "real", "research", "worst_case", "costs", "hours", "losers",
                "daily", "alarms", "ready", "turn_off"):
        assert key in one, key
    assert got["verdict"]["verdict"] in rf.VERDICTS
    json.dumps(got)


def test_the_button_refuses_a_double_click(monkeypatch, tmp_path):
    f = tmp_path / "f.jsonl"
    monkeypatch.setattr(rf, "FILE", f)
    _write(_trades([1.0]))
    assert api.forecasts_new_route()["saved"]["source"] == "button"
    with pytest.raises(api.HTTPException) as e:
        api.forecasts_new_route()
    assert e.value.status_code == 409 and "wait a minute" in e.value.detail


def test_the_saved_route_checks_every_pick_and_scores_them_all(monkeypatch, tmp_path):
    f = tmp_path / "f.jsonl"
    monkeypatch.setattr(rf, "FILE", f)
    _write(_trades([1.0]))
    rf.add(rs.forecast_entry(rs.rooms(NOW), NOW - 60, "prompt"), path=f)
    got = api.forecasts_route(page=1)
    assert got["total"] == 1 and "since" in got["forecasts"][0]
    assert got["score"]["saved"] == 1 and "auto" in got and len(got["prompts"]) == 2


def test_the_page_prints_every_feature_and_works_nothing_out():
    src = (ROOT / "webapp/src/components/forecast/RoomForecasts.tsx").read_text(encoding="utf-8")
    for words in ("make a new forecast now", "ready for real money", "should be turned off",
                  "worst case today", "without costs", "market hours", "The coins losing the most",
                  "picks right", "to break even", "September research", "ProfitLine",
                  "api.forecastsLive()", "api.forecastNew()", "api.forecasts(page)"):
        assert words in src, words
    # dates through fmtWhen only, never a hand-built one
    assert "toLocale" not in src.replace("toLocaleString()", "")
    assert "new Date(" not in src
