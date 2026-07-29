"""The Twitter block reaches the sentiment prompt only when configured on."""

import pytest

from tradingagents.agents.analysts import sentiment_analyst as sa

pytestmark = pytest.mark.unit


def _kwargs(**over):
    base = dict(ticker="CATE-USD", start_date="2026-07-22", end_date="2026-07-29",
                news_block="NEWS", stocktwits_block="TWITS", reddit_block="REDDIT")
    base.update(over)
    return base


def test_prompt_omits_twitter_section_when_block_is_empty():
    msg = sa._build_system_message(**_kwargs(twitter_block=""))
    assert "start_of_twitter" not in msg
    assert "three complementary data sources" in msg
    assert "REDDIT" in msg


def test_prompt_includes_twitter_section_when_block_present():
    msg = sa._build_system_message(**_kwargs(twitter_block="TWEETS"))
    assert "<start_of_twitter>" in msg
    assert "TWEETS" in msg
    assert "four complementary data sources" in msg


def test_twitter_block_is_optional_for_existing_callers():
    """Omitting the kwarg entirely must still build a valid three-source prompt."""
    msg = sa._build_system_message(**_kwargs())
    assert "start_of_twitter" not in msg
    assert "three complementary data sources" in msg


def test_fetch_is_skipped_when_include_twitter_is_off(monkeypatch):
    called = []
    monkeypatch.setattr(sa, "fetch_twitter_posts",
                        lambda *a, **k: called.append(1) or "TWEETS")
    monkeypatch.setattr(sa, "get_config", lambda: {"include_twitter": False})
    assert sa._maybe_twitter_block("CATE-USD", "2026-07-22", "2026-07-29") == ""
    assert called == []


def test_fetch_runs_when_include_twitter_is_on(monkeypatch):
    monkeypatch.setattr(sa, "fetch_twitter_posts", lambda *a, **k: "TWEETS")
    monkeypatch.setattr(sa, "get_config", lambda: {"include_twitter": True})
    assert sa._maybe_twitter_block("CATE-USD", "2026-07-22", "2026-07-29") == "TWEETS"


def test_query_uses_the_base_asset_as_a_cashtag(monkeypatch):
    seen = {}

    def capture(terms, **kw):
        seen["terms"] = terms
        seen.update(kw)
        return "TWEETS"

    monkeypatch.setattr(sa, "fetch_twitter_posts", capture)
    monkeypatch.setattr(sa, "get_config", lambda: {"include_twitter": True})
    sa._maybe_twitter_block("CATE-USD", "2026-07-22", "2026-07-29")
    assert "$CATE" in seen["terms"]
    assert seen["start_date"] == "2026-07-22"
    assert seen["end_date"] == "2026-07-29"


@pytest.mark.parametrize("ticker,expected", [
    ("AEONUSDT", "AEON"),     # MEXC pair form
    ("CATE-USD", "CATE"),     # app/Yahoo form
    ("CATEUSDC", "CATE"),
    ("NVDA", "NVDA"),         # equities untouched
    ("nvda", "NVDA"),
    ("USDT", "USDT"),         # never strip a symbol down to nothing
])
def test_cashtag_strips_the_quote_currency(ticker, expected):
    """Traders write $AEON, not $AEONUSDT, so the pair suffix must go."""
    assert sa._cashtag(ticker) == expected


def test_unavailable_source_is_reported_not_hidden(monkeypatch):
    """The placeholder reaches the prompt so the model says 'unavailable'."""
    monkeypatch.setattr(sa, "fetch_twitter_posts",
                        lambda *a, **k: "<twitter unavailable: TWITTERAPI_IO_KEY not set>")
    monkeypatch.setattr(sa, "get_config", lambda: {"include_twitter": True})
    out = sa._maybe_twitter_block("CATE-USD", "2026-07-22", "2026-07-29")
    assert out.startswith("<twitter unavailable")
