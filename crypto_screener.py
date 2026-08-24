"""New Crypto tab — MEXC new-listing screener with per-coin agent analysis.

Kept out of app.py, which already carries the whole single-run screen. The pure
helpers here (config building, instrument context, row formatting) are unit
tested without a Streamlit runtime; render_new_crypto_tab() is the only part
that touches st.*.
"""

from __future__ import annotations

import html
import logging
import os
import time
from copy import deepcopy

logger = logging.getLogger(__name__)

# Fundamentals is omitted rather than disabled: a three-week-old memecoin has no
# filings, and giving that analyst nothing to read only feeds placeholders into
# the debate. Mirrors how the CLI filters analysts for crypto.
CRYPTO_ANALYSTS = ("market", "social", "news")


# Social sentiment sources, offered cheapest-first. StockTwits is keyless and
# free; X costs metered credits, so it is never the default.
SOURCE_STOCKTWITS = "StockTwits (free)"
SOURCE_TWITTER = "X / Twitter (paid credits)"
SOURCE_BOTH = "Both"
SOCIAL_SOURCES = (SOURCE_STOCKTWITS, SOURCE_TWITTER, SOURCE_BOTH)

_SOCIAL_FLAGS = {
    SOURCE_STOCKTWITS: {"include_stocktwits": True, "include_twitter": False},
    SOURCE_TWITTER: {"include_stocktwits": False, "include_twitter": True},
    SOURCE_BOTH: {"include_stocktwits": True, "include_twitter": True},
}


def social_flags(choice: str) -> dict:
    """Config flags for a social-source choice. Raises on an unknown label."""
    return dict(_SOCIAL_FLAGS[choice])


def parse_keywords(text: str) -> list[str]:
    """Comma-separated keywords → clean list: stripped, de-duped, empties out."""
    seen: list[str] = []
    for raw in (text or "").split(","):
        term = raw.strip()
        if term and term.lower() not in (s.lower() for s in seen):
            seen.append(term)
    return seen


def build_crypto_config(base: dict, *, provider: str, deep_model: str,
                        quick_model: str, debate_rounds: int, risk_rounds: int,
                        social_source: str = SOURCE_STOCKTWITS,
                        display_name: str | None = None,
                        listed_date: str | None = None,
                        age_hours: float | None = None,
                        twitter_keywords: list[str] | None = None) -> dict:
    """Config for a new-coin run: MEXC prices, Yahoo news, chosen social source.

    Returns a copy — the caller's DEFAULT_CONFIG must stay untouched so a later
    stock run in the same process still routes prices to yfinance. Defaults to
    the free source so an omitted choice never spends X credits.
    """
    cfg = deepcopy(base)
    cfg["llm_provider"] = provider
    cfg["deep_think_llm"] = deep_model
    cfg["quick_think_llm"] = quick_model
    cfg["max_debate_rounds"] = debate_rounds
    cfg["max_risk_discuss_rounds"] = risk_rounds
    vendors = dict(cfg.get("data_vendors", {}))
    vendors["core_stock_apis"] = "mexc"
    vendors["technical_indicators"] = "mexc"
    cfg["data_vendors"] = vendors
    cfg.update(social_flags(social_source))
    # The project name reaches the X search this way: people post "xPayLink" far
    # more than "$XPLK", and the analyst has no other route to a coin's name.
    if display_name:
        cfg["asset_display_name"] = display_name
    # Listing date and age let the analyst size its search window to the coin and
    # rank by recency while a listing is still reacting.
    if listed_date:
        cfg["asset_listed_date"] = listed_date
    if age_hours is not None:
        cfg["asset_age_hours"] = age_hours
    # User keywords are OR'd into the X search beside the cashtag and name.
    if twitter_keywords:
        cfg["twitter_extra_terms"] = list(twitter_keywords)
    return cfg


def coin_instrument_context(coin) -> str:
    """Instrument identity for a coin Yahoo has never heard of.

    resolve_instrument_context() looks the ticker up on yfinance, which returns
    nothing for a brand-new MEXC listing. MEXC's own metadata is strictly better
    here, so it is passed to the graph directly.
    """
    contract = f" Contract address: {coin.contract}." if coin.contract else ""
    return (
        f"The ticker {coin.base} refers to {coin.name}, a crypto asset trading on "
        f"MEXC as the spot pair {coin.symbol}. It was first traded on MEXC on "
        f"{coin.listed_date} ({coin.age_days} days ago), so it has almost no price "
        f"history and no company fundamentals.{contract} Treat it as a newly listed "
        f"crypto asset rather than a company, and do not infer a business, revenue, "
        f"or filings for it."
    )


def verdict_key(symbol: str, date: str, model: str) -> str:
    """Session-state key so each coin/date/model verdict survives other runs.

    The model is part of the key on purpose: without it, switching models and
    pressing Analyze showed the previous model's cached verdict instead of
    running the new one.
    """
    return f"verdict:{symbol}:{date}:{model}"


def report_key(symbol: str, date: str, model: str) -> str:
    """Session-state key for the stored reports behind a completed verdict."""
    return f"reports:{symbol}:{date}:{model}"


# Report sections shown in the expander, in reading order. Fundamentals is absent
# because the crypto pipeline does not run that analyst.
REPORT_SECTIONS = (
    ("sentiment_report", "Sentiment (social · Reddit · news)"),
    ("news_report", "News"),
    ("market_report", "Market / technicals (MEXC candles)"),
    ("investment_plan", "Research-team debate"),
    ("trader_investment_plan", "Trader plan"),
    ("final_trade_decision", "Risk-team final decision"),
)


# New-listing watch. One exchangeInfo request per poll covers the whole exchange
# and the age filter runs locally, so the cost is independent of how many coins
# qualify: 720 requests a day at this interval, against a measured 429 threshold
# of roughly 25 requests a second.
POLL_SECONDS = 120
# Coins listed longer ago than this are not announced. Without it, a fresh
# baseline plus a delisting/relisting could shout about a month-old coin.
ALERT_MAX_AGE_HOURS = 48.0


