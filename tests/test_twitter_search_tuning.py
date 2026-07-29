"""Search tuning for freshly listed coins.

The defaults were built for equities: a 7-day window, engagement-ranked results,
and an English-only filter. For a coin listed three hours ago those choices work
against the goal — the window covers days the coin did not exist, "Top" favours
pre-listing announcements over the live reaction, and the crowd trading new
listings is largely not tweeting in English.
"""

from unittest.mock import patch

import pytest

from tradingagents.agents.analysts import sentiment_analyst as sa
from tradingagents.dataflows import twitter

pytestmark = pytest.mark.unit


# --- query construction ---------------------------------------------------


def test_query_has_no_language_filter_by_default():
    """Non-English chatter is most of the audience for a new listing."""
    assert "lang:" not in twitter._build_query("$XPLK", None, None)


def test_language_filter_can_be_requested():
    assert "lang:en" in twitter._build_query("$XPLK", None, None, lang="en")


def test_query_keeps_the_date_window():
    q = twitter._build_query("$XPLK", "2026-07-27", "2026-07-30")
    assert "since:2026-07-27" in q and "until:2026-07-30" in q


# --- sort order -----------------------------------------------------------


def test_sort_order_is_passed_to_the_endpoint(monkeypatch):
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    monkeypatch.setattr(twitter, "_RETRY_SLEEP", 0.0)
    seen = []

    def capture(params, key, timeout):
        seen.append(params.get("queryType"))
        return {"tweets": [{"text": "p", "createdAt": "2026-07-30",
                            "author": {"userName": "u"}}], "has_next_page": False}

    with patch.object(twitter, "_request", side_effect=capture):
        twitter.fetch_twitter_posts("$XPLK", sort="Latest", include_replies=False)
    assert seen == ["Latest"]


def test_sort_defaults_to_top(monkeypatch):
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    monkeypatch.setattr(twitter, "_RETRY_SLEEP", 0.0)
    seen = []

    def capture(params, key, timeout):
        seen.append(params.get("queryType"))
        return {"tweets": [{"text": "p", "createdAt": "2026-07-30",
                            "author": {"userName": "u"}}], "has_next_page": False}

    with patch.object(twitter, "_request", side_effect=capture):
        twitter.fetch_twitter_posts("$XPLK", include_replies=False)
    assert seen == ["Top"]


# --- author credibility ---------------------------------------------------


def _tweet(user, followers=None, blue=False, text="hello", likes=0):
    author = {"userName": user, "isBlueVerified": blue}
    if followers is not None:
        author["followers"] = followers
    return {"id": "1", "text": text, "createdAt": "Wed Jul 29 08:25:57 +0000 2026",
            "likeCount": likes, "retweetCount": 0, "replyCount": 0, "author": author}


def test_post_line_shows_follower_count():
    """A 200-follower shill and a 48k-follower account are not equal evidence."""
    out = twitter.format_thread_block("$X", None, None, [_tweet("whale", 48_210)], [], 0)
    line = next(ln for ln in out.splitlines() if "whale" in ln)
    assert "48.2k followers" in line


def test_small_follower_counts_are_shown_exactly():
    out = twitter.format_thread_block("$X", None, None, [_tweet("nano", 9)], [], 0)
    assert "9 followers" in out


def test_verified_authors_are_marked():
    out = twitter.format_thread_block("$X", None, None,
                                      [_tweet("real", 1000, blue=True)], [], 0)
    line = next(ln for ln in out.splitlines() if "real" in ln)
    assert "✓" in line


def test_missing_follower_data_is_simply_omitted():
    out = twitter.format_thread_block("$X", None, None, [_tweet("mystery")], [], 0)
    assert "followers" not in out
    assert "@mystery" in out


def test_reply_lines_also_carry_follower_counts():
    posts = [_tweet("poster")]
    replies = [dict(_tweet("replier", 1_500), id="2", inReplyToId="1")]
    out = twitter.format_thread_block("$X", None, None, posts, replies, 0)
    line = next(ln for ln in out.splitlines() if "replier" in ln)
    assert "1.5k followers" in line


# --- the analyst's choices for a young coin -------------------------------


def test_window_starts_before_listing_for_a_young_coin(monkeypatch):
    """Pre-listing hype is real signal; days before the coin existed are not."""
    seen = {}
    monkeypatch.setattr(sa, "fetch_twitter_posts",
                        lambda terms, **kw: seen.update(kw) or "T")
    monkeypatch.setattr(sa, "get_config", lambda: {
        "include_twitter": True, "asset_display_name": "xPayLink",
        "asset_listed_date": "2026-07-29", "asset_age_hours": 10.0})
    sa._maybe_twitter_block("XPLKUSDT", "2026-07-23", "2026-07-30")
    assert seen["start_date"] == "2026-07-27"      # listing minus two days
    assert seen["end_date"] == "2026-07-30"


def test_window_falls_back_to_the_seven_day_default(monkeypatch):
    seen = {}
    monkeypatch.setattr(sa, "fetch_twitter_posts",
                        lambda terms, **kw: seen.update(kw) or "T")
    monkeypatch.setattr(sa, "get_config", lambda: {"include_twitter": True})
    sa._maybe_twitter_block("NVDA", "2026-07-23", "2026-07-30")
    assert seen["start_date"] == "2026-07-23"


def test_a_listing_older_than_the_window_does_not_widen_it(monkeypatch):
    """An old coin must not drag the window back weeks."""
    seen = {}
    monkeypatch.setattr(sa, "fetch_twitter_posts",
                        lambda terms, **kw: seen.update(kw) or "T")
    monkeypatch.setattr(sa, "get_config", lambda: {
        "include_twitter": True, "asset_listed_date": "2026-01-01",
        "asset_age_hours": 5000.0})
    sa._maybe_twitter_block("OLDUSDT", "2026-07-23", "2026-07-30")
    assert seen["start_date"] == "2026-07-23"


@pytest.mark.parametrize("age_hours,expected", [
    (2.0, "Latest"),        # hours old: the live reaction is the signal
    (10.0, "Latest"),
    (23.9, "Latest"),
    (48.0, "Top"),          # settled: rank by engagement
    (None, "Top"),
])
def test_sort_follows_the_coin_age(monkeypatch, age_hours, expected):
    seen = {}
    monkeypatch.setattr(sa, "fetch_twitter_posts",
                        lambda terms, **kw: seen.update(kw) or "T")
    config = {"include_twitter": True}
    if age_hours is not None:
        config["asset_age_hours"] = age_hours
    monkeypatch.setattr(sa, "get_config", lambda: config)
    sa._maybe_twitter_block("XPLKUSDT", "2026-07-23", "2026-07-30")
    assert seen["sort"] == expected
