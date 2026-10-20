"""The Pro Trader results page's data (tradingagents/pro_page.py, Oct 20, 2026):
the choice, the check plan the machines read, and each row's untouched days.
Made-up numbers, worked out by hand."""
from __future__ import annotations

import gzip
import json

import numpy as np

from tests.test_pro_report import GOOD, _line, _lines
from tradingagents import backtest_report as br, pro_page as pg, pro_report as pr

DAY = 86_400_000
LAST = 1_790_000_000                     # the search's last 15m bar (unix s)


def _search(rows, coins=("A", "B", "C")):
    L = _lines(rows, coins)
    stats = {c: {"vol": 2.0, "vr": 1.1, "kind": "crypto",
                 "pre": {"fine_from": 1, "book_lo": 2, "slip": 0.0003, "slip_source": "x"}}
             for c in coins}
    report = [{"coin": c, "tf": "15m", "last": LAST} for c in coins]
    return {"lines": L, "mon": pr.months(L), "stats": stats, "report": report,
            "groups": dict.fromkeys(coins, "g")}


def _trades(n_before, n_after, win=1.30, loss=-0.60):
    """n_before trades closed before the untouched days, n_after inside,
    alternating win/loss; [entry, exit, side, why, profit, cost]."""
    start = LAST * 1000 - 120 * DAY
    out = []
    for k in range(n_before):
        x = start - (n_before - k) * DAY
        out.append([x - 3_600_000, x, 1, "TP" if k % 2 == 0 else "SL", win if k % 2 == 0 else loss, 0.23])
    for k in range(n_after):
        x = start + k * DAY + 60_000
        out.append([x - 3_600_000, x, -1, "TP" if k % 2 == 0 else "SL", win if k % 2 == 0 else loss, 0.23])
    return out


def test_the_plan_carries_the_searchs_bars_costs_and_the_check_runs_spelling(tmp_path):
    S = _search([(0, 0, _line((60, 20, 30.0), GOOD))])
    picks = pr.choose(S["lines"], S["mon"], S["groups"], upto=1)
    plan = pg.check_plan(S, picks)
    assert list(plan) == ["A"]
    assert plan["A"]["pre"]["slip"] == 0.0003
    assert plan["A"]["tfs"]["15m"] == {"last": LAST, "keys": ["pt_aaa_x0:15m:0.4:1.5"]}
    path = pg.write_plan(plan, tmp_path / "research" / "pro" / "p.json.gz")
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        assert json.load(fh) == plan


def test_a_pick_the_report_cannot_date_is_refused():
    S = _search([(0, 0, _line((60, 20, 30.0), GOOD))])
    S["report"] = [{"coin": "A", "tf": "15m", "error": "boom"}]
    picks = pr.choose(S["lines"], S["mon"], S["groups"], upto=1)
    try:
        pg.check_plan(S, picks)
    except ValueError as exc:
        assert "A 15m" in str(exc)
    else:
        raise AssertionError("a pick with no dated pair must be refused")


def test_a_row_shows_only_its_untouched_days_and_says_when_the_counts_disagree():
    S = _search([(0, 0, _line((60, 20, 30.0), GOOD))])       # 4 x 5 = 20 untouched trades
    picks = pr.choose(S["lines"], S["mon"], S["groups"], upto=1)
    key = pg.key_of(S["lines"], 0)
    lines = [{"coin": "A", "tf": "15m", "cfg": key, "trades": _trades(7, 20)}]
    rows, files, problems = pg.rows(S, picks, {}, lines)
    assert problems == []
    (r,) = rows
    assert r["id"] == br.row_code("A", "15m", "pt_aaa_x0", 0.0, 0.4, 1.5, "flat", res="1m")
    assert len(r["tr"]) == 20 and all(x >= LAST * 1000 - 120 * DAY for x, _p in r["tr"])
    assert files[r["file"]][r["id"]][0][:4] == [_trades(7, 20)[7][0], _trades(7, 20)[7][1], -1, "TP"]
    assert r["chosen_on"]["trades"] == 60 and r["how"] == "group default"
    # 1.5 - 0.2 = 1.3 a win, 0.4 + 0.2 = 0.6 a loss: break-even 0.6 / 1.9
    assert abs(r["be"] - 31.58) < 0.01
    # one trade fewer from the check run than the search counted: NAMED
    lines[0]["trades"] = _trades(7, 19)
    _rows, _f, problems = pg.rows(S, picks, {}, lines)
    assert problems and "19" in problems[0] and "20" in problems[0]


def test_a_pick_the_check_run_did_not_return_is_named_never_dropped_quietly():
    S = _search([(0, 0, _line((60, 20, 30.0), GOOD))])
    picks = pr.choose(S["lines"], S["mon"], S["groups"], upto=1)
    rows, _files, problems = pg.rows(S, picks, {}, [])
    assert rows == [] and problems and "returned no trades" in problems[0]


def test_the_luck_bar_and_the_walk_forward_add_up():
    rows = [(0, 0, _line((60, 20, 30.0), GOOD)),
            (0, 4, _line((60, 20, 10.0), [(10, 2, -1.5)] * 4)),   # pt_rand, same coin/tf/bar
            (1, 4, _line((60, 20, 10.0), [(10, 2, -9.0)] * 4))]   # pt_rand on another coin
    S = _search(rows)
    picks = pr.choose(S["lines"], S["mon"], S["groups"], upto=1)
    b = pg.baseline(S, picks)
    assert b == {"trades": 40, "profit": -6.0, "per_trade": -0.15}
    wf = {(0, 0): [(0, "own pick", 5, 2, 1.0), None, (0, "own pick", 5, 2, -2.0), None]}
    assert pg.walk_total(wf) == {"picks": 2, "trades": 10, "wins": 4, "profit": -1.0}
    assert np.isfinite(b["per_trade"])
