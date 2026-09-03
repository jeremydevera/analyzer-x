"""TP and SL are RANGES: between a low and a high, both ends inclusive.

Operator, 2026-09-03: *"create filter to tp using between / EXAMPLE BETWEEN .5
- 2.5 / SAME FOR SL"*.

Each box was a lone ceiling, so "TP from 0.5% to 2.5%" could not be asked —
and a ceiling by itself keeps the pennies-in-front-of-a-steamroller rows the
kit rules were written about: a 0.05% target that the round-trip cost eats,
winning 96 times and giving it all back on one loss (JPY 30m fade15, TP 0.3%
against SL 2%).

Measured against the operator's own store right after the change (49.8M rows):

    min_tp=0.5&max_tp=2.5                   0.2s, 200 rows, tp 2.00..2.50
    min_sl=0.5&max_sl=1.5                   0.5s, 200 rows, sl 0.50..1.50
    min_tp=0.5&max_tp=2.5&min_sl=0.5&max_sl=1.5
                                            0.6s, tp 2.00..2.50, sl 0.50..1.50

Neither column has an index, so both bounds carry the `+` no-index hint for the
same reason the ceiling always did: if a tp or sl index is ever added, the `+`
is what keeps the ORDER BY's own index instead of sorting every match in a
temp b-tree.
"""
import io
import json

import pytest

from tradingagents import api, market_sweep as msw, rows_index as ri

PANEL = "webapp/src/components/backtest/StrategiesPanel.tsx"


def _row(signal, tp, sl, profit=10.0, coin="AAA", tf="1h", trades=120,
         winrate=60.0, sizing="flat"):
    wins = round(trades * winrate / 100)
    return {"coin": coin, "tf": tf, "signal": signal, "th": 0.1, "sl": sl,
            "tp": tp, "rr": round(tp / sl, 2) if sl else 0, "sizing": sizing,
            "lev": 20, "base": 5.0, "notional": 100.0, "trades": trades,
            "wins": wins, "losses": trades - wins, "winrate": winrate,
            "profit": profit, "funding": -0.2, "h1": profit / 2,
            "h2": profit / 2, "green": 8, "months": 12, "worst": -4.1,
            "dd": 22.0, "liqs": 0, "stop_reachable": True, "days": 360,
            "bars": 34000, "monthly": {"2026-08": profit / 3},
            "cost_of_tp": 12.5, "rt": 0.04, "gate": "ok"}


def _settled(**kw):
    import time

    return ri.sync(now=time.time() + ri.SETTLE_S + 1, **kw)


@pytest.fixture
def store(tmp_path, monkeypatch):
    """TPs and SLs that sit ON the operator's own bounds (0.5 and 2.5), so an
    exclusive comparison would be visible, plus rows outside on both sides."""
    rows_dir = tmp_path / "rows"
    rows_dir.mkdir()
    monkeypatch.setattr(msw, "ROWDIR", rows_dir)
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    (rows_dir / "AAA-1h.json").write_text(json.dumps([
        _row("scalp", tp=0.3, sl=0.2, profit=99.0),    # under the floor: goes
        _row("low_edge", tp=0.5, sl=0.5, profit=40.0),  # ON the floor: stays
        _row("middle", tp=1.5, sl=1.0, profit=30.0),
        _row("high_edge", tp=2.5, sl=1.5, profit=20.0),  # ON the ceiling: stays
        _row("wide", tp=4.0, sl=2.0, profit=80.0),      # over: goes
    ]))
    _settled()
    return None


# --------------------------------------------------------------- the SQL

def test_both_bounds_reach_the_query_and_step_aside_for_the_order():
    where, args = ri._where(min_tp=0.5, max_tp=2.5, min_sl=0.5, max_sl=1.5)
    assert "tp <= ?" in where and "tp >= ?" in where
    assert "sl <= ?" in where and "sl >= ?" in where
    assert args == [2.5, 0.5, 1.5, 0.5], args
    row_where, _ = ri._where(min_tp=0.5, max_tp=2.5, min_sl=0.5, max_sl=1.5,
                             order_owns_index=True, order_key="profit")
    for term in ("+tp <= ?", "+tp >= ?", "+sl <= ?", "+sl >= ?"):
        assert term in row_where, term


# ------------------------------------------------------------- the answer

def test_tp_between_keeps_both_ends_and_drops_what_is_outside(store):
    got = ri.query(min_tp=0.5, max_tp=2.5)
    names = sorted(r["signal"] for r in got["rows"])
    assert names == ["high_edge", "low_edge", "middle"], names
    assert got["total"] == 3, "the count is of what MATCHES"
    tps = [r["tp"] for r in got["rows"]]
    assert 0.5 in tps and 2.5 in tps, "both ends are INCLUSIVE"
    assert 0.3 not in tps, "the 0.3% scalp is out, best profit or not"
    assert 4.0 not in tps


def test_sl_between_is_its_own_range(store):
    got = ri.query(min_sl=0.5, max_sl=1.5)
    assert sorted(r["signal"] for r in got["rows"]) == [
        "high_edge", "low_edge", "middle"]
    assert all(0.5 <= r["sl"] <= 1.5 for r in got["rows"])


