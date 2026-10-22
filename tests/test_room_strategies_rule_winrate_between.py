"""Room strategies: filter by the RULE's own win line, between two numbers
(operator, Oct 21, 2026: *"can you add filter to these like winrate between so
when i click it, it will show room strategy that has criteria of 70% or 80% if
my filter is between 50-80%"*).

The Rules column prints each rule set's switch-on line first ("70% wins, 50+
trades in 30 days, ..."), and that is the number this filter reads — never the
win rate the dates measured, which "min win %" already filters. Both ends are
included, in the percent the column prints, and either end may be left empty.
The 1,008 kept that day asked 60% (34), 65% (45), 70% (151), 75% (132), 80%
(224), 85% (78), 90% (300) and 95% (44), so 50-80 keeps 586 of them.

Every test writes to tmp_path through ROOM_STRATEGIES_HOME; trades sit on one
timeline, Sep 2026.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from tradingagents import forecast_rules as fr
from tradingagents import room_strategies as rst

ROOT = Path(__file__).resolve().parents[1]
REAL = {"took": 0.5, "gap": 0.1}
END = int(dt.datetime(2026, 10, 2, 12).timestamp() * 1000)


def ms(y, m, d, h=12):
    return int(dt.datetime(y, m, d, h).timestamp() * 1000)


def _trades(spec):
    return [[ms(y, m, d) - 3_600_000, ms(y, m, d), p] for y, m, d, p in spec]


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("ROOM_STRATEGIES_HOME", str(tmp_path / "store"))
    rst._KEPT.clear()
    rst._TABLE.clear()
    yield
    rst._KEPT.clear()
    rst._TABLE.clear()


LO, HI = ms(2026, 9, 1, 0) / 1000, ms(2026, 9, 30, 23) / 1000


def _keep(lines):
    """One kept rule set per win line; the 90% one has NO trade in Sep."""
    out = {}
    for wr in lines:
        c = rst.cfg(30, wr, 20, ">", 2.0)
        t = (_trades([(2026, 8, 10, 1.0)]) if wr == 90
             else _trades([(2026, 9, 10, 1.0), (2026, 9, 12, -0.5)]))
        rst.keep([{"id": rst.sid(c), "cfg": c, "words": fr.words(c), "deployable": True,
                   "deploy_why": "", "p4": rst.measure(t, END, REAL), "trades": t}],
                 "r1", "RUN", now=1000)
        out[wr] = rst.sid(c)
    return out


def _lines(got):
    return sorted(r["rule_wr"] for r in got["rows"])


def test_between_keeps_the_rule_sets_whose_line_is_inside_both_ends_included():
    _keep([60, 70, 80, 90])
    every = rst.table(LO, HI, reality=REAL, per=50)
    assert every["matched"] == 4 and _lines(every) == [60.0, 70.0, 80.0, 90.0], "every row says its line"
    got = rst.table(LO, HI, reality=REAL, per=50, rule_wr_min=70, rule_wr_max=80)
    assert _lines(got) == [70.0, 80.0], "the operator's own example: 70% and 80%, both ends included"
    assert got["matched"] == 2 and got["kept"] == 4, "the count says what was examined"
    assert _lines(rst.table(LO, HI, reality=REAL, per=50, rule_wr_min=50, rule_wr_max=80)) == [60.0, 70.0, 80.0]


def test_either_end_alone_is_a_floor_or_a_ceiling():
    _keep([60, 70, 80, 90])
    assert _lines(rst.table(LO, HI, reality=REAL, per=50, rule_wr_min=80)) == [80.0, 90.0]
    assert _lines(rst.table(LO, HI, reality=REAL, per=50, rule_wr_max=70)) == [60.0, 70.0]


def test_the_rules_line_is_not_the_dates_win_rate():
    """The 90% rule set has no trade in Sep: it has no measured win rate, so
    it passes no "min win %" floor (RCA-2026-10-07-N) — but its RULE still asks
    90%, which is what this filter is about."""
    ids = _keep([60, 70, 80, 90])
    got = rst.table(LO, HI, reality=REAL, per=50, rule_wr_min=85, rule_wr_max=95)
    assert [r["id"] for r in got["rows"]] == [ids[90]]
    assert got["rows"][0]["trades"] == 0 and got["rows"][0]["winrate"] is None


def test_it_stacks_with_the_other_filters():
    _keep([60, 70, 80, 90])
    # every Sep row here won 1 of 2 = 50%: a 60% floor on the dates' win rate keeps none of them
    assert rst.table(LO, HI, reality=REAL, per=50, rule_wr_min=50, rule_wr_max=80, min_winrate=60)["matched"] == 0
    assert rst.table(LO, HI, reality=REAL, per=50, rule_wr_min=50, rule_wr_max=80, min_winrate=50)["matched"] == 3


def test_a_range_no_rule_set_asks_names_the_lines_that_exist():
    """An empty page names what it examined: 50-55 matches none of 60/70/80/90,
    so the answer carries every line the kept ask and that none is inside."""
    _keep([60, 70, 80, 90])
    got = rst.table(LO, HI, reality=REAL, per=50, rule_wr_min=50, rule_wr_max=55)
    assert got["matched"] == 0 and got["rule_matched"] == 0 and got["kept"] == 4
    assert got["rule_lines"] == [[60.0, 1], [70.0, 1], [80.0, 1], [90.0, 1]]
    # counted BEFORE the other filters: 70-80 holds 2 rule sets even when the
    # dates' win-rate floor then cuts both
    cut = rst.table(LO, HI, reality=REAL, per=50, rule_wr_min=70, rule_wr_max=80, min_winrate=60)
    assert cut["matched"] == 0 and cut["rule_matched"] == 2
    assert rst.table(LO, HI, reality=REAL, per=50)["rule_matched"] is None, "no rule filter, no count"
    s = _section()
    assert "d.rule_matched === 0" in s and "No kept rule set asks for those win rates" in s


def test_a_from_above_its_to_is_refused_by_name():
    _keep([70])
    with pytest.raises(ValueError, match="rule win %"):
        rst.table(LO, HI, reality=REAL, rule_wr_min=80, rule_wr_max=50)


def test_the_route_takes_both_ends(monkeypatch):
    from fastapi import HTTPException

    from tradingagents import api
    from tradingagents import forecast_v2_api as f2a

    monkeypatch.setitem(f2a._LIVE, "value", {"reality": {"all": REAL}, "at": 0})
    _keep([60, 70, 80, 90])
    got = api.room_strategies_route(LO, HI, rule_wr_min=50, rule_wr_max=80)
    assert got["matched"] == 3 and got["kept"] == 4
    with pytest.raises(HTTPException) as e:
        api.room_strategies_route(LO, HI, rule_wr_min=80, rule_wr_max=50)
    assert e.value.status_code == 400


def _section() -> str:
    src = (ROOT / "webapp/src/components/forecast/RoomForecasts.tsx").read_text(encoding="utf-8")
    return src


def test_the_page_sends_both_ends_and_names_them():
    s = _section()
    # two boxes under one label, in the percent the Rules column prints
    assert "rule win % between" in s
    assert 'aria-label="rule win % from"' in s and 'aria-label="rule win % to"' in s
    # sent on Apply, with the rest of the ask, never while typing
    assert "rule_wr_min: ask.rule_wr_min" in s and "rule_wr_max: ask.rule_wr_max" in s
    # refused out loud, never sent as no filter
    assert "rule win % takes a number from 0 to 100" in s
    assert "the rule win % 'from' is above its 'to'" in s
    # the line above the table names it, from what was applied — and a back
    # end that ignored the boxes (older code, before its restart) says so
    assert "rules that need" in s
    assert "d.rule_matched == null" in s and "has not applied" in s
    api_ts = (ROOT / "webapp/src/lib/api.ts").read_text(encoding="utf-8")
    assert 'p.set("rule_wr_min"' in api_ts and 'p.set("rule_wr_max"' in api_ts
