"""A coin's past is priced with its USUAL gap, never with one reading of the book (RCA-2026-11-12-B).

What the operator's picker did on Nov 12, 2026 8:16pm: switched two of the three skill rooms off,
"a whole month lost money". The month had not changed - its price had. Every night the skill
backtest re-measured each coin's whole history with ONE reading of its order book taken as the
machine ran (about 7:10pm): CATL read 0.21% a side on Nov 11 and 0.86% on Nov 12, so the same
September trade (Sep 01, 2026 10:00pm, long, closed Sep 02 10:00am) was +$1.30 one night and -$0.01
the next, and the rule set #CKVS7G7Z's September went from +$148.62 to -$55.56 overnight. Of 1,078
coins, 283 had their cost a trade moved by more than $0.25 between those two nights.

The usual gap is the median of the coin's own recorded minutes over the last 30 days."""
import ast
import json
from pathlib import Path

import numpy as np
import pytest

from tradingagents import cost_store, skill_bt as sb, v4_store as v4

ROOT = Path(__file__).resolve().parents[1]
DAY = 86_400
NOV12 = 1_794_441_600            # Nov 12, 2026 12:00am UTC
NOV13 = NOV12 + DAY


def _packed(times, gaps, exhausted=None):
    """Recorded minutes in the costs store's own shape: buying and selling each cost `gap`."""
    n = len(times)
    out = {k: np.zeros(n) for k in cost_store.KEYS}
    out["t"] = np.asarray(times, dtype="int64")
    out["buy"] = np.asarray(gaps, dtype="float64")
    out["sell"] = np.asarray(gaps, dtype="float64")
    out["exhausted"] = np.zeros(n, bool) if exhausted is None else np.asarray(exhausted, bool)
    out["source"] = np.zeros(n, dtype="int64")
    return out


def _store(readings):
    """A fake costs store: `readings` = [(t, gap, exhausted)], served a month at a time."""
    asked = []

    def load(sym, ym, strict=False):
        asked.append((sym, ym, strict))
        mine = [r for r in readings if cost_store._month_key(r[0]) == ym]
        if not mine:
            return None
        return _packed([r[0] for r in mine], [r[1] for r in mine], [r[2] for r in mine])

    return load, asked


def _hourly(first_s, last_s, gap_at):
    return [(t, gap_at(t), False) for t in range(first_s, last_s, 3600)]


NO_APP = lambda sym, book, lo, hi: book                                   # noqa: E731


def test_the_usual_gap_is_the_median_of_the_recorded_minutes_of_the_last_thirty_days():
    # 0.2% all month, except the one hour the machine used to look at the book: 0.9%
    wild = NOV12 - 3600
    load, asked = _store(_hourly(NOV12 - 40 * DAY, NOV12 + DAY, lambda t: 0.009 if t == wild else 0.002))
    gap, n = sb.usual_gap("CATL_USDT", NOV12, load=load, books=NO_APP)
    assert gap == pytest.approx(0.002), "one wild hour is not what a coin usually costs"
    assert n == 30 * 24, "the 30 days before the run's midnight: nothing older, nothing after it"
    assert {a[1] for a in asked} == {"202610", "202611"} and all(a[2] is True for a in asked), \
        "every month the window touches, each read strictly"


def test_tomorrows_run_prices_the_coin_as_tonights_did():
    """The bug in one line: two nights, the same past, two prices. The median barely moves."""
    def gap_at(t):                       # a stock token: tight in market hours, wide for the rest of the day
        return 0.001 if 14 <= (t // 3600) % 24 < 21 else 0.006
    load, _ = _store(_hourly(NOV12 - 45 * DAY, NOV13 + DAY, gap_at))
    tonight, _n = sb.usual_gap("CATL_USDT", NOV12, load=load, books=NO_APP)
    tomorrow, _n = sb.usual_gap("CATL_USDT", NOV13, load=load, books=NO_APP)
    assert tonight == tomorrow == pytest.approx(0.006)
    # what the machine used to do: one look at 7:10pm New York (wide) or at 10:10am (tight)
    assert gap_at(NOV12 + 600) == 0.006 and gap_at(NOV12 + 15 * 3600) == 0.001


def test_a_minute_whose_book_ran_out_is_left_out_and_a_coin_with_no_minute_has_no_usual_gap():
    rows = _hourly(NOV12 - 10 * DAY, NOV12, lambda t: 0.003)
    rows = [(t, 0.9, True) if i % 2 else (t, g, e) for i, (t, g, e) in enumerate(rows)]
    load, _ = _store(rows)
    gap, n = sb.usual_gap("X_USDT", NOV12, load=load, books=NO_APP)
    assert gap == pytest.approx(0.003) and n == 10 * 24 // 2
    none, _ = _store([])
    assert sb.usual_gap("NEW_USDT", NOV12, load=none, books=NO_APP) == (None, 0)
    old, _ = _store(_hourly(NOV12 - 90 * DAY, NOV12 - 31 * DAY, lambda t: 0.002))
    assert sb.usual_gap("OLD_USDT", NOV12, load=old, books=NO_APP) == (None, 0), "minutes older than the window"


def test_the_apps_own_recorded_books_are_laid_over_the_record():
    load, _ = _store(_hourly(NOV12 - 30 * DAY, NOV12 - 20 * DAY, lambda t: 0.002))     # the record stops early
    seen = {}

    def books(sym, book, lo, hi):
        seen.update(sym=sym, lo=lo, hi=hi, had=len(book["t"]))
        mine = _hourly(NOV12 - 20 * DAY, NOV12, lambda t: 0.005)
        return cost_store.merge(book, _packed([r[0] for r in mine], [r[1] for r in mine]))

    gap, n = sb.usual_gap("CATL_USDT", NOV12, load=load, books=books)
    assert seen == {"sym": "CATL_USDT", "lo": NOV12 - 30 * DAY, "hi": NOV12, "had": 10 * 24}
    assert n == 30 * 24 and gap == pytest.approx(0.005), "20 of the 30 days are the app's own readings"
    assert sb.usual_gap.__kwdefaults__["books"] is None and "cost_store.with_app_books" in \
        (ROOT / "tradingagents" / "skill_bt.py").read_text(encoding="utf-8"), "the one rule every backtest reads by"


def test_a_month_that_cannot_be_read_fails_the_coin_instead_of_pricing_it_from_half_its_months():
    def load(sym, ym, strict=False):
        assert strict is True
        raise cost_store.CostReadError(f"{sym} {ym} could not be read")

    with pytest.raises(cost_store.CostReadError):
        sb.usual_gap("CATL_USDT", NOV12, load=load, books=NO_APP)


# ------------------------------------------------------------------ the machines' own script
def _costs(usual, live=0.0086):
    """The shard's `costs`, run with stand-ins for everything it reaches (the script itself needs a
    GitHub machine's environment to import)."""
    src = (ROOT / ".github" / "scripts" / "skill_shard.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "costs")
    looked = []

    class FX:
        @staticmethod
        def book_cost(sym, notional):
            looked.append((sym, notional))
            return {"slippage": live}

    class AT:
        LEVERAGE = 20

        @staticmethod
        def taker_fee(sym, fx=None):
            return 0.00075

    class SB:
        GAP_DAYS = sb.GAP_DAYS
        asked = []

        @staticmethod
        def usual_gap(sym, day_s):
            SB.asked.append((sym, day_s))
            return usual

    class SS:
        BASE_MARGIN = 5.0

    import time

    from tradingagents import backtest_report as br

    ns = {"at": AT, "fx": FX, "sb": SB, "ss": SS, "br": br, "time": time}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "skill_shard.costs", "exec"), ns)   # noqa: S102
    return ns["costs"], looked, SB.asked


