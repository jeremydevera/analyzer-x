"""Auto Trade -> Forecast shows the saved room forecasts (Oct 01, 2026:
"create a forecast tab, then if i run this prompt make sure it will generate
a new forecast / take note create forecast tab only for now").

The tab works nothing out: a forecast is made by the prompt in
docs/FORECAST-PROMPTS.md and saved with `room_forecasts.add`, which refuses a
line the tab could not show.
"""
import json
from pathlib import Path

import pytest

from tradingagents import api, room_forecasts as rf

ROOT = Path(__file__).resolve().parents[1]


def _forecast(at, pick="4FC03172", verdict="pick"):
    return {"at": at, "pick": pick, "verdict": verdict,
            "pick_why": "#4FC03172 lost least per trade",
            "rooms": [{"id": "4FC03172", "rules": "30 days · on 70%",
                       "research": {"profit": 4967.43},
                       "real": {"closed": 406, "wins": 161, "losses": 245,
                                "winrate": 39.7, "breakeven": 62.3,
                                "profit": -128.77, "per_trade": -0.317,
                                "worst_run": -27.5, "worst_run_trades": 25,
                                "open": 122, "days": 0.7}},
                      {"id": "main", "real": {"closed": 16, "wins": 6, "losses": 10,
                                              "winrate": 37.5, "breakeven": 62.3,
                                              "profit": -5.43, "per_trade": -0.339,
                                              "worst_run": -7.14, "worst_run_trades": 5,
                                              "open": 5, "days": 1.1}}],
            "artifact": None}


def test_a_new_forecast_is_appended_and_shown_newest_first(tmp_path):
    f = tmp_path / "room_forecasts.jsonl"
    rf.add(_forecast(1790800000), path=f)
    rf.add(_forecast(1790900000, pick=None, verdict="too early"), path=f)
    got = rf.read(path=f)
    assert got["total"] == 2 and got["unreadable"] == 0
    assert [x["at"] for x in got["forecasts"]] == [1790900000, 1790800000]
    # append only: the first line is still the first forecast, untouched
    first = json.loads(f.read_text(encoding="utf-8").splitlines()[0])
    assert first["at"] == 1790800000


def test_a_forecast_the_tab_cannot_show_is_refused_by_name(tmp_path):
    f = tmp_path / "room_forecasts.jsonl"
    bad = _forecast(1790800000)
    bad["pick"] = "NOTAROOM"
    del bad["rooms"][0]["real"]["breakeven"]
    with pytest.raises(ValueError) as e:
        rf.add(bad, path=f)
    msg = str(e.value)
    assert "NOTAROOM" in msg and "breakeven" in msg
    assert not f.exists(), "nothing is written when it is refused"
    with pytest.raises(ValueError, match="pick null"):
        rf.add(_forecast(1790800000, pick="main", verdict="too early"), path=f)


def test_a_broken_line_is_counted_never_silently_dropped(tmp_path):
    f = tmp_path / "room_forecasts.jsonl"
    rf.add(_forecast(1790800000), path=f)
    with f.open("a", encoding="utf-8") as fh:
        fh.write("{not json\n")
    got = rf.read(path=f)
    assert got["total"] == 1 and got["unreadable"] == 1


def test_ten_a_page(tmp_path):
    f = tmp_path / "room_forecasts.jsonl"
    for i in range(23):
        rf.add(_forecast(1790800000 + i), path=f)
    p1, p3 = rf.read(page=1, path=f), rf.read(page=3, path=f)
    assert p1["pages"] == 3 and len(p1["forecasts"]) == 10 and len(p3["forecasts"]) == 3
    assert p1["forecasts"][0]["at"] == 1790800022


