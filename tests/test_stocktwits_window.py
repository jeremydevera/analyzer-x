"""StockTwits messages must be confined to the analysis window.

The stream returns the 30 most-recent messages whenever they happen to be from.
For a newly listed coin whose ticker was used years ago by a different asset,
that means 2021 chatter arriving as today's retail sentiment: AEON.X's newest
message is 878 days old, and CATE.X's is 118 days old, with nothing inside a
week. The prompt calls this a fast-moving signal, so stale messages have to be
dropped rather than presented as current.
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from tradingagents.dataflows import stocktwits

pytestmark = pytest.mark.unit


def _msg(days_ago, username="trader", sentiment=None, body="hello"):
    stamp = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    entities = {"sentiment": {"basic": sentiment}} if sentiment else {}
    return {"id": days_ago, "created_at": stamp, "body": body,
            "user": {"username": username}, "entities": entities}


def _payload(*messages):
    return {"messages": list(messages)}


def _patch_response(payload):
    class _Resp:
        def read(self):
            return json.dumps(payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return patch.object(stocktwits, "urlopen", return_value=_Resp())


def test_keeps_only_messages_inside_the_window():
    payload = _payload(_msg(1, "fresh", "Bullish"), _msg(300, "ancient", "Bullish"))
    with _patch_response(payload):
        out = stocktwits.fetch_stocktwits_messages("AEON.X", window_days=7)
    assert "@fresh" in out
    assert "@ancient" not in out
    assert "Total: 1" in out


def test_counts_reflect_only_windowed_messages():
    payload = _payload(_msg(1, "a", "Bullish"), _msg(2, "b", "Bearish"),
                       _msg(400, "c", "Bullish"), _msg(500, "d", "Bullish"))
    with _patch_response(payload):
        out = stocktwits.fetch_stocktwits_messages("BTC.X", window_days=7)
    assert "Bullish: 1 (50%)" in out
    assert "Bearish: 1 (50%)" in out
    assert "Total: 2" in out


def test_reports_when_everything_is_older_than_the_window():
    """The AEON.X case: real messages, none recent. Must read as unavailable."""
    payload = _payload(_msg(878, "old1", "Bullish"), _msg(1933, "old2", "Bullish"))
    with _patch_response(payload):
        out = stocktwits.fetch_stocktwits_messages("AEON.X", window_days=7)
    assert out.startswith("<no StockTwits messages")
    assert "7 days" in out
    assert "2 older" in out              # says what it discarded
    assert "878" in out                  # and how stale the newest was


def test_window_can_be_disabled_for_callers_that_want_everything():
    payload = _payload(_msg(1, "fresh"), _msg(900, "ancient"))
    with _patch_response(payload):
        out = stocktwits.fetch_stocktwits_messages("BTC.X", window_days=None)
    assert "@fresh" in out and "@ancient" in out


def test_default_window_is_seven_days_to_match_the_prompt():
    payload = _payload(_msg(1, "fresh"), _msg(30, "monthold"))
    with _patch_response(payload):
        out = stocktwits.fetch_stocktwits_messages("BTC.X")
    assert "@fresh" in out
    assert "@monthold" not in out


def test_malformed_timestamps_are_dropped_not_crashed():
    payload = {"messages": [{"id": 1, "created_at": "not-a-date", "body": "x",
                             "user": {"username": "weird"}, "entities": {}},
                            _msg(1, "fresh")]}
    with _patch_response(payload):
        out = stocktwits.fetch_stocktwits_messages("BTC.X", window_days=7)
    assert "@fresh" in out
    assert "@weird" not in out


def test_message_ages_are_shown_so_the_model_can_weight_them():
    payload = _payload(_msg(0, "today"), _msg(5, "lastweek"))
    with _patch_response(payload):
        out = stocktwits.fetch_stocktwits_messages("BTC.X", window_days=7)
    assert "newest" in out.lower()
