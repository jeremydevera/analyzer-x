"""The table's rule sets became rooms (operator, Sep 30, 2026: "undeploy my
current live then deploy the table you mentined").

Three of the five judge a row on its LAST 15 DAYS (#55D32617, #B2404C0B,
#6B08FF64). A v2 row carried only 30-day totals, so the engine now counts the
trades that closed in the row's last 15 days (`recent_from_ms`), the shard
writes them as `t15`/`w15`/`p15`, the index files them, and the watcher
judges a 15-day room on them — never on the 30-day totals relabelled.

Candles and exits share ONE clock here (RCA-2026-09-12-A): hour bars from
H0, and `recent_from_ms` sits between two of their exits.
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
from tradingagents import profiles
from tradingagents import watcher_candidates as wc

ROOT = Path(__file__).resolve().parents[1]
KEY = "t_recent_1h"
H0 = 1_789_516_800_000            # Sep 16, 2026 00:00 UTC
HOUR = 3_600_000


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


def test_the_engine_counts_the_trades_that_closed_in_the_window():
    df, dirs = _walk()
    cut = H0 + 250 * HOUR
    got = at.backtest_strategy(KEY, df, 5.0, dirs=dirs, sizing="flat",
                               recent_from_ms=cut)
    log = got["log"]
    late = [t for t in log if (t["exit_minute_ms"] or _ms(t["exit time"])) >= cut]
    assert 0 < len(late) < len(log), "the fixture must put exits on both sides"
    assert got["recent"]["trades"] == len(late)
    assert got["recent"]["wins"] == sum(t["pnl $"] > 0 for t in late)
    assert got["recent"]["profit"] == pytest.approx(sum(t["pnl $"] for t in late), abs=0.02)


def test_without_the_window_the_result_is_unchanged():
    df, dirs = _walk()
    a = at.backtest_strategy(KEY, df, 5.0, dirs=dirs, sizing="flat")
    b = at.backtest_strategy(KEY, df, 5.0, dirs=dirs, sizing="flat",
                             recent_from_ms=H0 + 250 * HOUR)
    assert "recent" not in a
    b.pop("recent")
    assert a == b


def test_the_row_fields_come_from_the_engine():
    assert br.recent_fields({}) == {}
    assert br.recent_fields({"recent": {"trades": 12, "wins": 9, "profit": 3.456}}) == \
        {"t15": 12, "w15": 9, "p15": 3.46}
    assert br.RECENT_FIELDS == ("t15", "w15", "p15")


def test_the_shard_writes_them_on_every_v2_row():
    src = (ROOT / ".github/scripts/sweep_shard.py").read_text(encoding="utf-8")
    assert "recent_from_ms=(int(ts[-1]) - br.RECENT_DAYS * 86_400_000" in src
    assert "**br.recent_fields(r)" in src


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


def _row(coin, t15, w15, tp=1.2, sl=1.0, trades=100, wins=50, sizing="flat"):
    return {"coin": coin, "tf": "1h", "signal": "macddiv", "th": 0.0, "sl": sl, "tp": tp,
            "sizing": sizing, "trades": trades, "wins": wins, "losses": trades - wins,
            "winrate": 100 * wins / trades, "profit": 1.0, "res": "1m",
            "t15": t15, "w15": w15, "p15": 2.5 if t15 else None}


def test_the_index_finds_rows_by_their_last_15_days_only(tmp_path):
    from tradingagents import rows_index as ri
    db = _db(tmp_path, [
        _row("KII", 50, 36),                 # 72%: in, though 30 days read 50%
        _row("VUG", 50, 34),                 # 68%: out
        _row("GPN", 40, 39),                 # 97% on 40 trades: out (50+)
        _row("OLD", None, None, wins=95),    # 95% on 30 days, never measured on 15: out
        _row("WID", 60, 50, tp=1.0, sl=1.0),  # TP not wider than SL: out
        _row("CAP", 60, 50, tp=3.0, sl=2.5),  # stop over the 2% cap: out
        _row("MAR", 60, 50, sizing="martingale"),
    ])
    got = ri.recent_rows(min_trades=50, min_winrate=70.0, max_sl=2.0, db_path=db)
    assert [r["coin"] for r in got] == ["KII"]


def test_a_15_day_room_reads_the_15_day_figures_never_the_30():
    r = _row("KII", 50, 36)
    f = wc._fresh("KII", "1h", r, 0.0, 15)
    assert (f["trades"], f["wins"], f["winrate"], f["window_days"]) == (50, 36, 72.0, 15)
    f30 = wc._fresh("KII", "1h", r, 0.0, 30)
    assert (f30["trades"], f30["winrate"]) == (100, 50.0)
    old = wc._fresh("OLD", "1h", _row("OLD", None, None, wins=95), 0.0, 15)
    assert old["unmeasured"] and old["trades"] == 0, "not measured is not a pass"


def test_the_watcher_takes_15_or_30_days_and_nothing_else(tmp_path, monkeypatch):
    from tradingagents import strategy_watcher as sw
    monkeypatch.setattr(sw, "_state_path", lambda: tmp_path / "w.json")
    monkeypatch.setattr(sw, "_log_path", lambda: tmp_path / "w.jsonl")
    # never the real settings: loading them merges the operator's recipes
    # into at.STRATEGY_SPECS for every test after this one
    monkeypatch.setattr(at, "load_settings", lambda: {})
    sw.set_cfg({"window_days": 15})
    assert sw.cfg_of()["window_days"] == 15
    sw.set_cfg({"window_days": 30})
    assert sw.cfg_of()["window_days"] == 30
    with pytest.raises(ValueError):
        sw.set_cfg({"window_days": 7})


def test_a_15_day_room_asks_the_15_day_search(monkeypatch):
    from tradingagents import strategy_watcher as sw
    seen = {}
    monkeypatch.setattr(wc, "_raw_recent", lambda cfg: seen.setdefault("r", cfg) and
                        {"rows": [], "asked": 0, "stale": 0, "gone": 0, "why": "x"})
    sw._candidates({**sw.wp.DEFAULTS, "window_days": 15, "raw": False}, 0.0)
    assert seen["r"]["window_days"] == 15


def test_the_rolling_figure_shortens_to_the_rooms_window(monkeypatch):
    from tradingagents import rolling30 as r30
    now = (H0 + 40 * 86_400_000) / 1000
    day = 86_400_000
    same = {"trades": 2, "wins": 1, "profit": 0.0}
    rec = {"end_ms": H0 + 39 * day, "stored": same, "rebuilt": same,
           "trades": [[0, H0 + 20 * day, -1.0], [0, H0 + 30 * day, 1.0]]}
    monkeypatch.setattr(r30, "_load", lambda slot: rec)
    assert r30.figure("s", now=now, exits=[])["trades"] == 2
    assert r30.figure("s", now=now, exits=[], window_ms=15 * day)["trades"] == 1


# ---------------------------------------------------------------- the rooms
TABLE = {"55D32617": (15, 70.0, 50), "4FC03172": (30, 70.0, 50),
         "B2404C0B": (15, 75.0, 50), "6B08FF64": (15, 80.0, 30),
         "CC94D9FB": (30, 80.0, 30)}


def test_each_room_is_its_rule_set_by_id():
    from tradingagents import watcher_research as rs
    for pid, (w, line, n) in TABLE.items():
        rules = profiles.get(pid)["rules"]
        assert (rules["window_days"], rules["on_winrate"], rules["min_trades"]) == (w, line, n)
        grid = {rs.rule_id(c): c for c in rs.scenarios5()}
        c = grid[pid]
        for k in ("on_winrate", "off_winrate", "min_trades", "tp_rule", "window_days",
                  "max_sl", "raw", "max_new_per_day", "max_slots", "max_per_coin"):
            assert rules[k] == c[k], (pid, k)


def test_the_old_rooms_are_retired_and_main_is_not():
    assert not profiles.retired(profiles.MAIN)
    for pid in ("DC57174E", "CC8DC54C", "B52662ED"):
        assert profiles.retired(pid)
    for pid in TABLE:
        assert not profiles.retired(pid)


def test_a_retired_room_switches_nothing_on():
    from tradingagents import strategy_watcher as sw
    with profiles.using("B52662ED"):
        assert sw.mode_of({"mode": "act"}) == "off"
    with profiles.using("55D32617"):
        assert sw.mode_of({"mode": "act"}) == "act"


def test_the_screen_lists_the_same_rooms():
    ts = (ROOT / "webapp/src/lib/api.ts").read_text(encoding="utf-8")
    block = ts.split("export const PROFILES", 1)[1].split("];", 1)[0]
    ids = re.findall(r'id: "([^"]+)"', block)
    # OFF MEANS NO TAB (Oct 01, 2026): a retired room is not on the screen
    assert ids == profiles.shown()
    assert not {"DC57174E", "CC8DC54C", "B52662ED"} & set(ids)


def test_retire_room_takes_off_practice_rows_and_never_real(tmp_path, monkeypatch):
    from tradingagents import strategy_watcher as sw
    settings = {"strategies": ["a", "b"],
                "strategy_coins": {"a": ["KII_USDT", "VUG_USDT"], "b": ["GPN_USDT"]},
                "strategy_books": {"a|KII_USDT": ["paper"], "a|VUG_USDT": ["paper", "real"],
                                   "b": ["paper"]}}
    box = {"s": json.loads(json.dumps(settings))}
    monkeypatch.setattr(at, "load_settings", lambda: json.loads(json.dumps(box["s"])))
    monkeypatch.setattr(at, "save_settings", lambda s: box.__setitem__("s", s))
    monkeypatch.setattr(sw, "_state_path", lambda: tmp_path / "w.json")
    got = sw.retire_room()
    assert got == {"switched_off": 2, "real_kept": ["a|VUG_USDT"]}
    assert box["s"]["strategy_coins"] == {"a": ["VUG_USDT"], "b": []}
    assert json.loads((tmp_path / "w.json").read_text())["mode"] == "off"


def test_a_writer_on_an_older_table_adds_the_columns_first(tmp_path):
    """A job's own filing may never have run ensure() with this code."""
    from tradingagents import rows_index as ri
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    old_cols = [c for c in ri.COLS if c not in ("t15", "w15", "p15")]
    con.execute(f"CREATE TABLE rows ({', '.join(old_cols)}, monthly TEXT, pair TEXT NOT NULL)")
    ri._late_columns(con)
    have = {r[1] for r in con.execute("PRAGMA table_info(rows)")}
    assert {"t15", "w15", "p15"} <= have
    con.execute(f"INSERT INTO rows ({','.join(ri.COLS)},monthly,pair) VALUES "
                f"({','.join('?' * (len(ri.COLS) + 2))})", ri._values(_row("KII", 50, 36), "KII-1h"))


