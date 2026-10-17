"""2:1 AFTER FEES — one win pays for two losses (operator, Oct 16, 2026).

Their words: *"first of all i asked claude to update those 1:1 to use 2:1 can
you review why was this not followed? when i say 2:1 this means in 2 lose all
fees are already included there"*, then **"Backtest list and rooms"**.

On Oct 06, 2026 they asked first for *"atleast 1:2 / meaning 1 win will break
even 2 loss"*, counted in dollars after fees; the build followed their last
words that day, *"the goal is to have higher tp than sl"*, on PRICES only. So
#5RKPYVQ7 (GPS 15m tsi, target 1% / stop 0.8%) stayed listed and traded while
practice paid +$0.79 a win and -$1.09 a loss: 0.72 to 1. Of 26,273,457
strategies on the Backtest v2 list, 10,389,743 pay two losses with one win
after fees.

The rule, one place (`backtest_report.pays_two_to_one`): with the row's own
round-trip cost c (its `cost_of_tp` percent of the target), a win is
TP - c and a loss SL + c, and the win must be at least twice the loss. A
cost the backtest could not read is not a pass — unknown is not ok when it is
money (rule 12).
"""
from __future__ import annotations

import pytest

from tradingagents import backtest_report as br
from tradingagents import watcher_policy as wp
from tradingagents import watcher_replay as wr

# GPS 15m tsi #5RKPYVQ7: target 1%, stop 0.8%, cost 0.25% of $100 (25% of TP)
GPS = {"tp": 1.0, "sl": 0.8, "cost_of_tp": 25.0, "gate": "warn", "res": "1m", "sizing": "flat"}
# a 1% stop with a 0.2% cost needs a target of 2 x 1 + 3 x 0.2 = 2.6%
TWO_ONE = {"tp": 2.6, "sl": 1.0, "cost_of_tp": round(0.2 / 2.6 * 100, 1), "gate": "ok",
           "res": "1m", "sizing": "flat"}


def test_a_win_must_pay_two_losses_after_fees():
    assert br.pays_two_to_one(GPS) is False          # +0.75 against -1.05
    assert br.pays_two_to_one(TWO_ONE) is True       # +2.40 against -1.20
    assert br.pays_two_to_one({**TWO_ONE, "tp": 2.5}) is False


def test_bigger_on_paper_is_not_enough():
    """TP 1.2% / SL 1% (the rooms' commonest pair) at a 0.2% cost: +1.00 a
    win against -1.20 a loss."""
    assert br.pays_two_to_one({**TWO_ONE, "tp": 1.2, "cost_of_tp": round(0.2 / 1.2 * 100, 1)}) is False


def test_a_fee_the_backtest_could_not_read_never_passes():
    assert br.pays_two_to_one({**TWO_ONE, "gate": "unknown", "cost_of_tp": 0.0}) is False
    assert br.pays_two_to_one({k: v for k, v in TWO_ONE.items() if k != "cost_of_tp"}) is False


def test_the_backtest_list_keeps_only_two_to_one():
    assert br.index_keeps(TWO_ONE) is True
    assert br.index_keeps(GPS) is False, "target bigger than stop is no longer enough"
    # Backtest v1 is untouched (no v1 rows on Gate; the operator asked for v2)
    assert br.index_keeps({**GPS, "res": None}) is True


def test_a_room_never_switches_on_a_strategy_that_pays_less():
    row = {**GPS, "id": "5RKPYVQ7", "trades": 152, "wins": 140, "winrate": 92.1,
           "profit": 50.0, "t15": 80, "w15": 75}
    why = wp.passes_on(row, dict(wp.DEFAULTS))
    assert "after fees" in why and "0.75" in why and "1.05" in why, why


def test_a_room_switches_off_a_running_strategy_that_pays_less():
    fresh = {**GPS, "winrate": 95.0, "trades": 40}
    why = wp.judge({"id": "5RKPYVQ7", "tp": 1.0, "sl": 0.8}, fresh, dict(wp.DEFAULTS))
    assert "after fees" in why, why
    # a running strategy whose fee cannot be read this hour is kept, as one
    # whose target cannot be read is (the rule is unknown, not failed)
    keep = {k: v for k, v in fresh.items() if k != "cost_of_tp"}
    assert wp.judge({"id": "5RKPYVQ7", "tp": 1.0, "sl": 0.8}, keep, dict(wp.DEFAULTS)) == ""


def test_the_replays_see_the_fee_so_they_judge_as_the_rooms_do():
    """watcher_replay / replay_shard / research all decide through passes_on:
    a replayed row must carry the fee, or every replay would switch on what
    the rooms refuse."""
    book = wr._Book({"id": "X", "coin": "GPS", "tf": "15m", "signal": "tsi", "th": 0.0,
                     "sl": 0.8, "tp": 1.0, "gate": "warn", "cost_of_tp": 25.0,
                     "trades": [[1_000, 2_000, 0.79, 1]]})
    assert book.row(3_000)["cost_of_tp"] == 25.0


