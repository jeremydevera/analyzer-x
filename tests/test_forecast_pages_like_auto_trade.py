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
    for src, lists in ((v2, ("{`${kind} streak`}", '"coins to avoid"', '"signal family"',
                             '"rule set"', '"what-if"')),
                       (rooms, ('"saved forecasts"', '"room backtest"', '"room strategies"'))):
        assert 'import PageButtons from "@/components/common/PageButtons"' in src
        for what in lists:
            assert f"what={what}" in src, what
    # the four old shapes are gone
    for old in ("function Pager(", ">back</button>", "‹ prev", "next ›", ">newer</button>",
                ">older</button>"):
        assert old not in v2 and old not in rooms, old


def test_no_long_list_is_cut_or_scrolled_in_the_browser():
    v2 = _src("forecast/ForecastV2.tsx")
    avoid = v2.split("function Avoid")[1].split("\nfunction ")[0]
    assert "api.forecastV2Avoid(page)" in avoid and "s.avoid.coins" not in avoid
    assert "max-h-[480px]" not in v2, "46 coins sat in one scroll box"
    assert "by_family.slice(" not in v2 and "api.forecastV2Families(page)" in v2
    assert "api.forecastV2WhatIfs(page)" in v2


# ----------------------------------------------------------- the server
def _live(coins=0, families=0):
    return {"avoid": {"coins": [{"coin": f"C{i:02d}", "profit": -50 + i} for i in range(coins)],
                      "examined": 101, "rule": "lost money over 5+ practice trades"},
            "money": {"by_family": [{"group": f"fam{i:02d}", "trades": 10, "wins": 4, "losses": 6,
                                     "profit": -20.0 + i, "per_trade": None, "winrate": 40.0,
                                     "thin": False} for i in range(families)]}}


def test_the_coins_to_avoid_page_on_the_server(monkeypatch):
    monkeypatch.setattr(f2a, "live", lambda: _live(coins=23))
    first, last = f2a.avoid(1), f2a.avoid(3)
    assert (first["total"], first["pages"], first["per"]) == (23, 3, 10)
    assert [c["coin"] for c in first["rows"]] == [f"C{i:02d}" for i in range(10)], "worst first, as ranked"
    assert len(last["rows"]) == 3 and last["examined"] == 101 and "5+" in last["rule"]
    assert f2a.avoid(99)["page"] == 3, "a page past the end is the last page"


def test_every_signal_family_pages_with_its_backtest_beside_it(monkeypatch):
    lv = _live(families=13)
    monkeypatch.setattr(f2a, "live", lambda: lv)
    monkeypatch.setattr(f2a, "latest", lambda: {"rooms": {
        "main": {"family": {"fam00": [5, 2, -3.0], "fam11": [1, 1, 0.5]}},
        "55D32617": {"family": {"fam00": [4, 3, 1.5]}}}})
    got = f2a.families(1)
    assert (got["total"], got["pages"], got["has_backtest"]) == (13, 2, True)
    assert got["rows"][0]["group"] == "fam00" and got["rows"][0]["bt"] == [9, 5, -1.5]
    assert got["rows"][1]["bt"] is None, "a family the backtest never traded"
    assert f2a.families(2)["rows"][1]["bt"] == [1, 1, 0.5]
    assert all("bt" not in g for g in lv["money"]["by_family"]), "the shared practice copy is never written"
    monkeypatch.setattr(f2a, "latest", lambda: None)
    none = f2a.families(1)
    assert none["has_backtest"] is False and none["rows"][0]["bt"] is None


def test_every_what_if_pages_newest_first_with_no_cap(monkeypatch):
    from tradingagents import forecast_v2_daily as fd

    monkeypatch.setattr(fd, "whatifs", lambda: {f"W{i:02d}": {"id": f"W{i:02d}", "asked_at": 1000 + i,
                                                              "status": "done", "why": ""}
                                                for i in range(23)})
    first, last = f2a.whatifs(1), f2a.whatifs(3)
    assert first["total"] == 23 and first["pages"] == 3 and first["rows"][0]["id"] == "W22"
    assert [w["id"] for w in last["rows"]] == ["W02", "W01", "W00"], "older than the newest 20 is reachable"


@pytest.fixture
def api_mod():
    from tradingagents import api as _api

    return _api


def test_the_room_lists_get_the_same_size_through_their_routes(api_mod, monkeypatch):
    from tradingagents import room_backtest as rb, room_strategies as rst

    seen = {}
    monkeypatch.setattr(rb, "compare", lambda *a, **k: seen.setdefault("backtest", k) and {})
    monkeypatch.setattr(rst, "table", lambda *a, **k: seen.setdefault("strategies", k) and {})
    api_mod.room_backtest_route("main", 1.0, 2.0, page=3)
    api_mod.room_strategies_route(1.0, 2.0, page=2)
    assert seen["backtest"]["per"] == f2a.PER_PAGE and seen["backtest"]["page"] == 3
    assert seen["strategies"]["per"] == f2a.PER_PAGE and seen["strategies"]["page"] == 2


def test_the_new_routes_answer_a_page(api_mod, monkeypatch):
    monkeypatch.setattr(f2a, "live", lambda: _live(coins=12, families=12))
    monkeypatch.setattr(f2a, "latest", lambda: None)
    assert len(api_mod.forecast_v2_avoid_route(page=2)["rows"]) == 2
    assert api_mod.forecast_v2_families_route(page=1)["pages"] == 2
    src = (ROOT / "tradingagents/api.py").read_text(encoding="utf-8")
    for route in ('@app.get("/api/forecast-v2/avoid")', '@app.get("/api/forecast-v2/families")',
                  "return _f2a.whatifs(page)"):
        assert route in src, route
    assert "rows[:20]" not in src.split('@app.get("/api/forecast-v2/whatif")')[1].split("@app.")[0]
