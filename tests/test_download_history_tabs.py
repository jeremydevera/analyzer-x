"""The download history groups its errors and splits into two tabs.

Operator, 2026-09-02: *"there are so many text here / can you group the error
messages in download history section / and create 'error' tab and success
tab"*. One run had named 26 lost pairs as 26 separate sentences — five of them
the same contract saying the same thing about five timeframes.

And the reason that run showed "0 bars · 0 pairs · download" while its own
detail said 1,280,408 bars over 5,117 pairs: `notifications.record` stored
`json.dumps(meta)[:2000]`, a blind cut of the finished JSON. That run's meta
carried 26 failure strings and 13 delisted names, went past 2,000 characters,
and was cut mid-string at `"mode`. Reading it back threw and fell back to `{}`,
so every number about the run was lost — and the worse a run went, the more
certain it was to lose all of it.
"""
import json

import pytest

from tradingagents import notifications as nt


def test_meta_that_is_too_long_still_parses_and_keeps_its_numbers():
    meta = {
        "pairs": 5117, "bars": 1280408, "errors": 26, "retries": 0,
        "stopped": False, "missing_added": 83, "mode": "update",
        "failed": [f"COIN{i}_USDT 15m: no Min15 candles for COIN{i}_USDT"
                   for i in range(200)],
        "delisted": [f"GONE{i}_USDT 1d" for i in range(50)],
    }
    text = nt.pack_meta(meta)
    got = json.loads(text)                      # must not raise
    assert len(text) <= nt.META_CHARS
    # the numbers the screen reads are never the thing dropped
    assert got["bars"] == 1280408 and got["pairs"] == 5117
    assert got["mode"] == "update" and got["errors"] == 26
    assert got["missing_added"] == 83
    # and what WAS dropped is counted, not silently gone
    assert len(got["failed"]) < 200
    assert got["failed_dropped"] == 200 - len(got["failed"])


def test_a_short_meta_is_untouched():
    meta = {"pairs": 4, "bars": 0, "errors": 4, "mode": "retry",
            "failed": ["MEZO_USDT 15m: no Min15 candles for MEZO_USDT"]}
    assert json.loads(nt.pack_meta(meta)) == meta


def test_a_value_json_cannot_hold_does_not_lose_the_whole_row():
    import datetime

    got = json.loads(nt.pack_meta({"pairs": 3, "bars": 9,
                                   "when": datetime.datetime.now()}))
    assert got["pairs"] == 3 and got["bars"] == 9


def test_it_never_returns_something_that_will_not_parse():
    """The whole point. Every shape must round-trip."""
    for meta in ({}, None, {"a": "x" * 50_000},
                 {"failed": ["y" * 300] * 400, "bars": 1},
                 {"nested": {"deep": ["z" * 100] * 200}, "pairs": 2}):
        json.loads(nt.pack_meta(meta))


def test_record_stores_readable_meta_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(nt, "DB_PATH", tmp_path / "notifications.db")
    meta = {"pairs": 5117, "bars": 1280408, "errors": 26, "mode": "update",
            "failed": [f"C{i}_USDT 1h: no Min60 candles for C{i}_USDT"
                       for i in range(120)]}
    assert nt.record("download", "Download finished with errors",
                     detail="1,280,408 bars over 5117 pair(s)", ok=False,
                     meta=meta)
    got = nt.recent(limit=1, kind="download")[0]
    assert got["meta"], "the meta must come back, not be swallowed by a parse error"
    assert got["meta"]["bars"] == 1280408
    assert got["meta"]["pairs"] == 5117
    assert got["meta"]["mode"] == "update"


# ------------------------------------------------------------------- the screen
SRC = open("webapp/src/components/candles/DownloadHistory.tsx",
           encoding="utf-8").read()


def test_there_are_two_tabs_and_the_runs_are_split_by_outcome():
    assert '{ id: "fail", label: "errors" }' in SRC
    assert '{ id: "ok", label: "success" }' in SRC
    assert '(tab === "ok" ? r.ok : !r.ok)' in SRC, \
        "errors go to the errors tab, success to the success tab"
    # each tab carries its own count, from the payload and not a literal
    assert "counts[t.id]" in SRC
    assert "{ fail: d.failed, ok: d.ok }" in SRC


def test_a_stopped_run_is_filed_with_the_errors():
    """It is unfinished, which is what somebody opening that tab is after."""
    assert "A STOPPED run is neither" in SRC


def test_the_failures_are_grouped_by_contract_not_listed_per_timeframe():
    assert "function groupFailures(" in SRC
    assert "function parseFailure(" in SRC
    # the same sentence with a different timeframe spliced in is ONE reason
    assert r'replace(/no (Min\d+|Hour\d+|Day\d+) candles for \S+/i,' in SRC
    assert '"no candles served"' in SRC
    # the timeframes it hit are listed on the one line
    assert 'g.tfs.join(" ")' in SRC
    assert '(all)' in SRC, "five of five reads as (all)"


def test_the_wall_of_text_is_behind_a_click():
    """The per-pair sentences still exist — they are just not the default."""
    assert "what happened" in SRC and "hide the detail" in SRC
    assert "still lost" in SRC and "recovered" in SRC
    assert "open ? named.length : 6" in SRC, "six contracts, then a +N more"


def test_the_panel_does_not_open_on_an_empty_tab():
    assert "if (d && !d.failed && d.ok) setTab" in SRC
    assert "no download has failed" in SRC