# ----------------------------- the REAL fee, not a one-time estimate (Oct 16)
# Operator, Oct 16, 2026, "Yes, use real fees": the estimate stored when a
# strategy was measured said 0.549% for CTK 15m mom15 (TP 1% / SL 0.2%) on the
# Backtest list and about 0.28% in the research replay; its own trades, each
# paying its minute's order book, paid about 0.28% (a 1% win came home +$0.72).

def test_the_backtest_keeps_what_its_trades_really_paid():
    from tests.test_backtest_pays_the_minute import T0, H, book, run

    bk = book([(T0 + 6 * H, 0.0002, 0.0001, 0.0001, False),     # the entry minute
               (T0 + 8 * H, 0.0004, 0.0002, 0.0005, False)])    # the exit bar
    r = run(book=bk)
    # two fees (0.075% each), no entry fill (bought AT the ask), the exit's 0.05%
    assert r["rt_paid"] == pytest.approx(0.2, abs=1e-6)
    assert "rt_paid" not in run(), "without minute books the result keeps its shape"


def test_two_to_one_reads_the_real_fee_before_the_estimate():
    row = {"tp": 1.0, "sl": 0.2, "cost_of_tp": 54.9, "gate": "warn", "res": "1m", "sizing": "flat"}
    assert br.pays_two_to_one(row) is False                     # estimate: +0.45 vs -0.75
    assert br.pays_two_to_one({**row, "rt_paid": 0.1}) is True  # paid: +0.90 vs -0.30
    assert br.pays_two_to_one({**row, "rt_paid": 0.28}) is False  # paid: +0.72 vs -0.48
    assert br.win_and_loss({**row, "rt_paid": 0.28}) == pytest.approx((0.72, 0.48))


def test_a_row_with_no_fee_field_is_not_made_unknown_on_the_way_through():
    """Backtest a room hands _Book combinations without the fee: a row must
    not grow a None fee there, or every replayed row would read "unknown"."""
    book = wr._Book({"id": "X", "coin": "GPS", "tf": "15m", "signal": "tsi", "th": 0.0,
                     "sl": 0.8, "tp": 1.0, "gate": "ok", "trades": [[1_000, 2_000, 0.79, 1]]})
    row = book.row(3_000)
    assert "cost_of_tp" not in row and "rt_paid" not in row


def test_the_replays_carry_the_real_fee_too():
    book = wr._Book({"id": "X", "coin": "CTK", "tf": "15m", "signal": "mom15", "th": 0.0,
                     "sl": 0.2, "tp": 1.0, "gate": "ok", "cost_of_tp": 54.9, "rt_paid": 0.28,
                     "trades": [[1_000, 2_000, 0.72, 1]]})
    assert book.row(3_000)["rt_paid"] == 0.28


# ------------------------------- a rule set may ask its own ratio (Oct 17, 2026)
# "Research 1.5:1 after fees": prompt 4 runs the same search with one win
# paying 1.5 losses. A rule set carries `min_pay`; 2 (the default) is never
# hashed, so every id made before keeps its value.

def _cfg(**kw):
    from tradingagents import forecast_rules as fr

    return fr.cfg_of(30, 65.0, 30, ">", 1.0, min_tp=2.0, **kw)


def test_a_rule_sets_own_ratio_is_part_of_its_id_and_its_words():
    from tradingagents import forecast_rules as fr

    two, one_half = _cfg(), _cfg(min_pay=1.5)
    assert fr.rule_id(_cfg(min_pay=2.0)) == fr.rule_id(two), "the default never moves an id"
    assert fr.rule_id(one_half) != fr.rule_id(two)
    assert "a win pays 1.5 losses after fees" in fr.words(one_half)
    assert "losses after fees" not in fr.words(two)


def test_a_ratio_under_the_lists_two_to_one_is_not_room_ready():
    """Rooms nominate from the Backtest list, which keeps 2:1 only: a 1.5:1
    rule set could never find its strategies there."""
    from tradingagents import forecast_rules as fr

    ok, why = fr.deployable(_cfg(min_pay=1.5))
    assert not ok and "2:1" in why
    assert fr.deployable(_cfg()) == (True, "")


def test_the_researchs_loosest_rule_takes_the_lowest_ratio():
    from tradingagents import watcher_research as wres

    assert wres.loose([_cfg(), _cfg(min_pay=1.5)])["min_pay"] == 1.5
    assert wres.loose([_cfg()])["min_pay"] == 2.0


def test_the_ids_default_ratio_is_the_rooms_own():
    from tradingagents import forecast_rules as fr

    assert fr._DEFAULT_PAY == wp.DEFAULTS["min_pay"] == br.PAY_RATIO
