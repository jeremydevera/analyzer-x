"""Unit tests for the Twitter/X sentiment fetcher (no network)."""

import json
from datetime import datetime
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
    # The recording carries has_next_page; present it as the only page so this
    # test covers formatting rather than the cursor walk.
    payload = {**payload, "has_next_page": False}
    with patch.object(twitter, "_request", return_value=payload):
        out = twitter.fetch_twitter_posts("$BTC", start_date="2026-07-22",
                                          end_date="2026-07-29", include_replies=False)
    assert "X/Twitter" in out
    assert "<twitter unavailable" not in out
    # Every recorded post's handle and like count must survive, and its raw X
    # timestamp must be rendered in the readable short form.
    for tweet in payload["tweets"]:
        assert f"@{tweet['author']['userName']}" in out
        assert f"{tweet['likeCount']} likes" in out
        # THE date format applies here too — a tweet's time is a time on
        # screen, and it used to print as "Jul 29 12:45" with no year
        from tradingagents.positions_view import fmt_when

        short = fmt_when(datetime.strptime(
            tweet["createdAt"], "%a %b %d %H:%M:%S %z %Y").timestamp())
        assert short in out
    # One POST header per recorded post: a body newline must not split a post.
    assert out.count("POST · @") == len(payload["tweets"])


def test_truncates_long_bodies(monkeypatch):
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    long_body = {"tweets": [{"text": "x" * 400, "createdAt": "2026-07-28T00:00:00Z",
                             "likeCount": 1, "retweetCount": 0,
                             "author": {"userName": "u"}}]}
    with patch.object(twitter, "_request", return_value=long_body):
        out = twitter.fetch_twitter_posts("$CATE", include_replies=False)
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
        out = twitter.fetch_twitter_posts("$CATE", limit=5, include_replies=False)
    assert out.count("POST · @u") == 5


def test_placeholder_on_http_error(monkeypatch):
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    with patch.object(twitter, "_request", side_effect=OSError("timed out")):
        out = twitter.fetch_twitter_posts("$CATE", include_replies=False)
    assert out.startswith("<twitter unavailable: OSError")


def test_placeholder_on_malformed_json(monkeypatch):
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    with patch.object(twitter, "_request", return_value={"unexpected": True}):
        out = twitter.fetch_twitter_posts("$CATE", include_replies=False)
    assert out.startswith("<no X/Twitter posts found")


def test_tolerates_alternate_field_names(monkeypatch):
    """The reseller's schema is not contractual, so aliases must be honored."""
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    alt = {"tweets": [{"full_text": "alt shape", "created_at": "2026-07-28",
                       "favorite_count": 9, "retweet_count": 2,
                       "author": {"screen_name": "altuser"}}]}
    with patch.object(twitter, "_request", return_value=alt):
        out = twitter.fetch_twitter_posts("$CATE", include_replies=False)
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
        out = twitter.fetch_twitter_posts("$CATE", include_replies=False)
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
        out = twitter.fetch_twitter_posts("$CATE", include_replies=False)
    assert len(calls) == 2
    assert out.startswith("<no X/Twitter posts found")


def test_retries_a_transport_error_then_succeeds(monkeypatch):
    """A single stalled request must not lose the source.

    Measured latency for the analyst's query is 1.5-1.9s, so a timeout is a blip,
    not a signal that the endpoint is down.
    """
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    monkeypatch.setattr(twitter, "_RETRY_SLEEP", 0.0)
    calls = []

    def flaky(params, key, timeout):
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError("The read operation timed out")
        return {"tweets": [{"text": "recovered", "createdAt": "2026-07-30",
                            "likeCount": 1, "retweetCount": 0,
                            "author": {"userName": "u"}}]}

    with patch.object(twitter, "_request", side_effect=flaky):
        out = twitter.fetch_twitter_posts("$XPLK", include_replies=False)
    assert len(calls) == 2
    assert "recovered" in out


def test_recovers_when_two_stalls_precede_a_success(monkeypatch):
    """Broad user-keyword queries stall more often — two blips must not lose
    the source."""
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    monkeypatch.setattr(twitter, "_RETRY_SLEEP", 0.0)
    calls = []

    def flaky(params, key, timeout):
        calls.append(1)
        if len(calls) <= 2:
            raise TimeoutError("The read operation timed out")
        return {"tweets": [{"text": "third time lucky", "createdAt": "2026-07-31",
                            "likeCount": 1, "retweetCount": 0,
                            "author": {"userName": "u"}}]}

    with patch.object(twitter, "_request", side_effect=flaky):
        out = twitter.fetch_twitter_posts("$XPLK", include_replies=False)
    assert len(calls) == 3
    assert "third time lucky" in out


