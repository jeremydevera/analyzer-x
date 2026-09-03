"""BALANCED — one 1-10 number over win rate AND profit, and the working behind it.

Operator, 2026-08-27: *"i want you to put column 'balanced' wher you rate each
stored strategies from 1-10 in terms of winrate and profit, because sometimes it
has high winrate but since tp is low and sl is high, its still not profitable so
that would be 1-4/10"*, and *"when i apply the months dropdown this column should
adjust as well"*.

So: profit is the ANCHOR. A row that did not make money cannot rate above 3
however often it wins, which is the 1-4 band they asked for. A profitable one
starts at 4 and earns up to 10 on profit per trade, win rate, green months and
whether its take-profit clears the round-trip cost (rule 11); it loses points for
a dip bigger than what it earned, for a dip over ten times the stake (the APEX
wallet: -$79.80 over 13 trades while the total was still green), and for losing
most of its trades — a row winning 11.7% of the time is carried by the ladder,
not by the signal, which is what rule 19's audit proved.

Every score carries its own sentence: a rating the operator cannot audit is a
rating they cannot use.
"""
import inspect
import json
import time

import pytest

from tradingagents import market_sweep as msw, rows_index as ri


def _row(**kw):
    row = {"winrate": 60.0, "profit": 100.0, "trades": 300, "tp": 2.0,
           "sl": 1.0, "dd": 10.0, "rt": 0.08, "base": 5.0, "green": 10,
           "months": 12}
    row.update(kw)
    return row


def test_the_operators_own_case_rates_in_the_1_to_4_band():
    """High win rate, tight TP, wide SL, and it still lost money."""
    score, why = ri.balanced_score(_row(winrate=82.0, profit=-45.0, tp=0.3,
                                        sl=3.0, dd=60.0))
    assert 1.0 <= score <= 4.0, (score, why)
    assert isinstance(score, float), "the operator asked for a decimal"
    assert "cannot rate above 3.0" in why
    assert "TP 0.3% against SL 3%" in why, why
    assert "payoff 0.10x" in why, "the TP/SL axis is named, not implied"
    assert "one loss erases many wins" in why, why


def test_no_win_rate_can_rescue_a_losing_row():
    for wr in (10.0, 50.0, 70.0, 99.9):
        score, _ = ri.balanced_score(_row(winrate=wr, profit=-1.0))
        assert score <= 3, (wr, score)


def test_a_clean_earner_rates_high():
    score, why = ri.balanced_score(_row(winrate=62.0, profit=420.0, tp=3.0,
                                        sl=1.0, dd=40.0, green=11))
    assert score >= 8, (score, why)
    assert "made 420.00 USDT" in why


def test_a_ladder_carried_row_is_not_balanced():
    """PONS 15m fade15: +1,638.14 on an 11.70% win rate. Profitable, and not
    what the operator means by balanced — rule 19's audit is the reason."""
    score, why = ri.balanced_score(_row(winrate=11.7, profit=1638.14,
                                        trades=1820, tp=3.0, sl=0.1, dd=89.3,
                                        green=2, months=2))
    assert score <= 6, (score, why)
    assert "the ladder is carrying this" in why


def test_a_dip_that_would_empty_the_wallet_costs_points():
    near = ri.balanced_score(_row(profit=200.0, dd=5.0))[0]
    deep = ri.balanced_score(_row(profit=200.0, dd=300.0))[0]
    assert deep < near, (deep, near)
    _, why = ri.balanced_score(_row(profit=200.0, dd=300.0))
    assert "worst dip" in why and "x the 5 USDT stake" in why


def test_a_rate_still_needs_a_denominator():
    """"CHF 30m soldiers 100.00% over 1 trade" was the top of this store once;
    10/10 over two trades is the same lie with a nicer number."""
    fluke, why = ri.balanced_score(_row(winrate=100.0, profit=3.0, trades=2))
    assert fluke <= 4, (fluke, why)
    assert "too few to rate above 4" in why
    thin, why = ri.balanced_score(_row(winrate=100.0, profit=30.0, trades=80))
    assert thin <= 7, (thin, why)
    assert "cannot rate above 7" in why


def test_an_unreachable_take_profit_earns_nothing_for_its_cost():
    """Rule 11: round-trip cost under 20% of the TP is comfortable, near 50% is
    fatal. BDX_USDT once ran at 734%."""
    cheap = ri.balanced_score(_row(tp=3.0, rt=0.05))[0]
    dear = ri.balanced_score(_row(tp=0.2, rt=0.15))[0]
    assert cheap > dear, (cheap, dear)


