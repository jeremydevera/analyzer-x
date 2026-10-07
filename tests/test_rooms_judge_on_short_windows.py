"""Rooms that switch on by their last 1, 2, 3 or 4 days (operator, Oct 07,
2026: "can you create a room strategy that has criteria that looks for past 1
day or 2 days or 3 days or 4 days ... (create seperate room for each)").

Their answers: the 30+ trades are counted INSIDE the 1-4 days ("Then it
should not show any results dont you get me?"), and the switch-off reads the
DEMO 30 DAYS figure ("Refer to previous prompt"). So a v2 row now carries its
own measured count for each of those windows (`t1`/`w1`/`p1` .. `t4`/`w4`/
`p4`, beside `t15`), the index files and searches them, and a room carries a
second window, `judge_days`, for its switch-off.

Candles and exits share ONE clock here (RCA-2026-09-12-A): hour bars from H0,
and every cutoff is measured back from the last of those bars.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tradingagents import auto_trader as at
from tradingagents import backtest_report as br
from tradingagents import watcher_candidates as wc

ROOT = Path(__file__).resolve().parents[1]
KEY = "t_short_1h"
H0 = 1_789_516_800_000            # Sep 16, 2026 00:00 UTC
HOUR = 3_600_000
DAY = 86_400_000


@pytest.fixture(autouse=True)
def _spec():
    at.STRATEGY_SPECS[KEY] = {"interval": "Min60", "bar_seconds": 3600,
                              "tp": .01, "sl": .01, "threshold": .003}
    yield
    at.STRATEGY_SPECS.pop(KEY, None)


def _walk(n=400, seed=7):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, .006, n)))
    opens = np.r_[close[0], close[:-1]]
    high = np.maximum(opens, close) * (1 + rng.uniform(0, .006, n))
    low = np.minimum(opens, close) * (1 - rng.uniform(0, .006, n))
    df = pd.DataFrame({"Date": pd.to_datetime([H0 + i * HOUR for i in range(n)], unit="ms"),
                       "Open": opens, "High": high, "Low": low, "Close": close,
                       "Volume": [1000.0] * n})
    dirs = [int(x) for x in rng.choice([-1, 0, 1], n, p=[.2, .6, .2])]
    return df, dirs


def _ms(stamp: str) -> int:
    from tradingagents import rolling30
    return rolling30._parse_when(stamp)


def _cuts(n=400):
    end = H0 + (n - 1) * HOUR           # the last candle, as the shard measures back
    return {d: end - d * DAY for d in br.SHORT_DAYS}


# ------------------------------------------------------------ the measurement
def test_the_engine_counts_each_short_window_like_the_15_day_one():
    df, dirs = _walk()
    cuts = _cuts()
    got = at.backtest_strategy(KEY, df, 5.0, dirs=dirs, sizing="flat", recent_windows=cuts)
    log = got["log"]
    for d, cut in cuts.items():
        late = [t for t in log if (t["exit_minute_ms"] or _ms(t["exit time"])) >= cut]
        assert 0 < len(late) < len(log), f"the fixture must put exits on both sides of {d}d"
        rec = got["recents"][d]
        assert rec["trades"] == len(late)
        assert rec["wins"] == sum(t["pnl $"] > 0 for t in late)
        assert rec["profit"] == pytest.approx(sum(t["pnl $"] for t in late), abs=0.02)
    # a longer window holds at least what a shorter one does
    n = [got["recents"][d]["trades"] for d in br.SHORT_DAYS]
    assert n == sorted(n)


def test_without_the_windows_the_result_is_unchanged():
    df, dirs = _walk()
    a = at.backtest_strategy(KEY, df, 5.0, dirs=dirs, sizing="flat")
    b = at.backtest_strategy(KEY, df, 5.0, dirs=dirs, sizing="flat", recent_windows=_cuts())
    assert "recents" not in a
    b.pop("recents")
    assert a == b


def test_the_15_day_count_and_the_short_ones_come_from_one_walk():
    df, dirs = _walk()
    cut15 = H0 + 250 * HOUR
    alone = at.backtest_strategy(KEY, df, 5.0, dirs=dirs, sizing="flat", recent_from_ms=cut15)
    both = at.backtest_strategy(KEY, df, 5.0, dirs=dirs, sizing="flat", recent_from_ms=cut15,
                                recent_windows=_cuts())
    assert both["recent"] == alone["recent"]
    assert set(both["recents"]) == set(br.SHORT_DAYS)


def test_the_row_fields_carry_every_window():
    assert br.SHORT_DAYS == (1, 2, 3, 4)
    assert br.RECENT_WINDOWS == (1, 2, 3, 4, 15)
    assert br.recent_keys(2) == ("t2", "w2", "p2")
    assert br.recent_keys(15) == br.RECENT_FIELDS == ("t15", "w15", "p15")
    with pytest.raises(ValueError):
        br.recent_keys(7)
    r = {"recent": {"trades": 12, "wins": 9, "profit": 3.456},
         "recents": {d: {"trades": d, "wins": d - 1, "profit": d + .004} for d in br.SHORT_DAYS}}
    assert br.recent_fields(r) == {
        "t15": 12, "w15": 9, "p15": 3.46,
        "t1": 1, "w1": 0, "p1": 1.0, "t2": 2, "w2": 1, "p2": 2.0,
        "t3": 3, "w3": 2, "p3": 3.0, "t4": 4, "w4": 3, "p4": 4.0}
    # the 15-day count stays the LAST-but-the-short-ones: recent_measured reads
    # a file's tail for "t15", and the short keys follow it
    assert list(br.recent_fields(r))[:3] == ["t15", "w15", "p15"]
    assert br.recent_fields({}) == {}


def test_the_shard_asks_for_the_short_windows_on_every_v2_row():
    src = " ".join((ROOT / ".github/scripts/sweep_shard.py").read_text(encoding="utf-8").split())
    assert ("recent_windows=({d: int(ts[-1]) - d * 86_400_000 for d in br.SHORT_DAYS}"
            in src)
    assert "**br.recent_fields(r)" in src


# ------------------------------------------------------------------ the index
def _db(tmp_path, rows):
    from tradingagents import rows_index as ri
    path = tmp_path / "rows.db"
    con = sqlite3.connect(path)
    con.executescript(ri._SCHEMA)
    for r in rows:
        con.execute(f"INSERT INTO rows ({','.join(ri.COLS)},monthly,pair) VALUES "
                    f"({','.join('?' * (len(ri.COLS) + 2))})", ri._values(r, f"{r['coin']}-{r['tf']}"))
    con.commit()
    con.close()
    return path


def _row(coin, t2=None, w2=None, tp=1.2, sl=1.0, trades=100, wins=50, sizing="flat", **more):
    r = {"coin": coin, "tf": "15m", "signal": "macddiv", "th": 0.0, "sl": sl, "tp": tp,
         "sizing": sizing, "trades": trades, "wins": wins, "losses": trades - wins,
         "winrate": 100 * wins / trades, "profit": 1.0, "res": "1m",
         "t15": 60, "w15": 40, "p15": 2.0}
    if t2 is not None:
        r.update(t2=t2, w2=w2, p2=1.5)
    r.update(more)
    return r


def test_the_index_files_every_short_window():
    from tradingagents import rows_index as ri
    for d in br.SHORT_DAYS:
        t, w, p = br.recent_keys(d)
        assert {t, w, p} <= set(ri.COLS)
        assert (t, "INTEGER") in ri.LATE_COLUMNS and (w, "INTEGER") in ri.LATE_COLUMNS
        assert (p, "REAL") in ri.LATE_COLUMNS


def test_the_index_finds_rows_by_their_last_2_days_only(tmp_path):
    from tradingagents import rows_index as ri
    db = _db(tmp_path, [
        _row("KII", 32, 27),                  # 84% on 32 trades in 2 days: in
        _row("VUG", 32, 25),                  # 78%: out
        _row("GPN", 29, 29),                  # 100% on 29: out (30+)
        _row("OLD", wins=95),                 # 95% over 30 days, never measured on 2: out
        _row("WID", 40, 39, tp=1.0, sl=1.0),  # TP not wider than SL: out
        _row("CAP", 40, 39, tp=3.0, sl=2.5),  # stop over the 2% cap: out
        _row("MAR", 40, 39, sizing="martingale"),
    ])
    got = ri.recent_rows(min_trades=30, min_winrate=80.0, max_sl=2.0, days=2, db_path=db)
    assert [r["coin"] for r in got] == ["KII"]
    # the 15-day search is what it always was
    got15 = ri.recent_rows(min_trades=50, min_winrate=60.0, max_sl=2.0, db_path=db)
    assert {r["coin"] for r in got15} == {"KII", "VUG", "GPN", "OLD"}
    with pytest.raises(ValueError):
        ri.recent_rows(min_trades=30, min_winrate=80.0, days=7, db_path=db)


def test_an_older_table_answers_no_rows_never_an_error(tmp_path):
    """A table filed before the columns existed has no t2: nothing matches."""
    from tradingagents import rows_index as ri
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    old_cols = [c for c in ri.COLS if not re.fullmatch(r"[twp][1-4]", c)]
    con.execute(f"CREATE TABLE rows ({', '.join(old_cols)}, monthly TEXT, pair TEXT NOT NULL)")
    con.commit()
    con.close()
    assert ri.recent_rows(min_trades=30, min_winrate=80.0, days=2, db_path=db) == []


def test_a_writer_on_an_older_table_adds_the_short_columns_first(tmp_path):
    from tradingagents import rows_index as ri
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    old_cols = [c for c in ri.COLS if not re.fullmatch(r"[twp](1|2|3|4|15)", c)]
    con.execute(f"CREATE TABLE rows ({', '.join(old_cols)}, monthly TEXT, pair TEXT NOT NULL)")
    ri._late_columns(con)
    have = {r[1] for r in con.execute("PRAGMA table_info(rows)")}
    for d in br.RECENT_WINDOWS:
        assert set(br.recent_keys(d)) <= have
    con.execute(f"INSERT INTO rows ({','.join(ri.COLS)},monthly,pair) VALUES "
                f"({','.join('?' * (len(ri.COLS) + 2))})", ri._values(_row("KII", 32, 27), "KII-15m"))


# ---------------------------------------------------------------- the watcher
def test_a_room_switches_on_by_a_measured_window_and_off_by_its_judge_window():
    assert [wc.window_of({"window_days": d}) for d in (1, 2, 3, 4, 15, 30)] == [1, 2, 3, 4, 15, 30]
    assert wc.window_of({"window_days": 7}) == 30, "an unmeasured window is the store's"
    # judge_days 0 (every room before Oct 07, 2026) is the switch-on window
    assert wc.judge_of({"window_days": 15}) == 15
    assert wc.judge_of({"window_days": 2, "judge_days": 30}) == 30
    assert wc.judge_of({"window_days": 2, "judge_days": 0}) == 2


def test_a_2_day_room_reads_the_2_day_figures_never_the_30():
    r = _row("KII", 32, 27)
    f = wc._fresh("KII", "15m", r, 0.0, 2)
    assert (f["trades"], f["wins"], f["winrate"], f["profit"], f["window_days"]) == \
        (32, 27, 84.38, 1.5, 2)
    f30 = wc._fresh("KII", "15m", r, 0.0, 30)
    assert (f30["trades"], f30["winrate"], f30["window_days"]) == (100, 50.0, 30)
    old = wc._fresh("OLD", "15m", _row("OLD", wins=95), 0.0, 2)
    assert old["unmeasured"] and old["trades"] == 0, "not measured is not a pass"
    zero = wc._fresh("ZRO", "15m", _row("ZRO", 0, 0), 0.0, 2)
    assert not zero.get("unmeasured") and zero["trades"] == 0, "measured at zero is zero"


def test_the_watcher_takes_only_windows_a_row_is_measured_over(tmp_path, monkeypatch):
    from tradingagents import strategy_watcher as sw
    monkeypatch.setattr(sw, "_state_path", lambda: tmp_path / "w.json")
    monkeypatch.setattr(sw, "_log_path", lambda: tmp_path / "w.jsonl")
    monkeypatch.setattr(at, "load_settings", lambda: {})
    for d in (1, 2, 3, 4, 15, 30):
        sw.set_cfg({"window_days": d})
        assert sw.cfg_of()["window_days"] == d
    with pytest.raises(ValueError):
        sw.set_cfg({"window_days": 7})
    sw.set_cfg({"window_days": 2, "judge_days": 30})
    c = sw.cfg_of()
    assert (c["window_days"], c["judge_days"]) == (2, 30)
    assert sw.status()["cfg"]["judge_days"] == 30, "the screen reads it"
    with pytest.raises(ValueError):
        sw.set_cfg({"judge_days": 7})
    # the same window twice is the room's one window
    sw.set_cfg({"window_days": 30, "judge_days": 30})
    assert sw.cfg_of()["judge_days"] == 0


def test_the_words_say_one_day_and_the_switch_off_window():
    from tradingagents import watcher_policy as wp
    assert wp.window_words({"window_days": 1}) == "1 day"
    assert wp.window_words({"window_days": 2}) == "2 days"
    cfg = {**wp.DEFAULTS, "window_days": 2, "judge_days": 30, "on_winrate": 80.0,
           "off_winrate": 80.0}
    row = {"winrate": 76.0, "tp": 1.2, "sl": 1.0}
    assert wp.judge({"id": "X"}, row, cfg) == \
        "its last-30-days win rate fell to 76%, under 80%"
    # a 15-day room says what it always said
    assert wp.judge({"id": "X"}, row, {**cfg, "window_days": 15, "judge_days": 0}) == \
        "its last-15-days win rate fell to 76%, under 80%"
    few = {"tp": 1.2, "sl": 1.0, "winrate": 100.0, "trades": 12, "profit": 1.0}
    assert wp.passes_on(few, {**cfg, "min_trades": 30, "window_days": 1}) == \
        "12 trades in 1 day, fewer than 30"


def _room_cfg(**more):
    from tradingagents import strategy_watcher as sw
    return {**sw.wp.DEFAULTS, "window_days": 2, "judge_days": 30, "on_winrate": 80.0,
            "off_winrate": 80.0, "min_trades": 30, "tp_rule": ">", "max_sl": 2.0,
            "raw": True, "max_new_per_day": 0, "max_slots": 0, "max_per_coin": 0,
            "cooldown_days": 0, **more}


def _in_file(coin, *, t2, w2, trades, wins):
    return {"coin": coin, "tf": "15m", "signal": "macddiv", "th": 0.0, "sl": 1.0, "tp": 1.2,
            "sizing": "flat", "trades": trades, "wins": wins, "losses": trades - wins,
            "winrate": round(100 * wins / trades, 2), "profit": 3.0, "gate": "ok",
            "t2": t2, "w2": w2, "p2": 1.0}


def test_the_switch_off_reads_the_30_day_figure_of_a_2_day_room(monkeypatch):
    """Running rows of a 2-day room: one strong for 2 days but 76% over 30 is
    switched off; one weak for 2 days but 85% over 30 stays on."""
    from tradingagents import strategy_watcher as sw
    files = {"KII": _in_file("KII", t2=32, w2=30, trades=100, wins=76),
             "VUG": _in_file("VUG", t2=32, w2=19, trades=100, wins=85)}
    key = "macddiv_15m_sl1tp12"
    ws = {f"{key}|{c}_USDT": {"id": f"ID{c}", "coin": c, "tf": "15m", "signal": "macddiv",
                              "th": 0.0, "sl": 1.0, "tp": 1.2, "on_at": 0.0} for c in files}
    settings = {"strategies": [key], "strategy_coins": {key: [f"{c}_USDT" for c in files]},
                "strategy_books": {s: ["paper"] for s in ws}, "watcher_slots": ws}
    monkeypatch.setattr(at, "load_settings", lambda: json.loads(json.dumps(settings)))
    monkeypatch.setattr(sw, "_delisted", lambda syms: set())
    monkeypatch.setattr(wc, "pair_file", lambda coin, tf: Path(__file__))
    monkeypatch.setattr(wc, "matched_rows", lambda coin, tf, wants:
                        {wc._sig(w): files[coin] for w in wants})
    monkeypatch.setattr(wc, "_last_ms", lambda coin, tf: 1_790_000_000_000.0)
    windows = []
    monkeypatch.setattr(sw, "_judged", lambda slot, fresh, now, window=30:
                        windows.append(window) or fresh)
    out: list = []
    gone = sw._off_pass(0.0, _room_cfg(), {}, False, out)
    assert gone == [f"{key}|KII_USDT"]
    assert [d["why"] for d in out if d["action"] == "off"] == \
        ["#IDKII KII 15m macddiv TP 1.2% / SL 1.0% — its last-30-days win rate fell to "
         "76%, under 80%"]
    assert set(windows) == {30}, "judged on the DEMO 30 DAYS figure"


def test_switch_on_leaves_out_a_row_the_hourly_check_would_drop_at_once(monkeypatch):
    """RCA-2026-10-01-B across two windows: KII passes the 2-day line AND its
    30 days; VUG passes the 2-day line but is 70% over 30 — the hourly
    switch-off would take it off at once, so it is never switched on, and the
    status line says so. GPN has 20 trades in 2 days: under the 30."""
    from tradingagents import strategy_watcher as sw
    files = {"KII": _in_file("KII", t2=32, w2=30, trades=100, wins=85),
             "VUG": _in_file("VUG", t2=32, w2=30, trades=100, wins=70),
             "GPN": _in_file("GPN", t2=20, w2=20, trades=100, wins=90)}
    listed = [wc._fresh(c, "15m", r, 0.0, 2) for c, r in files.items()]
    monkeypatch.setattr(sw, "_candidates", lambda cfg, now: {
        "rows": listed, "why": "3 row(s) in the Backtest v2 table meet the criteria"})
    monkeypatch.setattr(at, "load_settings", lambda: {})
    monkeypatch.setattr(sw, "_delisted", lambda syms: set())
    monkeypatch.setattr(wc, "matched_rows", lambda coin, tf, wants:
                        {wc._sig(w): files[coin] for w in wants})
    monkeypatch.setattr(wc, "_last_ms", lambda coin, tf: 1_790_000_000_000.0)
    windows = []
    monkeypatch.setattr(sw, "_judged", lambda slot, fresh, now, window=30:
                        windows.append(window) or fresh)
    picked: list = []

    def _try(picks, now, st, act, out, settings, ws, arm, refused):
        picked.extend(p["row"]["coin"] for p in picks)
        refused.update(p["row"]["id"] for p in picks)
    monkeypatch.setattr(sw, "_try_picks", _try)
    st: dict = {}
    assert sw._on_pass(0.0, _room_cfg(), st, False, []) == ""
    assert picked == ["KII"]
    # the switch-on reads the measured 2 days; only the switch-off's 30 days go
    # through the DEMO figure (final review, finding 1)
    assert sorted(set(windows)) == [30]
    assert st["last_candidates"] == (
        "3 row(s) in the Backtest v2 table meet the criteria — 1 pass every rule on their "
        "own result file (1 fail one, most often trades in days, fewer than) · 1 pass "
        "the 2-day line but the hourly check would switch them off at once (its "
        "last-30-days win rate fell to 70%, under 80%)")


def test_a_one_window_room_judges_once(monkeypatch):
    """A 15-day room: the switch-on reads one window, as it always did."""
    from tradingagents import strategy_watcher as sw
    files = {"KII": {**_in_file("KII", t2=None, w2=None, trades=100, wins=85),
                     "t15": 60, "w15": 50, "p15": 2.0}}
    listed = [wc._fresh("KII", "15m", files["KII"], 0.0, 15)]
    monkeypatch.setattr(wc, "matched_rows", lambda coin, tf, wants:
                        {wc._sig(w): files[coin] for w in wants})
    monkeypatch.setattr(wc, "_last_ms", lambda coin, tf: 1_790_000_000_000.0)
    windows = []
    monkeypatch.setattr(sw, "_judged", lambda slot, fresh, now, window=30:
                        windows.append(window) or fresh)
    seen = sw._as_the_off_check_sees(listed, 0.0, _room_cfg(window_days=15, judge_days=0))
    assert windows == [15] and "off_row" not in seen[0]


def test_a_short_window_room_waits_for_its_own_count(tmp_path, monkeypatch):
    """The files and the table must carry `t2` itself — `t15` is not enough."""
    import types
    rows = tmp_path / "rows"
    rows.mkdir()
    only15 = dict(_row("KII"))                                 # t15, no t2
    (rows / "KII-15m.json").write_text(json.dumps([only15]))
    monkeypatch.setattr(wc, "stores", types.SimpleNamespace(
        V2=types.SimpleNamespace(home=tmp_path, rows_db=tmp_path / "rows.db")))
    called = []
    # the 1-4 day rooms search through ONE shared pass (recent_rows_any)
    wc._SHORT_PASS.clear()
    monkeypatch.setattr("tradingagents.rows_index.recent_rows_any",
                        lambda **k: called.append(k) or [])
    cfg = {"min_trades": 30, "on_winrate": 80.0, "max_sl": 2.0, "window_days": 2}
    got = wc._raw_recent(cfg)
    assert got["not_ready"] and not called and "last-2-day count" in got["why"]
    (rows / "VUG-15m.json").write_text(json.dumps([_row("VUG", 32, 27)]))
    _file_into_table(tmp_path, rows, cols=("t15",))
    got = wc._raw_recent(cfg)
    assert got["not_ready"] and not called, "the table has t15 but not t2"
    _file_into_table(tmp_path, rows, cols=("t15", "t2"))
    got = wc._raw_recent(cfg)
    assert not got.get("not_ready") and called and called[0]["days_list"] == br.SHORT_DAYS
    assert got["why"] == "0 row(s) in the Backtest v2 table meet the criteria on their last 2 days"
    # a 1-day room says "1 day"
    got = wc._raw_recent({**cfg, "window_days": 1})
    assert got["not_ready"] and "last-1-day count" in got["why"]


def _file_into_table(home, rows, *, cols, values=True):
    """A rows.db whose `pairs` table records every pair file at its current
    mtime/size, each pair with one row; `values=False` files them the way a
    process on the code before the columns does — the column there, NULL."""
    db = home / "rows.db"
    if db.exists():
        db.unlink()
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE rows (pair TEXT" + "".join(f", {c} INTEGER" for c in cols) + ")")
    con.execute("CREATE TABLE pairs (pair TEXT PRIMARY KEY, mtime REAL, size INTEGER)")
    for f in rows.glob("*.json"):
        st = f.stat()
        con.execute("INSERT INTO pairs VALUES (?,?,?)", (f.stem, st.st_mtime, st.st_size))
        con.execute(f"INSERT INTO rows VALUES ({', '.join('?' * (len(cols) + 1))})",
                    (f.stem, *([32] * len(cols) if values else [None] * len(cols))))
    con.commit()
    con.close()


def test_a_column_full_of_nothing_is_not_ready(tmp_path, monkeypatch):
    """The 2-day column exists (a process on the new code added it) while the
    newest pairs were filed by one on the old code, NULL there: a search now
    finds nothing and spends the 2-day room's pass for the day. Ready needs a
    value in the table, not a column."""
    import types
    rows = tmp_path / "rows"
    rows.mkdir()
    (rows / "VUG-15m.json").write_text(json.dumps([_row("VUG", 32, 27)]))
    monkeypatch.setattr(wc, "stores", types.SimpleNamespace(
        V2=types.SimpleNamespace(home=tmp_path, rows_db=tmp_path / "rows.db")))
    _file_into_table(tmp_path, rows, cols=("t15", "t2"), values=False)
    assert not wc.recent_filed(days=2)
    _file_into_table(tmp_path, rows, cols=("t15", "t2"))
    assert wc.recent_filed(days=2)


# --------------------------------------------------------- Backtest a room
def _local_ms(y, m, d, h=0):
    import datetime as dt
    return int(dt.datetime(y, m, d, h).timestamp() * 1000)


def _replay_cfg(judge_days):
    from tradingagents import watcher_policy as wp
    return {**wp.DEFAULTS, "window_days": 2, "judge_days": judge_days, "on_winrate": 80.0,
            "off_winrate": 80.0, "min_trades": 30, "tp_rule": ">", "max_sl": 2.0,
            "raw": True, "max_new_per_day": 0, "max_slots": 0, "max_per_coin": 0,
            "cooldown_days": 0}


def _replay_combo(cid, exits):
    """exits: (exit_ms, pnl); each trade entered 30 minutes before its exit."""
    return {"id": cid, "coin": "VUG", "tf": "15m", "signal": "willr14", "th": 0.0,
            "sl": 1.2, "tp": 2.0, "group": "classic", "gate": "ok",
            "trades": [[x - 1_800_000, x, p, 1] for x, p in exits]}


def test_the_replay_never_switches_on_what_its_30_days_would_drop():
    """40 losses in the first week of September, then 32 wins inside two
    days: the 2-day line passes, the 30 days read 44% — the live room would
    never switch it on, and neither may its replay."""
    from tradingagents import watcher_replay as wr
    sep1, sep9 = _local_ms(2026, 9, 1), _local_ms(2026, 9, 9, 1)
    exits = ([(sep1 + i * 4 * HOUR, -1.0) for i in range(40)]
             + [(sep9 + i * HOUR, 0.9) for i in range(32)])
    combo = _replay_combo("GUARD001", exits)
    start, end = _local_ms(2026, 9, 9), _local_ms(2026, 9, 12)
    sched = wr.live_schedule(start, end, True)
    two_only = wr.simulate([combo], start_ms=start, end_ms=end, cfg=_replay_cfg(0),
                           schedule=sched)
    assert [e["action"] for e in two_only["events"]][:1] == ["on"], \
        "the fixture must pass the 2-day line to prove anything"
    got = wr.simulate([combo], start_ms=start, end_ms=end, cfg=_replay_cfg(30),
                      schedule=sched)
    assert got["events"] == []


def test_the_replay_switches_a_2_day_room_off_by_its_30_days_only():
    """Switched on after a strong week; then two days of half wins pull its
    2-day figure to about 62% while its 30 days stay over 90%: the 2-day room
    keeps it (it is switched off on 30 days), a room judging on 2 days would
    not."""
    from tradingagents import watcher_replay as wr
    sep2, sep9, sep11 = (_local_ms(2026, 9, 2), _local_ms(2026, 9, 9, 8),
                         _local_ms(2026, 9, 11, 1))
    exits = ([(sep2 + i * HOUR, 0.9) for i in range(168)]
             + [(sep9 + i * HOUR, 0.9) for i in range(40)]
             + [(sep11 + i * HOUR, 0.9 if i % 2 else -1.5) for i in range(47)])
    combo = _replay_combo("JUDGE030", exits)
    start, end = _local_ms(2026, 9, 10), _local_ms(2026, 9, 13)
    sched = wr.live_schedule(start, end, True)
    got = wr.simulate([combo], start_ms=start, end_ms=end, cfg=_replay_cfg(30),
                      schedule=sched)
    assert [e["action"] for e in got["events"]] == ["on"]
    two = wr.simulate([combo], start_ms=start, end_ms=end, cfg=_replay_cfg(0),
                      schedule=sched)
    offs = [e["why"] for e in two["events"] if e["action"] == "off"]
    assert offs and offs[0].startswith("its last-2-days win rate fell to")


def test_a_replayed_switch_off_shows_the_figures_it_was_judged_on():
    """The event row of a switch-off carries the 30-day figures the 2-day
    room's switch-off read — never the 2-day ones beside a 30-day reason."""
    from tradingagents import room_replay as rr
    from tradingagents import watcher_replay as wr
    sep2, sep9 = _local_ms(2026, 9, 2), _local_ms(2026, 9, 9, 8)
    exits = ([(sep2 + i * HOUR, -1.0) for i in range(40)]
             + [(sep9 + i * HOUR, 0.9) for i in range(40)])
    book = wr._Book(_replay_combo("ROWS0001", exits))
    at = _local_ms(2026, 9, 11)
    on = rr._event_row(book, {"at": at, "action": "on"}, 2 * DAY, 30 * DAY)
    off = rr._event_row(book, {"at": at, "action": "off"}, 2 * DAY, 30 * DAY)
    assert (on["trades"], on["winrate"]) == (40, 100.0)
    assert (off["trades"], off["winrate"]) == (80, 50.0)


