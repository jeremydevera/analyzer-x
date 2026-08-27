"""A deployed row shows BOTH records: what it did live and what it did on demo.

Operator, 2026-08-27: *"can you add w/L for demo in stratragies you deployed
section"*.

The row carried ONE record — its own book — so a strategy ticked LIVE showed
nothing of what its demo had done, which is the whole reason to run both.

A label bug sat in the same lines: `today $` was
`pnl_today_by_strategy(dry=False)` for EVERY row, so a demo-only row printed
the REAL book's today. That is 0.00 for a strategy that has never traded real
money, however well its demo did — a true number under a false label, the
2026-08-14 shape.

What must never happen: the two records blending. `strategy_stats(dry=...)`
keeps them apart at the source ("real and paper must never be blended into one
record the operator judges a strategy by"), and this file checks the route
keeps them apart too.
"""
import json

import pytest

from tradingagents import auto_trader as at

LIVE_KEY, DEMO_KEY = "fvg_1h_sl25tp25", "stoch14_1h_sl3tp3"


@pytest.fixture
def books(tmp_path, monkeypatch):
    """One row on the real book, one on demo, each with its own exits."""
    monkeypatch.setattr(at, "LEDGER_PATH", tmp_path / "ledger.jsonl")
    now = 1_787_800_000
    rows = [
        # the LIVE row: two wins, one loss
        {"ts": now, "action": "exit", "symbol": "TREE_USDT",
         "strategy": LIVE_KEY, "pnl_est": 2.50, "dry_run": False},
        {"ts": now, "action": "exit", "symbol": "TREE_USDT",
         "strategy": LIVE_KEY, "pnl_est": 1.75, "dry_run": False},
        {"ts": now, "action": "exit", "symbol": "TREE_USDT",
         "strategy": LIVE_KEY, "pnl_est": -2.60, "dry_run": False},
        # the DEMO row: one win, three losses
        {"ts": now, "action": "exit", "symbol": "LYN_USDT",
         "strategy": DEMO_KEY, "pnl_est": 3.10, "dry_run": True},
        {"ts": now, "action": "exit", "symbol": "LYN_USDT",
         "strategy": DEMO_KEY, "pnl_est": -3.15, "dry_run": True},
        {"ts": now, "action": "exit", "symbol": "LYN_USDT",
         "strategy": DEMO_KEY, "pnl_est": -3.15, "dry_run": True},
        {"ts": now, "action": "exit", "symbol": "LYN_USDT",
         "strategy": DEMO_KEY, "pnl_est": -3.10, "dry_run": True},
        # and the LIVE row also ran on demo — the case the screen could not show
        {"ts": now, "action": "exit", "symbol": "TREE_USDT",
         "strategy": LIVE_KEY, "pnl_est": 4.20, "dry_run": True},
        {"ts": now, "action": "exit", "symbol": "TREE_USDT",
         "strategy": LIVE_KEY, "pnl_est": 4.20, "dry_run": True},
    ]
    at.LEDGER_PATH.write_text("".join(json.dumps(r) + "\n" for r in rows),
                              encoding="utf-8")
    return rows


def test_the_source_keeps_the_two_books_apart(books):
    real = at.strategy_stats(dry=False)
    paper = at.strategy_stats(dry=True)
    assert (real[LIVE_KEY]["wins"], real[LIVE_KEY]["losses"]) == (2, 1)
    assert (paper[LIVE_KEY]["wins"], paper[LIVE_KEY]["losses"]) == (2, 0)
    assert (paper[DEMO_KEY]["wins"], paper[DEMO_KEY]["losses"]) == (1, 3)
    assert DEMO_KEY not in real, "a demo-only strategy has no live record"
    # and nothing is blended
    both = at.strategy_stats()
    assert both[LIVE_KEY]["wins"] == 4, "unfiltered is the sum, by design"


