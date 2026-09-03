"""Stored strategies can be filtered by GROUP: Preset Confluence or Classic.

Operator, Aug 27, 2026, after the ten researched setups landed in the engine:
"i want to group this new backtests to 'Preset Confluence' / then the existing
backtests before this should be all grouped to 'Classic'".

Two groups, decided by the signal's own name, so no column has to be added and
35.8 million indexed rows do not need rewriting:

  Preset Confluence -- the 30 rules in tradingagents/signals_conf.py, every one
                       named `cf_...` (ten setups x three levels)
  Classic           -- the 75 that existed before them

The group is named in the caption too: a table filtered to one group while the
caption says "all signals" is the label-does-not-match-the-data failure this
project keeps paying for.
"""
from __future__ import annotations

import pytest

from tradingagents import backtest_report as br, rows_index as ri
from tradingagents.signals_conf import CONF_SIGNALS


def test_the_two_groups_partition_the_signal_library():
    """Every signal belongs to exactly one group -- no gaps, no overlap."""
    preset = [s for s in br.SIGNALS if s.startswith("cf_")]
    classic = [s for s in br.SIGNALS if not s.startswith("cf_")]
    # 15 setups x 3 levels: the 1-hour ten, plus the five that only the
    # 4-hour ranking had (built 2026-08-28)
    assert len(preset) == 45 == len(CONF_SIGNALS)
    assert len(classic) == 75
    assert len(preset) + len(classic) == len(br.SIGNALS)
    assert set(preset) == set(CONF_SIGNALS)


def test_the_group_names_are_the_operators_words():
    assert ri.GROUPS["preset"]["label"] == "Preset Confluence"
    assert ri.GROUPS["classic"]["label"] == "Classic"
    assert set(ri.GROUPS) == {"preset", "classic"}


@pytest.mark.parametrize("group,terms,sample_in,sample_out", [
    ("preset", "signal >= 'cf_' AND signal < 'cf`'", "cf_ttm_l2", "trend50"),
    ("classic", "(signal < 'cf_' OR signal >= 'cf`')", "trend50", "cf_ttm_l2"),
])
def test_the_where_clause_selects_the_group(group, terms, sample_in, sample_out):
    r"""A RANGE on the signal name, not a LIKE.

    `signal LIKE 'cf\_%' ESCAPE '\'` is correct and unusable: SQLite turns
    its LIKE optimisation off whenever ESCAPE is given, so no index can serve
    it and a partial index cannot be matched to it. The operator paid for that
    with `HTTP 500` on their own screen -- 78.7 s to rank 500 preset rows.
    """
    sql, args = ri._where(group=group)
    assert terms in sql, sql
    assert "LIKE" not in sql, "a LIKE cannot use an index; a range can"
    assert args == [], "the bounds are INLINE: a bound parameter cannot be "                        "matched against a partial index at prepare time"
    assert ri.in_group(sample_in, group) is True
    assert ri.in_group(sample_out, group) is False


def test_the_preset_group_has_a_partial_index_for_every_order():
    """Every order the screen offers, over just the cf_ slice of the store."""
    from tradingagents import rows_index as r
    for sort in r.SORTS:
        name = r.group_index("preset", sort)
        assert name == f"rows_cf_{sort}", sort
        ddl = r.INDEX_DDL[name]
        assert ddl.startswith(f"CREATE INDEX IF NOT EXISTS {name} ON rows (")
        assert f"WHERE {r.PRESET_TERMS}" in ddl,             "the index's WHERE must be the query's own terms, word for word, "             "or SQLite will not match them"
        assert sort in ddl.split("WHERE")[0], "and it must be IN that order"
    # classic is ~95% of the store: the plain profit walk finds 500 at once
    # (1.5 s measured), so an index there is a build that buys nothing
    for sort in r.SORTS:
        assert r.group_index("classic", sort) == ""
    assert r.group_index(None, "profit") == ""


def test_a_group_without_its_index_is_refused_with_the_reason(monkeypatch):
    """Not a 20 s hang and not a bare 500: the sentence, and a build behind it.

    What the operator saw before this:
        ApiError: /api/strategies?sort=profit&group=preset&desc=true&limit=500
        -> HTTP 500
    """
    from tradingagents import rows_index as r

    built = []
    monkeypatch.setattr(r, "_rows_estimate", lambda: 35_893_630)
    monkeypatch.setattr(r, "has_index", lambda name: False)
    monkeypatch.setattr(r, "_build_index", lambda name: built.append(name))
    with pytest.raises(r.SortNotReady) as exc:
        r.query(group="preset", sort="profit")
    said = str(exc.value)
    assert "Preset Confluence" in said and "rows_cf_profit" in said
    assert "coin" in said, "and it must say what IS answerable now"
    assert built == ["rows_cf_profit"], built


