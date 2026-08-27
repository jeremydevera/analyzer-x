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
    assert len(preset) == 30 == len(CONF_SIGNALS)
    assert len(classic) == 75
    assert len(preset) + len(classic) == len(br.SIGNALS)
    assert set(preset) == set(CONF_SIGNALS)


def test_the_group_names_are_the_operators_words():
    assert ri.GROUPS["preset"]["label"] == "Preset Confluence"
    assert ri.GROUPS["classic"]["label"] == "Classic"
    assert set(ri.GROUPS) == {"preset", "classic"}


@pytest.mark.parametrize("group,sql_has,sample_in,sample_out", [
    ("preset", "LIKE", "cf_ttm_l2", "trend50"),
    ("classic", "NOT LIKE", "trend50", "cf_ttm_l2"),
])
def test_the_where_clause_selects_the_group(group, sql_has, sample_in, sample_out):
    sql, args = ri._where(group=group)
    assert "signal" in sql and sql_has in sql, sql
    assert ri.in_group(sample_in, group) is True
    assert ri.in_group(sample_out, group) is False


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
    assert "showing rows where" in src


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


def test_a_group_count_is_bounded_rather_than_scanned():
    """`signal` has no index, so counting a group is a table scan: measured
    26.2 s for the first 5,001 preset rows on the 35.9M-row store, which the
    20 s query budget kills -- the filter then failed outright instead of
    answering. -1 is this module's existing "bounded, over the cap" answer and
    prints with the "+", so the caption reads "5,000+ match".
    """
    import inspect

    src = inspect.getsource(ri.query)
    i = src.index("elif where and group and not coin:")
    branch = src[i:i + 700]
    assert "total = -1" in branch
    assert "rows_coin" in branch, "with a coin the count is cheap and still exact"
    # and -1 must still be turned into a capped count for the caption
    j = src.index("if total < 0:")
    assert "total, capped_count = COUNT_CAP, True" in src[j:j + 700],         "an unknown total must print as a bound, with the +"
