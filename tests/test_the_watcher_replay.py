"""The watcher replay: the live watcher's rules, day by day, with no look-ahead.

Operator, Sep 28, 2026: "Then do the backtest replay so i know the pnl for
every day to know if my plan has relevenave". Each test builds trades on ONE
timeline, the local days the operator reads, starting Aug 02, 2026 (30 days
before the first check on Sep 01, 2026). Trades here are made up — the real
ones come from the GitHub replay (.github/scripts/replay_shard.py).
"""
from __future__ import annotations

import datetime as dt

import pytest

from tradingagents import watcher_policy as wp, watcher_replay as wr

H = 3_600_000
D = 24 * H


def _ms(y, m, d, h=0):
    return int(dt.datetime(y, m, d, h).timestamp() * 1000)


SEP1 = _ms(2026, 9, 1)
AUG2 = _ms(2026, 8, 2)
END = _ms(2026, 9, 10, 12)


def _combo(cid, coin, trades, tp=1.0, sl=0.7):
    return {"id": cid, "coin": coin, "tf": "1h", "signal": "macddiv",
            "th": 0.0, "sl": sl, "tp": tp, "gate": "ok",
            "trades": [list(t) for t in trades]}


def _steady(start, n, every_h, win=0.8, lose=-1.5, lose_every=0):
    """n closed trades, one every `every_h` hours, each lasting 2 hours."""
    out = []
    for i in range(n):
        e = start + i * every_h * H
        pnl = lose if lose_every and (i + 1) % lose_every == 0 else win
        out.append((e, e + 2 * H, pnl, 1))
    return out


def test_a_row_that_passes_on_sep1_is_switched_on_at_midnight_and_earns_after():
    # 25 winning trades in August (all before Sep 01), then 5 more in September
    aug = _steady(AUG2 + 5 * H, 25, 24)
    sep = _steady(SEP1 + 3 * H, 5, 24)
    got = wr.simulate([_combo("GOOD0001", "GPNSTOCK", aug + sep)],
                      start_ms=SEP1, end_ms=END)
    s = got["slots"][0]
    assert s["on_ms"] == SEP1 and s["id"] == "GOOD0001"
    assert s["closed"] == 5, "only trades ENTERED after it was switched on"
    assert got["summary"]["profit"] == pytest.approx(5 * 0.8)


def test_nothing_that_happens_after_a_check_can_switch_a_row_on_at_it():
    """No look-ahead: 25 wins that all land in September cannot make the row
    pass on Sep 01 — it is switched on the first midnight after its 20th."""
    sep = _steady(SEP1 + 1 * H, 25, 6)          # 4 a day from Sep 01 1am
    got = wr.simulate([_combo("LATE0001", "KKRSTOCK", sep)],
                      start_ms=SEP1, end_ms=END)
    on = got["slots"][0]["on_ms"]
    assert on > SEP1
    assert on == _ms(2026, 9, 6), "the 20th exit is Sep 05 at 11am"


def test_under_ninety_percent_switches_it_off_at_the_next_midnight():
    aug = _steady(AUG2 + 5 * H, 25, 24)                       # 25 wins
    losses = [(SEP1 + 2 * H + i * 3 * H, SEP1 + 3 * H + i * 3 * H, -1.5, 1)
              for i in range(4)]                             # 4 losses Sep 01
    got = wr.simulate([_combo("FADE0001", "FASTSTOCK", aug + losses)],
                      start_ms=SEP1, end_ms=END)
    s = got["slots"][0]
    assert s["off_ms"] == _ms(2026, 9, 2)
    assert "under 90" in s["off_why"]
    assert s["closed"] == 4 and s["profit"] == pytest.approx(-6.0)
    assert s["worst_streak"] == pytest.approx(-6.0) and s["worst_streak_len"] == 4


