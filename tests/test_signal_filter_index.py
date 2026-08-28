"""One signal, ranked by profit, must be a SEEK — not a walk of the store.

Aug 28, 2026. The five 4-hour confluence setups landed in the store (49,043,628
rows) and the operator's own Signal filter stopped answering:

    /api/strategies?signal=cf_bosfvg   -> HTTP 500 after 30.1 s (the proxy gave
                                          up before the query budget did)
    /api/strategies?signal=cf_fundfade -> HTTP 503 at the 20 s budget
    /api/strategies?signal=cf_diadx    -> HTTP 503 at the 20 s budget

`signal` had no index and deliberately stepped aside for the ORDER BY, on the
reasoning that one rule of 105 cannot be selective enough to drive a plan. That
was true while every rule was measured on every pair; it is not true of a
low-frequency rule. cf_bosfvg is 161,828 rows of 49 million — 0.3% — and the
walk down rows_profit read a candidate ROW off the disk for every test.

`rows_signal` is (signal, profit DESC, id): a seek whose rows arrive already in
profit order, so there is no temp b-tree either.
"""
from __future__ import annotations

import inspect

from tradingagents import rows_index as ri


def test_the_index_is_declared_and_buildable_on_demand():
    ddl = ri.INDEX_DDL["rows_signal"]
    assert "ON rows (signal, profit DESC, id)" in ddl
    assert ri.FILTER_INDEX_FOR["signal"] == "rows_signal", \
        "build_filter_index('signal') has to know what to build"


def test_a_named_signal_keeps_its_index_only_when_it_has_one():
    """The `+` is what tells SQLite not to use an index for a term. It must be
    there when there is no index to use, and gone when there is."""
    seek, _ = ri._where(signal="cf_bosfvg", order_owns_index=True,
                        signal_seeks=True)
    walk, _ = ri._where(signal="cf_bosfvg", order_owns_index=True)
    assert "WHERE signal = ?" in seek and "+signal" not in seek
    assert "+signal = ?" in walk


def test_the_statement_names_the_index(monkeypatch):
    assert ri._indexed_by(None, signal_seeks=True) == " INDEXED BY rows_signal"
    # a named coin is still the better driver (~10k rows for a pair), so it
    # outranks the signal seek WHEN ITS OWN INDEX IS THERE
    monkeypatch.setattr(ri, "has_index", lambda name: name == "rows_coin")
    assert ri._indexed_by("KAVA", signal_seeks=True) == " INDEXED BY rows_coin"


def test_a_missing_index_is_refused_with_the_reason_not_a_thirty_second_500(
        monkeypatch):
    built = []
    monkeypatch.setattr(ri, "_rows_estimate", lambda: 49_043_628)
    monkeypatch.setattr(ri, "has_index", lambda name: False)
    monkeypatch.setattr(ri, "build_filter_index", lambda col: built.append(col))
    try:
        ri.query(signal="cf_bosfvg")
    except ri.SortNotReady as exc:
        said = str(exc)
        assert "cf_bosfvg" in said and "rows_signal" in said
        assert "coin" in said, "and it must say what IS answerable now"
    else:
        raise AssertionError("a store this size must refuse, not walk")
    assert built == ["signal"]


def test_the_csv_export_seeks_the_same_way():
    """The download button carries the Signal filter; an export that scans 49
    million rows to write its first line is a download that never starts."""
    src = inspect.getsource(ri.iter_rows)
    assert "signal_seeks" in src
    assert "rows_signal" in inspect.getsource(ri.query)


def test_a_small_store_still_answers_without_the_index(monkeypatch):
    """The refusal is about SIZE. A few thousand rows sort instantly, and
    refusing there would be a feature removed to protect a plan."""
    monkeypatch.setattr(ri, "_rows_estimate", lambda: 1_000)
    monkeypatch.setattr(ri, "has_index", lambda name: False)
    monkeypatch.setattr(ri, "_missing_ok", lambda fn, default: default)
    got = ri.query(signal="cf_bosfvg")
    assert got["rows"] == []          # empty store, but it ANSWERED
