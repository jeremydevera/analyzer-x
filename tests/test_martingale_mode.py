"""Martingale mode: double after a loss, back to base after a win.

Operator, `Sep 17, 2026`: *"create a checkbox in auto trade 'Martingale mode'
meaning if the past trade lose, double the margin, if it won then return to
original set margin"*, and *"i want check for live and demo"*.

This REVERSES their `Sep 11, 2026` instruction (*"you will not double anything
in martingale, just flat only"*), so the flat rule is now what the switch OFF
means — `tests/test_runner_stakes_flat.py` holds that half and both halves have
to pass together.

Three things this file exists to stop:

* **A missing setting must be OFF.** Every config written between Sep 11 and
  Sep 17 has neither key, and an absent switch that read as ON would double
  real money on a machine nobody touched.
* **The two books are separate.** Ticking DEMO must not stake a cent more on
  the real book, which is the whole point of having two checkboxes.
* **The screen and the order agree.** The grid's "next $" is asked of the same
  function the runner stakes with, so the column cannot say $5 while the order
  sends $40 — and nothing is silently capped, because a stake the wallet
  cannot fund is refused out loud by the capital gate rather than sized down.

The ladder here is NOT `LADDER` (1,1,2,2,4,4,8), which doubles every SECOND
loss and belongs to the backtest engine. It is what they described: 1, 2, 4,
8, 16 — one doubling per loss in a row.
"""
from __future__ import annotations

import inspect

import pytest

from tradingagents import auto_trader as at
from tradingagents import api

KEY = "macddiv_4h_sl25tp3"
BASE = {"strategy_margins": {KEY: 5.0}, "margin": 5.0}
LIVE = dict(BASE, martingale_live=True)
DEMO = dict(BASE, martingale_demo=True)


# ------------------------------------------------------------- the stake
def test_it_doubles_once_for_every_loss_in_a_row():
    """Their own words, at their own $5 base."""
    got = [at.staked_margin(KEY, LIVE, n, False) for n in range(6)]
    assert got == [5.0, 10.0, 20.0, 40.0, 80.0, 160.0], got


def test_a_win_puts_it_straight_back_to_the_base():
    """The runner already zeroes `step` on a win, so rung 0 IS 'after a win'."""
    assert at.staked_margin(KEY, LIVE, 0, False) == 5.0


def test_it_is_not_the_backtests_ladder():
    """`LADDER` doubles every SECOND loss (1,1,2,2,4,4,8). Using it here would
    make the screen's next stake disagree with what the operator described."""
    assert at.LADDER[1] == 1, "the backtest ladder is unchanged"
    assert at.staked_margin(KEY, LIVE, 1, False) == 10.0, \
        "one loss must double it, not hold it"


def test_a_row_with_its_own_margin_doubles_from_ITS_base():
    cfg = dict(LIVE, strategy_margins={KEY: 1.0})
    assert [at.staked_margin(KEY, cfg, n, False) for n in range(4)] == \
        [1.0, 2.0, 4.0, 8.0]


# ------------------------------------------------------- two switches
def test_off_is_the_default_on_both_books():
    for dry in (False, True):
        assert at.martingale_on({}, dry) is False
        assert [at.staked_margin(KEY, BASE, n, dry) for n in range(5)] == [5.0] * 5


def test_demo_on_does_not_stake_a_cent_more_on_real_money():
    """The point of two checkboxes: try it on the practice book first."""
    assert [at.staked_margin(KEY, DEMO, n, True) for n in range(4)] == \
        [5.0, 10.0, 20.0, 40.0]
    assert [at.staked_margin(KEY, DEMO, n, False) for n in range(4)] == [5.0] * 4


def test_live_on_does_not_change_the_practice_book():
    assert [at.staked_margin(KEY, LIVE, n, True) for n in range(4)] == [5.0] * 4