def test_a_trade_open_at_switch_off_finishes_and_counts():
    aug = _steady(AUG2 + 5 * H, 25, 24)
    bad = [(SEP1 + 1 * H, SEP1 + 2 * H, -1.5, 1),
           (SEP1 + 3 * H, SEP1 + 4 * H, -1.5, 1),
           (SEP1 + 5 * H, SEP1 + 6 * H, -1.5, 1),
           (SEP1 + 20 * H, SEP1 + 30 * H, 0.8, 1)]          # spans midnight
    got = wr.simulate([_combo("SPAN0001", "VUG", aug + bad)],
                      start_ms=SEP1, end_ms=END)
    s = got["slots"][0]
    assert s["off_ms"] == _ms(2026, 9, 2)
    assert s["closed"] == 4, "entered before the switch-off, so it counts"


def test_a_switched_off_row_waits_seven_days_before_it_can_return():
    aug = _steady(AUG2 + 5 * H, 25, 24)
    dip = [(SEP1 + 1 * H, SEP1 + 2 * H, -1.5, 1),
           (SEP1 + 3 * H, SEP1 + 4 * H, -1.5, 1),
           (SEP1 + 5 * H, SEP1 + 6 * H, -1.5, 1)]
    wins = _steady(_ms(2026, 9, 2, 1), 60, 3)                # passes again fast
    got = wr.simulate([_combo("BACK0001", "AONSTOCK", aug + dip + wins)],
                      start_ms=SEP1, end_ms=_ms(2026, 9, 12))
    ons = [s["on_ms"] for s in got["slots"]]
    assert ons[0] == SEP1 and ons[1] >= _ms(2026, 9, 9), ons


def test_tp_not_wider_than_sl_is_never_switched_on():
    aug = _steady(AUG2 + 5 * H, 25, 24)
    got = wr.simulate([_combo("EQUAL001", "FASTSTOCK", aug, tp=1.2, sl=1.2)],
                      start_ms=SEP1, end_ms=END)
    assert got["slots"] == []


def test_every_day_is_a_row_and_the_running_total_adds_up():
    aug = _steady(AUG2 + 5 * H, 25, 24)
    sep = _steady(SEP1 + 3 * H, 9, 24)
    got = wr.simulate([_combo("GOOD0001", "GPNSTOCK", aug + sep)],
                      start_ms=SEP1, end_ms=END)
    days = got["days"]
    assert [d["day"] for d in days][:2] == ["2026-09-01", "2026-09-02"]
    assert len(days) == 10, "Sep 01 through Sep 10, quiet days included"
    assert sum(d["pnl"] for d in days) == pytest.approx(got["summary"]["profit"])
    assert days[-1]["total"] == pytest.approx(got["summary"]["profit"])
    assert days[0]["on"] == 1 and days[0]["running"] == 1


def test_a_trade_still_open_at_the_end_is_listed_never_counted():
    aug = _steady(AUG2 + 5 * H, 25, 24)
    still = [(END - 5 * H, END, 0.0, 0)]
    got = wr.simulate([_combo("OPEN0001", "GPNSTOCK", aug + still)],
                      start_ms=SEP1, end_ms=END)
    s = got["slots"][0]
    assert s["open"] == 1 and s["closed"] == 0 and s["profit"] == 0


def test_it_uses_the_live_watchers_own_rules():
    """No second copy of the rules: the replay must call watcher_policy."""
    import inspect

    src = inspect.getsource(wr)
    assert "wp.pick(" in src and "wp.judge(" in src and "wp.passes_on(" in src
    assert wp.DEFAULTS["on_winrate"] == 90.0


def test_the_per_coin_cap_holds_in_the_replay():
    combos = [_combo(f"GPN{i:05d}", "GPNSTOCK", _steady(AUG2 + 5 * H, 25, 24),
                     tp=1.0 + i / 10) for i in range(6)]
    got = wr.simulate(combos, start_ms=SEP1, end_ms=END)
    assert len(got["slots"]) == 3
