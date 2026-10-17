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


def test_a_round_file_carries_each_rule_sets_ratio_to_github(tmp_path, monkeypatch):
    """Oct 17, 2026: write_round kept only the six dials, so p15round1.json
    reached GitHub without min_pay and the "1.5:1 search" ran 2:1 again — it
    found #BBE0A361 (a 2:1 id) once more. The ratio travels in the file, and a
    file written before it reads back exactly as it did."""
    import json as _json

    from tradingagents import forecast_rules as fr
    from tradingagents import room_strategies as rst

    monkeypatch.setattr(rst, "ROUNDS_DIR", tmp_path)
    monkeypatch.setattr(rst, "ROOT", tmp_path)
    sets = [_cfg(min_pay=1.5), _cfg()]
    p = rst.write_round("t", sets)
    back = rst.read_round(p.name)
    assert [fr.rule_id(c) for c in back] == [fr.rule_id(c) for c in sets]
    assert back[0]["min_pay"] == 1.5 and "min_pay" not in back[1]
    old = [{k: v for k, v in r.items() if k != "min_pay"} for r in _json.loads(p.read_text())]
    p.write_text(_json.dumps(old))
    assert [fr.rule_id(c) for c in rst.read_round(p.name)] == [fr.rule_id(sets[1])] * 2


def test_the_next_rounds_neighbours_keep_their_parents_ratio():
    from tradingagents import room_strategies as rst

    nxt = rst.neighbours([_cfg(min_pay=1.5)], set())
    assert nxt and all(c.get("min_pay") == 1.5 for c in nxt)
    assert all("min_pay" not in c for c in rst.neighbours([_cfg()], set()))


# ------------------------------------------------ the #BBE0A361 room (Oct 17, 2026)
def test_the_room_for_bbe0a361_is_that_rule_set_exactly():
    """Operator, Oct 17, 2026: "Room for #BBE0A361" - the one rule set prompt 4
    kept at 2:1 after real fees (BANANA 30m cx_veto 2.5% / 1%: 18 trades,
    8W/10L, +$6.92, a win +$2.15 vs a loss -$1.03). One room per rule set,
    named by its id, practice only, Smart Watcher on, raw (STANDING SETUP)."""
    from pathlib import Path

    from tradingagents import forecast_rules as fr
    from tradingagents import profiles
    from tradingagents import room_strategies as rst

    p = profiles.get("BBE0A361")
    assert p and p["name"] == "#BBE0A361" and not profiles.retired("BBE0A361")
    assert "BBE0A361" in profiles.shown()
    r = p["rules"]
    assert fr.rule_id(rst.cfg(30, 65.0, 30, "any", 1.0, 2.0)) == "BBE0A361"
    assert fr.rule_id({**r, "coin_slices": fr.COIN_SLICES}) == "BBE0A361"
    assert (r["window_days"], r["on_winrate"], r["off_winrate"], r["min_trades"],
            r["tp_rule"], r["max_sl"], r["min_tp"]) == (30, 65.0, 65.0, 30, "any", 1.0, 2.0)
    assert r["raw"] and not (r["max_new_per_day"] or r["max_slots"] or r["max_per_coin"])
    assert "min_pay" not in r, "the rooms' own 2:1 after fees"
    api = (Path(__file__).resolve().parents[1] / "webapp" / "src" / "lib" / "api.ts").read_text(encoding="utf-8")
    assert '{ id: "BBE0A361", name: "#BBE0A361" }' in api, "a tab on the screen"
