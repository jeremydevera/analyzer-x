"""Unit tests for the New Crypto tab's pure helpers (no Streamlit runtime)."""

import importlib.util
import sys
from pathlib import Path

import pytest

from tradingagents.dataflows.mexc import NewCoin, ScreenResult

_PATH = Path(__file__).resolve().parents[1] / "crypto_screener.py"

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def screener():
    spec = importlib.util.spec_from_file_location("ta_crypto_screener", _PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ta_crypto_screener"] = mod
    spec.loader.exec_module(mod)
    return mod


def _coin(**over):
    base = {"symbol": "CATEUSDT", "base": "CATE", "name": "Catestein", "contract": "0xabc",
                "listed_at_ms": 1784505600000, "listed_date": "2026-07-20",
                "age_hours": 9 * 24.0, "price": 0.0037841,
                "change_pct": 12.4321, "quote_volume": 140_981.74}
    base.update(over)
    return NewCoin(**base)


def _result(**over):
    base = {"coins": [], "scanned": 1741, "unresolved": 0, "hidden_by_volume": 0,
                "hidden_by_age": 0, "fetched_at": 0.0, "from_cache": False, "stale": False}
    base.update(over)
    return ScreenResult(**base)


def test_crypto_analysts_exclude_fundamentals(screener):
    assert screener.CRYPTO_ANALYSTS == ("market", "social", "news")


def test_build_crypto_config_routes_prices_to_mexc(screener):
    base = {"data_vendors": {"core_stock_apis": "yfinance",
                             "technical_indicators": "yfinance",
                             "news_data": "yfinance"},
            "llm_provider": "openai", "deep_think_llm": "x", "quick_think_llm": "y",
            "max_debate_rounds": 9, "max_risk_discuss_rounds": 9}
    cfg = screener.build_crypto_config(
        base, provider="google", deep_model="gemini-3.1-flash-lite",
        quick_model="gemini-3.1-flash-lite", debate_rounds=1, risk_rounds=2,
        social_source="Both")

    assert cfg["data_vendors"]["core_stock_apis"] == "mexc"
    assert cfg["data_vendors"]["technical_indicators"] == "mexc"
    assert cfg["data_vendors"]["news_data"] == "yfinance"   # news still Yahoo
    assert cfg["include_twitter"] is True
    assert cfg["llm_provider"] == "google"
    assert cfg["deep_think_llm"] == "gemini-3.1-flash-lite"
    assert cfg["max_debate_rounds"] == 1
    assert cfg["max_risk_discuss_rounds"] == 2


def test_build_crypto_config_does_not_mutate_the_caller(screener):
    """A later stock run in the same process must still route to yfinance."""
    base = {"data_vendors": {"core_stock_apis": "yfinance",
                             "technical_indicators": "yfinance"},
            "llm_provider": "openai", "deep_think_llm": "x", "quick_think_llm": "y",
            "max_debate_rounds": 1, "max_risk_discuss_rounds": 1}
    screener.build_crypto_config(base, provider="google", deep_model="m",
                                 quick_model="m", debate_rounds=1, risk_rounds=1)
    assert base["data_vendors"]["core_stock_apis"] == "yfinance"
    assert base.get("include_twitter") is None


def test_instrument_context_uses_mexc_metadata(screener):
    ctx = screener.coin_instrument_context(_coin())
    assert "CATE" in ctx and "Catestein" in ctx
    assert "0xabc" in ctx
    assert "2026-07-20" in ctx
    assert "crypto" in ctx.lower()


def test_instrument_context_omits_contract_when_absent(screener):
    ctx = screener.coin_instrument_context(_coin(contract=""))
    assert "Contract address" not in ctx


def test_verdict_key_is_symbol_date_and_model_scoped(screener):
    assert (screener.verdict_key("CATEUSDT", "2026-07-29", "gpt-5-mini")
            == "verdict:CATEUSDT:2026-07-29:gpt-5-mini")
    # A different model must produce a different key: reusing another
    # model's cached verdict instead of re-analyzing was a real bug.
    assert (screener.verdict_key("CATEUSDT", "2026-07-29", "glm-5.1")
            != screener.verdict_key("CATEUSDT", "2026-07-29", "gpt-5-mini"))
    assert (screener.report_key("CATEUSDT", "2026-07-29", "glm-5.1")
            == "reports:CATEUSDT:2026-07-29:glm-5.1")


@pytest.mark.parametrize("signal,expected", [
    ("BUY", "▲ BUY"), ("SELL", "▼ SELL"), ("HOLD", "■ HOLD"),
    ("Overweight", "↗ OVERWEIGHT"), ("Underweight", "↘ UNDERWEIGHT"),
    ("buy", "▲ BUY"), ("", "—"), (None, "—"), ("garbage", "—"),
])
def test_verdict_label(screener, signal, expected):
    assert screener.verdict_label(signal) == expected


def test_age_units_cover_hour_day_week(screener):
    assert screener.AGE_UNITS == {"hour": 1, "day": 24, "week": 168}


@pytest.mark.parametrize("value,unit,expected", [
    (1, "hour", 1),
    (36, "hour", 36),
    (1, "day", 24),
    (1, "week", 168),
    (2, "week", 336),
])
def test_to_hours(screener, value, unit, expected):
    assert screener.to_hours(value, unit) == expected


@pytest.mark.parametrize("lo_v,lo_u,hi_v,hi_u,expected", [
    (1, "hour", 1, "week", (1, 168)),      # the user's "1hr to 1 week"
    (1, "day", 1, "week", (24, 168)),      # the user's "1d to 1 week"
    (1, "week", 2, "week", (168, 336)),    # "1 week to 2 weeks"
    (12, "hour", 3, "day", (12, 72)),
])
def test_parse_age_range_accepts_ascending_ranges(screener, lo_v, lo_u, hi_v, hi_u,
                                                  expected):
    lo, hi, error = screener.parse_age_range(lo_v, lo_u, hi_v, hi_u)
    assert error is None
    assert (lo, hi) == expected


@pytest.mark.parametrize("lo_v,lo_u,hi_v,hi_u", [
    (1, "week", 1, "hour"),    # the user's rejected example
    (2, "week", 1, "week"),
    (48, "hour", 1, "day"),
    (1, "day", 1, "day"),      # empty range
])
def test_parse_age_range_rejects_descending_or_empty(screener, lo_v, lo_u, hi_v, hi_u):
    lo, hi, error = screener.parse_age_range(lo_v, lo_u, hi_v, hi_u)
    assert lo is None and hi is None
    assert error is not None
    assert "younger" in error.lower()


def test_parse_age_range_rejects_an_unknown_unit(screener):
    lo, hi, error = screener.parse_age_range(1, "fortnight", 2, "week")
    assert error is not None


def test_parse_age_range_rejects_a_negative_bound(screener):
    lo, hi, error = screener.parse_age_range(-1, "day", 2, "week")
    assert error is not None


@pytest.mark.parametrize("hours,expected", [
    (0.4, "24m"),
    (1.0, "1h"),
    (5.5, "5h"),
    (23.9, "23h"),
    (24.0, "1d"),
    (36.0, "1d 12h"),
    (168.0, "7d"),
    (200.0, "8d"),
    (336.0, "14d"),
    (1440.0, "60d"),
])
def test_fmt_age(screener, hours, expected):
    assert screener.fmt_age(hours) == expected


def test_social_source_options_are_offered_in_cost_order(screener):
    assert screener.SOCIAL_SOURCES[0] == screener.SOURCE_STOCKTWITS
    assert set(screener.SOCIAL_SOURCES) == {
        screener.SOURCE_STOCKTWITS, screener.SOURCE_TWITTER, screener.SOURCE_BOTH}


@pytest.mark.parametrize("choice,stocktwits,twitter", [
    ("StockTwits (free)", True, False),
    ("X / Twitter (paid credits)", False, True),
    ("Both", True, True),
])
def test_social_flags(screener, choice, stocktwits, twitter):
    flags = screener.social_flags(choice)
    assert flags == {"include_stocktwits": stocktwits, "include_twitter": twitter}


def test_social_flags_rejects_an_unknown_choice(screener):
    with pytest.raises(KeyError):
        screener.social_flags("Telepathy")


def test_build_crypto_config_applies_the_source_choice(screener):
    base = {"data_vendors": {}, "llm_provider": "openai", "deep_think_llm": "x",
            "quick_think_llm": "y", "max_debate_rounds": 1, "max_risk_discuss_rounds": 1}
    free = screener.build_crypto_config(
        base, provider="google", deep_model="m", quick_model="m",
        debate_rounds=1, risk_rounds=1, social_source=screener.SOURCE_STOCKTWITS)
    assert free["include_stocktwits"] is True
    assert free["include_twitter"] is False

    paid = screener.build_crypto_config(
        base, provider="google", deep_model="m", quick_model="m",
        debate_rounds=1, risk_rounds=1, social_source=screener.SOURCE_TWITTER)
    assert paid["include_stocktwits"] is False
    assert paid["include_twitter"] is True


def test_build_crypto_config_defaults_to_the_free_source(screener):
    """An omitted choice must not silently spend X credits."""
    base = {"data_vendors": {}, "llm_provider": "openai", "deep_think_llm": "x",
            "quick_think_llm": "y", "max_debate_rounds": 1, "max_risk_discuss_rounds": 1}
    cfg = screener.build_crypto_config(base, provider="google", deep_model="m",
                                       quick_model="m", debate_rounds=1, risk_rounds=1)
    assert cfg["include_twitter"] is False
    assert cfg["include_stocktwits"] is True


def _balance(**over):
    base = {"ok": True, "recharge": 0, "bonus": 280, "total": 280, "error": ""}
    base.update(over)
    return base


def test_credit_summary_converts_credits_to_runs_and_dollars(screener):
    s = screener.credit_summary(_balance(bonus=30_000, total=30_000))
    assert s["runs"] == 100            # 30,000 / 300 credits per run
    assert s["usd"] == pytest.approx(0.30)
    assert s["known"] is True


def test_credit_summary_on_the_real_low_balance(screener):
    s = screener.credit_summary(_balance())
    assert s["runs"] == 0              # 280 credits buys no complete 20-tweet page
    assert s["level"] == "empty"


@pytest.mark.parametrize("total,level", [
    (0, "empty"),
    (280, "empty"),          # under one run's worth
    (300, "low"),            # exactly one run
    (4_500, "low"),          # 15 runs
    (6_000, "ok"),           # 20 runs
    (60_000, "ok"),
])
def test_credit_summary_levels(screener, total, level):
    assert screener.credit_summary(_balance(total=total))["level"] == level


def test_credit_summary_bar_fraction_is_capped(screener):
    assert screener.credit_summary(_balance(total=0))["fraction"] == 0.0
    assert screener.credit_summary(_balance(total=15_000))["fraction"] == pytest.approx(0.5)
    assert screener.credit_summary(_balance(total=999_999))["fraction"] == 1.0


def test_credit_summary_marks_an_unreadable_balance_unknown(screener):
    s = screener.credit_summary(_balance(ok=False, total=0, error="OSError: boom"))
    assert s["known"] is False
    assert s["level"] == "unknown"
    assert "boom" in s["detail"]


def test_credit_summary_notes_bonus_expiry_when_only_bonus_credits_remain(screener):
    s = screener.credit_summary(_balance(recharge=0, bonus=6_000, total=6_000))
    assert "30 days" in s["detail"]


def test_credit_summary_omits_expiry_note_for_recharged_credits(screener):
    s = screener.credit_summary(_balance(recharge=50_000, bonus=0, total=50_000))
    assert "30 days" not in s["detail"]


def test_report_key_is_symbol_date_and_model_scoped(screener):
    assert (screener.report_key("CATEUSDT", "2026-07-29", "gpt-5-mini")
            == "reports:CATEUSDT:2026-07-29:gpt-5-mini")


def test_collect_reports_keeps_only_populated_sections(screener):
    state = {"sentiment_report": "S", "news_report": "", "market_report": "M",
             "final_trade_decision": "D", "fundamentals_report": "IGNORED"}
    reports = screener.collect_reports(state, "D")
    assert reports == {"sentiment_report": "S", "market_report": "M",
                       "final_trade_decision": "D"}


def test_collect_reports_falls_back_to_the_decision_argument(screener):
    """A run whose state lacks the decision still keeps the returned markdown."""
    reports = screener.collect_reports({"sentiment_report": "S"}, "DECISION")
    assert reports["final_trade_decision"] == "DECISION"


def test_collect_reports_is_empty_for_an_empty_state(screener):
    assert screener.collect_reports({}, "") == {}


def test_default_age_range_is_one_hour_to_twenty_four_hours(screener):
    lo, hi, error = screener.parse_age_range(*screener.DEFAULT_AGE_RANGE)
    assert error is None
    assert (lo, hi) == (1, 24)


def test_chart_intervals_offer_minute_to_daily(screener):
    from tradingagents.dataflows.mexc import INTRADAY_INTERVALS
    assert all(v in INTRADAY_INTERVALS for v in screener.CHART_INTERVALS.values())
    assert "1m" in screener.CHART_INTERVALS.values()


def test_chart_refresh_is_frequent_enough_to_feel_live(screener):
    assert 5 <= screener.CHART_REFRESH_SECONDS <= 30


def test_candlestick_chart_builds_from_a_frame(screener):
    import pandas as pd
    df = pd.DataFrame({
        "Date": pd.date_range("2026-07-30", periods=3, freq="1min"),
        "Open": [1.0, 1.1, 1.2], "High": [1.3, 1.3, 1.4],
        "Low": [0.9, 1.0, 1.1], "Close": [1.1, 1.2, 1.15],
        "Volume": [10.0, 20.0, 30.0],
    })
    chart = screener.candlestick_chart(df, "XPLK")
    spec = chart.to_dict()
    assert spec["layer"], "candlestick needs wick and body layers"


def test_chart_summary_reports_last_price_and_change(screener):
    import pandas as pd
    df = pd.DataFrame({
        "Date": pd.date_range("2026-07-30", periods=2, freq="1min"),
        "Open": [1.0, 1.0], "High": [2.0, 2.0], "Low": [0.5, 0.5],
        "Close": [1.0, 1.5], "Volume": [1.0, 1.0],
    })
    text = screener.chart_summary(df)
    assert "1.5" in text
    assert "+50" in text          # 1.0 -> 1.5 across the window


def test_chart_summary_handles_a_single_candle(screener):
    import pandas as pd
    df = pd.DataFrame({"Date": pd.date_range("2026-07-30", periods=1, freq="1min"),
                       "Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0],
                       "Volume": [1.0]})
    assert "1" in screener.chart_summary(df)


def test_upcoming_line_shows_the_countdown(screener):
    line = screener.upcoming_line({"base": "NATG", "name": "NatGold Digital",
                                   "open_ms": 1785409200000, "hours_until": 12.5})
    assert "NATG" in line
    assert "NatGold Digital" in line
    assert "12h" in line or "12.5h" in line


def test_upcoming_line_handles_an_unpublished_time(screener):
    line = screener.upcoming_line({"base": "GRVT", "name": "Grvt",
                                   "open_ms": None, "hours_until": None})
    assert "GRVT" in line
    assert "time" in line.lower()          # says the hour is unknown


def test_upcoming_line_marks_an_imminent_listing(screener):
    line = screener.upcoming_line({"base": "SOON", "name": "Soon", "open_ms": 1,
                                   "hours_until": 0.4})
    assert "24m" in line


def test_poll_interval_is_two_minutes(screener):
    assert screener.POLL_SECONDS == 120


def test_watch_status_line_reports_the_last_check(screener):
    line = screener.watch_status_line(1641, last_poll=1_000.0, now=1_042.0)
    assert "1641" in line
    assert "42s ago" in line


def test_watch_status_line_before_any_check(screener):
    assert "starting" in screener.watch_status_line(0, last_poll=None, now=5.0).lower()


def test_watch_status_line_shows_minutes_once_past_a_minute(screener):
    line = screener.watch_status_line(10, last_poll=0.0, now=185.0)
    assert "3m ago" in line


def test_alert_beep_is_a_playable_wav(screener):
    data = screener.alert_beep_wav()
    assert data[:4] == b"RIFF"
    assert data[8:12] == b"WAVE"
    assert len(data) > 2000          # real samples, not just a header


def test_alert_beep_is_short_enough_to_not_annoy(screener):
    import io
    import wave
    with wave.open(io.BytesIO(screener.alert_beep_wav())) as w:
        seconds = w.getnframes() / w.getframerate()
    assert 0.1 < seconds < 1.5


# --- selectable alert sounds ----------------------------------------------


def test_sound_choices_are_offered_by_name(screener):
    assert "Two-tone beep" in screener.ALERT_SOUNDS
    assert len(screener.ALERT_SOUNDS) >= 4


def test_every_sound_renders_a_playable_wav(screener):
    import io
    import wave
    for name in screener.ALERT_SOUNDS:
        data = screener.alert_beep_wav(name)
        assert data[:4] == b"RIFF", name
        with wave.open(io.BytesIO(data)) as w:
            seconds = w.getnframes() / w.getframerate()
        assert 0.1 < seconds < 3.0, f"{name} is {seconds}s"


def test_sounds_are_distinguishable_from_each_other(screener):
    rendered = {name: screener.alert_beep_wav(name) for name in screener.ALERT_SOUNDS}
    assert len(set(rendered.values())) == len(rendered)


def test_unknown_sound_falls_back_to_the_default(screener):
    assert screener.alert_beep_wav("Kazoo") == screener.alert_beep_wav(
        screener.DEFAULT_ALERT_SOUND)


def test_default_sound_is_one_of_the_choices(screener):
    assert screener.DEFAULT_ALERT_SOUND in screener.ALERT_SOUNDS


def test_alert_message_names_each_new_coin_with_its_age(screener):
    found = [{"symbol": "XPLKUSDT", "base": "XPLK", "name": "xPayLink",
              "age_hours": 0.5, "listed_date": "2026-07-29"},
             {"symbol": "FOOUSDT", "base": "FOO", "name": "Foo Coin",
              "age_hours": 3.0, "listed_date": "2026-07-29"}]
    msg = screener.alert_message(found)
    assert "2 new" in msg
    assert "XPLK" in msg and "FOO" in msg
    assert "30m" in msg              # 0.5h rendered by fmt_age
    assert "3h" in msg


def test_alert_message_is_singular_for_one_coin(screener):
    msg = screener.alert_message([{"symbol": "XPLKUSDT", "base": "XPLK",
                                   "name": "xPayLink", "age_hours": 1.0,
                                   "listed_date": "2026-07-29"}])
    assert "1 new MEXC listing" in msg
    assert "listings" not in msg


def test_alert_message_empty_for_no_coins(screener):
    assert screener.alert_message([]) == ""


def test_source_panels_have_headers_in_reading_order(screener):
    labels = [label for _, label in screener.SOURCE_PANELS]
    keys = [key for key, _ in screener.SOURCE_PANELS]
    assert keys == ["stocktwits", "twitter", "reddit", "news"]
    assert any("StockTwits" in label for label in labels)
    assert any("X / Twitter" in label for label in labels)


def test_collect_reports_keeps_the_raw_sentiment_sources(screener):
    state = {"sentiment_report": "S",
             "sentiment_sources": {"stocktwits": "TWITS", "reddit": "REDDIT"}}
    reports = screener.collect_reports(state, "D")
    assert reports["sentiment_sources"] == {"stocktwits": "TWITS", "reddit": "REDDIT"}


def test_collect_reports_tolerates_a_run_without_sources(screener):
    reports = screener.collect_reports({"sentiment_report": "S"}, "D")
    assert reports.get("sentiment_sources", {}) == {}


def test_source_panel_rows_only_cover_fetched_sources(screener):
    rows = screener.source_panel_rows({"stocktwits": "TWITS", "news": "NEWS"})
    assert [key for key, _, _ in rows] == ["stocktwits", "news"]
    assert rows[0][2] == "TWITS"


def test_source_panel_rows_flag_an_unavailable_source(screener):
    rows = screener.source_panel_rows(
        {"stocktwits": "<no StockTwits messages for $AEON.X in the last 7 days: "
                       "30 older messages ignored, newest was 878 days old>"})
    key, label, body = rows[0]
    assert "unavailable" in label.lower() or "no data" in label.lower()
    assert "878" in body


def test_report_sections_exclude_fundamentals(screener):
    keys = [k for k, _ in screener.REPORT_SECTIONS]
    assert "fundamentals_report" not in keys
    assert "sentiment_report" in keys
    assert "final_trade_decision" in keys


def test_row_cells_formats_price_volume_and_change(screener):
    cells = screener.row_cells(_coin())
    assert cells["symbol"] == "CATE"
    assert cells["name"] == "Catestein"
    assert cells["listed"] == "2026-07-20"
    assert cells["age"] == "9d"
    assert cells["price"] == "0.0037841"
    assert cells["change"] == "+12.43%"
    assert cells["volume"] == "$141.0k"


def test_row_cells_marks_negative_change_and_millions(screener):
    cells = screener.row_cells(_coin(price=1.5, change_pct=-6.1,
                                     quote_volume=2_400_000.0))
    assert cells["change"] == "-6.10%"
    assert cells["volume"] == "$2.4M"


def test_row_cells_handles_tiny_volume(screener):
    cells = screener.row_cells(_coin(quote_volume=812.0))
    assert cells["volume"] == "$812"


def test_status_caption_reports_cache_and_gaps(screener):
    res = _result(unresolved=12, hidden_by_volume=5, hidden_by_age=3,
                  from_cache=True, stale=True)
    caption = screener.status_caption(res)
    assert "1741" in caption
    assert "12" in caption          # unresolved symbols surfaced, not hidden
    assert "5" in caption           # volume-filtered count surfaced
    assert "stale" in caption.lower()


def test_status_caption_stays_quiet_when_nothing_is_wrong(screener):
    res = _result()
    caption = screener.status_caption(res)
    assert "1741" in caption
    assert "could not be checked" not in caption
    assert "stale" not in caption.lower()


def test_page_slice_single_page_when_under_size(screener):
    coins = list(range(5))
    assert screener.page_slice(coins, 0) == (0, 1, coins)


def test_page_slice_splits_at_page_size(screener):
    coins = list(range(45))
    page, total, rows = screener.page_slice(coins, 1)
    assert (page, total) == (1, 3)
    assert rows == coins[20:40]
    assert screener.page_slice(coins, 2)[2] == coins[40:]


def test_page_slice_clamps_a_stale_page(screener):
    coins = list(range(15))
    assert screener.page_slice(coins, 7) == (0, 1, coins)   # shrunken list
    assert screener.page_slice(coins, -3)[0] == 0
    assert screener.page_slice([], 2) == (0, 1, [])


def test_parse_keywords(screener):
    assert screener.parse_keywords("airdrop, listing pump, airdrop") == [
        "airdrop", "listing pump"]
    assert screener.parse_keywords("  , ,") == []
    assert screener.parse_keywords("") == []
    assert screener.parse_keywords(None) == []


def test_build_crypto_config_threads_twitter_keywords(screener):
    base = {"data_vendors": {}, "llm_provider": "x", "deep_think_llm": "x",
            "quick_think_llm": "x", "max_debate_rounds": 1,
            "max_risk_discuss_rounds": 1}
    cfg = screener.build_crypto_config(
        base, provider="google", deep_model="m", quick_model="m",
        debate_rounds=1, risk_rounds=1, twitter_keywords=["airdrop", "big pump"])
    assert cfg["twitter_extra_terms"] == ["airdrop", "big pump"]
    cfg2 = screener.build_crypto_config(
        base, provider="google", deep_model="m", quick_model="m",
        debate_rounds=1, risk_rounds=1)
    assert "twitter_extra_terms" not in cfg2


def test_cached_balance_keeps_last_good_reading_on_failure(screener, monkeypatch):
    """A slow credit endpoint must not flash 'unavailable' over a known balance."""
    from unittest.mock import patch

    class FakeSt:
        session_state: dict = {}

    good = {"ok": True, "recharge": 100_000, "bonus": 0, "total": 100_000}
    bad = {"ok": False, "recharge": 0, "bonus": 0, "total": 0,
           "error": "TimeoutError: The read operation timed out"}

    st = FakeSt()
    from tradingagents.dataflows import twitter
    with patch.object(twitter, "fetch_credit_balance", return_value=good):
        assert screener._cached_balance(st, force=True) == good
    with patch.object(twitter, "fetch_credit_balance", return_value=bad):
        assert screener._cached_balance(st, force=True) == good   # keeps last good
    # with no good reading ever, the failure is what there is to show
    st2 = FakeSt()
    st2.session_state = {}
    with patch.object(twitter, "fetch_credit_balance", return_value=bad):
        assert screener._cached_balance(st2, force=True) == bad
