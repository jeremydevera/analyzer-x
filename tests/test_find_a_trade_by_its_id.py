"""Searching a trade id has to cross BOTH books, and search the LEDGER.

Operator, `Sep 17, 2026`: *"in trade history, put a id search there, when i
search LG9NSU4B for example it should show trade id LG9NSU4B for both live and
demo trade"*.

Why both books is the whole point: the live book and the practice book stamp a
trade with the SAME id. `MTX4FSGN` is one id on two trades — the real one was
closed at MEXC at `Sep 16, 2026 1:38pm` for −$0.84 and the practice one sold
itself at its target at `7:04pm` for +$0.17 — and a table that showed one of
them, with no column saying which, cost five answers before the operator could
see what had happened. So a search ignores the live/demo tab, and every row it
returns says which book it is on.

And it searches WHERE THE DATA IS. The route hands the browser five rows a
page; a `.filter()` in the component would search the page, not the book. That
is the rule CLAUDE.md bought with a KITE loss sitting 640 rows past the window
a panel had fetched, and this test exists so the search cannot be "simplified"
into the browser later.
"""
from __future__ import annotations

import json

import pytest

import tradingagents.auto_trader as at
from tradingagents import api

TRADE = "MTX4FSGN"
STRAT = "willr14_30m_sl2tp05"


def _exit(trade_id, symbol, pnl, ts, dry, strategy=STRAT):
    return {"action": "exit", "trade_id": trade_id, "symbol": symbol,
            "strategy": strategy, "pnl_est": pnl, "ts": ts, "dry_run": dry,
            "why": "TP" if pnl > 0 else "SL", "side": "LONG",
            "opened_at": ts - 3600, "held_s": 3600}


LEDGER = [
    # the operator's own shape: ONE id, two books, two different endings
    _exit(TRADE, "VUG_USDT", -0.84, 1_789_537_088.0, False),
    _exit(TRADE, "VUG_USDT", +0.17, 1_789_556_640.0, True),
    # and some noise either side
    _exit("AAAA1111", "STBL_USDT", +0.55, 1_789_500_000.0, True),
    _exit("BBBB2222", "CTC_USDT", +1.07, 1_789_400_000.0, False),
]


@pytest.fixture
def ledger(monkeypatch):
    monkeypatch.setattr(at, "ledger_tail", lambda n: list(LEDGER))
    monkeypatch.setattr(at, "load_settings", lambda: {
        "strategy_coins": {STRAT: ["VUG_USDT"]},
        "strategy_books": {STRAT: ["paper"]}})
    return LEDGER


# ------------------------------------------------ 1. the search itself
def test_one_id_brings_back_both_books(ledger):
    """The ask, exactly."""
    got = api.trade_history(q=TRADE, per_page=50)
    assert got["total"] == 2, got["rows"]
    assert sorted(r["book"] for r in got["rows"]) == ["demo", "live"]
    assert {r["id"] for r in got["rows"]} == {TRADE}


def test_the_tab_does_not_narrow_a_search(ledger):
    """`dry` still decides the tab, but a search overrules it — otherwise the
    operator sees one of the two copies and the other looks like it never
    happened."""
    for tab in (False, True):
        assert api.trade_history(dry=tab, q=TRADE, per_page=50)["total"] == 2


def test_the_strategy_id_is_searchable_too(ledger):
    """They typed a STRATEGY id in the ask (`LG9NSU4B`), not a trade id. Both
    have to work, because both are printed in this table."""
    sid = api.row_id_for(STRAT, "VUG_USDT", at.load_settings())
    assert sid, "the fixture has no strategy id to search for"
    got = api.trade_history(q=sid, per_page=50)
    assert got["total"] == 2
    assert all(r["strategy_id"] == sid for r in got["rows"])


def test_the_hash_and_the_case_are_both_optional(ledger):
    for typed in (TRADE.lower(), f"#{TRADE}", f" #{TRADE.lower()} "):
        assert api.trade_history(q=typed, per_page=50)["total"] == 2, typed


def test_no_search_is_one_book_as_before(ledger):
    assert api.trade_history(dry=False, per_page=50)["total"] == 2
    assert api.trade_history(dry=True, per_page=50)["total"] == 2
    assert api.trade_history(dry=False, per_page=50)["books"] == ["live"]
    assert api.trade_history(dry=True, per_page=50)["books"] == ["demo"]


# ------------------------------------- 2. the numbers beside the results
def test_the_running_total_stays_its_own_books(ledger):
    """A live exit must never advance the practice book's running total. The
    two rows of #MTX4FSGN end at −0.84 and +0.17 of their own books, not at
    one blended figure."""
    rows = {r["book"]: r for r in api.trade_history(q=TRADE, per_page=50)["rows"]}
    # the route rounds each step to the cent, so compare to the cent
    assert rows["live"]["running"] == 0.23, "1.07 then -0.84"
    assert rows["demo"]["running"] == 0.72, "0.55 then +0.17"


def test_the_summary_describes_the_MATCHES_not_the_whole_book(ledger):
    """label-must-match-data. A whole-book total printed beside two matched
    rows is a false label."""
    got = api.trade_history(q=TRADE, per_page=50)
    assert got["totals"]["trades"] == 2
    assert got["totals"]["wins"] == 1 and got["totals"]["losses"] == 1
    assert got["totals"]["profit"] == round(-0.84 + 0.17, 2)


def test_an_empty_result_says_what_it_examined(ledger):
    """An empty page may never speak for the store: it reports how many closed
    trades it actually looked at."""
    got = api.trade_history(q="ZZZZZZZZ", per_page=50)
    assert got["total"] == 0
    assert got["examined"] == len(LEDGER), got
    assert got["q"] == "ZZZZZZZZ"


# ------------------------------------- 3. it is searched where the data is
def test_the_search_is_a_query_not_a_browser_filter():
    """The route sends five rows a page. A `.filter()` in the component would
    search the PAGE, which is how a KITE loss 640 rows deep went missing."""
    p = open("webapp/src/components/trade/TradeHistory.tsx",
             encoding="utf-8").read()
    assert "tradeApi.history(dry, page, 5, q.trim())" in p, \
        "the typed id is not being sent to the server"
    body = p[p.index("const [q, setQ]"):]
    assert ".filter(" not in body.split("return (")[0], \
        "the component is filtering rows it was already handed"
    assert "q=${encodeURIComponent(q)}" in open(
        "webapp/src/lib/api.ts", encoding="utf-8").read()


def test_every_row_says_which_book_it_is_on():
    p = open("webapp/src/components/trade/TradeHistory.tsx",
             encoding="utf-8").read()
    assert "HEADS_SEARCH" in p and '"book"' in p, \
        "two books in one table and no column saying which"
    assert 'r.book === "demo"' in p


def test_the_page_resets_when_the_search_changes():
    """Page 4 of the old result is not page 4 of the new one."""
    p = open("webapp/src/components/trade/TradeHistory.tsx",
             encoding="utf-8").read()
    assert "setPage(1); }, [dry, q]" in p
