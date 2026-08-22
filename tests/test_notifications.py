"""The bell: a local event feed, and it must never break the caller.

Operator, 2026-08-21: "when i click download i want to show if it was success,
give me download history / create notification icon beside night mode ... i
want to see if download, backtest, open trade was made".

Pure local (SQLite beside the ledger) — the operator's standing rule, recorded
twice in local_history.py: "i said i want all local machine".
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def nt(tmp_path, monkeypatch):
    from tradingagents import notifications as mod
    importlib.reload(mod)
    monkeypatch.setattr(mod, "DB_PATH", tmp_path / "n.db")
    return mod


def test_it_records_and_reads_back_newest_first(nt):
    nt.record("download", "one")
    nt.record("backtest", "two")
    rows = nt.recent()
    assert [r["title"] for r in rows] == ["two", "one"]


def test_a_failure_is_marked_not_guessed(nt):
    nt.record("backtest", "boom", ok=False, detail="inconsistent keys")
    r = nt.recent()[0]
    assert r["ok"] is False and "inconsistent" in r["detail"]


def test_unread_count_and_mark_all(nt):
    for i in range(3):
        nt.record("download", f"d{i}")
    assert nt.unread_count() == 3
    assert nt.mark_read() == 3
    assert nt.unread_count() == 0
    assert all(r["read"] for r in nt.recent())


def test_mark_read_can_target_one_event(nt):
    a = nt.record("download", "a")
    nt.record("download", "b")
    assert nt.mark_read([a]) == 1
    assert nt.unread_count() == 1


def test_filtering_by_kind(nt):
    nt.record("download", "d")
    nt.record("trade_open", "t")
    assert [r["kind"] for r in nt.recent(kind="download")] == ["download"]


def test_meta_round_trips(nt):
    nt.record("download", "d", meta={"pairs": 3, "bars": 2892})
    assert nt.recent()[0]["meta"]["bars"] == 2892


def test_record_NEVER_raises_even_on_an_unusable_store(nt, monkeypatch):
    """It is called from the live trading loop. A feed write failing must not
    be able to interrupt an order, a bracket, or an exit."""
    monkeypatch.setattr(nt, "DB_PATH", nt.Path("/nonexistent-dir/x/y.db"))
    assert nt.record("trade_open", "LONG PI") == 0        # reports failure
    assert nt.recent() == [] and nt.unread_count() == 0   # and stays quiet


def test_prune_keeps_the_newest(nt):
    for i in range(12):
        nt.record("download", f"d{i}")
    nt.prune(keep=5)
    rows = nt.recent(50)
    assert len(rows) == 5 and rows[0]["title"] == "d11"


def test_the_trading_loop_emits_open_and_close():
    """The emitters must be wired where the money moves, and wrapped."""
    src = open("tradingagents/auto_trader.py", encoding="utf-8").read()
    assert src.count('_nt.record(') >= 2
    assert '"trade_open"' in src and '"trade_close"' in src
    # every call site is inside a try/except so it cannot raise into the loop
    for frag in ('_nt.record(\n                "trade_open"',
                 '_nt.record(\n                    "trade_close"'):
        i = src.find(frag)
        assert i > 0, frag
        assert "try:" in src[max(0, i - 400):i]


def test_the_jobs_emit_download_and_backtest():
    src = open("tradingagents/db_jobs.py", encoding="utf-8").read()
    assert '"download",' in src and '"backtest",' in src
    assert "Backtest FAILED" in src, "a dead job must also speak"


def test_the_suite_can_never_write_the_operators_real_bell():
    """One suite run put 30 fixture trades into the live notification store,
    the same class of mistake as the run that wrote 43 fake XAUT rows into the
    live ledger. The sandbox must cover this path."""
    from tradingagents import notifications as nt

    real = str(nt.Path("~/.tradingagents/notifications.db").expanduser())
    assert str(nt.DB_PATH) != real, (
        "DB_PATH still points at the operator's real feed during tests — "
        "add it to the sandbox in tests/conftest.py")
    assert "tradingagents_state" in str(nt.DB_PATH) or "tmp" in str(nt.DB_PATH)
