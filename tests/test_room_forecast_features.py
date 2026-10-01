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
    monkeypatch.setitem(api._FORECAST_LIVE, "value", None)    # the background copy too
    monkeypatch.setitem(api._FORECAST_LIVE, "error", "")
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
    assert "-40.00 over 25 trades" in kinds["losing_run"] and "-30.07 over 23" in kinds["losing_run"]
    assert "3 open" in kinds["too_many_open"] and "most at once was 2" in kinds["too_many_open"]
    # money and win rates spelled the way the card beside them prints them
    assert "+4967.44 in the research" in kinds["far_below"] and "67.2% wins in September" in kinds["far_below"]
    assert "$" not in "".join(kinds.values())


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
    (ny,) = h["markets"]
    assert ny["market"] == "New York" and ny["hours"] == "9:30am–4pm"
    assert ny["open"]["profit"] == 1.0 and ny["closed"]["profit"] == -1.0
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


def test_the_live_numbers_are_served_from_a_background_copy(monkeypatch):
    """Measured Oct 01, 2026 3:10pm: worked out inside the request, the
    numbers waited 1.9 s for Python's lock behind the Auto Trade polls."""
    _write(_trades([1.0]))
    first = api.forecasts_live_route()                  # nothing yet: made now
    assert api.forecasts_live_route() is first          # fresh: the same copy, at once
    made = []
    monkeypatch.setattr(api, "_forecast_live_refresh", lambda: made.append(1) or first)
    monkeypatch.setitem(first, "at", first["at"] - 10 * api.FORECAST_LIVE_FRESH_S)
    assert api.forecasts_live_route() is first          # stale: still served at once...
    time.sleep(0.2)
    assert made, "...and a new copy is started behind it"


def test_a_failed_refresh_is_named_and_the_last_copy_still_served(monkeypatch):
    _write(_trades([1.0]))
    first = api.forecasts_live_route()

    def boom():
        raise RuntimeError("disk said no")

    monkeypatch.setattr(api, "_forecast_live_payload", boom)
    monkeypatch.setitem(api._FORECAST_LIVE, "error", "")
    assert api._forecast_live_refresh() is first
    got = api.forecasts_live_route()
    assert "disk said no" in got["refresh_error"] and got["rooms"] == first["rooms"]
    monkeypatch.setitem(api._FORECAST_LIVE, "value", None)
    with pytest.raises(RuntimeError):            # nothing to serve: the failure itself
        api.forecasts_live_route()


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
    # every "## N." prompt in docs/FORECAST-PROMPTS.md, however many there are
    # (a third arrived Oct 01, 2026 6:00pm; a hardcoded 2 went red)
    assert got["score"]["saved"] == 1 and "auto" in got
    assert [p["title"][:2] for p in got["prompts"]] == [
        f"{i}." for i in range(1, len(got["prompts"]) + 1)] and len(got["prompts"]) >= 2


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


def test_a_failing_refresh_never_skips_the_daily_forecast():
    """Both run in the supervisor's 30-second tick; each has its own guard."""
    import inspect
    src = inspect.getsource(api)
    i = src.index("                    _forecast_live_refresh()")
    j = src.index("_rf.daily_tick()", i)
    assert "except Exception" in src[i:j] and "try:" in src[i:j]


