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


def test_first_daily_build_also_keeps_the_nov10_forecast_once(tmp_path):
    """Final review (Nov 11, 2026): the daily build replaces forecast.json too, and the numbers the
    three rooms were chosen on (#D7EN8BNV, #RSS7CUKH, #7T3VJU82) lived only there. Kept once, gzipped,
    beside the dated daily copies - never overwritten, and never a daily forecast under that name."""
    import gzip

    home = tmp_path / "v4"
    home.mkdir()
    db = home / "rows.db"
    db.write_bytes(b"the nov 10 store")
    fc = home / "forecast.json"
    nov10 = json.dumps({"store": {"sources": {"technical-analysis + backtesting-frameworks": 226380}},
                        "rules": [{"id": "D7EN8BNV"}]})
    fc.write_text(nov10, encoding="utf-8")
    v4.keep_first_copy(db)
    kept = home / "forecast-days" / "forecast-2026-11-10-static.json.gz"
    assert kept.exists() and gzip.decompress(kept.read_bytes()).decode("utf-8") == nov10
    fc.write_text(json.dumps({"store": {"sources": {"daily re-measure": 15933}}}), encoding="utf-8")
    v4.keep_first_copy(db)
    assert gzip.decompress(kept.read_bytes()).decode("utf-8") == nov10, "never overwritten"
    kept.unlink()
    v4.keep_first_copy(db)
    assert not kept.exists(), "a forecast built from a daily store is never kept as the Nov 10 one"
    assert [p.name for p in home.rglob("*") if p.name.endswith((".tmp", ".copying"))] == []


# ------------------------------------------------------------------ exits settled by the minute (Nov 11, 2026)
def test_a_minute_exit_keeps_its_minute_and_the_page_says_how_far_the_minutes_went(tmp_path):
    folder = tmp_path / "acs"
    folder.mkdir()
    en, ex = ms(2026, 10, 25, 10), ms(2026, 10, 25, 11)
    at_ms = ex + 12 * 60_000
    pick = _daily_pick("sma_crossover", "stopped", [(en, ex, -1.5)])
    pick["trades"][0].append(at_ms)                                  # a sixth item: the minute it ended in
    plain = _daily_pick("ta_ma_pullback", "closed", [(en, ex + H, 0.5)])
    _file(folder, {("AAA", "1h"): [pick, plain]})
    path = folder / "skilldaily.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["lines"]["AAA|1h"]["exits"] = {"minute": 30, "candle": 10, "unclear": 1, "from_ms": ms(2026, 7, 13)}
    path.write_text(json.dumps(doc), encoding="utf-8")
    db = tmp_path / "v4" / "rows.db"
    meta = v4.build(folder, target=db, sources=v4.DAILY_SOURCES, log=lambda *_: None)
    # one line, two strategies: the counts are the LINE's, never added once a strategy
    assert meta["exits"] == {"minute": 30, "candle": 10, "unclear": 1, "from_s": ms(2026, 7, 13) // 1000}
    con = sqlite3.connect(db)
    got = {r[0]: r[1] for r in con.execute("SELECT s.label, t.at FROM trade t JOIN strat s ON s.sid = t.sid")}
    assert got == {"stopped": at_ms // 1000, "closed": None}, "only a trade the minutes settled has a minute"
    con.close()


def test_the_trade_log_shows_the_minute_and_an_old_store_without_the_column_still_reads(tmp_path, monkeypatch):
    folder = tmp_path / "acs"
    folder.mkdir()
    en, ex = ms(2026, 10, 25, 10), ms(2026, 10, 25, 11)
    pick = _daily_pick("sma_crossover", "stopped", [(en, ex, -1.5)])
    pick["trades"][0].append(ex + 12 * 60_000)
    _file(folder, {("AAA", "1h"): [pick]})
    home = tmp_path / "v4"
    monkeypatch.setattr(stores, "V4", stores.Store(**{**stores.V4.__dict__, "home": home,
                                                      "rows_db": home / "rows.db"}))
    v4.build(folder, target=home / "rows.db", sources=v4.DAILY_SOURCES, log=lambda *_: None)
    rid = v4.row_id("AAA", "1h", {**pick, "label": pick["label"]})
    log = v4.trade_log(rid)["log"]
    assert log[0]["exit_s"] == (ex + 12 * 60_000) // 1000 and log[0]["by_minute"] is True

    con = sqlite3.connect(home / "rows.db")                          # a store built before Nov 11, 2026
    con.execute("ALTER TABLE trade DROP COLUMN at")
    con.commit()
    con.close()
    old = v4.trade_log(rid)["log"]
    assert old[0]["exit_s"] == ex // 1000 and old[0]["by_minute"] is False


def test_a_store_with_no_minute_exits_says_nothing_about_them(tmp_path):
    folder = tmp_path / "acs"
    folder.mkdir()
    _file(folder, {("AAA", "1h"): [_daily_pick("sma_crossover", "x", [(ms(2026, 10, 25, 10), ms(2026, 10, 25, 11), 1.0)])]})
    meta = v4.build(folder, target=tmp_path / "v4" / "rows.db", sources=v4.DAILY_SOURCES, log=lambda *_: None)
    assert "exits" not in meta
