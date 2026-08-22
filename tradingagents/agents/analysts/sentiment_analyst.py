"""Sentiment analyst — multi-source sentiment analysis for a target ticker.

Previously named ``social_media_analyst``. Renamed and redesigned because
the old version had a prompt that demanded social-media analysis but the
only tool available was Yahoo Finance news — which led LLMs to fabricate
Reddit/X/StockTwits content under prompt pressure (verified live).

The redesigned agent pre-fetches three complementary data sources before
the LLM is invoked and injects them into the prompt as structured blocks:

  1. News headlines     — Yahoo Finance (institutional framing)
  2. StockTwits messages — retail-trader posts indexed by cashtag, with
                           user-labeled Bullish/Bearish sentiment tags
  3. Reddit posts        — r/wallstreetbets, r/stocks, r/investing

The agent does not use tool-calling; the data is in the prompt from
turn 0. Output uses the structured-output pattern (json_schema for
OpenAI/xAI, response_schema for Gemini, tool-use for Anthropic), falling
back to free-text generation for providers that lack native support, so
the sentiment header (band + score + confidence) is deterministic across
runs and providers instead of free-form per-model prose.

See: https://github.com/TauricResearch/TradingAgents/issues/557
See: https://github.com/TauricResearch/TradingAgents/issues/796
"""

from datetime import datetime, timedelta

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.schemas import SentimentReport, render_sentiment_report
from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
    get_news,
)
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)
from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.reddit import fetch_reddit_posts
from tradingagents.dataflows.stocktwits import fetch_stocktwits_messages
from tradingagents.dataflows.twitter import fetch_twitter_posts, search_terms

_COUNT_WORDS = {2: "two", 3: "three", 4: "four"}


def collect_sentiment_sources(*, news_block: str, stocktwits_block: str,
                              reddit_block: str, twitter_block: str) -> dict:
    """The raw blocks that went into the prompt, keyed by source.

    Returned in state so a UI can show the actual posts the model read instead of
    only its narrative about them — the difference between "17 bullish messages"
    being checkable and being taken on faith. Disabled sources are omitted so a
    reader never sees an empty panel for a source that was switched off.
    """
    blocks = {"news": news_block, "stocktwits": stocktwits_block,
              "reddit": reddit_block, "twitter": twitter_block}
    return {name: block for name, block in blocks.items() if block}