def test_the_machines_price_a_coin_with_its_usual_gap_and_never_look_at_the_book_for_it():
    costs, looked, asked = _costs((0.0065, 36_769))
    fee, slip, gap = costs("CATL_USDT", now_s=NOV13 + 600)            # 7:10pm New York, the machine's hour
    assert (fee, slip) == (0.00075, 0.0065)
    assert gap == {"from": "minutes", "minutes": 36_769, "days": 30}
    assert not looked, "no reading of the book decides a coin's whole past"
    assert asked == [("CATL_USDT", NOV13)], "cut at the run's own UTC midnight: every machine the same minutes"


def test_only_a_coin_with_no_recorded_minute_pays_one_reading_and_its_lines_say_so():
    for nothing in ((None, 0), (0.0, 12)):
        costs, looked, _ = _costs(nothing)
        fee, slip, gap = costs("NEW_USDT", now_s=NOV13 + 600)
        assert slip == pytest.approx(0.0086) and looked == [("NEW_USDT", 100.0)]
        assert gap["from"] == "one reading" and gap["minutes"] == 0


def test_every_line_the_machines_write_carries_where_its_gap_came_from():
    src = (ROOT / ".github" / "scripts" / "skill_shard.py").read_text(encoding="utf-8")
    assert src.count('"gap": gap}') == 2, "the daily lines and the research lines alike"
    assert "fee, slip, gap = costs(sym)" in src
    assert src.count("fx.book_cost(") == 1, "one place may look at the book: the coin with no recorded minute"


def test_the_store_counts_where_each_coins_gap_came_from(tmp_path):
    def pick(pnl):
        return {"label": "ta_ma_pullback(n=1) stop 1.5%", "strategy": "ta_ma_pullback", "params": {"n": 1},
                "stop": 0.015, "target": 0.03, "older": {}, "newer": {}, "older_lost": False,
                "trades": [[1_790_000_000_000, 1_790_003_600_000, 1, "TP", pnl]]}

    def line(coin, tf, gap):
        x = {"coin": coin, "tf": tf, "fee": 0.00075, "slip": 0.002, "bars": 900, "combos": 1,
             "split_ms": 1_789_000_000_000, "start_ms": 1_788_000_000_000, "end_ms": 1_790_100_000_000,
             "bar": 0.0, "picks": [pick(1.0)]}
        return {**x, "gap": gap} if gap else x

    lines = {"AAA|1h": line("AAA", "1h", {"from": "minutes", "minutes": 40_000, "days": 30}),
             "AAA|4h": line("AAA", "4h", {"from": "minutes", "minutes": 40_000, "days": 30}),
             "NEW|1h": line("NEW", "1h", {"from": "one reading", "minutes": 0, "days": 30})}
    (tmp_path / "skilldaily.json").write_text(json.dumps({"lines": lines}), encoding="utf-8")
    meta = v4.build(tmp_path, target=tmp_path / "rows.db", sources=v4.DAILY_SOURCES, log=lambda *_: None)
    assert meta["gaps"] == {"minutes": 1, "one reading": 1}, "counted a coin, not a line"
    # a store filed from runs older than this says nothing rather than something false
    (tmp_path / "skilldaily.json").write_text(json.dumps({"lines": {"AAA|1h": line("AAA", "1h", None)}}), encoding="utf-8")
    assert "gaps" not in v4.build(tmp_path, target=tmp_path / "rows2.db", sources=v4.DAILY_SOURCES, log=lambda *_: None)