def test_every_score_carries_its_working():
    for kw in ({}, {"profit": -5.0}, {"trades": 4}, {"winrate": 12.0}):
        _, why = ri.balanced_score(_row(**kw))
        assert why and len(why) > 20, (kw, why)


@pytest.fixture
def store(tmp_path, monkeypatch):
    """One row that was green early and red lately, so a window MUST change its
    rating: May +500, Jun -100, Jul -400."""
    rows_dir = tmp_path / "rows"
    rows_dir.mkdir()
    monkeypatch.setattr(msw, "ROWDIR", rows_dir)
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    (rows_dir / "AAA-1h.json").write_text(json.dumps([{
        "coin": "AAA", "tf": "1h", "signal": "mom6", "th": 0.1, "sl": 1.0,
        "tp": 2.0, "rr": 2.0, "sizing": "flat", "lev": 20, "base": 5.0,
        "notional": 100.0, "trades": 900, "wins": 540, "losses": 360,
        "winrate": 60.0, "profit": 0.0, "funding": -0.2, "h1": 1.0, "h2": 1.0,
        "green": 1, "months": 3, "worst": -4.1, "dd": 20.0, "liqs": 0,
        "stop_reachable": True, "days": 90, "bars": 8600,
        "monthly": {"2026-05": 500.0, "2026-06": -100.0, "2026-07": -400.0},
        "cost_of_tp": 12.5, "rt": 0.08, "gate": "ok"}]))
    ri.sync(now=time.time() + ri.SETTLE_S + 1)
    return None


def test_the_window_re_rates_it(store):
    """The whole history nets zero; the last two months lost 500. The score has
    to follow the window, which is what the operator asked for."""
    full = ri.query()["rows"][0]
    two = ri.query(months=2)["rows"][0]
    assert full["balanced"] <= 3, full["balanced_why"]     # nets 0.00 -> a loser
    assert two["w_profit"] == -500.0
    assert two["balanced"] <= 3, two["balanced_why"]
    assert "lost -500.00" in two["balanced_why"], two["balanced_why"]

    one = ri.query(months=1)["rows"][0]
    assert one["w_profit"] == -400.0
    assert "lost -400.00" in one["balanced_why"]


def test_every_row_has_a_score_and_a_why(store):
    for kw in ({}, {"months": 2}, {"months": 12}):
        for r in ri.query(**kw)["rows"]:
            assert isinstance(r["balanced"], float)
            assert 1.0 <= r["balanced"] <= 10.0
            assert r["balanced_why"]


def test_the_csv_carries_the_column_too(store):
    """Kit item F: every row carries every column, the download included."""
    from tradingagents import api

    body = "".join(api.strategies_csv_lines())
    head = body.split("\n")[0].split(",")
    assert "balanced" in head and "balanced_why" in head, head
    row = body.split("\n")[1]
    assert float(row.split(",")[head.index("balanced")]) >= 1.0, row[:120]


def test_the_panel_prints_it_and_says_what_it_means():
    p = open("webapp/src/components/backtest/StrategiesPanel.tsx",
             encoding="utf-8").read()
    assert 'winHead("balanced"' in p, "the header follows the window"
    assert "r.balanced.toFixed(1)" in p, "one decimal, asked for by name"
    assert "r.balanced_why" in p, "the working is on hover"
    assert "rates win rate AND profit together" in p
    # and it is dimmed where the window's win rate is not the row's own
    assert "stale(r)" in p


def test_tp_against_sl_is_its_own_axis():
    """*"i want decimal value ypu will access how balanced it is in terms of
    profit, winrate, tp /sl"* — so the payoff ratio scores on its own, and two
    rows that differ ONLY in TP/SL cannot score the same."""
    wide = ri.balanced_score(_row(tp=3.0, sl=1.0))[0]     # 3.00x
    even = ri.balanced_score(_row(tp=1.0, sl=1.0))[0]     # 1.00x
    tight = ri.balanced_score(_row(tp=0.4, sl=3.0))[0]    # 0.13x
    assert wide > even > tight, (wide, even, tight)
    _, why = ri.balanced_score(_row(tp=0.4, sl=3.0))
    assert "payoff 0.13x" in why, why


def test_the_scores_are_decimals_that_separate_close_rows():
    a = ri.balanced_score(_row(profit=100.0, winrate=60.0))[0]
    b = ri.balanced_score(_row(profit=120.0, winrate=61.0))[0]
    assert a != b, (a, b)
    assert round(a, 1) == a and round(b, 1) == b, "one decimal place"


