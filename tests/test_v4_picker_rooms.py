"""Forecast v4 -> Rooms (Nov 12, 2026): every tested picker rule as a room, for the days asked.

Operator: "in v4 just remove the streak section, then create a section 'room' where you will list
all the room that is earning this month take note i want to see necessary filter on this, like
dates, or winrate etc. if i adjust the date filter i should, the winrate should adjust asw well /
if i click the room, i want to see what switch-on has been deployed and undeployed per day".

The rooms are read from one lab run over the tiny store of tests/test_v4_picker_lab.py (GOOD 1h wins
$1, BAD 1h loses $1, FLIP 4h wins $1.50 until Sep 20, 2026 and loses after, LATE 30m wins $2 from
Sep 25), on one timeline."""
import json
import pickle
import re
from pathlib import Path

import numpy as np
import pytest

from tests.test_v4_picker_lab import _lines, _store, ms
from tradingagents import v4_picker_lab as lab, v4_picker_rooms as vr

REPO = Path(__file__).resolve().parents[1]
DAY = 86_400


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    tmp = tmp_path_factory.mktemp("rooms")
    from tradingagents import profiles

    mp.setattr(profiles, "PICKER_PATH", tmp / "picker.json", raising=False)
    db = _store(tmp, mp, _lines())
    doc = lab.run(db, log=lambda *_: None)
    vr._CACHE.update(key=None, doc=None, tr=None)
    with open(tmp / "v4" / "picker-lab" / "trades.pkl", "rb") as fh:
        trades = pickle.load(fh)["trades"]
    yield {"doc": doc, "tmp": tmp, "trades": trades}
    mp.undo()
    vr._CACHE.update(key=None, doc=None, tr=None)


def _room(doc, key):
    return next(r for r in doc["rules"] if r["key"] == key)


def _own(t, lo, hi):
    """A room's figures over the trades it opened in [lo, hi), added up here, not by the module."""
    m = (t["en"] >= lo) & (t["en"] < hi)
    p = t["p4"][m]
    return int(p.size), int((p > 0).sum()), round(float(p.sum()) / 1e4, 4)


def _all(q):
    """Every page of an ask, in order."""
    first = vr.rooms_page({**q, "page": 1})
    rows = list(first["rows"])
    for n in range(2, first["pages"] + 1):
        rows += vr.rooms_page({**q, "page": n})["rows"]
    return first, rows


# ------------------------------------------------------------------ the window
def test_with_no_days_asked_the_window_is_this_month(run):
    p = vr.rooms_page({})
    w = p["window"]
    assert w["asked"] == "this month"
    assert w["from_s"] == ms(2026, 11, 1) // 1000, "Nov 01, 12:00am UTC: the month of the newest day measured"
    assert w["to_s"] == ms(2026, 11, 6) // 1000 and w["days"] == 5, "to the end of the newest day (Nov 05)"
    assert p["of"] == 21 and p["measured"]["tested"] == 20


