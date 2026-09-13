"""An id the store does not hold gets an ANSWER, not a guess.

Operator, Sep 10, 2026: *"why is #PNK3G9KZ not searchable it says no row
#PNK3G9KZ in the store. The id is hashed from the combination, so it changes if
the row was re-measured with different barriers — check it against the first
column of the table or the artifact you copied it from. / im getting tired of
these errors"*.

They quoted the message back, and the message was the problem. It asserted a
CAUSE nobody had checked — "it changes if the row was re-measured" — and the
advice that followed ("check it against the table") could not possibly work.
Measured for that id: **zero** of the **148,773,240** combinations the current
grid can mint produce it, on any of the 5,367 pairs in the store, all 120
signals, every barrier pair, both sizings and the threshold grid. So the row
was not "re-measured with different barriers" in this store at all; the id came
from outside the current grid, and no amount of looking at the table would
have found it.

The id is not opaque, which is the whole point: `row_code` is
blake2s(coin|tf|signal|th|sl|tp|sizing) rendered as 8 base32 characters, so the
characters ARE that 40-bit number and the question "which combination is this?"
is answerable by enumeration in ~144 s.
"""
from __future__ import annotations

import json
import time

import pytest

from tradingagents import backtest_report as br, market_sweep as msw, rows_index as ri


@pytest.fixture()
def store(tmp_path, monkeypatch):
    rows_dir, states = tmp_path / "rows", tmp_path / "states"
    rows_dir.mkdir()
    states.mkdir()
    monkeypatch.setattr(msw, "ROWDIR", rows_dir)
    monkeypatch.setattr(msw, "STATES", states)
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    ri._ready.discard(str(tmp_path / "rows.db"))
    # ONE real combination, with the id the real minter gives it
    sl, tp = br.BARRIERS["1h"][0]
    signal = br.SIGNALS[0]
    rid = br.row_code("AAA", "1h", signal, 0.0, sl, tp, "flat")
    (rows_dir / "AAA-1h.json").write_text(json.dumps([
        {"id": rid, "coin": "AAA", "tf": "1h", "signal": signal,
         "th": 0.0, "sl": sl, "tp": tp, "sizing": "flat",
         "trades": 40, "wins": 30, "losses": 10, "winrate": 75.0,
         "profit": 12.0, "monthly": {}}]), encoding="utf-8")
    (states / "AAA-1h.json").write_text(
        json.dumps({"__last_ms__": int(time.time() * 1000)}), encoding="utf-8")
    ri.ensure()
    ri.sync()
    return {"id": rid, "signal": signal, "sl": sl, "tp": tp}


def test_a_row_that_IS_there_is_reported_as_there(store):
    got = ri.resolve_row_code(store["id"], pairs=[("AAA", "1h")])
    assert got["well_formed"] is True
    assert got["in_store"] is True, "it is indexed; the id is simply findable"


def test_a_combination_whose_row_is_GONE_is_still_named(store):
    """The useful case: the id is real, the row is not. Naming the coin is
    what lets the operator re-measure that pair instead of guessing."""
    sl, tp = br.BARRIERS["1h"][1]           # a barrier pair with no row
    rid = br.row_code("AAA", "1h", store["signal"], 0.0, sl, tp, "flat")
    got = ri.resolve_row_code(rid, pairs=[("AAA", "1h")])
    assert got["in_store"] is False
    assert got["combination"], "the grid CAN mint it, so it must be named"
    assert got["combination"]["coin"] == "AAA"
    assert got["combination"]["tf"] == "1h"
    assert got["combination"]["sizing"] == "flat"
    assert abs(got["combination"]["tp"] - tp) < 1e-9


def test_an_id_no_grid_can_mint_says_exactly_that(store):
    """#PNK3G9KZ's real answer. `combination` stays None and `searched` carries
    the number, so the message can say "148,773,240 and none of them" instead
    of a shrug."""
    got = ri.resolve_row_code("PNK3G9KZ", pairs=[("AAA", "1h")])
    assert got["well_formed"] is True
    assert got["in_store"] is False
    assert got["combination"] is None
    assert got["searched"] > 0, "it must report how hard it looked"


def test_a_typo_is_told_apart_from_a_miss(store):
    """The one case the reader can actually fix, so it must not be lumped in
    with "not in the store"."""
    for bad in ("PNK3G9K", "PNK3G9KZZ", "PNK3G9KI", "", "  "):
        got = ri.resolve_row_code(bad)
        assert got["well_formed"] is False, bad
        assert got["searched"] == 0, "and it must not burn 144s on a typo"


def test_a_pasted_id_resolves_like_a_typed_one(store):
    """`" #6yaczsxx "` is what a paste from chat looks like."""
    got = ri.resolve_row_code(f"  #{store['id'].lower()} ",
                              pairs=[("AAA", "1h")])
    assert got["well_formed"] and got["in_store"]


def test_it_is_never_called_from_a_request(store):
    """144 s of CPU on a polled route is pattern 4 in docs/RCA.md, paid for
    three times in one day."""
    import ast
    import inspect
    import textwrap

    from tradingagents import api

    tree = ast.parse(textwrap.dedent(inspect.getsource(api)))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = getattr(f, "attr", None) or getattr(f, "id", None)
            assert name != "resolve_row_code", \
                "the API must never call the enumerator"


def test_the_cli_answers_all_three_cases(store, capsys):
    """The command the message tells the operator to run."""
    assert ri.main(["resolve", store["id"]]) == 0
    assert "IN the store" in capsys.readouterr().out

    assert ri.main(["resolve", "PNK3G9K"]) == 1
    assert "NOT a row code" in capsys.readouterr().out

    assert ri.main(["resolve"]) == 2
    assert "usage:" in capsys.readouterr().out


# ------------------------------------------------------------------ the screen
def test_the_message_no_longer_asserts_a_cause_it_did_not_check():
    src = (open("webapp/src/components/backtest/StrategiesPanel.tsx",
                encoding="utf-8").read())
    i = src.index("no row <b>#{servedFilters.rowId}</b> in the store")
    said = src[i:i + 1200]
    assert "so it changes if the row was re-measured" not in said, \
        "that was a guess presented as a fact"
    assert "rows_index resolve" in said, "it must name the command that knows"
    assert "exists only while that row does" in said, \
        "and state the one thing that IS true about an id"
