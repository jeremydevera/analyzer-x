"""Tests may not write the operator's real pending list (RCA-2026-09-18-C).

On `Sep 18, 2026 3:10am` `~/.tradingagents/pending_candles.json` — the number
on the v1 Candles screen's RESOLVE button — held 11 rows, and every one was a
test fixture: C0_USDT..C7_USDT 1h (19 fails each, `IncompleteRead(183452
bytes read)`, the CLAUDE.md quote), FLAKY_USDT 15m (`timed out`), NAORIS_USDT
30m and MEZO_USDT 15m. `tests/test_download_retry.py` drove `_run_download`,
which records failures in the ledger, and the ledger's folder was never
sandboxed. The conftest sandbox now points `pending_ledger.STATE_DIR` at the
test's own folder, and this file — deliberately WITHOUT its own fixture —
proves the sandbox is what a test sees.
"""
from __future__ import annotations

from pathlib import Path

from tradingagents import pending_ledger as pl


def test_the_ledger_a_test_sees_is_not_the_operators():
    real = Path.home() / ".tradingagents"
    where = pl.path("candles")
    assert real != where.parent, where
    assert real not in where.parents, where


def test_recording_in_a_test_lands_in_the_sandbox():
    pl.record("candles", [("FIXTURE_USDT", "1h", "IncompleteRead(1 byte)")])
    assert [r["symbol"] for r in pl.pending("candles")] == ["FIXTURE_USDT"]
    assert pl.path("candles").exists()
    assert not (Path.home() / ".tradingagents" / "pending_candles.json").exists() or \
        "FIXTURE_USDT" not in (Path.home() / ".tradingagents" /
                               "pending_candles.json").read_text(encoding="utf-8")