# ------------------------------------------------------------------ the rooms
# the four rooms as built Oct 07, 2026: id -> its switch-on window in days
SHORT_ROOMS = {"99E79CBA": 1, "C7396286": 2, "1D4274C1": 3, "8F0C7926": 4}


def _room_rule_set(days):
    from tradingagents import forecast_rules as fr
    return fr.cfg_of(days, 80.0, 30, ">", 2.0, judge_days=30)


def test_no_existing_id_moves_and_a_second_window_makes_a_new_one():
    from tradingagents import forecast_rules as fr
    base = fr.cfg_of(2, 80.0, 30, ">", 2.0)
    assert fr.rule_id({**base, "judge_days": 0}) == fr.rule_id(base)
    assert fr.rule_id({**base, "judge_days": 2}) == fr.rule_id(base), \
        "the same window twice is one window"
    assert fr.rule_id({**base, "judge_days": 30}) != fr.rule_id(base)
    # ids hashed before Oct 07, 2026 are unchanged
    assert fr.rule_id(fr.cfg_of(30, 80.0, 30, ">", 2.0)) == "C2B0F302"
    assert fr.rule_id(fr.cfg_of(15, 70.0, 50, ">", 2.0)) == "1CA782AB"


def test_each_short_window_room_is_its_rule_set_by_id():
    from tradingagents import forecast_rules as fr
    from tradingagents import profiles
    for pid, days in SHORT_ROOMS.items():
        assert fr.rule_id(_room_rule_set(days)) == pid, (pid, days)
        p = profiles.get(pid)
        assert p and p["name"] == f"#{pid}" and not profiles.retired(pid)
        r = p["rules"]
        assert (r["window_days"], r["judge_days"], r["on_winrate"], r["off_winrate"],
                r["min_trades"], r["tp_rule"], r["max_sl"]) == (days, 30, 80.0, 80.0, 30, ">", 2.0)
        assert r["raw"] and not (r["max_new_per_day"] or r["max_slots"] or r["max_per_coin"])
        assert pid in profiles.shown()


