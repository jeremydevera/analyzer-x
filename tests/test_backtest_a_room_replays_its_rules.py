"""Backtest a room = replay the room's OWN rules day by day (operator, Oct 02,
2026: "backtest room should like backtest for the room strategy example / what
strategies did switched on and off for Sept 3, 4, 5, 6, 7 and so on", and "you
should be using the backtest rows because this is the source of truth").

Spec: docs/superpowers/specs/2026-10-02-room-replay-design.md. Every test here
puts its candles, its trades and its checks on ONE timeline — the operator's
local days (RCA-2026-09-12-A).
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3

import pandas as pd
import pytest

from tradingagents import room_replay as rr, watcher_policy as wp, watcher_replay as wr

H = 3_600_000
MIN = 60_000


def _ms(y, m, d, h=0, mi=0):
    return int(dt.datetime(y, m, d, h, mi).timestamp() * 1000)


ROOM_RULES = {**wp.DEFAULTS, "on_winrate": 80.0, "off_winrate": 80.0, "min_trades": 30,
              "tp_rule": ">", "max_sl": 2.0, "window_days": 15, "raw": True,
              "max_new_per_day": 0, "max_slots": 0, "max_per_coin": 0}


# ------------------------------------------------------- 1. the live timing
@pytest.mark.parametrize("raw", [True, False])
def test_the_schedule_is_the_live_watchers_own(monkeypatch, raw):
    """Drive the REAL strategy_watcher.consider() every 30 seconds for two
    days (the supervisor's tick) and record when it runs each pass: the
    replay's schedule must be exactly those moments."""
    from tradingagents import strategy_watcher as sw

    box = {"st": {"mode": "act", "cfg": {"raw": raw}}}
    monkeypatch.setattr(sw, "_read", lambda: json.loads(json.dumps(box["st"])))
    monkeypatch.setattr(sw, "_write", lambda d: box.__setitem__("st", json.loads(json.dumps(d))))
    calls = []
    monkeypatch.setattr(sw, "_off_pass",
                        lambda now, cfg, st, act, out: calls.append(("off", now)) or [])
    monkeypatch.setattr(sw, "_on_pass",
                        lambda now, cfg, st, act, out: calls.append(("on", now)) or "")
    monkeypatch.setattr(sw, "_practice_now", lambda now, cfg: {})
    t0 = _ms(2026, 9, 3)
    t1 = _ms(2026, 9, 5)
    for now in range(t0 // 1000, t1 // 1000, 30):
        sw.consider(now=float(now))
    sched = wr.live_schedule(t0, t1 - 1, raw)
    assert [n for k, n in calls if k == "off"] == [a / 1000 for a, f, _o in sched if f]
    assert [n for k, n in calls if k == "on"] == [a / 1000 for a, _f, o in sched if o]
    on_hours = {dt.datetime.fromtimestamp(a / 1000).hour for a, _f, o in sched if o}
    assert on_hours == ({0} if raw else {sw.ON_HOUR}), \
        "raw rooms switch on just after midnight, the others at noon"
    assert len([1 for _a, f, _o in sched if f]) == 48, "the switch-off pass runs every hour"


def test_without_a_schedule_simulate_is_the_midnight_replay_it_always_was():
    """Existing callers pass no schedule: one check a midnight, switch-off then
    switch-on — the same answer as that schedule written out."""
    start = _ms(2026, 9, 1)
    trades = [[start - 10 * 24 * H + i * 6 * H, start - 10 * 24 * H + i * 6 * H + H,
               0.5 if i % 7 else -1.0, 1] for i in range(80)]
    combos = [{"id": "AAAA0001", "coin": "VUG", "tf": "1h", "signal": "ibs", "th": 0.0,
               "sl": 0.5, "tp": 0.6, "gate": "ok", "trades": trades}]
    end = _ms(2026, 9, 9, 12)
    a = wr.simulate(combos, start_ms=start, end_ms=end, cfg={"min_trades": 20,
                                                              "on_winrate": 80.0,
                                                              "off_winrate": 80.0})
    plan = [(m, True, True) for m in wr.local_midnights(start, end)]
    b = wr.simulate(combos, start_ms=start, end_ms=end, cfg={"min_trades": 20,
                                                              "on_winrate": 80.0,
                                                              "off_winrate": 80.0},
                    schedule=plan)
    assert a["events"] == b["events"] and a["summary"] == b["summary"]
    assert a["events"], "the fixture must switch something on to prove anything"


# ------------------------------------------------------- 2. no look-ahead
def _log(trades):
    """A trades_for log: (entry_ms, exit_minute_ms, pnl) per trade."""
    from tradingagents.positions_view import fmt_when

    return [{"entry time": fmt_when(e / 1000), "exit time": fmt_when(x / 1000),
             "exit_minute_ms": x, "why": "TP" if p > 0 else "SL", "side": "LONG",
             "pnl $": p} for e, x, p in trades]


def _combo(cid, trades, coin="VUG"):
    c = {"id": cid, "coin": coin, "tf": "15m", "signal": "willr14", "th": 0.0, "sl": 1.2,
         "tp": 2.0, "group": "classic", "gate": "warn"}
    rec = rr.record(c, {"log": _log(trades)}, None, None)
    return {**c, "trades": rec["trades"]}


def test_a_trade_is_known_only_when_its_exit_minute_has_ended():
    """30 wins, the 30th touching its target in the minute that STARTS at the
    Sep 10 midnight check: at that check it has not closed yet, so the row is
    switched on at the next midnight — never by a trade still in progress."""
    sep10 = _ms(2026, 9, 10)
    wins = [(sep10 - (30 - i) * 4 * H, sep10 - (30 - i) * 4 * H + 30 * MIN, 0.9)
            for i in range(1, 30)]
    wins.append((sep10 - 2 * H, sep10, 0.9))            # exit minute 00:00-00:01
    combo = _combo("LATEWIN1", wins)
    assert combo["trades"][-1][1] == sep10 + MIN, "known at the END of its exit minute"
    got = wr.simulate([combo], start_ms=_ms(2026, 9, 8), end_ms=_ms(2026, 9, 12),
                      cfg=ROOM_RULES, schedule=wr.live_schedule(_ms(2026, 9, 8),
                                                                _ms(2026, 9, 12), True))
    on = [e["at"] for e in got["events"] if e["action"] == "on"]
    assert on == [_ms(2026, 9, 11)], [dt.datetime.fromtimestamp(x / 1000) for x in on]


def test_moving_a_later_trade_never_changes_an_earlier_decision():
    """The spec's own test: shift or flip every trade that closes after a
    decision moment D, and every switch-on/off at or before D is unchanged."""
    base = _ms(2026, 9, 1)
    combos = []
    for k in range(6):
        trades = []
        for i in range(200):
            e = base - 16 * 24 * H + i * 5 * H + k * 37 * MIN
            # blocks of 20 trades, every third one half lost: the 15-day win
            # rate swings across 80% and the rows go on AND off
            pnl = -1.0 if (i // 20 + k) % 3 == 0 and i % 2 == 0 else 0.6
            trades.append((e, e + 50 * MIN + k * MIN, pnl))
        combos.append(_combo(f"MOVE000{k}", trades, coin=f"C{k}"))
    sched = wr.live_schedule(base, _ms(2026, 9, 12), True)
    before = wr.simulate(combos, start_ms=base, end_ms=_ms(2026, 9, 12), cfg=ROOM_RULES,
                         schedule=sched)
    assert len(before["events"]) >= 6, "the fixture must switch things on AND off"
    for d in (_ms(2026, 9, 3, 7), _ms(2026, 9, 5), _ms(2026, 9, 8, 13)):
        moved = []
        for c in combos:
            ts = []
            for t in c["trades"]:
                t = list(t)
                if t[1] > d:                    # known only after D: rewrite it
                    t[2] = -t[2]
                    t[1] += 3 * H
                    t[4] += 3 * H
                ts.append(t)
            moved.append({**c, "trades": ts})
        after = wr.simulate(moved, start_ms=base, end_ms=_ms(2026, 9, 12), cfg=ROOM_RULES,
                            schedule=sched)
        upto = lambda r: [e for e in r["events"] if e["at"] <= d]  # noqa: E731, B023 — used at once
        assert upto(after) == upto(before), dt.datetime.fromtimestamp(d / 1000)
        assert after["events"] != before["events"], "the later trades did matter after D"


def test_dropping_a_list_that_never_passes_changes_nothing():
    """A raw room has tens of thousands of candidates; the replay keeps only
    the lists that clear the line at some switch-on check. Exact: the same
    replay with and without the others."""
    base = _ms(2026, 9, 1)
    combos = []
    for k in range(8):
        trades = []
        for i in range(200):
            e = base - 16 * 24 * H + i * 5 * H + k * 11 * MIN
            lose = (i // 20 + k) % 3 == 0 and i % 2 == 0 if k < 4 else i % 3 == 0
            trades.append((e, e + 40 * MIN, -1.0 if lose else 0.6))
        combos.append(_combo(f"KEEP000{k}", trades, coin="VUG" if k % 2 else "FAST"))
    end = _ms(2026, 9, 12)
    sched = wr.live_schedule(base, end, True)
    ons = [a for a, _f, o in sched if o]
    kept = [c for c in combos
            if rr.ever_passes(wr._Book(c), ons, 15 * 24 * H, ROOM_RULES)]
    assert 0 < len(kept) < len(combos), "some must pass and some never"
    a = wr.simulate(combos, start_ms=base, end_ms=end, cfg={**ROOM_RULES, "coin_slices": 4},
                    schedule=sched)
    b = wr.simulate(kept, start_ms=base, end_ms=end, cfg={**ROOM_RULES, "coin_slices": 4},
                    schedule=sched)
    assert a["events"] == b["events"] and a["summary"] == b["summary"]


# ------------------------------------------------- 3. the candidate floors
def _rows_db(path, rows):
    con = sqlite3.connect(path)
    cols = ("id", "coin", "tf", "signal", "th", "sl", "tp", "trades", "wins", "winrate",
            "profit", "cost_of_tp", "gate", "t15", "w15", "sizing", "res", "pair")
    con.execute(f"CREATE TABLE rows ({', '.join(cols)})")
    for r in rows:
        con.execute(f"INSERT INTO rows VALUES ({', '.join('?' * len(cols))})",
                    [r.get(c) for c in cols])
    con.commit()
    con.close()


def test_the_candidates_are_every_row_that_could_ever_pass_and_no_other(tmp_path):
    from tradingagents import stores

    ok = {"coin": "VUG", "tf": "15m", "signal": "willr14", "th": 0.0, "sl": 1.2, "tp": 2.0,
          "trades": 30, "wins": 24, "winrate": 80.0, "profit": 5.0, "cost_of_tp": 41.9,
          "gate": "warn", "sizing": "flat", "res": "1m"}
    rows = [ok,
            {**ok, "signal": "stoch14", "cost_of_tp": None, "gate": "unknown"},   # unread cost
            {**ok, "signal": "ibs", "trades": 900, "wins": 24, "winrate": 2.7},  # 24 wins can cluster
            {**ok, "signal": "a", "wins": 23},                                   # too few wins
            {**ok, "signal": "b", "trades": 29},                                 # too few trades
            {**ok, "signal": "c", "cost_of_tp": 50.0},                           # live blocks it
            {**ok, "signal": "d", "sl": 2.1},                                    # stop too wide
            {**ok, "signal": "e", "tp": 1.2},                                    # TP = SL
            {**ok, "signal": "f", "sizing": "martingale"},
            {**ok, "signal": "g", "res": None}]                                  # not minute-exact
    db = tmp_path / "rows.db"
    _rows_db(db, rows)
    st = stores.Store(name="v2", home=tmp_path, candles=tmp_path / "candles", rows_db=db,
                      parquet=tmp_path / "pq", fine_tf="1m", download_kind="download_v2",
                      backtest_kind="backtest_v2")
    got, info = rr.candidates(ROOM_RULES, store=st)
    assert sorted(c["signal"] for c in got) == ["ibs", "stoch14", "willr14"]
    assert info["count"] == 3 and info["no_cost_reading"] == 1
    assert info["floors"] == {"trades": 30, "wins": 24, "cost_under_pct": 50.0,
                              "max_sl": 2.0, "tp_rule": ">"}
    from tradingagents import backtest_report as br

    vug = next(c for c in got if c["signal"] == "willr14")
    assert vug["id"] == br.row_code("VUG", "15m", "willr14", 0.0, 1.2, 2.0, "flat", res="1m")


def _store(tmp_path, db):
    from tradingagents import stores

    return stores.Store(name="v2", home=tmp_path, candles=tmp_path / "candles", rows_db=db,
                        parquet=tmp_path / "pq", fine_tf="1m", download_kind="download_v2",
                        backtest_kind="backtest_v2")


def _many(n_pairs=20, per=50):
    """`per` candidate rows on each of `n_pairs` pairs, win rates 40%..89%."""
    out = []
    for p in range(n_pairs):
        for i in range(per):
            wr_ = 40 + i
            out.append({"coin": f"C{p}", "tf": "15m", "signal": f"s{i}", "th": 0.0, "sl": 1.0,
                        "tp": 1.5, "trades": 100, "wins": wr_, "winrate": float(wr_),
                        "profit": 1.0, "cost_of_tp": 10.0, "gate": "ok", "sizing": "flat",
                        "res": "1m", "pair": f"C{p}-15m"})
    return out


def _rows_db_pairs(path, rows):
    _rows_db(path, rows)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE pairs (pair TEXT PRIMARY KEY)")
    con.executemany("INSERT INTO pairs VALUES (?)", sorted({(r["pair"],) for r in rows}))
    con.commit()
    con.close()


def test_a_run_too_big_for_this_pc_is_refused_before_it_starts(tmp_path, monkeypatch):
    """Item 4 exactly is ~5 million rows for #6B08FF64 (60 sampled pairs,
    Oct 02, 2026): days of work. The estimate refuses it at once, by name."""
    db = tmp_path / "rows.db"
    _rows_db_pairs(db, _many())
    st = _store(tmp_path, db)
    est = rr.estimate(ROOM_RULES, store=st, pairs=20)
    assert est["estimate"] == 1000 and est["of"] == 20
    assert rr.estimate(ROOM_RULES, store=st, min_wr30=80.0, pairs=20)["estimate"] == 200
    monkeypatch.setattr(rr, "MAX_LISTS", 500)
    monkeypatch.setattr(rr, "rules_for", lambda room: ROOM_RULES)
    with pytest.raises(rr.TooMany) as e:
        rr.replay("6B08FF64", "2026-09-01", "2026-09-02", store=st, now=_ms(2026, 9, 3) / 1000)
    assert "about 1,000 Backtest v2 rows" in str(e.value) and "min_winrate30" in str(e.value)


def test_a_second_range_reuses_the_search_until_the_table_changes(tmp_path, monkeypatch):
    """The search is one pass over the whole v2 table — over 40 minutes on
    this PC's disk (Oct 03, 2026) — and it does not depend on the dates, so a
    second range for the same rules must not pay it again; a table the daily
    update re-filed must."""
    import os

    db = tmp_path / "rows.db"
    _rows_db_pairs(db, _many(n_pairs=2))
    st = _store(tmp_path, db)
    searched = []
    real = rr._search
    monkeypatch.setattr(rr, "_search", lambda *a, **k: searched.append(1) or real(*a, **k))
    first, info = rr.candidates(ROOM_RULES, store=st, min_wr30=80.0)
    again, info2 = rr.candidates(ROOM_RULES, store=st, min_wr30=80.0)
    assert len(searched) == 1 and again == first and info2["cached"] is True
    assert info2["count"] == info["count"] == 20
    rr.candidates(ROOM_RULES, store=st, min_wr30=85.0)
    assert len(searched) == 2, "another floor is another search"
    st_ = db.stat()
    os.utime(db, (st_.st_atime, st_.st_mtime + 3600))           # the daily update re-filed it
    rr.candidates(ROOM_RULES, store=st, min_wr30=80.0)
    assert len(searched) == 3, "a changed table is searched again"


def test_a_floor_nominates_above_it_and_audits_below_it(tmp_path):
    db = tmp_path / "rows.db"
    _rows_db_pairs(db, _many(n_pairs=4))
    st = _store(tmp_path, db)
    got, info = rr.candidates(ROOM_RULES, store=st, min_wr30=80.0)
    assert info["count"] == 4 * 10 and info["min_wr30"] == 80.0
    assert min(c["winrate30"] for c in got) == 80.0
    below = rr.audit_sample(ROOM_RULES, 80.0, store=st, want=30)
    assert len(below) == 30 and max(c["winrate30"] for c in below) < 80.0
    assert len({c["id"] for c in below}) == 30, "a sample never repeats a row"


def test_the_candidates_are_read_in_one_pass_never_through_the_win_rate_index(tmp_path,
                                                                             monkeypatch):
    """With a floor the planner seeks rows_wr2 and then fetches each match off
    the disk: 20,000 rows took 514 s on Oct 02, 2026 (7.5 hours for the 75%
    floor's 1,052,433). One pass over the table instead."""
    db = tmp_path / "rows.db"
    _rows_db_pairs(db, _many(n_pairs=2))
    con = sqlite3.connect(db)
    con.execute("CREATE INDEX rows_wr2 ON rows (winrate DESC, trades, profit DESC, id)")
    con.commit()
    con.close()
    seen = []
    from tradingagents import rows_index as ri

    real = ri._open

    class Spy:
        def __init__(self, con):
            self.con = con

        def execute(self, sql, *a):
            if sql.startswith("SELECT"):
                seen.append([tuple(r) for r in self.con.execute("EXPLAIN QUERY PLAN " + sql, *a)])
            return self.con.execute(sql, *a)

    import contextlib

    @contextlib.contextmanager
    def spy_open(*a, **k):
        with real(*a, **k) as con:
            yield Spy(con)
    monkeypatch.setattr(ri, "_open", spy_open)
    rr.candidates(ROOM_RULES, store=_store(tmp_path, db), min_wr30=75.0)
    plans = " ".join(str(p) for p in seen)
    assert "SCAN rows" in plans and "rows_wr2" not in plans, plans


def test_an_oversize_run_is_refused_out_loud_and_the_screen_says_why(monkeypatch):
    """A JOB THAT CANNOT START MUST SAY SO (CLAUDE.md): the refusal lands in
    the run file, and the page reads it instead of an empty table."""
    def too_many(*a, **k):
        raise rr.TooMany("about 6,699,613 Backtest v2 rows could pass this room's line")
    monkeypatch.setattr(rr, "replay", too_many)
    monkeypatch.setattr(rr, "disk_job", lambda: "")
    assert rr.main(["6B08FF64", "--from", "2026-09-01", "--to", "2026-10-02"]) == 4
    st = rr.status()
    assert not st["running"] and "about 6,699,613" in st["error"]
    got = rr.view("6B08FF64", _ms(2026, 9, 1) / 1000, _ms(2026, 10, 2) / 1000)
    assert got["state"] == "failed" and "6,699,613" in got["why"] and "rows" not in got
    assert not rr.lock_held(), "the lock is given back"


def test_no_test_can_read_the_real_backtest_v2_table():
    with pytest.raises(RuntimeError):
        rr.candidates(ROOM_RULES)
    with pytest.raises(RuntimeError):
        rr.estimate(ROOM_RULES)


# ------------------------------------------------- 4. trades_for parity
H0 = 1_789_516_800_000            # Sep 16, 2026 00:00 UTC


def _write_minutes(home, hours):
    rows = []
    for h in range(hours):
        for k in range(60):
            hi = lo = 100.0
            if h % 5 == 2 and k == 7:
                hi = 101.5                       # the target is touched
            if h % 5 == 4 and k == 40:
                lo = 96.5                        # the stop is touched
            rows.append((H0 + (h * 60 + k) * MIN, 100.0, hi, lo, 100.0, 7.0))
    df = pd.DataFrame(rows, columns=["t", "o", "h", "l", "c", "v"])
    (home / "candles").mkdir(parents=True, exist_ok=True)
    (home / "candles" / "XPIN_USDT-1m.json").write_text(json.dumps(
        {k: [float(x) if k != "t" else int(x) for x in df[k]] for k in df.columns}))


@pytest.fixture
def v2(tmp_path, monkeypatch):
    from tradingagents import auto_trader as at, market_sweep as msw, stores

    home = tmp_path / "v2"
    st = stores.Store(name="v2", home=home, candles=home / "candles",
                      rows_db=home / "rows.db", parquet=tmp_path / "pq",
                      fine_tf="1m", download_kind="download_v2", backtest_kind="backtest_v2")
    (home / "rows").mkdir(parents=True)
    (home / "state").mkdir()
    _write_minutes(home, 120)
    last_ms = H0 + 119 * H
    (home / "rows" / "XPIN-1h.json").write_text(json.dumps([
        {"coin": "XPIN", "tf": "1h", "signal": "ote", "th": 0.0, "sl": sl, "tp": tp,
         "sizing": "flat", "trades": 1, "wins": 1, "losses": 0, "profit": 0.9, "bars": 100,
         "last_ms": last_ms, "fee": 0.0004, "res": "1m", "unclear": 0}
        for sl, tp in ((3.0, 1.0), (3.0, 1.2))]))
    (home / "state" / "XPIN-1h.json").write_text(json.dumps({"__last_ms__": last_ms}))
    msw.save_costs("XPIN_USDT", fee=0.0004, liq=4.0, funding=[], root=str(home))
    # the signal: long on every 5th bar
    monkeypatch.setattr(at, "_dirs_for_backtest",
                        lambda key, hi, lo, cl, **k: [1 if i % 5 == 0 else 0
                                                      for i in range(len(cl))])
    return st


def _cand(tp):
    from tradingagents import backtest_report as br

    return {"coin": "XPIN", "tf": "1h", "signal": "ote", "th": 0.0, "sl": 3.0, "tp": tp,
            "id": br.row_code("XPIN", "1h", "ote", 0.0, 3.0, tp, "flat", res="1m"),
            "group": "classic", "gate": "ok"}


def test_a_cached_list_is_the_list_backtest_v2_shows_for_that_id(v2):
    from tradingagents import market_sweep as msw

    cands = [_cand(1.0), _cand(1.2)]
    fresh = {c["id"]: rr.record(c, msw.trades_for("XPIN", "1h", signal="ote", th=0.0, sl=3.0,
                                                   tp=c["tp"], sizing="flat", base_margin=5.0,
                                                   store=v2), None, None)["trades"]
             for c in cands}
    assert all(len(v) >= 10 for v in fresh.values()), "the fixture must trade"
    built, info = rr.build_lists(cands, store=v2, workers=0, memo=False)
    assert info["rebuilt"] == 2 and info["cached"] == 0
    again, info2 = rr.build_lists(cands, store=v2, workers=0)
    assert info2["cached"] == 2, "nothing changed: both come from the cache"
    for c in cands:
        assert built[c["id"]]["trades"] == fresh[c["id"]]
        assert json.loads(json.dumps(again[c["id"]]["trades"])) == \
            json.loads(json.dumps(fresh[c["id"]]))
    # the one-coin memo a worker uses gives the same lists, call for call
    memo = rr.rebuild_coin((v2, "XPIN", [{**c, "_stamp": None} for c in cands], True,
                            str(rr.trades_dir())))
    for c in cands:
        assert memo[c["id"]]["trades"] == fresh[c["id"]]


def test_a_list_is_rebuilt_when_its_candles_grow(v2):
    cands = [_cand(1.0)]
    rr.build_lists(cands, store=v2, workers=0)
    _write_minutes(v2.home, 121)              # one more hour of minutes on disk
    _, info = rr.build_lists(cands, store=v2, workers=0)
    assert info["rebuilt"] == 1 and info["cached"] == 0


# ------------------------------------- 5. the practice side and its total
ROOM = "6B08FF64"
SLOT_ON = "willr14_15m_sl12tp2|VUG_USDT"
SLOT_OFF = "zscore20_30m_sl06tp08|DVNSTOCK_USDT"


@pytest.fixture
def room(tmp_path, monkeypatch):
    from tradingagents import (
        auto_trader as at,
        local_history as lh,
        profiles,
        room_backtest as rb,
        strategy_watcher as sw,
    )

    monkeypatch.setattr(sw, "STATE", tmp_path / "strategy_watcher.json")
    monkeypatch.setattr(sw, "LOG", tmp_path / "strategy_watcher.jsonl")
    on1 = _ms(2026, 10, 1, 12, 51) // 1000
    off2 = _ms(2026, 10, 2, 3, 0) // 1000
    with profiles.using(ROOM):
        led = at._pp(at.LEDGER_PATH)
        dep = lh._deploy_log()
        sett = at._pp(at.SETTINGS_PATH)
    exits = [  # (slot, exit_s, entry_s, pnl, dry)
        (SLOT_ON, on1 + 3600, on1 + 900, 0.98, True),
        (SLOT_ON, on1 + 7200, on1 + 5400, -1.62, True),
        (SLOT_ON, _ms(2026, 10, 2, 9) // 1000, _ms(2026, 10, 2, 8) // 1000, 0.98, True),
        (SLOT_OFF, on1 + 4000, on1 + 1800, -0.55, True),   # switched off since
        (SLOT_OFF, off2 - 600, off2 - 7200, 0.41, True),
        (SLOT_ON, on1 - 86400 * 3, on1 - 86400 * 3 - 900, 5.0, True),   # before the range
        (SLOT_ON, on1 + 9000, on1 + 8100, 9.99, False),                  # real money
    ]
    lines = [{"action": "exit", "dry_run": d, "strategy": s.split("|")[0],
              "symbol": s.split("|")[1], "ts": x, "entry_ts": e, "pnl_est": p}
             for s, x, e, p, d in exits]
    lines += [{"action": "gate_blocked", "dry_run": True, "strategy": "willr14_15m_sl12tp2",
               "symbol": "VUG_USDT", "ts": on1 + 600, "candles": 1, "bars": [on1]},
              {"action": "enter", "dry_run": True, "strategy": "willr14_15m_sl12tp2",
               "symbol": "VUG_USDT", "ts": on1 + 900}]
    led.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    dep.write_text("".join(json.dumps(x) + "\n" for x in (
        {"changed_at": on1, "strategy_key": SLOT_ON, "action": "deployed"},
        {"changed_at": on1, "strategy_key": SLOT_OFF, "action": "deployed"},
        {"changed_at": off2, "strategy_key": SLOT_OFF, "action": "disarmed"})),
        encoding="utf-8")
    sett.write_text(json.dumps({"strategies": ["willr14_15m_sl12tp2"],
                                "strategy_coins": {"willr14_15m_sl12tp2": ["VUG_USDT"]},
                                "watcher_slots": {SLOT_ON: {"id": "NJUZZEC2", "on_at": on1}}}),
                    encoding="utf-8")
    # NEITHER may read the operator's real Backtest v2 table (the first draft
    # of this fixture patched `candidates` alone, and `estimate` sampled the
    # real 52-million-row rows.db for 40 seconds)
    monkeypatch.setattr(rr, "candidates", lambda cfg, store=None, limit=0, min_wr30=None: (
        [], {"count": 0, "ready": True, "limit": 0, "by_group": {}, "no_cost_reading": 0,
             "floors": {}, "sql": "", "min_wr30": min_wr30}))
    monkeypatch.setattr(rr, "estimate", lambda cfg, store=None, min_wr30=None: {
        "estimate": 0, "pairs": 0, "of": 0})
    rb._LEDGER.clear()
    yield {"in_range": [x for x in exits if x[4] and x[1] >= _ms(2026, 10, 1) // 1000]}
    rb._LEDGER.clear()


def test_the_practice_total_is_the_rooms_own_trade_record(room):
    """Every closed PRACTICE trade in the range — a strategy switched off
    since included, real money and days outside the range not — so the total
    is the auto-trade screen's for the same dates."""
    now = _ms(2026, 10, 2, 18) / 1000
    res = rr.replay(ROOM, "2026-10-01", "2026-10-02", now=now)
    want = round(sum(x[3] for x in room["in_range"]), 2)
    pr = res["summary"]["practice"]
    assert pr["profit"] == want == 0.2
    assert pr["closed"] == 5 and pr["wins"] == 3
    days = [d["practice"] for d in res["days"] if d["practice"]]
    assert round(sum(d["profit"] for d in days), 2) == want
    assert days[-1]["total"] == want, "the running total ends on the total"
    bt_days = res["days"]
    assert bt_days[-1]["total"] == res["summary"]["backtest"]["profit"]
    off = [t for t in res["practice_trades"] if t["slot"] == SLOT_OFF]
    assert len(off) == 2 and all(t["off_now"] for t in off), \
        "a strategy switched off since is still in the total, and marked"
    assert res["summary"]["practice"]["slots_switched_off"] == 1
    assert res["summary"]["reconcile"]["practice_only"] == 5, \
        "with no candidate, every practice trade is named as one the replay never had"


def test_a_range_not_measured_yet_says_so_and_never_shows_an_empty_table(room):
    got = rr.view(ROOM, _ms(2026, 10, 1) / 1000, _ms(2026, 10, 2) / 1000, start=False)
    assert got["state"] == "not_measured" and "rows" not in got
    got = rr.view(ROOM, _ms(2026, 10, 1) / 1000, _ms(2026, 10, 2) / 1000)
    assert got["state"] == "not_measured" and "never under a test run" in got["why"]


def test_a_measuring_range_says_how_far_it_has_got(room):
    assert rr.take_lock()
    try:
        rr._write_json(rr._run_file(), {"running": True, "room": ROOM,
                                        "from_day": "2026-10-01", "to_day": "2026-10-02",
                                        "phase": "trade lists", "done": 120, "total": 2000})
        got = rr.view(ROOM, _ms(2026, 10, 1) / 1000, _ms(2026, 10, 2) / 1000)
        assert got["state"] == "measuring" and "120 of 2,000" in got["why"]
    finally:
        rr.release_lock()
    got = rr.view(ROOM, _ms(2026, 10, 1) / 1000, _ms(2026, 10, 2) / 1000, start=False)
    assert got["state"] == "failed" and "stopped before it finished" in got["why"]


def test_a_measured_range_pages_ten_at_a_time_on_the_server(room):
    now = _ms(2026, 10, 2, 18) / 1000
    res = rr.replay(ROOM, "2026-09-20", "2026-10-02", now=now)
    rr.save(res)
    got = rr.view(ROOM, _ms(2026, 9, 20) / 1000, _ms(2026, 10, 2) / 1000, what="days")
    assert got["state"] == "ready" and got["total"] == 13 and len(got["rows"]) == 10
    assert got["pages"] == 2 and got["per"] == 10
    # the room's first practice trade closed Sep 28, 2026 (the fixture's
    # out-of-range one): before that day there is no practice column at all
    before = [d for d in got["rows"] if d["day"] < "2026-09-28"]
    after = [d for d in got["rows"] if d["day"] >= "2026-09-28"]
    assert before and all(d["practice"] is None for d in before), \
        "before the room existed there is no practice column, never a column of zeros"
    assert after and all(d["practice"] is not None for d in after)
    pr = rr.view(ROOM, _ms(2026, 9, 20) / 1000, _ms(2026, 10, 2) / 1000, what="practice",
                 day="2026-10-02")
    assert pr["total"] == 2 and {t["slot"] for t in pr["rows"]} == {SLOT_ON, SLOT_OFF}


def test_the_api_route_serves_the_replay(room):
    from tradingagents import api

    # the route asks the room's automatic floor (the screen sends none)
    res = rr.replay(ROOM, "2026-10-01", "2026-10-02", now=_ms(2026, 10, 2, 18) / 1000,
                    min_wr30=rr.auto_floor(rr.rules_for(ROOM)))
    rr.save(res)
    got = api.room_replay_route(ROOM, _ms(2026, 10, 1) / 1000, _ms(2026, 10, 2) / 1000 + 86399,
                                view="practice")
    assert got["state"] == "ready" and got["total"] == 5 and got["per"] == 10
    with pytest.raises(api.HTTPException) as e:
        api.room_replay_route("NOPE", 0, 1)
    assert e.value.status_code == 404


# ------------------------------------------ 6. the window's own words
def test_a_15_day_room_says_15_days_not_30():
    """RCA-2026-10-02-H: #6B08FF64's log said "91.18% over 68 trades in the last
    30 days" over a 15-day count."""
    cfg = {**ROOM_RULES}
    row = {"id": "6PRDA4S8", "coin": "YMTCSTOCK", "tf": "1h", "signal": "ibs", "th": 0.0,
           "sl": 0.3, "tp": 0.4, "trades": 68, "wins": 62, "winrate": 91.18,
           "profit": 11.48, "gate": "warn"}
    why = wp.pick([row], [], {}, 0.0, cfg)[0]["why"]
    assert "in the last 15 days" in why and "30" not in why
    off = wp.judge({}, {**row, "winrate": 78.12}, cfg)
    assert off.startswith("its last-15-days win rate fell to 78.12%")
    assert "in the last 30 days" in wp.pick([row], [], {}, 0.0, {**cfg, "window_days": 30})[0]["why"]


def test_the_replay_page_derives_its_window_words():
    from tradingagents import replay_page as rp

    for stale in ("over 30 days`", "trades in 30 days", "over those 30 days",
                  "closed in the 30 days", "over the previous 30 days"):
        assert stale not in rp._HTML, stale
    assert rp._HTML.count("window_days||30") == 5


def test_the_first_note_warns_of_hindsight_with_the_fair_side_by_side():
    """#6B08FF64, Sep 01 - Oct 02, 2026: the replay +6,947.20 against the
    room's real practice -13.24. The candidates are chosen by their stored
    30-day results, so the totals read with hindsight; the page says so FIRST
    and prints the fair comparison — the days the room really traded — from
    the run's own rows."""
    days = [{"day": "2026-09-30", "profit": 25.5, "practice": None},
            {"day": "2026-10-01", "profit": 23.3, "practice": {"profit": -8.47}},
            {"day": "2026-10-02", "profit": 23.14, "practice": {"profit": -4.77}}]
    note = rr._hindsight(days, {"cut": [_ms(2026, 8, 23, 16)], "end_max": _ms(2026, 10, 2, 12)})
    assert note.startswith("HINDSIGHT")
    assert "Aug 23, 2026 4:00pm to Oct 02, 2026 12:00pm" in note
    assert ("On the 2 day(s) the room really traded (Oct 01, 2026 12:00am to Oct 02, 2026 "
            "12:00am) the replay made +46.44 and the practice account -13.24.") in note
    assert "2026-10" not in note, "dates on screen read like Oct 01, 2026, never a key"
    assert rr._hindsight([], {}).startswith("HINDSIGHT")


# ------------------------- 6. the room's own switch-ons, and no floor box
def test_the_rooms_own_switch_ons_are_candidates_whatever_the_floor(v2, tmp_path, monkeypatch):
    """Oct 03, 2026: #DS598KQV APHSTOCK 1h was switched on in #6B08FF64 at
    Oct 01, 2026 12:44pm (24 of 29 in 15 days) with a 30-day win rate of
    69.49% — under the 70% floor, so the replay never had it and could never
    match its practice trades. The room's own switch-ons are read from its
    watcher log and looked up in the pair files by the id the watcher wrote."""
    from tradingagents import profiles, strategy_watcher as sw

    monkeypatch.setattr(sw, "LOG", tmp_path / "strategy_watcher.jsonl")
    with profiles.using(ROOM):
        log = sw._log_path()
    hit = _cand(1.0)
    end = _ms(2026, 10, 2, 23, 59)
    ev = [{"at": _ms(2026, 10, 1, 12, 44) / 1000, "mode": "act", "action": "on",
           "id": hit["id"], "coin": "XPIN", "tf": "1h", "signal": "ote", "tp": 1.0, "sl": 3.0},
          {"at": _ms(2026, 10, 1, 12, 44) / 1000, "mode": "act", "action": "on",
           "id": "ZZZZZZZZ", "coin": "XPIN", "tf": "1h", "signal": "ote", "tp": 9.0, "sl": 3.0},
          {"at": _ms(2026, 10, 1, 12, 44) / 1000, "mode": "preview", "action": "on",
           "id": _cand(1.2)["id"], "coin": "XPIN", "tf": "1h", "signal": "ote",
           "tp": 1.2, "sl": 3.0},
          {"at": end / 1000 + 3600, "mode": "act", "action": "on",
           "id": _cand(1.2)["id"], "coin": "XPIN", "tf": "1h", "signal": "ote",
           "tp": 1.2, "sl": 3.0}]
    log.write_text("".join(json.dumps(e) + "\n" for e in ev) + "not json\n", encoding="utf-8")
    picks, info = rr.room_picks(ROOM, end, store=v2)
    assert [c["id"] for c in picks] == [hit["id"]], \
        "a preview is not a switch-on, and one after the range is not in it"
    assert picks[0]["tp"] == 1.0 and picks[0]["th"] == 0.0 and picks[0]["group"] == "classic"
    assert info == {"count": 2, "found": 1, "missing": ["ZZZZZZZZ"]}, \
        "an id the files do not hold is NAMED, never dropped quietly"


def test_the_screen_asks_only_a_room_and_dates(monkeypatch):
    """Operator, Oct 03, 2026: "what's this textbox i dont need this, i only
    need to input date and id of the room strategy that's it"."""
    from pathlib import Path

    from tradingagents import api

    src = (Path(__file__).resolve().parents[1] / "webapp" / "src" / "components"
           / "forecast" / "RoomForecasts.tsx").read_text(encoding="utf-8")
    assert "30-day win %" not in src and "setFloor" not in src
    client = (Path(__file__).resolve().parents[1] / "webapp" / "src" / "lib"
              / "api.ts").read_text(encoding="utf-8")
    assert 'p.set("min_winrate30"' not in client
    got = {}
    monkeypatch.setattr(rr, "view", lambda *a, **k: got.update(k) or {"state": "x"})
    api.room_replay_route(room=ROOM, from_s=_ms(2026, 9, 1) / 1000,
                          to_s=_ms(2026, 10, 2) / 1000)
    assert got["min_wr30"] == rr.rules_for(ROOM)["on_winrate"] - rr.FLOOR_BELOW
    assert rr.range_path(ROOM, "2026-09-01", "2026-10-02", 70.0).name \
        == f"2026-09-01_2026-10-02_wr70_{rr.RESULT_TAG}.json", \
        "a replay saved before the room's switch-ons were candidates is never served"


# ------------------------------------------------ 7. the progress bar
def test_a_running_replay_says_its_step_and_percent(room):
    """Operator, Oct 03, 2026: "can you show loading bar on whats percentage so
    i know the progress, in mobile i only see 'being measured' only"."""
    import re
    from pathlib import Path

    src = Path(rr.__file__).read_text(encoding="utf-8")
    said = set(re.findall(r'say\("([a-z ]+)"', src)) | set(re.findall(r'write\("([a-z ]+)"\)', src))
    assert said and said <= {n for n, _w in rr.PHASES}, \
        f"every step a run reports has its words: {said - {n for n, _w in rr.PHASES}}"
    assert rr.take_lock()
    try:
        rr._write_json(rr._run_file(), {"running": True, "room": ROOM, "min_wr30": 70.0,
                                        "from_day": "2026-10-01", "to_day": "2026-10-02",
                                        "phase": "trade lists", "done": 1206, "total": 4825,
                                        "started_at": 0.0})
        got = rr.view(ROOM, _ms(2026, 10, 1) / 1000, _ms(2026, 10, 2) / 1000, min_wr30=70.0)
        run = got["run"]
        assert got["state"] == "measuring"
        assert (run["step"], run["steps"]) == (4, len(rr.PHASES)) and run["pct"] == 25.0
        assert run["step_words"] == "reading each strategy's own backtest trades"
        rr._write_json(rr._run_file(), {"running": True, "room": ROOM, "min_wr30": 70.0,
                                        "from_day": "2026-10-01", "to_day": "2026-10-02",
                                        "phase": "candidates", "done": 0, "total": 0})
        run = rr.status()
        assert run["step"] == 3 and run["pct"] is None, \
            "a step with no count prints no number, never 0%"
    finally:
        rr.release_lock()
    tsx = (Path(__file__).resolve().parents[1] / "webapp" / "src" / "components" / "forecast"
           / "RoomForecasts.tsx").read_text(encoding="utf-8")
    assert 'role="progressbar"' in tsx and "<RunProgress run={d.run} />" in tsx
