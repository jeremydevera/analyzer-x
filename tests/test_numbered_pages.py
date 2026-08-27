"""Numbered pagination — "make pagination like page 1 2 3 4" (2026-08-27).

The store holds 35,863,520 measured combinations. The pager before this had
first/prev/next/last and a "page 26 of 71,021" caption, and the operator read
that as a refusal to show them: *"why cant you show all? ... there are other
apps that have billions of rows and it shows all rows but paginated why cant
you do that"*.

Every row IS reachable and was before — but only by clicking next 71,020 times.
What those other apps have is NUMBERS: 1 2 … 25 [26] 27 … 71,021, and a box to
jump. That is what these tests hold in place.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "webapp" / "src"
PAGER = WEB / "lib" / "pager.ts"
PANELS = (WEB / "components" / "backtest" / "StrategiesPanel.tsx",
          WEB / "components" / "backtest" / "BacktestStorage.tsx")


def _node(script: str):
    """Run a snippet against the REAL pager.ts (node strips the types)."""
    node = shutil.which("node")
    if not node:                                     # pragma: no cover
        pytest.skip("node is not on PATH")
    out = subprocess.run([node, "--input-type=module", "-e", script],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def _window(page: int, pages: int):
    url = PAGER.as_uri()
    return _node(f'import {{ pageWindow }} from "{url}";'
                 f'console.log(JSON.stringify(pageWindow({page}, {pages})));')


def test_the_pager_is_numbers_not_just_next():
    """1, 2, the neighbourhood, and the last two — with gaps marked."""
    assert _window(1, 71021) == [1, 2, 3, None, 71020, 71021]
    assert _window(26, 71021) == [1, 2, None, 24, 25, 26, 27, 28, None,
                                  71020, 71021]
    assert _window(71021, 71021) == [1, 2, None, 71019, 71020, 71021]


def test_a_short_list_has_no_gaps_and_no_repeats():
    """Two pages must print `1 2`, not `1 2 … 1 2` — the first/last pushes and
    the window overlap on a small list."""
    assert _window(1, 1) == [1]
    assert _window(1, 2) == [1, 2]
    assert _window(2, 3) == [1, 2, 3]
    assert _window(3, 6) == [1, 2, 3, 4, 5, 6]


def test_no_page_number_is_outside_the_list():
    """A number that does not exist is a click that lands on nothing."""
    for pages in (1, 2, 5, 40, 71021):
        for page in (1, 2, pages // 2 or 1, pages):
            got = _window(page, pages)
            nums = [n for n in got if n is not None]
            assert nums == sorted(set(nums)), (page, pages, got)
            assert min(nums) >= 1 and max(nums) <= pages, (page, pages, got)


def test_the_window_always_holds_the_current_page():
    """Whatever page you are on, it is highlighted in the pager — otherwise the
    numbers do not tell you where you are."""
    for pages in (1, 3, 9, 71021):
        for page in {1, 2, 3, pages // 3 or 1, pages - 1 or 1, pages}:
            if page > pages:            # not a page that exists
                continue
            assert page in _window(page, pages), (page, pages)


@pytest.mark.parametrize("path", PANELS, ids=lambda p: p.name)
def test_both_tables_render_the_numbers(path):
    src = path.read_text(encoding="utf-8")
    assert 'from "@/lib/pager"' in src, "one pager, not a second copy"
    assert "pageWindow(" in src, "the numbers must be rendered"
    # the current page is MARKED, for a reader and for a screen reader
    assert 'aria-current={n ===' in src
    assert 'aria-label={`page ${n}`}' in src
    # 71,021 numbered links is what those apps do not do either
    assert re.search(r'\bnull\s*\?', src), "the gap must render as …"


def test_the_strategy_list_can_jump_to_any_page():
    """Numbers reach the neighbourhood; the box reaches row 30,000,000."""
    src = PANELS[0].read_text(encoding="utf-8")
    assert 'aria-label="Go to page"' in src
    assert 'e.key !== "Enter"' in src
    # a jump must not leave the previous page's LOAD MORE rows underneath it
    assert "setExtra([]);" in src.split("const goto")[1][:600]