def test_a_short_window_room_is_switched_on_by_its_window_and_off_by_30():
    """The room's watcher, seeded from profiles.BUILTIN, reads both."""
    from tradingagents import profiles
    from tradingagents import strategy_watcher as sw
    for pid, days in SHORT_ROOMS.items():
        c = sw.cfg_of({"cfg": dict(profiles.get(pid)["rules"])})
        assert (c["window_days"], c["judge_days"]) == (days, 30)
        assert (wc.window_of(c), wc.judge_of(c)) == (days, 30)


def test_a_room_with_two_windows_reaches_github_with_both():
    """Forecast v2's daily chain sends each room's rules to GitHub as one short
    line; without the switch-off window there, GitHub would forecast the 2-day
    room as switched off on 2 days."""
    from tradingagents import forecast_rules as fr
    c = _room_rule_set(2)
    assert fr.encode(c) == "2:80:80:30:>:2:j30"
    back = fr.decode(fr.encode(c))
    assert back["judge_days"] == 30 and fr.rule_id(back) == fr.rule_id(c)
    plain = fr.cfg_of(15, 70.0, 50, ">", 2.0)
    assert fr.encode(plain) == "15:70:70:50:>:2", "every existing line is unchanged"
    assert fr.rule_id(fr.decode("15:70:70:50:>:2")) == fr.rule_id(plain)
    rooms = fr.decode_rooms(fr.encode_rooms({"C7396286": c}))
    assert rooms["C7396286"]["judge_days"] == 30


