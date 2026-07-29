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
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    with patch.object(twitter, "_request", return_value=payload):
        out = twitter.fetch_twitter_posts("$CATE", start_date="2026-07-22",
                                          end_date="2026-07-29")
    assert "X/Twitter posts" in out
    assert "@chainwatcher" in out
    assert "412 likes" in out
    assert "<twitter unavailable" not in out


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


def test_query_includes_cashtag_dates_and_excludes_retweets(monkeypatch):
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    seen = {}

    def capture(params, key, timeout):
        seen.update(params)
        return {"tweets": []}

    with patch.object(twitter, "_request", side_effect=capture):
        twitter.fetch_twitter_posts("$CATE OR Catestein",
                                    start_date="2026-07-22", end_date="2026-07-29")
    assert "$CATE" in seen["query"]
    assert "since:2026-07-22" in seen["query"]
    assert "until:2026-07-29" in seen["query"]
    assert "-filter:retweets" in seen["query"]