def test_the_csv_carries_the_group_too():
    """The panel's download button sits under a filtered table; a CSV that
    ignores the group is 35.9M rows under a name that says otherwise."""
    import inspect

    from tradingagents import api

    assert "group" in inspect.signature(ri.iter_rows).parameters
    for fn in (api.strategies_csv, api.strategies_csv_lines):
        assert "group" in inspect.signature(fn).parameters, fn.__name__
        assert "group=group" in inspect.getsource(fn), fn.__name__
    assert "preset" in api.strategies_csv_name(group="preset"),         "and the FILENAME has to say which slice is in the file"


def test_no_group_filters_nothing():
    sql, args = ri._where()
    assert "LIKE" not in sql
    for s in ("cf_mom", "trend50"):
        assert ri.in_group(s, None) is True
        assert ri.in_group(s, "") is True


def test_an_unknown_group_is_a_bad_request_not_a_silent_pass():
    """A typo must not quietly return the whole store as if it were the group."""
    with pytest.raises(ValueError) as exc:
        ri._where(group="level9")
    assert "preset" in str(exc.value) and "classic" in str(exc.value)


def test_a_row_id_still_overrides_the_group(monkeypatch):
    """Kit item H: the find-by-ID box overrides the other filters. A group left
    in the WHERE could only contradict the id and read as "not in the store"."""
    sql, args = ri._where(row_id="#AEA44946", group="preset")
    assert sql.strip().startswith("WHERE id = ?")
    assert len(args) == 1


def test_the_query_and_the_route_take_the_group():
    import inspect

    from tradingagents import api

    assert "group" in inspect.signature(ri.query).parameters
    src = inspect.getsource(api.strategies)
    assert "group" in inspect.signature(api.strategies).parameters
    assert "group=group" in src, "the route must pass it through"


def test_the_caption_names_the_active_group():
    """The panel prints "showing rows where: ..." and the group has to appear in
    it, or the caption describes a table it is not showing."""
    src = open("webapp/src/components/backtest/StrategiesPanel.tsx",
               encoding="utf-8").read()
    assert "Preset Confluence" in src and "Classic" in src
    assert "all groups" in src, "the neutral option needs a name too"
    # the caption is built by andLine(), the one place that turns the filter set
    # into a sentence -- a term added anywhere else would not reach the screen
    i = src.index("const andLine")
    j = src.index("].join(\" AND \")", i)
    builder = src[i:j]
    assert "group = Preset Confluence" in builder, \
        "the group must be a term in the caption's sentence"
    assert "group = Classic" in builder
    assert "all groups" in builder, "and the neutral case has to be named too"
    # the line is labelled "Filter:" since 2026-09-03 ("show the text
    # description on this part"), and the group is one of its chips
    assert "Filter:" in src
    assert "${GROUP_LABEL[f.group] ?? f.group} setups" in src


def test_the_panel_sends_it_to_the_api():
    src = open("webapp/src/lib/api.ts", encoding="utf-8").read()
    assert "group" in src
    panel = open("webapp/src/components/backtest/StrategiesPanel.tsx",
                 encoding="utf-8").read()
    assert "setGroup" in panel and "aria-label=\"Group\"" in panel


def test_a_group_is_counted_not_taken_from_the_pair_summaries():
    """The count for coin/timeframe alone comes from the pair summaries, which
    are exact and free. A GROUP cuts inside a pair -- half the signals in every
    pair file -- so it cannot use that shortcut.

    Measured before this: `group=preset` and `group=classic` both reported
    total 35,893,630, the whole store, beside a table showing one group.
    """
    import inspect

    src = inspect.getsource(ri.query)
    i = src.index("from_pairs = not (")
    clause = src[i:i + 260]
    assert "or group" in clause, \
        "a group filter must disqualify the pair-summary count"
    j = src.index("from_winrate = bool(")
    assert "not group" in src[j:j + 320], \
        "and the win-rate shortcut too"


def test_a_group_count_is_bounded_until_its_index_exists():
    """Counting a group is a table scan while `signal` has no index: measured
    26.2 s for the first 5,001 preset rows on the 35.9M-row store, which the
    20 s budget kills, so the filter failed outright instead of answering. -1
    is this module's existing "bounded, over the cap" answer and prints with
    the "+", so the caption reads "5,000+ match". Once the partial index is
    built the bounded count rides it instead and stays exact under the cap.
    """
    import inspect

    src = inspect.getsource(ri.query)
    i = src.index("elif where and group and not coin and not group_idx:")
    branch = src[i:i + 900]
    assert "total = -1" in branch
    # and with the index there, the generic bounded count must NAME it
    assert "_indexed_by(coin, group_idx=group_idx" in src,         "the count has to ride the partial index once it exists"
    # -1 must still be turned into a capped count for the caption
    j = src.index("if total < 0:")
    assert "total, capped_count = COUNT_CAP, True" in src[j:j + 700],         "an unknown total must print as a bound, with the +"