def test_the_daily_forecast_takes_the_rooms_switch_off_window(monkeypatch):
    from tradingagents import forecast_v2_daily as fd
    from tradingagents import profiles
    from tradingagents import room_stats as rs
    from tradingagents import strategy_watcher as sw
    monkeypatch.setattr(rs, "rules_of", lambda pid: sw.cfg_of(
        {"cfg": dict((profiles.get(pid) or {}).get("rules") or {"on_winrate": 90.0,
                                                               "min_trades": 20})}))
    got = fd.room_rules()
    assert got["C7396286"]["judge_days"] == 30 and got["C7396286"]["window_days"] == 2
    assert not got["CC94D9FB"].get("judge_days"), "a one-window room stays one window"


def test_the_words_name_both_windows():
    from tradingagents import forecast_rules as fr
    from tradingagents import room_stats as rs
    assert fr.words(_room_rule_set(2)) == ("80% wins, 30+ trades in 2 days, TP wider than "
                                           "SL, stop 2% or tighter, switched off on its "
                                           "last 30 days")
    assert fr.words(_room_rule_set(1)).startswith("80% wins, 30+ trades in 1 day,")
    assert fr.deployable(_room_rule_set(2)) == (True, "")
    assert not fr.deployable(fr.cfg_of(7, 80.0, 30, ">", 2.0))[0], "7 days is not measured"
    cfg = {"window_days": 2, "judge_days": 30, "on_winrate": 80.0, "off_winrate": 80.0,
           "min_trades": 30, "tp_rule": ">", "max_sl": 2.0}
    assert rs.rules_text(cfg).startswith("on by its last 2 days, off by its last 30 days · ")
    assert rs.rules_text({**cfg, "judge_days": 0, "window_days": 15}).startswith(
        "judged on 15 days · ")


