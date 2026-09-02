"""GET /api/candles/lost — what the RETRY FAILED button shows and counts.

It reads the download job's own lost file, so the button's number is the
same list the retry will fetch — never a second bookkeeping of it.

The endpoint function is called directly: conftest forbids sockets, and on
Windows a TestClient cannot even build its event loop without one.
"""
import json
import re

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
    # each pair now says WHY it is lost as well (2026-09-02): "26 still lost"
    # was reading as 26 problems when 25 of them were the venue serving no
    # candles at all, which no retry can change.
    assert [(p["symbol"], p["timeframe"]) for p in got["pairs"]] == [
        ("CHILLGUY_USDT", "15m"), ("NAORIS_USDT", "30m")]
    assert all(p["kind"] in ("retry", "empty", "delisted", "recovered")
               for p in got["pairs"]), got["pairs"]
    # The FORMAT is the rule, not a fixed literal: the same epoch prints twelve
    # hours apart in Manila and New York, and the operator moved this PC's
    # timezone on 2026-08-27 — which failed this assertion and nothing else.
    from tradingagents import positions_view as pv

    assert got["written"] == pv.fmt_when(1787680852), "the operator's date format"
    assert re.fullmatch(r"[A-Z][a-z]{2} \d{2}, \d{4} \d{1,2}:\d{2}[ap]m",
                        got["written"]), got["written"]


def test_no_file_means_nothing_lost_not_an_error(lost_file, monkeypatch):
    from tradingagents import notifications as nt

    monkeypatch.setattr(nt, "recent", lambda limit=20, kind=None: [])
    assert not lost_file.exists()
    got = api.candles_lost()
    assert (got["pairs"], got["count"], got["written"]) == ([], 0, "")
    assert (got["recovered"], got["failed_run_when"], got["unnamed"]) == ([], "", 0)
