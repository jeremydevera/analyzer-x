"""Reply collection and the readable thread layout.

The search endpoint returns top-level posts only, so reply engagement — the
clearest signal that anyone is actually talking about a new coin — was invisible.
A post with 98 replies rendered as a single line with no sign of the conversation.
"""

from unittest.mock import patch

import pytest

from tradingagents.dataflows import twitter

pytestmark = pytest.mark.unit


def _tweet(tid, user, text, likes=0, rts=0, replies=0, created="Wed Jul 29 08:25:57 +0000 2026",
           in_reply_to=None, conversation=None):
    return {"id": tid, "text": text, "createdAt": created, "likeCount": likes,
            "retweetCount": rts, "replyCount": replies,
            "author": {"userName": user},
            "inReplyToId": in_reply_to,
            "conversationId": conversation or tid}


# --- grouping -------------------------------------------------------------


def test_a_fetched_reply_nests_under_its_fetched_parent():
    """The term search returns replies as results too, since they name the coin.

    Rendering them as standalone posts loses the conversation and double-counts
    them; they belong under the post they answer.
    """
    parent = _tweet("1", "Alpha_MEXC", "MEXC listing $XPLK", likes=19)
    child = _tweet("2", "ericgudboy", "trading already?", in_reply_to="1",
                   conversation="1")
    threads, orphans = twitter.group_replies([parent, child], [])
    assert [t["post"]["id"] for t in threads] == ["1"], "the reply is not a post"
    assert [r["id"] for r in threads[0]["replies"]] == ["2"]
    assert orphans == []


def test_counts_reflect_what_is_actually_rendered():
    """A reply already present among the posts must not be counted twice."""
    parent = _tweet("1", "Alpha_MEXC", "listing")
    child = _tweet("2", "ericgudboy", "nice", in_reply_to="1", conversation="1")
    out = twitter.format_thread_block("$XPLK", None, None, [parent, child],
                                      [child], retweets=0)
    summary = out.splitlines()[1]
    assert "1 post" in summary
    assert "1 reply" in summary
    assert out.count("POST · @") == 1
    assert out.count("↳ @ericgudboy") == 1


def test_a_reply_whose_parent_was_not_fetched_is_still_a_reply():
    """It is a reply by nature; presenting it as an original post would mislead."""
    orphan_reply = _tweet("2", "zarsiful", "@xPayLink from Hindustan",
                          in_reply_to="999", conversation="999")
    threads, orphans = twitter.group_replies([orphan_reply], [])
    assert threads == []
    assert [r["id"] for r in orphans] == ["2"]


def test_replies_attach_to_their_parent_post():
    posts = [_tweet("1", "Alpha_MEXC", "MEXC New Listing $XPLK", replies=2)]
    replies = [_tweet("11", "ericgudboy", "@Alpha_MEXC trading already?", in_reply_to="1"),
               _tweet("12", "srkn_ydgr", "@Alpha_MEXC nice", in_reply_to="1")]
    threads, orphans = twitter.group_replies(posts, replies)
    assert [t["post"]["id"] for t in threads] == ["1"]
    assert [r["id"] for r in threads[0]["replies"]] == ["11", "12"]
    assert orphans == []


def test_replies_attach_by_conversation_when_the_parent_id_differs():
    """A reply to a reply still belongs to the thread the post started."""
    posts = [_tweet("1", "Alpha_MEXC", "listing", conversation="1")]
    replies = [_tweet("22", "someone", "deep reply", in_reply_to="11", conversation="1")]
    threads, orphans = twitter.group_replies(posts, replies)
    assert [r["id"] for r in threads[0]["replies"]] == ["22"]
    assert orphans == []


def test_replies_to_unfetched_threads_are_kept_as_orphans():
    """Discarding them would hide engagement on posts the search did not return."""
    posts = [_tweet("1", "Alpha_MEXC", "listing")]
    replies = [_tweet("99", "zarsiful", "@xPayLink from Hindustan",
                      in_reply_to="777", conversation="777")]
    threads, orphans = twitter.group_replies(posts, replies)
    assert threads[0]["replies"] == []
    assert [r["id"] for r in orphans] == ["99"]


def test_a_post_is_never_listed_as_its_own_reply():
    posts = [_tweet("1", "Alpha_MEXC", "listing", conversation="1")]
    threads, orphans = twitter.group_replies(posts, [posts[0]])
    assert threads[0]["replies"] == []
    assert orphans == []


# --- layout ---------------------------------------------------------------


