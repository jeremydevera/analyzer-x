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


def test_the_tab_offers_both_prompts_from_the_one_document():
    got = rf.prompts()
    assert [p["title"] for p in got] == ["1. Make a new forecast",
                                         "2. Look across every saved forecast"]
    # prompt 1 saves through the checked door, so every run makes a new forecast
    assert "python -m tradingagents.room_forecasts add" in got[0]["text"]
    assert "room_forecasts.jsonl" in got[1]["text"]


def test_the_route_serves_the_file_and_the_prompts(tmp_path, monkeypatch):
    f = tmp_path / "room_forecasts.jsonl"
    rf.add(_forecast(1790800000), path=f)
    monkeypatch.setattr(rf, "FILE", f)
    got = api.forecasts_route(page=1)
    assert got["total"] == 1 and got["forecasts"][0]["pick"] == "4FC03172"
    assert len(got["prompts"]) == 2


def test_the_tab_is_under_auto_trade():
    side = (ROOT / "webapp/src/layout/AppSidebar.tsx").read_text(encoding="utf-8")
    assert '{ name: "Forecast", path: "/forecast" }' in side
    assert (ROOT / "webapp/src/app/(admin)/forecast/page.tsx").exists()
    panel = (ROOT / "webapp/src/components/forecast/RoomForecasts.tsx").read_text(encoding="utf-8")
    assert "api.forecasts(page)" in panel and "fmtWhen(f.at)" in panel
