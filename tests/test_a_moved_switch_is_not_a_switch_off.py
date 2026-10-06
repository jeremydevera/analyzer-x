"""A strategy moved from its coin's own switch to the strategy's switch stayed ON.

RCA-2026-10-06-A: Main's keltner_30m_sl2tp2 on GPNSTOCK. At Sep 24, 2026
7:45am one save removed the coin's own switch (`key|GPNSTOCK`) and put the
strategy's switch on for GPNSTOCK and KKRSTOCK - the same row, still trading
practice. The switch history read the removal as a switch-off, so the two
practice trades of Oct 01, 2026 (4:30am -$2.42, 11:30am +$1.78) had no
stretch, Backtest a room never nominated the row, and both trades sat in
"practice only". It really went off at Oct 01, 2026 11:51am, when the
strategy's coin list emptied.

The history is a diff of three settings (`local_history.deploy_diff`), so it
is replayed as them - the runner's own rule, `auto_trader.books_for`.
"""
from __future__ import annotations

import json

from tradingagents import forecast_v2 as f2

K = "keltner_30m_sl2tp2"
GPN, KKR, STBL = "GPNSTOCK_USDT", "KKRSTOCK_USDT", "STBL_USDT"


def _bare(t, sym, act, books, prev_books, prev_coins, margin=5.0, key=K):
    return json.dumps({"changed_at": t, "strategy_key": key, "symbol": sym, "action": act,
                       "books": books, "base_margin": margin,
                       "prev_json": json.dumps({"books": prev_books, "coins": prev_coins,
                                                "base_margin": margin})})


def _own(t, sym, act, books, prev_books, key=K):
    return json.dumps({"changed_at": t, "strategy_key": f"{key}|{sym}", "symbol": "—",
                       "action": act, "books": books, "base_margin": None,
                       "prev_json": json.dumps({"books": prev_books, "coins": [],
                                                "base_margin": None})})


def test_a_switch_moved_onto_the_strategy_stays_on():
    lines = [
        # Sep 03: on for GPNSTOCK, by the strategy's switch
        _bare(100, GPN, "deployed", "paper", [], []),
        # Sep 16: moved onto GPNSTOCK's own switch, never written (the per-coin
        # move); Sep 24 7:45am: moved back, and KKRSTOCK added - ONE save
        _bare(200, GPN, "deployed", "paper", [], [GPN]),
        _bare(200, KKR, "deployed", "paper", [], [GPN]),
        _own(201, GPN, "disarmed", "", ["paper"]),
        # Sep 29: KKRSTOCK taken off
        _bare(300, GPN, "changed", "paper", ["paper"], [GPN, KKR]),
        # Oct 01 11:51am: GPNSTOCK taken off - no coin left, so deploy_diff
        # lists the coins BEFORE, with the accounts and margin unchanged
        _bare(400, GPN, "changed", "paper", ["paper"], [GPN]),
    ]
    got = f2._switches(lines)
    assert got == [(100, f"{K}|{GPN}", "deployed"),
                   (200, f"{K}|{KKR}", "deployed"),
                   (300, f"{K}|{KKR}", "disarmed"),
                   (400, f"{K}|{GPN}", "disarmed")], got


def test_a_coin_switch_the_log_never_set_is_off_when_removed_alone():
    """macddiv_4h_sl25tp25 on STBL: the per-coin move of Sep 16, 2026 took the
    strategy's accounts away without a line, so when STBL's own switch was
    removed at Sep 24, 2026 7:45am, with no line for the strategy in that
    save, nothing was left - the settings copies of Sep 16 - Sep 22 say so."""
    k = "macddiv_4h_sl25tp25"
    lines = [_bare(100, STBL, "deployed", "paper", [], [], key=k),
             _own(500, STBL, "disarmed", "", ["paper"], key=k)]
    assert f2._switches(lines) == [(100, f"{k}|{STBL}", "deployed"),
                                   (500, f"{k}|{STBL}", "disarmed")]


def test_a_coin_switch_the_log_did_set_falls_back_to_the_strategy():
    """The watcher's own switch, removed while the strategy's switch still
    carries the coin on practice: the row keeps trading."""
    lines = [_bare(100, GPN, "deployed", "paper", [], []),
             _own(200, GPN, "deployed", "paper", []),
             _own(900, GPN, "disarmed", "", ["paper"])]
    assert f2._switches(lines) == [(100, f"{K}|{GPN}", "deployed")]


def test_real_money_only_is_not_on_the_practice_account():
    """Main, Sep 03, 2026: 1:33pm on for REAL money only, practice added at
    10:28pm. The practice account traded from 10:28pm."""
    lines = [_bare(100, GPN, "deployed", "real", [], []),
             _bare(200, GPN, "changed", "real,paper", ["real"], [GPN]),
             _bare(300, GPN, "changed", "real", ["real", "paper"], [GPN])]
    assert f2._switches(lines) == [(200, f"{K}|{GPN}", "deployed"),
                                   (300, f"{K}|{GPN}", "disarmed")]


def test_a_margin_change_is_not_a_switch_off():
    """The same coins listed with a NEW margin is a margin change, not the
    empty coin list deploy_diff spells the same way."""
    lines = [_bare(100, GPN, "deployed", "paper", [], [], margin=5.0),
             _bare(200, GPN, "changed", "paper", ["paper"], [GPN], margin=1.0)]
    e = json.loads(lines[1])
    e["prev_json"] = json.dumps({"books": ["paper"], "coins": [GPN], "base_margin": 5.0})
    lines[1] = json.dumps(e)
    assert f2._switches(lines) == [(100, f"{K}|{GPN}", "deployed")]


def test_one_save_written_over_two_seconds_leaves_no_gap():
    """A switch-off and the switch-on that replaces it, a second apart in the
    same save, are no stretch the runner ever stood still in."""
    lines = [_own(100, GPN, "deployed", "paper", []),
             _own(500, GPN, "disarmed", "", ["paper"]),
             _bare(501, GPN, "deployed", "paper", [], [])]
    assert f2._switches(lines) == [(100, f"{K}|{GPN}", "deployed")]


def test_main_trades_of_oct_01_sit_inside_a_stretch(tmp_path, monkeypatch):
    """Through _intervals, as Backtest a room and the reality check read it."""
    from tradingagents import local_history as lh

    log = tmp_path / "deployments.jsonl"
    log.write_text("\n".join([
        _bare(1788488927, GPN, "deployed", "paper", [], []),
        _bare(1790250312, GPN, "deployed", "paper", [], [GPN]),
        _bare(1790250312, KKR, "deployed", "paper", [], [GPN]),
        _own(1790250312, GPN, "disarmed", "", ["paper"]),
        _bare(1790869873, GPN, "changed", "paper", ["paper"], [GPN])]) + "\n",
        encoding="utf-8")
    monkeypatch.setattr(lh, "_deploy_log", lambda: log)
    monkeypatch.setattr(f2, "_settings", lambda pid: {"strategy_coins": {K: []}})
    monkeypatch.setattr(f2, "_watcher_decisions", lambda pid: {})
    spans = f2._intervals("main", 1791331200.0)[f"{K}|{GPN}"]
    for opened in (1790843402, 1790868600):          # Oct 01, 2026 4:30am, 11:30am
        assert any(a <= opened <= b for a, b in spans), spans
    assert spans == [(1788488927, 1790869873)]