def test_the_screen_prints_both_windows():
    """The rules popup and the Watcher panel read `judge_days`; the replay
    page counts a day short against the longer window."""
    panel = (ROOT / "webapp/src/components/trade/WatcherPanel.tsx").read_text(encoding="utf-8")
    assert "judge_days" in panel
    assert "judged on the DEMO 30 DAYS figure" in panel
    assert "switched on by its last" in panel
    box = (ROOT / "webapp/src/components/trade/SmartWatcherBox.tsx").read_text(encoding="utf-8")
    assert "judge_days" in box
    rf = (ROOT / "webapp/src/components/forecast/RoomForecasts.tsx").read_text(encoding="utf-8")
    assert "judge_days" in rf


def test_the_four_rooms_share_one_pass_over_the_table(tmp_path, monkeypatch):
    """One pass over the 16 GB Backtest v2 table took 283 s on this PC
    (Oct 07, 2026). The 1-4 day rooms share their floors, so the first room's
    pass answers all four: one search, each room then reads its own window."""
    import types
    from tradingagents import rows_index as ri
    db = _db(tmp_path, [
        _row("KII", 32, 27, t1=31, w1=30, p1=1.0, t4=60, w4=50, p4=2.0),   # 1d 96.8%, 2d 84%
        _row("VUG", 32, 20, t1=10, w1=10, p1=1.0, t4=64, w4=60, p4=3.0),   # 4d only
        _row("GPN", 12, 12, t1=5, w1=5, p1=1.0, t4=20, w4=20, p4=1.0),     # none: few trades
    ])
    # THE FILE'S TIME, PINNED: Windows can report a just-closed file's write
    # time a moment late, so a stamp read straight after the write may differ
    # from the next one and look like a change (this test failed 2 runs in 5)
    import os
    os.utime(db, ns=(1_790_000_000_000_000_000, 1_790_000_000_000_000_000))
    monkeypatch.setattr(wc, "stores", types.SimpleNamespace(
        V2=types.SimpleNamespace(home=tmp_path, rows_db=db)))
    monkeypatch.setattr(wc, "recent_measured", lambda sample=5, days=15: True)
    monkeypatch.setattr(wc, "recent_filed", lambda sample=5, days=15: True)
    wc._SHORT_PASS.clear()
    passes = []
    real = ri.recent_rows_any
    monkeypatch.setattr(ri, "recent_rows_any", lambda **k: passes.append(k) or real(**k))
    cfg = {"min_trades": 30, "on_winrate": 80.0, "max_sl": 2.0, "tp_rule": ">"}
    got = {d: sorted(r["coin"] for r in wc._raw_recent({**cfg, "window_days": d})["rows"])
           for d in (1, 2, 3, 4)}
    assert got == {1: ["KII"], 2: ["KII"], 3: [], 4: ["KII", "VUG"]}
    assert len(passes) == 1, "one pass for the four rooms"
    # each room's own figures, never another window's
    two = wc._raw_recent({**cfg, "window_days": 2})["rows"][0]
    assert (two["trades"], two["wins"], two["window_days"]) == (32, 27, 2)
    # other floors are another search
    wc._raw_recent({**cfg, "window_days": 2, "on_winrate": 70.0})
    assert len(passes) == 2
    wc._raw_recent({**cfg, "window_days": 2})            # the rooms' floors again
    assert len(passes) == 3
    wc._raw_recent({**cfg, "window_days": 3})
    assert len(passes) == 3, "the same table and floors: no second pass"
    # and a table that changed is searched again
    con = sqlite3.connect(db)
    con.execute("DELETE FROM rows WHERE coin = 'VUG'")
    con.commit()
    con.close()
    os.utime(db, ns=(1_790_000_001_000_000_000, 1_790_000_001_000_000_000))
    assert [r["coin"] for r in wc._raw_recent({**cfg, "window_days": 4})["rows"]] == ["KII"]
    assert len(passes) == 4