# ------------------------------------------- found on the running screen, Oct 01
def test_server_sentences_spell_numbers_the_way_the_page_does(tmp_path):
    """An alarm said "+$3,597.61" one line under the card's "+3597.61", and
    "53.3% wins ... against 70.22% wins" in one sentence. The server's words
    now go through room_stats._money/_pct, held here to the page's own
    fmtMoney (api.ts) and pct (RoomForecasts.tsx) — the REAL code, lifted
    and run, over the values where Python and JavaScript round differently."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")

    def lift(path, start):
        body = (ROOT / path).read_text(encoding="utf-8")
        i = body.index(start)
        return (body[i:body.index(";\n", i) + 1].replace("export const", "const")
                .replace(": number | undefined | null", "").replace(": number | null | undefined", ""))

    money = [0.0, -0.0, 0.125, -0.125, 0.375, 1.005, 2.675, 3597.61, -9.53, 0.004, -0.004,
             12345.678, -151.92, 4967.44, None]
    pcts = [70.22, 70.25, 53.3, 0.05, 99.95, 100.0, 67.16, 41.95, None]
    js = tmp_path / "p.mjs"
    js.write_text(lift("webapp/src/lib/api.ts", "export const fmtMoney") + "\n"
                  + lift("webapp/src/components/forecast/RoomForecasts.tsx", "const pct") + "\n"
                  + "console.log(JSON.stringify([" + json.dumps(money) + ".map(fmtMoney), "
                  + json.dumps(pcts) + ".map(pct)]));\n", encoding="utf-8")
    # node writes UTF-8 whatever the console's code page ("—" came back as
    # three cp1252 letters on this PC)
    out = subprocess.run([node, str(js)], capture_output=True, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    got_money, got_pct = json.loads(out.stdout)
    assert got_money == [rs._money(v) for v in money]
    assert got_pct == [rs._pct(v) for v in pcts]


def test_a_nan_in_a_trade_record_is_counted_never_carried():
    """NEVER HAPPENED YET (0 of 147,325 ledger lines on Oct 01, 2026), but
    Python writes NaN for a float that went wrong, and one NaN in the answer
    fails it on every request (allow_nan=False)."""
    rows = _trades([1.0, -1.0, 2.0])
    rows[3]["pnl_est"] = float("nan")              # the second trade's exit
    _write(rows)
    r = rs.room(ROOM, NOW)
    assert r["unreadable_lines"] == 1 and r["practice"]["closed"] == 2
    _open([{"side": 1, "entry": float("nan"), "sl": 98, "margin": 5, "dry": True}])
    json.dumps(rs.room(ROOM, NOW), allow_nan=False)


def test_a_forecast_holding_nan_is_refused_and_a_saved_one_is_counted(tmp_path):
    """A prompt-made forecast written in Python gets NaN from any 0/0 — and a
    saved one would have failed the saved list for ever."""
    e = rs.forecast_entry(rs.rooms(NOW), NOW, "prompt")
    e["rooms"][0]["real"]["winrate"] = float("nan")
    e["rooms"][0]["research"] = {"profit": float("inf")}
    bad = rf.problems(e)
    assert any("rooms[0].real.winrate" in b and "rooms[0].research.profit" in b for b in bad), bad
    with pytest.raises(ValueError):
        rf.add(e, path=tmp_path / "f.jsonl")
    nan_at = dict(rs.forecast_entry(rs.rooms(NOW), NOW, "prompt"), at=float("nan"))
    assert "'at' must be unix seconds" in rf.problems(nan_at)
    f = tmp_path / "f.jsonl"
    f.write_text(json.dumps(e) + "\n", encoding="utf-8")      # written by hand, NaN and all
    rf.add(rs.forecast_entry(rs.rooms(NOW), NOW, "button"), path=f)
    got = rf.read(path=f)
    assert got["total"] == 1 and got["unreadable"] == 1
    json.dumps(got, allow_nan=False)


def test_a_copy_that_cannot_be_sent_is_never_kept(monkeypatch):
    _write(_trades([1.0]))
    first = api.forecasts_live_route()
    monkeypatch.setattr(api, "_forecast_live_payload", lambda: {"rooms": [], "at": float("nan")})
    monkeypatch.setitem(api._FORECAST_LIVE, "error", "")
    assert api._forecast_live_refresh() is first, "the last good copy stays"
    assert "ValueError" in api._FORECAST_LIVE["error"]


def test_worst_case_counts_only_the_trades_it_priced():
    """The label says "if all N open trades hit their stop"; a trade with no
    stop to price is counted apart, never folded into N."""
    _write(_trades([1.0]))
    _open([{"side": 1, "entry": 100.0, "sl": 98.0, "margin": 5.0, "dry": True},
           {"side": 1, "entry": 100.0, "sl": 0, "margin": 5.0, "dry": True}])
    w = rs.room(ROOM, NOW)["worst_case"]
    assert (w["open"], w["unpriced"]) == (1, 1)
    src = (ROOT / "webapp/src/components/forecast/RoomForecasts.tsx").read_text(encoding="utf-8")
    assert "with no stop to price are not in it" in src


def test_on_a_phone_the_tables_fit_and_a_forecast_opens_from_its_first_column():
    """At 390px: the coins table's forced 360px hid "profit", the hours
    table's 420px hid "profit" and "a trade", and "rooms then" sat in the
    last column of a 720px table, opening its rooms inside the "why" cell
    off the left of the screen."""
    src = (ROOT / "webapp/src/components/forecast/RoomForecasts.tsx").read_text(encoding="utf-8")
    card = src[src.index("function RoomCard"):src.index("function SinceCell")]
    assert "min-w-" not in card
    hist = src[src.index("function History"):src.index("export default")]
    first_cell = hist[hist.index("<Fragment"):hist.index("</td>", hist.index("<Fragment"))]
    assert "rooms then" in first_cell
    assert "colSpan={4}" in hist and "<ForecastDetail f={f} />" in hist
    detail = src[src.index("function ForecastDetail"):src.index("function History")]
    assert "overflow-x-auto" not in detail          # one sideways scroll, not two
    assert "{pct(res.winrate)} wins" in src


def test_each_stock_coin_is_timed_by_its_own_market():
    """Oct 01, 2026: every stock coin was timed by New York, so #4FC03172's
    MITSUBISHISTOCK trade at Sep 30, 2026 8:30pm New York — 9:30am in Tokyo,
    an hour after its market opened — was booked "nights and weekends", and
    KIMISTOCK, a company on no market at all, landed in either row. ONE
    moment, five coins, five different answers."""
    import datetime as dt
    from zoneinfo import ZoneInfo

    wed_830pm = dt.datetime(2026, 9, 30, 20, 30, tzinfo=ZoneInfo("America/New_York")).timestamp()
    tokyo = dt.datetime.fromtimestamp(wed_830pm, ZoneInfo("Asia/Tokyo"))
    assert (tokyo.weekday(), tokyo.hour, tokyo.minute) == (3, 9, 30)      # Thursday 9:30am
    sat_tokyo_10am = dt.datetime(2026, 10, 3, 10, 0, tzinfo=ZoneInfo("Asia/Tokyo")).timestamp()
    rows = (_trades([1.0], start=wed_830pm, symbol="MITSUBISHISTOCK_USDT")       # Tokyo, open
            + _trades([2.0], start=wed_830pm, symbol="FASTRETAILSTOCK_USDT")     # Tokyo, open
            + _trades([-1.0], start=wed_830pm, symbol="GPNSTOCK_USDT")           # New York, closed
            + _trades([-2.0], start=wed_830pm, symbol="FASTSTOCK_USDT")          # Fastenal: New York
            + _trades([0.5], start=wed_830pm, symbol="KIMISTOCK_USDT")           # no market yet
            + _trades([-0.5], start=sat_tokyo_10am, symbol="TOYOTASTOCK_USDT"))  # Tokyo, Saturday
    for i, r in enumerate(rows):
        r["trade_id"] = f"M{i // 2}"
    _write(rows)
    h = rs.room(ROOM, NOW)["hours"]
    by = {m["market"]: m for m in h["markets"]}
    assert list(by) == ["New York", "Tokyo"]
    assert (by["Tokyo"]["open"]["trades"], by["Tokyo"]["open"]["profit"]) == (2, 3.0)
    assert (by["Tokyo"]["closed"]["trades"], by["Tokyo"]["closed"]["profit"]) == (1, -0.5)
    assert (by["New York"]["open"]["trades"], by["New York"]["closed"]["trades"]) == (0, 2)
    assert h["unlisted"]["trades"] == 1 and h["unlisted_coins"] == ["KIMISTOCK"]
    assert by["Tokyo"]["hours"] == "9am–3:30pm"
    # every row the page prints adds back up to the stock trades it counted
    assert sum(m["open"]["trades"] + m["closed"]["trades"] for m in h["markets"]) \
        + h["unlisted"]["trades"] == h["stock_trades"] == 6


def test_the_coins_the_rooms_traded_are_on_the_right_market():
    """The list, checked against what the rooms actually traded by Oct 01,
    2026. MEXC's own "japanstock" tag is not used: it marks FASTSTOCK (50.21,
    Fastenal) as Japanese and misses RENESAS, NINTENDO and the rest."""
    tokyo = ["MITSUBISHI", "RENESAS", "AJINOMOTO", "TOYOTA", "PANASONIC", "MUFG", "RECRUIT",
             "FANUC", "SHINETSU", "NINTENDO", "NEC", "FASTRETAIL", "DISCO"]
    assert all(rs.home_market(f"{c}STOCK_USDT") == "Tokyo" for c in tokyo)
    assert rs.home_market("FASTSTOCK_USDT") == "New York"
    assert rs.home_market("KIMISTOCK_USDT") is None and rs.home_market("YMTCSTOCK_USDT") is None
    assert rs.home_market("GPNSTOCK_USDT") == "New York"
    assert rs.home_market("TSMCSTOCK_USDT") == "Taipei" and rs.home_market("TSMSTOCK_USDT") == "New York"
    assert not set(rs.LISTED_IN) & rs.NOT_LISTED
    src = (ROOT / "webapp/src/components/forecast/RoomForecasts.tsx").read_text(encoding="utf-8")
    assert "market hours = 9:30am–4pm New York" not in src, "no coin is timed by one clock"
    assert "not on any market yet" in src and "(r.hours.markets ?? []).map" in src
    assert "the project has no rule of its own" not in rs.STOCK_RULE
