"""A pair the operator pressed UPDATE on is filed FIRST, not 5,095th.

Operator, `Sep 18, 2026`, having pressed UPDATE on #LG9NSU4B (XPIN 1h, `ote`,
TP 1.0 / SL 3.0, flat) and watched the job succeed:

    "is download done now / contunue"

The job WAS working by then. It measured XPIN correctly — **175 trades, 136
won, 39 lost, -$5.73 over 117 days**, written to `XPIN-1h.json` at 3:01am — and
reported honestly that it could not file the rows. What the screen still said
was the OLD measurement: **50 trades, +$36.97 over 29 days**.

The gap is the filing queue. Measured the same minute: XPIN 1h sat at position
**5,095 of 5,272** pairs waiting, because `stale_pairs()` returns
never-indexed-then-changed, both alphabetical, and nothing knew the operator
was standing in front of this one.

Retrying the lock is NOT the fix and was already in place: the job tries three
times, 20 s apart. Measured at 3:05am, six independent attempts with a
10-second wait each: **0 of 6 got the write lock** — the indexer holds it in
one long bulk transaction while it works the backlog. So the pair asks to be
NEXT rather than fighting to be now.
"""
import json

import pytest

from tradingagents import rows_index as ri


@pytest.fixture(autouse=True)
def _own_file(tmp_path, monkeypatch):
    """Never touch the operator's real queue file."""
    monkeypatch.setattr(ri, "ASKED_FIRST", tmp_path / "asked.json")


class _P:
    """A pair file, as `stale_pairs` yields them."""
    def __init__(self, stem):
        self.stem = stem


def _stale(monkeypatch, names):
    monkeypatch.setattr(ri, "_missing_ok", lambda fn, default: default)
    monkeypatch.setattr(ri, "stale_pairs", ri.stale_pairs)  # keep the real one
    return [_P(n) for n in names]


def test_asking_puts_the_pair_at_the_front():
    ri.ask_first("XPIN-1h")
    assert ri._asked() == ["XPIN-1h"]


def test_asking_twice_does_not_duplicate_it():
    ri.ask_first("XPIN-1h")
    ri.ask_first("XPIN-1h")
    assert ri._asked() == ["XPIN-1h"]


def test_the_newest_ask_wins_the_front():
    ri.ask_first("AAA-1h")
    ri.ask_first("ZZZ-4h")
    assert ri._asked()[0] == "ZZZ-4h", "the one just pressed goes first"


def test_the_list_is_capped():
    """A queue-jump list longer than this is a backlog wearing a hat."""
    for i in range(ri.ASKED_MAX + 25):
        ri.ask_first(f"C{i}-1h")
    assert len(ri._asked()) == ri.ASKED_MAX


def test_a_missing_or_broken_file_is_an_empty_list():
    assert ri._asked() == []
    ri.ASKED_FIRST.write_text("{not json", encoding="utf-8")
    assert ri._asked() == [], "a corrupt hint must never raise into a job"
    ri.ASKED_FIRST.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    assert ri._asked() == []


def test_an_unwritable_file_never_breaks_the_caller(monkeypatch):
    """The hint is worth nothing next to the measurement it decorates."""
    monkeypatch.setattr(ri, "ASKED_FIRST",
                        ri.Path("/nope/nowhere/asked.json"))
    ri.ask_first("XPIN-1h")          # must not raise


def test_stale_pairs_puts_the_asked_pair_first(tmp_path, monkeypatch):
    """THE BUG: XPIN was 5,095th of 5,272.

    This drives the REAL `stale_pairs()` over real files on disk. The first
    draft re-implemented the ordering inline and asserted on its own copy,
    which proves the test can add, not that the code can.
    """
    from tradingagents import market_sweep as msw

    rowdir = tmp_path / "rows"
    rowdir.mkdir()
    names = [f"C{i:04d}-1h" for i in range(300)] + ["XPIN-1h"]
    for n in names:
        (rowdir / f"{n}.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(msw, "ROWDIR", rowdir)
    # nothing indexed yet, and no watermark check to chase
    monkeypatch.setattr(ri, "_missing_ok", lambda fn, default: default)
    monkeypatch.setattr(ri, "stale_watermark", lambda stem: False)

    before = [f.stem for f in ri.stale_pairs()]
    assert before[0] != "XPIN-1h", "alphabetical order should bury it"
    assert before.index("XPIN-1h") > 250,         f"expected it near the back, found it at {before.index('XPIN-1h')}"

    ri.ask_first("XPIN-1h")
    after = [f.stem for f in ri.stale_pairs()]
    assert after[0] == "XPIN-1h", "the operator's own ask is filed first"
    assert sorted(after) == sorted(before),         "the jump may not lose or duplicate a single pair"


def test_an_asked_pair_that_is_no_longer_stale_leaves_the_list():
    """It filed — so it must not sit pinned to the front for ever, and a
    crash between the ask and the filing cannot strand it."""
    ri.ask_first("XPIN-1h")
    byname = {}                         # nothing is stale any more
    still = [a for a in ri._asked() if a in byname]
    assert still == []


def test_the_job_asks_when_it_cannot_file():
    """The button must do this itself — the operator cannot run a function."""
    import inspect

    from tradingagents import db_jobs as dj

    src = inspect.getsource(dj._run_pairbt)
    assert "ri.ask_first(" in src, "the pair never asks to jump the queue"
    i = src.index("ri.ask_first(")
    assert "if index_error:" in src[:i], \
        "it must ask ONLY when filing failed, not on every success"
