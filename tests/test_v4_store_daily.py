"""Backtest v4 learns the daily run (Nov 10, 2026): `skilldaily.json`, each pick's own split, and the
Nov 10 store kept once. One timeline: every trade sits between its line's start and end."""
import json
import sqlite3
from datetime import datetime, timezone

from tradingagents import stores, v4_store as v4

H = 3_600_000


def ms(y, m, d, h=0):
    return int(datetime(y, m, d, h, tzinfo=timezone.utc).timestamp() * 1000)


END = ms(2026, 11, 8)


def _daily_pick(strategy, label, trades, *, split_ms=None):
    """A daily-run pick: no `older`/`newer`, no `older_lost`; the pinned bt picks carry their own split."""
    p = {"label": label, "strategy": strategy, "params": {"n": 1}, "stop": 0.015, "target": 0.03,
         "trades": [[en, ex, 1, "TP" if pnl > 0 else "SL", pnl] for en, ex, pnl in trades]}
    if split_ms is not None:
        p["split_ms"] = split_ms
    return p


def _file(folder, picks_by_line, name="skilldaily.json"):
    lines = {}
    for (coin, tf), picks in picks_by_line.items():
        lines[f"{coin}|{tf}"] = {"coin": coin, "tf": tf, "fee": 0.00075, "slip": 0.001, "bars": 500,
                                 "combos": len(picks), "split_ms": ms(2026, 10, 20), "start_ms": ms(2026, 9, 1),
                                 "end_ms": END, "bar": None, "picks": picks}
    (folder / name).write_text(json.dumps({"lines": lines}), encoding="utf-8")


def test_daily_build_keeps_each_picks_own_split(tmp_path):
    folder = tmp_path / "acs"
    folder.mkdir()
    trades = [(ms(2026, 10, 1, 10), ms(2026, 10, 1, 11), 1.0), (ms(2026, 10, 25, 10), ms(2026, 10, 25, 11), 2.0)]
    _file(folder, {("AAA", "1h"): [
        _daily_pick("sma_crossover", "pinned", trades, split_ms=ms(2026, 10, 5)),       # its own Oct 05 split
        _daily_pick("ta_ma_pullback", "ta", trades)]})                                   # the line's Oct 20 split
    db = tmp_path / "v4" / "rows.db"
    meta = v4.build(folder, target=db, sources=v4.DAILY_SOURCES, log=lambda *_: None)
    assert v4.DAILY_SOURCES == (("skilldaily.json", "daily re-measure"),)
    assert meta["sources"] == {"daily re-measure": 2}
    con = sqlite3.connect(db)
    rows = {r[0]: r[1:] for r in con.execute("SELECT label, split_s, older_lost, older_trades, newer_trades "
                                              "FROM strat")}
    # the pinned pick keeps ITS split (Oct 05): the Oct 01 trade is older, the Oct 25 one unseen. The other
    # pick falls back to the line's split (Oct 20): the same two trades fall the same way, so the proof of
    # "its own split" is the stored split_s itself
    assert rows["pinned"] == (ms(2026, 10, 5) // 1000, 0, 1, 1)
    assert rows["ta"] == (ms(2026, 10, 20) // 1000, 0, 1, 1)
    # a pick with no `older` stats and no flag never raised: its figures come from its trades
    assert con.execute("SELECT trades, wins, profit FROM strat WHERE label='ta'").fetchone() == (2, 2, 3.0)
    con.close()


def test_a_pinned_split_moves_the_older_unseen_line(tmp_path):
    folder = tmp_path / "acs"
    folder.mkdir()
    trades = [(ms(2026, 10, 10, 10), ms(2026, 10, 10, 11), 1.0)]           # Oct 10: before the line's Oct 20
    _file(folder, {("AAA", "1h"): [_daily_pick("sma_crossover", "pinned", trades, split_ms=ms(2026, 10, 5)),
                                   _daily_pick("ta_ma_pullback", "ta", trades)]})
    db = tmp_path / "v4" / "rows.db"
    v4.build(folder, target=db, sources=v4.DAILY_SOURCES, log=lambda *_: None)
    con = sqlite3.connect(db)
    got = {r[0]: r[1:] for r in con.execute("SELECT label, older_trades, newer_trades FROM strat")}
    assert got == {"pinned": (0, 1), "ta": (1, 0)}      # Oct 10 is unseen for Oct 05, older for Oct 20
    con.close()


def test_first_daily_build_keeps_the_nov10_store_once(tmp_path):
    db = tmp_path / "v4" / "rows.db"
    db.parent.mkdir()
    db.write_bytes(b"the nov 10 store")
    got = v4.keep_first_copy(db)
    assert got == tmp_path / "v4" / "rows-2026-11-10.db" and got.read_bytes() == b"the nov 10 store"
    db.write_bytes(b"a daily store")                       # the refresh replaced it
    assert v4.keep_first_copy(db) is None                  # the copy exists: never written again
    assert got.read_bytes() == b"the nov 10 store"
    assert [p.name for p in db.parent.iterdir() if p.name.endswith(".copying")] == []


def test_a_missing_store_has_nothing_to_keep(tmp_path):
    assert v4.keep_first_copy(tmp_path / "v4" / "rows.db") is None


def test_the_daily_cli_fails_loudly_with_its_reason(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(stores, "V4", stores.Store(**{**stores.V4.__dict__, "home": tmp_path / "v4",
                                                      "rows_db": tmp_path / "v4" / "rows.db"}))

    def boom(*a, **k):
        raise RuntimeError("no daily file")

    monkeypatch.setattr(v4, "build", boom)
    assert v4.main(["build", "--daily"]) == 1
    out = capsys.readouterr().out
    assert "FAILED" in out and "no daily file" in out
