"""The screen reads a room's TRADES, never its whole trade record again.

Operator, Oct 07, 2026, a screenshot of Auto Trade: *"profit — still not
loading after 112s, retrying"*, then *"also day by day calendar is taking too
long to load and trade history"*.

Measured that afternoon (RCA-2026-10-07-L): #4FC03172's trade record held
366,316 lines, and 374 of them were trades — 300,907 were the cost check's
hourly "gate_blocked" notes, written at 43,000-52,000 a day. Every figure on
Auto Trade parsed the WHOLE record to find those 374: eleven full reads per
room per refresh (summary 3, strategies 4, positions 2, the calendar, the
history), every 5 s for the room on screen and every 15 s for the other
five. One read was 2.0 s alone; the API was busy 12.1 s of
every 10 s, and the calendar of #4FC03172 took 18.6 s to answer a direct ask.

Now each process keeps every record's ENTER and EXIT rows
(`auto_trader.ledger_trades`) and reads only what was appended since its last
look. These tests hold both halves: the kept rows are EXACTLY what a full read
finds, in every state the file can be in, and no screen route reads the whole
record again.
"""
from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

import tradingagents.auto_trader as at
from tradingagents import api, profiles


def _exit(ts, pnl, *, dry=True, sym="KITE_USDT", strat="squeeze_1h_sl3tp3",
          tid="AAAA1111"):
    return {"ts": ts, "action": "exit", "symbol": sym, "strategy": strat,
            "dry_run": dry, "why": "TP" if pnl > 0 else "SL", "pnl_est": pnl,
            "trade_id": tid}


def _enter(ts, *, dry=True, sym="KITE_USDT", strat="squeeze_1h_sl3tp3",
           tid="AAAA1111"):
    return {"ts": ts, "action": "enter", "symbol": sym, "strategy": strat,
            "dry_run": dry, "side": "LONG", "trade_id": tid}


def _note(ts, i=0):
    # the cost check's refusal, the row that filled #4FC03172's record
    return {"ts": ts, "action": "gate_blocked", "symbol": f"C{i}_USDT",
            "strategy": "bb20_15m_sl03tp04", "dry_run": True,
            "reason": "spread 0.41% eats the target", "candles": 4}


def _append(rows):
    with at._pp(at.LEDGER_PATH).open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def _full_read_trades(ts=0):
    """What the old readers found: every row, then the trades among them."""
    return [e for e in at.ledger_since(ts)
            if e.get("action") in ("enter", "exit")]


# ------------------------------------------------ 1. exactly what a full read finds
def test_the_kept_trades_are_exactly_what_a_full_read_finds(write_ledger):
    rows = []
    for i in range(40):
        rows.append(_note(1_000 + i, i))
        if i % 7 == 0:
            rows.append(_enter(1_000 + i, tid=f"T{i:07d}"))
        if i % 7 == 3:
            rows.append(_exit(1_000 + i, -0.5 if i % 2 else 0.9, tid=f"T{i:07d}",
                              dry=bool(i % 3)))
    # a refusal whose WORDS say exit is still not a trade
    rows.append({**_note(2_000), "reason": "the exit price is \"exit\" quoted"})
    p = write_ledger(rows)
    with p.open("a", encoding="utf-8") as fh:
        fh.write("\n")                       # a blank line
        fh.write('{"action": "exit", "ts": 3\n')   # a torn row
    for ts in (0, 1_010, 1_025, 1_039, 5_000):
        assert at.ledger_trades(ts) == _full_read_trades(ts), ts
    assert len(at.ledger_trades(0)) == 12


def test_a_line_that_is_not_a_row_is_skipped_never_an_error(write_ledger):
    p = write_ledger([_exit(1, 1.0)])
    with p.open("a", encoding="utf-8") as fh:
        fh.write('["exit", "enter"]\n')      # JSON, but not a row
        fh.write('"exit"\n')
    _append([_exit(2, -1.0, tid="BBBB2222")])
    assert [e["trade_id"] for e in at.ledger_trades(0)] == ["AAAA1111", "BBBB2222"]


# ------------------------------------------------ 2. only the new lines are read
def test_only_the_lines_added_since_the_last_look_are_parsed(write_ledger, monkeypatch):
    write_ledger([_note(1_000 + i, i) for i in range(5_000)]
                 + [_enter(6_000), _exit(6_100, 0.98)])
    assert len(at.ledger_trades(0)) == 2
    parsed = []
    real = json.loads
    monkeypatch.setattr(json, "loads", lambda s, *a, **k: (parsed.append(s), real(s, *a, **k))[1])
    _append([_note(7_000 + i, i) for i in range(3_000)] + [_exit(9_000, -1.62, tid="CCCC3333")])
    got = at.ledger_trades(0)
    assert [e["trade_id"] for e in got][-1] == "CCCC3333" and len(got) == 3
    assert len(parsed) == 1, \
        f"3,001 lines were added and {len(parsed)} were parsed — only the trade should be"
    parsed.clear()
    assert len(at.ledger_trades(0)) == 3
    assert parsed == [], "nothing new, nothing parsed"


