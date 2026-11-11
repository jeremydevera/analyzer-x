"""Strategies for every coin and every timeframe (CLAUDE.md, Nov 05, 2026): a v2 pick is CHOSEN on its
older 15 days only, ranked by its cost against its target, identical results kept once, and the
newest 15 days are left to check it. `tradingagents.acs`."""
from tradingagents import acs


def _row(i, *, trades=20, wins=12, profit=5.0, t15=10, w15=5, p15=-1.0, tp=2.0, sl=1.0, rt=0.2,
         rt_paid=None):
    return {"id": f"R{i}", "coin": "BTC", "tf": "1h", "signal": "rsi2", "th": 0.0, "sl": sl, "tp": tp,
            "trades": trades, "wins": wins, "profit": profit, "t15": t15, "w15": w15, "p15": p15,
            "rt": rt, "rt_paid": rt_paid}


def test_older_is_the_thirty_days_less_the_newest_fifteen():
    assert acs.older(_row(1)) == {"trades": 10, "wins": 7, "profit": 6.0}


def test_a_pick_is_chosen_on_the_older_days_never_the_newest():
    # R1 lost on the older 15 days and won big on the newest: it must NOT be chosen
    rows = [_row(1, profit=30.0, p15=40.0), _row(2, profit=5.0, p15=-1.0)]
    got = [p["id"] for p in acs.pick_pair(rows, "1h")]
    assert got == ["R2"]


def test_too_few_older_trades_is_not_a_pick():
    rows = [_row(1, trades=10, t15=5)]           # 5 older trades, 1h needs 6
    assert acs.pick_pair(rows, "1h") == []
    assert len(acs.pick_pair(rows, "4h")) == 1   # 4h needs 4


def test_ranked_by_cost_against_target_lowest_first_and_rt_paid_wins_over_the_estimate():
    rows = [_row(1, tp=2.0, rt=0.4), _row(2, tp=4.0, rt=0.4, wins=13), _row(3, tp=2.0, rt=0.4,
                                                                              rt_paid=0.1, wins=11)]
    assert [p["id"] for p in acs.pick_pair(rows, "1h")] == ["R3", "R2", "R1"]


def test_identical_results_are_kept_once_and_at_most_per_pair():
    rows = [_row(i, tp=2.0 + i * 0.1) for i in range(6)]     # same trades, wins, profit on both halves
    assert len(acs.pick_pair(rows, "1h")) == 1
    rows = [_row(i, wins=10 + i) for i in range(6)]
    assert len(acs.pick_pair(rows, "1h")) == acs.PER_PAIR


def test_a_row_without_the_newest_count_is_never_a_pick():
    assert acs.pick_pair([_row(1, t15=None)], "1h") == []


def test_the_pair_bar_is_the_average_rows_newest_fifteen_days():
    bar = acs.pair_bar([_row(1, t15=10, p15=-2.0), _row(2, t15=10, p15=1.0), _row(3, t15=None)])
    assert bar == {"rows": 2, "trades": 20, "profit": -1.0, "per_trade": -0.05, "share_positive": 0.5}


def test_the_plan_lists_every_pick_and_its_id_follows_the_configs():
    picks = {"made_s": 1, "pairs": {"BTC-1h": {"coin": "BTC", "tf": "1h", "picks": [
        {"signal": "rsi2", "th": 0.0, "sl": 1.2, "tp": 4.0}, {"signal": "mom6", "th": 0.2, "sl": 0.3,
                                                              "tp": 0.4}]}}}
    plan = acs.plan_of(picks)
    assert plan["configs"] == {"BTC": {"1h": ["rsi2:0:1.2:4", "mom6:0.2:0.3:0.4"]}}
    picks["pairs"]["BTC-1h"]["picks"].pop()
    assert acs.plan_of(picks)["id"] != plan["id"]


def test_github_answers_are_read_as_utf8_so_a_run_title_with_a_dot_matches(monkeypatch):
    # RCA-2026-11-05-A: read in this PC's code page, "·" in the title never matched
    seen = {}

    class Done:
        returncode, stdout, stderr = 0, "All coins strategies · x · 1 of 3", ""

    def fake(cmd, **kw):
        seen.update(kw)
        return Done()

    monkeypatch.setattr(acs.subprocess, "run", fake)
    assert "· 1 of 3" in acs._gh("run", "list")
    assert seen.get("encoding") == "utf-8"


