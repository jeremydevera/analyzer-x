"""The demo cell counted 69W/3L while the ledger held 30W/6L.

Operator, `Sep 16, 2026`, choosing how the demo win/loss cell should be drawn.
Before drawing anything the NUMBER had to be right, and it was not.

Measured on their own machine that morning:

    ledger, demo exits only        36 closed trades, 30 W, 6 L, +1.84 USDT
    counted per (strategy, coin)   26 rows, most trades on any one row: 3
    what /api/trade/strategies     69 W, 3 L
    printed across the demo rows

`strategy_stats` groups the ledger by `e["strategy"]`, and a strategy KEY is
`signal_timeframe_slXtpY` — the coin is not in it. So `willr14_30m_sl2tp05`,
armed on DVNSTOCK, FASTSTOCK, KKRSTOCK, ROLSTOCK and VUG, summed all five
contracts into one record and the grid printed that same total on each of the
five rows. Five rows of one trade each read as five rows of five.

This is the SECOND half of the id bug fixed the day before
(`test_one_id_is_one_switch.py`): that one gave each contract its own id and
its own switch, this one gives it its own record. See
`.claude/skills/deploy-by-id` — a row id is coin + timeframe + signal +
threshold + SL + TP + sizing, all seven.

The default stays per strategy ON PURPOSE. `tripped_strategies` reads
`pnl_today_by_strategy` to enforce a strategy's daily loss cap; splitting that
per coin would multiply the cap by the number of contracts it is armed on,
which is a trading change wearing a display fix's clothes.
"""
from __future__ import annotations

import json

import pytest

import tradingagents.auto_trader as at
from tradingagents import api

KEY = "willr14_30m_sl2tp05"
COINS = ["DVNSTOCK_USDT", "FASTSTOCK_USDT", "VUG_USDT"]


def _exit(strategy: str, symbol: str, pnl: float, ts: float = 1_789_500_000.0,
          dry: bool = True) -> dict:
    return {"action": "exit", "strategy": strategy, "symbol": symbol,
            "pnl_est": pnl, "ts": ts, "dry_run": dry}


# one WIN on each of three contracts of ONE strategy — the operator's shape
LEDGER = [_exit(KEY, "DVNSTOCK_USDT", 0.16),
          _exit(KEY, "FASTSTOCK_USDT", 0.16),
          _exit(KEY, "VUG_USDT", -0.40)]


@pytest.fixture
def ledger(monkeypatch):
    monkeypatch.setattr(at, "ledger_since", lambda ts: list(LEDGER))
    return LEDGER


# ------------------------------------------------- 1. the source of the count
def test_the_record_can_be_asked_for_by_contract(ledger):
    got = at.strategy_stats(dry=True, by_coin=True)
    assert set(got) == {at.book_slot(KEY, c) for c in COINS}
    assert got[at.book_slot(KEY, "DVNSTOCK_USDT")]["wins"] == 1
    assert got[at.book_slot(KEY, "DVNSTOCK_USDT")]["losses"] == 0
    assert got[at.book_slot(KEY, "VUG_USDT")]["losses"] == 1


def test_the_default_is_still_the_whole_strategy(ledger):
    """`tripped_strategies` depends on this. A per-coin split would raise a
    strategy's daily loss cap by however many contracts it holds."""
    got = at.strategy_stats(dry=True)
    assert set(got) == {KEY}
    assert (got[KEY]["wins"], got[KEY]["losses"]) == (2, 1)


def test_todays_pnl_takes_the_same_switch(ledger, monkeypatch):
    monkeypatch.setattr(at, "ledger_since", lambda ts: list(LEDGER))
    per_coin = at.pnl_today_by_strategy(now=1_789_500_100.0, dry=True,
                                        by_coin=True)
    whole = at.pnl_today_by_strategy(now=1_789_500_100.0, dry=True)
    assert at.book_slot(KEY, "VUG_USDT") in per_coin
    assert set(whole) == {KEY}, "the loss-cap reading must not move"
    assert round(sum(per_coin.values()), 2) == round(whole[KEY], 2)


# --------------------------------------------------- 2. the row reads its own
def test_a_row_reads_only_its_own_contract():
    stats = {f"{KEY}|DVNSTOCK_USDT": {"wins": 1, "losses": 0, "trades": 1,
                                      "pnl": 0.16},
             f"{KEY}|VUG_USDT": {"wins": 0, "losses": 1, "trades": 1,
                                 "pnl": -0.40}}
    mine = api._slot_stats(stats, KEY, "VUG_USDT")
    assert (mine["wins"], mine["losses"]) == (0, 1)
    assert mine["pnl"] == -0.40, "it read another contract's money"


