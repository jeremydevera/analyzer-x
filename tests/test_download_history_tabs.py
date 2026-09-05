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


def test_pending_is_a_tab_and_it_is_the_one_that_opens():
    """Operator: *"i dont know if there are still errors or not ... if there
    are unfinished or error or pending on my side, put that in the tab
    'Pending'"*. The old tabs counted RUNS that had failed at some point; a run
    that failed in August is not a thing to do in September."""
    assert '{ id: "pending", label: "pending" }' in SRC
    assert 'useState<Tab>("pending")' in SRC, "it must be the default tab"
    assert '{ id: "fail", label: "failed runs" }' in SRC
    assert '{ id: "ok", label: "clean runs" }' in SRC
    assert "What still needs doing is in <b>pending</b>" in SRC


def test_pending_reads_the_store_now_not_the_run_history():
    for call in ("api.candleLost()", "api.candleCompleteness()",
                 "api.candleGaps()"):
        assert call in SRC, call
    assert "notifyApi.downloadHistory" in SRC, "history still feeds its own tabs"


def test_only_what_a_button_can_fix_counts_as_pending():
    """25 of the 26 lost pairs were the venue serving no candles. Counting
    those as pending is what made "26 still lost" read as 26 problems.

    The count moved into the ROUTE on Sep 04, 2026 (`/api/candles/pending`),
    so the Pending tab and the RESOLVE PENDING button read ONE number. This
    component added it up itself while the button read a different field —
    two answers to one question on one screen. The component keeps its own
    arithmetic only as the fallback for the moment before the route answers.
    """
    assert "api.candlePending()" in SRC, "the count comes from the route"
    assert "work ? work.count :" in SRC, "with the local sum only as fallback"
    assert "Only the things a BUTTON on this screen can change" in SRC
    assert "nothing pending" in SRC
    # and the unfixable ones are still shown, just never added in
    assert "more nothing can" in SRC


def test_each_pending_thing_names_the_button_that_fixes_it():
    assert 'fix="press UPDATE CANDLES"' in SRC
    assert 'fix="press RETRY FAILED"' in SRC
    assert "a retry gets the same empty answer" in SRC
    assert "nothing can fetch a contract MEXC has dropped" in SRC


def test_a_delisted_pair_is_not_drawn_as_a_retryable_error():
    """The contradiction the operator was looking at: "FAILED · RESOLVED"
    beside "4 pairs still lost", when those pairs were delisted."""
    assert 'p.kind ?? "retry"' in SRC
    assert '"delisted" ? "delisted &mdash; nothing can fetch these"' in SRC         or "delisted — nothing can fetch these" in SRC
    assert "the venue serves no candles for these" in SRC


def test_the_failures_are_grouped_by_contract():
    assert "function groupBy(" in SRC
    assert 'g.tfs.join(" ")' in SRC
    assert '"all 5"' in SRC, "five of five reads as one word"


def test_the_wall_of_text_is_behind_a_click():
    assert "which ones" in SRC and '{open ? "hide"' in SRC
