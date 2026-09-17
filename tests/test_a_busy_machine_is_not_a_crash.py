"""Pressing a button while another job holds the disk is a 409, never a 500.

Operator, `Sep 17, 2026`, on row #LG9NSU4B (XPIN 1h, `ote`, TP 1.0 / SL 3.0):

    "when i click update this backtest for #LG9NSU4B im getting
     process died before finishing"

then, when it was pressed for real: **HTTP 500, "Internal Server Error"**, with
no traceback in `api.log` at all — the POST never even reached the access log.

What was actually wrong: `db_jobs.start` refuses to launch while ANY other job
holds the store — one job at a time, across both versions — by raising
`JobBusy`. A `download_v2` job was running (CATI_USDT 1m). `strategy_row_update`
did not catch it, so the one sentence the operator needed to read —
*"download_v2 is running ... wait for it to finish"* — was thrown away and
replaced with a blank crash.

`POST /api/jobs/{kind}` has answered 409 for exactly this since it was written.
The row UPDATE button and the per-strategy backtest never learned.
"""
import inspect

import pytest
from fastapi import HTTPException

from tradingagents import api, db_jobs as dj, rows_index as ri


@pytest.fixture
def busy(monkeypatch):
    """Every start refused, the way a running download refuses one."""
    def refuse(kind, spec=None):
        raise dj.JobBusy("download_v2 is running — one job at a time, across "
                         "both versions; stop it or wait for it to finish")
    monkeypatch.setattr(dj, "start", refuse)
    return refuse


@pytest.fixture
def one_row(monkeypatch):
    """#LG9NSU4B as the store really holds it: XPIN 1h, ote, 1.0/3.0 flat."""
    monkeypatch.setattr(ri, "clean_row_id", lambda r: "LG9NSU4B")
    monkeypatch.setattr(ri, "query", lambda **k: {"rows": [
        {"coin": "XPIN", "tf": "1h", "signal": "ote", "tp": 1.0, "sl": 3.0,
         "sizing": "flat", "base": 5.0}]})


def test_the_row_update_button_says_what_is_busy(busy, one_row):
    """THE BUG. It answered 500 with nothing in the log."""
    with pytest.raises(HTTPException) as e:
        api.strategy_row_update("LG9NSU4B")
    assert e.value.status_code == 409, "a busy machine is not a crash"
    assert "download_v2" in str(e.value.detail), \
        "and the message must NAME what is holding the disk"


@pytest.mark.parametrize("fn", ["strategy_row_update", "strategy_backtest"])
def test_every_button_that_starts_a_job_catches_the_refusal(fn):
    """Grep for the CONCEPT, not the one that was reported (CLAUDE.md): there
    were THREE `start` call sites and only the generic one handled this."""
    # READ THE CALLS, NOT THE PROSE. The first draft of this test grepped for
    # the word "JobBusy" and PASSED on the broken file, because the comment
    # explaining the fix contains that word. A guard is only as wide as its
    # pattern (CLAUDE.md) — so walk the AST and demand a real handler.
    import ast

    tree = ast.parse(inspect.getsource(getattr(api, fn)).lstrip())
    handlers = [h for node in ast.walk(tree) if isinstance(node, ast.Try)
                for h in node.handlers]
    named = {ast.unparse(n).split(".")[-1]
             for h in handlers
             for n in (h.type.elts if isinstance(h.type, ast.Tuple)
                       else [h.type] if h.type else [])}
    assert "JobBusy" in named, (
        f"{fn} has no `except` naming JobBusy — found {sorted(named)}")
    bodies = " ".join(ast.unparse(h) for h in handlers)
    assert "409" in bodies, f"{fn} catches it but does not answer 409"


def test_no_route_starts_a_job_without_catching_it():
    """The guard that would have caught this one, over the WHOLE file, so a
    fourth button added later cannot reintroduce it.

    It reads the CALLS, not the prose. The first draft grepped a 37-line
    window for the word "JobBusy" and passed on the broken file, because the
    comment explaining the fix sits in that window and contains the word. A
    guard is only as wide as its pattern (CLAUDE.md) — and a guard satisfied
    by a comment is satisfied by nothing.
    """
    import ast
    import pathlib

    src = pathlib.Path("tradingagents/api.py").read_text(encoding="utf-8")
    lines = src.splitlines()
    starts = [n + 1 for n, ln in enumerate(lines)
              if ("dj.start(" in ln or "db_jobs.start(" in ln)
              and "def start" not in ln]
    assert starts, "no job starts found — has the API moved?"

    guarded = set()
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Try):
            continue
        named = {ast.unparse(n).split(".")[-1]
                 for h in node.handlers
                 for n in (h.type.elts if isinstance(h.type, ast.Tuple)
                           else [h.type] if h.type else [])}
        if "JobBusy" not in named:
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call) and ast.unparse(
                    inner.func).endswith(".start"):
                guarded.add(inner.lineno)

    loose = [n for n in starts if n not in guarded]
    assert not loose, (
        "these start a job outside any `except JobBusy`, so a busy machine "
        "answers 500: " + ", ".join(f"line {n}: {lines[n - 1].strip()}"
                                    for n in loose))


def test_the_exceptions_it_catches_actually_exist():
    """An `except` naming a class that is not there crashes WORSE than the
    bug it was written for — a NameError instead of a 500."""
    assert isinstance(dj.JobBusy, type) and issubclass(dj.JobBusy, Exception)
    assert isinstance(dj.LocalSweepsOff, type)
    assert issubclass(dj.LocalSweepsOff, Exception)


def test_a_free_machine_still_starts(one_row, monkeypatch):
    """The refusal must not swallow the happy path."""
    monkeypatch.setattr(dj, "start", lambda kind, spec=None: 4242)
    got = api.strategy_row_update("LG9NSU4B")
    assert got["started"] is True and got["pid"] == 4242
    assert got["coin"] == "XPIN" and got["tf"] == "1h"
