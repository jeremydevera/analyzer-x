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

import datetime as _dt
import html
import time
import json
import logging
import os
import sys
import traceback
from pathlib import Path
from typing import NamedTuple

import streamlit as st

logger = logging.getLogger(__name__)

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
_QWEN = {"label": "qwen", "provider": "qwen", "base_url": None, "key_env": "DASHSCOPE_API_KEY"}
# Alibaba MaaS workspace (dedicated host) — OpenAI-compatible; serves glm-5.1 etc.
_MAAS = {"label": "maas", "provider": "openai_compatible",
         "base_url": "https://ws-wu00l7n3hmiafz2q.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
         "key_env": "MAAS_API_KEY"}
# Catalog pruned 2026-08-18 against a live ping of every model. Removed:
# deepseek-ai/* (410 Gone — NVIDIA retired the endpoint) and all four OpenAI
# models (429 "exceeded your current quota" — errors until the OpenAI account
# is funded). Earlier prunes (2026-07-31): Cloudflare @cf/* + partner deepseek
# (401), claude-opus-4-8 (no key), glm-4.7 + qwen3-coder:480b (410),
# z-ai/glm-5.1 (410), moonshotai/kimi-k2.6 (404). Re-add any of them on the
# LLM Models tab if the key/endpoint comes back.
MODELS: dict[str, dict] = {
    "gemini-3.1-flash-lite": _GOOGLE,            # free · fast · clean
    "gemini-3.5-flash": _GOOGLE,                 # free
    "gpt-oss:120b": _OLLAMA,                     # Ollama Cloud · free
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
/* Every element using the mono face is showing numbers that get compared
   column-to-column (PnL, prices, dates). Proportional digits make the
   columns shift as values change; tabular-nums locks the width. Declared
   once here rather than in each of the 31 inline blocks. */
[style*="--font-mono"], [style*="font-mono"], .ta-mono,
[style*="IBM Plex Mono"] { font-variant-numeric: tabular-nums; }


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

# Night mode: the same design, re-tokened. Injected AFTER the base CSS so the
# variable overrides win; a handful of Streamlit widget internals need
# explicit repaints because they don't read our variables.
DARK_CSS = """
<style>
:root {
  --bg:#0f1318; --panel:#151b23; --panel-2:#1a222c; --sidebar:#151b23;
  --border:#2a3441; --border-soft:#232c37; --border-strong:#3a4757;
  --text:#e3e9f1; --muted:#8b98a9; --faint:#5d6979;
  --accent:#4c8dff; --accent-dim:#6ea3ff; --accent-wash:#16233a;
}
[data-testid="stAppViewContainer"], .stApp{ background:var(--bg) !important; }
[data-testid="stHeader"]{ background:transparent !important; }
h1,h2,h3,h4,h5,h6,p,li,label,span,div{ color:inherit; }
.stMarkdown, [data-testid="stWidgetLabel"] p{ color:var(--text); }
/* Radio/checkbox OPTION labels are not stWidgetLabel — Streamlit leaves them at
   the light theme's near-black, which is invisible on the night background.
   The calendar's "REAL money / PAPER (demo)" choices read as blank without this. */
[data-testid="stRadio"] label p, [data-testid="stCheckbox"] label p,
[data-testid="stRadio"] label span, [data-testid="stCheckbox"] label span{
  color:var(--text) !important; }
/* …except the nav pills, which keep a LIGHT pill background from the base CSS.
   The rule above would paint light text on it and blank out the current tab. */
.st-key-nav_page [role="radiogroup"] label p{ color:var(--muted) !important; }
.st-key-nav_page [role="radiogroup"] label:hover{ background:var(--panel-2); }
.st-key-nav_page [role="radiogroup"] label:has(input:checked){
  background:var(--panel-2); }
.st-key-nav_page [role="radiogroup"] label:has(input:checked) p{
  color:var(--text) !important; }
[data-testid="stCaptionContainer"] p{ color:var(--muted) !important; }
.stTextInput input, .stNumberInput input, .stTextArea textarea{
  background:var(--panel-2) !important; color:var(--text) !important;
  border-color:var(--border) !important; }
[data-baseweb="select"] > div{
  background:var(--panel-2) !important; border-color:var(--border) !important;
  color:var(--text) !important; }
[data-baseweb="select"] span, [data-baseweb="select"] div{ color:var(--text); }
[data-baseweb="popover"] li, [data-baseweb="menu"]{
  background:var(--panel-2) !important; color:var(--text) !important; }
[data-baseweb="tag"]{ background:var(--accent-wash) !important;
  color:var(--accent-dim) !important; }
.stButton button{ background:var(--panel-2); color:var(--text);
  border-color:var(--border); }
.stButton button[kind="primary"]{ background:var(--accent); color:#fff; }
.stNumberInput button{ background:var(--panel-2) !important;
  color:var(--text) !important; border-color:var(--border) !important; }
[data-testid="stExpander"] details{ background:var(--panel);
  border-color:var(--border) !important; }
[data-testid="stVerticalBlockBorderWrapper"]{
  border-color:var(--border) !important; background:var(--panel); }
[data-testid="stMetricValue"]{ color:var(--text); }
/* Glide data grid paints its own colors; inversion approximates the theme. */
[data-testid="stDataFrame"]{ filter:invert(0.9) hue-rotate(180deg); }
[data-testid="stAlert"]{ filter:none; }
hr{ border-color:var(--border); }
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
PAGES = ("New Crypto", "Stocks", "Auto Trade", "LLM Models")


UI_PREFS = Path(os.path.expanduser("~/.tradingagents/ui_prefs.json"))


def _ui_prefs_load() -> dict:
    try:
        return json.loads(UI_PREFS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def render_nav() -> str:
    """Brand mark plus the screen tabs on top. Returns the selected screen."""
    st.markdown(
        '<div class="ta-brand"><div class="ta-mark">◈</div>'
        '<div><div class="ta-brand-name">TradingAgents</div>'
        '<div class="ta-brand-sub">Terminal</div></div></div>',
        unsafe_allow_html=True)
    nav1, nav2 = st.columns([6, 1])
    page = nav1.radio("Screen", PAGES, horizontal=True,
                      label_visibility="collapsed", key="nav_page")
    if "ui_night" not in st.session_state:
        st.session_state["ui_night"] = bool(_ui_prefs_load().get("night"))
    night = nav2.toggle("Night mode", key="ui_night")
    prefs = _ui_prefs_load()
    if bool(prefs.get("night")) != night:
        UI_PREFS.parent.mkdir(parents=True, exist_ok=True)
        UI_PREFS.write_text(json.dumps({**prefs, "night": night}),
                            encoding="utf-8")
    if night:
        st.markdown(DARK_CSS, unsafe_allow_html=True)
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
    elif page == "Auto Trade":
        render_auto_trade_tab()
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
    except fx.MexcFuturesError as exc:
        # Narrow on purpose. A bare `except Exception` here would swallow a typo in
        # this function and silently return no funding — and funding is 40% of the
        # measured return on this contract, so the backtest would quietly lose its
        # largest component with nothing on screen to say so. That exact pattern
        # made _tradable_notional a no-op for an hour.
        logger.warning("funding history unavailable for %s: %s", symbol, exc)
        return []


@st.cache_data(ttl=1800, show_spinner=False)
def _funding_summary(symbol: str) -> dict:
    from tradingagents.dataflows import mexc_futures as fx
    try:
        return fx.funding_summary(symbol)
    except fx.MexcFuturesError as exc:
        logger.warning("funding summary unavailable for %s: %s", symbol, exc)
        return {"available": False}


@st.cache_data(ttl=600, show_spinner=False)
def _futures_contracts() -> list[dict]:
    """Tradeable MEXC perpetuals, cached — 920 contracts is one slow request."""
    from tradingagents.dataflows import mexc_futures as fx
    return fx.list_contracts()



@st.cache_data(ttl=300, show_spinner=False)
def _tradable_notional(symbol: str, margin: float, leverage: float,
                       cap: float) -> float:
    """The notional the bot can actually put on, not the arithmetic ideal.

    Contracts are indivisible, so a $15 target becomes 19 contracts worth $14.65 —
    2.4% less. The backtest sized to the ideal and therefore reported returns on a
    position the exchange cannot express.
    """
    # `fx` is imported inside render_trade_tab, not at module scope, so referencing
    # it here raised NameError — swallowed by the except below, which made this
    # function always return the ideal and do nothing at all. A broad except that
    # hides a typo is worse than no except.
    from tradingagents.dataflows import mexc_futures as _fx

    want = min(margin * leverage, cap)
    try:
        px = _fx.last_price(symbol)
        vol = _fx.contracts_for(symbol, want, px)
        size = float(_fx.contract_spec(symbol).get("contractSize") or 0)
    except _fx.MexcFuturesError:
        return want                       # exchange unreachable: use the ideal
    if vol >= 1 and size > 0 and px > 0:
        return vol * size * px
    return want

# Each entry: key, label, evidence note, default contracts.
# The 1h block below is the shortlist that survived the 941-coin sweep with
# measured slippage, then a split-half holdout (profitable in BOTH halves of
# its history), then a stability re-run on fresh candles. Figures are $10 base
# margin, 20x, DEEP ladder, costs included. See docs/INCIDENT-2026-08-12-BDX.md
# for why raw sweep profit alone is not evidence.
AUTO_STRATEGIES = (
    # Only the strategies actually deployed appear here. The specs for
    # every other config still live in auto_trader.STRATEGY_SPECS, so a
    # tile can be restored in one line; an unticked tile on the page is
    # just clutter the operator has to read past.
    ("mom15_4h_w", "Momentum 15 (4h) · TP 8.0% — PI",
     "Winner of a 630-combination grid on PI's full 18-month history "
     "(2026-08-13): #1 of 105 configs. +$1,283 martingale / +$293 flat at $5 "
     "base — vs +$884 / +$168 for the 4.5% version it replaces. 19/19 months "
     "green, profitable in BOTH halves at BOTH sizings (+$768 / +$462 "
     "martingale), 433 trades instead of 666 so less fee drag. Same signal "
     "and timeframe as before — only the barriers are wider.",
     ("PI_USDT",)),
    ("mom6_1h_pv", "Momentum 6 (1h) · TP 4.0% — PROVE",
     "Replaced trend50 (4h) on 2026-08-17. Winner of a 3,432-combination "
     "search over PROVE's own 1-hour year, with MEXC's 4.50% liquidation "
     "modelled — an earlier pass without it crowned an 8% stop the venue "
     "would never have let fire. Flat-staked this is the ONLY signal that "
     "survives on PROVE at 1h: +$171.77 over 375 days, 38.8% win across 765 "
     "trades, both halves positive (+$98 / +$70), 10/13 months green, worst "
     "trade -$2.10. trend50 on the same terms: +$89.57 at 29.5%. The cost is "
     "depth — worst dip $57 against trend50's $28 at a $5 base.",
     ("PROVE_USDT",)),
    ("sweep30_1h_w", "Liquidity sweep 30 (1h) · TP 4.0% — APEX",
     "The strongest evidence in the 55,062-combination all-market sweep "
     "(2026-08-14): one of only TWO configs that survived FLAT-staked over a "
     "real year. APEX_USDT flat +$55.72 at $5 base, 10/12 months green, "
     "profitable in BOTH halves (+$17 / +$36), 302 trades over 320 days. "
     "Martingale +$141.16 — but note the ladder makes it LESS consistent "
     "(7/12 green), so the flat figure is the honest one. Cost 6% of target.",
     ("APEX_USDT",)),
    ("fvg_1h_w", "ICT fair value gap (1h) · TP 4.0% — ALICE",
     "Most consistent martingale survivor in the same sweep: +$443 at $5 "
     "base, 13/15 months green over 416 days, both halves strongly positive. "
     "Its FLAT version is also clearly profitable (+$80.20, the highest flat "
     "figure of any candidate), so the edge is in the signal rather than the "
     "ladder — though its flat months (8/15) miss the 70% survivor bar. "
     "570 trades. Cost 3% of target.",
     ("ALICE_USDT",)),
    ("mom6_1h_gx", "Momentum 6 (1h) · TP 2.4% — XAUT gold",
     "The ONLY 1-hour configuration in the 55,062-combination all-market "
     "sweep that survived at BOTH sizings on a real year. Flat +$36.96 at $5 "
     "base (11/15 months green, both halves positive: +$14.71 / +$23.04) AND "
     "martingale +$148.01 (14/15 green). 282 trades over 416 days, 31.6% win "
     "rate. Gold's 0.01% taker fee makes the round-trip cost just 1% of the "
     "target — the cheapest contract on the venue. Same barriers as the "
     "mom15 version it replaces; only the signal differs.",
     ("XAUT_USDT",)),
    ("mom15_1h_g", "Momentum 15 (1h) · TP 2.4% — GOLD (XAUT/PAXG)",
     "RE-MEASURED 2026-08-13 on 10,000 fresh 1h bars (14 months), real fees "
     "+ slippage. XAUT_USDT: martingale +$382 (14/15 green) but FLAT only "
     "+$48 (9/15 green, halves +8 / +36) — a weak but genuinely two-sided "
     "edge. PAXG_USDT: martingale +$301 (15/15 green) but FLAT +$1.95 "
     "(7/15 green, FIRST HALF NEGATIVE −$13) — that headline is the ladder, "
     "not the signal. Cost is 1% of target on XAUT, 5% on PAXG. Prefer XAUT.",
     ("XAUT_USDT",)),
)

AUTO_TRADE_SETTINGS = Path(os.path.expanduser("~/.tradingagents/auto_trade.json"))


def _fmt_when(ts: float) -> str:
    """Operator's requested format: Aug 13, 2026 (8:03PM)."""
    d = _dt.datetime.fromtimestamp(ts)
    hour = d.hour % 12 or 12
    return f"{d:%b} {d.day}, {d.year} ({hour}:{d:%M}{d:%p})"


def _fmt_age(seconds: float) -> str:
    """How long a position has been open, in words."""
    seconds = max(0, int(seconds))
    d, r = divmod(seconds, 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def _auto_trade_load() -> dict:
    try:
        return json.loads(AUTO_TRADE_SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _auto_trade_save(payload: dict) -> None:
    AUTO_TRADE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    AUTO_TRADE_SETTINGS.write_text(json.dumps(payload, indent=2), encoding="utf-8")


@st.cache_data(ttl=900, show_spinner=False)
def _auto_bt_klines(symbol: str, interval: str, limit: int):
    from tradingagents.dataflows import mexc_futures as fx
    return fx.klines(symbol, interval, limit)


@st.cache_data(ttl=10, show_spinner=False)
def _live_open_positions() -> list:
    """The exchange's open positions, cached so the 5-second status fragment
    doesn't hammer MEXC's private API."""
    from tradingagents.dataflows import mexc_futures as fx
    if not fx.has_credentials():
        return []
    return fx.open_positions()


@st.cache_data(ttl=3600, show_spinner=False)
def _contract_size(symbol: str) -> float:
    """USDT of underlying per CONTRACT. Not always 1: XAUT is 0.001, so
    entry x vol overstated its notional 1000x and told the operator a 2.40%
    take-profit was worth +2,279 USDT on a 5 USDT margin position."""
    from tradingagents.dataflows import mexc_futures as fx
    try:
        return float(fx.contract_spec(symbol).get("contractSize") or 1.0)
    except Exception:
        return 1.0


@st.cache_data(ttl=300, show_spinner=False)
def _edge_check(key: str, symbol: str, margin: float) -> dict:
    """Live liquidity/edge verdict for a strategy-coin pair, cached 5 min."""
    from tradingagents import auto_trader as at
    return at.edge_check(key, symbol, margin)


@st.cache_data(ttl=10, show_spinner=False)
def _last_price(symbol: str) -> float | None:
    """Mark price for a symbol, cached — used to value DRY-RUN positions,
    which the exchange knows nothing about."""
    from tradingagents.dataflows import mexc_futures as fx
    try:
        return float(fx.last_price(symbol))
    except Exception:
        return None


@st.cache_data(ttl=30, show_spinner=False)
def _wallet_equity() -> float | None:
    from tradingagents.dataflows import mexc_futures as fx
    if not fx.has_credentials():
        return None
    try:
        return fx.usdt_equity()
    except Exception:
        return None


# TP/SL pairs swept per timeframe, scaled to the bar. CLAUDE.md rule 18 asks
# for at least three pairs per timeframe and BOTH sizings, because the ladder
# is a sizing choice, not a measurement: an audit showed the "13/13 green
# months" behind six live strategies came from the ladder, not the signal.
_BT_GRID = {
    900: [(.004, .008), (.005, .010), (.005, .015), (.008, .016), (.008, .024)],
    1800: [(.005, .010), (.006, .018), (.008, .016), (.010, .020), (.010, .030)],
    3600: [(.005, .010), (.006, .018), (.008, .016), (.008, .024), (.010, .020),
           (.010, .030), (.010, .040), (.015, .030), (.015, .045), (.020, .040),
           (.025, .040), (.025, .050), (.030, .060)],
    14400: [(.010, .020), (.015, .020), (.015, .030), (.015, .045), (.020, .030),
            (.020, .040), (.020, .060), (.020, .080), (.025, .050), (.030, .060)],
    86400: [(.020, .040), (.025, .050), (.030, .060), (.030, .090), (.040, .080),
            (.040, .120)],
}


# A momentum signal's THRESHOLD — how big a move counts — changes which bars
# fire at all, so it changes the trade list as much as the barriers do. The
# backtest used to hold it at whatever was deployed and never showed it, which
# meant the button could not reach a configuration found by a wider search and
# said nothing about the gap.
_BT_TH = {900: [.001, .002, .003], 1800: [.002, .003, .004],
          3600: [.002, .003, .005], 14400: [.004, .006, .008],
          86400: [.008, .010, .015]}


def _bt_thresholds(spec: dict) -> list:
    """Thresholds to sweep, always including the deployed one. Signals with no
    threshold get a single ``None`` pass."""
    if "threshold" not in spec:
        return [None]
    out = list(_BT_TH.get(int(spec.get("bar_seconds") or 0), [.003]))
    live = round(float(spec["threshold"]), 6)
    if live not in [round(x, 6) for x in out]:
        out.append(live)
    return sorted(set(out))


def _bt_pairs(spec: dict) -> list:
    """The barrier grid for this strategy's bar, always including its LIVE
    pair so the table can show what is actually deployed beside the
    alternatives."""
    pairs = list(_BT_GRID.get(int(spec.get("bar_seconds") or 0), []))
    live = (round(float(spec["sl"]), 6), round(float(spec["tp"]), 6))
    if live not in [(round(a, 6), round(b, 6)) for a, b in pairs]:
        pairs.append(live)
    return sorted(set(pairs))


def _render_strategy_backtest(key: str, label: str, coins: list[str],
                              base_margin: float, days: int = 365) -> None:
    """Run the strategy's exact live rules over MEXC history, one row per
    coin. Same engine as the runner: DEEP ladder, 20x, worst-case fills."""
    import pandas as pd

    from tradingagents import auto_trader as at
    if not coins:
        st.error("Select at least one contract to backtest.")
        return
    spec = at.STRATEGY_SPECS[key]
    # Ask for a YEAR of bars, not a fixed 2000 — 2000 bars is 333 days on 4h
    # but only 83 days on 1h, which quietly turned a "1 year" backtest into
    # under three months. Rule 13: never cap a fetch below what the venue
    # serves for the window being claimed.
    _need = int(days * 86400 / spec["bar_seconds"] * 1.15)
    _limit = max(300, min(_need, 10_000))
    _cut = pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(days=days)
    _pairs = _bt_pairs(spec)
    _threshes = _bt_thresholds(spec)
    # Liquidation, from MEXC's own maintenance margin. Without it a stop wider
    # than the liquidation distance looks survivable when the venue would have
    # closed the position first and taken the whole margin.
    from tradingagents.dataflows import mexc_futures as _fx0
    _liq = {}
    _live_sizing = at.sizing_for(_auto_trade_load())
    rows = []
    logs: dict[str, dict] = {}
    _ncombo = len(coins) * len(_pairs) * len(_threshes) * 2
    with st.spinner(f"backtesting {len(coins)} coin(s) × {len(_threshes)} "
                    f"threshold(s) × {len(_pairs)} TP/SL pairs × 2 sizings = "
                    f"{_ncombo} combinations over {days} days of MEXC "
                    f"{spec['interval']} history…"):
        for coin in coins:
            try:
                df = _auto_bt_klines(coin, spec["interval"], _limit)
            except Exception as exc:
                st.warning(f"{coin}: no history ({exc})")
                continue
            # Trim to exactly the window claimed. A coin younger than that
            # keeps whatever it has, and the row states its real depth.
            df = df[df["Date"] >= _cut]
            if len(df) < 30:
                st.warning(f"{coin}: only {len(df)} bars inside the last "
                           f"{days} days — too little to test.")
                continue
            _fee = at.taker_fee(coin)
            try:
                _liq[coin] = _fx0.liquidation_move_pct(coin, at.LEVERAGE)
            except Exception:
                _liq[coin] = None
            _hi = [float(x) for x in df["High"]]
            _lo = [float(x) for x in df["Low"]]
            _cl = [float(x) for x in df["Close"]]
            for _th in _threshes:
                # The signal array depends on the THRESHOLD, so it is rebuilt
                # per threshold — but only once, not once per barrier pair.
                # A throwaway key: never mutate the deployed spec, which the
                # runner brackets with and the grid renders from.
                if _th is None:
                    _dirs = at._dirs_for_backtest(key, _hi, _lo, _cl)
                else:
                    _tk = f"{key}__bt"
                    at.STRATEGY_SPECS[_tk] = {**spec, "threshold": _th}
                    try:
                        _dirs = at._dirs_for_backtest(_tk, _hi, _lo, _cl)
                    finally:
                        at.STRATEGY_SPECS.pop(_tk, None)
                for _sl, _tp in _pairs:
                    for _sz in ("martingale", "flat"):
                        r = at.backtest_strategy(
                            key, df, base_margin=base_margin, fee=_fee,
                            sizing=_sz, dirs=_dirs, tp=_tp, sl=_sl,
                            liq_move_pct=_liq.get(coin))
                        _is_live = (abs(_tp - spec["tp"]) < 1e-9
                                    and abs(_sl - spec["sl"]) < 1e-9
                                    and _sz == _live_sizing
                                    and (_th is None
                                         or abs(_th - spec.get("threshold", 0))
                                         < 1e-9))
                        _lk = (f"{coin}|{_sl * 100:.2f}|{_tp * 100:.2f}|{_sz}"
                               f"|{'-' if _th is None else f'{_th * 100:.2f}'}")
                        logs[_lk] = r
                        rows.append({
                            "LIVE": "◀ DEPLOYED" if _is_live else "",
                            "coin": coin,
                            "TF": spec["interval"],
                            "thresh %": ("—" if _th is None
                                         else round(_th * 100, 2)),
                            "SL %": round(_sl * 100, 2),
                            "TP %": round(_tp * 100, 2),
                            "R:R": round(_tp / _sl, 2) if _sl else 0.0,
                            "sizing": _sz,
                            "leverage": f"{at.LEVERAGE}x",
                            "base margin $": base_margin,
                            "notional $": round(base_margin * at.LEVERAGE, 2),
                            "trades": r["trades"],
                            "trades/day": round(r["trades"] / max(r["days"], 1), 2),
                            "WINS": r["wins"],
                            "LOSSES": r["losses"],
                            "win %": round(100 * r["wins"] / r["trades"], 1)
                                     if r["trades"] else 0.0,
                            "PROFIT TOTAL $": r["profit"],
                            "months green": f"{r['months_green']}/"
                                            f"{r['months_total']}",
                            "worst month $": r["worst_month"],
                            "worst trade $": r["worst_trade"],
                            "max drawdown $": r["max_dd"],
                            "days of history": r["days"],
                            "_log": _lk,
                        })
    if not rows:
        st.error("No coin returned enough history to test.")
        return
    _dmax = max(r["days of history"] for r in rows)
    _dep = next((r for r in rows if r["LIVE"]), None)
    _best = max(rows, key=lambda r: r["PROFIT TOTAL $"])
    st.markdown(
        f"<div class='tm-p' style='margin:6px 0 8px'>"
        f"<div class='row'><span>DEPLOYED &middot; SL "
        + (f"{_dep['SL %']:.2f}% / TP {_dep['TP %']:.2f}% &middot; "
           f"{_dep['sizing']}" if _dep else "not in this grid")
        + "</span><span class='"
        + (_tm_cls(_dep["PROFIT TOTAL $"]) if _dep else "tm-nil")
        + "' style='font-weight:700'>"
        + (f"{_dep['PROFIT TOTAL $']:+,.2f} USDT" if _dep else "—")
        + "</span></div>"
        f"<div class='row'><span>BEST IN GRID &middot; SL "
        f"{_best['SL %']:.2f}% / TP {_best['TP %']:.2f}% &middot; "
        f"{_best['sizing']}</span>"
        f"<span class='{_tm_cls(_best['PROFIT TOTAL $'])}' "
        f"style='font-weight:700'>{_best['PROFIT TOTAL $']:+,.2f} USDT"
        f"</span></div>"
        f"<div class='row sub'><span style='color:var(--t-faint)'>"
        f"{len(coins)} contract(s) &times; {len(_threshes)} threshold(s) "
        f"&times; {len(_pairs)} TP/SL pairs &times; 2 sizings = "
        f"<b>{len(rows)} combinations tested</b> "
        f"&middot; {days}-day window &middot; {_dmax} days served "
        f"&middot; {at.LEVERAGE}x &middot; base {base_margin:g} USDT "
        f"({base_margin * at.LEVERAGE:g} notional)</span>"
        f"<span style='color:var(--t-faint)'>"
        f"{_best['trades']} trades &middot; {_best['WINS']}W / "
        f"{_best['LOSSES']}L &middot; {_best['trades/day']:.2f}/day "
        f"at best</span></div></div>", unsafe_allow_html=True)
    st.caption(
        "Every row is the SAME signal at different barriers — only TP, SL and "
        "sizing change. Flat is what the signal measures; the DEEP ladder "
        "multiplies whatever edge exists, including a negative one, so a row "
        "that only wins on martingale is telling you about the ladder rather "
        "than the strategy. Fills are worst-case: MEXC taker fee 0.02%/side "
        "PLUS 0.03%/side slippage, because a live market order never fills at "
        "the printed candle price. Columns sort on click.")
    _df = pd.DataFrame(rows).sort_values(
        "PROFIT TOTAL $", ascending=False).reset_index(drop=True)
    st.dataframe(_df.drop(columns=["_log"]), width="stretch", height=430)
    # Trade-by-trade log for each combination, best first.
    for _lk, r in sorted(logs.items(), key=lambda kv: -kv[1]["profit"]):
        _c, _s, _t, _z, _th = _lk.split("|")
        with st.expander(
                f"Trades — {_c} · SL {_s}% / TP {_t}% · {_z}"
                + ("" if _th == "-" else f" · threshold {_th}%") + " · "
                f"{r['trades']} trades · {r['wins']} WIN / {r['losses']} LOSE "
                f"· TOTAL PROFIT {r['profit']:+.2f} $"):
            st.metric("TOTAL PROFIT", f"{r['profit']:+.2f} $")
            if r["log"]:
                _lg = pd.DataFrame(r["log"]).rename(columns={
                    "entry time": "OPENED", "exit time": "CLOSED",
                    "step": "ladder rung", "why": "closed by"})
                # How long each trade was actually held — the question the two
                # timestamps are usually being read to answer.
                _o = pd.to_datetime(_lg["OPENED"])
                _c = pd.to_datetime(_lg["CLOSED"])
                _h = (_c - _o).dt.total_seconds() / 3600.0
                _lg.insert(2, "HELD", [
                    f"{v/24:.1f}d" if v >= 24 else f"{v:.1f}h" for v in _h])
                _lg = _lg[["OPENED", "CLOSED", "HELD", "side", "closed by",
                           "entry", "exit", "TP px", "SL px", "ladder rung",
                           "margin $", "notional $", "leverage",
                           "WIN/LOSE", "pnl $", "running total $"]]
                _nliq = int((_lg["closed by"] == "LIQ").sum())
                st.caption(
                    f"{len(_lg)} trades · median hold "
                    f"{pd.Series(_h).median():.1f}h · longest "
                    f"{max(_h)/24:.1f}d"
                    + (f" · **{_nliq} LIQUIDATED**" if _nliq else "")
                    + ". OPENED is the bar the entry filled on, CLOSED the bar "
                      "the barrier was hit.")
                st.dataframe(_lg, width="stretch", height=400)
            else:
                st.caption("No trades in the tested window.")


# ---------------------------------------------------------------------------
# Auto Trade is a TERMINAL, and it commits to that one visual world: it paints
# its own near-black ground and monospace grid regardless of the app's Night
# toggle. That is deliberate, not an oversight. Two separate bugs on
# 2026-08-15 were "correct value, invisible text" caused by this screen
# inheriting a theme it did not control (radio options black-on-black, the nav
# pill white-on-white). A band that owns its palette cannot have that bug.
# ---------------------------------------------------------------------------
TERMINAL_CSS = """
<style>
.st-key-term{
  --t-ground:#07090b; --t-panel:#0d1115; --t-panel2:#121820;
  --t-rule:#1b232b; --t-rule2:#2c3844;
  --t-ink:#d3dbe3; --t-dim:#63717f; --t-faint:#3d4854;
  --t-amber:#f0a848; --t-up:#35d07f; --t-dn:#ff5f56;
  background:var(--t-ground); color:var(--t-ink);
  font-family:var(--font-mono); font-variant-numeric:tabular-nums;
  padding:18px 20px 22px; border:1px solid var(--t-rule);
}
.st-key-term p, .st-key-term span, .st-key-term div, .st-key-term label{
  font-family:var(--font-mono); }
/* …but NEVER the Material icon spans. Their glyphs are ligatures, so a mono
   font renders the ligature's source text: the expander chevrons came out as
   the literal word "arrow_right" printed over the contract column. */
.st-key-term [data-testid="stIconMaterial"],
.st-key-term .material-symbols-rounded, .st-key-term [class*="material"]{
  font-family:"Material Symbols Rounded" !important; }

/* ---- band header: amber tick, tracked label, rule to the right edge ---- */
.tm-h{ display:flex; align-items:center; gap:10px; margin:22px 0 8px; }
.tm-h:first-child{ margin-top:0; }
.tm-h .k{ color:var(--t-amber); font-size:10.5px; letter-spacing:.22em;
  text-transform:uppercase; white-space:nowrap; }
.tm-h .k::before{ content:"\\258C"; margin-right:7px; }
.tm-h .r{ flex:1; height:1px; background:var(--t-rule2); }
.tm-h .v{ color:var(--t-dim); font-size:10.5px; letter-spacing:.14em;
  text-transform:uppercase; white-space:nowrap; }

/* ---- the readout ribbon: cells split by hairlines, no cards ---- */
.tm-rib{ display:flex; border:1px solid var(--t-rule2); background:var(--t-panel); }
.tm-rib > div{ flex:1; padding:10px 14px; border-left:1px solid var(--t-rule); }
.tm-rib > div:first-child{ border-left:0; }
.tm-rib .l{ font-size:9.5px; letter-spacing:.16em; text-transform:uppercase;
  color:var(--t-dim); margin-bottom:3px; white-space:nowrap; }
.tm-rib .n{ font-size:23px; font-weight:600; letter-spacing:-.02em;
  line-height:1.15; }
.tm-rib .s{ font-size:10.5px; color:var(--t-dim); margin-top:2px; }
.tm-up{ color:var(--t-up); } .tm-dn{ color:var(--t-dn); }
.tm-nil{ color:var(--t-dim); } .tm-am{ color:var(--t-amber); }

/* ---- the strategy grid. Monospace + white-space:pre IS the column
       alignment — no table markup can survive inside an expander label. ---- */
/* Font size and left offset are MEASURED against the expander rows below
   (text starts at x=112, 12.5px). Change either and the header stops sitting
   over its own columns — the whole grid is monospace alignment, nothing else
   holds it together. */
.tm-th{ white-space:pre; font-size:12.5px; letter-spacing:.02em;
  color:var(--t-dim); padding:6px 0 5px 21px;
  border-bottom:1px solid var(--t-rule2); }
/* Streamlit paints :green[]/:red[]/:gray[] with its LIGHT theme's ink, inline,
   so it is near-invisible on this band's near-black ground. These are the
   three literal values it emits. */
.st-key-term .stMarkdownColoredText[style*="21, 130, 55"]{
  color:var(--t-up) !important; }
.st-key-term .stMarkdownColoredText[style*="189, 64, 67"]{
  color:var(--t-dn) !important; }
.st-key-term .stMarkdownColoredText[style*="49, 51, 63"]{
  color:var(--t-faint) !important; }
.st-key-term [data-testid="stExpander"]{ border:0 !important;
  background:transparent !important; }
.st-key-term [data-testid="stExpander"] details{ border:0 !important;
  border-bottom:1px solid var(--t-rule) !important; border-radius:0 !important;
  background:transparent !important; }
.st-key-term [data-testid="stExpander"] summary{ padding:0 !important;
  border-radius:0 !important; min-height:0 !important; }
/* Streamlit puts ~1rem of gap between stacked blocks; on a 24px terminal row
   that reads as a list of cards, not a grid. */
.st-key-term [data-testid="stExpander"]{ margin-bottom:0 !important; }
.st-key-term [data-testid="stVerticalBlock"]:has(> [data-testid="stExpander"]){
  gap:0 !important; }
.st-key-term [data-testid="stExpander"] summary:hover{
  background:var(--t-panel2) !important; }
.st-key-term [data-testid="stExpander"] summary p{ white-space:pre;
  font-size:12.5px !important; letter-spacing:.02em; color:var(--t-ink);
  line-height:2.1; }
.st-key-term [data-testid="stExpander"] summary svg{ fill:var(--t-faint); }
.st-key-term [data-testid="stExpanderDetails"]{ background:var(--t-panel);
  border-left:2px solid var(--t-amber); padding:12px 16px !important;
  margin:0 0 2px 22px; }

/* ---- tables: a CSS grid, because st.dataframe cannot hold a button and
       st.data_editor cannot colour a cell. `__POSGRID__` is substituted from
       _TM_POS at render time so the header, every row and this rule can never
       disagree about the column count; the smaller tables override
       grid-template-columns inline. ---- */
.tm-pt{ display:grid; grid-template-columns:__POSGRID__; gap:11px;
  align-items:center; font-size:11px; padding:5px 8px;
  border-bottom:1px solid var(--t-rule); }
.tm-pt .c{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.tm-pt .r{ text-align:right; }
.tm-pt .l{ text-align:left; }
.tm-pt-h{ color:var(--t-dim); font-size:10px; letter-spacing:.08em;
  text-transform:uppercase; border-bottom:1px solid var(--t-rule2); }
.tm-pt-t{ font-weight:700; border-top:1px solid var(--t-rule2);
  border-bottom:0; background:var(--t-panel); }
/* Each book is a hard-bordered box with a solid badge, because two ruled
   grids stacked together read as one table — and "real money or simulator?"
   is the one thing this section must never leave ambiguous. */
.tm-badge{ display:inline-block; padding:3px 10px; margin:0 0 8px;
  font-size:10px; letter-spacing:.16em; font-weight:700; color:#07090b; }
.st-key-pos_real, .st-key-pos_paper{ border-radius:0 !important;
  padding:12px 14px 6px !important; margin-bottom:14px !important; }
.st-key-pos_real{ border:1px solid var(--t-dn) !important;
  border-left:4px solid var(--t-dn) !important;
  background:rgba(255,95,86,.03) !important; }
.st-key-pos_paper{ border:1px solid var(--t-up) !important;
  border-left:4px solid var(--t-up) !important;
  background:rgba(53,208,127,.03) !important; }
.st-key-pos_real .tm-badge{ background:var(--t-dn); }
.st-key-pos_paper .tm-badge{ background:var(--t-up); }

/* The close button sits in its own column beside the row. */
.st-key-term [data-testid="stColumn"] .stButton button{ padding:2px 8px !important;
  font-size:10px !important; letter-spacing:.06em; width:100%; }

/* ---- ledger panels: ruled rows, totals set off by a heavy rule ---- */
.tm-p{ border:1px solid var(--t-rule2); background:var(--t-panel);
  padding:11px 13px; font-size:12px; line-height:1.85; }
.tm-p .row{ display:flex; justify-content:space-between; gap:8px; }
.tm-p .sub{ border-top:1px solid var(--t-rule2); margin-top:5px; padding-top:5px; }
.tm-p .tot{ border-top:2px solid var(--t-rule2); margin-top:4px; padding-top:5px;
  font-weight:700; }
.tm-big{ font-size:34px; font-weight:700; line-height:1.1; letter-spacing:-.03em; }
.tm-feed{ max-height:230px; overflow-y:auto; border:1px solid var(--t-rule);
  background:var(--t-panel); padding:8px 11px; font-size:11.5px; line-height:1.65;
  color:var(--t-dim);
  /* Oldest at the top, newest at the bottom, scrolled to the newest — the
     way a terminal reads. column-reverse over a reversed DOM is the only way
     to get the auto-scroll without a script. */
  display:flex; flex-direction:column-reverse; }

/* Strategy-grid rows: one height for every cell so the columns line up.
   Streamlit gives a text input 35px, a checkbox 21px and a bare span 13px;
   left alone they sit on three different baselines across the row. */
.st-key-term [data-testid="stColumn"] [data-testid="stTextInput"],
.st-key-term [data-testid="stColumn"] [data-testid="stNumberInput"]{
  margin:0 !important; }
.st-key-term [data-testid="stColumn"] [data-testid="stTextInput"] input,
.st-key-term [data-testid="stColumn"] [data-testid="stNumberInput"] input{
  height:30px !important; padding:2px 8px !important; }
.st-key-term [data-testid="stColumn"] [data-testid="stCheckbox"]{
  min-height:38px; display:flex; align-items:center; margin:0 !important; }
.st-key-term [data-testid="stColumn"] [data-testid="stElementContainer"]{
  margin-bottom:0 !important; }

/* Every column row in the terminal is a LAYOUT row, never a data row, so the
   app-wide `align-items:center` must not reach in here — it floats a short
   column into the middle of a tall neighbour. */
.st-key-term [data-testid="stHorizontalBlock"]{ align-items:flex-start; }
/* The 150px app-wide cap on number inputs clamps the widget's own label and
   wraps it into its help icon. */
.st-key-term [data-testid="stNumberInput"]{ max-width:230px; }

/* ---- Streamlit widgets, repainted for the dark band ---- */
.st-key-term [data-testid="stWidgetLabel"] p{ color:var(--t-dim) !important;
  font-size:10px !important; letter-spacing:.14em; text-transform:uppercase; }
.st-key-term [data-testid="stCheckbox"] p,
.st-key-term [data-testid="stRadio"] label p{ color:var(--t-ink) !important;
  font-size:12px !important; text-transform:none; letter-spacing:0; }
/* A ticked book is GREEN — the same green as a profit, so "on" and "good"
   read the same way down the table. Streamlit's own primary is orange, which
   on this band was indistinguishable from the amber used for the ladder. */
.st-key-term label[data-baseweb="checkbox"] > span:first-child{
  background:var(--t-panel2) !important;
  border-color:var(--t-rule2) !important; }
.st-key-term label[data-baseweb="checkbox"]:has(input:checked) > span:first-child{
  background:var(--t-up) !important; border-color:var(--t-up) !important; }
.st-key-term input, .st-key-term textarea{ background:var(--t-panel2) !important;
  color:var(--t-ink) !important; border-color:var(--t-rule2) !important;
  border-radius:0 !important; }
.st-key-term [data-baseweb="select"] > div{ background:var(--t-panel2) !important;
  border-color:var(--t-rule2) !important; border-radius:0 !important;
  color:var(--t-ink) !important; }
.st-key-term [data-baseweb="tag"]{ background:var(--t-panel2) !important;
  color:var(--t-amber) !important; border-radius:0 !important; }
/* A multiselect's search box is a 16px-wide input that BaseWeb parks UNDER
   the first tag and keeps transparent. Giving every input in the band an
   opaque panel background painted it over the tag's first glyph, so
   PROVE_USDT rendered as "ROVE_USDT". Measured: input at x=136 w=16, the
   tag's text starts at x=144. */
.st-key-term [data-baseweb="select"] input{ background:transparent !important; }
.st-key-term .stButton button{ background:var(--t-panel2) !important;
  color:var(--t-ink) !important; border:1px solid var(--t-rule2) !important;
  border-radius:0 !important; font-family:var(--font-mono) !important;
  font-size:11.5px !important; letter-spacing:.1em; text-transform:uppercase; }
.st-key-term .stButton button:hover{ border-color:var(--t-amber) !important;
  color:var(--t-amber) !important; }
.st-key-term .stButton button[kind="primary"]{ background:var(--t-amber) !important;
  color:#0a0c0e !important; border-color:var(--t-amber) !important;
  font-weight:700 !important; }
.st-key-term .stNumberInput button{ background:var(--t-panel2) !important;
  border-color:var(--t-rule2) !important; }
.st-key-term [data-testid="stCaptionContainer"] p{ color:var(--t-dim) !important;
  font-size:11.5px !important; }
.st-key-term [data-testid="stAlert"]{ border-radius:0 !important;
  background:var(--t-panel) !important; }
.st-key-term [data-testid="stDataFrame"]{ filter:invert(.92) hue-rotate(180deg); }
</style>
"""

# Bar length -> the name a trader uses for it.
_TF_NAMES = {60: "1m", 300: "5m", 900: "15m", 1800: "30m", 3600: "1h",
             7200: "2h", 14400: "4h", 28800: "8h", 86400: "1d"}


def _tm_tf(spec: dict) -> str:
    """Timeframe read from the spec's bar length, never parsed out of a key."""
    return _TF_NAMES.get(int(spec.get("bar_seconds") or 0), "—")


def _tm_sig(key: str) -> str:
    """The signal name inside a strategy key ('mom15_4h_w' -> 'mom15')."""
    parts = key.split("_")
    return parts[1] if parts and parts[0] == "ict" and len(parts) > 1 else parts[0]


def _tm_head(label: str, value: str = "") -> str:
    return (f"<div class='tm-h'><span class='k'>{label}</span>"
            f"<span class='r'></span><span class='v'>{value}</span></div>")


def _tm_cls(v: float) -> str:
    return "tm-up" if v > 0 else "tm-dn" if v < 0 else "tm-nil"



# Column widths for the strategy grid. The header and every row use these
# same numbers — change one, change both, or the columns stop lining up.

# Each strategy picks its own book. "off" is a real option, not the absence of
# one — a strategy can be loaded, configured and deliberately trading nowhere.


def _books_to_choice(books: list) -> str:
    """['real','paper'] -> 'both'. The stored form is a list so the runner can
    ask 'is this book mine?'; the UI form is one choice."""
    has_r, has_p = "real" in books, "paper" in books
    return ("both" if has_r and has_p else "real" if has_r
            else "paper" if has_p else "off")


def _choice_to_books(choice: str) -> list:
    return {"off": [], "paper": ["paper"], "real": ["real"],
            "both": ["real", "paper"]}[choice]


def _parse_contracts(text: str, known: set | None = None) -> tuple:
    """'pi, btc' -> (['PI_USDT','BTC_USDT'], []).

    Returns the symbols AND the rejects. A typo must never silently arm
    nothing: the caller names what it dropped so an empty strategy is
    obviously a mistake rather than a quiet choice.
    """
    good, bad = [], []
    for tok in str(text or "").split(","):
        tok = tok.strip().upper().replace(" ", "")
        if not tok:
            continue
        sym = tok if tok.endswith("_USDT") else f"{tok}_USDT"
        if known and sym not in known:
            bad.append(sym)
        elif sym not in good:
            good.append(sym)
    return good, bad

# The positions table: (key, header, weight, alignment, kind). Money columns
# are coloured by sign; everything else is plain. Header and rows are built
# from THIS list, so a column can never appear in one and not the other.
_TM_POS = (
    # `state` and `vol` are still carried on the row — the open/flat filter
    # and the close order both need them — they are simply not displayed.
    ("coin", "coin", 1.1, "l", "text"),
    ("total $", "total $", 1.4, "r", "money"),
    ("realised $", "realised $", 1.8, "r", "money"),
    ("open $", "unreal $", 1.5, "r", "money"),
    ("prog", "to TP", 2.6, "l", "html"),
    ("tp_pct", "TP % ($)", 2.4, "r", "html"),
    ("sl_pct", "SL % ($)", 2.4, "r", "html"),
    ("W", "W", 0.5, "r", "num"),
    ("L", "L", 0.5, "r", "num"),
    ("trades", "trd", 0.7, "r", "num"),
    ("side", "side", 1.0, "l", "text"),
    ("strategy", "strategy", 2.1, "l", "text"),
    ("opened", "opened", 1.9, "l", "text"),
    ("held", "held", 1.2, "l", "text"),
    ("entry", "entry", 1.4, "r", "px"),
    # The TP/SL PRICES were dropped: entry plus TP %/SL % says the same thing
    # in the unit the strategy is specified in, and 20 columns did not fit —
    # every strategy name and timestamp was ellipsised to make room for them.
    # `lev` went too; it is 20x on every row and now sits in the band header.
    ("margin $", "margin", 1.1, "r", "num"),
    ("bracket", "bracket", 1.3, "l", "text"),
)
_TM_POS_GRID = " ".join(f"{w}fr" for _, _, w, _a, _k in _TM_POS)


def _tm_pos_head() -> str:
    return "".join(
        f"<span class='c {a}'>{html.escape(lab)}</span>"
        for _k, lab, _w, a, _kind in _TM_POS)


def _tm_progress(entry, tp, sl, px, side: int) -> str:
    """A bar showing how far this position has travelled from its ENTRY
    toward its take-profit — green — or toward its stop — red.

    Works for both directions because the span is signed: for a short, tp sits
    below entry, so (px - entry) / (tp - entry) is still positive when the
    trade is winning. Returns "" when any leg is missing rather than drawing a
    bar from a guess.
    """
    try:
        entry, tp, sl, px = float(entry), float(tp), float(sl), float(px)
    except (TypeError, ValueError):
        return ""
    if not entry or not px or side == 0:
        return ""
    tp_span, sl_span = tp - entry, sl - entry
    moved = px - entry
    if tp_span and (moved / tp_span) >= 0:
        frac, colour, target = moved / tp_span, "var(--t-up)", "TP"
    elif sl_span:
        frac, colour, target = moved / sl_span, "var(--t-dn)", "SL"
    else:
        return ""
    pct = max(0.0, min(frac, 1.0)) * 100
    return (
        f"<span style='display:inline-flex;align-items:center;gap:6px;"
        f"width:100%'>"
        f"<span style='flex:1;height:9px;background:var(--t-panel2);"
        f"border:1px solid var(--t-rule2);position:relative;min-width:40px'>"
        f"<span style='position:absolute;left:0;top:0;bottom:0;"
        f"width:{pct:.1f}%;background:{colour}'></span></span>"
        f"<span style='color:{colour};font-size:10.5px;white-space:nowrap'>"
        f"{pct:.0f}%&nbsp;{target}</span></span>")


def _tm_pos_cell(val, kind: str) -> str:
    """One cell. An absent value prints an em dash, never 'None' — a missing
    price and a broken one must not look the same."""
    if kind == "html":
        return str(val) if val else ""
    if val is None or val == "":
        return "—" if kind != "text" else ""
    if kind == "money":
        return f"<span class='{_tm_cls(float(val))}'>{float(val):+.2f}</span>"
    if kind == "px" and isinstance(val, (int, float)):
        # Simulated brackets carry full float noise (0.09547200000000002);
        # six significant figures is past any contract's price scale.
        return f"{val:.6g}"
    if kind == "num" and isinstance(val, (int, float)):
        return f"{val:g}"
    return html.escape(str(val))


def _tm_pos_row(r: dict) -> str:
    return "".join(
        f"<span class='c {a}'>{_tm_pos_cell(r.get(k), kind)}</span>"
        for k, _lab, _w, a, kind in _TM_POS)


def _tm_table(cols: tuple, rows: list, total: dict | None = None,
              empty: str = "nothing yet") -> str:
    """A small ruled table sharing the positions grid's look.

    ``cols`` is (key, label, weight, align, kind). The TOTAL row, when given,
    is rendered from the SAME cell formatter as the body, so a total can never
    be formatted — or coloured — differently from the rows it sums.
    """
    tmpl = "grid-template-columns:" + " ".join(f"{w}fr" for _k, _l, w, _a, _kd
                                               in cols)
    head = "".join(f"<span class='c {a}'>{html.escape(lab)}</span>"
                   for _k, lab, _w, a, _kd in cols)
    out = [f"<div class='tm-pt tm-pt-h' style='{tmpl}'>{head}</div>"]
    if not rows:
        return (out[0] + f"<div style='font-size:11.5px;color:var(--t-faint);"
                         f"padding:7px 8px'>{empty}</div>")
    for r in rows:
        cells = "".join(
            f"<span class='c {a}'>{_tm_pos_cell(r.get(k), kd)}</span>"
            for k, _l, _w, a, kd in cols)
        out.append(f"<div class='tm-pt' style='{tmpl}'>{cells}</div>")
    if total is not None:
        cells = "".join(
            f"<span class='c {a}'>{_tm_pos_cell(total.get(k), kd)}</span>"
            for k, _l, _w, a, kd in cols)
        out.append(f"<div class='tm-pt tm-pt-t' style='{tmpl}'>{cells}</div>")
    return "".join(out)


def render_auto_trade_tab() -> None:
    """The trading terminal: status ribbon, strategy grid, risk, book, feed."""
    from tradingagents import auto_trader as at
    from tradingagents.dataflows import mexc_credentials as cred
    from tradingagents.dataflows import mexc_futures as fx

    cred.load_into_env()
    saved = _auto_trade_load()
    term = st.container(key="term")

    with term:
        # The positions grid template is built from _TM_POS so the header,
        # every row and the CSS can never disagree about the column count.
        st.markdown(TERMINAL_CSS.replace("__POSGRID__", _TM_POS_GRID),
                    unsafe_allow_html=True)

        # ================= BAND 1 — SYSTEM ==============================
        # Its own fragment so the ribbon can refresh at the top of the page
        # without dragging the whole terminal through a rerun.
        # Refresh rates are staggered and matched to the cache TTLs below.
        # All three panels used to run at 5s, firing independently, which
        # redrew the page up to three times every five seconds — the operator
        # saw it as the screen blinking. Nothing here changes faster than its
        # cache anyway, so a faster tick only redraws the same numbers.
        @st.fragment(run_every=10)
        def _ribbon() -> None:
            pid = at.runner_pid()
            books = at.active_modes()
            live, paper_on = False in books, True in books
            equity = _wallet_equity()
            day = at.pnl_today(dry=False)
            paper = at.pnl_today(dry=True)
            open_real = 0.0
            open_n = 0
            open_bits: list[tuple] = []
            try:
                for p in _live_open_positions():
                    _u = float(p.get("unRealizedPnl") or 0.0)
                    open_real += _u
                    open_n += 1
                    open_bits.append(
                        (str(p.get("symbol", "?")).replace("_USDT", ""), _u))
                open_bits.sort(key=lambda r: -abs(r[1]))
            except Exception:
                open_real, open_n, open_bits = 0.0, 0, []
            open_paper = 0.0
            for _s, _sst in at.load_state().items():
                _p = _sst.get("position") if isinstance(_sst, dict) else None
                if _p and _p.get("dry"):
                    _px = _last_price(_s)
                    if _px and _p.get("entry"):
                        open_paper += ((_px / _p["entry"] - 1) * _p["side"]
                                       * _p["margin"] * at.LEVERAGE)
            life = at.coin_stats(dry=False)
            life_total = round(sum(v["pnl"] for v in life.values()), 2)
            all_time = life_total + open_real
            paper_total = paper["total"] + open_paper
            if pid:
                mode = ("LIVE+PAPER" if live and paper_on else
                        "LIVE" if live else "PAPER")
                mode_cls = "tm-dn" if live else "tm-up"
            else:
                mode, mode_cls = "STOPPED", "tm-nil"
            st.markdown(
                _tm_head("System", f"pid {pid}" if pid else "no process")
                + "<div class='tm-rib'>"
                f"<div><div class='l'>Futures wallet</div><div class='n'>"
                f"{f'{equity:,.2f}' if equity is not None else '—'}</div>"
                f"<div class='s'>USDT collateral</div></div>"
                f"<div><div class='l'>Real &middot; all time</div>"
                f"<div class='n {_tm_cls(all_time)}'>{all_time:+,.2f}</div>"
                f"<div class='s'>{life_total:+.2f} closed &middot; "
                f"{open_real:+.2f} open</div></div>"
                f"<div><div class='l'>Real &middot; today closed</div>"
                f"<div class='n {_tm_cls(day['total'])}'>{day['total']:+,.2f}</div>"
                f"<div class='s'>{day['wins']}W / {day['losses']}L &middot; "
                f"{day['trades']} closed</div></div>"
                # Unrealized is money that has NOT been banked, so it never
                # joins the realized figure in one number. It is also not a
                # "today" quantity — a position open since the 13th carries
                # its whole life in here — so the label says OPEN NOW, and
                # the coins are itemised rather than hidden behind a total
                # (a summed figure once shipped labelled with one coin's name).
                f"<div><div class='l'>Open now &middot; unrealized</div>"
                f"<div class='n {_tm_cls(open_real)}'>{open_real:+,.2f}</div>"
                f"<div class='s'>"
                + (" &middot; ".join(f"{_c} {_v:+.2f}" for _c, _v in open_bits)
                   if open_bits else "no position open")
                + "</div></div>"
                f"<div><div class='l'>Paper &middot; demo</div>"
                f"<div class='n {_tm_cls(paper_total)}'>{paper_total:+,.2f}</div>"
                f"<div class='s'>not real money</div></div>"
                f"<div><div class='l'>Runner</div>"
                f"<div class='n {mode_cls}'>{mode}</div>"
                f"<div class='s'>{'entries halted' if at.halted() else 'scanning'}"
                f"</div></div></div>", unsafe_allow_html=True)

        _ribbon()

        # ================= BAND 2 — POSITIONS ===========================
        @st.fragment(run_every=20)
        def _positions() -> None:
            # ONE table per book. Open positions and per-coin PnL used to be
            # four separate tables; the same contract appeared in two of them
            # with different columns, which read as duplication.
            def _book_rows(dry: bool):
                stats = at.coin_stats(dry)
                rows: dict[str, dict] = {}

                def _blank(sym):
                    v = stats.get(sym, {"pnl": 0.0, "wins": 0, "losses": 0,
                                        "trades": 0, "strategies": "—"})
                    return {"coin": sym.replace("_USDT", ""),
                            # kept for the close buttons; dropped from the
                            # displayed frame by the _order filter below
                            "symbol": sym,
                            "state": "flat", "side": "—",
                            "strategy": v["strategies"],
                            "opened": "—", "held": "—",
                            "vol": None, "margin $": None,
                            "lev": f"{at.LEVERAGE}x",
                            "entry": None, "TP": None, "SL": None,
                            "tp_pct": None, "sl_pct": None, "prog": "",
                            "open $": 0.0,
                            "realised $": round(v["pnl"], 2),
                            "total $": round(v["pnl"], 2),
                            "trades": v["trades"], "W": v["wins"],
                            "L": v["losses"], "bracket": "—"}

                for sym in stats:
                    rows[sym] = _blank(sym)
                for _sym, _sst in at.load_state().items():
                    _pos = (_sst.get("position")
                            if isinstance(_sst, dict) else None)
                    if not _pos or bool(_pos.get("dry", False)) is not dry:
                        continue
                    _base = _sym.split("#")[0]
                    r = rows.setdefault(_base, _blank(_base))
                    _op = None
                    if dry:
                        _px = _last_price(_base)
                        if _px and _pos.get("entry"):
                            _op = round((_px / _pos["entry"] - 1)
                                        * _pos["side"] * _pos["margin"]
                                        * at.LEVERAGE, 2)
                    _when = _pos.get("opened_at") or _pos.get("entry_ts")
                    r.update({
                        "state": "OPEN",
                        "side": "LONG" if _pos["side"] > 0 else "SHORT",
                        "strategy": _pos.get("strategy", r["strategy"]),
                        # Compact stamp: "Aug 14, 2026 (4:00AM)" does not fit
                        # a grid cell and ellipsised to "Aug 14, 20…", which
                        # hides the part that matters — the time.
                        "opened": (_dt.datetime.fromtimestamp(_when)
                                   .strftime("%m-%d %H:%M") if _when else "—"),
                        "held": (_fmt_age(time.time() - _when) if _when
                                 else "—"),
                        "vol": _pos.get("vol"), "margin $": _pos.get("margin"),
                        "entry": _pos.get("entry"), "TP": _pos.get("tp"),
                        "SL": _pos.get("sl"),
                        "bracket": ("SIMULATED" if dry
                                    else "on MEXC" if _pos.get("bracket", True)
                                    else "RETRYING"),
                    })
                    if _op is not None:
                        r["open $"] = _op
                # the exchange is the source of truth for the REAL book
                if not dry:
                    try:
                        for _p in _live_open_positions():
                            _sym = _p.get("symbol")
                            r = rows.setdefault(_sym, _blank(_sym))
                            if r["state"] != "OPEN":
                                r["state"] = "OPEN"
                                r["strategy"] = "(not the bot's)"
                                r["side"] = ("LONG"
                                             if _p.get("positionType") == 1
                                             else "SHORT")
                            r["vol"] = _p.get("holdVol", r["vol"])
                            r["entry"] = _p.get("holdAvgPrice", r["entry"])
                            _u = _p.get("unRealizedPnl")
                            if _u is not None:
                                r["open $"] = round(float(_u), 2)
                    except Exception as exc:
                        st.caption(f"could not read MEXC positions: {exc}")
                out = [r for r in rows.values() if r["state"] == "OPEN"]
                for r in out:
                    r["total $"] = round(r["realised $"] + (r["open $"] or 0), 2)
                    # Barriers as PERCENTAGES off the entry, plus how far the
                    # price has travelled toward one of them. Percent is what
                    # the strategy is specified in; the raw prices alone make
                    # you do the arithmetic every time you look.
                    _e, _tp, _sl = r.get("entry"), r.get("TP"), r.get("SL")
                    _side = 1 if r.get("side") == "LONG" else -1
                    # …and what each barrier is WORTH on this position, net of
                    # the round-trip taker fee. The percentage is on the
                    # NOTIONAL, so the dollar figure is the only one that says
                    # what actually lands in the wallet.
                    _vol = r.get("vol") or 0
                    _notional = (float(_e or 0) * float(_vol)
                                 * _contract_size(r.get("symbol") or ""))
                    try:
                        _fee = at.taker_fee(r.get("symbol") or "")
                    except Exception:
                        _fee = 0.0004
                    _cost = _notional * _fee * 2
                    if _e and _tp:
                        _p = abs(float(_tp) / float(_e) - 1) * 100
                        _usd = _notional * _p / 100 - _cost
                        r["tp_pct"] = (f"{_p:.2f} <span class='tm-up'>"
                                       f"({_usd:+,.2f})</span>")
                    if _e and _sl:
                        _p = abs(float(_sl) / float(_e) - 1) * 100
                        _usd = -(_notional * _p / 100 + _cost)
                        r["sl_pct"] = (f"{_p:.2f} <span class='tm-dn'>"
                                       f"({_usd:+,.2f})</span>")
                    _now = _last_price(r.get("symbol") or "")
                    r["prog"] = _tm_progress(_e, _tp, _sl, _now, _side)
                out.sort(key=lambda r: r["total $"])
                return out

            _real, _paper = _book_rows(False), _book_rows(True)
            st.markdown(
                _tm_head("Positions",
                         f"{len(_real)} real &middot; {len(_paper)} paper "
                         f"&middot; {at.LEVERAGE}x isolated"),
                unsafe_allow_html=True)
            # Each book gets its OWN bordered box with a coloured badge. Two
            # ruled grids stacked with only a small caption between them read
            # as one table, and "is this row real money or the simulator?" is
            # the single question this section must never leave ambiguous.
            for _label, _rows, _empty, _boxkey in (
                    ("REAL — MONEY AT RISK", _real,
                     "none — no real money at risk", "pos_real"),
                    ("PAPER — DEMO, NOT REAL MONEY", _paper,
                     "none — no simulated position open", "pos_paper")):
              with st.container(key=_boxkey, border=True):
                st.markdown(
                    f"<div class='tm-badge'>{_label}</div>",
                    unsafe_allow_html=True)
                if not _rows:
                    st.markdown(f"<div style='font-size:12px;"
                                f"color:var(--t-faint);padding:2px 0 6px'>"
                                f"{_empty}</div>", unsafe_allow_html=True)
                    continue
                # Rendered as a grid rather than st.dataframe because a
                # dataframe cannot host a widget, and the close control has
                # to live on the row it closes.
                _closable = _rows is _real
                # The header must sit in the SAME 10/1.15 split as the rows,
                # or its grid is 144px wider than theirs and every label
                # drifts off its own column.
                _hc, _ = st.columns([10, 1.15], gap="small")
                _hc.markdown(
                    f"<div class='tm-pt tm-pt-h'>{_tm_pos_head()}</div>",
                    unsafe_allow_html=True)
                for _r in _rows:
                    _rc, _bc = st.columns([10, 1.15], gap="small")
                    _rc.markdown(f"<div class='tm-pt'>{_tm_pos_row(_r)}</div>",
                                 unsafe_allow_html=True)
                    if _closable:
                        # The coin moved out of the label and into the
                        # tooltip. Row/button alignment is asserted at 0px,
                        # and the confirm step names the contract in full
                        # before anything is sent — so a bare "Close" cannot
                        # flatten something the operator did not mean.
                        if _bc.button("Close", key=f"cl_{_r['symbol']}",
                                      help=f"Close {_r['symbol']} at market"):
                            st.session_state["close_pending"] = _r["symbol"]
                            st.rerun(scope="fragment")
                # The TOTAL row is derived from the rows above it, never
                # carried in from elsewhere.
                _sum = {
                    "coin": "TOTAL", "state": "", "side": "", "strategy": "",
                    "opened": "", "held": "", "lev": "", "bracket": "",
                    "entry": None, "TP": None, "SL": None, "vol": None,
                    "margin $": None,
                    # A total has no barriers and no progress of its own.
                    "tp_pct": None, "sl_pct": None, "prog": "",
                    "trades": sum(int(r["trades"]) for r in _rows),
                    "W": sum(int(r["W"]) for r in _rows),
                    "L": sum(int(r["L"]) for r in _rows),
                    "open $": round(sum(r["open $"] or 0 for r in _rows), 2),
                    "realised $": round(sum(r["realised $"] or 0
                                            for r in _rows), 2),
                    "total $": round(sum(r["total $"] or 0 for r in _rows), 2)}
                _tc, _ = st.columns([10, 1.15], gap="small")
                _tc.markdown(
                    f"<div class='tm-pt tm-pt-t'>{_tm_pos_row(_sum)}</div>",
                    unsafe_allow_html=True)

            # ---- the second half of the per-row close. Real money and no
            # undo, so it takes two clicks: the row button names the contract,
            # this states exactly what is being flattened before it is sent.
            _pend = st.session_state.get("close_pending")
            if _pend:
                _row = next((r for r in _real if r["symbol"] == _pend), None)
                if _row is None:
                    # It closed on its own (TP/SL) between the two clicks.
                    st.session_state.pop("close_pending", None)
                    st.info(f"{_pend} is no longer open — nothing to close.")
                else:
                    _mg = _row.get("margin $") or 0
                    st.warning(
                        f"**Close {_pend} at market now?** {_row['side']} "
                        f"{_row['vol']} contracts, entry {_row['entry']}, "
                        f"{_mg} USDT margin at {at.LEVERAGE}x. Unrealised "
                        f"**{_row['open $']:+.2f} USDT** becomes real the "
                        f"moment this fills. There is no undo, and the "
                        f"strategy may re-enter on its next signal.")
                    _y, _n = st.columns([1, 1])
                    if _y.button("CONFIRM — close at market", type="primary",
                                 key="cl_confirm"):
                        rep = at.close_one(_pend)
                        st.session_state.pop("close_pending", None)
                        # The positions read is cached for 5 s; without this
                        # the table would still show the closed position.
                        _live_open_positions.clear()
                        if rep["closed"]:
                            st.success(
                                f"{_pend} closed. Realised "
                                + (f"{rep['realised']:+.2f} USDT."
                                   if rep["realised"] is not None
                                   else "PnL not yet reported by MEXC."))
                        else:
                            st.error(f"NOT closed — {rep['error']}. The "
                                     f"position is still open and still "
                                     f"tracked.")
                    if _n.button("Cancel", key="cl_cancel"):
                        st.session_state.pop("close_pending", None)
                        st.rerun(scope="fragment")

            # ---- what the removed BOOK band used to carry, as tables.
            # Today's closes are itemised because a net figure hides the
            # trades inside it: +2.71 and -1.66 net to +1.05, which is
            # indistinguishable from one flat trade.
            _lt = time.localtime()
            _mid = time.mktime((_lt.tm_year, _lt.tm_mon, _lt.tm_mday,
                                0, 0, 0, 0, 0, -1))
            _today = [e for e in at.ledger_since(_mid)
                      if e.get("action") == "exit" and not e.get("dry_run")]
            _trows = [{
                "when": _dt.datetime.fromtimestamp(
                    float(e.get("ts") or 0)).strftime("%H:%M"),
                "coin": str(e.get("symbol", "?")).replace("_USDT", ""),
                "strategy": e.get("strategy") or "—",
                "why": (e.get("why") or "—"),
                "PROFIT $": round(float(e.get("pnl_est") or 0), 2),
            } for e in sorted(_today, key=lambda x: -float(x.get("ts") or 0))]
            _tcols = (("when", "time", 1.0, "l", "text"),
                      ("coin", "coin", 1.2, "l", "text"),
                      ("strategy", "strategy", 2.0, "l", "text"),
                      ("why", "closed by", 2.0, "l", "text"),
                      ("PROFIT $", "PROFIT $", 1.3, "r", "money"))
            _ttot = {"when": "TOTAL", "coin": "", "strategy": "",
                     "why": f"{len(_trows)} closed",
                     "PROFIT $": round(sum(r["PROFIT $"] for r in _trows), 2)}
            st.markdown(
                "<div style='font-size:10px;letter-spacing:.14em;"
                "text-transform:uppercase;color:var(--t-dim);"
                "margin:16px 0 4px'>Today &middot; real closes</div>"
                + _tm_table(_tcols, _trows, _ttot if _trows else None,
                            "no trades closed today"),
                unsafe_allow_html=True)

            # All-time per contract. Realised comes from this book's ledger,
            # open from the exchange, and the two are added — never mixed.
            _life = at.coin_stats(dry=False)
            _open_by: dict[str, float] = {}
            try:
                for _p in _live_open_positions():
                    _open_by[str(_p.get("symbol"))] = float(
                        _p.get("unRealizedPnl") or 0.0)
            except Exception:
                _open_by = {}
            try:
                _cfg = at.load_settings()
                _mine = {c for v in (_cfg.get("strategy_coins")
                                     or {}).values() for c in v}
            except Exception:
                _mine = set()
            # The DEMO book, kept in its own columns. Simulated money is never
            # added to the real figures — mixing them is how an operator
            # misjudges what is actually at risk — so each side carries its
            # own realised, open and TOTAL, and the footer sums them apart.
            _demo = at.coin_stats(dry=True)
            _dopen: dict[str, float] = {}
            for _s, _sst in at.load_state().items():
                _p = _sst.get("position") if isinstance(_sst, dict) else None
                if not _p or not _p.get("dry"):
                    continue
                _base = _s.split("#")[0]
                _px = _last_price(_base)
                if _px and _p.get("entry"):
                    _dopen[_base] = _dopen.get(_base, 0.0) + (
                        (_px / _p["entry"] - 1) * _p["side"] * _p["margin"]
                        * at.LEVERAGE)
            _arows = []
            for _sym in sorted(set(_life) | set(_open_by) | set(_demo)
                               | set(_dopen),
                               key=lambda s: (_life.get(s, {}).get("pnl", 0)
                                              + _open_by.get(s, 0))):
                _v = _life.get(_sym, {"pnl": 0.0, "wins": 0, "losses": 0,
                                      "trades": 0})
                _d = _demo.get(_sym, {"pnl": 0.0, "wins": 0, "losses": 0,
                                      "trades": 0})
                _op, _dop = _open_by.get(_sym, 0.0), _dopen.get(_sym, 0.0)
                _has_demo = bool(_d["trades"] or _dop)
                _arows.append({
                    "coin": _sym.replace("_USDT", ""),
                    "mine": "" if _sym in _mine else "not yours",
                    "W": _v["wins"], "L": _v["losses"],
                    "realised $": round(_v["pnl"], 2),
                    "open $": round(_op, 2),
                    "total $": round(_v["pnl"] + _op, 2),
                    "dW": _d["wins"] if _has_demo else None,
                    "dL": _d["losses"] if _has_demo else None,
                    "d realised $": round(_d["pnl"], 2) if _has_demo else None,
                    "d open $": round(_dop, 2) if _has_demo else None,
                    "d total $": (round(_d["pnl"] + _dop, 2) if _has_demo
                                  else None)})
            _acols = (("coin", "coin", 1.1, "l", "text"),
                      ("mine", "", 1.3, "l", "text"),
                      ("W", "real W", 0.8, "r", "num"),
                      ("L", "real L", 0.8, "r", "num"),
                      ("realised $", "real realised $", 1.7, "r", "money"),
                      ("open $", "real open $", 1.5, "r", "money"),
                      ("total $", "REAL TOTAL $", 1.6, "r", "money"),
                      ("dW", "demo W", 0.8, "r", "num"),
                      ("dL", "demo L", 0.8, "r", "num"),
                      ("d realised $", "demo realised $", 1.7, "r", "money"),
                      ("d open $", "demo open $", 1.5, "r", "money"),
                      ("d total $", "DEMO TOTAL $", 1.6, "r", "money"))
            _sm = lambda k: round(sum(r[k] or 0 for r in _arows), 2)  # noqa: E731
            _atot = {
                "coin": "TOTAL", "mine": f"{len(_arows)} contracts",
                "W": sum(r["W"] for r in _arows),
                "L": sum(r["L"] for r in _arows),
                "realised $": _sm("realised $"),
                "open $": _sm("open $"),
                "total $": _sm("total $"),
                "dW": sum(r["dW"] or 0 for r in _arows),
                "dL": sum(r["dL"] or 0 for r in _arows),
                "d realised $": _sm("d realised $"),
                "d open $": _sm("d open $"),
                "d total $": _sm("d total $")}
            st.markdown(
                "<div style='font-size:10px;letter-spacing:.14em;"
                "text-transform:uppercase;color:var(--t-dim);"
                "margin:16px 0 4px'>All time &middot; per contract &middot; "
                "<span style='color:var(--t-dn)'>real</span> vs "
                "<span style='color:var(--t-up)'>demo</span> &mdash; never "
                "summed together</div>"
                + _tm_table(_acols, _arows, _atot if _arows else None,
                            "no closed trades yet"),
                unsafe_allow_html=True)

        _positions()


        # ================= BAND 3 — STRATEGY ============================
        try:
            contracts = _futures_contracts()
            symbols = sorted(c["symbol"] for c in contracts)
        except Exception as exc:
            symbols = []
            st.warning(f"Could not fetch the MEXC contract list ({exc}); "
                       "showing saved selections only.")
        saved_strats = saved.get("strategies", ["ict_fvg"])
        saved_coins_by = saved.get("strategy_coins") or {}
        legacy_coins = saved.get("coins", ["BTC_USDT"])
        chosen_strats: list[str] = []
        blocked_now: list[tuple] = []
        strategy_coins: dict[str, list[str]] = {}
        strategy_limits: dict[str, float] = {}
        strategy_margins: dict[str, float] = {}
        saved_limits = saved.get("strategy_loss_limits") or {}
        saved_margins = saved.get("strategy_margins") or {}
        live_stats = at.strategy_stats(dry=False)
        paper_stats = at.strategy_stats(dry=True)
        paused = at.tripped_strategies(saved)
        # ---- ONE table, built from real widgets rather than st.data_editor.
        # The editor is a canvas: it cannot colour a cell, and the operator
        # wants a green tick when a book is on and red/green money. So each
        # row is a st.columns strip — widgets where a value is typed, HTML
        # where it is computed and needs colour.
        strategy_books: dict[str, list] = {}
        _bad_syms: list[str] = []
        _runstate = at.load_state()
        _sizing_now = at.sizing_for(saved)
        _flat = _sizing_now == "flat"
        _W = [1.15, 1.45, .62, .62, .95, .95, .8, 2.5, .9, .95, 1.0, .95, 1.0,
              .95]
        _HEADS = ("strategy", "contracts", "LIVE", "DEMO", "base $",
                  "notional $", "streak", f"ladder $ · {'flat' if _flat else 'DEEP'}",
                  "next $", "SL / TP", "loss cap $", "W / L", "PROFIT $",
                  "backtest")

        _head_slot = st.empty()
        st.caption(
            "One row per strategy. LIVE places real orders on MEXC, DEMO "
            "simulates fills in a separate book — independent, so a strategy "
            "can run both, one, or neither. Contracts, base margin and loss "
            "cap are typed in place; press Save & run to commit them. "
            "`ladder $` is the whole DEEP sequence in dollars with the "
            "current rung boxed, so `next $` is never a number you have to "
            "work out.")
        _hc = st.columns(_W, gap="small", vertical_alignment="bottom")
        for _i, _h in enumerate(_HEADS):
            _hc[_i].markdown(
                f"<div style='font-size:9.5px;letter-spacing:.11em;"
                f"text-transform:uppercase;color:var(--t-dim);"
                f"border-bottom:1px solid var(--t-rule2);padding-bottom:4px;"
                f"white-space:nowrap;overflow:hidden;text-overflow:ellipsis'>"
                f"{_h}</div>", unsafe_allow_html=True)

        # Every cell in a strategy row is the same height and vertically
        # centred, so a 35px text input and a 13px text span share a baseline.
        # Before this they sat 11px apart and the row read as ragged.
        _cell = ("display:flex;align-items:center;min-height:38px;"
                 "font-size:11.5px;white-space:nowrap;overflow:hidden;"
                 "text-overflow:ellipsis")
        for key, label, note, default_coins in AUTO_STRATEGIES:
            _spec = at.STRATEGY_SPECS.get(key, {})
            _bks = at.books_for(key, saved) if key in saved_strats else []
            _coins = saved_coins_by.get(key) or list(default_coins)
            _mgs = float(saved_margins.get(key) or 5.0)
            # The LOSING STREAK is the ladder's own counter: it advances on a
            # loss and resets to zero on a win, so it IS the streak, and it is
            # what decides the next stake. Read per contract, worst one wins.
            _streak = max((int((_runstate.get(c) or {}).get("step", 0) or 0)
                           for c in _coins), default=0)
            c = st.columns(_W, gap="small", vertical_alignment="center")
            c[0].markdown(
                f"<div style='{_cell}'>{_tm_sig(key)}"
                f"<span style='color:var(--t-faint)'> {_tm_tf(_spec)}</span>"
                f"</div>", unsafe_allow_html=True)
            _txt = c[1].text_input(
                "contracts", value=", ".join(x.replace("_USDT", "")
                                             for x in _coins),
                key=f"g_c_{key}", label_visibility="collapsed",
                placeholder="PI, BTC")
            _live = c[2].checkbox("LIVE", value=False in _bks,
                                  key=f"g_live_{key}",
                                  label_visibility="collapsed",
                                  help="REAL money — sends orders to MEXC.")
            _demo = c[3].checkbox("DEMO", value=True in _bks,
                                  key=f"g_demo_{key}",
                                  label_visibility="collapsed",
                                  help="Simulated fills, separate book, no "
                                       "real orders.")
            _base = c[4].number_input(
                "base", min_value=1.0, max_value=10_000.0, value=_mgs,
                step=1.0, key=f"g_b_{key}", label_visibility="collapsed")
            c[5].markdown(f"<div style='{_cell}'>"
                          f"{_base * at.LEVERAGE:,.2f}"
                          f"<span style='color:var(--t-faint)'> "
                          f"{at.LEVERAGE}x</span></div>",
                          unsafe_allow_html=True)
            # Streak colour is the risk, not the sign: 0 is calm, deep is red.
            _scol = ("tm-nil" if _streak == 0 else "tm-am" if _streak < 4
                     else "tm-dn")
            c[6].markdown(
                f"<div style='{_cell}' class='{_scol}'><b>{_streak}</b>"
                f"<span style='color:var(--t-faint)'> loss</span></div>",
                unsafe_allow_html=True)
            # The ladder, in dollars, with the rung it is standing on boxed.
            if _flat:
                _lad = (f"<span class='tm-up'>{_base:,.2f}</span>"
                        f"<span style='color:var(--t-faint)'> every trade"
                        f"</span>")
                _next = _base
            else:
                _idx = min(_streak, len(at.LADDER) - 1)
                _next = _base * at.LADDER[_idx]
                _lad = " ".join(
                    (f"<span style='background:var(--t-amber);color:#0a0c0e;"
                     f"padding:1px 4px;font-weight:700'>{_base * m:,.0f}</span>"
                     if i == _idx else
                     f"<span style='color:var(--t-faint)'>{_base * m:,.0f}"
                     f"</span>")
                    for i, m in enumerate(at.LADDER))
            c[7].markdown(f"<div style='{_cell};overflow:visible'>{_lad}</div>",
                          unsafe_allow_html=True)
            c[8].markdown(f"<div style='{_cell}' class='tm-am'>"
                          f"<b>{_next:,.2f}</b></div>",
                          unsafe_allow_html=True)
            c[9].markdown(
                f"<div style='{_cell}'>{_spec.get('sl', 0) * 100:.2f}"
                f"<span style='color:var(--t-faint)'> / </span>"
                f"{_spec.get('tp', 0) * 100:.2f}</div>",
                unsafe_allow_html=True)
            _cap = c[10].number_input(
                "cap", min_value=0.0, max_value=100_000.0,
                value=float(saved_limits.get(key, 0.0)), step=1.0,
                key=f"g_l_{key}", label_visibility="collapsed")
            # The record has to come from the book this strategy trades: a
            # live P&L printed beside a DEMO-only strategy is a false label.
            _stt = (live_stats.get(key) if _live
                    else paper_stats.get(key) if _demo
                    else live_stats.get(key))
            _pnl = _stt["pnl"] if _stt else None
            c[11].markdown(
                f"<div style='{_cell}'>"
                f"<span class='tm-up'>{_stt['wins'] if _stt else 0}</span>"
                f"<span style='color:var(--t-faint)'> / </span>"
                f"<span class='tm-dn'>{_stt['losses'] if _stt else 0}</span>"
                f"</div>", unsafe_allow_html=True)
            c[12].markdown(
                f"<div style='{_cell}' class='{_tm_cls(_pnl or 0)}'><b>"
                + ("·" if _pnl is None else f"{_pnl:+,.2f}")
                + f"</b><span style='color:var(--t-faint)'> "
                + ("live" if _live else "demo" if _demo else "—")
                + "</span></div>", unsafe_allow_html=True)
            # Backtest THIS row, over the past year, on the contracts typed
            # in the row — not on whatever was last saved.
            if c[13].button("1 YEAR", key=f"g_bt_{key}",
                            help=f"Replay {_tm_sig(key)} over the last 365 "
                                 f"days of MEXC history at this row's base "
                                 f"margin."):
                st.session_state["auto_bt_run"] = key

            _cs, _rej = _parse_contracts(_txt, set(symbols))
            _bad_syms.extend(_rej)
            strategy_books[key] = (["real"] if _live else []) + \
                                  (["paper"] if _demo else [])
            strategy_margins[key] = float(_base)
            strategy_limits[key] = float(_cap)
            strategy_coins[key] = _cs
            if _live or _demo:
                chosen_strats.append(key)

        _n_real = sum(1 for v in strategy_books.values() if "real" in v)
        _n_paper = sum(1 for v in strategy_books.values() if "paper" in v)
        _n_off = sum(1 for v in strategy_books.values() if not v)
        _head_slot.markdown(
            _tm_head("Strategy",
                     f"{_n_real} live &middot; {_n_paper} demo &middot; "
                     f"{_n_off} off &middot; {len(AUTO_STRATEGIES)} loaded"),
            unsafe_allow_html=True)
        if _bad_syms:
            st.error("Not MEXC USDT perpetuals — these were dropped: "
                     + ", ".join(sorted(set(_bad_syms))))


        # ---- liquidity gate. The per-pair readout was removed at the
        # operator's request: all six pairs sit at 1–6% of target, so the list
        # was noise. The CHECK still runs, because rule 12 says a blocked pair
        # places no orders — and the runner enforces that itself
        # (auto_trader.edge_check, called again before every entry), so this
        # is only about surfacing it. Nothing is drawn unless a pair is
        # actually blocked, which is the one case worth interrupting for.
        for key in chosen_strats:
            for coin in strategy_coins.get(key, []):
                try:
                    g = _edge_check(key, coin, strategy_margins.get(key) or 5.0)
                except Exception:
                    continue
                if g.get("verdict") == "block":
                    blocked_now.append((key, coin))

        # ---- the backtest a row asked for, rendered under the table. The
        # flag is CLEARED before the run, so a lingering one cannot re-fire
        # the whole year on every later widget interaction.
        if st.session_state.get("auto_bt_run"):
            _k = st.session_state.pop("auto_bt_run")
            _lbl = {k: l for k, l, *_ in AUTO_STRATEGIES}
            st.markdown(
                f"<div style='font-size:10px;letter-spacing:.14em;"
                f"text-transform:uppercase;color:var(--t-amber);"
                f"margin:14px 0 2px'>Backtest &middot; past 365 days &middot; "
                f"{html.escape(_lbl.get(_k, _k))}</div>",
                unsafe_allow_html=True)
            _render_strategy_backtest(_k, _lbl.get(_k, _k),
                                      strategy_coins.get(_k, []),
                                      strategy_margins.get(_k) or 5.0,
                                      days=365)

        chosen_coins = [c for cs in strategy_coins.values() for c in cs]

        # ================= BAND 4 — RISK ================================
        st.markdown(_tm_head("Risk", f"{at.LEVERAGE}x isolated"),
                    unsafe_allow_html=True)
        rk1, rk2 = st.columns([1, 1.6], gap="large")
        with rk1:
            # The book is chosen PER STRATEGY, in the grid above. These two
            # are derived from those choices, not set here — the old global
            # pair could not paper-test one strategy beside a live one.
            _real_ks = [k for k, b in strategy_books.items() if "real" in b]
            _paper_ks = [k for k, b in strategy_books.items() if "paper" in b]
            enabled = bool(_real_ks)
            dry_run = bool(_paper_ks)
            _fmt = (lambda ks: ", ".join(
                sorted({c.replace("_USDT", "")
                        for k in ks for c in (strategy_coins.get(k) or [])}))
                or "none")
            st.markdown(
                f"<div style='font-size:10px;letter-spacing:.14em;"
                f"text-transform:uppercase;color:var(--t-dim)'>Books in "
                f"use</div><div class='tm-p' style='margin:4px 0 12px'>"
                f"<div class='row'><span>REAL &middot; real orders</span>"
                f"<span class='{'tm-dn' if _real_ks else 'tm-nil'}'>"
                f"{len(_real_ks)} strategies</span></div>"
                f"<div class='row'><span style='color:var(--t-faint)'>"
                f"&nbsp;&nbsp;{_fmt(_real_ks)}</span><span></span></div>"
                f"<div class='row sub'><span>PAPER &middot; simulated</span>"
                f"<span class='{'tm-up' if _paper_ks else 'tm-nil'}'>"
                f"{len(_paper_ks)} strategies</span></div>"
                f"<div class='row'><span style='color:var(--t-faint)'>"
                f"&nbsp;&nbsp;{_fmt(_paper_ks)}</span><span></span></div>"
                f"</div>", unsafe_allow_html=True)
            acct_limit = st.number_input(
                "Account loss cap USDT", min_value=0.0,
                max_value=100_000.0, value=float(saved.get("loss_limit", 0.0)),
                step=1.0, key="auto_acct_limit",
                help="0 turns it off. Across ALL strategies: when the day's "
                     "real losses reach this, the whole runner stops and "
                     "drops the kill file. Set it larger than any single "
                     "strategy's limit.")
        with rk2:
            # Sizing is a first-class setting, not an assumption. It was NOT
            # in the save payload, so any Save silently reverted a flat book
            # to the ladder — the exact dimension an audit showed was
            # producing the "13/13 green months" behind six live strategies.
            sizing = st.radio(
                "Position sizing", options=("flat", "martingale"),
                index=0 if at.sizing_for(saved) == "flat" else 1,
                horizontal=True, key="auto_sizing",
                format_func=lambda v: (
                    "Flat — every trade stakes the base margin" if v == "flat"
                    else "Martingale — 1,1,2,2,4,4,8 × base after each loss"),
                help="Flat is what the backtests measure. Martingale "
                     "multiplies whatever edge exists, including a negative "
                     "one, and needs 8x the base margin in the account to "
                     "survive its own worst case.")
            # The worst-case and LIVE-MODE banners were removed at the
            # operator's request. What they said is now on the rows: every
            # strategy shows its own ladder in dollars with the current rung
            # boxed, and the LIVE tick is green next to it. A pair the gate
            # BLOCKS still interrupts, because that one is not a reminder —
            # it means orders will be refused.
            if enabled and blocked_now:
                st.error("**These pairs are blocked by the liquidity gate and "
                         "will place no orders:** "
                         + ", ".join(f"{k} on {c}" for k, c in blocked_now)
                         + ". Untick them or move the strategy to a "
                           "deeper-book contract.")

        sv1, sv2, sv3 = st.columns([1.1, 1, 1])
        if sv1.button("Save & run", type="primary", key="auto_save"):
            _payload = {"strategies": chosen_strats,
                              "strategy_coins": strategy_coins,
                              "coins": chosen_coins,   # legacy union, kept for
                                                       # anything still reading it
                              "strategy_loss_limits": strategy_limits,
                              "strategy_margins": strategy_margins,
                              # The per-strategy book map is the real setting.
                              "strategy_books": {k: v for k, v in
                                                 strategy_books.items() if v},
                              "loss_limit": acct_limit,
                              "sizing": sizing,
                        # Derived, not chosen — kept so anything still
                        # reading the old globals sees the truth.
                        "enabled": enabled, "dry_run": dry_run}
            _auto_trade_save(_payload)
            # "Saved" must mean the FILE says so, not that the write was
            # attempted. Read it back off disk and compare the fields that
            # decide where money goes; only then report success.
            _verified, _diff = False, []
            try:
                _back = json.loads(
                    AUTO_TRADE_SETTINGS.read_text(encoding="utf-8"))
                for _f in ("strategies", "strategy_books", "strategy_coins",
                           "strategy_margins", "strategy_loss_limits",
                           "sizing", "loss_limit"):
                    if _back.get(_f) != _payload.get(_f):
                        _diff.append(_f)
                _verified = not _diff
            except Exception as _exc:
                _diff = [f"could not re-read the file: {_exc}"]
            st.session_state["auto_saved_at"] = {
                "when": time.strftime("%H:%M:%S"), "ok": _verified,
                "diff": _diff, "n": len(chosen_strats),
                "live": sorted(k for k, v in strategy_books.items()
                               if "real" in v),
                "demo": sorted(k for k, v in strategy_books.items()
                               if "paper" in v),
                "path": str(AUTO_TRADE_SETTINGS)}
            st.toast(
                f"Saved — {len(chosen_strats)} strategies written and verified "
                f"on disk" if _verified
                else f"NOT saved cleanly — {', '.join(_diff)}",
                icon="✅" if _verified else "🚨")
            if enabled and at.halted():
                # A deliberate re-enable clears a loss-limit (or manual) halt.
                at.KILL_PATH.unlink(missing_ok=True)
                st.info("Kill file cleared — trading resumes.")
            if (enabled or dry_run) and not chosen_strats:
                st.error("Auto Trade is on but no strategy is armed — the "
                         "runner will start and do nothing.")
            if (enabled or dry_run) and not chosen_coins:
                st.error("Auto Trade is on but no coin is selected — the "
                         "runner will start and do nothing.")
            if enabled or dry_run:
                pid = at.start_runner()
                bk = []
                if enabled:
                    bk.append("**LIVE — real orders on MEXC**")
                if dry_run:
                    bk.append("**PAPER — simulated, separate book**")
                st.success(f"Saved and running (pid {pid}). Running "
                           f"{' and '.join(bk)}.")
            else:
                stopped = at.stop_runner()
                st.success("Saved. Runner stopped — neither switch is on."
                           if stopped else "Saved. Runner was not running.")
        if sv2.button("Stop — halt entries", key="auto_halt"):
            at.KILL_PATH.parent.mkdir(parents=True, exist_ok=True)
            at.KILL_PATH.write_text("stopped from the UI")
            at.stop_runner()
            st.warning("Entries halted and runner stopped. Open positions "
                       "keep their exchange-side TP/SL.")
        _armed_panic = sv3.checkbox(
            "Arm PANIC", key="auto_panic_arm",
            help="Tick this to unlock the PANIC button. It closes EVERY real "
                 "position at market immediately — there is no undo.")
        if sv3.button("PANIC — close all", key="auto_panic",
                      disabled=not _armed_panic):
            rep = at.panic_stop()
            st.error(f"Panic stop. Closed: {rep['closed'] or 'nothing'}."
                     + (f" FAILED: {rep['failed']}" if rep["failed"]
                        else " Runner stopped, entries halted."))
        if at.halted():
            st.error(f"Kill file present at {at.KILL_PATH} — entries halted. "
                     f"Save with a switch ticked to clear it.")
        # The toast disappears after a few seconds; this stays, so the
        # operator can still see WHAT was written and that it was read back.
        _sv = st.session_state.get("auto_saved_at")
        if _sv:
            _sym = lambda ks: ", ".join(   # noqa: E731
                sorted({c.replace("_USDT", "")
                        for k in ks for c in (strategy_coins.get(k) or [])})
            ) or "none"
            st.markdown(
                f"<div class='tm-p' style='margin-top:10px;border-color:"
                f"{'var(--t-up)' if _sv['ok'] else 'var(--t-dn)'}'>"
                f"<div class='row' style='font-size:10px;letter-spacing:.14em;"
                f"text-transform:uppercase;color:var(--t-dim)'>"
                f"<span>Save &middot; {html.escape(_sv['when'])}</span>"
                f"<span class='{'tm-up' if _sv['ok'] else 'tm-dn'}'>"
                + ("WRITTEN &amp; VERIFIED ON DISK" if _sv["ok"]
                   else "FAILED")
                + "</span></div>"
                + (f"<div class='row'><span>LIVE &middot; real orders</span>"
                   f"<span class='tm-dn'>{_sym(_sv['live'])}</span></div>"
                   f"<div class='row'><span>DEMO &middot; simulated</span>"
                   f"<span class='tm-up'>{_sym(_sv['demo'])}</span></div>"
                   f"<div class='row sub'><span style='color:var(--t-faint)'>"
                   f"{html.escape(_sv['path'])}</span>"
                   f"<span style='color:var(--t-faint)'>{_sv['n']} strategies"
                   f"</span></div>"
                   if _sv["ok"] else
                   f"<div class='row'><span>fields that did not match</span>"
                   f"<span class='tm-dn'>"
                   f"{html.escape(', '.join(_sv['diff']))}</span></div>")
                + "</div>", unsafe_allow_html=True)


        # ================= BAND 6 — FEED ================================
        @st.fragment(run_every=30)
        def _feed() -> None:
            log_lines = at.log_tail(200)
            recent = at.ledger_tail(100)
            st.markdown(_tm_head("Feed", "newest at the bottom"),
                        unsafe_allow_html=True)
            f1, f2 = st.columns(2, gap="large")
            with f1:
                st.markdown("<div style='font-size:10px;letter-spacing:.14em;"
                            "text-transform:uppercase;color:var(--t-dim);"
                            "margin-bottom:4px'>Runner log &middot; every scan"
                            "</div>", unsafe_allow_html=True)
                # Terminal order: oldest at the top, newest at the bottom.
                # The DOM order is REVERSED and the box is column-reverse —
                # that renders them the right way up AND keeps the scroll
                # pinned to the newest line, which plain markup cannot do
                # without a script Streamlit would strip.
                st.markdown(
                    "<div class='tm-feed'>"
                    + ("".join(f"<div>{html.escape(l)}</div>"
                               for l in reversed(log_lines))
                       if log_lines else "<div>runner has not logged yet</div>")
                    + "</div>", unsafe_allow_html=True)
            with f2:
                st.markdown("<div style='font-size:10px;letter-spacing:.14em;"
                            "text-transform:uppercase;color:var(--t-dim);"
                            "margin-bottom:4px'>Trades &amp; events</div>",
                            unsafe_allow_html=True)
                rows = []
                for e in recent:
                    bits = [_fmt_when(e.get("ts", 0)),
                            "PAPER" if e.get("dry_run") else "REAL",
                            e.get("symbol", ""), e.get("action", "")]
                    for k in ("strategy", "side", "why"):
                        if e.get(k):
                            bits.append(str(e[k]))
                    if e.get("pnl_est") is not None:
                        bits.append(f"pnl {e['pnl_est']:+.2f}")
                    rows.append(html.escape(" · ".join(str(b) for b in bits)))
                st.markdown("<div class='tm-feed'>"
                            + ("".join(f"<div>{r}</div>" for r in rows)
                               if rows else "<div>no events yet</div>")
                            + "</div>", unsafe_allow_html=True)

        _feed()

        # ================= BAND 7 — CONNECTION ==========================
        cst = cred.status()
        st.markdown(
            _tm_head("Connection",
                     "keys connected" if cst["has_credentials"]
                     else "keys NOT SET"), unsafe_allow_html=True)
        cn1, cn2 = st.columns([1.4, 1], gap="large")
        with cn1:
            # Keys are set once and then never touched, so they live at the
            # bottom of the terminal, out of the reading path.
            with st.expander("MEXC API keys", expanded=False):
                if cst["has_credentials"]:
                    st.markdown(
                        f"<div style='color:var(--t-dim);font-size:12px'>"
                        f"Using existing keys "
                        f"({html.escape(cst['source'])}) — key "
                        f"{html.escape(cst['key_fingerprint'])} · secret "
                        f"{html.escape(cst['secret_fingerprint'])}</div>",
                        unsafe_allow_html=True)
                else:
                    st.warning("No MEXC keys found. Paste a key pair below, "
                               "or export MEXC_API_KEY / MEXC_API_SECRET "
                               "before launching.")
                with st.form("auto_mexc_keys", clear_on_submit=True):
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
                            st.success("Saved.")
                            st.rerun()
                    if f2.form_submit_button("Forget saved keys"):
                        st.warning("Removed." if cred.clear()
                                   else "Nothing stored.")
                        st.rerun()
        with cn2:
            probe_symbol = chosen_coins[0] if chosen_coins else "BTC_USDT"
            if st.button("Test connect", key="auto_test_connect"):
                st.session_state["auto_conn_test"] = True
            if st.session_state.get("auto_conn_test"):
                # Clear before rendering — a lingering flag would re-issue the
                # signed probe on every widget interaction (Trade-tab lesson).
                st.session_state.pop("auto_conn_test", None)
                with st.spinner("talking to MEXC…"):
                    rep = fx.preflight(probe_symbol)
                rows = ""
                for _lab, ok in (
                        ("Credentials present", rep.get("credentials")),
                        ("Read account balance", rep.get("read_assets")),
                        ("Read open positions", rep.get("read_positions")),
                        ("Permission to place orders",
                         rep.get("order_permission")),
                        ("Rest a stop on MEXC's servers",
                         rep.get("can_rest_stop"))):
                    mark = "PASS" if ok else ("FAIL" if ok is False
                                              else "UNKNOWN")
                    cls = ("tm-up" if ok else "tm-dn" if ok is False
                           else "tm-nil")
                    rows += (f"<div class='row'><span>{_lab}</span>"
                             f"<span class='{cls}'>{mark}</span></div>")
                st.markdown(f"<div class='tm-p'>{rows}</div>",
                            unsafe_allow_html=True)
                if rep.get("ready"):
                    st.success("Connected — this key can read the account and "
                               "place orders.")
                elif rep.get("detail"):
                    st.error(rep["detail"])

        st.caption("This page refreshes itself: the top strip every 10 s, "
                   "positions every 20 s, the feed every 30 s. The runner "
                   "itself is unaffected — it wakes seconds after each candle "
                   "of the finest armed timeframe closes and enters at the "
                   "live price; open simulated positions are tick-checked "
                   "every 30 seconds. "
                   "Auto Trade checked = REAL orders; tick Dry run to "
                   "simulate. Emergency stop: uncheck + Save, or `touch "
                   "~/.tradingagents/auto_trade.KILL`. Brackets rest on "
                   "MEXC's servers when live.")


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
