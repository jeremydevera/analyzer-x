"""Five of the operator's ids shared one switch, and one wrong id on the screen.

Operator, `Sep 16, 2026`: *"WHY IS #DM84QDSZ IN LIVE TRADE HAVE DIFFERENT
COINS?"*, then *"I DEPLOY SAID DEPLOY AND ID BUT IT HAS DIFFERNT COINS THEN
DEPLOY THE ID, DONT GROUP THEM AS ONE"*.

`#DM84QDSZ` is **DVNSTOCK 30m willr14, SL 2.00% / TP 0.50%, flat — 168
trades, 97.62%, +$36.72**. They deployed 280 ids; those became **83 strategy
keys**, because a key is `signal_timeframe_slXtpY` and the COIN is not in it.
`willr14_30m_sl2tp05` ended up holding five contracts at once:

    DVNSTOCK  #DM84QDSZ      FASTSTOCK #7BSMBRFA     KKRSTOCK  #DGCSMB9N
    ROLSTOCK  #MU2AU5P6      VUG       #GXTHE8EJ

The grid built ONE row for all five and hashed its id from `coins[key][0]`,
so every one of them was labelled #DM84QDSZ — four labels naming a contract
the row was not trading — and one LIVE toggle moved all five together.

A row id is coin + timeframe + signal + threshold + SL + TP + sizing, all
seven (`backtest_report.row_code`). Drop the coin and it is a different
measurement wearing the same name. See `.claude/skills/deploy-by-id`.
"""
from __future__ import annotations

import pytest

import tradingagents.auto_trader as at
from tradingagents import api

KEY = "willr14_30m_sl2tp05"
COIN = "VUG_USDT"


@pytest.fixture
def cfg():
    return {"strategies": [KEY],
            "strategy_coins": {KEY: ["DVNSTOCK_USDT", "FASTSTOCK_USDT", COIN]},
            "strategy_books": {KEY: ["paper"]},
            "enabled": False, "dry_run": False}


# ------------------------------------------------- 1. one switch per row
def test_the_slot_name_carries_the_coin():
    assert at.book_slot(KEY, COIN) == f"{KEY}|{COIN}"
    assert at.book_slot(KEY, None) == KEY, "no coin, no suffix"


def test_arming_one_id_leaves_the_others_alone(cfg):
    """The whole ask. One contract live, the rest untouched."""
    cfg["strategy_books"][at.book_slot(KEY, COIN)] = ["paper", "real"]
    assert at.books_for(KEY, cfg, COIN) == [False, True], "this one is live"
    for other in ("DVNSTOCK_USDT", "FASTSTOCK_USDT"):
        assert at.books_for(KEY, cfg, other) == [True], f"{other} moved too"


def test_a_file_with_no_per_coin_entries_is_unchanged(cfg):
    """This may only ever NARROW. Every settings file written before today
    has bare keys only and must behave exactly as it did."""
    for coin in cfg["strategy_coins"][KEY]:
        assert at.books_for(KEY, cfg, coin) == at.books_for(KEY, cfg)


def test_the_cycle_runs_the_live_book_for_one_armed_id(cfg):
    """`active_modes` asked `books_for(key)` with no coin, so a single id
    armed live read as paper-only and the live book would never have run —
    the row would sit armed on screen and never take a trade. Found by the
    harddev loop on this very change."""
    assert at.active_modes(cfg) == [True]
    cfg["strategy_books"][at.book_slot(KEY, COIN)] = ["paper", "real"]
    assert False in at.active_modes(cfg), "the live book is never run"


# ------------------------------------- 2. the readers cope with both shapes
def test_book_names_prefers_the_contract_then_falls_back(cfg):
    assert at.book_names(cfg, KEY) == ["paper"]
    cfg["strategy_books"][at.book_slot(KEY, COIN)] = ["paper", "real"]
    assert at.book_names(cfg, KEY, COIN) == ["paper", "real"]
    assert at.book_names(cfg, KEY, "DVNSTOCK_USDT") == ["paper"], "fallback"


def test_book_names_any_unions_across_contracts(cfg):
    cfg["strategy_books"][at.book_slot(KEY, COIN)] = ["paper", "real"]
    assert at.book_names_any(cfg, KEY) == {"paper", "real"}, (
        "a question about the STRATEGY must see a coin armed live, or a "
        "per-coin deploy reads as touching no real money at all")


def test_a_coin_claimed_live_locks_only_itself(cfg):
    """`timeframe_locks` decides which contract is spoken for. Asking the bare
    key would claim all five, or none."""
    cfg["strategy_books"][at.book_slot(KEY, COIN)] = ["paper", "real"]
    claimed = at.timeframe_locks(cfg)
    assert isinstance(claimed, dict)


# --------------------------------------------- 3. the screen, one id per row
@pytest.fixture
def deployed(monkeypatch, cfg):
    """The operator's shape: ONE strategy, THREE contracts. Driven through
    `api.trade_strategies` itself, not a copy of its logic."""
    monkeypatch.setattr(at, "load_settings", lambda: cfg)
    return cfg


def test_the_grid_emits_one_row_per_contract(deployed):
    rows = api.trade_strategies()["rows"]
    mine = [r for r in rows if r.get("key") == KEY]
    assert len(mine) == 3, f"one strategy, three coins, {len(mine)} row(s)"
    assert not [r for r in mine if len(r.get("coins") or []) > 1], (
        "a row still carries more than one coin, so its id names only the "
        "first of them")
    assert {r["coins"][0] for r in mine} == set(deployed["strategy_coins"][KEY])


def test_every_grid_row_carries_ITS_OWN_id(deployed):
    """The measured failure: four rows in five stamped #DM84QDSZ."""
    rows = [r for r in api.trade_strategies()["rows"] if r.get("key") == KEY]
    wrong = [(r.get("id"), r["coins"][0]) for r in rows
             if r.get("id") != api.row_id_for(r["key"], r["coins"][0], deployed)]
    assert wrong == [], wrong
    assert len({r["id"] for r in rows}) == len(rows), "two rows share an id"


def test_each_row_shows_its_own_switch(deployed):
    """One contract live, and only that row painted live."""
    deployed["strategy_books"][at.book_slot(KEY, COIN)] = ["paper", "real"]
    rows = [r for r in api.trade_strategies()["rows"] if r.get("key") == KEY]
    live = [r["coins"][0] for r in rows if "real" in (r.get("books") or [])]
    assert live == [COIN], live