def test_reports_unavailable_only_after_all_retries_fail(monkeypatch):
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    monkeypatch.setattr(twitter, "_RETRY_SLEEP", 0.0)
    calls = []

    def always_timeout(params, key, timeout):
        calls.append(1)
        raise TimeoutError("The read operation timed out")

    with patch.object(twitter, "_request", side_effect=always_timeout):
        out = twitter.fetch_twitter_posts("$XPLK", include_replies=False)
    assert len(calls) == 3
    assert out.startswith("<twitter unavailable")
    assert "TimeoutError" in out


def test_timeout_allows_for_a_slow_endpoint(monkeypatch):
    """15s was tight enough that one stall killed the source."""
    assert twitter._TIMEOUT >= 30


# --- pagination -----------------------------------------------------------


def _page(n, start=0, more=False, cursor="c1"):
    return {"tweets": [{"text": f"post {start + i}", "createdAt": "2026-07-30",
                        "likeCount": 1, "retweetCount": 0,
                        "author": {"userName": f"u{start + i}"}} for i in range(n)],
            "has_next_page": more, "next_cursor": cursor}


def test_follows_the_cursor_until_the_limit_is_reached(monkeypatch):
    """One page caps at 20; the limit is 30, so a second page is required."""
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    monkeypatch.setattr(twitter, "_RETRY_SLEEP", 0.0)
    seen = []

    def paged(params, key, timeout):
        seen.append(params.get("cursor"))
        return _page(20, more=True) if len(seen) == 1 else _page(20, start=20)

    with patch.object(twitter, "_request", side_effect=paged):
        out = twitter.fetch_twitter_posts("$XPLK", limit=30, include_replies=False)
    assert seen == [None, "c1"], "second call must carry the cursor"
    assert out.count("POST · @u") == 30


def test_stops_when_the_endpoint_reports_no_more_pages(monkeypatch):
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    monkeypatch.setattr(twitter, "_RETRY_SLEEP", 0.0)
    calls = []

    def one_page(params, key, timeout):
        calls.append(1)
        return _page(4, more=False)

    with patch.object(twitter, "_request", side_effect=one_page):
        out = twitter.fetch_twitter_posts("$XPLK", limit=30, include_replies=False)
    assert len(calls) == 1
    assert out.count("POST · @u") == 4


def test_page_count_is_bounded_even_if_the_cursor_never_ends(monkeypatch):
    """Each page is billed, so a runaway cursor must not spend without limit."""
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    monkeypatch.setattr(twitter, "_RETRY_SLEEP", 0.0)
    calls = []

    def endless(params, key, timeout):
        calls.append(1)
        return _page(1, start=len(calls), more=True)

    with patch.object(twitter, "_request", side_effect=endless):
        twitter.fetch_twitter_posts("$XPLK", limit=30, include_replies=False)
    assert len(calls) <= twitter.MAX_PAGES


# --- query terms ----------------------------------------------------------


@pytest.mark.parametrize("symbol,name,expected", [
    # A distinctive project name is what people actually write.
    ("XPLK", "xPayLink", '$XPLK OR "xPayLink"'),
    ("PIPEDOG", "pipedog", '$PIPEDOG'),          # name repeats the symbol
    ("AEON", "AEON", "$AEON"),                   # ditto, and $AEON alone is noisy
    ("CATE", "Catecoin", '$CATE OR "Catecoin"'),
    ("XPLK", "", "$XPLK"),
    ("XPLK", None, "$XPLK"),
    ("SPCXX", "SpaceX xStocks", '$SPCXX OR "SpaceX xStocks"'),
])
def test_search_terms_add_a_distinctive_name(symbol, name, expected):
    assert twitter.search_terms(symbol, name) == expected


def test_search_terms_ignores_a_name_that_merely_extends_the_symbol():
    """"XPLK Token" adds nothing the cashtag does not already match."""
    assert twitter.search_terms("XPLK", "XPLK Token") == "$XPLK"


def test_credit_balance_parses_both_buckets(monkeypatch):
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    payload = {"recharge_credits": 12_000, "total_bonus_credits": 280}
    with patch.object(twitter, "_get_json", return_value=payload):
        bal = twitter.fetch_credit_balance()
    assert bal["ok"] is True
    assert bal["recharge"] == 12_000
    assert bal["bonus"] == 280
    assert bal["total"] == 12_280
    assert bal["error"] == ""


