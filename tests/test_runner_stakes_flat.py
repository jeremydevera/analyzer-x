"""The runner never doubles a stake. The backtests still measure the ladder.

Operator, Sep 11, 2026, after asking what the ladder does ("once i loss will
it double the margin?" — every second loss: 1,1,2,2,4,4,8 × base):

  *"From now on you will not double anything in martingale, just flat only,
  update your code to not double the margin for all martingale. No need to
  update the backtests since what matters to me is winrate not the profit."*

Three things have to hold at once, and each is pinned here:

* the RUNNER stakes the base margin on every trade, whatever a row was
  deployed as and whatever the settings file says;
* the BACKTEST engine is untouched — a martingale row is still measured with
  the ladder, so the stored rows keep their meaning (its win rate is the same
  trades as its flat twin; only profit differs);
* every label derived from sizing tells the truth: the grid says flat, the
  next stake is the base, and a deployed row's id is its flat twin's.
"""
import inspect

import pytest

from tradingagents import auto_trader as at, backtest_report as br

SETTINGS = {
    "strategies": ["mom6_1h_pv", "willr14_15m_sl1tp12"],
    "strategy_coins": {"mom6_1h_pv": ["PROVE_USDT"],
                       "willr14_15m_sl1tp12": ["PSXSTOCK_USDT"]},
    "strategy_books": {"mom6_1h_pv": ["real"], "willr14_15m_sl1tp12": ["real"]},
    "strategy_margins": {"mom6_1h_pv": 5.0, "willr14_15m_sl1tp12": 1.0},
    "sizing": "martingale",
    "strategy_sizing": {"mom6_1h_pv": "martingale",
                        "willr14_15m_sl1tp12": "martingale"},
}


# ------------------------------------------------------------- the stake
def test_the_stake_is_the_base_margin_on_every_rung():
    """The operator's own PSXSTOCK row ($1 base) and a $5 row: rung 0 to rung
    8, the stake never moves. Before this, rung 6 staked 8× ($8 and $40)."""
    for step in range(0, 9):
        assert at.staked_margin("willr14_15m_sl1tp12", SETTINGS, step) == 1.0
        assert at.staked_margin("mom6_1h_pv", SETTINGS, step) == 5.0


def test_the_stake_does_not_even_ask_how_the_row_is_labelled():
    """`staked_margin` must not route through `sizing_for`: a later change to
    how a row is LABELLED must not be able to put a multiplier on real money."""
    src = inspect.getsource(at.staked_margin)
    body = src.split('"""')[-1]            # the CODE, not the docstring that names them
    assert "sizing_for(" not in body and "ladder_margin(" not in body and "LADDER[" not in body
    assert "return margin_for(key, settings)" in body


def test_sizing_for_says_flat_for_every_input():
    for s in ({}, {"sizing": "flat"}, {"sizing": "martingale"},
              {"sizing": "MARTINGALE"}, SETTINGS):
        assert at.sizing_for(s) == "flat"
        assert at.sizing_for(s, "mom6_1h_pv") == "flat"


def test_the_runner_takes_its_margin_from_staked_margin_only():
    """One call site, and it is the one that was changed."""
    src = inspect.getsource(at)
    calls = [ln for ln in src.splitlines()
             if "staked_margin(" in ln and "def staked_margin" not in ln]
    assert len(calls) == 1, calls
    assert 'margin = staked_margin(key, settings, st["step"])' in calls[0]
    # and nothing else in the runner's entry path reaches for the ladder: the
    # only ladder_margin call left is the backtest engine's
    engine = [ln for ln in src.splitlines()
              if "ladder_margin(" in ln and "def ladder_margin" not in ln]
    assert len(engine) == 1, engine
    assert "else ladder_margin(base_margin, step))" in engine[0]


# ------------------------------------------------------- the backtests stay
def test_the_backtest_engine_still_measures_the_ladder():
    """No need to update the backtests — so they must not have changed."""
    assert at.LADDER == (1, 1, 2, 2, 4, 4, 8)
    assert [at.ladder_margin(5.0, s) for s in range(9)] == \
        [5.0, 5.0, 10.0, 10.0, 20.0, 20.0, 40.0, 40.0, 40.0]
    src = inspect.getsource(at.backtest_strategy)
    assert 'margin = (base_margin if sizing == "flat"' in src
    assert "else ladder_margin(base_margin, step))" in src


def test_a_martingale_row_and_its_flat_twin_share_a_win_rate():
    """The operator's reason for leaving the backtests alone: the ladder
    changes how much rides on each trade, never which trades are taken."""
    from tests.test_auto_trader import _bars

    df = _bars([100.0 + ((i * 7) % 11) - 5 for i in range(400)])
    flat = at.backtest_strategy("mom6", df, 5.0, sizing="flat")
    mart = at.backtest_strategy("mom6", df, 5.0, sizing="martingale")
    assert flat["trades"] == mart["trades"] and flat["wins"] == mart["wins"]
    assert flat["trades"] > 0


# ------------------------------------------------------------- the labels
def test_a_deployed_row_is_named_by_its_flat_twin(monkeypatch):
    """Sizing is part of a row's identity, and flat is what runs now — so a
    row deployed from a martingale line carries the FLAT row's id, which is
    the row in Stored strategies whose numbers describe what the runner
    does."""
    from tradingagents.api import row_id_for

    monkeypatch.setitem(at.STRATEGY_SPECS, "mom6_1h_pv",
                        {"interval": "Min60", "threshold": 0.006, "sl": 0.02,
                         "tp": 0.03})
    got = row_id_for("mom6_1h_pv", "PROVE_USDT", SETTINGS)
    assert got == br.row_code("PROVE", "1h", "mom6", 0.6, 2.0, 3.0, "flat")
    assert got != br.row_code("PROVE", "1h", "mom6", 0.6, 2.0, 3.0, "martingale")


def test_the_grid_is_told_flat_and_a_one_rung_ladder(monkeypatch):
    from fastapi.testclient import TestClient

    from tradingagents import api

    monkeypatch.setattr(at, "load_settings", lambda: dict(SETTINGS))
    monkeypatch.setattr(at, "load_state", lambda: {"_rev": {}})
    monkeypatch.setattr(at, "strategy_stats", lambda dry=None: {})
    monkeypatch.setattr(at, "pnl_today_by_strategy", lambda dry=None: {})
    monkeypatch.setattr(at, "tripped_strategies", lambda s: set())
    monkeypatch.setattr(at, "timeframe_locks", lambda s: {})
    body = TestClient(api.app).get("/api/trade/strategies").json()
    assert body["sizing"] == "flat" and body["flat"] is True
    for r in body["rows"]:
        assert r["sizing"] == "flat", r["key"]
        assert r["ladder"] == [at.margin_for(r["key"], SETTINGS)], r["key"]
