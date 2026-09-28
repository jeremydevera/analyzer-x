"""The watcher's two decisions, with the operator's own rows."""
import pytest

from tradingagents import watcher_policy as wp

CFG = dict(wp.DEFAULTS)
NOW = 1_790_700_000.0
# #77Y3BPFG GPNSTOCK 1h macddiv SL 0.7% / TP 1.0% flat, as the v2 index held
# it on Sep 28, 2026: 20 trades, 20W, 100%, +$15.84
R6 = {"id": "77Y3BPFG", "coin": "GPNSTOCK", "tf": "1h", "signal": "macddiv",
      "th": 0.0, "sl": 0.7, "tp": 1.0, "trades": 20, "wins": 20,
      "losses": 0, "winrate": 100.0, "profit": 15.84, "gate": "ok"}


def test_the_operators_row_passes():
    assert wp.passes_on(R6, CFG) == ""


def test_the_operators_numbers_are_the_defaults():
    assert (CFG["on_winrate"], CFG["off_winrate"], CFG["min_trades"],
            CFG["tp_rule"]) == (90.0, 90.0, 20, ">")


@pytest.mark.parametrize("change,word", [
    ({"tp": 1.0, "sl": 1.2}, "TP"), ({"winrate": 89.9}, "win"),
    ({"trades": 19}, "trades"), ({"profit": -0.01}, "profit"),
    ({"gate": "block"}, "cost")])
def test_each_floor_refuses_by_name(change, word):
    assert word in wp.passes_on({**R6, **change}, CFG)


def test_equal_barriers_are_refused_tp_must_be_wider():
    """#R6FRS3KD FASTSTOCK 15m bb20 is TP 1.2% / SL 1.2%: refused by name."""
    assert "TP" in wp.passes_on({**R6, "tp": 1.2, "sl": 1.2}, CFG)


def test_exactly_ninety_percent_is_switched_on():
    assert wp.passes_on({**R6, "winrate": 90.0}, CFG) == ""


def test_break_even_is_the_operators_62_3():
    assert wp.break_even(0.98, 1.62) == pytest.approx(62.3, abs=0.05)


def test_pick_keeps_three_per_coin_and_twenty_a_day():
    many = [{**R6, "id": f"A{i:07d}", "coin": f"C{i % 30}"} for i in range(200)]
    got = wp.pick(many, running=[], cooling={}, now=NOW, cfg=CFG)
    assert len(got) == 20
    per = {}
    for g in got:
        per[g["row"]["coin"]] = per.get(g["row"]["coin"], 0) + 1
    assert max(per.values()) <= 3


def test_pick_never_arms_an_id_already_running():
    got = wp.pick([R6], running=[{"id": "77Y3BPFG", "coin": "GPNSTOCK"}],
                  cooling={}, now=NOW, cfg=CFG)
    assert got == []


def test_a_switched_off_id_waits_out_its_cooldown():
    off_at = NOW - 6 * 86400
    assert wp.pick([R6], [], {"77Y3BPFG": off_at}, NOW, CFG) == []
    assert len(wp.pick([R6], [], {"77Y3BPFG": off_at}, NOW + 86400, CFG)) == 1


def test_pick_stops_at_max_slots_counting_what_runs():
    running = [{"id": f"R{i}", "coin": f"X{i}"} for i in range(99)]
    many = [{**R6, "id": f"B{i}", "coin": f"Y{i}"} for i in range(50)]
    assert len(wp.pick(many, running, {}, NOW, CFG)) == 1


def test_pick_takes_the_highest_win_rate_first_then_trades():
    lo = {**R6, "id": "LO", "coin": "A", "winrate": 91.0}
    hi = {**R6, "id": "HI", "coin": "B", "winrate": 95.0, "trades": 21}
    hi2 = {**R6, "id": "HI2", "coin": "C", "winrate": 95.0, "trades": 60}
    got = wp.pick([lo, hi, hi2], [], {}, NOW, {**CFG, "max_new_per_day": 2})
    assert [g["row"]["id"] for g in got] == ["HI2", "HI"]


# ---- judge: switching OFF
def test_under_ninety_percent_over_30_days_switches_it_off():
    why = wp.judge({"id": "77Y3BPFG"}, {**R6, "winrate": 89.9}, CFG)
    assert "89.9" in why and "90" in why


def test_exactly_ninety_percent_is_kept():
    assert wp.judge({"id": "x"}, {**R6, "winrate": 90.0}, CFG) == ""


def test_the_practice_record_is_shown_never_switches_it_off():
    """The operator gave ONE off rule, the 30-day win rate. A losing practice
    record is printed beside the row; the row stays on."""
    p = {"trades": 10, "wins": 6, "losses": 4, "pnl": -0.60, "streak": 4,
         "win_usd": 0.98, "loss_usd": 1.62}
    assert wp.judge({"id": "x"}, R6, CFG) == ""
    why = wp.warn(p, CFG)
    assert "-0.60" in why and "4 losses in a row" in why


def test_nine_practice_trades_are_not_enough_to_warn_about_money():
    p = {"trades": 9, "wins": 3, "losses": 6, "pnl": -5.0, "streak": 0,
         "win_usd": 0.98, "loss_usd": 1.62}
    assert wp.warn(p, CFG) == ""


def test_a_row_the_store_no_longer_holds_is_switched_off():
    assert "no longer" in wp.judge({"id": "x"}, None, CFG)