def test_credit_balance_without_a_key(monkeypatch):
    monkeypatch.delenv("TWITTERAPI_IO_KEY", raising=False)
    bal = twitter.fetch_credit_balance()
    assert bal["ok"] is False
    assert bal["total"] == 0
    assert "TWITTERAPI_IO_KEY" in bal["error"]


def test_credit_balance_survives_a_transport_error(monkeypatch):
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    with patch.object(twitter, "_get_json", side_effect=OSError("boom")):
        bal = twitter.fetch_credit_balance()
    assert bal["ok"] is False
    assert bal["total"] == 0
    assert "OSError" in bal["error"]


def test_credit_balance_survives_an_unexpected_shape(monkeypatch):
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    with patch.object(twitter, "_get_json", return_value=["nope"]):
        bal = twitter.fetch_credit_balance()
    assert bal["ok"] is False


def test_credit_balance_treats_missing_buckets_as_zero(monkeypatch):
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    with patch.object(twitter, "_get_json", return_value={}):
        bal = twitter.fetch_credit_balance()
    assert bal["ok"] is True
    assert bal["total"] == 0


def test_pricing_constants_match_the_published_rates():
    """1 USD = 100,000 credits, 15 credits per returned tweet."""
    assert twitter.CREDITS_PER_USD == 100_000
    assert twitter.CREDITS_PER_TWEET == 15
    assert twitter.CREDITS_PER_RUN == 15 * twitter.TWEETS_PER_PAGE


def test_query_includes_cashtag_and_dates(monkeypatch):
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    monkeypatch.setattr(twitter, "_RETRY_SLEEP", 0.0)
    seen = {}

    def capture(params, key, timeout):
        seen.update(params)
        return {"tweets": []}

    with patch.object(twitter, "_request", side_effect=capture):
        twitter.fetch_twitter_posts("$CATE OR Catestein",
                                    start_date="2026-07-22", end_date="2026-07-29", include_replies=False)
    assert "$CATE" in seen["query"]
    assert "since:2026-07-22" in seen["query"]
    assert "until:2026-07-29" in seen["query"]
    # No language filter: it excluded most of a new listing's audience.
    assert "lang:" not in seen["query"]


def test_query_omits_filter_retweets(monkeypatch):
    """This reseller returns zero results for any query containing that operator."""
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    monkeypatch.setattr(twitter, "_RETRY_SLEEP", 0.0)
    seen = {}

    def capture(params, key, timeout):
        seen.update(params)
        return {"tweets": []}

    with patch.object(twitter, "_request", side_effect=capture):
        twitter.fetch_twitter_posts("$CATE", include_replies=False)
    assert "filter:retweets" not in seen["query"]


def test_header_reports_how_many_retweets_were_excluded(monkeypatch):
    """Retweet volume is attention even though it carries no original opinion."""
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    payload = {"tweets": [
        {"text": "RT @a: echo", "createdAt": "2026-07-30", "likeCount": 1,
         "retweetCount": 0, "author": {"userName": "parrot"}},
        {"text": "original", "createdAt": "2026-07-30", "likeCount": 2,
         "retweetCount": 0, "author": {"userName": "author"}},
    ], "has_next_page": False}
    with patch.object(twitter, "_request", return_value=payload):
        out = twitter.fetch_twitter_posts("$XPLK", include_replies=False)
    assert "1 post" in out
    assert "1 retweet excluded" in out


def test_header_omits_the_retweet_note_when_there_were_none(monkeypatch):
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    payload = {"tweets": [{"text": "original", "createdAt": "2026-07-30",
                           "likeCount": 2, "retweetCount": 0,
                           "author": {"userName": "author"}}],
               "has_next_page": False}
    with patch.object(twitter, "_request", return_value=payload):
        out = twitter.fetch_twitter_posts("$XPLK", include_replies=False)
    assert "retweet" not in out.split("\n")[0]


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
        out = twitter.fetch_twitter_posts("$CATE", include_replies=False)
    assert "@original" in out
    assert "@parrot" not in out
    assert "@wrapper" not in out
    assert "1 post" in out


def test_search_terms_appends_extra_keywords():
    from tradingagents.dataflows.twitter import search_terms
    out = search_terms("XPLK", "xPayLink", extra_terms=["airdrop", "listing pump"])
    assert out == '$XPLK OR "xPayLink" OR airdrop OR "listing pump"'


def test_search_terms_extra_keywords_dedupe_and_blank():
    from tradingagents.dataflows.twitter import search_terms
    out = search_terms("XPLK", None, extra_terms=["", "  ", "$xplk", "moon"])
    assert out == "$XPLK OR moon"
