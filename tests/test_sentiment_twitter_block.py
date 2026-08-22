"""The Twitter block reaches the sentiment prompt only when configured on."""

import pytest

from tradingagents.agents.analysts import sentiment_analyst as sa

pytestmark = pytest.mark.unit


def _kwargs(**over):
    base = {"ticker": "CATE-USD", "start_date": "2026-07-22", "end_date": "2026-07-29",
                "news_block": "NEWS", "stocktwits_block": "TWITS", "reddit_block": "REDDIT"}
    base.update(over)
    return base


# --- StockTwits symbol mapping and gating ---------------------------------


@pytest.mark.parametrize("ticker,asset_type,expected", [
    ("AEONUSDT", "crypto", "AEON.X"),     # MEXC pair -> StockTwits crypto symbol
    ("CATE-USD", "crypto", "CATE.X"),
    ("BTCUSDT", "crypto", "BTC.X"),
    ("btcusdt", "crypto", "BTC.X"),
    ("NVDA", "stock", "NVDA"),            # equities keep the plain ticker
    ("BRK.B", "stock", "BRK.B"),
])
def test_stocktwits_symbol_uses_the_crypto_suffix(ticker, asset_type, expected):
    """StockTwits indexes crypto as BASE.X; the exchange pair returns 404."""
    assert sa._stocktwits_symbol(ticker, asset_type) == expected


def test_stocktwits_block_is_skipped_when_disabled(monkeypatch):
    called = []
    monkeypatch.setattr(sa, "fetch_stocktwits_messages",
                        lambda *a, **k: called.append(1) or "TWITS")
    monkeypatch.setattr(sa, "get_config", lambda: {"include_stocktwits": False})
    assert sa._maybe_stocktwits_block("AEONUSDT", "crypto") == ""
    assert called == []


def test_stocktwits_block_runs_when_enabled_with_mapped_symbol(monkeypatch):
    seen = {}

    def capture(symbol, **kw):
        seen["symbol"] = symbol
        return "TWITS"

    monkeypatch.setattr(sa, "fetch_stocktwits_messages", capture)
    monkeypatch.setattr(sa, "get_config", lambda: {"include_stocktwits": True})
    assert sa._maybe_stocktwits_block("AEONUSDT", "crypto") == "TWITS"
    assert seen["symbol"] == "AEON.X"


def test_stocktwits_defaults_on_for_stock_runs(monkeypatch):
    """Omitting the flag must not silently disable a source stocks already had."""
    monkeypatch.setattr(sa, "fetch_stocktwits_messages", lambda *a, **k: "TWITS")
    monkeypatch.setattr(sa, "get_config", lambda: {})
    assert sa._maybe_stocktwits_block("NVDA", "stock") == "TWITS"


# --- Prompt assembly with a variable number of sources --------------------


def test_sentiment_sources_are_exposed_in_state(monkeypatch):
    """The UI must be able to show exactly the raw data the model read."""
    from tradingagents.agents.utils import agent_states
    assert "sentiment_sources" in agent_states.AgentState.__annotations__


def test_collected_sources_carry_every_fetched_block():
    sources = sa.collect_sentiment_sources(news_block="NEWS", stocktwits_block="TWITS",
                                           reddit_block="REDDIT", twitter_block="TWEETS")
    assert sources == {"news": "NEWS", "stocktwits": "TWITS",
                       "reddit": "REDDIT", "twitter": "TWEETS"}


def test_collected_sources_omit_disabled_blocks():
    sources = sa.collect_sentiment_sources(news_block="NEWS", stocktwits_block="",
                                           reddit_block="REDDIT", twitter_block="")
    assert sources == {"news": "NEWS", "reddit": "REDDIT"}
    assert "stocktwits" not in sources


def test_prompt_omits_stocktwits_section_when_disabled():
    msg = sa._build_system_message(**_kwargs(stocktwits_block=""))
    assert "start_of_stocktwits" not in msg
    assert "NEWS" in msg and "REDDIT" in msg


def test_prompt_counts_only_the_sources_present():
    two = sa._build_system_message(**_kwargs(stocktwits_block=""))
    assert "two complementary data sources" in two

    three = sa._build_system_message(**_kwargs())
    assert "three complementary data sources" in three

    four = sa._build_system_message(**_kwargs(twitter_block="TWEETS"))
    assert "four complementary data sources" in four

    twitter_only = sa._build_system_message(**_kwargs(stocktwits_block="",
                                                      twitter_block="TWEETS"))
    assert "three complementary data sources" in twitter_only


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
    assert seen["terms"] == "$CATE"
    assert seen["start_date"] == "2026-07-22"
    assert seen["end_date"] == "2026-07-29"


def test_query_includes_the_configured_display_name(monkeypatch):
    """The screener knows the project name; the cashtag alone finds far less."""
    seen = {}
    monkeypatch.setattr(sa, "fetch_twitter_posts",
                        lambda terms, **kw: seen.setdefault("terms", terms) or "T")
    monkeypatch.setattr(sa, "get_config",
                        lambda: {"include_twitter": True,
                                 "asset_display_name": "xPayLink"})
    sa._maybe_twitter_block("XPLKUSDT", "2026-07-23", "2026-07-30")
    assert seen["terms"] == '$XPLK OR "xPayLink"'


def test_query_falls_back_to_the_cashtag_without_a_name(monkeypatch):
    seen = {}
    monkeypatch.setattr(sa, "fetch_twitter_posts",
                        lambda terms, **kw: seen.setdefault("terms", terms) or "T")
    monkeypatch.setattr(sa, "get_config", lambda: {"include_twitter": True})
    sa._maybe_twitter_block("XPLKUSDT", "2026-07-23", "2026-07-30")
    assert seen["terms"] == "$XPLK"


def test_query_omits_the_bare_symbol(monkeypatch):
    """The bare term matches unrelated chatter sharing the ticker's letters."""
    seen = {}
    monkeypatch.setattr(sa, "fetch_twitter_posts",
                        lambda terms, **kw: seen.setdefault("terms", terms) or "T")
    monkeypatch.setattr(sa, "get_config", lambda: {"include_twitter": True})
    sa._maybe_twitter_block("AEONUSDT", "2026-07-22", "2026-07-29")
    assert seen["terms"] == "$AEON"
    assert " OR " not in seen["terms"]


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
