"""A strategy switched off a SECOND time is written to the deployment record.

RCA-2026-10-05-H: #ES68FMKK DVNSTOCK 15m ibs was switched off in #CC94D9FB at
Oct 01, 2026 12:51pm (recorded), on again at Oct 02, 2026 12:12am (recorded),
and off again at 12:56am — and that last line was never written: the
duplicate check compared the new line with the OLDEST same-strategy line among
the newest 200, which was the Oct 01 switch-off, word for word the same. The
room's replay then kept the strategy on for three days (84 trades the room
never made); 43 of #CC94D9FB's 497 watcher switch-offs were missing.
"""
from __future__ import annotations

import json

from tradingagents import local_history as lh

SLOT = ("ibs_15m_sl03tp04", "DVNSTOCK_USDT")


def _row(action, t, key=SLOT[0], sym=SLOT[1]):
    return {"changed_at": t, "strategy_key": key, "symbol": sym, "action": action,
            "books": "paper" if action == "deployed" else None}


def test_a_second_switch_off_is_written():
    t = 1_790_800_000
    assert lh.record_deployment(_row("deployed", t)) == 1
    assert lh.record_deployment(_row("disarmed", t + 60)) == 1
    for k in range(150):                       # the room's other strategies
        lh.record_deployment(_row("deployed", t + 100 + k, key=f"k{k}_15m", sym="X_USDT"))
    assert lh.record_deployment(_row("deployed", t + 1000)) == 1
    assert lh.record_deployment(_row("disarmed", t + 1100)) == 1, \
        "the second switch-off is history, not a copy of the first"
    mine = [d["action"] for d in reversed(lh.deployments(limit=1000))
            if d["strategy_key"] == SLOT[0]]
    assert mine == ["deployed", "disarmed", "deployed", "disarmed"]


def test_the_same_save_twice_in_a_row_is_still_one_line():
    t = 1_790_800_000
    assert lh.record_deployment(_row("deployed", t)) == 1
    assert lh.record_deployment(_row("deployed", t + 5)) == 0


def test_the_reality_check_reads_a_switch_off_the_deploy_log_lost(tmp_path, monkeypatch):
    """The reality check under Best room rules this month reads each room's
    switch history; a switch-off only the watcher log has must end the
    stretch there too (#ES68FMKK, #CC94D9FB, Oct 02, 2026 12:56am)."""
    import json

    from tradingagents import backtest_report as br, forecast_v2 as f2, profiles
    from tradingagents import strategy_watcher as sw

    monkeypatch.setattr(sw, "LOG", tmp_path / "strategy_watcher.jsonl")
    pid = "CC94D9FB"
    rid = br.row_code("DVNSTOCK", "15m", "ibs", 0.0, 0.3, 0.4, "flat", res="1m")
    on, off = 1_791_000_000, 1_791_002_460
    with profiles.using(pid):
        # the watcher's switches are written per SLOT: the key and its coin in
        # strategy_key, as #CC94D9FB's own lines read
        lh.record_deployment({"changed_at": on, "strategy_key": f"{SLOT[0]}|{SLOT[1]}",
                              "symbol": "—", "action": "deployed", "books": "paper"})
        sw._log_path().write_text(json.dumps(
            {"at": off, "mode": "act", "action": "off", "id": rid, "why": "79.96%"}) + "\n",
            encoding="utf-8")
    monkeypatch.setattr(f2, "_settings", lambda p: {})
    got = f2._intervals(pid, now_s=1_791_300_000)
    assert got[f"{SLOT[0]}|{SLOT[1]}"] == [(on, off)], got


def test_a_deploy_line_up_to_45_minutes_after_the_decision_is_that_decision():
    """The watcher stamps a decision when its pass STARTS; the deploy line is
    the settings write, which in #4FC03172 came a median 24.9 minutes later
    (#55D32617 up to 36). The switch-on is the deploy time, never earlier."""
    from tradingagents import forecast_v2 as f2

    deploy_on, decided_on = 1_790_811_660_000, 1_790_810_220_000   # 24 min apart
    got = f2.merge_decisions([(deploy_on, None)], True,
                             {("R", "on"): [(decided_on, "")]}, "R")
    assert got == [(deploy_on, None)]


def test_a_switch_off_repeated_by_the_next_decision_was_not_carried_out():
    """#4FC03172, Oct 02, 2026: #3L97L8ZF logged "act off" at 9:20am (never
    written: no deploy line, the runner traded it at 11:01am) and again at
    Oct 03 2:48am (deploy disarm 2:53am). The strategy was on until 2:53am."""
    from tradingagents import forecast_v2 as f2

    on, off_1, off_2, disarm = 1_790_810_000_000, 1_790_850_000_000, 1_790_910_000_000, 1_790_910_300_000
    got = f2.merge_decisions([(on, disarm)], False,
                             {("R", "off"): [(off_1, ""), (off_2, "")]}, "R")
    assert got == [(on, disarm)], "the 9:20am switch-off never happened"


def test_a_pass_that_failed_before_writing_logs_its_switches_as_refused(monkeypatch):
    """RCA-2026-10-05-H: a switch-off pass that raised before its settings
    write left "act off" lines for switches that never happened."""
    from tradingagents import auto_trader as at
    from tradingagents import strategy_watcher as sw

    settings = {"strategy_coins": {"k": ["X_USDT"]}, "strategy_books": {"k|X_USDT": ["paper"]}}
    monkeypatch.setattr(at, "load_settings", lambda: json.loads(json.dumps(settings)))
    decided = [{"action": "off", "why": "#A X 15m - fell to 69%"},
               {"action": "report", "why": "kept"}]
    sw._undo_if_unwritten(decided, sw._armed_now(), "the switch-off check failed: OSError")
    assert decided[0]["action"] == "refused" and "nothing was written" in decided[0]["why"]
    assert decided[1]["action"] == "report"
    # a pass that DID write before raising keeps what it logged
    before = sw._armed_now()
    settings["strategy_coins"] = {"k": []}
    kept = [{"action": "off", "why": "#A"}]
    sw._undo_if_unwritten(kept, before, "x")
    assert kept[0]["action"] == "off"
