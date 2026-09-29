"""The DEMO column is each id's LAST 30 DAYS, not its record since deployed.

Operator, `Sep 29, 2026`: *"in the DEMO W/L · $ column i want the winrate for
that id for the past 30 days / not the winrate strating when i deployed it"*,
and: *"the backtest for last 30 days is 95% then i have 5 losing trades in
live, and the scheduled backtest is not running, this is where you should
calculate it"*.

So: the id's backtest trades up to the backtest's last candle, then its
practice trades after it — never both for the same stretch of time.

ONE TIMELINE: every test places the backtest's trades, its last candle, the
practice exits and "now" on the same clock (`NOW`), the one a running API
sees. Do not "simplify" them onto separate clocks (RCA-2026-09-12-A).
"""
from __future__ import annotations

import json

import pytest

from tradingagents import rolling30 as r30

NOW = 1_790_700_000.0                      # Sep 29, 2026, seconds
DAY = 86_400
SLOT = "prank_15m_sl15tp15|FASTSTOCK_USDT"


@pytest.fixture
def home(tmp_path, monkeypatch):
    import tradingagents.auto_trader as at

    monkeypatch.setattr(at, "STATE_DIR", tmp_path)
    monkeypatch.setattr(at, "LEDGER_PATH", tmp_path / "auto_trade_ledger.jsonl")
    r30._MEMO.clear()
    return tmp_path


def _cache(home, trades, end_s, stored=None, rebuilt=None):
    stored = stored or {"trades": len(trades), "wins": 0, "profit": 0.0}
    rec = {"slot": SLOT, "wm": int(end_s * 1000) - 900_000, "bar_s": 900,
           "end_ms": int(end_s * 1000), "trades": trades,
           "stored": stored, "rebuilt": rebuilt or stored}
    (home / "rolling30").mkdir(exist_ok=True)
    (home / "rolling30" / (SLOT.replace("|", "__") + ".json")).write_text(json.dumps(rec))


def _bt(days_ago, pnl):
    ms = int((NOW - days_ago * DAY) * 1000)
    return [ms - 3_600_000, ms, pnl]


def test_the_operators_example_five_practice_losses_after_a_95_percent_backtest(home):
    # the backtest: 19 won, 1 lost, last candle a day ago
    trades = [_bt(20 - i, +1.0) for i in range(19)] + [_bt(1.5, -1.0)]
    _cache(home, trades, NOW - DAY)
    # ...and then, with no backtest update since, five practice losses
    exits = [(NOW - 3600 * (i + 1), SLOT, -1.5) for i in range(5)]
    f = r30.figure(SLOT, now=NOW, exits=exits)
    assert (f["wins"], f["losses"]) == (19, 6)
    assert f["winrate"] == 76.0             # 19 of 25, not the backtest's 95
    assert (f["from_backtest"], f["from_practice"]) == (20, 5)
    assert f["pnl"] == round(19 - 1 - 7.5, 2)


def test_nothing_older_than_30_days_counts(home):
    _cache(home, [_bt(31, -1.0), _bt(29, +1.0)], NOW - DAY)
    f = r30.figure(SLOT, now=NOW, exits=[])
    assert (f["wins"], f["losses"]) == (1, 0)


def test_a_practice_trade_the_backtest_already_covers_is_not_counted_twice(home):
    _cache(home, [_bt(2, +1.0)], NOW - DAY)
    exits = [(NOW - 2 * DAY, SLOT, +1.0),   # inside the backtest's stretch
             (NOW - 3600, SLOT, -1.0)]      # after its last candle
    f = r30.figure(SLOT, now=NOW, exits=exits)
    assert (f["from_backtest"], f["from_practice"]) == (1, 1)
    assert (f["wins"], f["losses"]) == (1, 1)


def test_another_ids_practice_trade_is_not_this_ones(home):
    _cache(home, [], NOW - DAY)
    exits = [(NOW - 3600, "prank_15m_sl15tp15|GPNSTOCK_USDT", -1.0),
             (NOW - 3600, "prank_15m_sl15tp2|FASTSTOCK_USDT", -1.0)]
    f = r30.figure(SLOT, now=NOW, exits=exits)
    assert f["trades"] == 0 and f["winrate"] is None


def test_a_backtest_older_than_30_days_leaves_only_the_practice_trades(home):
    _cache(home, [_bt(40, +1.0)], NOW - 35 * DAY)
    exits = [(NOW - 10 * DAY, SLOT, +1.0), (NOW - 40 * DAY, SLOT, +1.0)]
    f = r30.figure(SLOT, now=NOW, exits=exits)
    assert (f["from_backtest"], f["from_practice"]) == (0, 1)


def test_not_worked_out_yet_is_none_never_a_guess(home):
    assert r30.figure(SLOT, now=NOW, exits=[]) is None


