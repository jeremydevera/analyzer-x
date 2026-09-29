"""The criteria research: tuned on Jul-Aug, graded on September, one engine.

Operator, Sep 28, 2026: "can you research whats the best criteria for
promotion and demotion". Made-up trades on the operator's own calendar.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from tradingagents import replay_collect as rc
from tradingagents import watcher_policy as wp
from tradingagents import watcher_replay as wr
from tradingagents import watcher_research as rs

H = 3_600_000


def _ms(y, m, d, h=0):
    return int(dt.datetime(y, m, d, h).timestamp() * 1000)


def _combo(cid, coin, start, n, every_h, lose_every=0, tp=1.0, sl=0.7):
    trades = []
    for i in range(n):
        e = start + i * every_h * H
        pnl = -1.5 if lose_every and (i + 1) % lose_every == 0 else 0.8
        trades.append([e, e + 2 * H, pnl, 1])
    return {"id": cid, "coin": coin, "tf": "1h", "signal": "macddiv", "th": 0.0,
            "sl": sl, "tp": tp, "gate": "ok", "group": "classic", "trades": trades}


COMBOS = [_combo("AAAA0001", "GPNSTOCK", _ms(2026, 6, 5), 300, 9),
          _combo("BBBB0002", "KKRSTOCK", _ms(2026, 6, 5), 300, 7, lose_every=6),
          _combo("CCCC0003", "FASTSTOCK", _ms(2026, 6, 5), 300, 8, lose_every=12, tp=1.2, sl=1.2),
          _combo("DDDD0004", "VUG", _ms(2026, 6, 5), 300, 11, lose_every=4, tp=1.5, sl=1.0)]


def test_the_operators_rules_are_a_point_of_the_grid():
    g = rs.grid()
    assert rs.rule_id(rs.CURRENT) in {rs.rule_id(c) for c in g}
    assert len({rs.rule_id(c) for c in g}) == len(g), "ids are unique"


@pytest.mark.parametrize("cfg", [rs.CURRENT,
                                 {**rs.CURRENT, "on_winrate": 80.0, "off_winrate": 70.0,
                                  "tp_rule": ">=", "window_days": 14, "rank": "profit",
                                  "min_trades": 15, "off_streak_live": 3,
                                  "cooldown_days": 0, "max_per_coin": 1}])
def test_the_speed_up_gives_exactly_what_simulate_computes_itself(cfg):
    """Pre-cut rows are a speed-up only: the answer must not move a cent."""
    start, end = _ms(2026, 7, 1), _ms(2026, 9, 20)
    P = rs.prepare(COMBOS, start, end, [14, 30], rs.loose(rs.grid()))
    fast = wr.simulate(COMBOS, start_ms=start, end_ms=end, cfg=cfg,
                       rows=P["rows"][cfg["window_days"]], books=P["books"])
    slow = wr.simulate(COMBOS, start_ms=start, end_ms=end, cfg=cfg)
    assert fast["summary"] == slow["summary"]
    assert [s["id"] for s in fast["slots"]] == [s["id"] for s in slow["slots"]]


def test_the_training_replay_cannot_see_september():
    cut = rc.cut(COMBOS, _ms(2026, 9, 1) - 1)
    for c in cut:
        for t in c["trades"]:
            assert t[0] < _ms(2026, 9, 1)
            assert not (t[3] and t[1] >= _ms(2026, 9, 1)), "a September close"


def test_a_losing_streak_dial_switches_a_row_off(monkeypatch):
    start, end = _ms(2026, 7, 1), _ms(2026, 9, 20)
    # 53 wins every 12 hours, the last one entered Jul 01 12:00am (the check it
    # is switched on at), then three losses that are the LAST trades before
    # the Jul 02 check, while its 30-day win rate is still ~94%
    c = _combo("STRK0001", "GPNSTOCK", _ms(2026, 6, 5), 53, 12)
    bad = [[_ms(2026, 7, 1, 2) + i * 3 * H, _ms(2026, 7, 1, 3) + i * 3 * H, -1.5, 1]
           for i in range(3)]
    c["trades"] = sorted(c["trades"] + bad)
    on = wr.simulate([c], start_ms=start, end_ms=end,
                     cfg={**rs.CURRENT, "on_winrate": 80.0, "off_winrate": 70.0,
                          "min_trades": 15, "off_streak_live": 3})
    assert any("3 practice losses in a row" in s["off_why"] for s in on["slots"])


def test_score_counts_the_worst_day_the_dip_and_the_run():
    res = {"summary": {"profit": 1.0, "closed": 3, "wins": 1, "losses": 2,
                       "winrate": 33.3, "slots": 1, "open": 0},
           "days": [{"pnl": 2.0}, {"pnl": -1.5}, {"pnl": 0.5}],
           "slots": [{"trades": [[0, 1, 2.0, 1], [2, 3, -1.0, 1], [4, 5, -0.5, 1]]}]}
    s = rs.score(res)
    assert s["worst_day"] == -1.5 and s["max_dd"] == 1.5
    assert s["worst_run"] == -1.5 and s["worst_run_n"] == 2


def _folder(tmp_path, combos, end):
    d = tmp_path / "run" / "replay-0"
    d.mkdir(parents=True)
    with open(d / "replay-0.jsonl", "w", encoding="utf-8") as fh:
        for c in combos:
            fh.write(json.dumps(c) + "\n")
    (d / "replay-report-0.json").write_text(json.dumps({
        "start": "2026-07-01", "tz": "America/New_York", "cfg": {},
        "coins_board": 4, "coins_done": 4, "pairs": 4, "tested": 999, "kept": len(combos),
        "failed": {}, "short": [], "groups": ["classic", "preset"],
        "spans": {f"{c['coin']} 1h": [0, end] for c in combos}}))
    return str(tmp_path / "run")


@pytest.mark.parametrize("cfg", [rs.CURRENT,
                                 {**rs.CURRENT, "on_winrate": 80.0, "off_winrate": 70.0,
                                  "tp_rule": ">=", "window_days": 14, "rank": "profit",
                                  "min_trades": 15, "off_streak_live": 3,
                                  "cooldown_days": 0, "max_per_coin": 1}])
def test_the_lean_path_gives_what_simulate_computes_itself(tmp_path, cfg):
    """Research run 36495354168 wrote ~10.4 million trades with 2.4 GB free,
    so the research feeds simulate numpy books and per-check arrays. The
    replay those produce must be the replay simulate builds from plain lists."""
    end = _ms(2026, 9, 20)
    folder = _folder(tmp_path, COMBOS, end)
    L = rs.load_lean([folder])
    start = _ms(2026, 9, 1)
    pre = rs.compact_rows(L["books"], wr.local_midnights(start, end),
                          cfg["window_days"] * wr.DAY_MS, rs.loose(rs.grid()))
    lean = wr.simulate([], start_ms=start, end_ms=end, cfg=cfg,
                       rows=rs.CfgRows(pre, L["books"], cfg), books=L["books"])
    plain = wr.simulate(rc.cut(COMBOS, end), start_ms=start, end_ms=end, cfg=cfg)
    assert [s["id"] for s in lean["slots"]] == [s["id"] for s in plain["slots"]]
    assert [s["on_ms"] for s in lean["slots"]] == [s["on_ms"] for s in plain["slots"]]
    assert rs.score(lean) == rs.score(plain)


def test_an_arrbook_row_is_a_book_row():
    c = COMBOS[1]
    a = rs.ArrBook({k: v for k, v in c.items() if k != "trades"},
                   __import__("numpy").asarray(c["trades"], dtype=float))
    b = wr._Book(c)
    for at in wr.local_midnights(_ms(2026, 7, 1), _ms(2026, 9, 20)):
        for w in (14, 30):
            assert a.row(at, w * wr.DAY_MS) == b.row(at, w * wr.DAY_MS)


def test_a_trade_that_closed_after_the_period_is_not_counted():
    res = {"summary": {"profit": 0, "closed": 2, "wins": 2, "losses": 0,
                       "winrate": 100.0, "slots": 1, "open": 0},
           "days": [{"pnl": 0.8}],
           "slots": [{"trades": [[0, 10, 0.8, 1], [20, 99, 0.8, 1]]}]}
    s = rs.score(res, end_ms=50)
    assert (s["closed"], s["wins"], s["profit"]) == (1, 1, 0.8)


def test_the_most_trades_open_at_once_is_what_the_wallet_must_hold():
    res = {"summary": {"profit": 0, "closed": 3, "wins": 3, "losses": 0,
                       "winrate": 100.0, "slots": 2, "open": 0},
           "days": [{"pnl": 2.4}],
           "slots": [{"trades": [[0, 10, 0.8, 1], [12, 20, 0.8, 1]]},
                     {"trades": [[5, 15, 0.8, 1]]}]}
    assert rs.score(res)["max_open"] == 2
