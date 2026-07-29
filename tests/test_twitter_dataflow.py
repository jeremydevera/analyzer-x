"""Unit tests for the Twitter/X sentiment fetcher (no network)."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tradingagents.dataflows import twitter

pytestmark = pytest.mark.unit

_FIXTURE = Path(__file__).parent / "fixtures" / "twitterapi_search.json"


@pytest.fixture
def payload():
    return json.loads(_FIXTURE.read_text())


def test_returns_placeholder_without_key(monkeypatch):
    monkeypatch.delenv("TWITTERAPI_IO_KEY", raising=False)
    out = twitter.fetch_twitter_posts("$CATE")
    assert out == "<twitter unavailable: TWITTERAPI_IO_KEY not set>"


def test_formats_posts_from_payload(monkeypatch, payload):
    """Parses the recorded live response — field names come from a real call."""
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    with patch.object(twitter, "_request", return_value=payload):
        out = twitter.fetch_twitter_posts("$BTC", start_date="2026-07-22",
                                          end_date="2026-07-29")
    assert "X/Twitter posts" in out
    assert "<twitter unavailable" not in out
    # Every recorded post's handle, timestamp, and like count must survive.
    for tweet in payload["tweets"]:
        assert f"@{tweet['author']['userName']}" in out
        assert f"{tweet['likeCount']} likes" in out
        assert tweet["createdAt"] in out
    # Newlines inside a post body would corrupt the one-post-per-line format.
    body_lines = [ln for ln in out.split("\n") if ln.startswith("[")]
    assert len(body_lines) == len(payload["tweets"])


def test_truncates_long_bodies(monkeypatch):
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    long_body = {"tweets": [{"text": "x" * 400, "createdAt": "2026-07-28T00:00:00Z",
                             "likeCount": 1, "retweetCount": 0,
                             "author": {"userName": "u"}}]}
    with patch.object(twitter, "_request", return_value=long_body):
        out = twitter.fetch_twitter_posts("$CATE")
    assert "…" in out
    assert "x" * 400 not in out


def test_caps_post_count(monkeypatch):
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    many = {"tweets": [
        {"text": f"post {i}", "createdAt": "2026-07-28T00:00:00Z",
         "likeCount": i, "retweetCount": 0, "author": {"userName": f"u{i}"}}
        for i in range(100)
    ]}
    with patch.object(twitter, "_request", return_value=many):
        out = twitter.fetch_twitter_posts("$CATE", limit=5)
    assert out.count("@u") == 5


def test_placeholder_on_http_error(monkeypatch):
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    with patch.object(twitter, "_request", side_effect=OSError("timed out")):
        out = twitter.fetch_twitter_posts("$CATE")
    assert out.startswith("<twitter unavailable: OSError")


def test_placeholder_on_malformed_json(monkeypatch):
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    with patch.object(twitter, "_request", return_value={"unexpected": True}):
        out = twitter.fetch_twitter_posts("$CATE")
    assert out.startswith("<no X/Twitter posts found")


def test_tolerates_alternate_field_names(monkeypatch):
    """The reseller's schema is not contractual, so aliases must be honored."""
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    alt = {"tweets": [{"full_text": "alt shape", "created_at": "2026-07-28",
                       "favorite_count": 9, "retweet_count": 2,
                       "author": {"screen_name": "altuser"}}]}
    with patch.object(twitter, "_request", return_value=alt):
        out = twitter.fetch_twitter_posts("$CATE")
    assert "alt shape" in out
    assert "@altuser" in out
    assert "9 likes" in out


def test_retries_once_when_the_first_response_is_empty(monkeypatch):
    """twitterapi.io intermittently returns an empty list for a query that works."""
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    monkeypatch.setattr(twitter, "_RETRY_SLEEP", 0.0)
    calls = []

    def flaky(params, key, timeout):
        calls.append(params["query"])
        if len(calls) == 1:
            return {"tweets": []}
        return {"tweets": [{"text": "second try", "createdAt": "2026-07-28",
                            "likeCount": 5, "retweetCount": 1,
                            "author": {"userName": "u"}}]}

    with patch.object(twitter, "_request", side_effect=flaky):
        out = twitter.fetch_twitter_posts("$CATE")
    assert len(calls) == 2
    assert "second try" in out


def test_gives_up_after_one_retry(monkeypatch):
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    monkeypatch.setattr(twitter, "_RETRY_SLEEP", 0.0)
    calls = []

    def always_empty(params, key, timeout):
        calls.append(1)
        return {"tweets": []}

    with patch.object(twitter, "_request", side_effect=always_empty):
        out = twitter.fetch_twitter_posts("$CATE")
    assert len(calls) == 2
    assert out.startswith("<no X/Twitter posts found")


def test_does_not_retry_on_a_transport_error(monkeypatch):
    """A network failure is not the empty-response case; one attempt is enough."""
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    monkeypatch.setattr(twitter, "_RETRY_SLEEP", 0.0)
    calls = []

    def boom(params, key, timeout):
        calls.append(1)
        raise OSError("timed out")

    with patch.object(twitter, "_request", side_effect=boom):
        out = twitter.fetch_twitter_posts("$CATE")
    assert len(calls) == 1
    assert out.startswith("<twitter unavailable")


def test_query_includes_cashtag_and_dates(monkeypatch):
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    monkeypatch.setattr(twitter, "_RETRY_SLEEP", 0.0)
    seen = {}

    def capture(params, key, timeout):
        seen.update(params)
        return {"tweets": []}

    with patch.object(twitter, "_request", side_effect=capture):
        twitter.fetch_twitter_posts("$CATE OR Catestein",
                                    start_date="2026-07-22", end_date="2026-07-29")
    assert "$CATE" in seen["query"]
    assert "lang:en" in seen["query"]
    assert "since:2026-07-22" in seen["query"]
    assert "until:2026-07-29" in seen["query"]


def test_query_omits_filter_retweets(monkeypatch):
    """This reseller returns zero results for any query containing that operator."""
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    monkeypatch.setattr(twitter, "_RETRY_SLEEP", 0.0)
    seen = {}

    def capture(params, key, timeout):
        seen.update(params)
        return {"tweets": []}

    with patch.object(twitter, "_request", side_effect=capture):
        twitter.fetch_twitter_posts("$CATE")
    assert "filter:retweets" not in seen["query"]


def test_retweets_are_dropped_client_side(monkeypatch):
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    payload = {"tweets": [
        {"text": "RT @someone: recycled take", "createdAt": "2026-07-28",
         "likeCount": 10, "retweetCount": 3, "author": {"userName": "parrot"}},
        {"text": "quoted wrapper", "createdAt": "2026-07-28", "likeCount": 4,
         "retweetCount": 0, "author": {"userName": "wrapper"},
         "retweeted_tweet": {"text": "original"}},
        {"text": "an original opinion", "createdAt": "2026-07-28", "likeCount": 7,
         "retweetCount": 1, "author": {"userName": "original"}},
    ]}
    with patch.object(twitter, "_request", return_value=payload):
        out = twitter.fetch_twitter_posts("$CATE")
    assert "@original" in out
    assert "@parrot" not in out
    assert "@wrapper" not in out
    assert "1 posts" in out
