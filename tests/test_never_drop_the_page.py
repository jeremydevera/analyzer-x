"""The app must never remove an index the screen is about to need.

Operator, 2026-08-27 12:48am: "why does it not show anything". The Stored
strategies list was empty and even the DEFAULT order answered

    503  "ranking by profit needs its index (rows_profit); it is being built"

because the indexer had just finished a 500+ pair fill and, per the BIG_FILL
exception added hours earlier, had dropped rows_profit, rows_coin and
rows_winrate to reload faster. The guard then refused every query for the
~25 minutes the three rebuilds took, so the page had nothing at all on it.

A slow page is a bad page; an empty one is a broken product. The app now drops
NOTHING — a rebuild-from-the-pair-files is a deliberate, offline operation and
can drop indexes itself if it wants the speed.
"""
import inspect

from tradingagents import rows_index as ri


def test_sync_never_drops_an_index():
    src = inspect.getsource(ri.sync)
    assert "DROP INDEX" not in src, \
        "the indexer must not remove an index the screen orders by"


def test_the_page_orders_are_all_kept():
    kept = " ".join(ri.KEEP_INDEXES)
    for name in ("rows_pair", "rows_profit", "rows_coin", "rows_winrate"):
        assert name in kept, name
    assert ri.FILTER_INDEXES == {}, "nothing is droppable any more"


def test_a_fill_still_reports_what_it_did(tmp_path, monkeypatch):
    import json
    import time

    from tradingagents import market_sweep as msw

    rows_dir = tmp_path / "rows"
    rows_dir.mkdir()
    monkeypatch.setattr(msw, "ROWDIR", rows_dir)
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    ri._ready.discard(str(tmp_path / "rows.db"))
    row = {"coin": "BTC", "tf": "1h", "signal": "mom6", "th": 0.1, "sl": 0.3,
           "tp": 0.9, "rr": 3.0, "sizing": "flat", "lev": 20, "base": 5.0,
           "notional": 100.0, "trades": 120, "wins": 60, "losses": 60,
           "winrate": 50.0, "profit": 1.0, "funding": 0.0, "h1": 1.0, "h2": 1.0,
           "green": 1, "months": 1, "worst": -1.0, "dd": 1.0, "liqs": 0,
           "stop_reachable": True, "days": 90, "bars": 2000, "monthly": {},
           "cost_of_tp": 1.0, "rt": 0.01, "gate": "ok"}
    (rows_dir / "BTC-1h.json").write_text(json.dumps([row]))
    got = ri.sync(now=time.time() + ri.SETTLE_S + 1)
    assert got["pairs"] == 1
    # and every index the screen needs is STILL there afterwards
    ri.forget_indexes()
    for name in ("rows_profit", "rows_coin", "rows_winrate"):
        assert ri.has_index(name) is True, name