def test_block_leads_with_a_counts_summary():
    posts = [_tweet("1", "Alpha_MEXC", "listing", likes=19, rts=4, replies=12)]
    replies = [_tweet("11", "ericgudboy", "trading already?", in_reply_to="1")]
    out = twitter.format_thread_block("$XPLK", "2026-07-23", "2026-07-30",
                                      posts, replies, retweets=3)
    head = out.splitlines()[0]
    assert "$XPLK" in head
    assert "2026-07-23" in head and "2026-07-30" in head
    summary = out.splitlines()[1]
    assert "1 post" in summary
    assert "1 reply" in summary
    assert "2 authors" in summary          # post author + replier
    assert "3 retweets excluded" in summary


def test_each_post_shows_author_time_and_engagement():
    posts = [_tweet("1", "Alpha_MEXC", "MEXC New Listing", likes=19, rts=4, replies=12)]
    out = twitter.format_thread_block("$XPLK", None, None, posts, [], retweets=0)
    line = next(ln for ln in out.splitlines() if "Alpha_MEXC" in ln)
    assert "POST" in line
    assert "@Alpha_MEXC" in line
    assert "19 likes" in line
    assert "4 RT" in line
    assert "12 replies" in line
    # THE date format, not the raw X stamp and not a short one either
    import datetime as _dt

    from tradingagents.positions_view import fmt_when

    want = fmt_when(_dt.datetime.strptime("Wed Jul 29 08:25:57 +0000 2026",
                                          "%a %b %d %H:%M:%S %z %Y").timestamp())
    assert want in line, f"{want!r} not in {line!r}"


def test_replies_are_indented_under_their_post():
    posts = [_tweet("1", "Alpha_MEXC", "listing", replies=1)]
    replies = [_tweet("11", "ericgudboy", "trading already?", likes=2, in_reply_to="1")]
    out = twitter.format_thread_block("$XPLK", None, None, posts, replies, retweets=0)
    reply_line = next(ln for ln in out.splitlines() if "ericgudboy" in ln)
    assert reply_line.startswith("    ↳")
    assert "2 likes" in reply_line


def test_orphan_replies_get_their_own_section():
    posts = [_tweet("1", "Alpha_MEXC", "listing")]
    replies = [_tweet("99", "zarsiful", "from Hindustan", in_reply_to="777",
                      conversation="777")]
    out = twitter.format_thread_block("$XPLK", None, None, posts, replies, retweets=0)
    assert "OTHER REPLIES" in out
    assert "zarsiful" in out


def test_posts_are_ordered_by_engagement():
    posts = [_tweet("1", "quiet", "nobody cares", likes=0),
             _tweet("2", "loud", "everyone cares", likes=99)]
    out = twitter.format_thread_block("$X", None, None, posts, [], retweets=0)
    assert out.index("@loud") < out.index("@quiet")


def test_long_bodies_are_truncated_but_readable():
    posts = [_tweet("1", "a", "x" * 500)]
    out = twitter.format_thread_block("$X", None, None, posts, [], retweets=0)
    assert "…" in out
    assert "x" * 500 not in out


def test_newlines_inside_a_post_do_not_break_the_layout():
    posts = [_tweet("1", "a", "line one\nline two\nline three")]
    out = twitter.format_thread_block("$X", None, None, posts, [], retweets=0)
    body_lines = [ln for ln in out.splitlines() if "line one" in ln]
    assert len(body_lines) == 1
    assert "line two" in body_lines[0]


# --- per-post reply threads -----------------------------------------------


def test_thread_replies_hit_the_replies_endpoint(monkeypatch):
    """A reply to a post rarely names the coin, so term search cannot find it."""
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    seen = []

    def fake_get(url, key, timeout):
        seen.append(url)
        return {"tweets": [_tweet("11", "fan", "great project")],
                "has_next_page": False}

    with patch.object(twitter, "_get_json", side_effect=fake_get):
        out = twitter.fetch_replies("1", "k", 10.0, limit=20)
    assert any("tweet/replies" in u and "tweetId=1" in u for u in seen)
    assert [r["id"] for r in out] == ["11"]


def test_thread_replies_are_reparented_to_the_post_they_belong_to(monkeypatch):
    """The endpoint returns nested replies whose inReplyToId points mid-thread."""
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    posts = [_tweet("1", "MrHodlReal", "cabal call", replies=19)]
    nested = _tweet("55", "someone", "deep in the thread", in_reply_to="33")

    with patch.object(twitter, "fetch_replies", return_value=[nested]):
        collected = twitter.collect_thread_replies(posts, "k", 10.0, threads=3, limit=20)
    assert collected[0]["inReplyToId"] == "1"


def test_only_the_busiest_threads_are_fetched(monkeypatch):
    """Each thread page is billed, so the walk is bounded by reply volume."""
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    posts = [_tweet(str(i), f"u{i}", "post", replies=i) for i in range(1, 8)]
    asked = []

    def fake_fetch(tweet_id, key, timeout, limit):
        asked.append(tweet_id)
        return []

    with patch.object(twitter, "fetch_replies", side_effect=fake_fetch):
        twitter.collect_thread_replies(posts, "k", 10.0, threads=3, limit=20)
    assert asked == ["7", "6", "5"], "busiest threads first, capped at three"