# Alert sounds, as (frequency Hz, duration s) tone sequences. Synthesised rather
# than shipped as audio files so the repo carries no binaries and nothing has to
# resolve a path at runtime. A rest is a frequency of 0.
ALERT_SOUNDS: dict[str, tuple] = {
    "Two-tone beep": ((880, 0.16), (1320, 0.16)),
    "Triple chirp": ((1568, 0.09), (0, 0.06), (1568, 0.09), (0, 0.06), (1568, 0.09)),
    "Rising alert": ((660, 0.12), (880, 0.12), (1100, 0.12), (1480, 0.2)),
    "Low buzz": ((220, 0.22), (0, 0.05), (220, 0.22)),
    "Siren": ((900, 0.18), (650, 0.18), (900, 0.18), (650, 0.18)),
    "Single ping": ((1046, 0.25),),
}
DEFAULT_ALERT_SOUND = "Two-tone beep"
_SOUND_RATE = 22_050


def alert_beep_wav(sound: str = DEFAULT_ALERT_SOUND, rate: int = _SOUND_RATE) -> bytes:
    """Render a named alert sound as WAV bytes.

    An unknown name falls back to the default rather than raising: a stale
    session-state value from a renamed sound must not break the alert path.
    """
    import io
    import math
    import struct
    import wave

    tones = ALERT_SOUNDS.get(sound) or ALERT_SOUNDS[DEFAULT_ALERT_SOUND]
    frames = bytearray()
    for freq, seconds in tones:
        total = int(rate * seconds)
        for i in range(total):
            if not freq:
                frames += struct.pack("<h", 0)          # rest
                continue
            # Taper both ends of a tone so looping does not click at the seam.
            fade = min(1.0, i / (rate * 0.01), (total - i) / (rate * 0.01))
            frames += struct.pack(
                "<h", int(22_000 * fade * math.sin(2 * math.pi * freq * i / rate)))

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return buf.getvalue()


# Age range the tab opens on: the window where a new listing is still moving.
DEFAULT_AGE_RANGE = (1, "hour", 24, "hour")

# Live chart. MEXC candles are keyless, so refreshing often costs nothing but a
# request; 10s is responsive without hammering a 1m candle that barely moves.
CHART_INTERVALS = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "60m", "1d": "1d"}
CHART_REFRESH_SECONDS = 10
CHART_CANDLES = 180
_UP = "#22C55E"
_DOWN = "#EF4444"


def candlestick_chart(df, base: str):
    """Altair candlestick for an OHLCV frame.

    Two layers: a thin rule spanning low-to-high for the wick, and a bar from
    open to close for the body, coloured by direction. Altair ships with
    Streamlit, so this needs no extra dependency.
    """
    import altair as alt

    data = df.copy()
    data["rising"] = data["Close"] >= data["Open"]
    colour = alt.condition("datum.rising", alt.value(_UP), alt.value(_DOWN))
    base_chart = alt.Chart(data).encode(
        x=alt.X("Date:T", title=None),
        tooltip=["Date:T", "Open:Q", "High:Q", "Low:Q", "Close:Q", "Volume:Q"],
    )
    # labelLimit keeps five-figure prices (BTC at 64,872) from being clipped to
    # "000"; Altair's default reserves too little room for the axis text.
    y_axis = alt.Axis(format=",.6~g", labelLimit=90, labelPadding=4)
    wick = base_chart.mark_rule().encode(
        y=alt.Y("Low:Q", title=f"{base} price", axis=y_axis,
                scale=alt.Scale(zero=False)),
        y2=alt.Y2("High:Q"), color=colour)
    body = base_chart.mark_bar().encode(y="Open:Q", y2="Close:Q", color=colour)
    # No .configure_*() here: Altair refuses to nest a configured chart inside a
    # LayerChart, and the Trade tab layers take-profit / stop-loss rules on top.
    return (wick + body).properties(height=340)


def chart_summary(df) -> str:
    """Last price plus the change across the visible window."""
    last = float(df["Close"].iloc[-1])
    first = float(df["Open"].iloc[0])
    price = f"{last:.8f}".rstrip("0").rstrip(".") or "0"
    if len(df) < 2 or first == 0:
        return f"last {price}"
    change = (last - first) / first * 100
    return f"last {price} · {change:+.2f}% over {len(df)} candles"


def upcoming_line(coin: dict) -> str:
    """One line for a listing that has been announced but is not trading yet."""
    when = coin.get("hours_until")
    if when is None:
        timing = "open time not published yet"
    elif when < 1:
        timing = f"opens in {int(round(when * 60))}m"
    else:
        timing = f"opens in {fmt_age(when)}"
    return f"**{coin['base']}** · {coin['name']} · {timing}"


def watch_status_line(symbol_count: int, *, last_poll: float | None,
                      now: float | None = None) -> str:
    """Caption proving the watch is alive and saying when it last checked."""
    if last_poll is None:
        return f"Listing watch starting · checks every {POLL_SECONDS // 60} min"
    elapsed = (time.time() if now is None else now) - last_poll
    ago = f"{int(elapsed)}s ago" if elapsed < 60 else f"{int(elapsed // 60)}m ago"
    return (f"Watching {symbol_count} MEXC pairs · last checked {ago} · "
            f"every {POLL_SECONDS // 60} min")


def alert_message(found: list) -> str:
    """Headline for newly detected listings, or "" when there are none."""
    if not found:
        return ""
    noun = "listing" if len(found) == 1 else "listings"
    coins = ", ".join(f"{c['base']} ({fmt_age(c['age_hours'])} old)" for c in found)
    return f"{len(found)} new MEXC {noun}: {coins}"


# Raw source panels shown under the sentiment report, cheapest source first.
SOURCE_PANELS = (
    ("stocktwits", "StockTwits messages"),
    ("twitter", "X / Twitter posts"),
    ("reddit", "Reddit posts"),
    ("news", "News headlines"),
)