def test_a_rebuild_that_differs_from_the_stored_row_says_so(home):
    _cache(home, [], NOW - DAY, stored={"trades": 23, "wins": 22, "profit": 6.2},
           rebuilt={"trades": 22, "wins": 21, "profit": 5.7})
    f = r30.figure(SLOT, now=NOW, exits=[])
    assert f["match"] is False and f["stored"]["trades"] == 23


def test_a_cent_of_rounding_is_still_the_same_row():
    # FASTSTOCK 30m prank: stored +$96.64, rebuilt +$96.65, same 85 / 80
    assert r30.same_result({"trades": 85, "wins": 80, "profit": 96.64},
                           {"trades": 85, "wins": 80, "profit": 96.65})
    assert not r30.same_result({"trades": 85, "wins": 80, "profit": 96.64},
                               {"trades": 85, "wins": 79, "profit": 96.64})


def test_the_engine_log_becomes_closed_trades_only():
    from tradingagents.positions_view import fmt_when

    log = [{"entry time": fmt_when(NOW - 7200), "exit time": fmt_when(NOW - 3600),
            "exit_minute_ms": int((NOW - 3600) * 1000), "pnl $": 0.9, "why": "TP"},
           {"entry time": fmt_when(NOW - 600), "exit time": fmt_when(NOW),
            "pnl $": 0.1, "why": "END"}]
    got = r30.log_to_trades(log)
    assert len(got) == 1                    # the one still open has no result
    assert got[0][1] == int((NOW - 3600) * 1000) and got[0][2] == 0.9
    assert abs(got[0][0] - (NOW - 7200) * 1000) < 60_000   # minute precision


def _write_ledger(path, rows):
    with path.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def _exit(ts, pnl, dry=True, sym="FASTSTOCK_USDT"):
    return {"ts": ts, "symbol": sym, "action": "exit", "strategy": "prank_15m_sl15tp15",
            "pnl_est": pnl, "dry_run": dry}


def test_the_trade_record_is_read_as_it_grows(home):
    import tradingagents.auto_trader as at

    reader = r30._PracticeExits()
    _write_ledger(at.LEDGER_PATH, [_exit(NOW - 60, -1.0), _exit(NOW - 50, 1.0, dry=False),
                                   {"ts": NOW - 40, "action": "gate_blocked"}])
    assert reader.get(NOW) == [(NOW - 60, SLOT, -1.0)]
    _write_ledger(at.LEDGER_PATH, [_exit(NOW - 30, 2.0)])
    assert [r[2] for r in reader.get(NOW)] == [-1.0, 2.0]
    # a half-written last line is left for the next read, never half-parsed
    with at.LEDGER_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(_exit(NOW - 20, 3.0))[:30])
    assert len(reader.get(NOW)) == 2


def test_a_different_trade_record_starts_from_its_own_beginning(home, tmp_path, monkeypatch):
    """The reader keeps its place in ONE file; pointed at another it must not
    carry that place over and skip the new file's first rows."""
    import tradingagents.auto_trader as at

    reader = r30._PracticeExits()
    _write_ledger(at.LEDGER_PATH, [_exit(NOW - 60, -1.0)] * 5)
    assert len(reader.get(NOW)) == 5
    other = tmp_path / "other.jsonl"
    _write_ledger(other, [_exit(NOW - 10, 7.0)] * 8)
    monkeypatch.setattr(at, "LEDGER_PATH", other)
    got = reader.get(NOW)
    assert len(got) == 8 and all(r[2] == 7.0 for r in got)


def test_the_rebuild_never_runs_under_pytest():
    assert r30.refresh()["skipped"] == "under pytest"


def test_the_api_gives_every_row_its_30_days(home):
    src = open("tradingagents/api.py", encoding="utf-8").read()
    assert '"paper30": (_r30.figure(f"{key}|{_coin}", now=_now30, exits=_exits30)' in src
    # the trade record is read ONCE per request, not once per row
    assert src.count("_r30.PRACTICE.get(") == 2   # the request + the warm-up


def test_the_screen_uses_one_helper_for_every_demo_figure():
    src = open("webapp/src/components/trade/StrategiesGrid.tsx", encoding="utf-8").read()
    assert '["DEMO 30 DAYS W/L · $", ' in src
    assert "demo = tot(demoOf)" in src                     # desktop TOTAL
    assert '["DEMO", demoOf]' in src                       # phone TOTAL
    assert 'const got = which === "paper" ? demoOf(r) : null;' in src   # the cell
    assert ": demoOf(r);" in src                           # the phone card
    # the TOTAL no longer claims "every closed trade so far" for the demo side
    assert "TOTAL — every closed trade so far" not in src
    assert "demo: last 30 days" in src
    # a row not worked out yet SAYS so
    assert "last 30 days not worked out yet" in src
