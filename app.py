"""TradingAgents — Streamlit web UI (professional "trading terminal" design).

Run with:  streamlit run app.py

Wraps TradingAgentsGraph and streams the LangGraph node-by-node so the browser
shows each analyst/researcher/trader stage flip to done as it completes, then
the final BUY / SELL / HOLD decision.

The graph is driven exactly like TradingAgentsGraph._run_graph: build the
initial state via the propagator, then iterate `graph.stream(...)`. Because
get_graph_args() sets stream_mode="values", every chunk is the FULL state
snapshot at that point, so the UI just reads the latest chunk.
"""

from __future__ import annotations

import html
import os
import sys
import traceback
from typing import NamedTuple

import streamlit as st

import model_registry
import tickers as ticker_data
from crypto_screener import (
    SOCIAL_SOURCES,
    SOURCE_STOCKTWITS,
    parse_keywords,
    render_new_crypto_tab,
    social_flags,
    source_panel_rows,
)
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

# --- Stage model -----------------------------------------------------------
ANALYST_STAGES = [
    ("market", "Market Analyst", "market_report"),
    ("social", "Sentiment Analyst", "sentiment_report"),
    ("news", "News Analyst", "news_report"),
    ("fundamentals", "Fundamentals Analyst", "fundamentals_report"),
]
ANALYST_LABELS = {key: label for key, label, _ in ANALYST_STAGES}

# Each model's full client spec: a display `label`, the `provider` string the
# repo's client factory understands, an optional `base_url` override, and the
# env var holding its key. Selecting a model auto-uses its provider — so Gemini,
# NVIDIA, and Ollama-Cloud models can be MIXED in one parallel run, each on its
# own provider + rate-limit quota. (Ollama Cloud is reached via the generic
# OpenAI-compatible client pointed at https://ollama.com/v1.)
_OLLAMA = {"label": "ollama", "provider": "openai_compatible",
           "base_url": "https://ollama.com/v1", "key_env": "OLLAMA_API_KEY"}
_GOOGLE = {"label": "google", "provider": "google", "base_url": None, "key_env": "GOOGLE_API_KEY"}
_NVIDIA = {"label": "nvidia", "provider": "nvidia", "base_url": None, "key_env": "NVIDIA_API_KEY"}
_OPENAI = {"label": "openai", "provider": "openai", "base_url": None, "key_env": "OPENAI_API_KEY"}
_QWEN = {"label": "qwen", "provider": "qwen", "base_url": None, "key_env": "DASHSCOPE_API_KEY"}
# Alibaba MaaS workspace (dedicated host) — OpenAI-compatible; serves glm-5.1 etc.
_MAAS = {"label": "maas", "provider": "openai_compatible",
         "base_url": "https://ws-wu00l7n3hmiafz2q.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
         "key_env": "MAAS_API_KEY"}
# Catalog pruned 2026-07-31 against a live ping of every model (LLM Models tab
# health check). Removed as unresponsive: all Cloudflare @cf/* entries and
# deepseek/deepseek-v4-pro (401 — no valid CLOUDFLARE_API_KEY), claude-opus-4-8
# (no ANTHROPIC_API_KEY), glm-4.7 + qwen3-coder:480b (410 retired by Ollama),
# z-ai/glm-5.1 (410 gone from NVIDIA), moonshotai/kimi-k2.6 (404). Re-add any
# of them on the LLM Models tab if the key/endpoint comes back.
MODELS: dict[str, dict] = {
    "gemini-3.1-flash-lite": _GOOGLE,            # free · fast · clean
    "gemini-3.5-flash": _GOOGLE,                 # free
    "deepseek-ai/deepseek-v4-flash": _NVIDIA,    # NVIDIA NIM
    "deepseek-ai/deepseek-v4-pro": _NVIDIA,      # NVIDIA NIM (slow)
    "gpt-oss:120b": _OLLAMA,                     # Ollama Cloud · free
    "gpt-4o-mini": _OPENAI,                      # OpenAI · cheap (needs billing/credits)
    "gpt-5-mini": _OPENAI,                       # OpenAI · cheap reasoning
    "gpt-5.1": _OPENAI,                          # OpenAI · frontier
    "gpt-5.5": _OPENAI,                          # OpenAI · frontier (needs billing)
    "qwen3.6-flash": _QWEN,                      # Qwen Cloud · cheap · clean
    "qwen3.7-plus": _QWEN,                       # Qwen Cloud · balanced
    "qwen3.7-max": _QWEN,                        # Qwen Cloud · top reasoning/coding
    "glm-5.1": _MAAS,                            # Alibaba MaaS · GLM-5.1 (works here!)
    "deepseek-v4-flash": _MAAS,                  # Alibaba MaaS · DeepSeek V4 Flash
    "deepseek-v4-pro": _MAAS,                    # Alibaba MaaS · DeepSeek V4 Pro
}
CUSTOM_MODEL = "Custom…"


def all_models() -> dict[str, dict]:
    """Built-in catalog merged with models saved on the LLM Models tab."""
    return model_registry.merged_models(MODELS)


def model_choices() -> list[str]:
    """Model ids for the dropdowns — recomputed per rerun so a model added
    on the LLM Models tab appears everywhere immediately."""
    return list(all_models())


def _spec(model: str) -> dict:
    return all_models().get(
        model, {"label": DEFAULT_CONFIG["llm_provider"],
                "provider": DEFAULT_CONFIG["llm_provider"],
                "base_url": DEFAULT_CONFIG.get("backend_url"), "key_env": None})


def provider_for(model: str) -> str:
    """Display label of the provider that serves a model id."""
    return _spec(model)["label"]


def configure_cfg(cfg: dict, model: str, key_override: str = "") -> dict:
    """Set provider / base_url / api_key on a config for `model`'s real provider.
    Ollama-Cloud models pull their key from OLLAMA_API_KEY; an explicit override
    (per-model key field) always wins."""
    s = _spec(model)
    cfg["llm_provider"] = s["provider"]
    cfg["backend_url"] = s["base_url"]
    env_key = os.environ.get(s["key_env"], "") if s["key_env"] else ""
    # Force api_key only when it isn't the provider's own env default (Ollama via
    # openai_compatible) or when the user supplied a per-model override.
    if key_override:
        cfg["api_key"] = key_override
    elif s["provider"] == "openai_compatible" and env_key:
        cfg["api_key"] = env_key
    return cfg


def model_options(default: str) -> list[str]:
    """`default` first, then the model choices, then a Custom sentinel. De-duped."""
    seen: list[str] = []
    for m in [default, *model_choices()]:
        if m and m not in seen:
            seen.append(m)
    return [*seen, CUSTOM_MODEL]


# --- Pure, testable helpers ------------------------------------------------
def build_config(base: dict, *, provider: str, deep_model: str, quick_model: str,
                 debate_rounds: int, risk_rounds: int,
                 social_source: str = SOURCE_STOCKTWITS,
                 twitter_keywords: list[str] | None = None,
                 ticker: str = "") -> dict:
    """base config overlaid with the UI's per-run choices. `.env` still supplies keys.

    ``social_source`` defaults to the free source so a stock run never spends
    X credits unless the user picked X/Twitter or Both in the run settings.
    ``twitter_keywords`` are extra user terms OR'd into the X search.
    """
    cfg = base.copy()
    cfg["llm_provider"] = provider
    cfg["deep_think_llm"] = deep_model
    cfg["quick_think_llm"] = quick_model
    cfg["max_debate_rounds"] = int(debate_rounds)
    cfg["max_risk_discuss_rounds"] = int(risk_rounds)
    cfg.update(social_flags(social_source))
    if twitter_keywords:
        cfg["twitter_extra_terms"] = list(twitter_keywords)
    # PSE names have no Yahoo coverage, so their prices and indicators come
    # from the keyless `pse` vendor instead. Everything else (news, macro)
    # keeps its configured vendor.
    if ticker and ticker_data.is_pse(ticker):
        vendors = dict(cfg.get("data_vendors", {}))
        vendors.update(ticker_data.pse_vendor_overrides())
        cfg["data_vendors"] = vendors
    # One retry for a transient blip, then surface the raw API error fast
    # (high retry counts hide 429s behind long silent backoff).
    cfg.setdefault("max_retries", 1)
    cfg.setdefault("request_timeout", 120)
    return cfg


def _nonempty(value) -> bool:
    return bool(value) and str(value).strip() != ""


def stage_statuses(state: dict, selected: list[str]) -> list[tuple[str, str]]:
    """Map a graph state snapshot to ordered (label, status) pairs.

    status ∈ {done, running, waiting}. First not-done stage = running. Pure.
    """
    state = state or {}
    debate = state.get("investment_debate_state") or {}
    risk = state.get("risk_debate_state") or {}

    stages: list[tuple[str, bool]] = []
    for key, label, report_key in ANALYST_STAGES:
        if key in selected:
            stages.append((label, _nonempty(state.get(report_key))))
    stages.append((
        "Bull / Bear Debate",
        _nonempty(debate.get("judge_decision")) or _nonempty(state.get("investment_plan")),
    ))
    stages.append(("Research Manager", _nonempty(state.get("investment_plan"))))
    stages.append(("Trader", _nonempty(state.get("trader_investment_plan"))))
    stages.append((
        "Risk Debate",
        _nonempty(risk.get("judge_decision")) or _nonempty(state.get("final_trade_decision")),
    ))
    stages.append(("Final Decision", _nonempty(state.get("final_trade_decision"))))

    out: list[tuple[str, str]] = []
    running_assigned = False
    for label, done in stages:
        if done:
            out.append((label, "done"))
        elif not running_assigned:
            out.append((label, "running"))
            running_assigned = True
        else:
            out.append((label, "waiting"))
    return out


def progress_summary(state: dict, selected: list[str]) -> tuple[int, int, str]:
    """(#done, #total, current_running_label) from a state snapshot. Pure."""
    statuses = stage_statuses(state, selected)
    done = sum(1 for _, s in statuses if s == "done")
    running = next((label for label, s in statuses if s == "running"), "")
    return done, len(statuses), running


def _signal_color(signal: str) -> str:
    s = (signal or "").upper()
    if "BUY" in s:
        return "#16C784"   # buy green
    if "SELL" in s:
        return "#EA3943"   # sell red
    return "#F0B90B"       # hold amber


# status → (usability percentage, color). Providers expose no exact quota, so
# the percentage reads as "how usable right now": 100 = responding, 25 =
# alive but rate-limited/needs credits, 0 = down / no key / gone.
HEALTH_PCT = {"ok": ("100%", "#16a34a"), "ratelimit": ("25%", "#B45309"),
              "degraded": ("0%", "#bd413f"), "auth": ("0%", "#bd413f"),
              "error": ("0%", "#bd413f")}


def classify_error(name: str, msg: str) -> str:
    """Bucket an exception (type name + message) into a health status. Pure."""
    if "DEGRADED" in msg:
        return "degraded"
    if "429" in msg or "RateLimit" in name or "rate_limit" in msg or "RESOURCE_EXHAUSTED" in msg:
        return "ratelimit"
    if "401" in msg or "403" in msg or "Authentication" in name or "API_KEY" in msg or "PERMISSION_DENIED" in msg:
        return "auth"
    return "error"


def health_badge(result: dict | None) -> str:
    """Render a health result as a colored percentage + status + latency. Pure."""
    if not result:
        return "—"
    status = result.get("status", "error")
    pct, color = HEALTH_PCT.get(status, HEALTH_PCT["error"])
    return (f"<span style='color:{color};font-weight:700'>{pct}</span> · "
            f"{status} · {result.get('ms', '?')}ms")


# --- Design system (CSS) ---------------------------------------------------
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Mulish:wght@300;400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500&display=swap');

/* Celebrately-style terminal: neutral near-white surfaces, near-black ink,
   one cobalt accent, hairline rules. One sans (Mulish) does both display and
   body work; IBM Plex Mono keeps columns of prices aligned digit for digit. */
:root {
  --bg:#fafafa;            /* neutral near-white */
  --panel:#ffffff;
  --panel-2:#f6f6f4;
  --sidebar:#f6f6f4;
  --border:#e7e7ea;
  --border-soft:#f0f0f2;
  --border-strong:#d4d4d8;
  --text:#1a1a1a;          /* ink, not pure black */
  --muted:#71717a;
  --faint:#a1a1aa;
  --accent:#1E5BD6;        /* cobalt */
  --accent-dim:#174ab0;
  --accent-wash:#e7eefc;
  --buy:#16a34a; --sell:#bd413f; --hold:#9A5B08;
  --font-display:'Mulish','Helvetica Neue',Helvetica,Arial,sans-serif;
  --font-body:'Mulish','Helvetica Neue',Helvetica,Arial,sans-serif;
  --font-mono:'IBM Plex Mono',ui-monospace,monospace;
  --r:8px;
  --s:8px;
  --field:280px;           /* one field width, so the forms line up */
}

