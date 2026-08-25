"""GET /api/candles/lost — what the RETRY FAILED button shows and counts.

It reads the download job's own lost file, so the button's number is the
same list the retry will fetch — never a second bookkeeping of it.

The endpoint function is called directly: conftest forbids sockets, and on
Windows a TestClient cannot even build its event loop without one.
"""
import json

import pytest

from tradingagents import api, db_jobs


@pytest.fixture
def lost_file(tmp_path, monkeypatch):
    path = tmp_path / "db_download.lost.json"
    files = {k: dict(v) for k, v in db_jobs.FILES.items()}
    files["download"]["lost"] = path
    monkeypatch.setattr(db_jobs, "FILES", files)
    return path


def test_the_route_is_registered_as_a_get():
    routes = {r.path: r for r in api.app.routes if hasattr(r, "path")}
    assert "/api/candles/lost" in routes
    assert routes["/api/candles/lost"].methods == {"GET"}


def test_the_route_names_and_counts_the_lost_pairs(lost_file):
    lost_file.write_text(json.dumps({
        "pairs": [["CHILLGUY_USDT", "15m"], ["NAORIS_USDT", "30m"]],
        "written": 1787680852}))
    got = api.candles_lost()
    assert got["count"] == 2
    assert got["pairs"] == [{"symbol": "CHILLGUY_USDT", "timeframe": "15m"},
                            {"symbol": "NAORIS_USDT", "timeframe": "30m"}]
    assert got["written"] == "Aug 25, 2026 2:00pm", "the operator's date format"


def test_no_file_means_nothing_lost_not_an_error(lost_file, monkeypatch):
    from tradingagents import notifications as nt

    monkeypatch.setattr(nt, "recent", lambda limit=20, kind=None: [])
    assert not lost_file.exists()
    got = api.candles_lost()
    assert (got["pairs"], got["count"], got["written"]) == ([], 0, "")
    assert (got["recovered"], got["failed_run_when"], got["unnamed"]) == ([], "", 0)