def test_the_shared_pass_asks_for_every_short_window_at_its_floor(tmp_path):
    from tradingagents import rows_index as ri
    db = _db(tmp_path, [
        _row("KII", 32, 27),                                   # 2-day only
        _row("VUG", t1=31, w1=30, p1=1.0),                     # 1-day only
        _row("OLD"),                                           # never measured short
        _row("WID", 40, 39, tp=1.0, sl=1.0),                   # TP not wider than SL
    ])
    got = ri.recent_rows_any(days_list=br.SHORT_DAYS, min_trades=30, min_winrate=80.0,
                             max_sl=2.0, db_path=db)
    assert sorted(r["coin"] for r in got) == ["KII", "VUG"]
    with pytest.raises(ValueError):
        ri.recent_rows_any(days_list=(2, 7), min_trades=30, min_winrate=80.0, db_path=db)


# ------------------------------------------------- the final review's fixes
def test_switch_on_reads_the_measured_days_not_a_figure_cut_by_the_backtests_age(monkeypatch):
    """Review finding 1: `rolling30.figure` counts back from NOW, `t1` from the
    backtest's last candle. A room running the same slot elsewhere leaves a
    rolling30 record, and at a midnight pass 15 hours after the backtest ended
    the 1-day figure read 16 trades where the row measured 36 — refused with
    "16 trades in 1 day, fewer than 30" only because another room ran it. The
    switch-on reads the measured count; only the switch-off reads the DEMO
    figure."""
    from tradingagents import strategy_watcher as sw
    row = {**_in_file("KII", t2=None, w2=None, trades=100, wins=90),
           "t1": 36, "w1": 32, "p1": 2.0}
    listed = [wc._fresh("KII", "15m", row, 0.0, 1)]
    monkeypatch.setattr(wc, "matched_rows", lambda coin, tf, wants:
                        {wc._sig(w): row for w in wants})
    monkeypatch.setattr(wc, "_last_ms", lambda coin, tf: 1_790_000_000_000.0)
    # what rolling30 answers for a slot another room runs: the window cut short
    cut = {"trades": 16, "wins": 15, "losses": 1, "winrate": 93.75, "pnl": 1.0,
           "from_backtest": 16, "from_practice": 0}
    monkeypatch.setattr("tradingagents.rolling30.figure",
                        lambda slot, now=None, exits=None, window_ms=0:
                        cut if window_ms == 86_400_000 else
                        {**cut, "trades": 100, "wins": 90, "winrate": 90.0})
    seen = sw._as_the_off_check_sees(listed, 1_790_050_000.0, _room_cfg(window_days=1))
    assert (seen[0]["trades"], seen[0]["wins"]) == (36, 32)
    assert not sw.wp.passes_on(seen[0], _room_cfg(window_days=1))
    assert seen[0]["off_row"]["trades"] == 100, "the switch-off still reads the DEMO 30 days"