def test_the_two_ranges_stack_as_AND(store):
    got = ri.query(min_tp=1.0, max_tp=2.5, min_sl=1.4, max_sl=1.6)
    assert [r["signal"] for r in got["rows"]] == ["high_edge"], got["rows"]


def test_one_end_alone_still_filters(store):
    """A half-open range is a perfectly good filter."""
    assert sorted(r["signal"] for r in ri.query(min_tp=2.5)["rows"]) == [
        "high_edge", "wide"]
    assert sorted(r["signal"] for r in ri.query(max_tp=0.5)["rows"]) == [
        "low_edge", "scalp"]


def test_the_floors_are_echoed_so_the_screen_can_caption_the_rows(store):
    got = ri.query(min_tp=0.5, max_tp=2.5, min_sl=0.5, max_sl=1.5)
    assert got["min_tp"] == 0.5 and got["max_tp"] == 2.5
    assert got["min_sl"] == 0.5 and got["max_sl"] == 1.5
    plain = ri.query()
    assert plain["min_tp"] == 0.0 and plain["min_sl"] == 0.0


def test_it_is_a_percent_not_the_fraction_the_grid_stores(store):
    """BARRIERS holds .005; the rows and these boxes hold 0.5."""
    assert ri.query(min_tp=0.005, max_tp=0.025)["total"] == 0


# --------------------------------------------- the download carries the range

def test_the_csv_walks_the_same_range(store):
    rows = list(ri.iter_rows(min_tp=0.5, max_tp=2.5, min_sl=0.5, max_sl=1.5))
    assert sorted(r["signal"] for r in rows) == [
        "high_edge", "low_edge", "middle"]


def test_the_file_name_says_both_ends():
    """`tp2.5` for "between 0.5 and 2.5" would name a different slice than the
    file holds."""
    name = api.strategies_csv_name(min_tp=0.5, max_tp=2.5,
                                   min_sl=0.5, max_sl=1.5)
    assert "tp0.5-2.5" in name and "sl0.5-1.5" in name, name
    assert "tp2.5max" in api.strategies_csv_name(max_tp=2.5)
    assert "tp0.5min" in api.strategies_csv_name(min_tp=0.5)


# ------------------------------------------------------------- the browser

def test_the_modal_has_a_low_and_a_high_box_for_each():
    p = io.open(PANEL, encoding="utf-8").read()
    assert '<Field label="TP % between"' in p
    assert '<Field label="SL % between"' in p
    for name in ("Minimum take profit percent", "Maximum take profit percent",
                 "Minimum stop loss percent", "Maximum stop loss percent"):
        assert f'aria-label="{name}"' in p, name
    # and the request carries both ends
    assert "minTp: applied.minTp, minSl: applied.minSl," in p
    assert "min_tp?: number; min_sl?: number;" in io.open(
        "webapp/src/lib/api.ts", encoding="utf-8").read()


def test_a_range_is_ONE_chip_and_says_which_end_when_only_one_is_set():
    p = io.open(PANEL, encoding="utf-8").read()
    body = p[p.index("const chipsOf ="):]
    body = body[:body.index("\n  };")]
    assert "TP ${f.minTp}-${f.maxTp}%" in body
    assert "SL ${f.minSl}-${f.maxSl}%" in body
    assert "TP ${f.maxTp}% or tighter" in body
    assert "TP ${f.minTp}% or wider" in body
    assert "SL ${f.maxSl}% or tighter" in body
    assert "SL ${f.minSl}% or wider" in body


def test_removing_a_range_chip_clears_BOTH_ends():
    """One chip, one ×: leaving the floor behind would keep filtering under a
    line that no longer says so."""
    p = io.open(PANEL, encoding="utf-8").read()
    assert "const PAIRED" in p
    pair = p[p.index("const PAIRED"):]
    pair = pair[:pair.index("};")]
    for a, b in (("maxTp", "minTp"), ("minTp", "maxTp"),
                 ("maxSl", "minSl"), ("minSl", "maxSl")):
        assert f'{a}: "{b}"' in pair, (a, b)
    one = p[p.index("const clearOne ="):]
    one = one[:one.index("\n  };")]
    assert "const other = PAIRED[k];" in one
    assert "setBox[other](NO_FILTERS[other] as never);" in one
    assert "setApplied((a) => ({ ...a, [other]: NO_FILTERS[other] }));" in one


def test_clear_all_and_the_served_set_know_about_the_new_ends():
    p = io.open(PANEL, encoding="utf-8").read()
    no = p[p.index("const NO_FILTERS = {"):]
    no = no[:no.index("\n  };")]
    assert "minTp: 0" in no and "minSl: 0" in no
    # the chips read the API's OWN echo for these, like every other floor
    call = p[p.index("const chips = chipsOf({"):][:900]
    assert "servedMinTp > 0" in call and "servedMinSl > 0" in call
    assert "setServedMinTp(d.min_tp ?? applied.minTp);" in p
    assert "setServedMinSl(d.min_sl ?? applied.minSl);" in p
