"""A day box's calendar opens where it can be SEEN (operator, Oct 16, 2026:
"when i click calendar in bakctest a room look at this" — a screenshot of the
Backtest a room calendar with its month name, arrows and weekday row cut off
above the window).

DayPicker always opened ABOVE its box, as asked on Oct 05, 2026 ("the pop is
showing under, its very hard to click, it should be above"). On a window
where the box sits less than a calendar's height from the top, "above" ran
off the screen. So: above when it fits, below when only that fits, and never
with its top outside the window.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "webapp" / "src"
PLACE = WEB / "lib" / "calendarPlace.ts"
PICKER = WEB / "components" / "form" / "DayPicker.tsx"

CAL = 330          # the calendar's height in this app's styling, about


def _place(top, bottom, view):
    node = shutil.which("node")
    if not node:                                     # pragma: no cover
        pytest.skip("node is not on PATH")
    js = (f'import {{ placeCalendar }} from "{PLACE.as_uri()}";'
          f"console.log(JSON.stringify(placeCalendar({{ top: {top}, bottom: {bottom} }}, {CAL}, {view})));")
    out = subprocess.run([node, "--input-type=module", "-e", js],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_it_opens_above_when_there_is_room_as_asked_on_oct_05():
    got = _place(top=600, bottom=640, view=900)
    assert got["above"] is True
    assert got["top"] + CAL <= 600, "it must not sit over its own box"


def test_it_opens_below_when_above_would_leave_the_window():
    """The screenshot: the box less than a calendar's height below the top."""
    got = _place(top=300, bottom=340, view=870)
    assert got["above"] is False
    assert got["top"] >= 340, "below the box, not over it"
    assert got["top"] + CAL <= 870


def test_its_top_is_never_outside_the_window():
    """No room either side (a very short window): the month row stays visible."""
    for top in (40, 150, 300, 450):
        got = _place(top=top, bottom=top + 40, view=480)
        assert got["top"] >= 0, got


def test_the_day_box_uses_that_rule():
    src = PICKER.read_text(encoding="utf-8")
    assert "placeCalendar(" in src
    assert "window.innerHeight" in src
