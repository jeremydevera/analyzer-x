"""The grid measures FLAT only. The ladder is out.

Operator, Sep 11, 2026: *"can you delete the maritingale strategy moving
forward i waill not use it any more i only want flat so you will need to delete
marigingalte for my backtest as well"*.

This REPLACES the Aug 19, 2026 directive that every strategy request tests both
sizings (CLAUDE.md rules 18-19). The reason the ladder was ever in the grid is
the reason it is now out: rule 19's own audit showed the "13/13 green months"
behind six live strategies was produced by the LADDER, not the signal (flat:
7/12-11/12). A sizing choice that flatters every signal it touches is not a
measurement.

Two things follow, and both are asserted here rather than assumed:

* every sweep measures HALF the combinations it used to, because `fast_grid`
  computed six numbers per (signal, threshold, SL, TP) — flat and martingale,
  each over the full history and both halves;
* the `sizing` filter can only offer what the grid produces.

The RUNNER's ladder is deliberately untouched: all 35 of the operator's
deployed strategies read `flat`, and removing a live execution path is a
different change from removing a measurement dimension.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from tradingagents import backtest_report as br, market_sweep as msw


@pytest.fixture()
def store_rows(tmp_path, monkeypatch):
    """One pair holding BOTH sizings, as the operator's store does until the
    purge finishes."""
    import json
    import time

    from tradingagents import rows_index as ri
    rows_dir = tmp_path / "rows"
    rows_dir.mkdir()
    monkeypatch.setattr(msw, "ROWDIR", rows_dir)
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    ri._ready.discard(str(tmp_path / "rows.db"))
    (rows_dir / "AAA-1h.json").write_text(json.dumps([
        {"id": f"A{i}", "coin": "AAA", "tf": "1h", "signal": "willr14",
         "th": 0.0, "sl": 4.0, "tp": 0.6, "sizing": sz, "trades": 12,
         "wins": 12, "losses": 0, "winrate": 100.0, "profit": 4.56,
         "monthly": {}}
        for i, sz in enumerate(("flat", "martingale"))]), encoding="utf-8")
    ri.ensure()
    ri.sync(now=time.time() + ri.SETTLE_S + 1)
    return tmp_path

def test_the_grid_offers_flat_and_nothing_else():
    assert br.SIZINGS == ("flat",), br.SIZINGS


def test_it_is_defined_exactly_ONCE():
    """It was declared twice in `backtest_report`, eight lines apart, the
    second shadowing the first — two copies of one rule, which is the shape
    this repo has paid for over and over (the date format, the store rule,
    `land_rows` versus `run_pair`)."""
    src = Path("tradingagents/backtest_report.py").read_text(encoding="utf-8")
    assert src.count("\nSIZINGS: tuple[str, ...] =") == 1, \
        f"{src.count(chr(10) + 'SIZINGS: tuple[str, ...] =')} definitions"


def test_the_sweep_reads_the_registry_instead_of_a_literal():
    """A literal `("flat", "martingale")` anywhere in the measuring path is how
    the ladder comes back without anyone deciding to bring it back."""
    for mod in (msw, br):
        src = inspect.getsource(mod)
        assert '"flat", "martingale"' not in src, \
            f"{mod.__name__} still names both sizings inline"
        assert "'flat', 'martingale'" not in src, mod.__name__


def test_the_pair_loop_takes_its_sizings_from_the_registry():
    src = inspect.getsource(msw.run_pair)
    assert "br.SIZINGS" in src, \
        "the barrier loop must read the registry, so flat-only takes effect"


def test_the_cloud_measurer_follows_the_same_registry():
    """`fast_grid` is what GitHub's twenty machines run. If it kept its own
    list, the fleet would measure the ladder for weeks while this PC did not —
    and a store rule with two implementations is RCA-2026-09-09-P."""
    from tradingagents import fast_grid as fg
    src = inspect.getsource(fg)
    assert '"flat", "martingale"' not in src and "'flat', 'martingale'" not in src


def test_the_browsers_dropdown_is_built_from_the_registry_too():
    """The comment on SIZINGS says why: "a dropdown built from a literal in the
    browser is a label that can drift from the data"."""
    panel = Path("webapp/src/components/backtest/StrategiesPanel.tsx") \
        .read_text(encoding="utf-8")
    # the OPTIONS, not the prose. The file explains this change in comments and
    # quotes the operator's older "flat / martingale" ask, so a plain search
    # for the word hits the explanation — the trap this session fell into three
    # times today (RCA-2026-09-10-M, -L, -B).
    opts = [ln for ln in panel.splitlines() if "<option" in ln]
    assert opts, "the sizing dropdown is gone"
    named = [o.strip() for o in opts if "martingale" in o]
    assert not named, "an <option> still names martingale: " + "; ".join(named)
    assert "facets.sizings" in panel, \
        "the options must come from the store, never a literal"


def test_the_runners_ladder_is_untouched():
    """Not an oversight — a decision. The operator's ask was about the
    BACKTEST; none of their deployed rows uses the ladder, and ripping a live
    execution path out on the same commit is how a trading bug ships."""
    from tradingagents import auto_trader as at
    assert hasattr(at, "LADDER"), \
        "the runner's ladder was removed as a side effect of a grid change"


def test_the_rule_file_records_the_new_directive():
    """A rule that lives only in code gets 'restored' by the next session
    reading CLAUDE.md."""
    rules = Path("CLAUDE.md").read_text(encoding="utf-8")
    assert "FLAT SIZING ONLY" in rules
    assert "FLAT ONLY — the martingale ladder is out of the grid" in rules
    assert "both sizings (flat AND martingale)" not in rules, \
        "the superseded directive must not still read as current"


def test_the_QUERY_does_not_silently_filter_the_leftovers(store_rows):
    """Operator, Sep 11, 2026, on a "Past 30 days AND Winrate 95% or better"
    screen: *"why do i astill see martingale here"* — #C3JEKQ3S and #ZCB4Q7Z7
    (VSTOCK 1h, martingale) were on it, hours after the grid stopped measuring
    the ladder. The store still holds 48,157,842 martingale rows from before.

    The obvious fix — default every query to the grid's sizing — was BUILT,
    MEASURED AND REVERTED, and this test is the reason:

        no sizing (before)   0.58 s   total 27,720 EXACT
        implicit flat        2.34 s   total  5,000 CAPPED

    A sizing filter cannot use the pair summaries for its count, so every
    screen would have lost its exact total and its real last page — which this
    repo has an explicit guard for
    (`test_exact_page_count.py::test_a_timeframe_filter_counts_exactly_and_says_so`)
    and which the operator has objected to before. Five guards went red on it.

    So the leftovers are removed at the SOURCE (the pair files, then the index)
    rather than hidden by every query. Until that finishes the rows are still
    visible, which is honest: they were really measured.
    """
    from tradingagents import rows_index as ri
    got = ri.query(limit=50)
    assert got["total"] == 2, "the count must stay EXACT, from the summaries"
    assert {r["sizing"] for r in got["rows"]} == {"flat", "martingale"},         "a query that names no sizing answers what the store holds"


def test_nothing_MEASURES_the_ladder_any_more(store_rows):
    """Which is the actual fix: the grid asks for one sizing, so no new
    martingale row can appear."""
    assert br.SIZINGS == ("flat",)
    assert "martingale" not in str(br.SIZINGS)