def test_posts_without_replies_are_not_fetched(monkeypatch):
    posts = [_tweet("1", "a", "quiet post", replies=0)]
    asked = []

    def fake_fetch(tweet_id, key, timeout, limit):
        asked.append(tweet_id)
        return []

    with patch.object(twitter, "fetch_replies", side_effect=fake_fetch):
        twitter.collect_thread_replies(posts, "k", 10.0, threads=3, limit=20)
    assert asked == []


def test_one_failed_thread_does_not_lose_the_others(monkeypatch):
    posts = [_tweet("1", "a", "p", replies=5), _tweet("2", "b", "p", replies=4)]

    def flaky(tweet_id, key, timeout, limit):
        if tweet_id == "1":
            raise TimeoutError("stalled")
        return [_tweet("22", "fan", "nice", in_reply_to="2")]

    with patch.object(twitter, "fetch_replies", side_effect=flaky):
        collected = twitter.collect_thread_replies(posts, "k", 10.0, threads=3, limit=20)
    assert [r["id"] for r in collected] == ["22"]


def test_thread_replies_nest_under_their_post_end_to_end(monkeypatch):
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    monkeypatch.setattr(twitter, "_RETRY_SLEEP", 0.0)

    def fake_request(params, key, timeout):
        if "filter:replies" in params["query"]:
            return {"tweets": [], "has_next_page": False}
        return {"tweets": [_tweet("1", "MrHodlReal", "cabal call $PIPEDOG", replies=19)],
                "has_next_page": False}

    thread_reply = _tweet("11", "MasterMinion2", "Another scam coin obviously.",
                          in_reply_to="1")
    with patch.object(twitter, "_request", side_effect=fake_request), \
         patch.object(twitter, "fetch_replies", return_value=[thread_reply]):
        out = twitter.fetch_twitter_posts("$PIPEDOG")

    lines = out.splitlines()
    post_at = next(i for i, ln in enumerate(lines) if "POST · @MrHodlReal" in ln)
    reply_at = next(i for i, ln in enumerate(lines) if "MasterMinion2" in ln)
    assert reply_at > post_at
    assert lines[reply_at].startswith("    ↳")
    assert "OTHER REPLIES" not in out


# --- end to end through the fetcher ---------------------------------------


def test_fetcher_runs_a_second_search_for_replies(monkeypatch):
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    monkeypatch.setattr(twitter, "_RETRY_SLEEP", 0.0)
    queries = []

    def fake(params, key, timeout):
        queries.append(params["query"])
        if "filter:replies" in params["query"]:
            return {"tweets": [_tweet("11", "ericgudboy", "engaging!", in_reply_to="1")],
                    "has_next_page": False}
        return {"tweets": [_tweet("1", "Alpha_MEXC", "listing", replies=1)],
                "has_next_page": False}

    # fetch_replies() goes through _get_json, not _request, so the dedicated
    # replies endpoint was reached over the live network and its failure silently
    # swallowed by the per-thread handler. The search path below is what this test
    # is really about.
    with patch.object(twitter, "_request", side_effect=fake), \
            patch.object(twitter, "_get_json", return_value={"tweets": []}):
        out = twitter.fetch_twitter_posts("$XPLK")

    assert any("filter:replies" in q for q in queries), "replies must be searched"
    assert "ericgudboy" in out
    assert "1 reply" in out


def test_replies_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    monkeypatch.setattr(twitter, "_RETRY_SLEEP", 0.0)
    queries = []

    def fake(params, key, timeout):
        queries.append(params["query"])
        return {"tweets": [_tweet("1", "a", "post")], "has_next_page": False}

    with patch.object(twitter, "_request", side_effect=fake):
        twitter.fetch_twitter_posts("$XPLK", include_replies=False)
    assert not any("filter:replies" in q for q in queries)


def test_a_failed_reply_search_does_not_lose_the_posts(monkeypatch):
    """Replies are a bonus; losing them must not blank the whole source."""
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    monkeypatch.setattr(twitter, "_RETRY_SLEEP", 0.0)

    def fake(params, key, timeout):
        if "filter:replies" in params["query"]:
            raise TimeoutError("read timed out")
        return {"tweets": [_tweet("1", "Alpha_MEXC", "listing")], "has_next_page": False}

    with patch.object(twitter, "_request", side_effect=fake):
        out = twitter.fetch_twitter_posts("$XPLK")
    assert "Alpha_MEXC" in out
    assert "0 replies" in out or "1 post" in out