def collect_reports(state: dict, decision: str) -> dict:
    """Pull the report sections worth keeping out of a finished graph state."""
    reports = {key: state.get(key, "") for key, _ in REPORT_SECTIONS}
    if decision and not reports.get("final_trade_decision"):
        reports["final_trade_decision"] = decision
    kept = {k: v for k, v in reports.items() if v}
    sources = state.get("sentiment_sources") or {}
    if sources:
        kept["sentiment_sources"] = dict(sources)
    return kept


def source_panel_rows(sources: dict) -> list:
    """``(key, label, body)`` per fetched source, in panel order.

    A fetcher that could not reach its source returns a ``<...>`` placeholder
    rather than raising, so the label says so outright — otherwise a reader opens
    a panel expecting posts and finds a sentence they have to decode.
    """
    rows = []
    for key, label in SOURCE_PANELS:
        body = sources.get(key)
        if not body:
            continue
        unavailable = body.lstrip().startswith("<")
        rows.append((key, f"{label} — unavailable" if unavailable else label, body))
    return rows


def verdict_label(signal: str | None) -> str:
    """Render a signal as its table chip — the full 5-tier scale."""
    return {
        "BUY": "▲ BUY", "OVERWEIGHT": "↗ OVERWEIGHT", "HOLD": "■ HOLD",
        "UNDERWEIGHT": "↘ UNDERWEIGHT", "SELL": "▼ SELL",
    }.get((signal or "").strip().upper(), "—")


# Rows shown per table page. A 60-coin sweep rendered as one endless column
# buried the pagination-worthy signal (the newest listings) below the fold.
PAGE_SIZE = 20
_PAGE_KEY = "crypto_table_page"