def test_every_pair_gets_candidates_and_a_strategy_that_lost_where_it_was_chosen_says_so():
    rows = [_row(1, profit=5.0, p15=-1.0)] + [_row(i, profit=-2.0 - i, wins=5 + i, p15=1.0)
                                             for i in range(2, 9)]
    got = acs.candidates(rows, "1h")
    assert len(got) == acs.CANDIDATES
    assert got[0]["id"] == "R1" and not got[0]["older_lost"]
    assert all(g["older_lost"] for g in got[1:])
    # filled best older profit first: R2 lost least on the older days
    assert got[1]["id"] == "R2"


def test_a_pair_with_no_usable_row_has_no_candidates():
    assert acs.candidates([_row(1, tp=0), _row(2, trades=0, wins=0, t15=0, w15=0)], "1h") == []


def test_a_coin_too_new_for_older_days_still_gets_strategies_flagged_unchecked():
    rows = [_row(i, trades=12 + i, wins=6, t15=12 + i, w15=6, profit=float(i), p15=float(i))
            for i in range(1, 4)]
    got = acs.candidates(rows, "1h")
    assert [g["id"] for g in got] == ["R3", "R2", "R1"]
    assert all(g.get("unchecked") for g in got)


def test_a_skill_redo_replaces_its_lines_and_clears_their_reasons(tmp_path, monkeypatch):
    import json as _j

    monkeypatch.setattr(acs, "home", lambda: tmp_path)
    (tmp_path / "skill.json").write_text(_j.dumps({"lines": {"BTC|1h": {"coin": "BTC", "tf": "1h"}},
                                                   "failed": ["NEW 1d: no Day1 candles"],
                                                   "skipped": ["NEW 4h: only 30 candles"]}))
    out = tmp_path / "redo"
    out.mkdir()
    (out / "skill-0.jsonl").write_text(_j.dumps({"coin": "NEW", "tf": "4h", "picks": []}) + "\n")
    (out / "skill-report-0.json").write_text(_j.dumps([{"coin": "NEW", "tf": "1d", "error": "no Day1 candles"}]))
    got = acs.merge_skill(out)
    saved = _j.loads((tmp_path / "skill.json").read_text())
    assert set(saved["lines"]) == {"BTC|1h", "NEW|4h"}
    assert saved["skipped"] == [] and saved["failed"] == ["NEW 1d: no Day1 candles"]
    assert got == {"redone": 1, "failed": 1, "skipped": 0}


def test_a_whole_market_skill_run_keeps_its_own_state_apart_from_a_redo():
    # the dealt coin list replaced the "named coins" argument, so every skill dispatch looked like a
    # redo and a whole-market run would have written skill-redo-state.json (found Nov 05, 2026)
    assert acs._state_name(True, False) == "skill-state.json"
    assert acs._state_name(True, True) == "skill-redo-state.json"
    assert acs._state_name(True, False, "ta") == "skillta-state.json"
    assert acs._state_name(False, False) == "state.json"


def test_a_redo_of_any_set_keeps_its_own_state():
    # a machine lost mid-run on Nov 05, 2026 left 15 coins of the every-strategy run unmeasured;
    # they are redone alone, so the set's redo needs a state of its own beside the whole run's
    assert acs._state_name(True, True, "ta_all") == "skilltaall-redo-state.json"
    assert acs._state_name(True, True, "ta") == "skillta-redo-state.json"


def test_the_every_strategy_set_keeps_its_own_files():
    assert acs._state_name(True, False, "ta_all") == "skilltaall-state.json"
    assert acs.SKILL_PREFIX == {"bt": "skill", "ta": "skillta", "ta_all": "skilltaall",
                               "daily": "skilldaily"}


def test_a_redone_coin_leaves_the_not_reached_list(tmp_path, monkeypatch):
    import json as _j

    monkeypatch.setattr(acs, "home", lambda: tmp_path)
    (tmp_path / "skilltaall.json").write_text(_j.dumps({"lines": {}, "failed": [], "skipped": [],
                                                        "not_reached": ["GE", "HLT"]}))
    out = tmp_path / "redo"
    out.mkdir()
    (out / "skilltaall-0.jsonl").write_text(_j.dumps({"coin": "GE", "tf": "1h", "picks": []}) + "\n")
    acs.merge_skill(out, "ta_all")
    saved = _j.loads((tmp_path / "skilltaall.json").read_text())
    assert saved["not_reached"] == ["HLT"] and "GE|1h" in saved["lines"]
