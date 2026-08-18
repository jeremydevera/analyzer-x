"""Unit tests for app.py pure helpers (no Streamlit runtime needed)."""

import importlib.util
import sys
from pathlib import Path

import pytest

# Load app.py without triggering streamlit page setup (main() is guarded by
# __main__). We only import the module to reach build_config / stage_statuses.
_APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


@pytest.fixture(scope="module")
def app():
    spec = importlib.util.spec_from_file_location("ta_webapp", _APP_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ta_webapp"] = mod
    spec.loader.exec_module(mod)
    return mod


pytestmark = pytest.mark.unit


def test_app_exposes_the_run_analysis_tab_renderer(app):
    """main() must delegate, so a `return` in the run screen cannot skip tab 2."""
    assert callable(app.render_run_analysis_tab)
    assert callable(app.render_crypto_tab)


def test_build_config_overrides(app):
    base = {"llm_provider": "openai", "deep_think_llm": "x", "quick_think_llm": "y",
            "max_debate_rounds": 9, "max_risk_discuss_rounds": 9, "other": "keep"}
    cfg = app.build_config(base, provider="anthropic", deep_model="claude-sonnet-4-6",
                           quick_model="claude-haiku-4-5", debate_rounds=2, risk_rounds=3)
    assert cfg["llm_provider"] == "anthropic"
    assert cfg["deep_think_llm"] == "claude-sonnet-4-6"
    assert cfg["quick_think_llm"] == "claude-haiku-4-5"
    assert cfg["max_debate_rounds"] == 2
    assert cfg["max_risk_discuss_rounds"] == 3
    assert cfg["other"] == "keep"          # untouched keys preserved
    assert base["llm_provider"] == "openai"  # original not mutated


def test_stage_statuses_initial_state(app):
    selected = ["market", "social", "news", "fundamentals"]
    statuses = app.stage_statuses({}, selected)
    labels = [s[0] for s in statuses]
    assert labels[0] == "Market Analyst"
    assert statuses[0][1] == "running"          # first stage runs
    assert all(s[1] == "waiting" for s in statuses[1:])  # rest wait
    assert "Final Decision" in labels


def test_stage_statuses_respects_selection(app):
    statuses = app.stage_statuses({}, ["market"])
    labels = [s[0] for s in statuses]
    assert "Sentiment Analyst" not in labels
    assert "Market Analyst" in labels


def test_stage_statuses_progress_advances(app):
    selected = ["market", "social"]
    state = {"market_report": "done report"}
    statuses = dict(app.stage_statuses(state, selected))
    assert statuses["Market Analyst"] == "done"
    assert statuses["Sentiment Analyst"] == "running"


def test_stage_statuses_final_done(app):
    selected = ["market"]
    state = {
        "market_report": "r",
        "investment_plan": "plan",
        "trader_investment_plan": "trade",
        "investment_debate_state": {"judge_decision": "d"},
        "risk_debate_state": {"judge_decision": "d"},
        "final_trade_decision": "BUY",
    }
    statuses = dict(app.stage_statuses(state, selected))
    assert all(v == "done" for v in statuses.values())


@pytest.mark.parametrize("text,expected", [
    ("FINAL: BUY", "#16C784"),
    ("we should SELL", "#EA3943"),
    ("HOLD for now", "#F0B90B"),
    ("", "#F0B90B"),
])
def test_signal_color(app, text, expected):
    assert app._signal_color(text) == expected


def test_classify_error(app):
    assert app.classify_error("BadRequestError", "Function id 'x': DEGRADED function") == "degraded"
    assert app.classify_error("RateLimitError", "429 too many") == "ratelimit"
    assert app.classify_error("X", "RESOURCE_EXHAUSTED") == "ratelimit"
    assert app.classify_error("AuthenticationError", "401 invalid") == "auth"
    assert app.classify_error("X", "API_KEY_INVALID") == "auth"
    assert app.classify_error("ValueError", "something else") == "error"


def test_health_badge(app):
    assert app.health_badge(None) == "—"
    ok = app.health_badge({"status": "ok", "ms": 250})
    assert "100%" in ok and "250ms" in ok
    deg = app.health_badge({"status": "degraded", "ms": 90})
    assert "0%" in deg and "degraded" in deg
    rl = app.health_badge({"status": "ratelimit", "ms": 90})
    assert "25%" in rl


def test_provider_for(app):
    assert app.provider_for("gemini-3.1-flash-lite") == "google"
    assert app.provider_for("gpt-oss:120b") == "ollama"
    # unknown/custom model → falls back to the .env default provider. The pruned
    # models (nvidia 410s, openai quota-dead) take this path too now.
    assert app.provider_for("some/unknown") == app.DEFAULT_CONFIG["llm_provider"]
    assert app.provider_for("gpt-4o-mini") == app.DEFAULT_CONFIG["llm_provider"]
    assert app.provider_for("qwen3.6-flash") == "qwen"
    assert app.provider_for("glm-5.1") == "maas"
    # providers represented in the dropdown (catalog pruned 2026-08-18 to
    # models that answered a live ping; nvidia 410-Gone and openai
    # quota-exhausted entries removed alongside the earlier cloudflare/anthropic)
    assert {app.provider_for(m) for m in app.MODELS} == {
        "google", "ollama", "qwen", "maas"}


def test_configure_cfg_ollama(app):
    cfg = app.build_config(app.DEFAULT_CONFIG, provider="ollama", deep_model="gpt-oss:120b",
                           quick_model="gpt-oss:120b", debate_rounds=1, risk_rounds=1)
    app.configure_cfg(cfg, "gpt-oss:120b")
    assert cfg["llm_provider"] == "openai_compatible"          # routed via generic client
    assert cfg["backend_url"] == "https://ollama.com/v1"
    # google model gets no backend_url override and no forced api_key
    cfg2 = app.build_config(app.DEFAULT_CONFIG, provider="google", deep_model="gemini-3.5-flash",
                            quick_model="gemini-3.5-flash", debate_rounds=1, risk_rounds=1)
    app.configure_cfg(cfg2, "gemini-3.5-flash")
    assert cfg2["llm_provider"] == "google"
    assert cfg2["backend_url"] is None
    # per-model override wins
    cfg3 = app.build_config(app.DEFAULT_CONFIG, provider="nvidia", deep_model="x",
                            quick_model="x", debate_rounds=1, risk_rounds=1)
    app.configure_cfg(cfg3, "deepseek-ai/deepseek-v4-flash", key_override="nvapi-OVERRIDE")
    assert cfg3["api_key"] == "nvapi-OVERRIDE"


def test_model_options(app):
    opts = app.model_options("gemini-3.1-flash-lite")
    assert opts[0] == "gemini-3.1-flash-lite"                # default first
    assert "gemini-3.5-flash" in opts                        # other choice present
    assert opts[-1] == app.CUSTOM_MODEL
    assert len(opts) == len(set(opts))                       # no duplicates

    # a default not already listed gets prepended, no dupes
    opts2 = app.model_options("some/other-model")
    assert opts2[0] == "some/other-model"
    assert opts2.count("gemini-3.1-flash-lite") == 1


# provider_status / the Engine-capacity bars were removed 2026-07-31: the
# health panel now shows a usability percentage per model row instead.


def test_progress_summary(app):
    selected = ["market", "social"]
    done, total, running = app.progress_summary({}, selected)
    assert done == 0
    assert total == len(app.stage_statuses({}, selected))
    assert running == "Market Analyst"            # first stage runs

    done, total, running = app.progress_summary({"market_report": "r"}, selected)
    assert done == 1
    assert running == "Sentiment Analyst"          # advanced to next


def test_ticker_label_and_parse():
    import tickers as t
    assert t.label_for("AAPL") == "AAPL (Apple Inc.)"
    assert t.label_for("ZZZZ") == "ZZZZ"                 # unknown → bare symbol
    assert t.parse_ticker("AAPL (Apple Inc.)") == "AAPL"
    assert t.parse_ticker("BTC-USD (Bitcoin)") == "BTC-USD"
    assert t.parse_ticker("  msft ") == "MSFT"           # free-typed, normalized
    assert t.parse_ticker("0700.HK") == "0700.HK"


def test_ticker_search():
    import tickers as t
    assert t.search("") == t.options()                       # empty → all
    by_name = t.search("apple")
    assert by_name == ["AAPL (Apple Inc.)"]                  # matches company name
    by_sym = t.search("nvda")
    assert "NVDA (NVIDIA Corp.)" in by_sym                   # matches ticker
    assert t.search("zzzznotareal") == []                    # no match → empty (UI uses raw symbol)


def test_ticker_options_formatted():
    import tickers as t
    opts = t.options()
    assert "NVDA (NVIDIA Corp.)" in opts
    assert all("(" in o or o == o.upper() for o in opts)  # every entry has a name or is a bare symbol
    assert opts == sorted(opts)                            # sorted for the dropdown


def test_safe_markdown_escapes_dollar_signs(app):
    """Streamlit reads $...$ as LaTeX, which garbled every quoted price."""
    out = app.safe_markdown("a high of $5.82 before closing at $1.03")
    assert out == r"a high of \$5.82 before closing at \$1.03"


def test_safe_markdown_handles_empty_input(app):
    assert app.safe_markdown("") == ""
    assert app.safe_markdown(None) == ""


def test_build_config_social_source(app):
    cfg = app.build_config(app.DEFAULT_CONFIG, provider="google", deep_model="m",
                           quick_model="m", debate_rounds=1, risk_rounds=1)
    # default = free source: never spend X credits unless asked
    assert cfg["include_stocktwits"] is True
    assert cfg["include_twitter"] is False
    cfg = app.build_config(app.DEFAULT_CONFIG, provider="google", deep_model="m",
                           quick_model="m", debate_rounds=1, risk_rounds=1,
                           social_source="Both")
    assert cfg["include_stocktwits"] is True
    assert cfg["include_twitter"] is True


def test_confusable_warning_is_quiet_for_routed_tickers():
    """MER no longer needs a warning: it routes to the PSE vendor, which
    serves the real Meralco rather than Yahoo's unrelated Meren Energy."""
    import tickers as t
    assert t.confusable_warning("MER") == ""
    assert t.confusable_warning("AAPL") == ""
    assert t.confusable_warning("") == ""


def test_pse_ticker_switches_the_price_vendor(app):
    cfg = app.build_config(app.DEFAULT_CONFIG, provider="google", deep_model="m",
                           quick_model="m", debate_rounds=1, risk_rounds=1,
                           ticker="MER")
    assert cfg["data_vendors"]["core_stock_apis"] == "pse"
    assert cfg["data_vendors"]["technical_indicators"] == "pse"
    # a US ticker keeps whatever the base config had
    cfg2 = app.build_config(app.DEFAULT_CONFIG, provider="google", deep_model="m",
                            quick_model="m", debate_rounds=1, risk_rounds=1,
                            ticker="AAPL")
    assert cfg2["data_vendors"]["core_stock_apis"] != "pse"


# ============ Auto Trade tab ================================================
def test_auto_trade_page_exists():
    """Operator asked for a dedicated Auto Trade screen: strategy checkboxes,
    a coin multiselect, MEXC keys with a connection test."""
    import app
    assert "Auto Trade" in app.PAGES
    assert hasattr(app, "render_auto_trade_tab")
    keys = [row[0] for row in app.AUTO_STRATEGIES]
    from tradingagents import auto_trader as at
    assert keys, "at least one strategy must be offered"
    # The offered set is the operator's shortlist and changes as evidence
    # changes (2026-08-12: replaced with the 4h sweep winners). What must
    # always hold is that every offered key is one the runner can execute.
    for k in keys:
        assert k in at.STRATEGY_SPECS, f"{k} is offered but the runner cannot run it"


def test_auto_trade_settings_round_trip(tmp_path, monkeypatch):
    import app
    monkeypatch.setattr(app, "AUTO_TRADE_SETTINGS", tmp_path / "auto_trade.json")
    payload = {"strategies": ["ict_fvg"], "coins": ["BTC_USDT", "ETH_USDT"]}
    app._auto_trade_save(payload)
    assert app._auto_trade_load() == payload


def test_auto_trade_load_survives_missing_or_corrupt_file(tmp_path, monkeypatch):
    import app
    monkeypatch.setattr(app, "AUTO_TRADE_SETTINGS", tmp_path / "none.json")
    assert app._auto_trade_load() == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(app, "AUTO_TRADE_SETTINGS", bad)
    assert app._auto_trade_load() == {}