def page_slice(coins: list, page: int, size: int = PAGE_SIZE) -> tuple:
    """Clamped ``(page, total_pages, rows)`` for one table page.

    The stored page can go stale when a rescan shrinks the list (page 3 of a
    60-coin sweep, then a filter leaves 15 coins), so it is clamped rather
    than trusted.
    """
    total = max(1, -(-len(coins) // size))
    page = min(max(page, 0), total - 1)
    return page, total, coins[page * size:(page + 1) * size]


# Age units offered in the range dropdowns, in hours.
AGE_UNITS = {"hour": 1, "day": 24, "week": 168}

# The meter is drawn against a reference "full tank" rather than a real ceiling,
# because a pay-as-you-go balance has no maximum. 100 analyze runs is a week or
# two of ordinary use, which makes the bar readable at the scale that matters.
CREDIT_METER_REFERENCE_RUNS = 100
# Below this many remaining runs the bar turns amber; at zero it turns red.
CREDIT_LOW_RUNS = 20


def credit_summary(balance: dict) -> dict:
    """Turn a raw credit balance into everything the meter needs to render.

    Credits are meaningless to read directly, so they are expressed as the two
    units that answer "should I top up": how many analyze runs remain, and what
    the balance is worth in dollars.
    """
    from tradingagents.dataflows import twitter

    total = max(0, int(balance.get("total", 0)))
    runs = total // twitter.CREDITS_PER_RUN
    usd = total / twitter.CREDITS_PER_USD
    reference = CREDIT_METER_REFERENCE_RUNS * twitter.CREDITS_PER_RUN

    if not balance.get("ok"):
        level = "unknown"
    elif runs == 0:
        level = "empty"
    elif runs < CREDIT_LOW_RUNS:
        level = "low"
    else:
        level = "ok"

    if level == "unknown":
        detail = f"Balance unavailable — {balance.get('error', 'unknown error')}."
    elif runs == 0:
        detail = ("Not enough for another X/Twitter fetch. Sentiment will fall back "
                  "to Reddit and news until you top up ($1 ≈ 330 runs).")
    else:
        detail = f"About {runs} more analyze runs at ~{twitter.CREDITS_PER_RUN} credits each."
        # Bonus credits expire; recharged credits do not. Only warn when the
        # balance is entirely promotional, since that is the expiring kind.
        if balance.get("bonus", 0) > 0 and balance.get("recharge", 0) == 0:
            detail += " These are bonus credits, valid 30 days from the recharge that granted them."

    return {
        "known": bool(balance.get("ok")),
        "credits": total,
        "runs": runs,
        "usd": usd,
        "level": level,
        "fraction": min(1.0, total / reference) if reference else 0.0,
        "detail": detail,
    }


def to_hours(value: float, unit: str) -> float:
    """Convert a value plus unit label into hours."""
    return value * AGE_UNITS[unit]


def parse_age_range(min_value: float, min_unit: str,
                    max_value: float, max_unit: str):
    """Validate an age range. Returns ``(min_hours, max_hours, error)``.

    The bound pair is rejected rather than silently reordered when the minimum is
    not older-than-or-equal the maximum: "1 week to 1 hour" is a mistake, and
    swapping it would quietly analyze a different set of coins than asked for.
    """
    for unit in (min_unit, max_unit):
        if unit not in AGE_UNITS:
            return None, None, (
                f"Unknown unit {unit!r}. Choose one of: "
                f"{', '.join(AGE_UNITS)}."
            )
    if min_value < 0 or max_value < 0:
        return None, None, "Age bounds cannot be negative."

    low = to_hours(min_value, min_unit)
    high = to_hours(max_value, max_unit)
    if low >= high:
        return None, None, (
            f"The 'from' age ({fmt_age(low)}) must be younger than the 'to' age "
            f"({fmt_age(high)}) — a range reads from newest to oldest, e.g. "
            f"1 hour to 1 week."
        )
    return low, high, None


def fmt_age(hours: float) -> str:
    """Compact age label: 24m, 5h, 1d 12h, 9d.

    Days rather than weeks above a day: every coin here is younger than the sweep
    window, so "9d" reads faster in a table than "1w 2d". Hours are only shown
    alongside days below the first week, where they still carry information.
    """
    if hours < 1:
        return f"{int(round(hours * 60))}m"
    if hours < 24:
        return f"{int(hours)}h"
    days, rem = divmod(int(hours), 24)
    if days < 7 and rem:
        return f"{days}d {rem}h"
    return f"{days}d"


def _fmt_volume(value: float) -> str:
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:.1f}k"
    return f"${value:.0f}"


def row_cells(coin) -> dict:
    """Pre-formatted display strings for one table row."""
    # Sub-cent coins need every digit; trailing zeros are noise at this scale.
    price = f"{coin.price:.8f}".rstrip("0") or "0"
    return {
        "symbol": coin.base,
        "name": coin.name,
        "listed": coin.listed_date,
        "age": fmt_age(coin.age_hours),
        "price": price,
        "change": f"{coin.change_pct:+.2f}%",
        "volume": _fmt_volume(coin.quote_volume),
    }


def status_caption(result) -> str:
    """One line describing sweep coverage. Never hides what could not be checked."""
    parts = [f"{result.scanned} MEXC USDT pairs scanned"]
    if result.unresolved:
        parts.append(f"{result.unresolved} could not be checked (rate-limited)")
    if result.hidden_by_age:
        parts.append(f"{result.hidden_by_age} outside the age range")
    if result.hidden_by_volume:
        parts.append(f"{result.hidden_by_volume} hidden by the volume floor")
    if result.stale:
        parts.append("data is STALE — refresh failed, showing the last good sweep")
    elif result.fetched_at:
        age_min = max(0, int((time.time() - result.fetched_at) / 60))
        parts.append(f"data {age_min} min old")
    return " · ".join(parts)


# Column widths for the screener grid, shared by the header and every row.
# Widened 2026-08-20: the app's component stylesheet now reaches this screen,
# which puts these cells in Fira Code — wider per character than the face these
# ratios were set for. LISTED broke "2026-08-19" across two lines, 24H broke
# "+833.50%" into "+833." / "50%", and VOLUME broke "$321.6k". A figure split
# over two lines reads as two figures, so the columns fit their widest value:
# LISTED 10 chars, 24H 8, VOLUME 8, VERDICT 7. NAME gives up the slack,
# since it is the one cell where wrapping a long coin name is acceptable.
_WIDTHS = [0.9, 1.3, 1.6, 0.55, 1.05, 1.3, 1.05, 1.05, 0.9]
_HEADINGS = ("SYMBOL", "NAME", "LISTED", "AGE", "PRICE", "24H", "VOLUME",
             "VERDICT", "")


def render_run_panel(st, *, model_options, default_model, custom_sentinel,
                     provider_for, mexc):
    """Right-hand control panel: what a run uses, kept out of the table's way.

    Returns the settings the screener needs. These live beside the data rather
    than above it so the table starts at the top of the screen, which is what a
    reader came for.
    """
    st.markdown('<div class="ta-panel-title">Run settings</div>',
                unsafe_allow_html=True)

    model = st.selectbox("Model", model_options, index=0, key="crypto_model",
                         format_func=lambda m: f"{m}  ·  {provider_for(m)}")
    if model == custom_sentinel:
        model = st.text_input("Custom model id", value="", key="crypto_custom",
                             placeholder="vendor/model-id").strip() or default_model
    trade_date = st.date_input("Analysis date", key="crypto_date").isoformat()

    source = st.radio("Social sentiment source", SOCIAL_SOURCES,
                      key="crypto_social_source",
                      help="StockTwits is keyless and free with Bullish/Bearish "
                           "tags; X costs metered credits. News and Reddit are "
                           "always included.")
    # The credit bar and keyword box are noise when the run will not touch X.
    twitter_keywords: list[str] = []
    if social_flags(source)["include_twitter"]:
        twitter_keywords = parse_keywords(st.text_input(
            "X search keywords (optional, comma-separated)",
            key="crypto_twitter_keywords", placeholder="airdrop, listing pump",
            help="Extra terms OR'd into the X search besides the cashtag and "
                 "the coin's name. Multi-word terms match as phrases. Keep "
                 "terms specific — very common phrases return huge result "
                 "pages, which slows the search and can time it out."))
        _render_credit_meter(st)

    sound = st.selectbox("Alert sound", list(ALERT_SOUNDS),
                         index=list(ALERT_SOUNDS).index(DEFAULT_ALERT_SOUND),
                         key="crypto_alert_sound")
    s1, s2 = st.columns([1, 1])
    loop_sound = s1.checkbox("Loop", value=False, key="crypto_alert_loop",
                             help="Repeat until you press Stop.")
    if s2.button("▶ Test", key="crypto_alert_preview", help="Hear this sound"):
        st.audio(alert_beep_wav(sound), format="audio/wav", autoplay=True)

    r1, r2 = st.columns([1, 1])
    debate_rounds = r1.number_input("Debate", 1, 5, 1, key="crypto_debate",
                                    help="Bull/bear debate rounds")
    risk_rounds = r2.number_input("Risk", 1, 5, 1, key="crypto_risk",
                                  help="Risk-team discussion rounds")
    return {"model": model, "trade_date": trade_date, "source": source,
            "sound": sound, "loop_sound": loop_sound,
            "debate_rounds": debate_rounds, "risk_rounds": risk_rounds,
            "twitter_keywords": twitter_keywords}


def render_filter_popover(st, mexc):
    """Age range and volume floor, behind a funnel. Returns the filter values.

    Tucked away because they are set once and then left alone; showing four age
    widgets above the table pushed the data below the fold on every visit.
    """
    units = list(AGE_UNITS)
    dv, du, xv, xu = DEFAULT_AGE_RANGE
    with st.popover("Filters", icon=":material/filter_alt:"):
        st.markdown('<div class="ta-label">Age range — from / to</div>',
                    unsafe_allow_html=True)
        a1, a2 = st.columns([1, 1.4])
        min_value = a1.number_input("Age from", min_value=0, value=dv, step=1,
                                   key="crypto_age_min_value",
                                   label_visibility="collapsed")
        min_unit = a2.selectbox("From unit", units, index=units.index(du),
                                key="crypto_age_min_unit",
                                label_visibility="collapsed")
        b1, b2 = st.columns([1, 1.4])
        max_value = b1.number_input("Age to", min_value=0, value=xv, step=1,
                                   key="crypto_age_max_value",
                                   label_visibility="collapsed")
        max_unit = b2.selectbox("To unit", units, index=units.index(xu),
                                key="crypto_age_max_unit",
                                label_visibility="collapsed")
        st.markdown('<div class="ta-label">Liquidity</div>', unsafe_allow_html=True)
        min_vol = st.number_input("Min 24h volume (USDT)", min_value=0.0,
                                  value=mexc.DEFAULT_MIN_QUOTE_VOLUME, step=10_000.0,
                                  key="crypto_min_vol")
        include_all = st.checkbox("Show all (incl. dust)", value=False,
                                  key="crypto_include_all")
    return min_value, min_unit, max_value, max_unit, min_vol, include_all


def render_new_crypto_tab(*, model_options, default_model, custom_sentinel,
                          provider_for, base_config: dict, configure_cfg,
                          streaming_runner) -> None:
    """Announcements on the left, screener table in the middle, settings right.

    ``configure_cfg`` and ``streaming_runner`` are injected from app.py so this
    module never imports app.py, which would re-execute its Streamlit setup.
    """
    import streamlit as st

    from tradingagents.dataflows import mexc

    # The key gives this row a stable .st-key-crypto_layout class so the CSS can
    # top-align just this layout row while data rows elsewhere stay centered.
    layout = st.container(key="crypto_layout")
    ann_col, table_col, panel_col = layout.columns([1.1, 3.8, 1.1], gap="large")
    with ann_col:
        # Only the exchange's own coming-soon list: which coins open, and when.
        _render_upcoming_panel(st)
    with panel_col, st.container(border=True):
        settings = render_run_panel(
            st, model_options=model_options, default_model=default_model,
            custom_sentinel=custom_sentinel, provider_for=provider_for,
            mexc=mexc)

    model = settings["model"]
    provider = provider_for(model)
    trade_date = settings["trade_date"]
    source = settings["source"]
    sound_name = settings["sound"]
    loop_sound = settings["loop_sound"]

    with table_col:
        _render_screener(
            st, mexc, model=model, provider=provider, trade_date=trade_date,
            source=source, sound_name=sound_name, loop_sound=loop_sound,
            debate_rounds=settings["debate_rounds"],
            risk_rounds=settings["risk_rounds"],
            twitter_keywords=settings["twitter_keywords"],
            base_config=base_config, configure_cfg=configure_cfg,
            streaming_runner=streaming_runner)


def _render_screener(st, mexc, *, model, provider, trade_date, source, sound_name,
                     loop_sound, debate_rounds, risk_rounds, base_config,
                     configure_cfg, streaming_runner,
                     twitter_keywords: list[str] | None = None) -> None:
    """The toolbar, the table, the chart and the analysis modal."""
    # Timers are paused while a run is pending: a fragment refresh reruns the app,
    # Streamlit re-executes an open dialog's body, and the analysis restarted from
    # stage 0 — repeatedly, so it never finished and spent tokens each time.
    run_pending = bool(st.session_state.get(_PENDING_KEY))

    bar_filter, bar_scan, bar_note = st.columns([1, 1, 4])
    with bar_filter:
        (min_value, min_unit, max_value, max_unit,
         min_vol, include_all) = render_filter_popover(st, mexc)
    scan = bar_scan.button("↻ Scan MEXC", key="crypto_refresh",
                          help="Sweep all MEXC USDT pairs now (~2 minutes)")

    min_age, max_age, age_error = parse_age_range(min_value, min_unit,
                                                 max_value, max_unit)
    if age_error:
        # Refuse the range rather than reordering it: swapping the bounds would
        # silently screen a different set of coins than the one asked for.
        st.error(age_error)
        return
    bar_note.caption(f"Listed between **{fmt_age(min_age)}** and "
                     f"**{fmt_age(max_age)}** ago · volume ≥ ${min_vol:,.0f}")

    if not run_pending:
        _render_listing_watch(st, sound_name=sound_name, loop_sound=loop_sound)
    else:
        st.caption("Listing watch and chart refresh paused while an analysis runs.")

    # The sweep stays explicit: rendering it automatically would cost ~1700
    # requests every time anyone touched the app.
    if scan:
        try:
            with st.spinner("Scanning ~1700 MEXC pairs — this takes about 2 minutes…"):
                result = mexc.screen_new_listings(
                    min_quote_volume=min_vol, include_all=include_all,
                    force_refresh=True, min_age_hours=min_age,
                    max_age_hours=max_age)
        except mexc.MexcUnavailable as exc:
            st.error(f"Cannot reach MEXC: {exc}")
            return
    else:
        result = mexc.cached_listings(min_quote_volume=min_vol,
                                      include_all=include_all,
                                      min_age_hours=min_age, max_age_hours=max_age)

    if result is None:
        st.info("No scan yet. Press **↻ Scan MEXC** to sweep the exchange "
                "for coins listed in the last 30 days (about 2 minutes).")
        return

    if not result.coins:
        st.caption(status_caption(result))
        st.info(f"No MEXC coins were first traded between {fmt_age(min_age)} and "
                f"{fmt_age(max_age)} ago above that volume floor. Widen the range "
                f"or lower the floor.")
        return

    page, total_pages, page_coins = page_slice(
        result.coins, st.session_state.get(_PAGE_KEY, 0))
    st.session_state[_PAGE_KEY] = page

    to_run = None
    with st.container(border=True):
        header = st.columns(_WIDTHS)
        for col, label in zip(header, _HEADINGS, strict=False):
            col.markdown(f"<div class='ta-th'>{label}</div>", unsafe_allow_html=True)

        for coin in page_coins:
            cells = row_cells(coin)
            cols = st.columns(_WIDTHS)
            # The symbol is the chart handle: clicking it opens the live candles.
            if cols[0].button(cells["symbol"], key=f"chart_{coin.symbol}",
                              help=f"Live {coin.base} chart from MEXC candles"):
                st.session_state[_CHART_KEY] = coin.symbol
            cols[1].write(cells["name"])
            cols[2].write(cells["listed"])
            cols[3].write(cells["age"])
            cols[4].write(cells["price"])
            colour = _UP if coin.change_pct >= 0 else _DOWN
            cols[5].markdown(f"<span style='color:{colour}'>{cells['change']}</span>",
                             unsafe_allow_html=True)
            cols[6].write(cells["volume"])
            stored = st.session_state.get(
                verdict_key(coin.symbol, trade_date, model), "")
            cols[7].markdown(f"**{verdict_label(stored)}**")
            if cols[8].button("Analyze", key=f"analyze_{coin.symbol}"):
                st.session_state[_PENDING_KEY] = coin.symbol
                to_run = coin

        if total_pages > 1:
            prev_c, info_c, next_c = st.columns([1, 4, 1])
            if prev_c.button("← Prev", key="crypto_page_prev", disabled=page == 0):
                st.session_state[_PAGE_KEY] = page - 1
                st.rerun()
            info_c.caption(f"Page {page + 1} of {total_pages} · "
                           f"{len(result.coins)} coins · {PAGE_SIZE} per page")
            if next_c.button("Next →", key="crypto_page_next",
                             disabled=page >= total_pages - 1):
                st.session_state[_PAGE_KEY] = page + 1
                st.rerun()

    st.caption(status_caption(result))

    if not run_pending:
        _render_live_chart(st, {c.symbol: c for c in result.coins})

    pending = st.session_state.get(_PENDING_KEY)
    coin = to_run or next((c for c in result.coins if c.symbol == pending), None)
    if not pending or coin is None:
        _render_stored_reports(st, trade_date)
        return

    # The run happens in a modal rather than below the table: a 60-second stream
    # appended under 60 rows pushed the coin being analyzed out of view.
    @st.dialog(f"{coin.base} · {coin.name}", width="large")
    def _analysis_dialog():
        st.caption(f"{coin.symbol} · listed {coin.listed_date} "
                   f"({fmt_age(coin.age_hours)} old) · {model} · {source}")

        # Streamlit re-executes an open dialog's body on every rerun, so the run
        # has to be guarded: without this the analysis restarted from stage 0 and
        # spent LLM tokens and X credits again on each rerun.
        done = st.session_state.get(
            report_key(coin.symbol, trade_date, model)) is not None
        if not done:
            cfg = build_crypto_config(
                base_config, provider=provider, deep_model=model, quick_model=model,
                debate_rounds=debate_rounds, risk_rounds=risk_rounds,
                social_source=source, display_name=coin.name,
                listed_date=coin.listed_date, age_hours=coin.age_hours,
                twitter_keywords=twitter_keywords)
            configure_cfg(cfg, model)
            outcome = streaming_runner(
                coin.symbol, trade_date, list(CRYPTO_ANALYSTS), cfg, provider, model,
                asset_type="crypto", instrument_context=coin_instrument_context(coin))
            st.session_state[verdict_key(coin.symbol, trade_date, model)] = (
                outcome.signal or "")
            st.session_state[report_key(coin.symbol, trade_date, model)] = (
                collect_reports(outcome.state, outcome.decision))
            st.session_state["crypto_last_analyzed"] = (coin.symbol, coin.base,
                                                        coin.name, trade_date, model)
        else:
            # Cached rerun: the stream (and its Sentiment Analyst section with
            # the raw source posts) is gone, so show verdict + sources here.
            verdict = st.session_state.get(
                verdict_key(coin.symbol, trade_date, model), "")
            st.markdown(f"### {verdict_label(verdict)}")
            _render_source_panels(
                st, (st.session_state.get(report_key(coin.symbol, trade_date, model))
                     or {}).get("sentiment_sources") or {})

        if st.button("Close", type="primary", key="crypto_close_dialog"):
            st.session_state.pop(_PENDING_KEY, None)
            st.rerun()

    _analysis_dialog()


def _render_background_watcher_status(st) -> None:
    """Report the standalone watcher, which keeps alerting with the tab closed.

    Read from its state file rather than by importing it, so the tab works
    whether or not that script has ever been started.
    """
    import json

    from tradingagents.dataflows.config import get_config

    path = os.path.join(get_config()["data_cache_dir"], "mexc-watch-state.json")
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return                      # never started; nothing to report
    last = raw.get("last_poll_at")
    if not isinstance(last, (int, float)):
        return
    elapsed = time.time() - last
    alive = elapsed <= POLL_SECONDS * 2.5
    mark = "●" if alive else "○"
    state = "running" if alive else "stopped"
    st.caption(f"{mark} background watcher {state} · last poll "
               f"{int(elapsed // 60)}m {int(elapsed % 60)}s ago · "
               f"{raw.get('polls', 0)} polls")


_KNOWN_KEY = "crypto_known_symbols"
_LAST_POLL_KEY = "crypto_last_poll_at"
_ALERTS_KEY = "crypto_new_listings"
_BEEP_KEY = "crypto_pending_beep"
_SOUNDING_KEY = "crypto_alert_sounding"


def _render_listing_watch(st, *, sound_name=DEFAULT_ALERT_SOUND,
                          loop_sound: bool = False) -> None:
    """Poll MEXC for new listings and sound an alert when one appears.

    Runs as a fragment so the timer reruns only this block, leaving the table and
    any in-flight analysis untouched. Detection is one request per tick. The sound
    choice is passed in, since those controls now live in the run panel.
    """
    from tradingagents.dataflows import mexc

    watch = st.checkbox("Watch for new listings", value=True, key="crypto_watch",
                        help=f"Polls MEXC every {POLL_SECONDS // 60} min "
                             f"(one request) and plays a sound when a coin is listed.")
    if not watch:
        return

    @st.fragment(run_every=POLL_SECONDS)
    def _tick():
        known = st.session_state.get(_KNOWN_KEY) or set()
        try:
            found, seen = mexc.poll_new_listings(
                known, max_age_hours=ALERT_MAX_AGE_HOURS)
        except (mexc.MexcUnavailable, mexc.MexcHostUnavailable,
                mexc.MexcRateLimited) as exc:
            st.caption(f"Listing watch paused — {exc}")
            return

        st.session_state[_KNOWN_KEY] = seen
        st.session_state[_LAST_POLL_KEY] = time.time()
        if found:
            # Keep newest first and cap the log so a long session cannot grow it
            # without bound.
            st.session_state[_ALERTS_KEY] = (
                found + (st.session_state.get(_ALERTS_KEY) or []))[:20]
            st.session_state[_BEEP_KEY] = True
            st.session_state[_SOUNDING_KEY] = loop_sound
            st.toast(alert_message(found))
            # Put the coin in the table NOW: merge it into the cached sweep
            # (one request) and redraw the page. The beep flag is already in
            # session state, so the sound still plays on the rerun pass.
            try:
                merged = mexc.merge_new_listings(found)
            except Exception as exc:                     # noqa: BLE001
                logger.warning("Listing merge failed: %s", exc)
                merged = 0
            if merged:
                st.rerun(scope="app")

        _detect_upcoming(st, mexc)

        alerts = st.session_state.get(_ALERTS_KEY) or []
        if alerts:
            st.success(alert_message(alerts[:5]))
        # The stop control lives inside the fragment so it appears on the very
        # pass that arms the loop; rendered outside, it would not exist until the
        # next poll two minutes later, leaving no way to silence the sound.
        if st.session_state.get(_SOUNDING_KEY):
            # Clicking a widget inside a fragment already reruns that fragment,
            # which drops the audio element — no explicit rerun needed, and
            # st.rerun(scope="fragment") raises outside a fragment rerun.
            if st.button("Stop sound", key="crypto_alert_stop", type="primary"):
                st.session_state[_SOUNDING_KEY] = False
        st.caption(watch_status_line(
            len(seen), last_poll=st.session_state.get(_LAST_POLL_KEY)))
        _render_background_watcher_status(st)

        # Autoplay is allowed only after the user has interacted with the page,
        # which opening this tab satisfies.
        looping = loop_sound and st.session_state.get(_SOUNDING_KEY)
        if st.session_state.pop(_BEEP_KEY, False) or looping:
            # A one-shot is cleared by the pop above so a later tick cannot
            # replay it; a loop is re-rendered every tick until Stop clears the
            # flag, because a fragment rerun discards the previous audio element.
            st.audio(alert_beep_wav(sound_name), format="audio/wav",
                     autoplay=True, loop=bool(looping))

    _tick()


_CREDIT_CACHE_KEY = "crypto_credit_balance"
_CREDIT_CACHE_TTL = 120.0
_CREDIT_COLORS = {"ok": "#22C55E", "low": "#F59E0B", "empty": "#EF4444",
                  "unknown": "#64748B"}
_CREDIT_LABELS = {"ok": "healthy", "low": "running low", "empty": "exhausted",
                  "unknown": "unknown"}


def _cached_balance(st, force: bool = False) -> dict:
    """Credit balance, cached in session state.

    Streamlit re-runs this tab on every interaction and the free tier allows one
    request per five seconds, so polling the balance on each render would spend
    the run's rate-limit budget on a status widget.
    """
    from tradingagents.dataflows import twitter

    cached = st.session_state.get(_CREDIT_CACHE_KEY)
    if cached and not force and (time.time() - cached["at"]) < _CREDIT_CACHE_TTL:
        return cached["balance"]

    # Generous timeout: the account endpoint shares the API's slow days, and a
    # blown lookup used to flash "Balance unavailable" over a perfectly fine
    # balance. When the refresh still fails, keep showing the last good
    # reading (re-stamped, so the TTL keeps throttling retries).
    balance = twitter.fetch_credit_balance(timeout=20.0)
    if not balance.get("ok") and cached and cached["balance"].get("ok"):
        balance = cached["balance"]
    st.session_state[_CREDIT_CACHE_KEY] = {"at": time.time(), "balance": balance}
    return balance


def _render_credit_meter(st) -> None:
    """X/Twitter credit bar, in the same idiom as the engine-capacity panel."""
    col_bar, col_btn = st.columns([5, 1])
    refresh = col_btn.button("↻", key="crypto_credit_refresh",
                             help="Re-check the X/Twitter credit balance")
    summary = credit_summary(_cached_balance(st, force=refresh))

    colour = _CREDIT_COLORS[summary["level"]]
    headline = (f"{summary['credits']:,} credits · ~{summary['runs']} runs · "
                f"${summary['usd']:.2f}") if summary["known"] else "unavailable"
    col_bar.markdown(
        "<div style='margin:2px 0 10px'>"
        "<div style='display:flex;justify-content:space-between;"
        "font-family:var(--font-mono);font-size:12px'>"
        "<span style='color:var(--muted);letter-spacing:.08em'>X/TWITTER CREDITS "
        f"<span style='color:{colour}'>· {_CREDIT_LABELS[summary['level']]}</span></span>"
        f"<span style='color:{colour}'>{html.escape(headline)}</span></div>"
        "<div style='height:8px;background:#0E141B;border:1px solid var(--border);"
        "border-radius:6px;overflow:hidden;margin-top:3px'>"
        f"<div style='height:100%;width:{int(summary['fraction'] * 100)}%;"
        f"background:{colour}'></div></div>"
        f"<div style='font-size:11px;color:var(--muted);margin-top:4px'>"
        f"{html.escape(summary['detail'])}</div></div>",
        unsafe_allow_html=True)


_ANNOUNCED_KEY = "crypto_announced_symbols"
_UPCOMING_KEY = "crypto_upcoming_rows"


def _detect_upcoming(st, mexc) -> None:
    """Track listings MEXC has announced but not opened; beep on new ones.

    Read from the same exchangeInfo call the watch already makes, so knowing what
    is coming costs nothing extra. A newly announced coin beeps like a new listing
    does — it is the earliest warning the exchange gives. The rows are stashed in
    session state; the announcements column left of the table displays them.
    """
    try:
        rows = mexc.upcoming_listings()
    except (mexc.MexcUnavailable, mexc.MexcHostUnavailable, mexc.MexcRateLimited):
        return                      # the watch caption already reports the outage
    st.session_state[_UPCOMING_KEY] = rows
    if not rows:
        return

    known = st.session_state.get(_ANNOUNCED_KEY)
    current = {r["symbol"] for r in rows}
    if known is not None:
        fresh = [r for r in rows if r["symbol"] not in known]
        if fresh:
            st.session_state[_BEEP_KEY] = True
            st.toast(f"{len(fresh)} listing announced: "
                     f"{', '.join(r['base'] for r in fresh)}")
    st.session_state[_ANNOUNCED_KEY] = current


def _render_upcoming_panel(st) -> None:
    """The "Coming soon on MEXC" card in the announcements column.

    Display only — detection (and the beep) lives in the watch fragment, which
    stashes the rows in session state. A fragment on the same cadence keeps the
    card fresh without another exchangeInfo request.

    The timer MUST pause while an analysis is pending: a fragment refresh
    reruns the app, Streamlit re-executes the open dialog's body, and the
    analysis restarts from stage 0 — so any run longer than one poll interval
    would loop forever and burn tokens on every lap.
    """
    run_pending = bool(st.session_state.get(_PENDING_KEY))

    @st.fragment(run_every=None if run_pending else POLL_SECONDS)
    def _panel():
        rows = st.session_state.get(_UPCOMING_KEY)
        if rows is None:
            # First load: this column renders before the watch fragment's first
            # tick, so fetch once rather than showing an empty card for a poll.
            from tradingagents.dataflows import mexc
            try:
                rows = mexc.upcoming_listings()
            except (mexc.MexcUnavailable, mexc.MexcHostUnavailable,
                    mexc.MexcRateLimited):
                rows = []
            st.session_state[_UPCOMING_KEY] = rows
        if rows:
            st.info("**Coming soon on MEXC**\n\n"
                    + "\n\n".join(upcoming_line(r) for r in rows[:5]))

    _panel()


_CHART_KEY = "crypto_chart_symbol"
_PENDING_KEY = "crypto_pending_run"


def _render_live_chart(st, coins_by_symbol: dict) -> None:
    """Live candles for the symbol whose row was clicked.

    Wrapped in a fragment so the refresh timer redraws only the chart — a table
    of 60 rows and any running analysis stay put.
    """
    from tradingagents.dataflows import mexc

    symbol = st.session_state.get(_CHART_KEY)
    if not symbol:
        st.caption("Click a symbol to open its live chart.")
        return
    coin = coins_by_symbol.get(symbol)
    base = coin.base if coin else symbol

    st.markdown('<div class="ta-rule"></div>', unsafe_allow_html=True)
    head, picker, closer = st.columns([3, 1.4, 0.8])
    head.markdown(f"### {base} · live chart")
    labels = list(CHART_INTERVALS)
    choice = picker.selectbox("Interval", labels, index=0, key="crypto_chart_interval")
    if closer.button("✕ close", key="crypto_chart_close"):
        st.session_state.pop(_CHART_KEY, None)
        st.rerun()

    @st.fragment(run_every=CHART_REFRESH_SECONDS)
    def _chart():
        try:
            df = mexc.intraday_ohlcv(symbol, interval=CHART_INTERVALS[choice],
                                     limit=CHART_CANDLES)
        except Exception as exc:                       # noqa: BLE001
            # A chart is not worth breaking the tab over; say why and move on.
            st.warning(f"No {choice} candles for {base}: {exc}")
            return
        st.altair_chart(candlestick_chart(df, base), use_container_width=True)
        st.caption(f"{chart_summary(df)} · {choice} candles from MEXC · "
                   f"refreshing every {CHART_REFRESH_SECONDS}s")

    _chart()


def _render_stored_reports(st, trade_date: str) -> None:
    """Show the reports behind the most recently analyzed coin, if any."""
    last = st.session_state.get("crypto_last_analyzed")
    if not last:
        return
    symbol, base, name, date, model = last
    if date != trade_date:
        return
    reports = st.session_state.get(report_key(symbol, date, model), {})
    if not reports:
        return
    verdict = verdict_label(
        st.session_state.get(verdict_key(symbol, date, model), ""))
    with st.expander(f"{base} · {name} — {verdict} · full reports", expanded=True):
        for key, label in REPORT_SECTIONS:
            if reports.get(key):
                st.markdown(f"#### {label}")
                # Prices contain dollar signs, which Streamlit would read as LaTeX.
                st.markdown(reports[key].replace("$", r"\$"))
            # Raw source data sits directly under the narrative that used it, so
            # a claim about StockTwits sentiment can be checked against the posts.
            if key == "sentiment_report":
                _render_source_panels(st, reports.get("sentiment_sources") or {})


def _render_source_panels(st, sources: dict) -> None:
    """Collapsed panels holding the raw posts each source returned."""
    rows = source_panel_rows(sources)
    if not rows:
        return
    st.markdown("##### Source data the analyst read")
    for _, label, body in rows:
        with st.expander(label, expanded=False):
            st.code(body, language=None)
