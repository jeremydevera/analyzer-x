"""Every list on the Forecast page pages like Auto Trade (operator, Oct 02,
2026: "in forecast, make it paginated just like in auto trade").

Auto Trade's Positions and Watcher page TEN rows at a time under numbered
buttons — prev, the numbers around this page with … for the distance, next,
"of N". The Forecast page had four other shapes: "back · page 1 of 694 ·
next", "newer / older", "‹ prev · next ›", and no pages at all (46 coins to
avoid in one scroll box, the 15 worst of 33 signal families, the newest 20
what-ifs). Every list now pages on the SERVER, ten a page, under one pager
whose buttons are Auto Trade's own.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from tradingagents import forecast_v2_api as f2a

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "webapp/src/components"


def _src(rel: str) -> str:
    return (WEB / rel).read_text(encoding="utf-8")


def _const(src: str, name: str) -> str:
    m = re.search(rf'const {name} =\s*((?:"[^"]*"\s*\+?\s*)+);', src)
    assert m, name
    return "".join(re.findall(r'"([^"]*)"', m.group(1)))


# ---------------------------------------------------------------- the size
def test_ten_a_page_like_auto_trade():
    for panel in ("trade/PositionsPanel.tsx", "trade/WatcherPanel.tsx"):
        assert "const PER_PAGE = 10;" in _src(panel), panel
    assert f2a.PER_PAGE == 10


# ------------------------------------------------------------- the buttons
def test_the_pager_is_auto_trades_own_buttons():
    pager = _src("common/PageButtons.tsx")
    watcher = _src("trade/WatcherPanel.tsx")
    for name in ("pageNum", "pageBtn"):
        assert _const(pager, name) == _const(watcher, name), name
    assert "pageWindow(cur, pages)" in pager and 'from "@/lib/pager"' in pager
    for words in (">prev</button>", ">next</button>", "of {pages}", "if (pages <= 1) return null",
                  "border-brand-500 bg-brand-500 font-semibold text-white"):
        assert words in pager, words


def test_every_list_on_the_forecast_page_uses_it():
    v2 = _src("forecast/ForecastV2.tsx")
    rooms = _src("forecast/RoomForecasts.tsx")
    # (no "coins to avoid" list since Oct 07, 2026 — the operator: "remove the
    # section coins to avoid i dont need its logic" — and no signal-family or
    # what-if list since Oct 08, 2026, when "Where the money goes" and the
    # what-if box went: "i dont need it anymore")
    for src, lists in ((v2, ("{`${kind} streak`}", '"rule set"')),
                       (rooms, ('"saved forecasts"', '"room backtest"', '"room strategies"',
                                '"room strategy trades"'))):
        assert 'import PageButtons from "@/components/common/PageButtons"' in src
        for what in lists:
            assert f"what={what}" in src, what
    # the four old shapes are gone
    for old in ("function Pager(", ">back</button>", "‹ prev", "next ›", ">newer</button>",
                ">older</button>"):
        assert old not in v2 and old not in rooms, old


def test_no_long_list_is_cut_or_scrolled_in_the_browser():
    v2 = _src("forecast/ForecastV2.tsx")
    assert "function Avoid" not in v2 and "forecastV2Avoid" not in v2, "Coins to avoid: removed Oct 07, 2026"
    assert "max-h-[480px]" not in v2, "46 coins sat in one scroll box"
    # the signal families and the what-ifs went with their sections (Oct 08, 2026)
    assert "forecastV2Families" not in v2 and "forecastV2WhatIfs" not in v2


# ----------------------------------------------------------- the server
@pytest.fixture
def api_mod():
    from tradingagents import api as _api

    return _api


def test_the_room_lists_get_the_same_size_through_their_routes(api_mod, monkeypatch):
    from tradingagents import room_backtest as rb, room_strategies as rst

    # A KEPT REALITY CHECK, so the route never starts the real background
    # refresh: left running, it kept forecast_v2_api busy into the next test
    # file, whose live() then answered NotReady (1-2 failures in
    # test_forecast_v2.py whenever this file ran first, Oct 07, 2026)
    monkeypatch.setitem(f2a._LIVE, "value", {"reality": {"all": {}}})
    seen = {}
    monkeypatch.setattr(rb, "compare", lambda *a, **k: seen.setdefault("backtest", k) and {})
    monkeypatch.setattr(rst, "table", lambda *a, **k: seen.setdefault("strategies", k) and {})
    api_mod.room_backtest_route("main", 1.0, 2.0, page=3)
    api_mod.room_strategies_route(1.0, 2.0, page=2)
    assert seen["backtest"]["per"] == f2a.PER_PAGE and seen["backtest"]["page"] == 3
    assert seen["strategies"]["per"] == f2a.PER_PAGE and seen["strategies"]["page"] == 2


def test_the_removed_lists_have_no_route(api_mod):
    """The coins to avoid went on Oct 07, 2026; the signal families and the
    what-ifs on Oct 08, 2026 ("delete Where the money goes section i dont
    need it anymore, delete What if ... as well") — their routes with them."""
    src = (ROOT / "tradingagents/api.py").read_text(encoding="utf-8")
    for path in ("/api/forecast-v2/avoid", "/api/forecast-v2/families", "/api/forecast-v2/whatif"):
        for verb in ("get", "post"):
            assert f'@app.{verb}("{path}")' not in src, (verb, path)
    for name in ("forecast_v2_families_route", "forecast_v2_whatif_route", "forecast_v2_whatifs_route"):
        assert not hasattr(api_mod, name), name
    assert not hasattr(f2a, "families") and not hasattr(f2a, "whatifs")


def test_every_forecast_table_reads_at_night():
    """Operator, Oct 07, 2026: "fix the ui on these when in night mode" — the
    Room strategies cells had no colour (dark grey on dark) and Safari drew the
    dropdowns light. The colour sits on each table BODY (a cell's own tone,
    profit green/red, still wins) and every field turns dark."""
    src = open("webapp/src/components/forecast/RoomForecasts.tsx", encoding="utf-8").read()
    bodies = src.count('<tbody className="divide-y')
    assert bodies and src.count('<tbody className="divide-y divide-gray-100 text-gray-700 '
                                'dark:divide-white/[0.05] dark:text-gray-300">') == bodies
    for line in [l for l in src.splitlines() if "const sel =" in l]:
        assert "dark:bg-gray-900" in line and "dark:[color-scheme:dark]" in line, line
    # a colour on every CELL would override the profit tone in the dark theme
    assert all("dark:text" not in l for l in src.splitlines() if "const td =" in l)
