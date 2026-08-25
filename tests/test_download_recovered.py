"""A FAILED download row says whether its lost pairs are back in the store.

Operator, 2026-08-25, an hour after both lost pairs had been re-downloaded:

    "still error 39,656,242 bars over 4985 pair(s) · 2 error(s):
     CHILLGUY_USDT 15m: IncompleteRead(183452 bytes read)
     and i cannot click retry failed button"

The row was the 2:00pm run's record and was true; the pairs it named were
recovered at 2:50pm; the RETRY button was rightly disabled. Nothing on the
screen connected the three, so a fixed failure read as a live one. Every
label here is derived from the store: a named pair is "recovered" only if
its parquet file exists, with its bar count and stored time beside it.
"""
import json

import pandas as pd
import pytest

from tradingagents import api, db_jobs, notifications as nt, parquet_store as pqs

FAILED_2PM = {
    "ts": 1787680852.35, "kind": "download", "ok": 0,
    "title": "Download finished with errors",
    "detail": "39,656,242 bars over 4985 pair(s) · 2 error(s): "
              "CHILLGUY_USDT 15m: IncompleteRead(183452 bytes read)",
    "meta": {"pairs": 4985, "bars": 39656242, "errors": 2, "stopped": False,
             "mode": "download"},
}
OK_250PM = {
    "ts": 1787683851.0, "kind": "download", "ok": 1, "title": "Download finished",
    "detail": "53,393 bars over 4 pair(s)",
    "meta": {"pairs": 4, "bars": 53393, "errors": 0, "stopped": False,
             "mode": "download"},
}


def _frame(n):
    return pd.DataFrame({"Date": pd.to_datetime([1_787_000_000 + 900 * i
                                                for i in range(n)], unit="s"),
                         "Open": [1.0] * n, "High": [1.0] * n, "Low": [1.0] * n,
                         "Close": [1.0] * n, "Volume": [1.0] * n})


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(pqs, "CANDLES", tmp_path / "candles")
    files = {k: dict(v) for k, v in db_jobs.FILES.items()}
    files["download"]["lost"] = tmp_path / "lost.json"
    monkeypatch.setattr(db_jobs, "FILES", files)
    (tmp_path / "lost.json").write_text(json.dumps({"pairs": [], "written": 1787685830}))
    return tmp_path


def test_a_failed_row_names_its_pairs_and_says_which_are_back(store, monkeypatch):
    monkeypatch.setattr(nt, "recent", lambda limit=20, kind=None: [OK_250PM, FAILED_2PM])
    pqs.save_candles("CHILLGUY_USDT", "15m", _frame(34650))
    rows = api.download_history()["rows"]
    ok, failed = rows[0], rows[1]
    assert ok["lost"] == [] and ok["unnamed"] == 0
    assert failed["unnamed"] == 1, "the 2pm record named only errors[0]"
    assert len(failed["lost"]) == 1
    got = failed["lost"][0]
    assert (got["symbol"], got["timeframe"], got["recovered"]) == ("CHILLGUY_USDT", "15m", True)
    assert got["bars"] == 34650
    assert got["when"], "when the store got the file — the operator's format"
    import re

    assert re.fullmatch(r"[A-Z][a-z]{2} \d{2}, \d{4} \d{1,2}:\d{2}[ap]m", got["when"])


def test_a_pair_not_in_the_store_is_still_lost(store, monkeypatch):
    monkeypatch.setattr(nt, "recent", lambda limit=20, kind=None: [FAILED_2PM])
    got = api.download_history()["rows"][0]["lost"][0]
    assert got["recovered"] is False and got["bars"] is None and got["when"] == ""


def test_rows_written_after_the_fix_name_every_pair_from_meta(store, monkeypatch):
    row = dict(FAILED_2PM, meta={**FAILED_2PM["meta"],
                                 "failed": ["CHILLGUY_USDT 15m: IncompleteRead(183452 bytes read)",
                                            "NAORIS_USDT 30m: IncompleteRead(9 bytes read)"]})
    monkeypatch.setattr(nt, "recent", lambda limit=20, kind=None: [row])
    pqs.save_candles("NAORIS_USDT", "30m", _frame(3))
    got = api.download_history()["rows"][0]
    assert [(p["symbol"], p["timeframe"], p["recovered"]) for p in got["lost"]] == [
        ("CHILLGUY_USDT", "15m", False), ("NAORIS_USDT", "30m", True)]
    assert got["unnamed"] == 0


def test_the_lost_route_reports_what_the_last_failed_run_lost_and_recovered(store, monkeypatch):
    """The button is disabled because the lost file is empty; the line under
    it must say WHY: the pairs the last failed run lost are back."""
    monkeypatch.setattr(nt, "recent", lambda limit=20, kind=None: [OK_250PM, FAILED_2PM])
    pqs.save_candles("CHILLGUY_USDT", "15m", _frame(5))
    got = api.candles_lost()
    assert got["count"] == 0 and got["pairs"] == []
    assert got["failed_run_when"] == "Aug 25, 2026 2:00pm"
    assert [(p["symbol"], p["timeframe"], p["bars"]) for p in got["recovered"]] == [
        ("CHILLGUY_USDT", "15m", 5)]
    assert got["unnamed"] == 1


def test_the_lost_route_with_no_failed_run_has_nothing_to_say(store, monkeypatch):
    monkeypatch.setattr(nt, "recent", lambda limit=20, kind=None: [OK_250PM])
    got = api.candles_lost()
    assert got["recovered"] == [] and got["failed_run_when"] == "" and got["unnamed"] == 0