def test_the_route_carries_both_records_per_row(books, monkeypatch):
    from tradingagents import api

    monkeypatch.setattr(at, "load_settings", lambda: {
        "strategies": [LIVE_KEY, DEMO_KEY],
        "strategy_coins": {LIVE_KEY: ["TREE_USDT"], DEMO_KEY: ["LYN_USDT"]},
        "strategy_books": {LIVE_KEY: ["real"], DEMO_KEY: ["paper"]},
        "strategy_margins": {LIVE_KEY: 5.0, DEMO_KEY: 5.0},
        "strategy_sizing": {LIVE_KEY: "flat", DEMO_KEY: "flat"},
    })
    got = {r["key"]: r for r in api.trade_strategies()["rows"]}

    live = got[LIVE_KEY]
    assert (live["real"]["wins"], live["real"]["losses"]) == (2, 1)
    assert live["real"]["armed"] is True
    # the record the screen could not show before
    assert (live["paper"]["wins"], live["paper"]["losses"]) == (2, 0)
    assert live["paper"]["armed"] is False, "it is not running on demo"
    assert live["paper"]["pnl"] == pytest.approx(8.40)

    demo = got[DEMO_KEY]
    assert (demo["paper"]["wins"], demo["paper"]["losses"]) == (1, 3)
    assert demo["paper"]["armed"] is True
    assert (demo["real"]["wins"], demo["real"]["losses"]) == (0, 0)
    assert demo["real"]["armed"] is False


def test_the_own_book_fields_still_say_what_they_always_did(books, monkeypatch):
    """`pnl`/`wins`/`losses` remain the row's OWN book, so every existing
    reader is unchanged."""
    from tradingagents import api

    monkeypatch.setattr(at, "load_settings", lambda: {
        "strategies": [LIVE_KEY, DEMO_KEY],
        "strategy_coins": {LIVE_KEY: ["TREE_USDT"], DEMO_KEY: ["LYN_USDT"]},
        "strategy_books": {LIVE_KEY: ["real"], DEMO_KEY: ["paper"]},
    })
    got = {r["key"]: r for r in api.trade_strategies()["rows"]}
    assert (got[LIVE_KEY]["wins"], got[LIVE_KEY]["losses"]) == (2, 1)
    assert (got[DEMO_KEY]["wins"], got[DEMO_KEY]["losses"]) == (1, 3)


def test_today_follows_the_book_it_belongs_to(monkeypatch, tmp_path):
    """A demo-only row printed the REAL book's today — 0.00 for a strategy
    that has never traded real money."""
    monkeypatch.setattr(at, "LEDGER_PATH", tmp_path / "ledger.jsonl")
    import time

    now = time.time()
    at.LEDGER_PATH.write_text("".join(json.dumps(r) + "\n" for r in [
        {"ts": now, "action": "exit", "symbol": "LYN_USDT",
         "strategy": DEMO_KEY, "pnl_est": 6.25, "dry_run": True},
        {"ts": now, "action": "exit", "symbol": "TREE_USDT",
         "strategy": LIVE_KEY, "pnl_est": -1.10, "dry_run": False},
    ]), encoding="utf-8")

    from tradingagents import api

    monkeypatch.setattr(at, "load_settings", lambda: {
        "strategies": [LIVE_KEY, DEMO_KEY],
        "strategy_coins": {LIVE_KEY: ["TREE_USDT"], DEMO_KEY: ["LYN_USDT"]},
        "strategy_books": {LIVE_KEY: ["real"], DEMO_KEY: ["paper"]},
    })
    got = {r["key"]: r for r in api.trade_strategies()["rows"]}
    assert got[DEMO_KEY]["today"] == pytest.approx(6.25), \
        "the demo row's today must be its DEMO book"
    assert got[LIVE_KEY]["today"] == pytest.approx(-1.10)
    assert got[DEMO_KEY]["paper"]["today"] == pytest.approx(6.25)
    assert got[DEMO_KEY]["real"]["today"] == 0.0


def test_the_screen_names_which_book_each_column_is():
    """Two money columns side by side have to say which is which, or the
    operator reads a demo profit as real money."""
    src = (open("webapp/src/components/trade/StrategiesGrid.tsx",
                encoding="utf-8").read())
    assert '["LIVE $ · W/L", "9%"]' in src
    assert '["DEMO $ · W/L", "9%"]' in src
    assert '["PROFIT $", "6%"]' not in src, "the unlabelled column is gone"
    assert '[["real", r.real], ["paper", r.paper]]' in src
    # an unarmed book must not read as "no wins"
    assert "not armed" in src and "opacity-45" in src