def test_the_last_n_days_and_two_dates_are_the_pickers_own_days(run):
    w = vr.rooms_page({"days": 10})["window"]
    assert (w["to_s"] - w["from_s"]) // DAY == 10 == w["days"] and w["asked"] == "the last 10 days"
    w = vr.rooms_page({"date_from": "2026-10-01", "date_to": "2026-10-31"})["window"]
    assert (w["from_s"], w["to_s"], w["days"]) == (ms(2026, 10, 1) // 1000, ms(2026, 11, 1) // 1000, 31)
    w = vr.rooms_page({"date_from": "2026-07-01", "date_to": "2026-12-31"})["window"]
    assert w["cut"] and w["from_s"] == run["doc"]["first_day_s"] and w["days"] == run["doc"]["days"], \
        "cut to the days measured, and said"
    assert vr.rooms_page({"days": 7, "date_from": "2026-09-01"})["window"]["asked"] == "the last 7 days"


def test_a_day_that_is_not_a_day_is_refused_by_name(run):
    for bad in ({"date_from": "11/01/2026"}, {"date_to": "yesterday"},
                {"date_from": "2026-10-10", "date_to": "2026-10-01"}):
        with pytest.raises(vr.BadAsk):
            vr.rooms_page(bad)
    api = (REPO / "tradingagents/api.py").read_text(encoding="utf-8")
    for route in ('"/api/forecast-v4/rooms"', '"/api/forecast-v4/rooms/{room_id}"'):
        assert f"@app.get({route})" in api, route
    assert api.count("except vr.BadAsk as exc:") == 2 and "raise HTTPException(400, str(exc))" in api


# ------------------------------------------------------------------ the list is the window's own
def test_changing_the_days_changes_the_win_rate_because_every_figure_is_the_windows_own(run):
    """FLIP's switch-ons win until Sep 20 and lose after: a room that followed them wins in one
    window and loses in the next. Each window's figures are that window's trades, added up here."""
    doc, trades = run["doc"], run["trades"]
    seen = 0
    for a, b in (("2026-09-01", "2026-09-19"), ("2026-09-20", "2026-10-15"), ("2026-10-16", "2026-11-05")):
        lo, hi = ms(*map(int, a.split("-"))) // 1000, ms(*map(int, b.split("-"))) // 1000 + DAY
        _first, rows = _all({"date_from": a, "date_to": b})
        assert len(rows) == 21
        for r in rows:
            n, wins, profit = _own(trades[r["id"]], lo, hi)
            assert (r["trades"], r["wins"], r["losses"]) == (n, wins, n - wins), (r["id"], a)
            if n:
                assert r["profit"] == pytest.approx(profit) and r["win_rate"] == pytest.approx(100 * wins / n, abs=0.01)
            else:
                assert r["profit"] is None and r["win_rate"] is None
    money = _room(doc, "money30")["id"]
    rates = {vr.rooms_page({"date_from": a, "date_to": b, "q": money})["rows"][0]["win_rate"]
             for a, b in (("2026-09-01", "2026-09-19"), ("2026-09-20", "2026-10-15"))}
    seen += len(rates)
    assert len(rates) == 2, "the same room, two windows, two win rates"
    assert seen


def test_every_floor_is_applied_here_to_the_windows_figures_and_named(run):
    q = {"date_from": "2026-09-01", "date_to": "2026-11-05"}
    base, everything = _all(q)
    assert base["total"] == base["of"] == len(everything) == 21 and base["filters"] == []
    first, rows = _all({**q, "earning": True})
    assert rows and all(r["trades"] and r["profit"] > 0 for r in rows)
    assert first["total"] == sum(1 for r in everything if r["trades"] and r["profit"] > 0) == first["earning"]
    assert first["filters"] == ["made money in these days"]
    first, rows = _all({**q, "min_winrate": 70})
    assert all(r["win_rate"] >= 70 for r in rows) and first["total"] == sum(
        1 for r in everything if r["win_rate"] is not None and r["win_rate"] >= 70)
    assert "won 70% or more" in first["filters"]
    first, rows = _all({**q, "min_trades": 300, "min_profit": 100})
    assert all(r["trades"] >= 300 and r["profit"] >= 100 for r in rows)
    assert first["filters"] == ["300 or more trades", "profit of +100.00 or more"]


def test_ten_a_page_sorted_here_and_a_room_with_no_trade_sorts_last(run):
    q = {"date_from": "2026-09-01", "date_to": "2026-11-05"}
    first, rows = _all(q)
    assert first["per_page"] == 10 and first["pages"] == 3 and len(first["rows"]) == 10
    traded = [r["profit"] for r in rows if r["trades"]]
    assert traded == sorted(traded, reverse=True), "most money first, across the pages"
    assert all(r["trades"] for r in rows[:len(traded)]) and not any(r["trades"] for r in rows[len(traded):])
    low = _all({**q, "desc": False})[1]
    lowest = [r["profit"] for r in low if r["trades"]]
    assert lowest == sorted(lowest) and not any(r["trades"] for r in low[len(lowest):]), "blank last both ways"
    by_rate = [r["win_rate"] for r in _all({**q, "sort": "win_rate"})[1] if r["trades"]]
    assert by_rate == sorted(by_rate, reverse=True)


def test_find_by_id_overrides_the_floors_and_keeps_the_days(run):
    rid = _room(run["doc"], "money30")["id"]
    p = vr.rooms_page({"q": f"#{rid.lower()}", "min_winrate": 100, "min_profit": 10 ** 9, "earning": True,
                       "date_from": "2026-09-20", "date_to": "2026-10-15"})
    assert p["found_by_id"] and [r["id"] for r in p["rows"]] == [rid] and p["filters"] == []
    assert p["rows"][0]["trades"] == _own(run["trades"][rid], ms(2026, 9, 20) // 1000, ms(2026, 10, 16) // 1000)[0]
    none = vr.rooms_page({"q": "ZZZZZZZZ"})
    assert none["total"] == 0 and "no room has the id #ZZZZZZZZ" in none["why"] and "21 rooms" in none["why"]


def test_the_base_margin_scales_every_dollar_and_no_count(run):
    q = {"date_from": "2026-09-01", "date_to": "2026-11-05", "sort": "id"}
    one, two = _all({**q, "base_margin": 5})[1], _all({**q, "base_margin": 10})[1]
    for a, b in zip(one, two):
        assert (a["id"], a["trades"], a["wins"], a["win_rate"], a["break_even"]) == \
            (b["id"], b["trades"], b["wins"], b["win_rate"], b["break_even"])
        for money in ("profit", "per_trade", "avg_win", "avg_loss", "worst_run"):
            if a[money] is not None:
                assert b[money] == pytest.approx(2 * a[money], abs=1e-3), money
    # a profit floor is in the dollars on the screen
    floor = max(r["profit"] for r in one if r["trades"]) + 1
    assert vr.rooms_page({**q, "min_profit": floor})["total"] == 0
    assert vr.rooms_page({**q, "min_profit": floor, "base_margin": 10})["total"] >= 1


def test_an_empty_list_names_what_was_examined(run):
    p = vr.rooms_page({"date_from": "2026-09-01", "date_to": "2026-11-05", "min_winrate": 101})
    assert p["total"] == 0 and p["rows"] == []
    assert "none of the 21 rooms passes won 101% or more" in p["why"]
    assert f"{p['traded']} of them traded in these 66 days and {p['earning']} made money in them" in p["why"]
    out = vr.rooms_page({"date_from": "2027-01-01", "date_to": "2027-01-31"})
    assert out["total"] == 21 and out["window"]["outside"] and all(not r["trades"] for r in out["rows"])


def test_each_row_carries_its_stop_and_target_sizes_and_what_runs_now(run):
    _first, rows = _all({"date_from": "2026-09-01", "date_to": "2026-11-05"})
    for r in rows:
        if not r["trades"]:
            assert r["sl_max"] is None and r["tp_max"] is None
            continue
        assert 1.0 <= r["sl_min"] <= r["sl_max"] <= 3.0, "the fixture's stops: 1%, 1.5%, 2%, 3%"
        assert r["no_target"] <= r["trades"]
        assert r["room_days"] == 3 * 66 and 0 <= r["empty_room_days"] <= r["room_days"]
        assert len(r["running"]) <= 3


# ------------------------------------------------------------------ one room, day by day
def test_a_rooms_log_is_what_it_deployed_and_undeployed_each_day(run):
    doc = run["doc"]
    r = _room(doc, "money30")
    every = {"date_from": "2026-09-01", "date_to": "2026-11-05", "every": True}
    first = vr.room_log(r["id"], {**every, "page": 1})
    rows = list(first["rows"])
    for n in range(2, first["pages"] + 1):
        rows += vr.room_log(r["id"], {**every, "page": n})["rows"]
    assert first["found"] and first["per_page"] == 10 and len(rows) == 66 == first["total"]
    assert [x["day_s"] for x in rows] == sorted((x["day_s"] for x in rows), reverse=True), "newest day first"
    rows = rows[::-1]
    follow = r["follow"]
    assert rows[0]["day_s"] == doc["first_day_s"]
    assert [d["id"] for d in rows[0]["deployed"]] == [x for x in follow[0] if x] and rows[0]["undeployed"] == [], \
        "its first day deploys its first picks"
    for i, x in enumerate(rows):
        now = [v for v in follow[i] if v]
        was = [v for v in follow[i - 1] if v] if i else []
        assert x["running"] == now and x["empty"] == 3 - len(now)
        assert [d["id"] for d in x["deployed"]] == [v for v in now if v not in was]
        assert [d["id"] for d in x["undeployed"]] == [v for v in was if v not in now]
        assert (x["trades"], x["wins"]) == (r["day_trades"][i], r["day_wins"][i])
        assert (x["profit"] or 0) == pytest.approx(r["day_profit"][i] if x["trades"] else 0)
        for d in x["deployed"] + x["undeployed"]:
            assert d["words"] == doc["switch_ons"][d["id"]] and d["words"].startswith("Every day, switch on")
    changed = vr.room_log(r["id"], {"date_from": "2026-09-01", "date_to": "2026-11-05"})
    assert changed["total"] == sum(1 for x in rows if x["deployed"] or x["undeployed"]) == changed["days_changed"]
    assert changed["deployed"] == sum(len(x["deployed"]) for x in rows)
    assert changed["undeployed"] == sum(len(x["undeployed"]) for x in rows) >= 1, "FLIP's switch-ons were dropped"
    assert changed["figures"]["trades"] == r["trades"] and changed["figures"]["profit"] == pytest.approx(r["profit"])
    assert [d["id"] for d in changed["running_now"]] == [x for x in follow[-1] if x]


def test_a_log_follows_the_days_asked_and_says_when_nothing_changed(run):
    doc = run["doc"]
    none = _room(doc, "no_picker")
    quiet = vr.room_log(none["id"], {"date_from": "2026-10-01", "date_to": "2026-10-31"})
    assert quiet["total"] == 0 and "nothing was deployed or undeployed in these 31 days" in quiet["why"]
    assert quiet["figures"]["trades"] == sum(none["day_trades"][30:61])
    whole = vr.room_log(none["id"], {"date_from": "2026-09-01", "date_to": "2026-11-05"})
    assert whole["total"] == 1 and whole["rows"][0]["day_s"] == doc["first_day_s"], "it deployed once, on its first day"
    assert vr.room_log("ZZZZZZZZ", {})["found"] is False
    with pytest.raises(vr.BadAsk):
        vr.room_log(none["id"], {"date_from": "soon"})


def test_the_run_carries_each_rooms_switch_ons_day_by_day(run):
    doc = run["doc"]
    assert doc["version"] >= vr.NEED_VERSION
    used = set()
    for r in doc["rules"]:
        assert len(r["follow"]) == doc["days"] and all(len(day) == 3 for day in r["follow"])
        assert sum(r["day_wins"]) == r["wins"] and len(r["day_wins"]) == doc["days"]
        assert sum(1 for day in r["follow"] for x in day if x is None) == r["empty_room_days"]
        used |= {x for day in r["follow"] for x in day if x}
    assert used == set(doc["switch_ons"]), "every switch-on a room followed has its words"


def test_no_run_or_an_older_run_says_what_to_do(run, monkeypatch, tmp_path):
    monkeypatch.setattr(lab, "home", lambda: tmp_path / "nothing")
    vr._CACHE.update(key=None, doc=None, tr=None)
    p = vr.rooms_page({})
    assert p["ready"] is False and "have not been measured yet" in p["why"] and p["rows"] == []
    assert vr.room_log("ANY", {})["ready"] is False
    # a run from before the day-by-day switch-ons were kept is not one this page can read
    old = tmp_path / "old"
    old.mkdir()
    src = run["tmp"] / "v4" / "picker-lab"
    doc = json.loads((src / "lab.json").read_text(encoding="utf-8"))
    (old / "lab.json").write_text(json.dumps({**doc, "version": 1}), encoding="utf-8")
    (old / "trades.pkl").write_bytes((src / "trades.pkl").read_bytes())
    monkeypatch.setattr(lab, "home", lambda: old)
    vr._CACHE.update(key=None, doc=None, tr=None)
    assert vr.rooms_page({})["ready"] is False
    vr._CACHE.update(key=None, doc=None, tr=None)


# ------------------------------------------------------------------ measured again every night
def test_a_run_is_due_only_when_the_refresh_has_landed_a_newer_store(monkeypatch, tmp_path):
    from tradingagents import v4_daily

    monkeypatch.setattr(lab, "home", lambda: tmp_path)
    monkeypatch.setattr(lab, "running", lambda: False)
    monkeypatch.setattr(lab, "newest_run_end", lambda: 1_000)
    monkeypatch.setattr(v4_daily, "status", lambda: {"phase": "done"})
    monkeypatch.setattr(lab, "store_end", lambda: 1_000)
    assert lab.due() is None, "the newest run is already on this store"
    monkeypatch.setattr(lab, "store_end", lambda: 2_000)
    assert lab.due() and "the store now ends" in lab.due()
    for phase in ("dispatch", "running", "collect", "build", "lists", "agree", "unreadable"):
        monkeypatch.setattr(v4_daily, "status", lambda phase=phase: {"phase": phase})
        assert lab.due() is None, f"not while the refresh is at {phase}"
    monkeypatch.setattr(v4_daily, "status", lambda: {"phase": "done"})
    monkeypatch.setattr(lab, "running", lambda: True)
    assert lab.due() is None, "one run at a time"
    monkeypatch.setattr(lab, "running", lambda: False)
    monkeypatch.setattr(lab, "store_end", lambda: 0)
    assert lab.due() is None, "a store that cannot be read is not a go-ahead"


def test_a_failed_run_is_tried_again_an_hour_later_never_every_tick(monkeypatch, tmp_path):
    from tradingagents import v4_daily

    monkeypatch.setattr(lab, "home", lambda: tmp_path)
    monkeypatch.setattr(lab, "running", lambda: False)
    monkeypatch.setattr(lab, "newest_run_end", lambda: 1_000)
    monkeypatch.setattr(lab, "store_end", lambda: 2_000)
    monkeypatch.setattr(v4_daily, "status", lambda: {"phase": "idle"})
    lab._write_status({"started_s": 5_000, "ended_s": 5_100, "ok": False, "error": "MemoryError: ", "tried_end_s": 2_000})
    assert lab.due(now_s=5_100 + 60) is None
    assert lab.due(now_s=5_100 + lab.RETRY_S + 1), "an hour later it is tried again"
    monkeypatch.setattr(lab, "store_end", lambda: 3_000)
    assert lab.due(now_s=5_100 + 60), "a newer store is a new try at once"
    st = lab.status()
    assert st["ok"] is False and st["error"] == "MemoryError: " and st["running"] is False


def test_a_run_that_died_is_said_and_a_test_never_starts_one(monkeypatch, tmp_path):
    monkeypatch.setattr(lab, "home", lambda: tmp_path)
    monkeypatch.setattr(lab, "running", lambda: False)
    lab._write_status({"started_s": 5_000, "ended_s": None, "ok": None, "error": "", "tried_end_s": 2_000})
    assert lab.status()["error"] == "the run that started never finished"
    monkeypatch.setattr(lab, "running", lambda: True)
    assert lab.status()["error"] == "" and lab.status()["running"] is True, "still going is not dead"
    started = []
    monkeypatch.setattr(lab, "start_run", lambda: started.append(1) or 1)
    monkeypatch.setattr(lab, "due", lambda now_s=None: "a newer store")
    assert lab.tick() == {"started": False, "why": "never from a test"} and not started


def test_the_site_measures_the_rooms_again_in_a_thread_of_their_own():
    api = (REPO / "tradingagents/api.py").read_text(encoding="utf-8")
    assert 'name="picker-lab"' in api and "_vpl.tick" in api
    src = (REPO / "tradingagents/v4_picker_lab.py").read_text(encoding="utf-8")
    assert "**portable.DETACHED" in src, "a background program has no window"
    assert '"PYTHONUNBUFFERED": "1"' in src and 'run.log' in src, "its output is kept, line by line"


# ------------------------------------------------------------------ the page
def _panel():
    return (REPO / "webapp/src/components/forecast/ForecastV4.tsx").read_text(encoding="utf-8")


def test_the_streak_section_is_gone_and_the_rooms_section_is_there():
    p = _panel()
    assert "Streak" not in p and "/api/forecast-v4/streaks" not in p
    assert ">Rooms</h3>" in p and "<Rooms base={base} />" in p
    assert '"/api/forecast-v4/rooms"' in p and "`/api/forecast-v4/rooms/${id}`" in p


def test_the_rooms_table_carries_every_required_column_and_filter():
    p = _panel()
    cols = re.search(r'\{\["ID", "room \(its picker rule\)".*?\]\.map', p, re.S).group(0)
    for col in ('"ID"', '"PROFIT / TOTAL $"', '"win rate"', '"wins / losses"', '"trades"', '"worst losing run"',
                '"TP"', '"SL"', '"leverage"', '"deployed / undeployed"'):
        assert col in cols, col
    for box in ("rooms from day", "rooms to day", "rooms last N days", "rooms min win rate %", "rooms min trades",
                "rooms min profit $", "rooms that made money", "find a room by id", "sort the rooms", "clear all"):
        assert box in p, box
    assert "picker rules tested" in p and "margin a trade at" in p and "a day)" in p
    assert "TOTAL PROFIT" in p and "nothing here switches anything on" in p
    for word in ('"deployed"', '"undeployed"', '"running that day"', '"profit that day"'):
        assert word in p, word
    assert "earning: true" in p, "it opens on the rooms that are earning this month"


def test_the_rooms_section_filters_nothing_itself_and_prints_dates_one_way():
    p = _panel()
    rooms = p[p.index("// ---------------------------------------------------------------- rooms"):]
    assert not re.search(r"rows\??\.filter\(", rooms), "every filter is the server's"
    assert "new Date(" not in rooms and "toLocale" not in rooms.replace("toLocaleString()", "")
    assert rooms.count("fmtWhen(") >= 8
    assert 'type="date"' in rooms, "a date box hands the server a day; the page prints dates with fmtWhen"


def test_a_run_that_died_without_a_word_waits_an_hour_too(monkeypatch, tmp_path):
    """A run killed before it could write why (a restart, a crash on its first line) left "started,
    never ended": retried on every 30-second tick, it would start a new program twice a minute."""
    from tradingagents import v4_daily

    monkeypatch.setattr(lab, "home", lambda: tmp_path)
    monkeypatch.setattr(lab, "running", lambda: False)
    monkeypatch.setattr(lab, "newest_run_end", lambda: 1_000)
    monkeypatch.setattr(lab, "store_end", lambda: 2_000)
    monkeypatch.setattr(v4_daily, "status", lambda: {"phase": "done"})
    lab._write_status({"started_s": 5_000, "ended_s": None, "ok": None, "error": "", "tried_end_s": 2_000})
    assert lab.due(now_s=5_000 + 90) is None
    assert lab.due(now_s=5_000 + lab.RETRY_S + 1)


def test_a_run_being_written_never_empties_the_list_and_the_kept_runs_are_read_once(run, monkeypatch):
    vr._CACHE.update(key=None, doc=None, tr=None, measured=None)
    first = vr.rooms_page({})
    assert first["ready"]
    read = []
    monkeypatch.setattr(lab, "previous", lambda doc: read.append(1) or None)
    for _ in range(3):
        assert vr.rooms_page({})["measured"] == first["measured"]
    assert not read, "the night before is worked out once a run, not once an ask"
    # the trades of a NEWER run land before the run that names them: the list keeps the pair it holds
    home = run["tmp"] / "v4" / "picker-lab"
    old = (home / "trades.pkl").read_bytes()
    with open(home / "trades.pkl", "rb") as fh:
        tp = pickle.load(fh)
    try:
        with open(home / "trades.pkl", "wb") as fh:
            pickle.dump({**tp, "built_s": tp["built_s"] + 1}, fh, protocol=4)
        again = vr.rooms_page({})
        assert again["ready"] and again["rows"] == first["rows"]
    finally:
        (home / "trades.pkl").write_bytes(old)
        vr._CACHE.update(key=None, doc=None, tr=None, measured=None)
    src = (REPO / "tradingagents/v4_picker_lab.py").read_text(encoding="utf-8")
    assert src.index('tmp.replace(home() / "trades.pkl")') < src.index('publish(home() / "lab.json"'), \
        "the trades are swapped in whole, before the run that names them"