def test_a_row_still_being_written_is_left_for_the_next_look(write_ledger):
    p = write_ledger([_exit(1, 1.0)])
    assert len(at.ledger_trades(0)) == 1
    line = json.dumps(_exit(2, -1.0, tid="BBBB2222")) + "\n"
    with p.open("a", encoding="utf-8") as fh:
        fh.write(line[:25])                  # the runner is mid-write
    assert len(at.ledger_trades(0)) == 1
    with p.open("a", encoding="utf-8") as fh:
        fh.write(line[25:])
    assert [e["trade_id"] for e in at.ledger_trades(0)] == ["AAAA1111", "BBBB2222"]
    assert len(at.ledger_trades(0)) == 2, "and it is read once, never twice"


# ------------------------------------------------ 3. a rewritten record is read again
def test_a_rewritten_record_that_grew_back_past_the_old_end_is_read_again(write_ledger):
    """A reset removes trades and rewrites the file in place; by the next
    look the runner may have appended more than was removed, so the SIZE says
    nothing. The bytes before where the reader stopped do."""
    trades = [_exit(1_000 + i, 1.0, tid=f"OLD{i:05d}") for i in range(20)]
    p = write_ledger([_note(i, i) for i in range(50)] + trades)
    assert len(at.ledger_trades(0)) == 20
    old_size = p.stat().st_size
    write_ledger([_note(i, i) for i in range(50)])               # trades removed
    _append([_note(5_000 + i, i) for i in range(60)] + [_exit(9_000, -0.4, tid="NEW00001")])
    assert p.stat().st_size > old_size, "the fixture must defeat a size check"
    assert [e["trade_id"] for e in at.ledger_trades(0)] == ["NEW00001"]


def test_the_record_reset_button_drops_the_trades_it_removed(write_ledger):
    write_ledger([_enter(1), _exit(2, 1.0), _enter(3, dry=False, tid="REAL0001"),
                  _exit(4, -1.0, dry=False, tid="REAL0001")])
    assert len(at.ledger_trades(0)) == 4
    at.reset_record(["paper"])
    got = at.ledger_trades(0)
    assert {e["trade_id"] for e in got} == {"REAL0001"} and len(got) == 2
    assert got == _full_read_trades(0)


def test_a_swapped_in_copy_of_the_same_size_is_read_again(write_ledger):
    """`backfill_ledger_ids(restamp=True)` writes a temp file and renames it
    over the record. Ids are a fixed width, so the size can be identical and
    the changed rows can sit far from both ends."""
    head = [_note(i, i) for i in range(200)]
    tail = [_note(10_000 + i, i) for i in range(200)]
    p = write_ledger(head + [_exit(5_000, 1.0, tid="OLDID001")] + tail)
    assert [e["trade_id"] for e in at.ledger_trades(0)] == ["OLDID001"]
    tmp = p.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r) + "\n" for r in
                           head + [_exit(5_000, 1.0, tid="NEWID002")] + tail),
                   encoding="utf-8")
    assert tmp.stat().st_size == p.stat().st_size
    os.replace(tmp, p)
    assert [e["trade_id"] for e in at.ledger_trades(0)] == ["NEWID002"]


def test_an_edit_nobody_announced_is_wrong_for_minutes_never_for_ever(write_ledger,
                                                                     monkeypatch):
    """Same file, same size, same first and last bytes — the one change no
    check can see. The full re-read every RECHECK_S finds it."""
    head = [_note(i, i) for i in range(200)]
    tail = [_note(10_000 + i, i) for i in range(200)]
    p = write_ledger(head + [_exit(5_000, 1.0, tid="OLDID001")] + tail)
    assert [e["trade_id"] for e in at.ledger_trades(0)] == ["OLDID001"]
    raw = p.read_bytes()
    with p.open("r+b") as fh:                # the same file, edited in place
        fh.write(raw.replace(b"OLDID001", b"NEWID002"))
    assert at.ledger_trades(0)[0]["trade_id"] == "OLDID001", \
        "the fixture must hide the edit from the cheap checks"
    monkeypatch.setattr(at._TradeRows, "RECHECK_S", 0.0)
    assert [e["trade_id"] for e in at.ledger_trades(0)] == ["NEWID002"]


# ------------------------------------------------ 4. shared safely
def test_every_row_handed_out_is_a_copy(write_ledger):
    write_ledger([_exit(1, 1.0)])
    at.ledger_trades(0)[0]["pnl_est"] = -999.0
    assert at.ledger_trades(0)[0]["pnl_est"] == 1.0


