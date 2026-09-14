"""The screen promised "it retries by itself" and nothing ever retried.

Operator, `Sep 15, 2026`, on a filter of win % >= 100 + TP >= SL + last 30
days: *"im using this filter is this expected to be so slow"*, then *"its
still loading till now"*, then *"so i need to refersh it to finish? why"*.

They then pasted what their screen said, which is the whole bug:

    the store has not answered this filter yet — win % >= 100 with filters
    beside it ... needs the widest win-rate index (rows_wr4) — without it
    every row above the floor is read off the disk to test the rest. It is
    being built in the background; try again in a while ... it retries by
    itself.

It retried ONCE. The effect behind that sentence used `setTimeout`, and when
the single retry was refused again the 503 handler set `waiting` to the SAME
string — so the dependency never changed, the effect never re-armed, and that
was the end of it. The answer became available the moment `rows_wr4` finished
building — measured at **7.5 s** once it existed — and the screen went on
saying "not answered yet" until the page was reloaded by hand.

A one-shot retry under a sentence that says "retries" is the harder version of
this bug to see: it works exactly once, so it looks implemented.

This is `label-must-match-data` on a PROMISE rather than a number: the
sentence described behaviour the component did not have.
"""
from __future__ import annotations

import pathlib
import re

import pytest

PANEL = pathlib.Path("webapp/src/components/backtest/StrategiesPanel.tsx")


@pytest.fixture(scope="module")
def src() -> str:
    return PANEL.read_text(encoding="utf-8")


def test_the_caption_still_makes_the_promise(src):
    """If the words ever go, this whole file should be revisited rather than
    quietly passing on a screen that no longer claims it."""
    assert "it retries by itself" in src


def test_a_refused_filter_is_actually_retried(src):
    """The promise, implemented: a standing 503 re-runs the request."""
    i = src.index("if (!waiting) return;")
    block = src[i:i + 320]
    assert "setInterval" in block, (
        "setTimeout fires ONCE: a repeat 503 sets the same `waiting` string, "
        "so the effect never re-arms and the retry never happens again")
    assert "setTimeout" not in block, "the one-shot retry must not come back"
    assert "load(true)" in block, (
        "and it must be the LOAD that re-runs, in the BACKGROUND so the table "
        "is not thrown back into its loading state under the operator")
    assert "clearInterval" in block, "the timer has to be torn down"


def test_it_only_retries_while_the_store_is_still_refusing(src):
    """Keyed on `waiting`, so a filter that answered does not keep polling —
    and the effect stops the moment the 503 clears."""
    i = src.index("if (!waiting) return;")
    head = src[max(0, i - 200):i]
    assert "useEffect(() => {" in head
    tail = src[i:i + 420]
    assert "}, [waiting, load]);" in tail, tail[-120:]


def test_it_cannot_stack_requests(src):
    """`load` is slow by definition here — this is the 503 path. A retry that
    fires while one is in flight is how four requests once held every browser
    lane (RCA-2026-09-09-I)."""
    i = src.index("if (!waiting) return;")
    assert "if (!inFlight.current) load(true);" in src[i:i + 320]


def test_a_successful_answer_clears_the_waiting_state(src):
    """Otherwise the retry loop never ends. The success path must reset it."""
    ok = src.index("setIdx(d.index ?? null);")
    assert 'setWaiting("")' in src[ok:ok + 200]


def test_a_real_error_is_not_retried_for_ever(src):
    """Only a 503 ("the index is being built") is a temporary refusal worth
    re-asking. Anything else is an error the operator has to see."""
    i = src.index("e.status === 503")
    branch = src[i:i + 400]
    assert "setWaiting(" in branch
    assert re.search(r"else\s*\{\s*setErr\(String\(e\)\);\s*setWaiting\(\"\"\);",
                     branch), "a non-503 must clear `waiting`, not retry"