def test_the_tab_offers_every_prompt_from_the_one_document():
    got = rf.prompts()
    # the first four in order, and every prompt numbered 1..N — a later prompt
    # is added, never a hardcoded count to break (prompt 4 arrived Oct 02, 2026)
    assert [p["title"] for p in got][:4] == ["1. Make a new forecast",
                                             "2. Look across every saved forecast",
                                             "3. Find the best room rules (every shape, nothing left out)",
                                             "4. Find new winning room strategies and keep them in Best room rules"]
    assert [p["title"].split(".")[0] for p in got] == [str(i) for i in range(1, len(got) + 1)]
    # prompt 4 (Oct 02, 2026: "when i run prompt 4 i want it to find out winning
    # strategy and store it in Best room this month", then "i want it to be
    # flexible where i can select a between date range instead of hard cap 1
    # month only"): prompt 3's every-shape search, every winner kept as a row of
    # "Best room rules", and that section a FROM-TO date range re-measured over
    # the exact dates (never a month scaled, RCA-2026-10-01-J). The numbers and
    # rules it names are the code's own.
    from tradingagents import (
        backtest_report as br,
        forecast_rules as fr,
        watcher_policy as wp,
        watcher_research as rs,
    )

    p4 = " ".join(got[3]["text"].split())        # the phrases, whatever the line breaks
    assert "never a month scaled up or down" in p4 and "RCA-2026-10-01-J" in p4
    assert 'rename it from "Best room rules this month" to "Best room rules"' in p4
    assert "FROM and TO dates" in p4 and "re-measured over exactly the chosen dates" in p4
    assert f'write_rule "{rs.SCENARIOS6_WRITE}"' in p4, "the same loose data as prompt 3"
    assert f"grid 6 ({len(rs.scenarios6()):,})" in p4
    assert f"{len(fr.OPTIONS)} options (forecast_rules.OPTIONS)" in p4
    assert "never repeats one" in p4 and "A FAIR PICK" in p4
    # what a room cannot run yet is named as a switch it needs: the watcher takes
    # a 15- or 30-day window only, and none of Forecast v2's 1.5x / 2x rules
    assert br.RECENT_DAYS == 15 and "1.5x" not in wp.TP_RULES and "=" in wp.TP_RULES
    assert "a 7-day window" in p4 and "TP at least 1.5x or 2x SL" in p4
    assert "Read only on trading" in p4 and "never `git stash`" in p4
    # prompt 1 saves through the checked door, so every run makes a new forecast
    assert "python -m tradingagents.room_forecasts add" in got[0]["text"]
    assert "room_forecasts.jsonl" in got[1]["text"]
    # prompt 3 (Oct 01, 2026: "currently i think you are avoiding sl is greater
    # than tp or avoiding tp that is very high but low trade"): every shape is in
    # the grid, and the data is re-collected loose enough to test them fairly
    p3 = got[2]["text"]
    assert "1, 3, 5, 10, 20, 30 and 50" in p3 and "smallest target allowed: none, 1%, 2%, 3%" in p3
    assert "Pick on July–August, grade on September" in p3
    # COPY AND RUN (Oct 01, 2026: "i want it ready then"): the commands are
    # the real ones, and the grid and write rule they name are the code's
    from tradingagents import watcher_research as rs
    assert f'write_rule="{rs.SCENARIOS6_WRITE}"' in p3
    assert "-f scenarios=6 -f chunks=4" in p3
    assert "python -m tradingagents.research_merge s6" in p3
    assert "python -m tradingagents.research_page s6 --split --log-top 100" in p3
    assert f"{len(rs.scenarios6()):,} rule sets" in p3


def test_the_route_serves_the_file_and_the_prompts(tmp_path, monkeypatch):
    f = tmp_path / "room_forecasts.jsonl"
    rf.add(_forecast(1790800000), path=f)
    monkeypatch.setattr(rf, "FILE", f)
    got = api.forecasts_route(page=1)
    assert got["total"] == 1 and got["forecasts"][0]["pick"] == "4FC03172"
    # exactly what the one document holds, however many prompts that is
    assert got["prompts"] == rf.prompts() and len(got["prompts"]) >= 4


def test_the_tab_is_under_auto_trade():
    side = (ROOT / "webapp/src/layout/AppSidebar.tsx").read_text(encoding="utf-8")
    # MERGED Oct 02, 2026 ("can i merge forecast to forecast v2 ... what
    # matters to me is this prompt and ability to backtest a room strategy"):
    # one Forecast item, opening Forecast v2 with Backtest a room under it;
    # the first page stays at its address, off the menu
    assert '{ name: "Forecast", path: "/forecast-v2" }' in side
    assert 'path: "/forecast" }' not in side
    assert (ROOT / "webapp/src/app/(admin)/forecast/page.tsx").exists()
    v2 = (ROOT / "webapp/src/app/(admin)/forecast-v2/page.tsx").read_text(encoding="utf-8")
    assert "<ForecastV2 />" in v2 and "<RoomsAndBacktest />" in v2
    # ...and the prompts' copy buttons came with it: prompt 4 is half of what
    # the operator said matters on this page
    rf_src = (ROOT / "webapp/src/components/forecast/RoomForecasts.tsx").read_text(encoding="utf-8")
    merged = rf_src[rf_src.index("export function RoomsAndBacktest"):]
    assert "api.forecasts(1)" in merged and "saved.prompts.map((p) => <PromptBox" in merged
    assert "<RoomBacktestPanel rooms={live.rooms} />" in merged
    panel = (ROOT / "webapp/src/components/forecast/RoomForecasts.tsx").read_text(encoding="utf-8")
    assert "api.forecasts(page)" in panel and "fmtWhen(f.at)" in panel
