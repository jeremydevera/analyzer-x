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
    assert "✅" in ok and "250ms" in ok
    deg = app.health_badge({"status": "degraded", "ms": 90})
    assert "⚠️" in deg and "degraded" in deg


def test_provider_for(app):
    assert app.provider_for("gemini-3.1-flash-lite") == "google"
    assert app.provider_for("deepseek-ai/deepseek-v4-flash") == "nvidia"
    assert app.provider_for("glm-4.7") == "ollama"
    # unknown/custom model → falls back to the .env default provider
    assert app.provider_for("some/unknown") == app.DEFAULT_CONFIG["llm_provider"]
    assert app.provider_for("gpt-4o-mini") == "openai"
    assert app.provider_for("qwen3.6-flash") == "qwen"
    assert app.provider_for("glm-5.1") == "maas"
    assert app.provider_for("@cf/meta/llama-3.3-70b-instruct-fp8-fast") == "cloudflare"
    assert app.provider_for("claude-opus-4-8") == "anthropic"
    # providers represented in the dropdown
    assert {app.provider_for(m) for m in app.MODEL_CHOICES} == {
        "google", "nvidia", "ollama", "openai", "qwen", "maas", "cloudflare", "anthropic"}


def test_configure_cfg_ollama(app):
    cfg = app.build_config(app.DEFAULT_CONFIG, provider="ollama", deep_model="glm-4.7",
                           quick_model="glm-4.7", debate_rounds=1, risk_rounds=1)
    app.configure_cfg(cfg, "glm-4.7")
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


def test_provider_status(app):
    # pick two models known to be on the same provider (google)
    g = [m for m in app.MODEL_CHOICES if app.provider_for(m) == "google"]
    assert len(g) >= 2
    # any ok → provider ok
    health = {g[0]: {"status": "ratelimit"}, g[1]: {"status": "ok"}}
    assert app.provider_status("google", health) == "ok"
    # none ok → worst by rank
    health = {g[0]: {"status": "ratelimit"}, g[1]: {"status": "auth"}}
    assert app.provider_status("google", health) == "ratelimit"
    # nothing tested → untested
    assert app.provider_status("google", {}) == "untested"


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