[data-testid="stAppViewContainer"]{ background:var(--bg); }
html, body, [data-testid="stAppViewContainer"]{
  color:var(--text); font-family:var(--font-body); font-size:14px;
  -webkit-font-smoothing:antialiased;
}
#MainMenu, footer, [data-testid="stDecoration"],
[data-testid="stAppDeployButton"], .stDeployButton, [data-testid="stStatusWidget"]{ display:none !important; }
[data-testid="stHeader"]{ background:transparent !important; }
.block-container{ padding-top:calc(var(--s) * 2); max-width:1600px; }

/* One sans throughout; headings differ by weight, not family — heavier Mulish
   makes a verdict read as a statement without switching typefaces. */
h1,h2,h3,h4{ font-family:var(--font-display); font-weight:700; color:var(--text);
  letter-spacing:-.01em; }
h3{ font-size:20px; } h4{ font-size:16px; }

/* Numbers everywhere are tabular: a price column that shifts as digits change
   is unreadable at a glance. */
[data-testid="stMarkdownContainer"] code, .ta-chip, .ta-stage .tag,
input, [data-baseweb="select"]{ font-variant-numeric:tabular-nums; }

/* ---- Masthead ---- */
.ta-header{ display:flex; align-items:baseline; gap:calc(var(--s) * 1.5);
  padding:var(--s) 0 0; }
.ta-mark{
  width:28px;height:28px;border-radius:var(--r); display:grid;place-items:center;
  background:var(--text); color:var(--bg);
  font-family:var(--font-display); font-weight:600; font-size:15px;
  align-self:center;
}
.ta-title{ font-family:var(--font-display); font-weight:600; font-size:22px; line-height:1; }
.ta-title .dim{ color:var(--accent); }
.ta-sub{ color:var(--muted); font-size:12.5px; margin-top:3px; }
.ta-rule{ height:1px; background:var(--border); margin:calc(var(--s) * 2) 0; }
.ta-label{
  font-family:var(--font-mono); font-size:10px; letter-spacing:.1em;
  text-transform:uppercase; color:var(--faint);
  margin:calc(var(--s) * 2) 0 calc(var(--s) / 2);
}

/* ---- Section rule: separates the three jobs of the Trade tab ---- */
.ta-section{
  font-family:var(--font-mono); font-size:10px; letter-spacing:.14em;
  text-transform:uppercase; color:var(--faint); font-weight:500;
  margin:calc(var(--s) * 4) 0 calc(var(--s) * 1.5);
  padding-bottom:6px; border-bottom:1px solid var(--border);
}

/* ---- Command strip: the state, and the one action that acts on it ----
   Given a raised surface and a left accent so the primary control reads as the
   top of the page rather than as one more row of buttons. */
.st-key-command_strip{
  background:var(--panel); border:1px solid var(--border);
  border-left:3px solid var(--ink); border-radius:var(--r);
  padding:calc(var(--s) * 1.75) calc(var(--s) * 2);
  margin-bottom:var(--s);
}
.st-key-command_strip > [data-testid="stHorizontalBlock"],
.st-key-command_strip > div > [data-testid="stHorizontalBlock"]{
  align-items:center;
}
.ta-metric{ display:flex; flex-direction:column; gap:3px; }
.ta-metric span{
  font-family:var(--font-mono); font-size:9.5px; letter-spacing:.1em;
  text-transform:uppercase; color:var(--faint);
}
.ta-metric b{
  font-family:var(--font-mono); font-size:17px; font-weight:600;
  color:var(--ink); font-variant-numeric:tabular-nums; line-height:1.1;
}
/* The primary action carries weight; the stop is quiet until it is needed. */
.st-key-cs_start button{ font-weight:700; letter-spacing:.02em; }