# ---------------------------------------------------------------------------
# The COMBINATION is a ceiling, not one term among many.
#
# Operator, 2026-09-03: *"DO YOU CALCULATE BALANCED COLUMN BASED ON WINRATE AND
# SL /TP COMBINATION / MEANING EVEN IF IS 100% WINRATE AND TP IS 0.1% AND sl IS
# 10% THIS SHOULD BE NOT BALANCED"*.
#
# It did use both, but the weights let the win rate win the argument. Measured
# on exactly their row before the change: 7.3/10, because +2.0 for the win rate
# and +1.0 for green months cancelled the -1.5 for the payoff.

def _combo(**kw):
    r = dict(profit=20.0, winrate=100.0, trades=120, tp=0.1, sl=10.0,
             rt=0.04, base=5.0, green=12, months=12, dd=0.0)
    r.update(kw)
    return r


def test_the_operators_own_case_cannot_be_called_balanced():
    score, why = ri.balanced_score(_combo())
    assert score <= 3.0, f"100% wins on TP 0.1 / SL 10 rated {score}: {why}"
    assert "ONE LOSS ERASES 100 WINS" in why, why
    assert "cannot rate above 3.0" in why


def test_a_win_rate_cannot_argue_with_the_barriers():
    """Every win rate from 50 to 100 on those barriers is capped."""
    for wr in (50.0, 80.0, 95.0, 99.0, 100.0):
        score, _ = ri.balanced_score(_combo(winrate=wr))
        assert score <= 3.0, wr


def test_the_bands_follow_how_many_wins_one_loss_erases():
    # payoff 0.01 -> 100 wins: 3.0
    assert ri.balanced_score(_combo(tp=0.1, sl=10.0))[0] <= 3.0
    # payoff 0.15 -> ~7 wins (the JPY 30m fade15 trap): 5.0
    assert ri.balanced_score(_combo(tp=0.3, sl=2.0, winrate=96.0))[0] <= 5.0
    # payoff 0.4 -> 2.5 wins: 7.0
    assert ri.balanced_score(_combo(tp=0.8, sl=2.0, winrate=80.0))[0] <= 7.0


def test_a_healthy_payoff_is_not_touched():
    """The ceiling must not demote the rows that are actually balanced. These
    are real shapes from the operator's store."""
    for tp, sl, wr in ((3.0, 1.0, 60.0), (2.0, 2.0, 70.0), (5.0, 1.0, 45.0),
                       (2.5, 1.2, 53.58)):
        score, why = ri.balanced_score(
            _combo(tp=tp, sl=sl, winrate=wr, profit=400.0, trades=300))
        assert score >= 7.0, (tp, sl, wr, score, why)


def test_a_target_smaller_than_the_cost_is_arithmetically_impossible():
    """Rule 11: over 100% of the target is not merely bad."""
    score, why = ri.balanced_score(_combo(tp=0.03, sl=1.0, rt=0.05))
    assert score <= 2.0
    assert "bigger than the 0.03% target" in why


def test_the_ceilings_do_not_overwrite_each_other():
    """Two separate `ceiling = ...` assignments would let whichever ran last
    decide — which is how a 10/10 on two trades was once possible."""
    score, why = ri.balanced_score(
        _combo(tp=3.0, sl=1.0, winrate=60.0, trades=12))
    assert score <= 4.0, why
    assert "too few to rate above 4" in why


def test_the_break_even_model_is_NOT_used_as_a_ceiling():
    """It was, for one measurement: on 1,000 real rows it lowered 942 of them,
    including AMP 15m vwaprev (TP 2.5 / SL 1.2, 53.58% wins, +752.85 USDT)
    from 9.0 to 3.0. `wins` counts every trade that ended positive, NOT the
    ones that reached TP, so "average win = tp" is an assumption the store's
    columns do not support."""
    src = inspect.getsource(ri.balanced_score)
    i = src.index("caps.append(2.0)")
    assert "margin < 0" not in src[i:], "the margin must not cap the score"
    # the AMP row keeps its rating
    score, _ = ri.balanced_score(dict(
        coin="AMP", tf="15m", signal="vwaprev", profit=752.85, winrate=53.58,
        trades=1200, tp=2.5, sl=1.2, rt=0.8624, base=5.0, green=11, months=12,
        dd=120.0))
    assert score >= 7.0, score
