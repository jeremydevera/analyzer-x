"""A background refresh must not re-arm itself off the answer it just got.

Found Sep 09, 2026 by the press log the operator had asked for ten minutes
earlier — *"whenever i clicked apply filter and click download csv you should
be getting the logs of it so you can see the status"*. Measured straight out of
`~/.tradingagents/screen.log`, with the four chips applied and NOBODY touching
the page:

    page open, 60 s idle   ->  8 new `apply` lines
    page closed, 45 s      ->  0

Every one of those was the operator's own filter — 3.4 s, 25 rows re-measured
from this PC's candles — and it ran forever:

    useEffect(() => {
      if (!idx || (!idx.syncing && idx.behind === 0)) return;
      const t = setTimeout(() => { if (!inFlight.current) load(true); }, 5000);
      return () => clearTimeout(t);
    }, [idx, load]);          // <- idx is a NEW OBJECT in every response

`setIdx(d.index)` runs on every answer, so `idx` changed identity every time,
the effect re-fired, the 5-second timer re-armed, and the request went again.
The early return could never save it: `behind` is only 0 when the index has
caught up with the sweep, and on this store a sweep is nearly always running
(4,557 of 4,605 pairs indexed at the time).

Two costs, both real: 3.4 s of candle re-measurement every ~8 s on the machine
that is measuring the market, and one of the app's four browser lanes held
permanently — the same lanes whose exhaustion made the table wait five minutes
in RCA-I.

The rule: **a repeating refresh keys on VALUES, never on an object from a
response.** An object from a response is new every time, so it is not a
dependency, it is a metronome.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

PANEL = Path("webapp/src/components/backtest/StrategiesPanel.tsx")


@pytest.fixture(scope="module")
def src() -> str:
    return PANEL.read_text(encoding="utf-8")


def test_the_catch_up_refresh_keys_on_a_boolean_not_the_index_object(src):
    assert "const catchingUp = !!idx && (idx.syncing || idx.behind > 0);" in src
    body = src[src.index("if (!catchingUp) return;"):]
    body = body[:body.index("}, [")] + body[body.index("}, ["):][:40]
    assert "[catchingUp, load]" in body, body
    assert "setInterval" in body, "a repeating refresh is an interval, not a re-armed timeout"


def test_no_effect_depends_on_the_index_object(src):
    """`idx` comes fresh out of every response; in a dep array it is a timer."""
    bad = re.findall(r"\}, \[[^\]]*\bidx\b[^\]]*\]", src)
    assert not bad, f"an effect keyed on the response object: {bad}"


def test_the_refresh_is_slow_enough_to_be_free(src):
    """Each background load re-measures the window's rows from candles — 3.4 s
    on the operator's own filter. 5 seconds was not a refresh, it was a loop."""
    i = src.index("if (!catchingUp) return;")
    window = src[i:i + 400]
    m = re.search(r"setInterval\([^,]+,\s*([\d_]+)\)", window)
    assert m, window
    assert int(m.group(1).replace("_", "")) >= 30_000, m.group(1)


def test_a_background_load_still_never_shows_a_spinner(src):
    """The button belongs to the click: a timer's request must be silent, or
    the operator reads a refresh as their own press hanging."""
    assert "load(true)" in src
    i = src.index("const load = useCallback((background = false)")
    assert "if (!background) setLoading(true);" in src[i:i + 400]


def test_the_one_shot_retry_after_a_503_is_still_there(src):
    """The other timer is a single retry on the store's own "index is being
    built" answer — that one is correct and keyed on a STRING."""
    i = src.index("if (!waiting) return;")
    body = src[i:i + 260]
    assert "setTimeout" in body, "a 503 retry is one shot, not an interval"
    assert "[waiting, load]" in body