def test_a_15_day_room_waits_for_the_count_instead_of_losing_a_day(tmp_path, monkeypatch):
    """A once-a-day pass that ran before the daily update wrote t15 would
    otherwise switch nothing on until the NEXT day."""
    import types
    rows = tmp_path / "rows"
    rows.mkdir()
    old = {k: v for k, v in _row("KII", 50, 36).items() if k not in br.RECENT_FIELDS}
    (rows / "KII-1h.json").write_text(json.dumps([old]))
    monkeypatch.setattr(wc, "stores", types.SimpleNamespace(
        V2=types.SimpleNamespace(home=tmp_path, rows_db=tmp_path / "rows.db")))
    called = []
    monkeypatch.setattr("tradingagents.rows_index.recent_rows", lambda **k: called.append(k) or [])
    got = wc._raw_recent({"min_trades": 50, "on_winrate": 70.0, "max_sl": 2.0})
    assert got["not_ready"] and not called, "no pass over the table before the count exists"
    (rows / "VUG-1h.json").write_text(json.dumps([_row("VUG", 50, 36)]))
    # THE FILES CARRY IT, THE TABLE DOES NOT YET (RCA-2026-10-01-A): the daily
    # run lands files live, the table is rebuilt only after it comes home.
    # Searching now would spend the day's pass on an empty table.
    got = wc._raw_recent({"min_trades": 50, "on_winrate": 70.0, "max_sl": 2.0})
    assert got["not_ready"] and not called, got
    assert "not yet in the Backtest v2 table" in got["why"]
    _file_into_table(tmp_path, rows, with_t15=False)
    assert wc._raw_recent({"min_trades": 50, "on_winrate": 70.0,
                           "max_sl": 2.0})["not_ready"], "no column, not ready"
    _file_into_table(tmp_path, rows, with_t15=True)
    got = wc._raw_recent({"min_trades": 50, "on_winrate": 70.0, "max_sl": 2.0})
    assert not got.get("not_ready") and called
    # a file written AFTER the table was filed makes it not ready again
    import os
    st = (rows / "VUG-1h.json").stat()
    os.utime(rows / "VUG-1h.json", ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    assert wc._raw_recent({"min_trades": 50, "on_winrate": 70.0,
                           "max_sl": 2.0})["not_ready"]


def _file_into_table(home, rows, *, with_t15):
    """A rows.db whose `pairs` table records every pair file at its current
    mtime/size — what a finished rebuild leaves behind."""
    db = home / "rows.db"
    if db.exists():
        db.unlink()
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE rows (pair TEXT" + (", t15 INTEGER" if with_t15 else "") + ")")
    con.execute("CREATE TABLE pairs (pair TEXT PRIMARY KEY, mtime REAL, size INTEGER)")
    for f in rows.glob("*.json"):
        st = f.stat()
        con.execute("INSERT INTO pairs VALUES (?,?,?)", (f.stem, st.st_mtime, st.st_size))
    con.commit()
    con.close()


def test_the_status_line_says_how_many_pass_every_rule(monkeypatch):
    """RCA-2026-09-30-C: #CC94D9FB printed "1,511 row(s) ... meet the
    criteria" and switched on 539 — the other 972 had TP equal to SL, which
    the index is never asked to exclude (it is asked TP >= SL)."""
    from tradingagents import strategy_watcher as sw

    def row(i, tp, sl):
        return {"id": f"R{i}", "coin": f"C{i}", "tf": "1h", "signal": "macddiv",
                "th": 0.0, "tp": tp, "sl": sl, "winrate": 90.0, "trades": 40,
                "wins": 36, "losses": 4, "profit": 3.0, "gate": "ok"}
    got = {"rows": [row(1, 1.5, 1.0), row(2, 1.0, 1.0), row(3, 1.2, 1.2)],
           "why": "3 row(s) pass the floors"}
    monkeypatch.setattr(sw, "_candidates", lambda cfg, now: got)
    monkeypatch.setattr(at, "load_settings", lambda: {})
    monkeypatch.setattr(sw, "_try_picks", lambda *a, **k: None)
    monkeypatch.setattr(sw, "_as_the_off_check_sees", lambda rows, now, cfg: rows)
    st: dict = {}
    cfg = {**sw.wp.DEFAULTS, "tp_rule": ">", "on_winrate": 80.0, "min_trades": 30,
           "max_sl": 2.0, "raw": True, "max_new_per_day": 0, "max_slots": 0, "max_per_coin": 0}
    sw._on_pass(0.0, cfg, st, False, [])
    assert st["last_candidates"] == ("3 row(s) pass the floors — 1 pass every rule on "
                                     "their own result file (2 fail one, most often TP "
                                     "is not wider than SL)")
    src = (ROOT / "tradingagents/watcher_candidates.py").read_text(encoding="utf-8")
    assert 'meet the criteria"}' not in src


def test_switch_on_reads_the_number_switch_off_will_read(monkeypatch):
    """RCA-2026-10-01-A: #FR34HHN4 DHRSTOCK 15m bb20 went on at 7:57pm from
    the list's 71.13% (142 trades) and off at 8:30pm from its own file's
    69.06% (139), then on and off again after midnight. The switch-on now
    re-reads the file first, so it is never switched on at all."""
    from tradingagents import strategy_watcher as sw
    listed = {"id": "FR34HHN4", "coin": "DHRSTOCK", "tf": "15m", "signal": "bb20",
              "th": 0.0, "sl": 0.3, "tp": 0.4, "trades": 142, "wins": 101,
              "losses": 41, "winrate": 71.13, "profit": 0.25, "gate": "ok"}
    in_file = {k: v for k, v in listed.items() if k != "id"}
    in_file.update(trades=139, wins=96, losses=43, winrate=69.06, profit=-2.36, sizing="flat")
    monkeypatch.setattr(wc, "matched_rows", lambda coin, tf, wants: {wc._sig(w): in_file for w in wants})
    monkeypatch.setattr(wc, "_last_ms", lambda coin, tf: 1790775000000.0)
    monkeypatch.setattr(sw, "_judged", lambda slot, fresh, now, window=30: fresh)
    cfg = {**sw.wp.DEFAULTS, "tp_rule": ">", "on_winrate": 70.0, "off_winrate": 70.0,
           "min_trades": 50, "max_sl": 2.0, "raw": True}
    seen = sw._as_the_off_check_sees([listed], 0.0, cfg)
    assert [r["winrate"] for r in seen] == [69.06]
    assert sw.wp.passes_on(seen[0], cfg), "it must not be switched on"
    assert not sw.wp.passes_on(listed, cfg), "the list alone would have switched it on"
    monkeypatch.setattr(wc, "matched_rows", lambda coin, tf, wants: {})
    assert sw._as_the_off_check_sees([listed], 0.0, cfg) == [], "gone from its file: not on"