def test_a_short_window_on_an_old_backtest_is_not_this_weeks(monkeypatch):
    """Review finding 5: a pair whose backtest ended days ago would offer "its
    last 1 day" from a day that ended long before. Past `fresh_hours` (36) a
    1-4 day room skips it and says how many."""
    from tradingagents import strategy_watcher as sw
    now = 1_790_100_000.0                       # seconds
    files = {"KII": {**_in_file("KII", t2=32, w2=30, trades=100, wins=90)},
             "VUG": {**_in_file("VUG", t2=32, w2=30, trades=100, wins=90)}}
    last = {"KII": (now - 10 * 3600) * 1000, "VUG": (now - 60 * 3600) * 1000}
    listed = [wc._fresh(c, "15m", r, 0.0, 2) for c, r in files.items()]
    monkeypatch.setattr(sw, "_candidates", lambda cfg, now: {
        "rows": listed, "why": "2 row(s) in the Backtest v2 table meet the criteria"})
    monkeypatch.setattr(at, "load_settings", lambda: {})
    monkeypatch.setattr(sw, "_delisted", lambda syms: set())
    monkeypatch.setattr(wc, "matched_rows", lambda coin, tf, wants:
                        {wc._sig(w): files[coin] for w in wants})
    monkeypatch.setattr(wc, "_last_ms", lambda coin, tf: last[coin])
    monkeypatch.setattr(sw, "_judged", lambda slot, fresh, now, window=30: fresh)
    picked: list = []

    def _try(picks, now, st, act, out, settings, ws, arm, refused):
        picked.extend(p["row"]["coin"] for p in picks)
        refused.update(p["row"]["id"] for p in picks)
    monkeypatch.setattr(sw, "_try_picks", _try)
    st: dict = {}
    sw._on_pass(now, _room_cfg(), st, False, [])
    assert picked == ["KII"]
    assert ("1 skipped: its backtest ends more than 36 hours ago, so its last 2 days "
            "are not the latest") in st["last_candidates"]
    # a 15-day room is not touched by this
    seen = sw._as_the_off_check_sees(listed, now, _room_cfg(window_days=15, judge_days=0))
    assert not any("stale_h" in r for r in seen)


