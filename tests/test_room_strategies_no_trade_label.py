"""Room strategies: "no trades" is not "stopped working" (operator, Oct 19,
2026: *"why are all 'stopped working'"*, then *"can you check 1 by 1 if its
really no trade?"*).

Checked one by one that day: 985 of the 1,008 kept rule sets had no trade
closing in their newest 15 days, 19 traded and lost, 4 made money, and every
count matched its own saved trades. The table printed "stopped working" for
all 1,004, so a rule set that found nothing to trade read the same as one
that lost. The row now carries the 15-day trade count, and the page picks
the label from it.
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


def _keep(c, trades):
    rst.keep([{"id": rst.sid(c), "cfg": c, "words": fr.words(c), "deployable": True,
               "deploy_why": "", "p4": rst.measure(trades, END, REAL), "trades": trades}],
             "r1", "RUN", now=1000)


def test_a_rule_set_with_no_recent_trade_is_told_apart_from_one_that_lost(monkeypatch):
    from tradingagents import forecast_v2 as f2

    quiet = rst.cfg(15, 70, 50, ">", 2.0)
    lost = rst.cfg(30, 70, 50, ">", 2.0)
    _keep(quiet, _trades([(2026, 8, 10, 1.0)]))                       # nothing in Sep 17 - Oct 02
    _keep(lost, _trades([(2026, 8, 10, 1.0), (2026, 9, 25, -0.8)]))  # a loss inside them
    monkeypatch.setattr(f2, "live", lambda *a, **k: {"reality": {"all": REAL}})
    rows = {r["id"]: r for r in rst.table(ms(2026, 7, 1, 0) / 1000,
                                          ms(2026, 10, 2, 23) / 1000)["rows"]}
    q, lo = rows[rst.sid(quiet)], rows[rst.sid(lost)]
    assert not q["still_works"] and q["last15_trades"] == 0
    assert not lo["still_works"] and lo["last15_trades"] == 1


def test_the_page_picks_the_label_from_the_count():
    src = (ROOT / "webapp/src/components/forecast/RoomForecasts.tsx").read_text(encoding="utf-8")
    i = src.index("no trades in its last 15 days")
    block = src[i - 300:i + 300]
    assert "r.last15_trades === 0" in block and "stopped working" in block
