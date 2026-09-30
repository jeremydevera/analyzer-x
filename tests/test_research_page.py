"""The criteria-research page carries the kit and names what it compares.

Every rule set is a row with its dials first, Jul-Aug (where it was picked)
and September (which it never saw) side by side; a click opens both periods
day by day with a TOTAL PROFIT; the base-margin box re-prices everything; and
the operator's own rules and the picked ones are tagged by id, never by
position in the table.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import subprocess

import pytest

from tradingagents import research_page as rp
from tradingagents import watcher_research as wres
from tradingagents.positions_view import fmt_when


def _res():
    t0 = int(dt.datetime(2026, 7, 1).timestamp() * 1000)
    t1 = int(dt.datetime(2026, 9, 1).timestamp() * 1000)
    part = {"profit": 12.5, "closed": 20, "wins": 18, "losses": 2, "winrate": 90.0,
            "slots": 4, "open": 0, "worst_day": -1.6, "green_days": 10, "days_n": 3,
            "max_dd": 1.6, "worst_run": -1.6, "worst_run_n": 1, "max_open": 3,
            "days": [5.0, -1.6, 9.1]}
    cur = {"id": wres.rule_id(wres.CURRENT), "cfg": dict(wres.CURRENT),
           "train": part, "test": part}
    other_cfg = {**wres.CURRENT, "on_winrate": 85.0}
    other = {"id": wres.rule_id(other_cfg), "cfg": other_cfg,
             "train": {**part, "profit": 30.0}, "test": {**part, "profit": 20.0}}
    return {"train": [t0, t1 - 1], "test": [t1, t1 + 27 * 86_400_000],
            "end_ms": t1 + 27 * 86_400_000, "current_id": cur["id"],
            "best_train_id": other["id"], "combos": 5000,
            "totals": {"tested": 90_000_000, "coins_board": 1067,
                       "coins_by_groups": {"classic,preset": 1067},
                       "groups": ["classic", "preset"]},
            "rows": [cur, other]}


def test_every_rule_set_is_embedded_with_every_field():
    html = rp.build(_res())
    data = json.loads(re.search(r"const D = (\{.*?\});\n", html).group(1))
    assert len(data["rows"]) == 2
    for r in data["rows"]:
        assert len(r["c"]) == len(rp.DIALS) and len(r["tr"]) == len(rp.PARTS)
        assert r["ted"] == [5.0, -1.6, 9.1]
    assert data["current"] != data["best_train"]


def test_the_kit_is_on_the_page():
    html = rp.build(_res())
    cols = re.search(r"const COLS=\[(.*?)\];\n", html, re.S).group(1)
    assert cols.startswith('["id","rule",1]'), "a stable id first (kit H)"
    for label in ("PROFIT $", '"trades"', '"W"', '"L"', "win %", "worst run",
                  "worst day", "worst dip", "TP vs SL", "switched on"):
        assert label in cols, label
    for fid in ("f-base", "f-te", "f-tr", "f-wr", "f-dd", "f-on", "f-tp",
                "f-win", "f-id", "clear"):
        assert f'id="{fid}"' in html, fid
    assert "TOTAL PROFIT" in html and "never seen while tuning" in html
    assert "hindsight" in html, "the best-on-September card says it is not a fair test"
    assert "<title>Watcher Rules Research</title>" in html


def test_the_rule_dials_print_as_numbers_and_only_results_as_percents():
    html = rp.build(_res())
    assert 'key==="te_winrate"||key==="tr_winrate"' in html


def test_the_rule_id_is_hashed_from_the_rules():
    assert wres.rule_id(wres.CURRENT) == wres.rule_id(dict(reversed(list(wres.CURRENT.items()))))
    assert wres.rule_id(wres.CURRENT) != wres.rule_id({**wres.CURRENT, "min_trades": 21})


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_pages_date_format_is_the_projects():
    html = rp.build(_res())
    js = re.search(r"(const MON=.*?\nfunction fmtWhen\(ms\)\{.*?\n.*?\})\n", html, re.S).group(1)
    moments = [dt.datetime(2026, 8, 3, 20, 3), dt.datetime(2026, 9, 1, 0, 0),
               dt.datetime(2026, 9, 12, 12, 0)]
    ms = [int(m.timestamp() * 1000) for m in moments]
    out = subprocess.run(["node", "-e", js + f"\nfor (const m of {ms}) console.log(fmtWhen(m));"],
                         capture_output=True, text=True, timeout=60).stdout.split("\n")
    assert out[:3] == [fmt_when(m / 1000) for m in ms]


def test_a_rule_looser_than_its_data_is_never_picked():
    """RCA-2026-09-29-F: data written at 80% / 15 trades / TP >= SL cannot
    grade a 70% rule — it only holds strategies known to reach 80% later."""
    from tradingagents import research_page as rp

    w = {"wr": 80.0, "trades": 15, "tp": ">=", "windows": [30]}
    base = {"on_winrate": 80.0, "min_trades": 20, "tp_rule": ">"}
    assert rp.unfair(base, w) == ""
    assert "reached 80%" in rp.unfair({**base, "on_winrate": 70.0}, w)
    assert "15+" in rp.unfair({**base, "min_trades": 10}, w)
    assert "never held" in rp.unfair({**base, "tp_rule": "<"}, w)
    assert rp.unfair({**base, "tp_rule": "any"}, w) == "", "any over >= data IS at least"

    def row(rid, on, profit):
        part = {"profit": profit, "closed": 1, "wins": 1, "losses": 0, "winrate": 100.0,
                "slots": 1, "open": 0, "worst_day": 0.0, "green_days": 1, "days_n": 1,
                "max_dd": 0.0, "worst_run": 0.0, "worst_run_n": 0, "max_open": 1,
                "days": [profit]}
        cfg = {**base, "on_winrate": on, "off_winrate": on, "window_days": 30,
               "rank": "winrate", "max_per_coin": 3, "max_new_per_day": 20,
               "cooldown_days": 7, "off_streak_live": 0, "max_sl": 2.0}
        return {"id": rid, "cfg": cfg, "train": dict(part), "test": dict(part)}

    res = {"rows": [row("LOOSE70", 70.0, 999.0), row("FAIR80", 80.0, 10.0)],
           "train": [0, 1], "test": [0, 1], "end_ms": 1, "current_id": "FAIR80",
           "best_train_id": "LOOSE70", "combos": 2,
           "totals": {"tested": 2, "coins_board": 1, "write": w}}
    got = rp.payload(res)
    assert got["best_train"] == "FAIR80", "the hindsight row is never picked"
    assert next(r for r in got["rows"] if r["id"] == "LOOSE70")["unfair"]