def test_the_research_never_measures_a_two_window_room_as_one(tmp_path, monkeypatch):
    """Review finding 3: prompt 4's round 1 adds every room's rules through
    its six dials, which have no `judge_days` — it would research "2 days,
    switched off on 2" under another id, and carrying the window instead
    makes raw_trades refuse. A two-window room is left out of round 1."""
    from tradingagents import room_strategies as rst
    monkeypatch.setenv("ROOM_STRATEGIES_HOME", str(tmp_path / "store"))
    rst._KEPT.clear()
    got = rst.round1()
    assert not [c for c in got if int(c["window_days"]) in br.SHORT_DAYS]
    rst._KEPT.clear()


def test_the_forecast_filter_names_every_window():
    """Review finding 4: the empty choice read "15 or 30 days" while the base
    stage now holds the 1-4 day rooms' rule sets."""
    src = (ROOT / "webapp/src/components/forecast/ForecastV2.tsx").read_text(encoding="utf-8")
    block = src.split('aria-label="days judged"', 1)[1].split("</select>", 1)[0]
    assert "15 or 30 days" not in block and "any window" in block
    for d in (1, 2, 3, 4, 15, 30):
        assert f"<option value={{{d}}}>" in block, d
    api = (ROOT / "tradingagents/forecast_v2_api.py").read_text(encoding="utf-8")
    assert "switched on by its last" in api


def test_one_day_reads_that_day():
    """Review finding 6: "30+ trades in those 1 day"."""
    panel = (ROOT / "webapp/src/components/trade/WatcherPanel.tsx").read_text(encoding="utf-8")
    assert "in those ${d(days)}" not in panel
    assert 'days === 1 ? "in that day"' in panel


def test_an_old_row_in_a_fresh_file_is_not_this_weeks(monkeypatch):
    """Found watching the Oct 07, 2026 5:02pm run land: a pair file keeps the
    rows of combinations a later grid no longer measures (ALNYSTOCK-1h: 1,125
    rows measured to 4:00pm today beside 10,017 last measured Oct 06 or
    Sep 29). The pair's watermark is today's, so a row whose OWN `last_ms` is
    a week old would pass a watermark check with "its last 2 days" from a
    week ago. The row's own last bar decides."""
    from tradingagents import strategy_watcher as sw
    now = 1_790_100_000.0
    fresh_pair = (now - 3600) * 1000
    old_row = {**_in_file("KII", t2=32, w2=30, trades=100, wins=90),
               "last_ms": int((now - 7 * 86_400) * 1000)}
    new_row = {**_in_file("VUG", t2=32, w2=30, trades=100, wins=90),
               "last_ms": int((now - 3600) * 1000)}
    files = {"KII": old_row, "VUG": new_row}
    listed = [wc._fresh(c, "15m", r, 0.0, 2) for c, r in files.items()]
    monkeypatch.setattr(wc, "matched_rows", lambda coin, tf, wants:
                        {wc._sig(w): files[coin] for w in wants})
    monkeypatch.setattr(wc, "_last_ms", lambda coin, tf: fresh_pair)
    monkeypatch.setattr(sw, "_judged", lambda slot, fresh, now, window=30: fresh)
    seen = {r["coin"]: r for r in sw._as_the_off_check_sees(listed, now, _room_cfg())}
    assert seen["KII"].get("stale_h") == 168
    assert "stale_h" not in seen["VUG"]
