"""/feedcheck reports the window since its own last run.

Operator, 2026-09-05: *"report me how many trades where done how many failed
and whats reason and how many success and include emergency for trades that
should not be"*.
"""
import json
import time

from tradingagents import auto_trader as at, feedcheck as fc


def _write(tmp_path, monkeypatch, rows):
    monkeypatch.setattr(at, "LEDGER_PATH", tmp_path / "ledger.jsonl")
    at.LEDGER_PATH.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


NOW = time.time()


def test_the_window_starts_at_the_last_marker(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, [
        {"action": "exit", "why": "TP", "pnl_est": 1.0, "dry_run": True,
         "ts": NOW - 500},                                # before the marker
        {"action": fc.MARKER, "ts": NOW - 400},
        {"action": "enter", "dry_run": True, "ts": NOW - 300},
        {"action": "exit", "why": "TP", "pnl_est": 0.98, "dry_run": True,
         "ts": NOW - 200},
    ])
    got = fc.report(now=NOW)
    assert got["demo"]["entries"] == 1
    assert got["demo"]["closed"] == 1, "the pre-marker exit is NOT re-reported"
    assert got["demo"]["pnl"] == 0.98


def test_first_run_falls_back_to_24_hours(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, [
        {"action": "exit", "why": "SL", "pnl_est": -1.8, "dry_run": False,
         "ts": NOW - 3600},
        {"action": "exit", "why": "SL", "pnl_est": -9.9, "dry_run": False,
         "ts": NOW - 30 * 3600},                          # older than a day
    ])
    got = fc.report(now=NOW)
    assert got["live"]["losses"] == 1
    assert got["live"]["pnl"] == -1.8


def test_wins_losses_and_reasons_per_book(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, [
        {"action": "enter", "dry_run": False, "ts": NOW - 90,
         "symbol": "KITE_USDT"},
        {"action": "exit", "why": "TP", "pnl_est": 2.9, "dry_run": False,
         "ts": NOW - 80, "symbol": "KITE_USDT"},
        {"action": "exit", "why": "SL", "pnl_est": -3.1, "dry_run": True,
         "ts": NOW - 70, "symbol": "STBL_USDT"},
        {"action": "gate_blocked", "why": "round-trip cost 5% vs 1%",
         "dry_run": False, "ts": NOW - 60},
        {"action": "stale_skip", "dry_run": True, "ts": NOW - 50},
    ])
    got = fc.report(now=NOW)
    assert (got["live"]["wins"], got["live"]["losses"]) == (1, 0)
    assert got["live"]["win_reasons"] == {"TP": 1}
    assert (got["demo"]["wins"], got["demo"]["losses"]) == (0, 1)
    assert got["demo"]["loss_reasons"] == {"SL": 1}
    assert got["refused_total"] == 2
    assert "gate_blocked: round-trip cost 5% vs 1%" in got["refused"]
    assert "stale_skip" in got["refused"], "an empty why is not ': '"


def test_every_emergency_kind_is_caught_and_grouped(tmp_path, monkeypatch):
    rows = [
        {"action": "forced_close", "symbol": "PSXSTOCK_USDT",
         "why": "stop unplaceable (5003)", "ts": NOW - 100},
        {"action": "bracket_failed", "symbol": "PSXSTOCK_USDT",
         "why": "code 2009", "ts": NOW - 99},
        {"action": "exit", "why": "RECONCILED", "pnl_est": 0,
         "dry_run": False, "symbol": "KITE_USDT", "ts": NOW - 98},
        {"action": "blocked", "symbol": "GPNSTOCK_USDT",
         "why": "coin enabled on multiple timeframes", "ts": NOW - 97},
        # the PROVE class: a second REAL entry while one is held
        {"action": "enter", "dry_run": False, "symbol": "STBL_USDT",
         "strategy": "a", "ts": NOW - 96},
        {"action": "enter", "dry_run": False, "symbol": "STBL_USDT",
         "strategy": "b", "ts": NOW - 95},
    ]
    # the dead-guard row 500 times must be ONE group, not 500 lines
    rows += [{"action": "blocked", "symbol": "GPNSTOCK_USDT",
              "why": "coin enabled on multiple timeframes", "ts": NOW - 90 + i / 100}
             for i in range(499)]
    _write(tmp_path, monkeypatch, rows)
    got = fc.report(now=NOW)
    kinds = {g["what"][:20]: g["count"] for g in got["emergencies"]}
    assert len(got["emergencies"]) == 5, kinds
    dead = [g for g in got["emergencies"] if "nine-hour" in g["what"]][0]
    assert dead["count"] == 500, "grouped, not one line each"
    double = [g for g in got["emergencies"] if "SECOND real entry" in g["what"]]
    assert double and "a still held it, b entered" in double[0]["example"]


def test_a_demo_pair_on_one_coin_is_NOT_the_netting_emergency(tmp_path,
                                                              monkeypatch):
    """Two demo strategies on one coin is the operator's own design."""
    _write(tmp_path, monkeypatch, [
        {"action": "enter", "dry_run": True, "symbol": "GPNSTOCK_USDT",
         "strategy": "a", "ts": NOW - 96},
        {"action": "enter", "dry_run": True, "symbol": "GPNSTOCK_USDT",
         "strategy": "b", "ts": NOW - 95},
    ])
    assert fc.report(now=NOW)["emergencies"] == []


def test_the_marker_is_never_a_trade(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, [])
    monkeypatch.setattr(at, "STATE_PATH", tmp_path / "s.json", raising=False)
    fc.mark(NOW)
    assert at.strategy_stats(dry=True) == {}
    assert at.strategy_stats(dry=False) == {}
    assert at.pnl_today(dry=False)["total"] == 0.0
    got = fc.report(now=NOW + 10)
    assert got["hours"] == 0.0 or got["hours"] < 0.1


def test_a_row_on_the_markers_exact_second_is_not_double_reported(tmp_path,
                                                                  monkeypatch):
    _write(tmp_path, monkeypatch, [
        {"action": "exit", "why": "TP", "pnl_est": 1.0, "dry_run": True,
         "ts": NOW - 400},
        {"action": fc.MARKER, "ts": NOW - 400},
    ])
    assert fc.report(now=NOW)["demo"]["closed"] == 0
