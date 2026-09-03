"""Stored strategies filters by MAX SL % — a ceiling, not a floor.

Operator, Sep 02, 2026: *"can you add the sl filter in the Stored strategies as
well"*, having just settled its direction on the artifact: *"for sl if i input 1
then show below 1 or equal 1"*.

Both barrier boxes are CEILINGS as of Sep 03, 2026, when the operator turned the
TP box around too: *"when i input tp 3% it should show tp below 3%"*. What they
are hunting is a target the market actually reaches with a stop that risks
little — max TP % and max SL % — so a box that read "min SL" would hand back
exactly the rows they are trying to get rid of.

Why they wanted it: a win-rate ranking floats the lopsided rows to the top. The
best win rate in the 30-day list was JPY 30m fade15 at TP 0.3% against SL 2% —
96 wins out of 96 trades, and one loss hands all of it back. `max SL %` is how
that row leaves the screen without reading every row.
"""
from __future__ import annotations

import inspect

from tradingagents import rows_index as ri


def test_the_clause_is_a_ceiling():
    sql, args = ri._where(max_sl=1.0)
    assert "sl <= ?" in sql, sql
    assert "sl >= ?" not in sql, "a MIN SL box would keep the wide stops"
    assert args == [1.0]


def test_it_steps_aside_for_the_order_by_like_tp_does():
    """`sl` has no index, so the term cannot drive a plan; the `+` is what keeps
    a future sl index from stealing the ORDER BY and sorting in a temp b-tree.
    (The TP box works the same way, and now in the same direction.)"""
    plain, _ = ri._where(max_sl=1.0)
    ordered, _ = ri._where(max_sl=1.0, order_owns_index=True)
    assert "+sl <= ?" in ordered
    assert "+sl" not in plain
    # with a coin named, the coin index drives and nothing steps aside
    with_coin, _ = ri._where(coin="KAVA", max_sl=1.0, order_owns_index=True)
    assert "sl <= ?" in with_coin and "+sl" not in with_coin


def test_tp_and_sl_are_both_ceilings_together():
    """One AND the other, both downwards: "TP 3% or smaller AND SL 1% or
    tighter" is the question the operator actually asks of this store."""
    sql, args = ri._where(max_tp=3.0, max_sl=1.0, order_owns_index=True)
    assert "+tp <= ?" in sql and "+sl <= ?" in sql, sql
    assert "tp >= ?" not in sql, "the TP box stopped being a floor on 2026-09-03"
    assert args == [3.0, 1.0]


def test_every_layer_takes_it():
    from tradingagents import api

    assert "max_sl" in inspect.signature(ri.query).parameters
    assert "max_sl" in inspect.signature(ri.iter_rows).parameters
    assert "max_sl" in inspect.signature(api.strategies).parameters
    assert "max_sl" in inspect.signature(api.strategies_csv).parameters
    assert "max_sl" in inspect.signature(api.strategies_csv_lines).parameters
    for fn in (api.strategies, api.strategies_csv, api.strategies_csv_lines):
        assert "max_sl=max_sl" in inspect.getsource(fn), fn.__name__


def test_the_download_says_which_slice_it_is():
    """Two downloads of the same coin and order differ only by the filters, so
    the filename has to carry them (it already carried the TP box)."""
    from tradingagents import api

    name = api.strategies_csv_name(coin="KAVA", max_tp=2, max_sl=1)
    assert "tp2" in name and "sl1" in name, name


def test_it_disqualifies_the_free_counts():
    """coin/timeframe alone are answered exactly by the pair summaries. An SL
    ceiling cuts INSIDE a pair, so it cannot use that shortcut — the same trap
    the group filter fell into (both groups reported the whole store)."""
    src = inspect.getsource(ri.query)
    i = src.index("from_pairs = not (")
    assert "or max_sl" in src[i:i + 300], \
        "an SL ceiling must not take the pair-summary count"
    j = src.index("from_winrate = bool(")
    assert "not max_sl" in src[j:j + 420], "nor the win-rate shortcut"


def test_the_answer_reports_what_it_applied():
    """The caption prints the floors the SERVER used, never the boxes' values —
    on a 503 the request moves and the rows do not (label-must-match-data)."""
    src = inspect.getsource(ri.query)
    assert '"max_sl": float(max_sl or 0),' in src


def test_the_sl_list_comes_from_the_grid_that_measured_the_rows():
    """Offering a value the grid never measured costs a full scan to answer
    "nothing" — `sl` has no index either."""
    from tradingagents import backtest_report as br

    got = ri.stop_losses(["1h", "4h"])
    assert got, "the SL list must not be empty for measured timeframes"
    real = {round(sl * 100, 3) for tf in ("1h", "4h")
            for sl, _tp in br.BARRIERS.get(tf, ())}
    assert set(got) == real, (got, sorted(real))
    assert ri.facets()["sls"] is not None
    assert ri.stop_losses([]) == []


def test_the_panel_has_the_box_and_says_so():
    panel = open("webapp/src/components/backtest/StrategiesPanel.tsx",
                 encoding="utf-8").read()
    assert 'aria-label="Maximum stop loss percent"' in panel
    assert "max SL %" in panel
    assert "setMaxSl" in panel
    # the caption's sentence, built where every other term is built
    i = panel.index("const andLine")
    j = panel.index('].join(" AND ")', i)
    builder = panel[i:j]
    assert "max SL % = ${f.maxSl}" in builder, \
        "a filtered table under a caption that does not name it is the 2026-08-14 failure"
    assert '"any SL"' in builder, "and the neutral case needs a name too"
    # and it reaches the API
    assert "maxSl: applied.maxSl" in panel
    api_ts = open("webapp/src/lib/api.ts", encoding="utf-8").read()
    assert api_ts.count('p.set("max_sl"') == 2, \
        "the table AND the CSV download must both carry it"
    assert "maxSl?: number" in api_ts
    assert "sls?: number[]" in api_ts, "the box offers the measured values"