def test_each_room_keeps_its_own_trades(write_ledger):
    write_ledger([_exit(1, 1.0, sym="VUG_USDT")])
    with profiles.using("DC57174E"):
        write_ledger([_exit(1, -2.0, sym="XLI_USDT")])
        assert [e["symbol"] for e in at.ledger_trades(0)] == ["XLI_USDT"]
    assert [e["symbol"] for e in at.ledger_trades(0)] == ["VUG_USDT"]


def test_a_missing_record_is_no_trades(write_ledger):
    assert at.ledger_trades(0) == [] and at.ledger_line_count() == 0
    p = write_ledger([_exit(1, 1.0)])
    assert len(at.ledger_trades(0)) == 1
    p.unlink()
    assert at.ledger_trades(0) == [], "a removed record keeps no trades"


def test_a_read_that_fails_half_way_counts_nothing_twice(write_ledger, monkeypatch):
    """Found by the bug hunt before it shipped: the first draft kept each row
    as it parsed it, so a read that failed half-way kept its first half and
    read that half AGAIN next time — the same trade twice in every total."""
    from pathlib import Path

    write_ledger([_exit(1, 1.0)])
    assert len(at.ledger_trades(0)) == 1
    _append([_exit(2, 1.0, tid="BBBB2222"), _exit(3, 1.0, tid="CCCC3333")])
    real_open = Path.open

    class Torn:
        def __init__(self, fh):
            self.fh = fh

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.fh.close()

        def fileno(self):
            return self.fh.fileno()

        def seek(self, *a):
            return self.fh.seek(*a)

        def read(self, *a):
            return self.fh.read(*a)

        def __iter__(self):
            for i, line in enumerate(self.fh):
                if i == 1:
                    raise OSError("the disk went away")
                yield line

    monkeypatch.setattr(Path, "open", lambda self, *a, **k: Torn(real_open(self, *a, **k)))
    assert [e["trade_id"] for e in at.ledger_trades(0)] == ["AAAA1111"], \
        "a failed read answers from what was already kept"
    monkeypatch.setattr(Path, "open", real_open)
    assert [e["trade_id"] for e in at.ledger_trades(0)] == \
        ["AAAA1111", "BBBB2222", "CCCC3333"]


# ------------------------------------------------ 5. the screen never reads it all
def test_no_screen_route_reads_the_whole_record(write_ledger, monkeypatch):
    """Every route Auto Trade polls, plus the watcher's practice record and the
    loss limit's readers, with the whole-record readers made to fail."""
    from tradingagents import watcher_results

    write_ledger([_note(1, 1), _enter(2), _exit(3, 0.98), _note(4, 2)])

    def _whole(*_a, **_k):
        raise AssertionError("a screen read the whole trade record")

    monkeypatch.setattr(at, "ledger_since", _whole)
    monkeypatch.setattr(at, "ledger_tail", _whole)
    client = TestClient(api.app, raise_server_exceptions=True)
    for path in ("/api/trade/pnl/daily?dry=true", "/api/trade/history?dry=true",
                 "/api/trade/equity?dry=true", "/api/trade/summary",
                 "/api/trade/strategies", "/api/trade/positions",
                 "/api/ledger?limit=200&actions=enter,exit"):
        r = client.get(path)
        assert r.status_code == 200, (path, r.text[:300])
    assert at.daily_pnl(dry=True) and at.coin_stats(dry=True)
    assert at.strategy_stats(dry=True) and at.strategy_stats(dry=True, by_coin=True)
    at.pnl_today(dry=True)
    at.pnl_today_by_strategy(dry=True)
    at.tripped_strategies({"strategy_loss_limits": {"squeeze_1h_sl3tp3": 1}}, dry=True)
    assert watcher_results.practice({"squeeze_1h_sl3tp3|KITE_USDT": 0}, now=10.0)


def test_a_trade_100000_lines_back_is_still_in_the_history(write_ledger):
    """NEVER HAPPENED YET when this was fixed. The history read the last
    100,000 LINES; #4FC03172 writes ~55,000 a day, and its oldest trade was
    25,678 lines from the end — under two days from falling out of its own
    history, with `examined` and `total` shrinking to match."""
    p = write_ledger([_enter(1), _exit(2, 0.98)])
    with p.open("a", encoding="utf-8") as fh:
        fh.write("".join(json.dumps({"ts": 3, "action": "gate_blocked"}) + "\n"
                         for _ in range(100_000)))
    client = TestClient(api.app)
    got = client.get("/api/trade/history?dry=true&per_page=5").json()
    assert got["total"] == 1 and got["examined"] == 1
    led = client.get("/api/ledger?limit=200&actions=enter,exit").json()
    assert led["matched"] == 2
    assert led["total"] == 100_002, "every line of the record, not the window read"