def test_a_row_with_no_coin_sums_the_whole_strategy():
    """Only the catalog listing has no coin. Showing nothing there would hide
    a strategy's whole history behind a contract it has not been given yet."""
    stats = {f"{KEY}|DVNSTOCK_USDT": {"wins": 1, "losses": 0, "trades": 1,
                                      "pnl": 0.16},
             f"{KEY}|VUG_USDT": {"wins": 0, "losses": 1, "trades": 1,
                                 "pnl": -0.40}}
    got = api._slot_stats(stats, KEY, None)
    assert (got["wins"], got["losses"], got["trades"]) == (1, 1, 2)
    assert got["pnl"] == -0.24
    assert got["winrate"] == 50.0


def test_a_prefix_is_not_a_match():
    """`willr14_30m_sl2tp05` must never absorb `willr14_30m_sl2tp05b`."""
    stats = {f"{KEY}|A_USDT": {"wins": 1, "losses": 0, "trades": 1, "pnl": 1.0},
             f"{KEY}b|A_USDT": {"wins": 9, "losses": 9, "trades": 18,
                                "pnl": 99.0}}
    got = api._slot_stats(stats, KEY, None)
    assert (got["wins"], got["losses"]) == (1, 0), got


# ----------------------------------------------------------- 3. end to end
@pytest.fixture
def deployed(monkeypatch, ledger):
    at.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    at.SETTINGS_PATH.write_text(json.dumps({
        "strategies": [KEY],
        "strategy_coins": {KEY: COINS},
        "strategy_books": {KEY: ["paper"]},
        "enabled": False}))
    monkeypatch.setattr(at, "load_state", lambda: {})
    return COINS


def test_three_contracts_do_not_all_print_the_same_record(deployed):
    """The measured failure, at the route. One win each, not three each."""
    rows = [r for r in api.trade_strategies()["rows"] if r["key"] == KEY]
    assert len(rows) == 3
    got = {r["coins"][0]: (r["paper"]["wins"], r["paper"]["losses"])
           for r in rows}
    assert got == {"DVNSTOCK_USDT": (1, 0),
                   "FASTSTOCK_USDT": (1, 0),
                   "VUG_USDT": (0, 1)}, got


def test_the_totals_add_up_to_the_ledger(deployed):
    """label-must-match-data, as a sum: the rows on screen must add to what
    the ledger holds, or the cell is inventing trades. 69 against 36 is how
    this was found."""
    rows = [r for r in api.trade_strategies()["rows"] if r["key"] == KEY]
    assert sum(r["paper"]["wins"] for r in rows) == 2
    assert sum(r["paper"]["losses"] for r in rows) == 1
    assert sum(r["paper"]["trades"] for r in rows) == len(LEDGER)


def test_the_row_reads_the_book_its_own_contract_is_armed_on(deployed,
                                                             monkeypatch):
    """`_is_real` was `"real" in books[key]` — the bare key. After the switch
    went per contract, one coin armed live would have drawn the live ladder
    and the live record on all three."""
    at.SETTINGS_PATH.write_text(json.dumps({
        "strategies": [KEY],
        "strategy_coins": {KEY: COINS},
        "strategy_books": {KEY: ["paper"],
                           at.book_slot(KEY, "VUG_USDT"): ["real"]},
        "enabled": False}))
    rows = {r["coins"][0]: r for r in api.trade_strategies()["rows"]
            if r["key"] == KEY}
    assert rows["VUG_USDT"]["streak_book"] == "real"
    assert rows["DVNSTOCK_USDT"]["streak_book"] == "paper"
    # the LIVE row has no live trades in this ledger, so its own record is empty
    assert rows["VUG_USDT"]["trades"] == 0, \
        "a live-armed contract must not print the demo book's record"
    assert rows["DVNSTOCK_USDT"]["trades"] == 1


# ------------------------------------------------- 4. the caption over the grid
def test_the_caption_counts_rows_not_strategy_keys(deployed):
    """The same fault one level up. These counters read `books.get(key)` — the
    bare strategy key — which stopped holding the switch when arming went per
    contract, so the operator's screen said *"0 trading REAL money · 0 paper
    only · 85 deployed but switched off"* over 120 rows that were all armed
    demo."""
    got = api.trade_strategies()
    rows = [r for r in got["rows"] if r["key"] == KEY]
    assert got["paper_count"] == len(rows) == 3
    assert got["real_count"] == 0
    assert got["idle_count"] == 0, "an armed row is not switched off"
    assert got["deployed_count"] == 3


def test_one_contract_live_moves_only_one_count(deployed):
    at.SETTINGS_PATH.write_text(json.dumps({
        "strategies": [KEY],
        "strategy_coins": {KEY: COINS},
        "strategy_books": {KEY: ["paper"],
                           at.book_slot(KEY, "VUG_USDT"): ["real"]},
        "enabled": False}))
    got = api.trade_strategies()
    assert (got["real_count"], got["paper_count"]) == (1, 2)
