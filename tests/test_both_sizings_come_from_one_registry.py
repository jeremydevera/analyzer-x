"""BOTH sizings are measured, and ONE registry decides which.

A round trip on Sep 11, 2026. The operator cut the ladder from the grid — *"can
you delete the maritingale strategy moving forward i waill not use it any more
i only want flat so you will need to delete marigingalte for my backtest as
well"* — and changed their mind hours later, before the purge of the existing
rows had finished: *"dont delete the maritinagale cancel it"*, then *"i want the
martingale back to backtest results and include the filter martingale again in
filter"*. By then 712 pair files had lost their martingale rows; they were
restored from `rows.db`, which still held them.

What is worth keeping from that round trip is what this file now pins:

* `SIZINGS` is ONE definition. It had been declared TWICE in
  `backtest_report.py`, eight lines apart, the second shadowing the first —
  two copies of one rule, the shape this repo has paid for over and over.
* every measuring path READS it: `market_sweep.run_pair`,
  `fast_grid.combo_six` and `.github/scripts/sweep_shard.py`. Two of those
  carried `("flat", "martingale")` inline, so the fleet could have gone on
  measuring a sizing this PC had stopped asking for — and did, for the run
  dispatched at 12:53am.

Because of that, changing this dimension is one line in one place, which is
why putting the ladder back took a single edit instead of four.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from tradingagents import backtest_report as br, market_sweep as msw


@pytest.fixture()
def store_rows(tmp_path, monkeypatch):
    """One pair holding both sizings."""
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


def test_both_sizings_are_measured():
    assert br.SIZINGS == ("flat", "martingale"), br.SIZINGS


def test_it_is_defined_exactly_ONCE():
    """It was declared twice in `backtest_report`, eight lines apart, the
    second shadowing the first."""
    src = Path("tradingagents/backtest_report.py").read_text(encoding="utf-8")
    assert src.count(chr(10) + "SIZINGS: tuple[str, ...] =") == 1,         f"{src.count(chr(10) + 'SIZINGS: tuple[str, ...] =')} definitions"


def test_no_measuring_path_carries_its_own_copy():
    """A literal pair anywhere OTHER than the registry is how this dimension
    stops obeying it — which is exactly what happened to the fleet for one run:
    `sweep_shard.py` and `fast_grid.py` each had `for sz in ("flat",
    "martingale")`, so GitHub's machines kept measuring the ladder after this
    PC stopped asking for it.

    `backtest_report` is allowed exactly ONE occurrence: the definition.
    """
    from tradingagents import fast_grid as fg
    both = '"flat", "martingale"'
    # the registry itself — one, and only in the assignment
    # the ASSIGNMENT, not the prose: the comment above it quotes the literal
    # while explaining the round trip, and counting text hit that too — the
    # fourth time this session (RCA-2026-09-10-M, -L, -B and here).
    br_src = inspect.getsource(br)
    decl = f'SIZINGS: tuple[str, ...] = ({both})'
    assert br_src.count(decl) == 1, f"{br_src.count(decl)} declarations"

    for mod in (msw, fg):
        src = inspect.getsource(mod)
        assert both not in src,             f"{mod.__name__} names both sizings inline instead of reading SIZINGS"
    shard = Path(".github/scripts/sweep_shard.py").read_text(encoding="utf-8")
    assert f'for sz in ({both})' not in shard,         "what GitHub's machines run must read the registry too"
    assert "for sz in br.SIZINGS" in shard


def test_the_pair_loop_and_the_cloud_measurer_read_the_registry():
    assert "br.SIZINGS" in inspect.getsource(msw.run_pair)
    from tradingagents import fast_grid as fg
    assert "sizings or br.SIZINGS" in inspect.getsource(fg.combo_six),         "combo_six takes an explicit list for the parity tests, else the grid's"


def test_the_filter_offers_both_again(store_rows):
    """*"include the filter martingale again in filter"*. The dropdown is built
    from the grid, so this follows the registry."""
    from tradingagents import rows_index as ri
    assert ri.facets()["sizings"] == ["flat", "martingale"]
    got = ri.query(limit=50)
    assert {r["sizing"] for r in got["rows"]} == {"flat", "martingale"}
    assert got["total"] == 2, "and the count stays exact"


def test_asking_for_one_sizing_still_narrows(store_rows):
    from tradingagents import rows_index as ri
    for sz in ("flat", "martingale"):
        got = ri.query(sizing=sz, limit=50)
        assert {r["sizing"] for r in got["rows"]} == {sz}


def test_the_collect_does_not_filter_by_sizing():
    """The landing door dropped rows at sizings the grid was not asking for,
    which was right while the grid was flat-only and wrong the moment the
    ladder came back. Removed rather than left switched off."""
    from tradingagents import cloud_sweep as cs
    src = inspect.getsource(cs.land_rows)
    assert "keep = set(br.SIZINGS)" not in src
    assert "dropped" not in src.split('"""')[2]


def test_the_dropdown_offers_both():
    panel = Path("webapp/src/components/backtest/StrategiesPanel.tsx")         .read_text(encoding="utf-8")
    opts = [ln for ln in panel.splitlines() if "<option" in ln]
    assert any("flat and martingale" in o for o in opts),         "the any-value option must name what the grid measures"
    assert "facets.sizings" in panel


def test_the_rule_file_records_both_and_the_round_trip():
    rules = Path("CLAUDE.md").read_text(encoding="utf-8")
    assert "both sizings (flat AND martingale)" in rules
    assert "BOTH ARE MEASURED (restored 2026-09-11)" in rules
    assert "FLAT SIZING ONLY" not in rules,         "the superseded directive must not still read as current"


def test_the_runners_ladder_is_untouched():
    """It never was — the grid change deliberately left the live execution path
    alone, which is why putting the ladder back needed no runner change."""
    from tradingagents import auto_trader as at
    assert hasattr(at, "LADDER")
