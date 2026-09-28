"""The watcher-replay results page carries the whole standard kit.

CLAUDE.md "Backtest reporting requirements": profit, TP, SL, leverage, wins,
losses, the worst losing run, trades (and trades/day), combinations tested,
a stable id first, click-for-log with a TOTAL PROFIT, a base-margin box, sort,
and the filters in the unit their column prints. The page prints dates through
its own JS copy of the project format, so that copy is run in node against
`positions_view.fmt_when` on the instants that broke it before.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import subprocess

import pytest

from tradingagents import replay_page as rp
from tradingagents.positions_view import fmt_when


def _res():
    t0 = int(dt.datetime(2026, 9, 1).timestamp() * 1000)
    slot = {"id": "77Y3BPFG", "coin": "GPNSTOCK", "tf": "1h", "signal": "macddiv",
            "th": 0.0, "sl": 0.7, "tp": 1.0, "on_ms": t0, "off_ms": None,
            "on_why": "100% over 20 trades", "off_why": "",
            "on_row": {"trades": 20, "wins": 20, "losses": 0, "winrate": 100.0,
                       "profit": 15.84},
            "trades": [[t0 + 3_600_000, t0 + 7_200_000, 0.82, 1]]}
    return {"run": "1", "repo": "o/r", "end_ms": t0 + 9 * 86_400_000,
            "combos_written": 1, "cfg": {"on_winrate": 90.0, "off_winrate": 90.0,
                                         "min_trades": 20, "max_slots": 100,
                                         "max_per_coin": 3, "max_new_per_day": 20,
                                         "cooldown_days": 7},
            "totals": {"tested": 49_000_000, "coins_done": 1000,
                       "coins_board": 1067, "pairs": 5000, "machines": 20,
                       "failed": {}, "short": []},
            "summary": {"start_ms": t0}, "slots": [slot],
            "events": [{"at": t0, "action": "on", "id": "77Y3BPFG",
                        "coin": "GPNSTOCK", "why": "100% over 20 trades"}]}


def test_every_slot_and_every_trade_is_embedded():
    html = rp.build(_res())
    data = json.loads(re.search(r"const D = (\{.*?\});\n", html).group(1))
    assert data["tested"] == 49_000_000 and len(data["slots"]) == 1
    s = data["slots"][0]
    for k in ("id", "coin", "tf", "signal", "tp", "sl", "on", "off", "t"):
        assert k in s, k
    assert s["t"] == [[s["on"] + 3_600_000, s["on"] + 7_200_000, 0.82, 1]]


def test_the_kit_columns_and_filters_are_on_the_page():
    html = rp.build(_res())
    cols = re.search(r"const COLS=\[(.*?)\];", html).group(1)
    assert cols.startswith('["id","id",1]'), "a stable id is the first column (kit H)"
    for label in ("PROFIT $", "TP %", "SL %", '"lev"', '"trades"', "trades/day",
                  '"wins"', '"losses"', "worst losing run", "months green"):
        assert label in cols, label
    for fid in ("f-base", "f-days", "f-wr", "f-pf", "f-mg", "f-dd", "f-tp",
                "f-sl", "f-id", "clear"):
        assert f'id="{fid}"' in html, fid
    assert "TOTAL PROFIT" in html and "showModal" in html
    assert "combinations tested" in html
    assert "<title>Watcher Replay</title>" in html


def test_the_page_says_how_it_settles_exits():
    html = rp.build(_res())
    assert "1-minute candles" in html and "counted as the stop" in html


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_pages_date_format_is_the_projects():
    html = rp.build(_res())
    js = re.search(r"(const MON=.*?\nfunction fmtWhen\(ms\)\{.*?\n.*?\})\n", html,
                   re.S).group(1)
    moments = [dt.datetime(2026, 8, 3, 20, 3), dt.datetime(2026, 9, 1, 0, 0),
               dt.datetime(2026, 9, 12, 12, 0), dt.datetime(2026, 9, 28, 9, 5)]
    ms = [int(m.timestamp() * 1000) for m in moments]
    out = subprocess.run(["node", "-e", js + f"\nfor (const m of {ms}) console.log(fmtWhen(m));"],
                         capture_output=True, text=True, timeout=60).stdout.split("\n")
    assert out[:4] == [fmt_when(m / 1000) for m in ms]


def test_every_strategy_names_its_group_and_can_be_filtered_by_it():
    res = _res()
    res["slots"][0]["group"] = "sep25"
    res["totals"]["groups"] = ["classic", "preset", "sep25", "sep27ml"]
    html = rp.build(res)
    data = json.loads(re.search(r"const D = (\{.*?\});\n", html).group(1))
    assert data["slots"][0]["group"] == "sep25"
    assert data["groups"] == ["classic", "preset", "sep25", "sep27ml"]
    assert '["group","group",1]' in html and 'id="f-grp"' in html
    assert "judged on the same days they were learned from" in html