def _seven_days_back(trade_date: str) -> str:
    return (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")


def _maybe_twitter_block(ticker: str, start_date: str, end_date: str) -> str:
    """Fetch X posts when enabled, else return "" so the prompt omits the section.

    Gated on config rather than on key presence because the fetch is metered: a
    stock run should not spend X credits unless the user opted in. When enabled
    but unavailable, the fetcher's placeholder is passed through so the report
    says the source was missing instead of quietly dropping it.
    """
    config = get_config()
    if not config.get("include_twitter"):
        return ""
    # Cashtag plus the project name when one is configured. The bare *symbol* is
    # never used — on $AEON it dragged in anime fandom posts — but the quoted
    # *name* is what people actually write: $XPLK alone returned 4 posts where
    # '$XPLK OR "xPayLink"' returned 17.
    terms = search_terms(_cashtag(ticker), config.get("asset_display_name"),
                         extra_terms=config.get("twitter_extra_terms"))
    return fetch_twitter_posts(
        terms,
        start_date=twitter_window_start(start_date, config.get("asset_listed_date")),
        end_date=end_date,
        sort=twitter_sort(config.get("asset_age_hours")),
    )


# Pre-listing hype window. A coin listed today was being talked about before it
# traded ("will be listed July 29"), and that anticipation is real signal, while
# the days before it existed are not.
_PRE_LISTING_DAYS = 2
# Below this age the live reaction matters more than engagement ranking, which
# would surface the exchange's announcement post above everything else.
_FRESH_LISTING_HOURS = 24


def twitter_window_start(default_start: str, listed_date: str | None) -> str:
    """Search-window start: shortly before listing, or the caller's default.

    Never widens the window — an old coin must not drag the search back weeks —
    and never narrows past the listing, so pre-listing chatter is still caught.
    """
    if not listed_date:
        return default_start
    try:
        listed = datetime.strptime(listed_date, "%Y-%m-%d")
    except (TypeError, ValueError):
        return default_start
    candidate = (listed - timedelta(days=_PRE_LISTING_DAYS)).strftime("%Y-%m-%d")
    return max(candidate, default_start)


def twitter_sort(age_hours: float | None) -> str:
    """"Latest" for a coin still reacting, "Top" once engagement means something."""
    try:
        return "Latest" if float(age_hours) < _FRESH_LISTING_HOURS else "Top"
    except (TypeError, ValueError):
        return "Top"


def _stocktwits_symbol(ticker: str, asset_type: str) -> str:
    """Symbol StockTwits indexes this instrument under.

    StockTwits files crypto as ``BASE.X`` (``AEON.X``), not as an exchange pair:
    querying ``AEONUSDT`` returns 404 while ``AEON.X`` returns a full stream of
    sentiment-tagged messages. Equities keep their plain ticker.
    """
    if asset_type != "crypto":
        return ticker.strip().upper()
    return f"{_cashtag(ticker)}.X"


def _maybe_stocktwits_block(ticker: str, asset_type: str) -> str:
    """Fetch StockTwits messages unless the source is switched off.

    Defaults to enabled: it is keyless and free, and stock runs have always had
    it, so an absent flag must not silently drop a source.
    """
    if not get_config().get("include_stocktwits", True):
        return ""
    return fetch_stocktwits_messages(_stocktwits_symbol(ticker, asset_type), limit=30)


def _cashtag(ticker: str) -> str:
    """Reduce a ticker to the symbol people actually post about.

    Crypto arrives as an exchange pair (``AEONUSDT``, ``CATE-USD``), but traders
    write ``$AEON`` far more often than ``$AEONUSDT``, so the quote currency is
    stripped before searching.
    """
    base = ticker.split("-")[0].strip().upper()
    for quote in ("USDT", "USDC", "USD"):
        if base.endswith(quote) and len(base) > len(quote):
            return base[: -len(quote)]
    return base


def create_sentiment_analyst(llm):
    """Create a sentiment analyst node for the trading graph.

    Pre-fetches news + StockTwits + Reddit data, injects them into the
    prompt as structured blocks, and produces a deterministic sentiment
    report via structured output (with a free-text fallback for providers
    that do not support it).
    """
    structured_llm = bind_structured(llm, SentimentReport, "Sentiment Analyst")

    def sentiment_analyst_node(state):
        ticker = state["company_of_interest"]
        end_date = state["trade_date"]
        start_date = _seven_days_back(end_date)
        instrument_context = get_instrument_context_from_state(state)

        # Pre-fetch all three sources. Each fetcher degrades gracefully and
        # returns a string (no exceptions surface from here), so the LLM
        # always sees something — either real data or a clear placeholder.
        news_block = get_news.func(ticker, start_date, end_date)
        stocktwits_block = _maybe_stocktwits_block(ticker, state.get("asset_type", "stock"))
        reddit_block = fetch_reddit_posts(ticker)
        twitter_block = _maybe_twitter_block(ticker, start_date, end_date)

        system_message = _build_system_message(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            news_block=news_block,
            stocktwits_block=stocktwits_block,
            reddit_block=reddit_block,
            twitter_block=twitter_block,
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    " Today's date is {current_date}; treat it as 'now' for all analysis and tool-call date ranges. {instrument_context}"
                    "\n{system_message}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(current_date=end_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        # Format the template into a concrete message list so the structured
        # and free-text paths receive the same input. No bind_tools — the
        # data is already in the prompt.
        formatted_messages = prompt.format_messages(messages=state["messages"])

        report_text = invoke_structured_or_freetext(
            structured_llm,
            llm,
            formatted_messages,
            render_sentiment_report,
            "Sentiment Analyst",
        )

        return {
            "messages": [AIMessage(content=report_text)],
            "sentiment_report": report_text,
            "sentiment_sources": collect_sentiment_sources(
                news_block=news_block, stocktwits_block=stocktwits_block,
                reddit_block=reddit_block, twitter_block=twitter_block),
        }

    return sentiment_analyst_node


def _build_system_message(
    *,
    ticker: str,
    start_date: str,
    end_date: str,
    news_block: str,
    stocktwits_block: str,
    reddit_block: str,
    twitter_block: str = "",
) -> str:
    """Assemble the sentiment-analyst system message with structured data blocks.

    Optional sections appear only when their block was fetched, and the stated
    source count follows suit, so the prompt never advertises a source that is
    not present — naming an absent source is what drove the fabricated-post
    behavior this analyst was redesigned to fix.
    """
    stocktwits_section = ""
    if stocktwits_block:
        stocktwits_section = f"""
### StockTwits messages — retail-trader social platform indexed by cashtag
Fast-moving signal. Each message carries a user-labeled sentiment tag (Bullish / Bearish / no-label) plus the message body.

<start_of_stocktwits>
{stocktwits_block}
<end_of_stocktwits>
"""
    twitter_section = ""
    if twitter_block:
        twitter_section = f"""
### X/Twitter posts — public timeline search, ranked by engagement
Fastest-moving retail signal, and the most promotion-heavy. Weight posts by their like/retweet counts, and discount coordinated shilling: a cluster of near-identical posts from low-follower accounts is manufactured attention, not sentiment.

<start_of_twitter>
{twitter_block}
<end_of_twitter>
"""
    # News and Reddit are always present; the other two are switchable.
    source_count = _COUNT_WORDS[2 + bool(stocktwits_block) + bool(twitter_block)]
    return f"""You are a financial market sentiment analyst. Your task is to produce a comprehensive sentiment report for {ticker} covering the period from {start_date} to {end_date}, drawing on {source_count} complementary data sources that have already been collected for you.

## Data sources (pre-fetched, in this prompt)

### News headlines — Yahoo Finance, past 7 days
Institutional framing. Fact-driven, slower-moving signal.

<start_of_news>
{news_block}
<end_of_news>
{stocktwits_section}

### Reddit posts — r/wallstreetbets, r/stocks, r/investing (past 7 days)
Community discussion. Engagement signal via upvote score and comment count. Subreddit character matters (r/wallstreetbets is often contrarian/exuberant; r/stocks more measured; r/investing longer-term).

<start_of_reddit>
{reddit_block}
<end_of_reddit>
{twitter_section}
## How to analyze this data (best practices)

1. **Read the StockTwits Bullish/Bearish ratio as a leading retail-sentiment signal.** A 70/30 bullish/bearish split is moderately bullish; ≥90/10 may indicate over-extension and contrarian risk; 50/50 is uncertainty. Sample size matters — base rates on the actual message count, not percentages alone.

2. **Look for cross-source divergences.** If news framing is bearish but StockTwits is overwhelmingly bullish, that mismatch is itself a signal — it can mean retail is leaning into a thesis the news flow hasn't caught up to (or vice versa, that retail is chasing while institutions are cautious).

3. **Weight Reddit posts by engagement.** A 400-upvote / 200-comment thread reflects community attention; a 3-upvote post is noise. Read the body excerpts for context — the title alone often misleads.

4. **Distinguish opinion from event.** A news headline ("Nvidia announces $500M Corning deal") is an event; a StockTwits post ("buying NVDA, this is going to moon") is opinion. Both are inputs but should be weighted differently in your conclusions.

5. **Identify recurring narrative themes.** What topic keeps coming up across sources? That's the dominant narrative driving current sentiment.

6. **Be honest about data limits.** If StockTwits returned only a handful of messages, or one or more sources returned an "<unavailable>" placeholder, the sentiment read is less robust — flag this explicitly in the `confidence` field and the narrative. If the sources are silent on a given subreddit, say so.

7. **Identify catalysts and risks** that emerge across sources — news of upcoming earnings, product launches, competitive threats, macro headlines, etc.

8. **Past sentiment is not predictive.** Frame your conclusions as signal for the trader to weigh alongside fundamentals and technicals, not as a price call.

## Output fields

Fill the following fields:

- **overall_band**: Exactly one of Bullish / Mildly Bullish / Neutral / Mixed / Mildly Bearish / Bearish. Use Mixed when sources point in clearly different directions; Neutral only when all sources are genuinely silent.
- **overall_score**: A number from 0 (maximally bearish) to 10 (maximally bullish); 5 is neutral. Keep it consistent with overall_band.
- **confidence**: low / medium / high, based on data quality and sample size.
- **narrative**: Full source-by-source breakdown, divergences, dominant narrative themes, catalysts and risks, and a markdown summary table of key sentiment signals (direction, source, supporting evidence).

{get_language_instruction()}"""


# ---------------------------------------------------------------------------
# Backwards-compatibility shim
# ---------------------------------------------------------------------------
def create_social_media_analyst(llm):
    """Deprecated alias for :func:`create_sentiment_analyst`.

    Kept so existing code that imports ``create_social_media_analyst``
    continues to work.

    .. deprecated::
        Import :func:`create_sentiment_analyst` directly instead.
    """
    import warnings
    warnings.warn(
        "create_social_media_analyst is deprecated and will be removed in a "
        "future version. Use create_sentiment_analyst instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return create_sentiment_analyst(llm)
