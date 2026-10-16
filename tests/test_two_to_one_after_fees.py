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
