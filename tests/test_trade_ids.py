"""Trade identity in the ledger.

The operator asked for an id and an opening time on every trade, stored in
the ledger rather than computed for display (2026-08-22). Three properties
have to hold: the id is stable and derived (never a counter), the exit row
carries the SAME id its entry got, and the backfill of old rows produces
exactly what the live path would have written.
"""
import json

from tradingagents import auto_trader as at


def test_code_is_stable_and_derived_not_sequential():
    a = at.trade_code("PI_USDT", "trend50_30m_pi", 1787207404, 1, False)
    assert a == at.trade_code("PI_USDT", "trend50_30m_pi", 1787207404, 1,
                              False), "same trade must hash the same"
    assert len(a) == 8
    assert set(a) <= set(at._TRADE_ALPHABET), "no 0/O/1/I in a quotable id"
    # every field is part of the identity
    assert a != at.trade_code("PROVE_USDT", "trend50_30m_pi", 1787207404, 1, False)
    assert a != at.trade_code("PI_USDT", "mom6_1h_pv", 1787207404, 1, False)
    assert a != at.trade_code("PI_USDT", "trend50_30m_pi", 1787207999, 1, False)
    assert a != at.trade_code("PI_USDT", "trend50_30m_pi", 1787207404, -1, False)
    # the paper book is a DIFFERENT trade from the live one, same candle
    assert a != at.trade_code("PI_USDT", "trend50_30m_pi", 1787207404, 1, True)


def _write(tmp_path, rows):
    p = tmp_path / "ledger.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return p


def test_backfill_pairs_each_exit_with_its_own_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(at, "STATE_DIR", tmp_path)
    rows = [
        {"ts": 1000, "action": "enter", "symbol": "PI_USDT",
         "strategy": "s1", "side": "LONG", "dry_run": False},
        {"ts": 1100, "action": "enter", "symbol": "PI_USDT",
         "strategy": "s1", "side": "LONG", "dry_run": True},     # paper book
        {"ts": 1500, "action": "exit", "symbol": "PI_USDT",
         "strategy": "s1", "pnl_est": -2.0, "dry_run": False},
        {"ts": 1600, "action": "exit", "symbol": "PI_USDT",
         "strategy": "s1", "pnl_est": -1.0, "dry_run": True},
    ]
    p = _write(tmp_path, rows)
    res = at.backfill_ledger_ids(p)
    out = [json.loads(l) for l in p.read_text().splitlines()]
    live_in, paper_in, live_out, paper_out = out
    assert live_out["trade_id"] == live_in["trade_id"]
    assert paper_out["trade_id"] == paper_in["trade_id"]
    assert live_out["trade_id"] != paper_out["trade_id"], \
        "the two books must not share one trade id"
    assert live_out["opened_at"] == 1000 and live_out["held_s"] == 500
    assert paper_out["opened_at"] == 1100 and paper_out["held_s"] == 500
    assert res["written"] is True


def test_backfill_is_idempotent_and_keeps_a_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(at, "STATE_DIR", tmp_path)
    rows = [{"ts": 1000, "action": "enter", "symbol": "X_USDT",
             "strategy": "s", "side": "SHORT", "dry_run": False},
            {"ts": 1200, "action": "exit", "symbol": "X_USDT",
             "strategy": "s", "pnl_est": 1.0, "dry_run": False}]
    p = _write(tmp_path, rows)
    first = at.backfill_ledger_ids(p)
    before = p.read_text()
    second = at.backfill_ledger_ids(p)
    assert second["entered"] == 0 and second["exited"] == 0
    assert [json.loads(l)["trade_id"] for l in p.read_text().splitlines()] \
        == [json.loads(l)["trade_id"] for l in before.splitlines()]
    assert list(tmp_path.glob("*.bak-*")), "no backup written"
    assert first["written"] is True


def test_backfill_never_loses_unrelated_or_unparseable_lines(tmp_path,
                                                             monkeypatch):
    monkeypatch.setattr(at, "STATE_DIR", tmp_path)
    p = tmp_path / "ledger.jsonl"
    p.write_text('{"ts": 1, "action": "runner_start"}\n'
                 'this is not json\n'
                 '{"ts": 2, "action": "enter", "symbol": "A_USDT", '
                 '"strategy": "s", "side": "LONG", "dry_run": false}\n')
    at.backfill_ledger_ids(p)
    lines = p.read_text().splitlines()
    assert len(lines) == 3
    assert lines[1] == "this is not json"
    assert json.loads(lines[0])["action"] == "runner_start"
    assert json.loads(lines[2])["trade_id"]


def test_an_orphan_exit_still_gets_an_id_rather_than_a_blank(tmp_path,
                                                            monkeypatch):
    monkeypatch.setattr(at, "STATE_DIR", tmp_path)
    p = _write(tmp_path, [{"ts": 9000, "action": "exit", "symbol": "Z_USDT",
                           "strategy": "s", "pnl_est": -3.0,
                           "dry_run": False}])
    at.backfill_ledger_ids(p)
    row = json.loads(p.read_text().splitlines()[0])
    assert row["trade_id"], "an exit with no entry must still be quotable"
    assert row.get("opened_at") is None, \
        "and must NOT invent an opening time it never had"