# --------------------------------------------- the label still cannot do it
def test_only_the_checkbox_can_double_a_stake():
    """A row LABELLED martingale, with the checkbox off, stakes flat. This is
    the 2026-08-17 lesson and it survives the reversal: a config taken from a
    flat-only survivor list was deployed with the ladder on and went from
    +$141 to -$21 with a $339 drawdown on a $65 account."""
    labelled = dict(BASE, sizing="martingale",
                    strategy_sizing={KEY: "martingale"})
    assert [at.staked_margin(KEY, labelled, n, False) for n in range(5)] == [5.0] * 5
    body = inspect.getsource(at.staked_margin).split('"""')[-1]
    assert "sizing_for(" not in body and "LADDER" not in body


# ------------------------------------------- the screen tells the truth
@pytest.fixture
def deployed(monkeypatch, tmp_path):
    import json

    at.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)

    def _write(extra):
        at.SETTINGS_PATH.write_text(json.dumps({
            "strategies": [KEY], "strategy_coins": {KEY: ["STBL_USDT"]},
            "strategy_books": {KEY: ["paper"]},
            "strategy_margins": {KEY: 5.0}, "enabled": False, **extra}))
    monkeypatch.setattr(at, "strategy_stats", lambda dry=None, by_coin=False: {})
    monkeypatch.setattr(at, "pnl_today_by_strategy",
                        lambda now=None, dry=None, by_coin=False: {})
    return _write


def _row(rows):
    return next(r for r in rows if r["key"] == KEY)


def test_the_next_stake_column_is_the_stake_the_runner_will_send(deployed,
                                                                 monkeypatch):
    """Asked of the SAME function, so the column and the order cannot drift."""
    deployed({"martingale_demo": True})
    monkeypatch.setattr(at, "load_state", lambda: {
        at.state_key("STBL_USDT", True, KEY): {"step": 3}})
    r = _row(api.trade_strategies()["rows"])
    assert r["martingale"] is True
    assert r["ladder_rung"] == 3
    assert r["next_stake"] == 40.0, "three losses on a $5 base"
    assert r["ladder"][:4] == [5.0, 10.0, 20.0, 40.0]


def test_with_the_switch_off_the_column_says_the_base(deployed, monkeypatch):
    deployed({})
    monkeypatch.setattr(at, "load_state", lambda: {
        at.state_key("STBL_USDT", True, KEY): {"step": 3}})
    r = _row(api.trade_strategies()["rows"])
    assert r["martingale"] is False
    assert r["next_stake"] == 5.0, "a losing run must not move a flat stake"
    assert r["ladder"] == [5.0]
    assert r["ladder_rung"] == 0


def test_a_demo_row_does_not_read_the_live_switch(deployed, monkeypatch):
    """The row is armed on the practice book, so only the DEMO switch may
    change what it prints."""
    deployed({"martingale_live": True})
    monkeypatch.setattr(at, "load_state", lambda: {
        at.state_key("STBL_USDT", True, KEY): {"step": 2}})
    r = _row(api.trade_strategies()["rows"])
    assert r["martingale"] is False and r["next_stake"] == 5.0


# --------------------------------------------------- the screen's warning
def test_the_live_checkbox_spells_out_the_money_and_confirms():
    """Doubling after a loss is the fastest way this account can empty, so the
    live switch says the real figures and asks before it goes on. The demo one
    does not confirm — there is no money on it."""
    p = open("webapp/src/components/trade/StrategiesGrid.tsx",
             encoding="utf-8").read()
    assert "Martingale mode for DEMO" in p and "Martingale mode for LIVE" in p
    assert "x.martingale_demo = v" in p and "x.martingale_live = v" in p
    live = p[p.index("Martingale mode for LIVE") - 2200:
             p.index("Martingale mode for LIVE")]
    assert "window.confirm" in live, "REAL money went on without asking"
    assert "$5, $10, $20, $40, $80, $160" in live, \
        "the warning must show what a losing run actually stakes"
    assert "useState(false)" in p


def test_neither_switch_defaults_on_in_the_browser():
    p = open("webapp/src/components/trade/StrategiesGrid.tsx",
             encoding="utf-8").read()
    assert "se.settings.martingale_demo ?? false" in p
    assert "se.settings.martingale_live ?? false" in p