/* ---- Plan lanes: a tick-list of timeframes, each with its own approach ---- */
.st-key-plan_box{
  background:var(--panel); border:1px solid var(--border);
  border-radius:var(--r); padding:calc(var(--s) * 1.75) calc(var(--s) * 2);
}
.ta-lane{
  font-family:var(--font-mono); font-size:10px; letter-spacing:.09em;
  text-transform:uppercase; color:var(--faint); margin-bottom:5px;
}
.ta-fit{
  font-family:var(--font-mono); font-size:10px; letter-spacing:.06em;
  margin-top:5px;
}
.ta-fit.ok{ color:var(--buy); }
.ta-fit.warn{ color:#B45309; }
.ta-fit.bad{ color:var(--sell); }

/* ---- Chips ---- */
.ta-meta{ display:flex; gap:var(--s); flex-wrap:wrap; margin-bottom:calc(var(--s) * 2); }
.ta-chip{
  font-family:var(--font-mono); font-size:11.5px; color:var(--text);
  background:var(--panel); border:1px solid var(--border); border-radius:var(--r);
  padding:5px 9px;
}
.ta-chip b{ color:var(--faint); font-weight:500; margin-right:6px;
  text-transform:uppercase; letter-spacing:.08em; font-size:9.5px; }

/* ---- Cards ---- */
.ta-card{
  background:var(--panel); border:1px solid var(--border); border-radius:var(--r);
  padding:calc(var(--s) * 2);
}
.ta-card h4{ margin:0 0 var(--s); font-family:var(--font-mono); font-size:10px;
  letter-spacing:.1em; text-transform:uppercase; color:var(--faint); font-weight:500; }

/* ---- Stage list ---- */
.ta-stage{ display:flex; align-items:center; gap:var(--s);
  padding:7px 2px; border-bottom:1px solid var(--border-soft); }
.ta-stage:last-child{ border-bottom:none; }
.ta-dot{ width:7px;height:7px;border-radius:50%; flex:0 0 auto; }
.ta-stage .lbl{ font-size:13.5px; }
.ta-stage .tag{ margin-left:auto; font-family:var(--font-mono); font-size:9.5px;
  letter-spacing:.1em; text-transform:uppercase; }
.s-done .ta-dot{ background:var(--buy); }
.s-done .lbl{ color:var(--text); }    .s-done .tag{ color:var(--buy); }
.s-run .ta-dot{ background:var(--accent); animation:pulse 1.2s infinite; }
.s-run .lbl{ color:var(--text); font-weight:600; } .s-run .tag{ color:var(--accent); }
.s-wait .ta-dot{ background:var(--border-strong); } .s-wait .lbl{ color:var(--faint); }
.s-wait .tag{ color:var(--faint); }
@keyframes pulse{ 0%,100%{ box-shadow:0 0 0 0 rgba(30,91,214,.35);} 50%{ box-shadow:0 0 0 5px rgba(30,91,214,0);} }

/* ---- Verdict ---- */
.ta-decision{
  border-radius:var(--r); padding:calc(var(--s) * 3); margin:var(--s) 0;
  border:1px solid var(--border); background:var(--panel);
  border-left:3px solid var(--accent);
}
.ta-decision .k{ font-family:var(--font-mono); font-size:10px; letter-spacing:.14em;
  color:var(--faint); text-transform:uppercase; }
.ta-decision .v{ font-family:var(--font-display); font-weight:600; font-size:42px;
  line-height:1.05; margin-top:6px; letter-spacing:-.02em; }
.ta-decision .ticker{ font-family:var(--font-mono); font-size:12.5px; color:var(--muted);
  margin-top:var(--s); }

/* ---- Tabs: quiet pills, no underline rail ---- */
[data-baseweb="tab-list"]{ gap:4px !important;
  border-bottom:none !important; background:transparent !important; }
[data-baseweb="tab"]{ padding:3px 12px !important; font-size:14px; line-height:20px;
  color:#525252; background:transparent !important; border-radius:6px !important;
  transition:background .12s, color .12s; }
[data-baseweb="tab"]:hover{ background:#f4f4f5 !important; color:#171717; }
[data-baseweb="tab"][aria-selected="true"]{ background:#ededed !important;
  color:#171717; font-weight:600; }
[data-baseweb="tab-highlight"], [data-baseweb="tab-border"]{ display:none !important; }

/* ---- Fields: one width, not the whole column ----
   Streamlit stretches every widget to its container. Capping them keeps a form
   readable: an eight-character number input has no business being 700px wide. */
[data-testid="stSelectbox"] [data-testid="stWidgetLabel"] p,
[data-testid="stNumberInput"] [data-testid="stWidgetLabel"] p,
[data-testid="stDateInput"] [data-testid="stWidgetLabel"] p,
[data-testid="stTextInput"] [data-testid="stWidgetLabel"] p,
[data-testid="stMultiSelect"] [data-testid="stWidgetLabel"] p{
  font-family:var(--font-mono); color:var(--faint) !important; font-weight:500 !important;
  font-size:10px !important; text-transform:uppercase; letter-spacing:.1em;
}
/* Checkbox and radio text is a choice, not a field name — left in sentence case,
   since uppercasing "Show all (incl. dust)" reads as shouting. */
[data-testid="stCheckbox"] p, [data-testid="stRadio"] p{ font-size:13px !important; }

/* Field widths sized to their content: a model id needs room, a round count
   does not. */
[data-testid="stSelectbox"], [data-testid="stTextInput"]{ max-width:340px; }
[data-testid="stDateInput"]{ max-width:180px; }
[data-testid="stNumberInput"]{ max-width:150px; }
[data-testid="stMultiSelect"]{ max-width:620px; }
[data-baseweb="tag"]{
  background:var(--accent-wash) !important; color:var(--accent-dim) !important;
  border:1px solid #c8d8f7 !important; border-radius:4px !important;
  font-size:12px !important; font-weight:500 !important;
}
[data-baseweb="tag"] span, [data-baseweb="tag"] svg{ color:var(--accent-dim) !important; }
[data-baseweb="input"], [data-baseweb="base-input"], [data-baseweb="select"] > div,
[data-baseweb="textarea"]{
  background:var(--panel) !important;
  border:1px solid var(--border-strong) !important;
  border-radius:var(--r) !important;
  min-height:34px !important;
  transition:border-color .12s ease, box-shadow .12s ease;
}
[data-baseweb="input"] > div, [data-baseweb="select"] > div > div{
  border:none !important; background:transparent !important;
}
[data-baseweb="input"]:hover, [data-baseweb="select"] > div:hover{ border-color:#b6b6bd !important; }
[data-baseweb="input"]:focus-within, [data-baseweb="base-input"]:focus-within,
[data-baseweb="select"] > div:focus-within{
  border-color:var(--accent) !important; box-shadow:0 0 0 3px rgba(30,91,214,.14) !important;
}
input, [data-baseweb="select"]{ font-family:var(--font-mono) !important;
  color:var(--text) !important; font-size:13px !important; }
input::placeholder{ color:var(--faint) !important; }
[data-testid="stNumberInputStepUp"], [data-testid="stNumberInputStepDown"]{
  border-color:var(--border-strong) !important; background:var(--panel-2) !important;
  color:var(--muted) !important;
}
/* Dropdown menus: same paper, same hairlines */
[data-baseweb="popover"] [role="listbox"], [data-baseweb="menu"]{
  background:var(--panel) !important; border:1px solid var(--border-strong) !important;
  border-radius:var(--r) !important;
}
[role="option"]{ font-family:var(--font-mono) !important; font-size:12.5px !important; }
[role="option"]:hover{ background:var(--accent-wash) !important; }

/* ---- Buttons: sized to their label ---- */
.stButton{ width:auto !important; }
.stButton>button{
  width:auto !important; min-width:0 !important;
  background:var(--panel) !important; color:var(--text) !important;
  border:1px solid var(--border-strong) !important; border-radius:var(--r) !important;
  font-family:var(--font-body) !important; font-weight:500 !important; font-size:12.5px !important;
  padding:6px 14px !important; min-height:34px !important; box-shadow:none !important;
}
.stButton>button:hover{ border-color:var(--accent) !important; color:var(--accent) !important;
  background:var(--accent-wash) !important; }
.stButton>button[kind="primary"]{
  background:var(--text) !important; color:var(--bg) !important;
  border-color:var(--text) !important; font-weight:600 !important;
}
.stButton>button[kind="primary"]:hover{ background:var(--accent) !important;
  border-color:var(--accent) !important; color:#fff !important; }

/* ---- Data rows ---- */
[data-testid="stHorizontalBlock"]{ align-items:center; }
/* …but never page-layout rows: centering a short column against a tall one
   (announcements vs table) floats it into the middle of the screen. Layout
   rows are opted out by container key; direct-child chains so the data rows
   inside those columns keep their centering. */
.st-key-crypto_layout > [data-testid="stHorizontalBlock"],
.st-key-crypto_layout > div > [data-testid="stHorizontalBlock"],
.st-key-run_stream_layout > [data-testid="stHorizontalBlock"],
.st-key-run_stream_layout > div > [data-testid="stHorizontalBlock"],
.st-key-trade_layout > [data-testid="stHorizontalBlock"],
.st-key-trade_layout > div > [data-testid="stHorizontalBlock"]{
  align-items:flex-start;
}
[data-testid="stVerticalBlock"] > [data-testid="stHorizontalBlock"]{
  border-bottom:1px solid var(--border-soft); padding:1px 0;
}
[data-testid="stVerticalBlock"] > [data-testid="stHorizontalBlock"]:hover{
  background:var(--panel);
}
[data-testid="stVerticalBlock"] > [data-testid="stHorizontalBlock"] p{ font-size:13px; }

/* ---- Containers ---- */
[data-testid="stExpander"]{
  border:1px solid var(--border) !important; border-radius:var(--r) !important;
  background:var(--panel);
}
[data-testid="stExpander"] summary{ font-family:var(--font-body); font-size:13px; }
/* Report sections behave like chat bubbles: a fixed max height, long text
   scrolls inside instead of stretching the page to the floor. */
[data-testid="stExpanderDetails"]{
  max-height:420px; overflow-y:auto; overscroll-behavior:contain;
}
[data-testid="stSidebar"]{ background:var(--sidebar); border-right:1px solid var(--border); }
/* Alerts: the tint lives on stAlertContainer, so severity is a left edge on paper */
[data-testid="stAlert"]{
  border-radius:var(--r) !important; border:1px solid var(--border) !important;
  background:var(--panel) !important; border-left:2px solid var(--accent) !important;
}
[data-testid="stAlertContainer"]{ background:transparent !important; }
[data-testid="stAlert"] p, [data-testid="stAlert"] div{ color:var(--text) !important; }
[data-testid="stAlert"]:has([data-testid="stAlertContentSuccess"]){ border-left-color:var(--buy) !important; }
[data-testid="stAlert"]:has([data-testid="stAlertContentError"]){ border-left-color:var(--sell) !important; }
[data-testid="stAlert"]:has([data-testid="stAlertContentWarning"]){ border-left-color:var(--hold) !important; }
[data-testid="stCaptionContainer"]{ color:var(--muted) !important; font-size:12px; }
code, pre, .stMarkdown code{ font-family:var(--font-mono) !important; font-size:12px;
  background:var(--panel-2) !important; }
a{ color:var(--accent); text-decoration:none; }
a:hover{ text-decoration:underline; }
hr{ border-color:var(--border); }

/* ---- Top navigation: brand row, then screen tabs as quiet pills ---- */
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"],
[data-testid="stSidebarCollapseButton"]{ display:none !important; }
.ta-brand{ display:flex; align-items:center; gap:10px; padding:0 0 var(--s); }
.ta-brand .ta-mark{ width:34px;height:34px;background:var(--accent); color:#fff;
  border-radius:8px; font-size:16px; }
.ta-brand-name{ font-family:var(--font-display); font-size:16px; font-weight:700;
  line-height:1.1; }
.ta-brand-sub{ font-family:var(--font-mono); font-size:9px; letter-spacing:.16em;
  text-transform:uppercase; color:var(--faint); margin-top:3px; }

/* The nav radio reads as tabs: same quiet pills as the report tabs above */
.st-key-nav_page [role="radiogroup"]{ display:flex; gap:4px !important; }
.st-key-nav_page [role="radiogroup"] label{
  padding:3px 12px !important; border-radius:6px; cursor:pointer;
  transition:background .12s, color .12s;
}
.st-key-nav_page [role="radiogroup"] label p{ font-size:14px !important;
  line-height:20px; color:#525252; }
.st-key-nav_page [role="radiogroup"] label:hover{ background:#f4f4f5; }
.st-key-nav_page [role="radiogroup"] label:has(input:checked){
  background:#ededed;
}
.st-key-nav_page [role="radiogroup"] label:has(input:checked) p{
  font-weight:600 !important;
}
/* The radio dots would read as form controls in a tab row */
.st-key-nav_page [role="radiogroup"] label > div:first-child{ display:none !important; }
.st-key-nav_page [data-testid="stWidgetLabel"]{ display:none; }

/* ---- Page title ---- */
.ta-page-title{
  font-family:var(--font-display); font-size:26px; font-weight:700;
  letter-spacing:-.015em; margin:0 0 calc(var(--s) * 2);
}


/* ---- Table ---- */
.ta-th{
  font-size:11px; letter-spacing:.1em; font-weight:600;
  text-transform:uppercase; color:var(--muted); padding-bottom:6px;
}
/* Markdown tables in reports: hairline rows, uppercase letterspaced headers,
   a whisper of accent on row hover — no vertical rules, no zebra striping. */
.stMarkdown table{ width:100%; border-collapse:collapse; font-size:14px;
  border:none !important; }
.stMarkdown th{ text-align:left; padding:13px 16px; font-size:11px;
  letter-spacing:.1em; text-transform:uppercase; color:var(--muted);
  border:none !important; border-bottom:1px solid var(--border) !important;
  font-weight:600; white-space:nowrap; background:transparent !important; }
.stMarkdown td{ padding:14px 16px; border:none !important;
  border-bottom:1px solid var(--border) !important; vertical-align:middle; }
.stMarkdown tr:last-child td{ border-bottom:none !important; }
.stMarkdown tbody tr:hover td{ background:var(--panel-2); }
[data-testid="stVerticalBlock"] > [data-testid="stHorizontalBlock"]{ padding:3px 0; }
/* The symbol cell is a button, but it should read as a link in a table */
[data-testid="stHorizontalBlock"] .stButton>button{ padding:4px 9px !important;
  min-height:28px !important; font-size:12px !important; }

/* ---- Right-hand run panel ---- */
[data-testid="stVerticalBlockBorderWrapper"]{
  background:var(--panel); border-color:var(--border) !important; border-radius:var(--r);
}
.ta-panel-title{
  font-family:var(--font-mono); font-size:9.5px; letter-spacing:.12em;
  text-transform:uppercase; color:var(--faint); margin-bottom:var(--s);
}
/* Inside the narrow panel a field should fill its column, not stop at 340px */
[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stSelectbox"],
[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stDateInput"],
[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stTextInput"],
[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stNumberInput"]{
  max-width:100%;
}
[data-testid="stVerticalBlockBorderWrapper"] [role="radiogroup"]{ gap:2px !important; }
[data-testid="stVerticalBlockBorderWrapper"] [role="radiogroup"] p{ font-size:12.5px !important; }
</style>
"""


def header_html() -> str:
    return (
        '<div class="ta-header">'
        '<div class="ta-mark">◈</div>'
        '<div><div class="ta-title">Trading<span class="dim">Agents</span></div>'
        '<div class="ta-sub">Multi-agent LLM equity & crypto analysis · local terminal</div></div>'
        '</div><div class="ta-rule"></div>'
    )


def meta_bar(ticker: str, date: str, provider: str, deep: str, analysts: int) -> str:
    def chip(k, v):
        return f'<div class="ta-chip"><b>{k}</b>{html.escape(str(v))}</div>'
    return ('<div class="ta-meta">'
            + chip("Ticker", ticker) + chip("Date", date) + chip("Provider", provider)
            + chip("Deep model", deep) + chip("Analysts", analysts) + "</div>")


def render_progress(container, state: dict, selected: list[str]) -> None:
    cls = {"done": "s-done", "running": "s-run", "waiting": "s-wait"}
    tagtxt = {"done": "done", "running": "running", "waiting": "queued"}
    rows = ""
    for label, status in stage_statuses(state, selected):
        rows += (f'<div class="ta-stage {cls[status]}"><span class="ta-dot"></span>'
                 f'<span class="lbl">{html.escape(label)}</span>'
                 f'<span class="tag">{tagtxt[status]}</span></div>')
    container.markdown(f'<div class="ta-card"><h4>Pipeline</h4>{rows}</div>',
                       unsafe_allow_html=True)


def safe_markdown(text: str) -> str:
    """Escape dollar signs so prices are not parsed as LaTeX.

    Streamlit renders ``$...$`` as maths, so a report quoting "a high of $5.82
    before closing at $1.03" had everything between the two dollar signs turned
    into italic maths glyphs — unreadable exactly where the numbers matter.
    """
    return (text or "").replace("$", r"\$")


def render_reports(container, state: dict) -> None:
    state = state or {}
    debate = state.get("investment_debate_state") or {}
    risk = state.get("risk_debate_state") or {}
    sections: list[tuple[str, str]] = []
    for label, key in [
        ("Market Analyst", "market_report"),
        ("Sentiment Analyst", "sentiment_report"),
        ("News Analyst", "news_report"),
        ("Fundamentals Analyst", "fundamentals_report"),
    ]:
        if _nonempty(state.get(key)):
            sections.append((label, state[key]))
    if _nonempty(debate.get("bull_history")):
        sections.append(("Bull Researcher", debate["bull_history"]))
    if _nonempty(debate.get("bear_history")):
        sections.append(("Bear Researcher", debate["bear_history"]))
    if _nonempty(state.get("investment_plan")):
        sections.append(("Research Manager — Plan", state["investment_plan"]))
    if _nonempty(state.get("trader_investment_plan")):
        sections.append(("Trader — Proposal", state["trader_investment_plan"]))
    for label, rkey in [
        ("Risk — Aggressive", "aggressive_history"),
        ("Risk — Conservative", "conservative_history"),
        ("Risk — Neutral", "neutral_history"),
    ]:
        if _nonempty(risk.get(rkey)):
            sections.append((label, risk[rkey]))

    with container.container():
        if not sections:
            st.markdown(
                '<div class="ta-card"><h4>Reports</h4>'
                '<div style="color:var(--muted);font-size:14px">Each agent\'s report '
                'streams in here as it finishes.</div></div>', unsafe_allow_html=True)
            return
        sources = source_panel_rows(state.get("sentiment_sources") or {})
        for i, (label, content) in enumerate(sections):
            with st.expander(label, expanded=(i == len(sections) - 1)):
                st.markdown(safe_markdown(content))
                # Raw posts live under the narrative that used them, so a claim
                # about X sentiment is checkable in place. Tabs, not expanders:
                # Streamlit cannot nest an expander inside an expander.
                if "Sentiment Analyst" in label and sources:
                    st.markdown("###### Source data the analyst read")
                    tabs = st.tabs([lab for _, lab, _ in sources])
                    for tab, (_, _, body) in zip(tabs, sources):
                        tab.code(body, language=None)


def render_decision(container, ticker: str, date: str, signal: str) -> None:
    color = _signal_color(signal)
    label = signal.upper() if _nonempty(signal) else "SEE REPORT"
    container.markdown(
        f'<div class="ta-decision" style="background:'
        f'linear-gradient(135deg,{color}22,{color}0D);box-shadow:inset 0 0 0 1px {color}55;">'
        f'<div class="k">Final decision</div>'
        f'<div class="v" style="color:{color}">{html.escape(label)}</div>'
        f'<div class="ticker">{html.escape(ticker)} · {html.escape(date)}</div></div>',
        unsafe_allow_html=True)


def ping_model(model: str) -> dict:
    """Fire a tiny live request at one model on its OWN provider/endpoint/key.
    Returns {status, ms, detail}."""
    import time
    from tradingagents.llm_clients.factory import create_llm_client
    s = _spec(model)
    env_key = os.environ.get(s["key_env"], "") if s["key_env"] else ""
    kw = {"api_key": env_key} if (env_key and s["provider"] == "openai_compatible") else {}
    t0 = time.monotonic()
    try:
        cl = create_llm_client(provider=s["provider"], model=model, base_url=s["base_url"], **kw)
        out = cl.get_llm().invoke("Reply with one word: ok")
        ms = int((time.monotonic() - t0) * 1000)
        return {"status": "ok", "ms": ms, "detail": str(getattr(out, "content", ""))[:50]}
    except Exception as exc:  # noqa: BLE001
        ms = int((time.monotonic() - t0) * 1000)
        return {"status": classify_error(type(exc).__name__, str(exc)), "ms": ms,
                "detail": raw_error(exc)}        # verbatim API/SDK message


def _health_line(res: dict | None) -> str:
    line = health_badge(res)
    if res and res.get("status") != "ok":
        line += f"\n\n{res.get('detail', '')}"      # full verbatim API message
    return line


def render_health_panel() -> None:
    """Model list with a 'Test' button and a live usability percentage per row.
    Each model pings its OWN provider; rows update LIVE via as_completed."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    st.markdown("#### Model health")
    st.caption("Live ping each model on its own provider — the percentage says "
               "how usable it is right now (100 = responding, 25 = rate-limited "
               "or needs credits, 0 = down / no key).")
    test_all = st.button("Test ALL models (parallel)", key="test_all", type="primary")

    # Build rows with a placeholder per status cell so we can update them live.
    slots: dict[str, object] = {}
    for m in model_choices():
        c1, c2, c3 = st.columns([4, 1, 4])
        c1.markdown(f"`{m}`  ·  _{provider_for(m)}_")
        single = c2.button("Test", key=f"test_{m}")
        slots[m] = c3.empty()
        if single:
            slots[m].markdown("testing…")
            st.session_state[f"health_{m}"] = ping_model(m)
        slots[m].markdown(_health_line(st.session_state.get(f"health_{m}")),
                          unsafe_allow_html=True)

    if test_all:
        if st.button("Stop tests", key="stop_tests",
                     help="Abandon the in-flight tests (effective at the next model finishing)."):
            st.rerun()
        for m in model_choices():                       # all flip to testing at once…
            slots[m].markdown("testing…")
        with ThreadPoolExecutor(max_workers=len(model_choices())) as ex:
            futs = {ex.submit(ping_model, m): m for m in model_choices()}
            for fut in as_completed(futs):            # …and resolve as each finishes
                m = futs[fut]
                res = fut.result()
                st.session_state[f"health_{m}"] = res
                slots[m].markdown(_health_line(res), unsafe_allow_html=True)


def raw_error(exc: BaseException) -> str:
    """The raw error as the API/SDK reported it (includes the response body,
    e.g. 'RateLimitError: Error code: 429 - {...}'). No rewriting."""
    return f"{type(exc).__name__}: {exc}"


def _report_sig(state: dict) -> int:
    """Cheap change-signature of a state's report content (to skip redundant
    report re-renders during the poll loop — avoids expander flicker)."""
    state = state or {}
    deb = state.get("investment_debate_state") or {}
    risk = state.get("risk_debate_state") or {}
    n = sum(len(str(state.get(k, ""))) for k in (
        "market_report", "sentiment_report", "news_report", "fundamentals_report",
        "investment_plan", "trader_investment_plan", "final_trade_decision"))
    n += len(str(deb.get("bull_history", ""))) + len(str(deb.get("bear_history", "")))
    n += sum(len(str(risk.get(k, ""))) for k in
             ("aggressive_history", "conservative_history", "neutral_history"))
    return n


def _summary_card(model: str, label: str, color: str, sub: str) -> str:
    return (f"<div style='flex:1;min-width:150px;border:1px solid {color}55;border-radius:12px;"
            f"padding:12px 14px;background:{color}14'>"
            f"<div style='font-family:var(--font-mono);font-size:10.5px;color:var(--muted)'>{html.escape(model)}</div>"
            f"<div style='color:{color};font-family:var(--font-display);font-weight:800;font-size:24px;"
            f"margin-top:3px'>{html.escape(label)}</div>"
            f"<div style='font-size:11px;color:var(--muted);margin-top:2px'>{html.escape(sub)}</div></div>")


def _parallel_summary_html(models, shared, analysts) -> str:
    cards = ""
    for m in models:
        s = shared[m]
        if s["error"]:
            cards += _summary_card(m, "FAILED", "#EA3943", s["error"][:60])
        elif s["done"]:
            sig = s["decision"]
            cards += _summary_card(m, sig.upper() if _nonempty(sig) else "DONE", _signal_color(sig), "complete")
        else:
            done, total, running = progress_summary(s["state"], analysts)
            cards += _summary_card(m, f"{done}/{total}", "#2DD4BF", (running or "starting…"))
    return f"<div style='display:flex;gap:10px;flex-wrap:wrap;margin-bottom:10px'>{cards}</div>"


def run_parallel_live(models, ticker, date, analysts, debate_rounds, risk_rounds,
                      keys=None, social_source=SOURCE_STOCKTWITS,
                      twitter_keywords=None) -> None:
    """Run each model's FULL analysis in its own background thread and stream all
    of them LIVE — a folder-tab per model, each with its own pipeline + reports
    updating in real time (same live view as single-model, ×N concurrently).

    Each model uses its OWN provider (from MODELS), so NVIDIA + Gemini + Ollama
    models can be mixed — separate provider quotas. `keys` maps model -> API key.
    """
    import threading
    import time

    keys = keys or {}
    providers = sorted({provider_for(m) for m in models})
    distinct = len(set(keys.get(m, "") for m in models if keys.get(m)))
    note = (" · " + "+".join(providers)) if providers else ""
    st.markdown(meta_bar(ticker, date, "+".join(providers) or "—",
                         f"{len(models)} models · parallel{note}", len(analysts)),
                unsafe_allow_html=True)

    # Shared store the worker threads write to and the main thread polls.
    shared = {m: {"state": {}, "done": False, "error": None, "decision": ""} for m in models}

    def worker(model: str):
        cfg = build_config(DEFAULT_CONFIG, provider=provider_for(model), deep_model=model,
                           quick_model=model, debate_rounds=debate_rounds,
                           risk_rounds=risk_rounds, social_source=social_source,
                           twitter_keywords=twitter_keywords, ticker=ticker)
        configure_cfg(cfg, model, key_override=keys.get(model, ""))  # real provider/url/key
        try:
            ta = TradingAgentsGraph(selected_analysts=tuple(analysts), debug=False, config=cfg)
            past = ta.memory_log.get_past_context(ticker)
            inst = ta.resolve_instrument_context(ticker, "stock")
            init = ta.propagator.create_initial_state(
                ticker, date, asset_type="stock", past_context=past, instrument_context=inst)
            for chunk in ta.graph.stream(init, **ta.propagator.get_graph_args()):
                shared[model]["state"] = chunk        # atomic dict assignment (GIL)
            try:
                shared[model]["decision"] = ta.process_signal(
                    shared[model]["state"].get("final_trade_decision", ""))
            except Exception:  # noqa: BLE001
                pass
        except Exception as exc:  # noqa: BLE001
            shared[model]["error"] = raw_error(exc)        # verbatim API/SDK message
        finally:
            shared[model]["done"] = True

    # Stagger starts so all models don't fire their first burst simultaneously
    # (eases a SHARED rate limit). No shared quota when every model has a distinct
    # key OR they're on distinct providers → launch all at once for true parallel.
    no_shared = bool(models) and (distinct >= len(models) or len(providers) >= len(models))
    stagger = 0.0 if no_shared else 1.5
    for i, m in enumerate(models):
        threading.Thread(target=worker, args=(m,), daemon=True).start()
        if stagger and i < len(models) - 1:
            time.sleep(stagger)

    summary_ph = st.empty()
    tabs = st.tabs(list(models))
    cells: dict[str, dict] = {}
    for tab, m in zip(tabs, models):
        with tab:
            cells[m] = {"prog": st.empty(), "rep": st.empty(), "dec": st.empty()}
            render_progress(cells[m]["prog"], {}, analysts)
            render_reports(cells[m]["rep"], {})

    last_sig = {m: -1 for m in models}

    def paint(final: bool = False):
        summary_ph.markdown(_parallel_summary_html(models, shared, analysts), unsafe_allow_html=True)
        for m in models:
            s = shared[m]
            render_progress(cells[m]["prog"], s["state"], analysts)
            sig = _report_sig(s["state"])
            if final or sig != last_sig[m]:               # re-render reports only on change
                render_reports(cells[m]["rep"], s["state"])
                last_sig[m] = sig
            if final:
                box = cells[m]["dec"]
                if s["error"]:
                    box.error(s["error"])
                else:
                    fd = s["state"].get("final_trade_decision", "")
                    with box.container():
                        render_decision(st.empty(), ticker, date, s["decision"])
                        if _nonempty(fd):
                            with st.expander("Full final decision", expanded=False):
                                st.markdown(fd)
                            st.download_button(
                                "Download (.md)", data=fd, key=f"dl_{m}",
                                file_name=f"{ticker}_{date}_{m.replace('/', '_')}.md",
                                mime="text/markdown")

    while not all(shared[m]["done"] for m in models):
        paint()
        time.sleep(0.5)
    paint(final=True)
    st.success(f"All {len(models)} models complete.")


class RunOutcome(NamedTuple):
    """What a completed streaming run produced.

    Returned so a caller can persist the result across Streamlit reruns: a table
    row is drawn before its run starts, so the verdict can only appear if the
    caller stores this and redraws.
    """

    signal: str      # BUY / SELL / HOLD, "" when the run produced none
    decision: str    # the final decision markdown
    state: dict      # the last full graph state (per-analyst reports)


def run_single_streaming(ticker, trade_date, selected, cfg, provider, model,
                         asset_type: str = "stock",
                         instrument_context: str | None = None) -> RunOutcome:
    """One model, with live streaming progress + reports (the original flow).

    ``instrument_context`` overrides the yfinance identity lookup, which returns
    nothing for coins Yahoo does not list.
    """
    st.markdown(meta_bar(ticker, trade_date, provider, model, len(selected)), unsafe_allow_html=True)
    status = st.status(f"Running on {provider} / {model}…", expanded=True)
    progress_bar = st.progress(0.0, text="Starting…")
    # Keyed so the CSS can top-align this layout row (see .st-key-crypto_layout):
    # without it the short pipeline column gets vertically centered against the
    # tall reports column and ends up floating mid-dialog.
    stream_layout = st.container(key="run_stream_layout")
    progress_col, report_col = stream_layout.columns([1, 2], gap="large")
    with progress_col:
        progress_box = st.empty()
    with report_col:
        report_box = st.empty()
    decision_box = st.empty()
    error_box = st.empty()
    render_progress(progress_box, {}, selected)
    render_reports(report_box, {})

    final_state: dict = {}
    ta = None
    try:
        ta = TradingAgentsGraph(selected_analysts=tuple(selected), debug=False, config=cfg)
        past = ta.memory_log.get_past_context(ticker)
        inst = instrument_context or ta.resolve_instrument_context(ticker, asset_type)
        init_state = ta.propagator.create_initial_state(
            ticker, trade_date, asset_type=asset_type, past_context=past,
            instrument_context=inst)
        for chunk in ta.graph.stream(init_state, **ta.propagator.get_graph_args()):
            final_state = chunk
            done, total, running = progress_summary(final_state, selected)
            frac = min(1.0, done / total) if total else 0.0
            label = f"Running: {running}" if running else "Finalizing…"
            status.update(label=f"{label}  ·  {done}/{total} stages done")
            progress_bar.progress(frac, text=f"{label}  ·  {done}/{total}")
            render_progress(progress_box, final_state, selected)
            render_reports(report_box, final_state)
        progress_bar.progress(1.0, text="Complete")
        status.update(label="Analysis complete", state="complete", expanded=False)
    except Exception as exc:  # noqa: BLE001
        status.update(label="Run failed — raw API error below", state="error", expanded=True)
        error_box.error(raw_error(exc))                    # verbatim API/SDK message
        with error_box.expander("Full traceback"):
            st.code("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
        return RunOutcome("", "", final_state)

    final_decision = final_state.get("final_trade_decision", "")
    if _nonempty(final_decision):
        signal = ""
        try:
            signal = ta.process_signal(final_decision)
        except Exception:  # noqa: BLE001
            pass
        render_decision(decision_box, ticker, trade_date, signal)
        with st.expander("Full final decision", expanded=True):
            st.markdown(safe_markdown(final_decision))
        st.download_button("Download decision (.md)", data=final_decision,
                           file_name=f"{ticker}_{trade_date}_decision.md", mime="text/markdown")
        return RunOutcome(signal, final_decision, final_state)

    st.warning("Run ended without a final decision — see reports / errors above.")
    return RunOutcome("", "", final_state)


def render_run_mode(default_model: str):
    """Top-of-page mode selector. Returns (mode, list_of_models_to_run)."""
    st.markdown(
        '<div style="font-family:var(--font-display);font-size:13px;letter-spacing:.08em;'
        'text-transform:uppercase;color:var(--muted);margin-bottom:4px">Run mode</div>',
        unsafe_allow_html=True)
    mode = st.radio("Run mode", ["Selected model", "Parallel — compare models"],
                    horizontal=True, label_visibility="collapsed", key="run_mode")
    if mode.startswith("Selected"):
        opts = model_options(default_model)
        sel = st.selectbox("Model", opts, index=0, key="single_model", label_visibility="collapsed")
        if sel == CUSTOM_MODEL:
            sel = st.text_input("Custom model id", value="", key="single_custom",
                                placeholder="vendor/model-id").strip() or default_model
        return mode, [sel], {}
    default_two = model_choices()[:2]
    models = st.multiselect("Models to run in parallel", model_choices(), default=default_two,
                            key="parallel_models", format_func=lambda m: f"{m}  ·  {provider_for(m)}")
    st.caption("Each model runs a full analysis at once, each on **its own provider** "
               "(mixing NVIDIA + Gemini = separate quotas → best for dodging rate limits).")
    keys: dict[str, str] = {}
    with st.expander("Per-model API keys (optional)"):
        st.caption("Blank = use the provider's default key from `.env`. A distinct key per model "
                   "gives each its own per-key rate-limit quota.")
        for m in models:
            k = st.text_input(f"Key for `{m}` ({provider_for(m)})", type="password", key=f"key_{m}",
                              placeholder="optional override").strip()
            if k:
                keys[m] = k
    return mode, models, keys


# --- App -------------------------------------------------------------------
def engine_badge_html() -> str:
    provs = "+".join(sorted({provider_for(m) for m in model_choices()}))
    return (
        "<div style='background:var(--panel-2);border:1px solid var(--border);"
        "border-radius:5px;padding:7px 11px;margin-bottom:10px;"
        "font-family:var(--font-mono);font-size:11.5px'>"
        "<span style='color:var(--faint);letter-spacing:.1em'>ENGINE</span>  "
        f"<span style='color:var(--accent-dim)'>{html.escape(provs)}</span>"
        "<span style='color:var(--faint);font-size:10px'> · auto per model</span></div>")


# Sidebar navigation: one screen renders at a time, which is what lets each screen
# own its controls. Tabs could not do that — Streamlit renders every tab body on
# every run, so a sidebar full of settings looked like it applied to both.
PAGES = ("New Crypto", "Stocks", "Trade", "LLM Models")


def render_nav() -> str:
    """Brand mark plus the screen tabs on top. Returns the selected screen."""
    st.markdown(
        '<div class="ta-brand"><div class="ta-mark">◈</div>'
        '<div><div class="ta-brand-name">TradingAgents</div>'
        '<div class="ta-brand-sub">Terminal</div></div></div>',
        unsafe_allow_html=True)
    page = st.radio("Screen", PAGES, horizontal=True,
                    label_visibility="collapsed", key="nav_page")
    st.markdown('<div class="ta-rule" style="margin-top:var(--s)"></div>',
                unsafe_allow_html=True)
    return page


def main() -> None:
    st.set_page_config(page_title="TradingAgents", page_icon="◈", layout="wide",
                       initial_sidebar_state="collapsed")
    st.markdown(CSS, unsafe_allow_html=True)

    page = render_nav()
    st.markdown(f'<div class="ta-page-title">{html.escape(page)}</div>',
                unsafe_allow_html=True)
    if page == "New Crypto":
        render_crypto_tab()
    elif page == "Trade":
        render_trade_tab()
    elif page == "LLM Models":
        render_llm_models_tab()
    else:
        render_run_analysis_tab()


def render_run_settings():
    """Ticker / date / analysts / rounds for the stock run. Returns the choices."""
    st.markdown(engine_badge_html(), unsafe_allow_html=True)
    c1, c2 = st.columns([3, 1])
    # Searchable dropdown: click the field → search box appears inside it; type
    # to filter by symbol/company, or enter ANY Yahoo ticker (accept_new_options).
    opts = ticker_data.options()
    default = ticker_data.label_for("NVDA")
    choice = c1.selectbox(
        "Ticker", opts, index=opts.index(default) if default in opts else 0,
        accept_new_options=True,
        placeholder="Click to search — symbol or company…",
        help="Type to search by symbol or company name, or enter any Yahoo Finance "
             "ticker (e.g. 0700.HK, BTC-USD).")
    ticker = ticker_data.parse_ticker(choice) if choice else "NVDA"
    # A PSE ticker typed bare resolves to an unrelated US listing on Yahoo, so
    # say so rather than analyzing the wrong company in silence.
    mixup = ticker_data.confusable_warning(ticker)
    if mixup:
        st.warning(mixup)
    trade_date = c2.date_input("Analysis date").isoformat()

    selected = st.multiselect(
        "Analysts", options=[k for k, _, _ in ANALYST_STAGES],
        default=[k for k, _, _ in ANALYST_STAGES],
        format_func=lambda k: ANALYST_LABELS[k])
    r1, r2, r3 = st.columns([1, 1, 2])
    debate_rounds = r1.number_input("Debate rounds", 1, 5, 1)
    risk_rounds = r2.number_input("Risk rounds", 1, 5, 1)
    # Same cost-ordered choice as the New Crypto tab: StockTwits is free,
    # X spends metered credits, so it is opt-in per run.
    source = st.radio("Social sentiment source", SOCIAL_SOURCES, horizontal=True,
                      key="stock_social_source",
                      help="Where the Sentiment Analyst reads social posts. "
                           "X / Twitter spends metered API credits.")
    # Keyword box only when the run will actually search X.
    keywords: list[str] = []
    if social_flags(source)["include_twitter"]:
        keywords = parse_keywords(st.text_input(
            "X search keywords (optional, comma-separated)",
            key="stock_twitter_keywords", placeholder="Meralco, rate hike ERC",
            help="Extra terms OR'd into the X search besides the cashtag and "
                 "company name. Multi-word terms match as phrases. Keep terms "
                 "specific — very common phrases return huge result pages, "
                 "which slows the search and can time it out."))
    run = r3.button("Run analysis", type="primary")
    return (ticker, trade_date, selected, debate_rounds, risk_rounds,
            source, keywords, run)


def render_crypto_tab() -> None:
    """The screener, with its run settings rendered in a right-hand panel."""
    render_new_crypto_tab(
        model_options=model_options(DEFAULT_CONFIG["deep_think_llm"]),
        default_model=DEFAULT_CONFIG["deep_think_llm"],
        custom_sentinel=CUSTOM_MODEL,
        provider_for=provider_for,
        base_config=DEFAULT_CONFIG, configure_cfg=configure_cfg,
        streaming_runner=run_single_streaming)


@st.cache_data(ttl=1800, show_spinner=False)
def _funding_history(symbol: str) -> list:
    """Funding settlements for a contract, cached — several paged requests."""
    from tradingagents.dataflows import mexc_futures as fx
    try:
        return fx.funding_history(symbol)
    except Exception:                                     # noqa: BLE001
        return []


@st.cache_data(ttl=1800, show_spinner=False)
def _funding_summary(symbol: str) -> dict:
    from tradingagents.dataflows import mexc_futures as fx
    try:
        return fx.funding_summary(symbol)
    except Exception:                                     # noqa: BLE001
        return {"available": False}


@st.cache_data(ttl=600, show_spinner=False)
def _futures_contracts() -> list[dict]:
    """Tradeable MEXC perpetuals, cached — 920 contracts is one slow request."""
    from tradingagents.dataflows import mexc_futures as fx
    return fx.list_contracts()


def render_trade_tab() -> None:
    """Auto-trade console for the SPX500 perpetual bot.

    The UI deliberately cannot arm live trading: that needs SPX_BOT_ARMED in the
    bot's own environment, so a stray click in a browser can never start
    spending money. What the UI does own is everything safe — status, config,
    preflight, dry-run cycles, the ledger, and the two stop controls.
    """
    import json
    import signal
    import subprocess
    import time
    from dataclasses import asdict

    import pandas as pd

    import spx_bot
    from tradingagents import strategies as sg
    from tradingagents.dataflows import mexc_futures as fx

    from tradingagents.dataflows import mexc_credentials as cred

    cred.load_into_env()          # pick up keys saved from this page
    cfg = spx_bot.Config.load()
    state = spx_bot._read_state()
    armed_env = os.getenv("SPX_BOT_ARMED", "").strip().lower() in ("yes", "true", "1")
    killed = spx_bot.KILL_PATH.exists()
    live_ready = armed_env and not killed

    # ---- top row: what mode is this in, right now
    mode = ("LIVE — real money" if live_ready
            else ("HALTED — kill file present" if killed else "DRY RUN — no orders"))
    colour = "var(--sell)" if live_ready else ("var(--hold)" if killed else "var(--buy)")
    st.markdown(
        f"<div class='ta-card' style='border-left:3px solid {colour}'>"
        f"<h4>Bot mode</h4>"
        f"<div style='font-family:var(--font-mono);font-size:22px;font-weight:600;"
        f"color:{colour}'>{html.escape(mode)}</div>"
        f"<div style='color:var(--muted);font-size:13px;margin-top:6px'>"
        f"Live trading needs <code>SPX_BOT_ARMED=yes</code> in the bot's shell "
        f"<b>and</b> <code>--live</code> on its command line. This page cannot "
        f"set either — by design.</div></div>",
        unsafe_allow_html=True)

    # Keyed so the CSS top-aligns this row; otherwise the shorter left column
    # gets vertically centred against the tall settings panel.
    # ---- command strip: the primary action, and the state it acts on.
    # "Start bot (dry run)" used to sit four sections down the operating column,
    # below the API-key form, which is why it could not be found.
    _h = spx_bot.health()
    _st = spx_bot._read_state() or {}
    _pos = _st.get("position")
    _live_ready = os.getenv("SPX_BOT_ARMED", "").strip().lower() in ("yes", "true", "1")
    cs = st.container(key="command_strip")
    with cs:
        m1, m2, m3, m4, act = st.columns([1, 1, 1, 1, 1.5], gap="medium")
        m1.markdown(
            f"<div class='ta-metric'><span>Bot</span><b style='color:"
            f"{'var(--buy)' if _h['running'] else 'var(--muted)'}'>"
            f"{'RUNNING' if _h['running'] else 'STOPPED'}</b></div>",
            unsafe_allow_html=True)
        m2.markdown(
            f"<div class='ta-metric'><span>Position</span><b>"
            f"{(str(_pos.get('vol')) + ' contracts') if _pos else 'flat'}</b></div>",
            unsafe_allow_html=True)
        m3.markdown(
            f"<div class='ta-metric'><span>Realised today</span><b>"
            f"{_st.get('realised_today', 0.0):+.2f}</b></div>",
            unsafe_allow_html=True)
        _limit = int(getattr(cfg, "max_losses", 0) or 0)
        m4.markdown(
            f"<div class='ta-metric'><span>Losses</span><b>"
            f"{int(_st.get('losses', 0) or 0)}"
            f"{f' / {_limit}' if _limit else ''}</b></div>",
            unsafe_allow_html=True)
        with act:
            if _h["running"]:
                if st.button("Stop auto trade", type="secondary",
                             use_container_width=True, key="cs_stop"):
                    try:
                        os.kill(_h["pid"], signal.SIGTERM)
                        st.warning(f"Stopped pid {_h['pid']}.")
                    except OSError as exc:
                        st.error(f"could not stop pid {_h['pid']}: {exc}")
                    time.sleep(2)
                    st.rerun()
            else:
                if st.button("Run auto trade", type="primary",
                             use_container_width=True, key="cs_start"):
                    log = open(spx_bot.LOG_PATH, "a", buffering=1)
                    subprocess.Popen(
                        [sys.executable, "spx_bot.py", "watchdog"],
                        stdout=log, stderr=subprocess.STDOUT,
                        start_new_session=True)
                    st.success("Started.")
                    time.sleep(2)
                    st.rerun()
    st.caption(
        ("**This will place real orders.** " if _live_ready else
         "Runs in **dry run** — it decides and logs, but sends no orders. ")
        + (f"Trading `{cfg.primary_lane()['strategy']}` on "
           f"`{cfg.primary_lane()['timeframe']}` bars, checked every {cfg.poll}s"
           + (f", plus {len(cfg.active_lanes()) - 1} signal-only lane(s). "
              if len(cfg.active_lanes()) > 1 else ". ")
           + ("" if _live_ready else
              "To trade for real, launch it from a terminal with "
              "`SPX_BOT_ARMED=yes python spx_bot.py watchdog --live` — a browser "
              "button cannot arm real money, by design.")))


    # The plan block sits full width: seven timeframes plus an approach for each
    # cannot fit a narrow side rail without towering over the operating column.
    st.markdown('<div class="ta-section">Plan &mdash; tick the timeframes to run, '
                'and pick an approach for each</div>', unsafe_allow_html=True)
    plan_box = st.container(key="plan_box")
    with plan_box:
        _saved = {l["timeframe"]: l["strategy"] for l in cfg.active_lanes()}
        _cols = st.columns(len(sg.TIMEFRAMES))
        _on = []
        for _c, tf in zip(_cols, sg.TIMEFRAMES):
            if _c.checkbox(tf, value=tf in _saved, key=f"tf_on_{tf}",
                           help=sg.TIMEFRAME_LABELS[tf]):
                _on.append(tf)

        lanes: list = []
        if _on:
            _lc = st.columns(len(_on))
            for _c, tf in zip(_lc, _on):
                rows = sg.strategies_for(tf)
                keys = [r["key"] for r in rows]
                fit = {r["key"]: r for r in rows}
                mark = {"good": "", "workable": "  ~", "avoid": "  \u2715"}

                def _label(k, _fit=fit, _mark=mark):
                    name = sg.REGISTRY[k].name + _mark[_fit[k]["verdict"]]
                    if k not in spx_bot.RUNNABLE_STRATEGIES:
                        name += "  [backtest only]"
                    return name

                want = _saved.get(tf, keys[0])
                with _c:
                    st.markdown(f"<div class='ta-lane'>{tf} &middot; "
                                f"{sg.TIMEFRAME_LABELS[tf]}</div>",
                                unsafe_allow_html=True)
                    pick = st.selectbox(
                        f"Approach for {tf}", keys,
                        index=keys.index(want) if want in keys else 0,
                        key=f"tf_strat_{tf}", format_func=_label,
                        label_visibility="collapsed")
                    v = fit[pick]
                    if v["verdict"] == "avoid":
                        st.markdown("<div class='ta-fit bad'>not suited to these "
                                    "bars</div>", unsafe_allow_html=True)
                    elif v["verdict"] == "workable":
                        st.markdown("<div class='ta-fit warn'>workable</div>",
                                    unsafe_allow_html=True)
                    else:
                        st.markdown("<div class='ta-fit ok'>good fit</div>",
                                    unsafe_allow_html=True)
                lanes.append({"timeframe": tf, "strategy": pick})

        if not lanes:
            st.error("Tick at least one timeframe — the bot has nothing to run.")
            lanes = [{"timeframe": "Min5", "strategy": "barrier_harvest"}]

        timeframe = lanes[0]["timeframe"]
        strat_key = lanes[0]["strategy"]
        strat = sg.REGISTRY[strat_key]
        _worst = [l for l in lanes
                  if sg.timeframe_fit(l["timeframe"], l["strategy"])[0] == "avoid"]
        if _worst:
            st.error("**" + ", ".join(f"{l['strategy']} on {l['timeframe']}"
                                      for l in _worst) + "** — "
                     + sg.timeframe_fit(_worst[0]["timeframe"],
                                        _worst[0]["strategy"])[1])
        if len(lanes) > 1:
            others = ", ".join(f"{l['strategy']} on {l['timeframe']}"
                               for l in lanes[1:])
            st.info(
                f"**{strat_key} on {timeframe} places the orders.** The other "
                f"{len(lanes) - 1} ({others}) are evaluated and logged as signals "
                f"only.\n\nThis is MEXC's rule, not a shortcut here — the "
                f"exchange allows **one long per symbol** and refuses the "
                f"alternatives outright:\n"
                f"- a second long at a different leverage → "
                f"`code 2021: Order leverage is inconsistent with the existing "
                f"position leverage`\n"
                f"- one isolated plus one cross → `code 2027: Cross and isolated "
                f"position of the same direction are alternative`\n\n"
                f"Same-settings orders simply merge into one position, which "
                f"carries a single stop. To run several lanes for real at the same "
                f"time, give each a different perpetual — MEXC keeps positions on "
                f"different contracts separate.")
        st.caption(
            f"Checked every "
            f"**{min(sg.poll_seconds_for(l['timeframe']) for l in lanes)}s** — "
            f"half a bar of the finest timeframe ticked.")

    trade_layout = st.container(key="trade_layout")
    left, right = trade_layout.columns([1.6, 1], gap="large")

    with right:
        st.markdown('<div class="ta-panel-title">Instrument</div>',
                    unsafe_allow_html=True)
        try:
            contracts = _futures_contracts()
        except Exception as exc:                          # noqa: BLE001
            contracts = []
            st.warning(f"Contract list unavailable: {exc}")
        spec_by = {c["symbol"]: c for c in contracts}
        all_syms = [c["symbol"] for c in contracts] or [cfg.symbol]
        # The majors first: the dropdown holds ~920 contracts and Streamlit's
        # search does subsequence matching, so "BTC" alone surfaces junk like
        # RKLBSTOCK. Browsing beats searching for the handful people want.
        FAVOURITES = ("SPX500_USDT", "BTC_USDT", "ETH_USDT", "SOL_USDT",
                      "BNB_USDT", "XRP_USDT", "DOGE_USDT", "GOLD_USDT")
        head = [s for s in FAVOURITES if s in spec_by]
        syms = head + [s for s in all_syms if s not in head]
        idx = syms.index(cfg.symbol) if cfg.symbol in syms else 0
        symbol = st.selectbox(
            "Perpetual", syms, index=idx, key="trade_symbol",
            # Keep the full symbol in the label: Streamlit's picker does
            # subsequence matching, so stripping "_USDT" made "BTC" match
            # "RKLBSTOCK" ahead of BTC_USDT.
            format_func=lambda s: (f"{s}  ·  "
                                   f"{spec_by.get(s, {}).get('max_leverage', '?')}x max"),
            help="Majors are listed first. For anything else, use the exact-symbol "
                 "box below — the dropdown's search is fuzzy and ranks poorly "
                 "across 920 contracts.")
        exact = st.text_input("Or exact symbol", value="", key="trade_exact",
                              placeholder="e.g. PEPE_USDT",
                              help="Overrides the dropdown. Must match a "
                                   "tradeable MEXC perpetual exactly.").strip().upper()
        if exact:
            if exact in spec_by:
                symbol = exact
                st.caption(f"Using {symbol} (from the exact-symbol box).")
            else:
                st.error(f"{exact} is not a tradeable MEXC USDT perpetual.")
        max_lev = int(spec_by.get(symbol, {}).get("max_leverage", 20))

        lev = st.number_input("Leverage", 1, max(max_lev, 1),
                              min(int(cfg.leverage), max_lev), key="trade_lev",
                              help="3x was the highest that survived the worst "
                                   "drawdown in the backtest; 8x liquidated.")
        margin = st.number_input("Margin (USD)", 5.0, 10_000.0,
                                 float(cfg.margin_usd), step=5.0,
                                 key="trade_margin")
        if strat.kind == "bracket":
            tp = st.number_input("Take-profit %", 0.25, 20.0,
                                 float(cfg.take_profit_pct), step=0.25,
                                 key="trade_tp")
            sl = st.number_input("Stop-loss %", 1.0, 50.0,
                                 float(cfg.stop_loss_pct), step=0.5,
                                 key="trade_sl")
        else:
            tp, sl = float(cfg.take_profit_pct), float(cfg.stop_loss_pct)
            st.caption("This approach shapes exposure rather than setting "
                       "barriers, so it has no take-profit or stop-loss.")
        st.markdown('<div class="ta-panel-title">Risk limits</div>',
                    unsafe_allow_html=True)
        cap = st.number_input("Max notional (USD)", 10.0, 50_000.0,
                              float(cfg.max_notional_usd), step=50.0,
                              key="trade_cap")
        dl = st.number_input("Daily loss limit (USD)", 1.0, 5_000.0,
                             float(cfg.daily_loss_limit_usd), step=5.0,
                             key="trade_dl")
        floor = st.number_input("Halt below equity (USD)", 0.0, 5_000.0,
                                float(cfg.min_equity_usd), step=5.0,
                                key="trade_floor")
        mx = st.number_input("Stop after N losing trades", 0, 100,
                             int(getattr(cfg, "max_losses", 0)), step=1,
                             key="trade_maxlosses",
                             help="0 = no limit. Counts losing trades in "
                                  "total, not per day. Only the Reset button "
                                  "below clears it.")
        if st.button("Save settings", type="primary"):
            cfg.symbol = symbol
            cfg.strategy = strat_key
            cfg.timeframe = timeframe
            cfg.lanes = lanes
            cfg.poll_seconds = 0        # 0 = derive from the timeframes
            cfg.leverage, cfg.margin_usd = int(lev), float(margin)
            cfg.take_profit_pct, cfg.stop_loss_pct = float(tp), float(sl)
            cfg.max_notional_usd, cfg.daily_loss_limit_usd = float(cap), float(dl)
            cfg.min_equity_usd = float(floor)
            cfg.max_losses = int(mx)
            cfg.save()
            st.success("Saved. The bot picks these up on its next cycle.")
        if mx:
            st.caption(f"After {mx} losing trade{'s' if mx != 1 else ''} the bot "
                       f"stops opening new ones. At a {sl:.2f}% stop that is "
                       f"about ${mx * min(margin * lev, cap) * sl / 100:,.2f} "
                       f"of realised loss before it halts.")
        st.caption(f"Notional at these settings: "
                   f"${min(margin * lev, cap):,.2f}  ·  a {sl:.0f}% stop costs "
                   f"{sl * lev:.0f}% of margin.")
        if symbol != "SPX500_USDT":
            st.warning(
                f"These take-profit and stop-loss levels were validated on "
                f"SPX500_USDT only. {symbol.replace('_USDT','')} has different "
                f"volatility, so 2%/10% is an untested guess here — re-run the "
                f"backtest before trusting it.")

    with left:
        st.markdown('<div class="ta-label">Position detail</div>',
                    unsafe_allow_html=True)
        pos = state.get("position")
        c1, c2, c3 = st.columns(3)
        c1.metric("Entry", f"{pos['entry']:,.2f}" if pos else "—")
        c2.metric("Target", f"{pos.get('tp'):,.2f}"
                  if pos and pos.get("tp") else "—")
        c3.metric("Stop", f"{pos.get('sl'):,.2f}"
                  if pos and pos.get("sl") else "—")
        if pos and not pos.get("protected"):
            st.warning("This position has no verified exchange-side barriers — "
                       "the stop is only being watched by the bot process.")
        if state.get("halted"):
            st.error(f"Bot halted — {state.get('halt_reason', '')}")

        wallet = None
        if fx.has_credentials():
            try:
                wallet = fx.usdt_equity()
            except fx.MexcFuturesError as exc:
                st.warning(f"Exchange read failed: {exc}")
        st.caption(f"Futures wallet: "
                   f"{('%.2f USDT' % wallet) if wallet is not None else 'unavailable'}"
                   f"  ·  key present: {fx.has_credentials()}")

        st.markdown('<div class="ta-label">Bot process</div>',
                    unsafe_allow_html=True)
        h = spx_bot.health()
        if h["orphaned"]:
            st.error("**The bot is not running and a position is open.** Its "
                     "exchange stop still applies, but nothing is managing the "
                     "trade. Start it again, or close the position below.")
        elif h["running"] and h["stale"]:
            st.warning(f"Running as pid {h['pid']} but the last cycle was "
                       f"{h['seconds_since_cycle']:.0f}s ago — it may be stuck.")
        elif h["running"]:
            st.success(f"Running as pid {h['pid']}"
                       + (f" · last cycle {h['seconds_since_cycle']:.0f}s ago"
                          if h["seconds_since_cycle"] is not None else ""))
        else:
            st.caption("Not running. Use **Run auto trade** at the top — it "
                       "keeps running after you close this page.")
        if h["halted"]:
            st.error(f"Halted: {h['halt_reason']}")
        alerts = spx_bot.recent_alerts(5)
        if alerts:
            with st.expander(f"Recent alerts ({len(alerts)})",
                             expanded=alerts[0]["kind"] in ("halted", "giving-up",
                                                            "loss-limit")):
                for a in alerts:
                    st.markdown(f"`{a['at']}` **{a['kind']}** — {a['message']}")

        # Start/Stop lives in the command strip at the top of the page — having it
        # here as well was the reason two buttons appeared to do the same thing.
        st.markdown('<div class="ta-label">Controls</div>',
                    unsafe_allow_html=True)
        b1, b2, b3, b4 = st.columns(4)
        if b1.button("Preflight"):
            with st.spinner("checking key permissions…"):
                rep = fx.preflight(symbol)
            # Use preflight's own verdict: recomputing it here dropped
            # read_positions and edge_blocked, so a key that could not read
            # positions printed a green "ready" directly under a red FAIL row.
            ok = rep.get("ready")
            (st.success if ok else st.error)(
                f"Key can read {symbol} and place futures orders." if ok
                else f"Key is not ready for {symbol} — see details.")
            st.json(rep)
        if b2.button("Dry-run one cycle"):
            with st.spinner("running one decision cycle…"):
                r = subprocess.run(
                    [sys.executable, "spx_bot.py", "run", "--once"],
                    capture_output=True, text=True, timeout=180)
            st.code((r.stdout + r.stderr)[-2000:] or "(no output)")
        if b3.button("Close position now"):
            st.session_state["confirm_flat"] = True
        if b4.button("Kill switch" if not killed else "Clear kill file"):
            if killed:
                spx_bot.KILL_PATH.unlink(missing_ok=True)
                st.success("Kill file cleared — the bot may trade again.")
            else:
                spx_bot.KILL_PATH.parent.mkdir(parents=True, exist_ok=True)
                spx_bot.KILL_PATH.write_text("stopped from the Trade tab")
                st.warning("Kill file written. The bot will not open new trades.")
            st.rerun()

        bot_state = spx_bot._read_state() or {}
        losses = int(bot_state.get("losses", 0) or 0)
        limit = int(getattr(cfg, "max_losses", 0) or 0)
        c1, c2 = st.columns([2, 1])
        if limit:
            hit = losses >= limit
            c1.markdown(
                f"<div class='ta-card'><h4>Losing trades</h4>"
                f"<div style='font-family:var(--font-mono);font-size:22px;"
                f"color:{'var(--sell)' if hit else 'var(--ink)'}'>"
                f"{losses} / {limit}</div>"
                f"<div style='color:var(--muted);font-size:12px'>"
                f"{'LIMIT REACHED — the bot will not open new trades until you '
                   'reset' if hit else 'counts every losing trade, never resets '
                   'on its own'}</div></div>", unsafe_allow_html=True)
        else:
            c1.caption(f"Losing trades so far: {losses}. No limit set — "
                       f"set one in Risk limits.")
        if c2.button("Show bot log"):
            st.session_state["show_bot_log"] = True
        if st.session_state.get("show_bot_log"):
            try:
                st.code(spx_bot.LOG_PATH.read_text()[-3000:] or "(empty)")
            except OSError:
                st.caption("no log yet")
        if c2.button("Reset loss count", disabled=losses == 0):
            r = subprocess.run([sys.executable, "spx_bot.py", "reset-losses"],
                               capture_output=True, text=True, timeout=60)
            st.success((r.stdout or "reset").strip()[:200])
            st.rerun()

        # Closing a real position is irreversible, so it takes a second click.
        if st.session_state.get("confirm_flat"):
            st.warning("This sends a market order to close the whole position.")
            k1, k2 = st.columns(2)
            if k1.button("Yes, close it", type="primary"):
                r = subprocess.run(
                    [sys.executable, "spx_bot.py", "flat"]
                    + (["--live"] if live_ready else []),
                    capture_output=True, text=True, timeout=120)
                st.code((r.stdout + r.stderr)[-1500:] or "(no output)")
                st.session_state.pop("confirm_flat", None)
                st.rerun()
            if k2.button("Cancel"):
                st.session_state.pop("confirm_flat", None)
                st.rerun()

        st.markdown('<div class="ta-label">Trade log</div>', unsafe_allow_html=True)
        rows = []
        try:
            for line in spx_bot.LEDGER_PATH.read_text().splitlines()[-40:]:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except OSError:
            pass
        if not rows:
            st.caption("No trades recorded yet. Dry runs are logged here too.")
        else:
            body = "| when | action | price | contracts | PnL $ | mode |\n"
            body += "|---|---|---|---|---|---|\n"
            for e in reversed(rows):
                body += (f"| {e.get('at','')} | {e.get('action','')} "
                         f"| {e.get('price','')} | {e.get('vol','')} "
                         f"| {e.get('pnl_usd','')} "
                         f"| {'dry' if e.get('dry_run') else 'LIVE'} |\n")
            st.markdown(body)

    st.markdown('<div class="ta-rule"></div>', unsafe_allow_html=True)
    st.caption(
        "Strategy: always-long SPX500_USDT, take-profit as a limit order, "
        "stop-loss as a market exit, re-enter after each exit, never short. "
        "Backtest over 188 days: +47.6% on margin at 3x, 15 trades, 87% win "
        "rate. Most of that return was the index rising during the sample — "
        "funding costs are not in the backtest, and a limit fill is required or "
        "the take-profit edge disappears. To go live: set SPX_BOT_ARMED=yes and "
        "run `python spx_bot.py watchdog --live` in a terminal.")



    # Setup is a one-time job. It used to sit at the top of the operating
    # column, above the controls, which is why the tab read as jumbled.
    with st.expander("Setup and connection",
                     expanded=not cred.status()["has_credentials"]):
            st.markdown('<div class="ta-label">MEXC API keys</div>',
                        unsafe_allow_html=True)
            cst = cred.status()
            if cst["has_credentials"]:
                mode_note = ("" if cst["file_mode_ok"] else
                             f"  ·  file mode {cst['file_mode']} — should be -rw-------")
                st.markdown(
                    f"<div class='ta-card'><h4>Key loaded</h4>"
                    f"<div style='font-family:var(--font-mono);font-size:12.5px'>"
                    f"key &nbsp; {html.escape(cst['key_fingerprint'])}<br>"
                    f"secret {html.escape(cst['secret_fingerprint'])}</div>"
                    f"<div style='color:var(--muted);font-size:12px;margin-top:6px'>"
                    f"source: {html.escape(cst['source'])}{html.escape(mode_note)}"
                    f"</div></div>", unsafe_allow_html=True)
            else:
                st.caption("No key loaded. Enter one below, or export "
                           "MEXC_API_KEY / MEXC_API_SECRET before launching.")

            # A different key in .env is invisible from the browser. It used to win
            # silently, so every connection test ran against a key the user had
            # already replaced. The saved key now wins — say so, and name the file
            # to clean up.
            conflict = cred.env_conflict()
            if conflict.get("conflict"):
                stale = ", ".join(f"{where} ({fp})" for where, fp in conflict["stale"])
                st.warning(
                    f"A different MEXC key is also set in {stale}. The key saved "
                    f"here wins, but delete the `MEXC_API_KEY` / `MEXC_API_SECRET` "
                    f"lines from that file so there is only one answer to which "
                    f"key is live.")

            with st.expander("Enter or replace keys",
                             expanded=not cst["has_credentials"]):
                st.caption(
                    "Create the key on MEXC with **futures trading and read access "
                    "enabled**, **withdrawals disabled**, and an **IP allowlist**. "
                    "A trade-only key that leaks can lose money on bad trades but "
                    "cannot move funds off the exchange. Keys are written to "
                    f"`{cst['store_path']}` with owner-only permissions — never to "
                    "the project folder, and never shown back to you.")
                with st.form("mexc_keys", clear_on_submit=True):
                    k_in = st.text_input("API key", type="password",
                                         autocomplete="off")
                    s_in = st.text_input("API secret", type="password",
                                         autocomplete="off")
                    f1, f2 = st.columns([1, 1])
                    if f1.form_submit_button("Save keys", type="primary"):
                        try:
                            cred.save(k_in, s_in)
                        except ValueError as exc:
                            st.error(str(exc))
                        else:
                            st.success("Saved. Test the connection below.")
                            st.rerun()
                    if f2.form_submit_button("Forget saved keys"):
                        st.warning("Removed." if cred.clear() else "Nothing stored.")
                        st.rerun()

            tc1, tc2 = st.columns([1, 3])
            if tc1.button("Test connection", type="primary"):
                st.session_state["conn_test"] = True
            if st.session_state.get("conn_test"):
                # Clear the flag before rendering: Streamlit reruns the script on
                # every widget interaction, and leaving it set re-issued a signed
                # POST to the order endpoint on each one.
                st.session_state.pop("conn_test", None)
                with st.spinner("talking to MEXC…"):
                    rep = fx.preflight(symbol)
                checks = [
                    ("Credentials present", rep.get("credentials")),
                    ("Read account balance", rep.get("read_assets")),
                    ("Read open positions", rep.get("read_positions")),
                    ("Permission to place orders", rep.get("order_permission")),
                    ("Rest a stop on MEXC's servers", rep.get("can_rest_stop")),
                ]
                rows = ""
                for label, ok in checks:
                    mark = "PASS" if ok else ("FAIL" if ok is False else "unknown")
                    colour = ("var(--buy)" if ok else
                              ("var(--sell)" if ok is False else "var(--muted)"))
                    rows += (f"<div class='ta-stage'><span class='lbl'>{label}</span>"
                             f"<span class='tag' style='color:{colour}'>{mark}</span>"
                             f"</div>")
                st.markdown(f"<div class='ta-card'><h4>Connection</h4>{rows}</div>",
                            unsafe_allow_html=True)
                if rep.get("equity_usdt") is not None:
                    st.metric("Futures wallet", f"{rep['equity_usdt']:,.2f} USDT")
                if rep.get("ready"):
                    st.success(f"Connected. This key can read the account and place "
                               f"futures orders on {symbol}.")
                    st.caption("Both write checks are non-destructive: the order "
                               "check cancels an order id that cannot exist, and "
                               "the stop check targets a position id that cannot "
                               "exist. Neither can open a position. They are "
                               "separate endpoints, so both are tested — a key can "
                               "place orders and still not be allowed to rest a "
                               "stop.")
                elif rep.get("auth_failed"):
                    st.error("**MEXC rejected the credentials themselves, not their "
                             "permissions.** No permission setting will fix this.")
                    for fix in rep.get("remedies", []):
                        st.markdown(f"- {fix}")
                elif rep.get("edge_blocked"):
                    st.error("**Blocked by MEXC's edge proxy, not by your key.** The "
                             "order endpoint returned an HTML “Access Denied” "
                             "before the API saw the request, so no permission "
                             "setting on MEXC will change it.")
                    for fix in rep.get("remedies", []):
                        st.markdown(f"- {fix}")
                    st.caption("MEXC's edge refuses the futures order paths for "
                               "requests whose User-Agent identifies a scripted "
                               "client (bare urllib or requests). Reads are "
                               "unaffected, which makes it look like a trade "
                               "permission problem.")
                elif rep.get("missing_scopes"):
                    st.error("**Your key is missing permission scopes.** MEXC named "
                             "them exactly: " + ", ".join(rep["missing_scopes"]) + ".")
                    st.markdown("**To fix, on MEXC:**")
                    for fix in rep.get("remedies", []):
                        st.markdown(f"- {fix}")
                    st.markdown(
                        "- Keep **withdrawals disabled**, and check the key's "
                        "**IP allowlist** includes this machine.\n"
                        "- Editing scopes can issue a new secret — if so, paste "
                        "both values above again.")
                    st.caption("Futures API order placement is not gated by MEXC on "
                               "this contract; these are key settings you control.")
                else:
                    st.error("Not ready to trade — see the raw exchange responses "
                             "below. Common causes: a wrong secret (signature "
                             "failure) or an IP allowlist that excludes this machine.")
                for note in rep.get("notes", []):
                    st.caption(f"· {note}")


    st.markdown('<div class="ta-section">Analyse</div>',
                unsafe_allow_html=True)
    analyse_tabs = st.tabs(["Chart", "Backtest"])
    with analyse_tabs[0]:
            st.markdown('<div class="ta-label">Chart</div>', unsafe_allow_html=True)
            ci1, ci2 = st.columns([1, 3])
            interval = ci1.selectbox("Interval",
                                     ["Min1", "Min5", "Min15", "Min60", "Hour4", "Day1"],
                                     index=1, key="trade_interval",
                                     label_visibility="collapsed")
            try:
                import crypto_screener as _cs
                candles = fx.klines(symbol, interval, 240)
                chart = _cs.candlestick_chart(candles, symbol.replace("_USDT", ""))
                # overlay the live take-profit / stop levels off the last close
                import altair as alt
                last = float(candles["Close"].iloc[-1])
                levels = [{"level": last * (1 + tp / 100), "kind": f"take-profit +{tp:g}%"},
                          {"level": last * (1 - sl / 100), "kind": f"stop-loss -{sl:g}%"}]
                if pos:
                    levels += [{"level": float(pos["entry"]), "kind": "entry"},
                               {"level": float(pos["tp"]), "kind": "resting TP"}]
                rules = alt.Chart(pd.DataFrame(levels)).mark_rule(
                    strokeDash=[4, 4], size=1.5).encode(
                    y="level:Q",
                    color=alt.Color("kind:N", legend=alt.Legend(title=None,
                                                                orient="top")),
                    tooltip=["kind:N", "level:Q"])
                st.altair_chart(chart + rules, use_container_width=True)
                ci2.caption(f"{_cs.chart_summary(candles)}  ·  {interval} candles "
                            f"from MEXC futures")
            except Exception as exc:                          # noqa: BLE001
                st.warning(f"Chart unavailable for {symbol}: {exc}")

    with analyse_tabs[1]:
            st.markdown('<div class="ta-label">Backtest these settings</div>',
                        unsafe_allow_html=True)
            bt1, bt2, bt3 = st.columns([1, 1, 2])
            bt_interval = bt1.selectbox("Bars", ["Min5", "Min15", "Min60", "Hour4"],
                                        index=0, key="bt_interval")
            bt_limit = bt2.selectbox("History", [500, 1000, 2000], index=1,
                                     key="bt_limit",
                                     format_func=lambda n: f"{n} bars")
            bb1, bb2 = bt3.columns(2)
            if bb1.button("Run backtest", type="primary"):
                st.session_state["bt_run"] = True
                st.session_state.pop("bt_compare", None)
            if bb2.button("Compare all 6"):
                st.session_state["bt_compare"] = True
                st.session_state.pop("bt_run", None)

            if st.session_state.get("bt_compare"):
                from tradingagents import strategies as _sg
                try:
                    with st.spinner(f"running all six strategies on {symbol}…"):
                        hist = fx.klines(symbol, bt_interval, int(bt_limit))
                        fund_hist = _funding_history(symbol)
                        rows = _sg.compare(hist, margin=float(margin),
                                           leverage=float(lev), funding=fund_hist)
                except Exception as exc:                      # noqa: BLE001
                    st.error(f"Comparison failed: {exc}")
                else:
                    good = [r for r in rows if "error" not in r]
                    bh = good[0]["buy_hold_total"] if good else 0.0
                    fsum = _funding_summary(symbol)
                    st.caption(f"{symbol} · {bt_limit} {bt_interval} bars · "
                               f"${margin:,.0f} margin at {lev:.0f}x · "
                               f"buy & hold benchmark ${bh:+,.2f} (funding included)")
                    if fsum.get("available"):
                        sign = "receives" if fsum["long_total"] > 0 else "pays"
                        st.info(
                            f"**Funding on {symbol}:** a long {sign} "
                            f"{abs(fsum['long_total'])*100:.2f}% of notional over the "
                            f"published history ({fsum['long_daily']*100:+.4f}%/day, "
                            f"{fsum['long_annual']*100:+.1f}%/yr) across "
                            f"{fsum['settlements']} settlements, "
                            f"{fsum['pct_positive']:.0f}% of which charged longs. "
                            f"Perpetual funding is settled every few hours while a "
                            f"position is open, so it scales with time held.")
                    else:
                        st.warning("No funding history published for this contract — "
                                   "the totals below exclude funding.")
                    tbl = ("| strategy | price PnL | funding | TOTAL | return "
                           "| trades | win% | max DD | beats hold |\n"
                           "|---|---|---|---|---|---|---|---|---|\n")
                    for r in rows:
                        if "error" in r:
                            tbl += f"| {r['name']} | error | | | | | | | |\n"
                            continue
                        flag = "**YES**" if r["beats_buy_hold"] else "no"
                        if r["liquidated"]:
                            flag = "LIQUIDATED"
                        tbl += (f"| {r['name']} | {r['pnl']:+,.2f} "
                                f"| {r['funding_pnl']:+,.2f} "
                                f"| **{r['total_pnl']:+,.2f}** "
                                f"| {r['total_return_pct']:+.1f}% | {r['trades']} "
                                f"| {r['win_rate']:.0f}% "
                                f"| {r['max_drawdown']:+,.2f} | {flag} |\n")
                    st.markdown(tbl)
                    winners = [r for r in good if r.get("beats_buy_hold")]
                    if not winners:
                        st.warning(
                            f"On {symbol} over this window, no strategy beat simply "
                            f"holding (${bh:+,.2f}). That is the honest answer — "
                            f"holding is the benchmark for a reason.")
                    else:
                        best = winners[0]
                        st.success(
                            f"Best here: **{best['name']}** at "
                            f"${best['total_pnl']:+,.2f} "
                            f"({best['total_return_pct']:+.1f}%) including funding, "
                            f"versus ${bh:+,.2f} for holding.")
                    liq = [r for r in good if r["liquidated"]]
                    if liq:
                        st.error("Would have been liquidated at this leverage: "
                                 + ", ".join(r["name"] for r in liq))
            if st.session_state.get("bt_run"):
                from tradingagents import futures_backtest as fbt
                try:
                    with st.spinner(f"simulating {strat.name} on {symbol}…"):
                        hist = fx.klines(symbol, bt_interval, int(bt_limit))
                        res, fund_pnl = sg.backtest(
                            strat_key, hist, margin=float(margin),
                            leverage=float(lev),
                            params=({"take_profit_pct": float(tp),
                                     "stop_loss_pct": float(sl)}
                                    if strat.kind == "bracket" else None),
                            funding=_funding_history(symbol))
                except Exception as exc:                      # noqa: BLE001
                    st.error(f"Backtest failed: {exc}")
                else:
                    m1, m2, m3, m4, m5 = st.columns(5)
                    m1.metric("Result", f"${res.pnl + fund_pnl:+,.2f}",
                              f"{(res.pnl + fund_pnl)/res.margin*100:+.1f}% on margin")
                    m5.metric("of which funding", f"${fund_pnl:+,.2f}",
                              "received" if fund_pnl > 0 else "paid",
                              delta_color="normal" if fund_pnl > 0 else "inverse")
                    m2.metric("Buy & hold", f"${res.buy_hold_pnl:+,.2f}",
                              "beaten" if res.beats_buy_hold else "not beaten",
                              delta_color="normal" if res.beats_buy_hold else "inverse")
                    m3.metric("Trades", f"{len(res.trades)}",
                              f"{res.win_rate:.0f}% win")
                    m4.metric("Worst equity", f"${res.worst_equity:,.2f}",
                              "LIQUIDATED" if res.liquidated else
                              f"of ${res.margin:,.0f}",
                              delta_color="inverse" if res.liquidated else "off")
                    if res.liquidated:
                        st.error(
                            f"At {lev:.0f}x this configuration would have been "
                            f"liquidated — the drawdown consumed the whole margin. "
                            f"Lower the leverage or widen the stop.")
                    elif not res.beats_buy_hold:
                        st.warning(
                            f"Simply holding made more (${res.buy_hold_pnl:+,.2f} vs "
                            f"${res.pnl:+,.2f}). The barriers cost money on this "
                            f"symbol and period.")
                    st.caption(
                        f"{res.bars} {bt_interval} bars over {res.span_days:.1f} days · "
                        f"{res.n_tp} take-profits, {res.n_sl} stops, {res.n_open} open "
                        f"· max drawdown ${res.max_drawdown:,.2f} mark-to-market · "
                        f"fees 2bp per side")
                    if res.equity_curve:
                        import altair as alt
                        eq = pd.DataFrame(res.equity_curve, columns=["Date", "Equity"])
                        st.altair_chart(
                            alt.Chart(eq).mark_line(size=2).encode(
                                x=alt.X("Date:T", title=None),
                                y=alt.Y("Equity:Q", title="account",
                                        scale=alt.Scale(zero=False)),
                                tooltip=["Date:T", "Equity:Q"]).properties(height=170),
                            use_container_width=True)
                    if res.trades:
                        tbl = "| # | entry | exit | in | out | why | return | PnL $ |\n"
                        tbl += "|---|---|---|---|---|---|---|---|\n"
                        for t in res.trades[-30:]:
                            tbl += (f"| {t.n} | {t.entry_at:%m-%d %H:%M} "
                                    f"| {t.exit_at:%m-%d %H:%M} | {t.entry_px:,.4g} "
                                    f"| {t.exit_px:,.4g} | {t.reason} "
                                    f"| {t.net_return*100:+.2f}% | {t.pnl:+,.2f} |\n")
                        st.markdown(tbl)
                        if len(res.trades) > 30:
                            st.caption(f"showing the last 30 of {len(res.trades)} trades")

def render_llm_models_tab() -> None:
    """Manage the model catalog: built-ins listed, user models added/removed.

    Anything added here is persisted (~/.tradingagents/webapp_models.json) and
    appears in the model dropdowns of both other screens on the next rerun.
    """
    custom = model_registry.load_custom()

    st.markdown('<div class="ta-label">Add a model</div>', unsafe_allow_html=True)
    with st.form("add_model", clear_on_submit=True):
        c1, c2 = st.columns([2, 1])
        model_id = c1.text_input("Model id", placeholder="vendor/model-id")
        preset = c2.selectbox("Provider", list(model_registry.PROVIDER_PRESETS))
        c3, c4 = st.columns([2, 1])
        base_url = c3.text_input(
            "Base URL (openai-compatible only)", placeholder="https://host/v1")
        key_env = c4.text_input("Key env var (optional override)",
                                placeholder="MY_API_KEY")
        if st.form_submit_button("Add model", type="primary"):
            ok, msg = model_registry.add_model(
                model_id, preset, base_url=base_url, key_env=key_env)
            (st.success if ok else st.error)(msg)
            if ok:
                st.rerun()

    if custom:
        st.markdown('<div class="ta-label">Your models</div>', unsafe_allow_html=True)
        for mid, spec in custom.items():
            c1, c2, c3, c4 = st.columns([3, 1, 3, 1])
            c1.markdown(f"**{mid}**")
            c2.write(spec.get("label", ""))
            c3.write(spec.get("base_url") or "provider default endpoint")
            if c4.button("✕ remove", key=f"rm_{mid}"):
                model_registry.remove_model(mid)
                st.rerun()

    st.markdown('<div class="ta-rule"></div>', unsafe_allow_html=True)
    render_health_panel()


def render_run_analysis_tab() -> None:
    """The original single/parallel run screen, with its settings inline."""
    (ticker, trade_date, selected, debate_rounds, risk_rounds,
     source, keywords, run) = render_run_settings()
    st.markdown('<div class="ta-rule"></div>', unsafe_allow_html=True)
    # Two options on top: run mode + which model(s).
    mode, models_to_run, model_keys = render_run_mode(DEFAULT_CONFIG["deep_think_llm"])
    st.markdown('<div class="ta-rule"></div>', unsafe_allow_html=True)

    if not run:
        st.markdown(
            '<div class="ta-card"><h4>Ready</h4><div style="color:var(--muted);font-size:14px">'
            'Pick a ticker/date and a run mode, then Run. <b>Selected model</b> streams one run live; '
            '<b>Parallel</b> runs several models at once and compares their calls side-by-side. '
            'Manage and health-check models on the <b>LLM Models</b> tab.</div></div>',
            unsafe_allow_html=True)
        return
    if not ticker:
        st.error("Enter a ticker."); return
    if not selected:
        st.error("Select at least one analyst."); return
    if not models_to_run:
        st.error("Select at least one model."); return

    # Stop control. Clicking any widget mid-run makes Streamlit abandon the
    # in-flight script at its next UI call, so this returns to idle at the next
    # stage (single) / model (parallel) boundary.
    if st.button("Stop", key="stop_run",
                 help="Abandon the current run and return to idle (takes effect at the next stage/model boundary)."):
        st.rerun()

    if mode.startswith("Selected"):
        model = models_to_run[0]
        prov = provider_for(model)
        cfg = build_config(DEFAULT_CONFIG, provider=prov, deep_model=model, quick_model=model,
                           debate_rounds=debate_rounds, risk_rounds=risk_rounds,
                           social_source=source, twitter_keywords=keywords,
                           ticker=ticker)
        configure_cfg(cfg, model)               # real provider / base_url / key
        run_single_streaming(ticker, trade_date, selected, cfg, prov, model)
    else:
        run_parallel_live(models_to_run, ticker, trade_date, selected,
                          debate_rounds, risk_rounds, model_keys, source, keywords)


if __name__ == "__main__":
    main()
