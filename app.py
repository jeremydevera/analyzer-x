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
import hashlib as _hashlib
import html
import time
import json
import logging
import os
import re as _re
import sys
import traceback
from pathlib import Path
from typing import NamedTuple

import re
import subprocess
import streamlit as st
import streamlit.components.v1 as components

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
@import url('https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600;700&family=Geist+Mono:wght@400;500;600;700&display=swap');

/* Celebrately-style terminal: neutral near-white surfaces, near-black ink,
   one cobalt accent, hairline rules. One sans (Mulish) does both display and
   body work; IBM Plex Mono keeps columns of prices aligned digit for digit. */
:root {
  /* Ported from apex-django.dashboardpack.com, 2026-08-20 — read out of the
     running page's own custom properties (--background, --card, --muted,
     --border, --primary, --success, --destructive, --warning, --radius) after
     signing in with the demo credentials it publishes. APP-WIDE, not just the
     Auto Trade terminal: the first pass scoped everything to .st-key-term, so
     every other page looked untouched, which is exactly what the operator saw.
     Their stylesheet and assets are not copied; these are the same values. */
  /* ANALYST DESK — chosen 2026-08-20 from the ten-terminals gallery (design 09).
     Charts lead, tables follow, and every panel carries a caption that says what
     the number MEANS. The palette is navy/jade/coral; this is the LIGHT
     counterpart, which keeps the same semantics on paper so the Night toggle
     still works both ways. Layout metrics (12px/16px cells, uppercase headers,
     10px radius) are unchanged from the Apex pass — only the colours and the
     added chart band are new. */
  /* ZENITH (shadcn/ui) — read out of zenith-shadcn.dashboardpack.com's own
     running custom properties on 2026-08-20, light theme. Same oklch() values
     the template itself ships, so the match is exact rather than eyeballed.
     Their stylesheet and assets are not copied; these are the same numbers. */
  --bg:oklch(100% 0 0);                /* --background */
  --panel:oklch(100% 0 0);             /* --card */
  --panel-2:oklch(96.5% 0 0);          /* --secondary / --muted / --accent */
  --sidebar:oklch(98.5% 0 0);          /* --sidebar */
  --border:oklch(92.2% 0 0);           /* --border, and --input */
  --border-soft:oklch(94.5% 0 0);
  --border-strong:oklch(87% 0 0);
  --text:oklch(14.5% 0 0);             /* --foreground */
  --muted:oklch(44% 0 0);              /* --muted-foreground, darkened: the
                                          template's 55.6% fails 4.5:1 here */
  --faint:oklch(55.6% 0 0);            /* --muted-foreground as shipped */
  --accent:oklch(48.8% .243 264.376);  /* --chart-1, the interface blue */
  --accent-dim:oklch(42% .243 264.376);
  --accent-wash:oklch(96% .03 264.376);
  --buy:oklch(52% .17 162.48);         /* --chart-2 green, darkened for paper */
  --sell:oklch(57.7% .245 27.325);     /* --destructive */
  --hold:oklch(58% .188 70.08);        /* --chart-3 amber, darkened for paper */
  /* ui-ux-pro-max, dashboard/analytics pairing: Fira Sans for text, Fira Code
     for every figure. Chosen by the skill's typography search, not by taste —
     its stated mood is "dashboard, data, analytics, technical, precise". */
  --font-display:'Geist','Helvetica Neue',Helvetica,Arial,sans-serif;
  --font-body:'Geist','Helvetica Neue',Helvetica,Arial,sans-serif;
  --font-mono:'Geist Mono',ui-monospace,SFMono-Regular,monospace;
  --r:10px;                /* Apex --radius: .625rem */
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

/* ---- Navigation lives in the sidebar as of 2026-08-20. This rule USED to
   hide it, from when the screens were pills across the top; leaving it in place
   made the new rail render at 0x0 with display:none while still reporting
   aria-expanded="true", so the app looked navigation-less. The collapse control
   stays hidden: the rail IS the navigation and there is nothing behind it. ---- */
[data-testid="stSidebarCollapseButton"]{ display:none !important; }
.ta-brand{ display:flex; align-items:center; gap:10px; padding:0 0 var(--s); }
.ta-brand .ta-mark{ width:34px;height:34px;background:var(--accent); color:#fff;
  border-radius:8px; font-size:16px; }
.ta-brand-name{ font-family:var(--font-display); font-size:16px; font-weight:700;
  line-height:1.1; }
.ta-brand-sub{ font-family:var(--font-mono); font-size:9px; letter-spacing:.16em;
  text-transform:uppercase; color:var(--faint); margin-top:3px; }

/* The nav radio reads as tabs: same quiet pills as the report tabs above */
/* dead: the pills are gone. Kept harmless in case a screen still uses a
   horizontal radio, but the nav no longer renders one. */
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

/* =====================================================================
   APEX TREATMENT, APP-WIDE — apex-django.dashboardpack.com, 2026-08-20.
   Measured off the running page: card = --card on a --background page, 1px
   --border, radius .625rem, NO shadow, content flush inside; thead = --muted
   at ~30% alpha with NO uppercase and NO letter-spacing at 14px/500 and
   12px/16px padding; rows separated by a single hairline, no zebra, hover
   tint; status = rounded-full pill at 12px/600; primary = emerald.
   This block is LAST in the base sheet so it wins over the older rules
   without deleting them.
   ===================================================================== */

/* ---- every bordered container becomes an Apex card */
/* NOT inside .st-key-term: the terminal styles its own bands, and this rule
   was matching its nested wrappers — which drew a border between the positions
   table and the Close column beside it, so the buttons read as outside the
   box. Only containers Streamlit was told to draw a border on qualify. */
:not(.st-key-term) > div > [data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"] > div),
div[data-testid="stExpander"], .card, .panel{
  background:var(--panel); border:1px solid var(--border) !important;
  border-radius:var(--r) !important; box-shadow:none !important; }
.st-key-term [data-testid="stVerticalBlockBorderWrapper"]{
  background:transparent; border:0 !important; }
/* …except the two book boxes, which MUST keep their red/green frame: "is this
   real money or the simulator?" is the one thing this screen cannot blur. */
.st-key-term .st-key-pos_real, .st-key-term .st-key-pos_paper,
.st-key-pos_real, .st-key-pos_paper{
  border-width:1px !important; border-style:solid !important; }

/* ---- section titles: sentence case, 15px/600 ink, muted subtitle */
h1, h2, h3{ letter-spacing:-.01em; font-weight:600; }
h2{ font-size:20px; } h3{ font-size:15px; }
[data-testid="stCaptionContainer"] p{ color:var(--muted) !important;
  font-size:13px !important; letter-spacing:0 !important;
  text-transform:none !important; }

/* ---- TABLES: measured cell by cell off /customers/ on 2026-08-20.
   NOTE this CORRECTS the earlier pass. The dashboard's "Recent Orders" card
   uses sentence-case headers, so the first port removed uppercase everywhere —
   but the data table the operator actually asked for is the opposite: its
   headers ARE uppercase, 12px/600, letter-spacing .6px, in the muted ink, with
   NO bottom border on the cell (the row below carries the hairline).
     card    white, 1px --border, radius 10px, overflow hidden, padding 0
     thead   sticky, faint tint, th 12px/600 UPPERCASE ls .6px --muted-fg
     tr      44.5px tall, 1px --border under it, hover = accent at 30%
     td      padding 8px 12px, 14px, --foreground, numerics right-aligned
     avatar  32px circle on --muted, initials 12px/600
     pill    rounded-full, tinted, 12px/600 */
[data-testid="stTable"] table, .stMarkdown table{
  width:100%; border-collapse:separate; border-spacing:0;
  background:var(--panel); border:1px solid var(--border);
  border-radius:var(--r); overflow:hidden; font-size:14px; }
[data-testid="stTable"] thead th, .stMarkdown thead th{
  background:color-mix(in oklab, var(--panel-2) 55%, transparent);
  color:var(--muted) !important; font-size:12px !important;
  font-weight:600 !important; letter-spacing:.6px !important;
  text-transform:uppercase !important; white-space:nowrap;
  padding:10px 12px !important; text-align:left;
  border-bottom:1px solid var(--border) !important;
  position:sticky; top:0; z-index:2; }
[data-testid="stTable"] tbody td, .stMarkdown tbody td{
  padding:8px 12px !important; font-size:14px;
  color:var(--text); vertical-align:middle; height:44px;
  border-bottom:1px solid var(--border) !important; }
[data-testid="stTable"] tbody tr:last-child td,
.stMarkdown tbody tr:last-child td{ border-bottom:0 !important; }
/* Apex's own hover: the accent at 30%, not a grey wash. */
@media (hover:hover) and (pointer:fine){
  [data-testid="stTable"] tbody tr:hover td, .stMarkdown tbody tr:hover td{
    background:color-mix(in oklab, var(--accent-wash) 55%, transparent); } }
/* Numbers: tabular figures, right-aligned, as its ORDERS column is. */
[data-testid="stTable"] td, .stMarkdown td{ font-variant-numeric:tabular-nums; }
[data-testid="stTable"] td.num, .stMarkdown td.num,
[data-testid="stTable"] th.num, .stMarkdown th.num{ text-align:right !important; }
/* The two cell ornaments its rows are built from. */
.ap-av{ display:inline-flex; align-items:center; justify-content:center;
  width:32px; height:32px; border-radius:9999px; background:var(--panel-2);
  color:var(--text); font-size:12px; font-weight:600; margin-right:10px;
  flex:0 0 32px; }
.ap-cell{ display:flex; align-items:center; }
.ap-sub{ display:block; font-size:12px; color:var(--muted); margin-top:1px; }
.ap-pill{ display:inline-block; padding:2px 10px; border-radius:9999px;
  font-size:12px; font-weight:600; line-height:1.5;
  background:var(--panel-2); color:var(--muted); }
.ap-pill.ok{ background:color-mix(in oklab, var(--buy) 16%, transparent);
  color:var(--buy); }
.ap-pill.bad{ background:color-mix(in oklab, var(--sell) 16%, transparent);
  color:var(--sell); }
.ap-pill.warn{ background:color-mix(in oklab, var(--hold) 18%, transparent);
  color:var(--hold); }
/* Streamlit's own grid is a canvas it paints itself — give it the card frame */
[data-testid="stDataFrame"]{ border:1px solid var(--border) !important;
  border-radius:var(--r) !important; overflow:hidden; }

/* ---- buttons: Apex's emerald primary, quiet secondary */
.stButton>button{ border-radius:var(--r) !important; font-weight:500 !important;
  border:1px solid var(--border-strong) !important; box-shadow:none !important; }
.stButton>button[kind="primary"]{ background:var(--accent) !important;
  border-color:var(--accent) !important; color:#fff !important; }
.stButton>button:hover{ border-color:var(--accent) !important; }

/* ---- inputs pick up the same radius and hairline */
.stTextInput input, .stNumberInput input, .stTextArea textarea,
[data-baseweb="select"] > div{
  border-radius:var(--r) !important;
  border-color:var(--border) !important; box-shadow:none !important; }

/* ══ ui-ux-pro-max PRE-DELIVERY CHECKLIST, applied app-wide.
   Every item below is one line of that checklist, in its order. */
/* "cursor-pointer on all clickable elements" */
button, [role="button"], [role="radio"], [role="tab"], summary,
label:has(input[type="checkbox"]), label:has(input[type="radio"]),
[data-testid="stSidebar"] .stButton > button{ cursor:pointer; }
/* "focus states visible for keyboard nav" — never remove the ring, and make it
   a ring the OLED ground can actually show. */
:where(button,a,input,select,textarea,summary,[tabindex]):focus-visible{
  outline:2px solid var(--accent) !important; outline-offset:2px !important;
  border-radius:6px; }
/* "prefers-reduced-motion respected" — one global brake, so a component that
   forgets is still covered. */
@media (prefers-reduced-motion:reduce){
  *,*::before,*::after{ animation-duration:.001ms !important;
    animation-iteration-count:1 !important; transition-duration:.001ms !important;
    scroll-behavior:auto !important; } }
/* "hover states with smooth transitions (150-300ms)" */
button, .mv-cell, .mv-row, .stButton > button{ transition:background-color .18s ease,
  border-color .18s ease, color .18s ease, transform .18s ease; }
/* "responsive: 375px, 768px, 1024px, 1440px" — the dense grids collapse rather
   than forcing a horizontal scroll on the page body. */
@media (max-width:1024px){
  .mv-strip{ grid-template-columns:repeat(auto-fit,minmax(150px,1fr)) !important; }
  .mv-str > div{ grid-template-columns:1.6fr .7fr .9fr 1fr 1fr !important; }
  .mv-str > div > :last-child{ display:none !important; } }
@media (max-width:768px){
  .mv-hero .v{ font-size:34px !important; }
  .mv-row{ grid-template-columns:2fr 1fr 1fr !important; }
  .mv-row > :nth-child(n+4){ display:none !important; }
  .mv-str > div{ grid-template-columns:1.6fr 1fr 1fr !important; }
  .mv-str > div > :nth-child(n+4){ display:none !important; } }
@media (max-width:375px){
  .mv-strip{ grid-template-columns:1fr !important; }
  .mv-hero{ padding:18px 16px 0 !important; } }
/* Wide desks get the density the skill's dial asked for, not a stretched row. */
@media (min-width:1440px){ .mv{ --gap:18px; } }

/* ══ THE RAIL. Navigation is a sidebar now, not a row of pills. */
[data-testid="stSidebar"]{ background:var(--sidebar) !important;
  border-right:1px solid var(--border); }
[data-testid="stSidebar"] > div{ padding-top:14px; }
.nv-brand{ display:flex; gap:10px; align-items:center; padding:0 4px 16px; }
.nv-mark{ width:30px; height:30px; border-radius:8px; flex:0 0 30px;
  background:var(--accent); color:#04140a; display:grid; place-items:center;
  font-size:15px; font-weight:700; }
.nv-name{ font-size:14.5px; font-weight:600; letter-spacing:-.01em;
  color:var(--text); line-height:1.2; }
.nv-sub{ font-size:11px; color:var(--muted); letter-spacing:.02em; }
.nv-grp{ font-size:10px; letter-spacing:.16em; text-transform:uppercase;
  color:var(--faint); padding:14px 6px 5px; }
[data-testid="stSidebar"] .stButton > button{ justify-content:flex-start !important;
  text-align:left !important; border:0 !important; background:transparent !important;
  color:var(--muted) !important; font-weight:500 !important; font-size:13.5px !important;
  padding:7px 10px !important; border-radius:7px !important; min-height:0 !important; }
[data-testid="stSidebar"] .stButton > button:hover{
  background:var(--panel-2) !important; color:var(--text) !important; }
[data-testid="stSidebar"] .stButton > button[kind="primary"]{
  background:var(--accent-wash) !important; color:var(--accent) !important;
  font-weight:600 !important; }
.nv-foot{ border-top:1px solid var(--border); margin:16px 0 10px; }
/* the page title band is gone with the pills; give content the top back */
.ta-page-title{ font-size:24px !important; font-weight:600 !important;
  letter-spacing:-.02em !important; margin:0 0 2px !important; }

/* ---- the nav pills read like Apex's sidebar items */
.st-key-nav_page [role="radiogroup"] label{ border-radius:var(--r) !important; }
.st-key-nav_page [role="radiogroup"] label:has(input:checked){
  background:var(--accent-wash) !important; }
.st-key-nav_page [role="radiogroup"] label:has(input:checked) p{
  color:var(--accent) !important; font-weight:600 !important; }
</style>
"""

# Night mode: the same design, re-tokened. Injected AFTER the base CSS so the
# variable overrides win; a handful of Streamlit widget internals need
# explicit repaints because they don't read our variables.
DARK_CSS = """
<style>
:root {
  /* ANALYST DESK, the direction as designed: navy ground, one step up for the
     panel, jade and coral carrying the only verdicts on screen. */
  /* ui-ux-pro-max style "Dark Mode (OLED)" with its own palette values:
     background #020617, card #0E1223, border #334155, muted-fg #94A3B8,
     accent #22C55E, destructive #EF4444. The skill marks light mode
     "not-recommended" for this style — it is still supported here because the
     operator has a Night toggle, but dark is the designed state. */
  /* ZENITH dark, the template's own oklch values (2026-08-20). Neutral
     near-black with a lifted card — no blue cast, which is the single biggest
     visible difference from the palette this replaces. */
  --bg:oklch(7.5% 0 0);                /* --background */
  --panel:oklch(19% 0 0);              /* --card */
  --panel-2:oklch(23.5% 0 0);          /* --secondary / --muted / --accent */
  --sidebar:oklch(11% 0 0);            /* --sidebar */
  --border:oklch(28% 0 0);             /* --border, and --input */
  --border-soft:oklch(24% 0 0);        /* --sidebar-border is 26% */
  --border-strong:oklch(36% 0 0);
  --text:oklch(98.5% 0 0);             /* --foreground */
  --muted:oklch(72% 0 0);              /* --muted-foreground, LIFTED: the
                                          template ships 55.6%, which measures
                                          under 4.5:1 on the 19% card */
  --faint:oklch(60% 0 0);
  --accent:oklch(62% .21 264.376);     /* --chart-1 blue, lifted off 48.8% so
                                          it clears 4.5:1 as link/active text */
  --accent-dim:oklch(72% .18 264.376);
  --accent-wash:oklch(24% .06 264.376);
  --buy:oklch(69.6% .17 162.48);       /* --chart-2 */
  --sell:oklch(64.5% .246 16.439);     /* --chart-5 */
  --hold:oklch(76.9% .188 70.08);      /* --chart-3 */
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
PAGES = ("New Crypto", "Stocks", "Auto Trade", "Back Test", "Backtest 2",
         "LLM Models")


UI_PREFS = Path(os.path.expanduser("~/.tradingagents/ui_prefs.json"))


def _ui_prefs_load() -> dict:
    try:
        return json.loads(UI_PREFS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# Screens, grouped. A flat row of six pills said nothing about which of them
# spend money and which only look — the grouping does.
NAV_GROUPS = (
    ("Trading", ("Auto Trade",)),
    ("Research", ("Back Test", "Backtest 2")),
    ("Markets", ("New Crypto", "Stocks")),
    ("Setup", ("LLM Models",)),
)


def render_nav() -> str:
    """The screen rail. Left sidebar, grouped, one screen at a time.

    Rebuilt 2026-08-20 on the operator's instruction ("total remake ... i want
    clean"). It was six pills in a row across the top, which put navigation,
    the page title and the screen's own controls in one horizontal band and left
    nothing for the content. A vertical rail costs 210px once and gives the
    screen its full width back — and it can group by what a screen DOES.
    """
    with st.sidebar:
        st.markdown(
            '<div class="nv-brand"><div class="nv-mark">◈</div>'
            '<div><div class="nv-name">TradingAgents</div>'
            '<div class="nv-sub">Analyst desk</div></div></div>',
            unsafe_allow_html=True)
        page = st.session_state.get("nav_page") or "Auto Trade"
        for _title, _screens in NAV_GROUPS:
            st.markdown(f"<div class='nv-grp'>{_title}</div>",
                        unsafe_allow_html=True)
            for _sc in _screens:
                if st.button(_sc, key=f"nv_{_sc}", use_container_width=True,
                             type=("primary" if _sc == page else "secondary")):
                    st.session_state["nav_page"] = _sc
                    st.rerun()
        st.markdown("<div class='nv-foot'></div>", unsafe_allow_html=True)
        if "ui_night" not in st.session_state:
            st.session_state["ui_night"] = bool(_ui_prefs_load().get("night"))
        night = st.toggle("Night mode", key="ui_night")
    prefs = _ui_prefs_load()
    if bool(prefs.get("night")) != night:
        UI_PREFS.parent.mkdir(parents=True, exist_ok=True)
        UI_PREFS.write_text(json.dumps({**prefs, "night": night}),
                            encoding="utf-8")
    if night:
        st.markdown(DARK_CSS, unsafe_allow_html=True)
    return st.session_state.get("nav_page") or "Auto Trade"


import threading as _threading
import time as _time_mod

def main() -> None:
    st.set_page_config(page_title="TradingAgents", page_icon="◈", layout="wide",
                       initial_sidebar_state="expanded")
    st.markdown(CSS, unsafe_allow_html=True)

    page = render_nav()

    # The component stylesheet is scoped under `.st-key-term`, and that
    # container used to be created INSIDE the Auto Trade tab. Measured
    # 2026-08-20: Auto Trade loaded five stylesheets, every other screen loaded
    # two — the tokens and the fonts, and none of the 113 component rules. So
    # Back Test, Backtest 2, New Crypto, Stocks and LLM Models were unstyled
    # Streamlit widgets on a dark background, which is what "it still messy"
    # was pointing at. Creating the container HERE, around the dispatch, makes
    # every screen inherit the same sheet with no selector changes.
    term = st.container(key="term")
    with term:
        st.markdown(TERMINAL_CSS.replace("__POSGRID__", _TM_POS_GRID),
                    unsafe_allow_html=True)
        st.markdown(ANI_CSS, unsafe_allow_html=True)
        if st.session_state.get("ui_night"):
            st.markdown(TERMINAL_DARK_CSS, unsafe_allow_html=True)
        st.markdown(f'<div class="ta-page-title">{html.escape(page)}</div>',
                    unsafe_allow_html=True)
        if page == "New Crypto":
            render_crypto_tab()
        elif page == "Auto Trade":
            render_auto_trade_tab()
        elif page == "Back Test":
            render_backtest_tab()
        elif page == "Backtest 2":
            render_backtest2_tab()
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
def _strategy_label(key: str, label: str) -> str:
    """The tile's name plus the barriers READ FROM THE SPEC.

    The barriers used to be typed into the label by hand, and two of them had
    drifted from the config the runner trades: the APEX tile advertised
    "TP 4.0%" against a real 3.0% (it was changed on 2026-08-19 and the text
    was not), and the XAUT tile "TP 2.4%" against a real 2.0%. A label that
    repeats a number instead of deriving it is a label that will disagree with
    it eventually — so it is built here, from `STRATEGY_SPECS`, and cannot.
    """
    # `at` is imported inside the render functions, not at module scope, so it
    # must be imported here too — the same mistake made `_tradable_notional` a
    # silent no-op for an hour behind a bare `except Exception`.
    from tradingagents import auto_trader as at  # noqa: PLC0415
    spec = at.STRATEGY_SPECS.get(key) or {}
    tp, sl = spec.get("tp"), spec.get("sl")
    if tp is None or sl is None:
        return label
    name, _, tail = label.partition(" — ")
    barriers = f"TP {tp * 100:.2f}% / SL {sl * 100:.2f}%"
    return f"{name} · {barriers}" + (f" — {tail}" if tail else "")


AUTO_STRATEGIES = (
    # Only the strategies actually deployed appear here. The specs for
    # every other config still live in auto_trader.STRATEGY_SPECS, so a
    # tile can be restored in one line; an unticked tile on the page is
    # just clutter the operator has to read past.
    ("trend50_30m_pi", "Trend 50 (30m) — PI",
     "Row #3M3CRXP8 from the 28,600-combination 15m/30m year sweep "
     "(2026-08-19). +$140.74 over 360 days at $5 base, 47.6% win across 918 "
     "trades, with MEXC's per-book cost, 4.60% liquidation and real funding "
     "settlements all charged. NOT a survivor: 9/13 months green is 69.2%, a "
     "third of a month under the 70% bar, and the worst dip is $69.07 against "
     "an $80.47 wallet — at $5 base that leaves about $11 at the low point. "
     "Deployed on the operator's instruction; $2.91 base would bring the dip "
     "to $40.23. Replaced mom15_4h_w on PI, because one coin runs one "
     "timeframe.",
     ("PI_USDT",)),
    ("mom15_4h_w", "Momentum 15 (4h) — PI",
     "Winner of a 630-combination grid on PI's full 18-month history "
     "(2026-08-13): #1 of 105 configs. +$1,283 martingale / +$293 flat at $5 "
     "base — vs +$884 / +$168 for the 4.5% version it replaces. 19/19 months "
     "green, profitable in BOTH halves at BOTH sizings (+$768 / +$462 "
     "martingale), 433 trades instead of 666 so less fee drag. Same signal "
     "and timeframe as before — only the barriers are wider.",
     ("PI_USDT",)),
    ("fade15_1h_pv2", "Fade 15 (1h) — PROVE · Best 8.67 for August",
     "Row #8ZFUXG8F, the most profitable row of the 130,294-combination August "
     "sweep (2026-08-01 to 08-19): +$226.82 at a 12.50% win rate over 48 "
     "trades, threshold 0.20, SL 0.30% / TP 8.00%. The operator's label; 8.67 "
     "is their figure from the artifact's BALANCED column. "
     "MEASURED OVER 380 DAYS (9,095 hourly bars, fees + slippage + funding + "
     "4.50% liquidation charged): martingale +$104.07 over 1,562 trades — 91 "
     "wins against 1,471 losses, a 5.83% win rate — with a worst losing run of "
     "-$292.13 across 87 CONSECUTIVE losses and a $775.81 worst dip, which is "
     "four times the $192 wallet. Flat it is +$37.54 with a $126.45 dip. "
     "Cost is 2% of target and the stop is reachable, so the gate passes; the "
     "drawdown is the reason to think twice. SHIPPED WITH NO BOOK TICKED: "
     "PROVE already runs mom6_1h_pv on the same 1-hour bar, and one coin holds "
     "one position per book, so arming both would have them racing for the "
     "same slot.",
     ("PROVE_USDT",)),
    ("mom6_1h_pv", "Momentum 6 (1h) — PROVE",
     "Replaced trend50 (4h) on 2026-08-17. Winner of a 3,432-combination "
     "search over PROVE's own 1-hour year, with MEXC's 4.50% liquidation "
     "modelled — an earlier pass without it crowned an 8% stop the venue "
     "would never have let fire. Flat-staked this is the ONLY signal that "
     "survives on PROVE at 1h: +$171.77 over 375 days, 38.8% win across 765 "
     "trades, both halves positive (+$98 / +$70), 10/13 months green, worst "
     "trade -$2.10. trend50 on the same terms: +$89.57 at 29.5%. The cost is "
     "depth — worst dip $57 against trend50's $28 at a $5 base.",
     ("PROVE_USDT",)),
    ("sweep30_1h_w", "Liquidity sweep 30 (1h) — APEX",
     "The strongest evidence in the 55,062-combination all-market sweep "
     "(2026-08-14): one of only TWO configs that survived FLAT-staked over a "
     "real year. APEX_USDT flat +$55.72 at $5 base, 10/12 months green, "
     "profitable in BOTH halves (+$17 / +$36), 302 trades over 320 days. "
     "Martingale +$141.16 — but note the ladder makes it LESS consistent "
     "(7/12 green), so the flat figure is the honest one. Cost 6% of target.",
     ("APEX_USDT",)),
    ("fvg_1h_w", "ICT fair value gap (1h) — ALICE",
     "Most consistent martingale survivor in the same sweep: +$443 at $5 "
     "base, 13/15 months green over 416 days, both halves strongly positive. "
     "Its FLAT version is also clearly profitable (+$80.20, the highest flat "
     "figure of any candidate), so the edge is in the signal rather than the "
     "ladder — though its flat months (8/15) miss the 70% survivor bar. "
     "570 trades. Cost 3% of target.",
     ("ALICE_USDT",)),
    ("mom6_1h_gx", "Momentum 6 (1h) — XAUT gold",
     "The ONLY 1-hour configuration in the 55,062-combination all-market "
     "sweep that survived at BOTH sizings on a real year. Flat +$36.96 at $5 "
     "base (11/15 months green, both halves positive: +$14.71 / +$23.04) AND "
     "martingale +$148.01 (14/15 green). 282 trades over 416 days, 31.6% win "
     "rate. Gold's 0.01% taker fee makes the round-trip cost just 1% of the "
     "target — the cheapest contract on the venue. Same barriers as the "
     "mom15 version it replaces; only the signal differs.",
     ("XAUT_USDT",)),
    # mom15_1h_g (GOLD) was REMOVED from this list on 2026-08-19: XAUT now runs
    # mom6 at SL 1.50 / TP 2.00 (row #CZ7THVJW) and nothing else. Its spec stays
    # in auto_trader.STRATEGY_SPECS on purpose — a paper SHORT opened under it
    # is still resting, and the runner needs the spec to exit that position.
    # Restore the tile in one line if it is ever wanted back.
)

AUTO_TRADE_SETTINGS = Path(os.path.expanduser("~/.tradingagents/auto_trade.json"))


_LOG_TS_RE = _re.compile(
    r"^(?P<y>\d{4})-(?P<mo>\d{2})-(?P<d>\d{2}) "
    r"(?P<h>\d{2}):(?P<mi>\d{2}):(?P<s>\d{2})(?:,\d+)?")


def _fmt_log_line(line: str) -> str:
    """Rewrite a runner-log line's timestamp into the operator's clock.

    Python's logging writes "2026-08-20 01:20:50,936" — a 24-hour stamp with
    milliseconds and a redundant year, on a screen where every line is from
    today. Asked for on 2026-08-20: "make the time in am or pm i dont want this
    format". Becomes "Aug 20 1:20:50AM". Done at RENDER time, not by changing
    the log format, so the lines already on disk read the same way as the ones
    written next.

    A line that does not start with a stamp is handed back untouched — a
    traceback continuation must not be mangled into something that looks like
    an event.
    """
    m = _LOG_TS_RE.match(line)
    if not m:
        return line
    try:
        d = _dt.datetime(int(m["y"]), int(m["mo"]), int(m["d"]),
                         int(m["h"]), int(m["mi"]), int(m["s"]))
    except ValueError:
        return line
    hour = d.hour % 12 or 12
    return (f"{d:%b} {d.day} {hour}:{d:%M}:{d:%S}{d:%p}"
            f"{line[m.end():]}")


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


def _deploy_diff(old: dict, new: dict) -> list[dict]:
    """What changed about what is LIVE, one entry per strategy/coin.

    Config files overwrite. Without this the answer to "what was running on
    APEX on 12 August, at what barriers" is gone the moment it is saved.
    """
    from tradingagents import auto_trader as at

    out = []
    keys = set(list((old.get("strategy_books") or {}))
               + list((new.get("strategy_books") or {})))
    for k in sorted(keys):
        ob = list((old.get("strategy_books") or {}).get(k) or [])
        nb = list((new.get("strategy_books") or {}).get(k) or [])
        oc = list((old.get("strategy_coins") or {}).get(k) or [])
        nc = list((new.get("strategy_coins") or {}).get(k) or [])
        om = (old.get("strategy_margins") or {}).get(k)
        nm = (new.get("strategy_margins") or {}).get(k)
        if ob == nb and oc == nc and om == nm:
            continue
        spec = at.STRATEGY_SPECS.get(k) or {}
        action = ("disarmed" if nb == [] and ob else
                  "deployed" if nb and not ob else "changed")
        for coin in (nc or oc or ["—"]):
            out.append({
                "strategy_key": k, "symbol": coin, "action": action,
                "timeframe": _BT_TF_NAME.get(spec.get("interval")),
                "signal": _tm_sig(k),
                "threshold": round(float(spec.get("threshold") or 0) * 100, 3),
                "tp": round(float(spec.get("tp", 0)) * 100, 3),
                "sl": round(float(spec.get("sl", 0)) * 100, 3),
                "sizing": at.sizing_for(new),
                "books": ",".join(nb), "base_margin": nm,
                "prev_json": json.dumps({"books": ob, "coins": oc,
                                         "base_margin": om}),
            })
    return out


def _auto_trade_save(payload: dict) -> None:
    prev = _auto_trade_load()
    AUTO_TRADE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    AUTO_TRADE_SETTINGS.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    # Record what changed BEFORE this write is forgotten. Best-effort: the
    # archive being down must never stop a save the operator asked for.
    try:
        from tradingagents.dataflows import market_db as _mdb

        changes = _deploy_diff(prev, payload)
        if changes and _mdb.available():
            _mdb.ensure_schema()
            for c in changes:
                _mdb.record_deployment(c)
    except Exception:
        pass


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


# Interval -> the report module's timeframe label. A strategy running on 4-hour
# candles gets a 4h page; anything else is shown beside 1h and 4h so the
# operator can see whether their bar is the one that works.
_BT_TF_NAME = {"Min15": "15m", "Min30": "30m", "Min60": "1h",
               "Hour4": "4h", "Day1": "1d"}
# Generated pages live under ./static so Streamlit serves them at
# /app/static/... and the link can open in a real second tab. Keep the last
# few; a year of clicks would otherwise fill the disk with 500KB pages.
BT_REPORT_DIR = Path(__file__).parent / "static" / "bt"
BT_REPORT_KEEP = 20


def _bt_report_build(key: str, label: str, coins: list[str],
                     base_margin: float, days: int) -> tuple[str, str] | None:
    """Run the full grid for these coins and write the standalone page.

    Returns (url, filename), or None if nothing could be tested. Candles are
    fetched fresh on every click: the operator re-runs this over time, so a
    cached year would silently answer last week's question.
    """
    from tradingagents import auto_trader as at
    from tradingagents import backtest_report as br

    spec = at.STRATEGY_SPECS.get(key) or {}
    own = _BT_TF_NAME.get(spec.get("interval"), "1h")
    tfs = [own] + [t for t in ("1h", "4h") if t != own]
    sig = _tm_sig(key)
    sizing = at.sizing_for(_auto_trade_load())
    dep = [{"coin": c.replace("_USDT", ""), "tf": own, "signal": sig,
            "th": round(float(spec.get("threshold") or 0) * 100, 3),
            "sl": round(float(spec.get("sl", 0)) * 100, 3),
            "tp": round(float(spec.get("tp", 0)) * 100, 3),
            "sizing": sizing} for c in coins]
    # A rerun THROWS AWAY an in-flight build: Streamlit restarts the script on
    # any widget interaction, and a 22-signal grid takes ~5 minutes. So the
    # result is cached on disk under a signature of everything that could
    # change it, and a repeat click is instant.
    sig = "-".join([key, ",".join(sorted(coins)), ",".join(tfs), sizing,
                    f"{base_margin:g}", str(days),
                    f"{spec.get('sl')}/{spec.get('tp')}/"
                    f"{spec.get('threshold')}", str(len(br.SIGNALS))])
    stamp = _dt.datetime.now().strftime("%Y%m%d")
    name = f"{key}-{_hashlib.blake2s(sig.encode(), digest_size=4).hexdigest()}"
    fresh = BT_REPORT_DIR / f"{name}-{stamp}.html"
    if fresh.exists() and fresh.stat().st_size > 10_000:
        return f"app/static/bt/{fresh.name}", fresh.name

    bar = st.progress(0.0, text="fetching candles…")
    note = st.empty()
    note.caption(f"Testing {len(br.SIGNALS)} signals x 110 barrier pairs x 2 "
                 f"sizings on {', '.join(tfs)} — about 5 minutes. Leave this "
                 f"tab alone; clicking anything restarts it.")
    try:
        payload = br.run_grid(
            coins, tfs, base_margin=base_margin, days=days, deployed=dep,
            progress=lambda m, f: bar.progress(min(1.0, f), text=m))
    finally:
        bar.empty()
        note.empty()
    if not payload["rows"]:
        return None
    BT_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{name}-{stamp}.html"
    # The strategy label often already names its coin; appending it again read
    # as "PROVE · PROVE".
    _shown = [c.replace("_USDT", "") for c in dict.fromkeys(coins)]
    _extra = [c for c in _shown if c not in label]
    br.write_report(
        str(BT_REPORT_DIR / name), payload,
        title=label + (" · " + ", ".join(_extra) if _extra else ""),
        note=(f"<b>{label}</b> is deployed on "
              f"{', '.join(_shown)} at "
              f"SL {float(spec.get('sl', 0)) * 100:.2f}% / "
              f"TP {float(spec.get('tp', 0)) * 100:.2f}%, {sizing}. That row "
              f"is marked <b>DEPLOYED</b> and always visible, whatever the "
              f"Show box says &mdash; every other row is an alternative "
              f"measured on the same candles."))
    # Prune: keep the newest few pages, drop the rest.
    old = sorted(BT_REPORT_DIR.glob("*.html"),
                 key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in old[BT_REPORT_KEEP:]:
        try:
            stale.unlink()
        except OSError:
            pass
    return f"app/static/bt/{name}", name


def _render_strategy_backtest(key: str, label: str, coins: list[str],
                              base_margin: float, days: int = 365) -> None:
    """Replay the strategy over MEXC history and hand back the full grid page.

    The page opens in its own tab and carries everything — every signal on the
    same candles, both sizings, per-row trade logs — so nothing is drawn here.
    The in-page table below is the FALLBACK, reached only when the page could
    not be built; a click that produces nothing is worse than a plain table.
    """
    import pandas as pd

    from tradingagents import auto_trader as at
    if not coins:
        st.error("Select at least one contract to backtest.")
        return
    try:
        _rep = _bt_report_build(key, label, coins, base_margin, days)
    except Exception as exc:
        _rep = None
        st.warning(f"Full-grid page could not be built ({exc}) — falling back "
                   f"to the in-page table.")
    if _rep:
        st.session_state.setdefault("bt_pages", {})[key] = _rep
    _rep = _rep or st.session_state.get("bt_pages", {}).get(key)
    if _rep:
        _url, _name = _rep
        st.markdown(
            f"<a class='bt-open' href='{_url}' target='_blank' "
            f"rel='noopener'>OPEN FULL GRID &#8599;</a>"
            f"<span class='bt-open-note'>opened in a new tab &middot; every "
            f"signal on the same candles &middot; click any row for its "
            f"trades &middot; {html.escape(_name)}</span>",
            unsafe_allow_html=True)
        components.html(
            "<script>window.open("
            + json.dumps("/" + _url)
            + ",'_blank','noopener');</script>", height=0)
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
    _fund: dict[str, list] = {}
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
            # Holding cost, charged per settlement (rule 9): a backtest that
            # only pays entry and exit flatters every trade held overnight.
            try:
                _fund[coin] = _fx0.funding_history(coin)
            except Exception:
                _fund[coin] = []
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
                            liq_move_pct=_liq.get(coin),
                            funding=_fund.get(coin))
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
# Auto Trade is a TERMINAL — monospace, tabular, dense. It used to paint a
# near-black ground in BOTH themes and say so in this comment, on the grounds
# that a band owning its palette cannot have an invisible-text bug (two of
# those happened on 2026-08-15).
#
# The operator overruled that on 2026-08-19: "even when i light mode, the
# sections are black". So the palette is now re-tokened per theme instead of
# fixed, and the invisible-text risk is answered the right way round — every
# colour on this screen comes from a token that BOTH blocks define, so there is
# no rule that paints ink without also having painted its ground. The only
# thing the dark block does is redefine the seven tokens below.
# ---------------------------------------------------------------------------
TERMINAL_CSS = """
<style>
.st-key-term{
  /* LIGHT is the default token set; TERMINAL_DARK_CSS below redefines exactly
     these names for night mode and touches nothing else.
     --t-amber keeps its NAME because two dozen rules and several render
     functions reference it; it holds the accent, blue in both themes. */
  /* Palette measured off apex-django.dashboardpack.com (2026-08-20) with its
     own published demo login, read out of the page's CSS custom properties —
     --background, --card, --muted, --border, --primary, --success,
     --destructive, --radius. Their emerald primary replaces the blue accent;
     --t-amber keeps its NAME because two dozen rules reference it. */
  /* transparent, NOT a colour: the app paints the page and the card
     sits on it. Two near-identical darks (this band's and the app's)
     showed as a seam around every card in night mode. */
  --t-ground:transparent; --t-panel:oklch(100% 0 0);
  --t-panel2:oklch(96.5% 0 0);
  --t-rule:oklch(92.2% 0 0); --t-rule2:oklch(87% 0 0);
  --t-ink:oklch(14.5% 0 0); --t-dim:oklch(44% 0 0);
  --t-faint:oklch(55.6% 0 0);
  --t-amber:oklch(48.8% .243 264.376); --t-up:oklch(52% .17 162.48);
  --t-dn:oklch(57.7% .245 27.325);
  /* zenith: --radius .625rem for controls, and a measured 14px on the card */
  --t-r:14px; --t-rc:10px;
  background:var(--t-ground); color:var(--t-ink);
  font-family:var(--font-mono); font-variant-numeric:tabular-nums;
  padding:2px; border:0;
}
/* Bands are separated by a hairline, not wrapped in a filled card. The card
   was the "sections are enclosed on large box" the operator asked to remove on
   2026-08-19: nested panels inside a panel inside the page reads as three
   frames around one table. */
.st-key-term [class*="st-key-tmsec_"]{
  background:transparent; border:0; border-top:1px solid var(--t-rule);
  border-radius:0; padding:14px 0 10px; margin-bottom:6px;
}
/* The first band needs no divider above it. */
.st-key-term [class*="st-key-tmsec_"]:first-of-type{ border-top:0; }
/* Inner tiles carry the only fill on the screen, so they read as objects
   against the page rather than as panels within a panel. */
.st-key-term [class*="st-key-tmsec_"] .tm-p,
.st-key-term [class*="st-key-tmsec_"] .tm-feed{
  background:var(--t-panel2); border:1px solid var(--t-rule); }
/* The card supplies the top spacing; a header's own margin would double it. */
.st-key-term [class*="st-key-tmsec_"] .tm-h:first-child,
.st-key-term [class*="st-key-tmsec_"] [data-testid="stElementContainer"]:first-child .tm-h{
  margin-top:0; }
.st-key-term p, .st-key-term span, .st-key-term div, .st-key-term label{
  font-family:var(--font-mono); }
/* …but NEVER the Material icon spans. Their glyphs are ligatures, so a mono
   font renders the ligature's source text: the expander chevrons came out as
   the literal word "arrow_right" printed over the contract column. */
.st-key-term [data-testid="stIconMaterial"],
.st-key-term .material-symbols-rounded, .st-key-term [class*="material"]{
  font-family:"Material Symbols Rounded" !important; }

/* st.metric labels render at 0.8 opacity AND inherit config.toml's textColor,
   which CSS here must override or they measure 1.11:1 on the dark ground. */
/* Green form-submit buttons ("Add model", "Test ALL models") paint white on
   #22C55E — 2.28:1. Near-black on the same green measures 8.46. Scoped to the
   FORM-SUBMIT testid on purpose: the sidebar's active nav pill is also a
   primary button, and it carries green text on a dark wash (7.29:1), which a
   blanket primary rule turns into 1.15:1. */
[data-testid="stBaseButton-primaryFormSubmit"],
[data-testid="stBaseButton-primaryFormSubmit"] *{
  color:#04140a !important; }
[data-testid="stBaseButton-primaryFormSubmit"]{ font-weight:700 !important; }

/* Hoisting the terminal sheet app-wide swapped these screens onto Fira Code,
   which is wider per character than the face their column ratios were tuned
   for. The labels then broke mid-word — "Filter/s", "SWAR/M", "ANA/LYZ/E",
   "+833./50%". A control label is a single token: it never wraps, and if it
   cannot fit it shrinks. Overflow is checked in the layout probe, not assumed. */
button p, button span, button div,
[data-testid="stPopoverButton"] p, [data-testid="stPopoverButton"] span{
  white-space:nowrap !important; }
button{ min-width:0 !important; }
/* Checkbox and radio labels are single tokens too — "Loop" was rendering as
   "Loo" / "p" in the narrow run panel. */
[data-testid="stCheckbox"] label p, [data-testid="stRadio"] label p,
[data-testid="stWidgetLabel"] p{ white-space:nowrap !important; }
/* Numbers in a data cell are one token too — a percent that breaks across two
   lines reads as two different figures. */
.st-key-term [data-testid="stMarkdownContainer"] .nowrap,
.st-key-term .tm-num, .st-key-term .mv-num{ white-space:nowrap !important; }

/* An unstyled markdown link keeps Streamlit's default rgb(0,84,163), which is
   2.69:1 on this ground — "OPEN THE REPORT" on Back Test was the one that
   showed it. The accent measures 8.10:1, and the underline carries the link
   identity so it is never colour alone. */
[data-testid="stMarkdownContainer"] a:not(.bt-open):not(.ta-link){
  color:var(--accent-dim) !important; text-decoration:underline;
  text-underline-offset:2px; }
[data-testid="stMarkdownContainer"] a:not(.bt-open):not(.ta-link):hover{
  color:var(--accent) !important; }

/* st.popover's trigger keeps Streamlit's own light chrome: measured
   rgb(255,255,255) — a white box on the OLED ground, carrying light text, so
   New Crypto's "Filters" control read 1.28:1 and looked like a rendering
   fault rather than a button. */
[data-testid="stPopoverButton"]{
  background:var(--panel-2) !important; color:var(--text) !important;
  border:1px solid var(--border) !important; }
[data-testid="stPopoverButton"] *{ color:var(--text) !important; }
[data-testid="stPopoverButton"]:hover{ border-color:var(--accent) !important; }

/* An expander header outside the terminal container kept config.toml's ink,
   so "Filters" on New Crypto measured 1.28:1 — a control you cannot see is a
   control you cannot find. The chevron ligature is decorative but sits in the
   same run of text, so it takes --muted rather than being left at 3.93. */
[data-testid="stExpander"] summary{ color:var(--text) !important; }
[data-testid="stExpander"] summary p,
[data-testid="stExpander"] summary span:not([data-testid="stIconMaterial"]){
  color:var(--text) !important; }
[data-testid="stExpander"] summary [data-testid="stIconMaterial"],
[data-testid="stExpander"] summary svg{ color:var(--muted) !important;
  fill:var(--muted) !important; }

/* A disabled button inherits config.toml's ink at 0.4 alpha — measured 1.11:1
   on this ground, i.e. invisible. The operator asked "where is the DOWNLOAD in
   backtest 2?" and the answer was that it was rendering, unreadably. Disabled
   still has to look like a control. */
button:disabled, button[disabled]{
  color:var(--muted) !important; opacity:1 !important;
  border-color:var(--border-soft) !important;
  background:var(--panel-2) !important; cursor:not-allowed !important; }
button:disabled *, button[disabled] *{ color:var(--muted) !important; }

[data-testid="stMetricLabel"]{ opacity:1 !important; }
[data-testid="stMetricLabel"] p{ font-size:11px; letter-spacing:.12em;
  text-transform:uppercase; color:var(--muted) !important; }
a.bt-open{ display:inline-block; background:var(--accent); color:#04140a;
  font-weight:700; font-size:12px; letter-spacing:.14em; text-transform:uppercase;
  text-decoration:none; padding:10px 18px; border:1px solid var(--accent);
  margin:8px 12px 10px 0; }
a.bt-open:hover{ background:var(--accent-dim); border-color:var(--accent-dim); }
a.bt-open:focus-visible{ outline:2px solid var(--text); outline-offset:2px; }
.bt-open-note{ color:var(--faint); font-size:12px; }

/* ---- the full-grid page link: this is a door out of the app, so it reads
   like a button rather than a line of text ---- */
.st-key-term a.bt-open{
  display:inline-block; background:var(--t-ink); color:#0a0a0a;
  font-weight:700; font-size:11.5px; letter-spacing:.14em;
  text-transform:uppercase; text-decoration:none; padding:9px 16px;
  border:1px solid var(--t-ink); border-radius:var(--t-rc);
  margin:6px 10px 8px 0;
  transition:transform 160ms cubic-bezier(0.23,1,0.32,1),
             background 150ms ease, border-color 150ms ease; }
@media (hover:hover) and (pointer:fine){
  .st-key-term a.bt-open:hover{ background:#ffffff; border-color:#ffffff; } }
.st-key-term a.bt-open:active{ transform:scale(0.97); }
.st-key-term a.bt-open:focus-visible{ outline:2px solid var(--t-ink);
  outline-offset:2px; }
.st-key-term .bt-open-note{ color:var(--t-faint); font-size:11px; }

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
/* Apex's dashboard stat card, measured off the running page 2026-08-20:
   `rounded-lg border border-border bg-card p-4 flex flex-col gap-3`
   = white, 1px --border, radius 10px, padding 16px, gap 12px, NO shadow;
   the icon is a 36x36 chip at radius 8px carrying its tone at 10% alpha
   behind the full colour (theirs: rgba(22,163,74,.1) on rgb(22,163,74));
   the delta line is 12px in --success. */
.tm-rib{ display:flex; gap:12px; }
.tm-rib > div{ flex:1; padding:16px; background:var(--t-panel);
  border:1px solid var(--t-rule); border-radius:var(--t-r);
  display:flex; flex-direction:column; gap:12px;
  transition:border-color 150ms ease; }
@media (hover:hover) and (pointer:fine){
  .tm-rib > div:hover{ border-color:var(--t-rule2); } }
/* label row: name on the left, icon chip hard right */
.tm-rib .hd{ display:flex; align-items:flex-start; justify-content:space-between;
  gap:8px; }
.tm-rib .l{ font-size:14px; font-weight:500; letter-spacing:0;
  text-transform:none; color:var(--t-ink); white-space:nowrap; }
.tm-rib .ic{ width:36px; height:36px; border-radius:8px; flex:0 0 36px;
  display:inline-flex; align-items:center; justify-content:center;
  font-size:15px; font-weight:700; line-height:1; }
.tm-rib .n{ font-size:30px; font-weight:700; letter-spacing:-.02em;
  line-height:1.05; }
.tm-rib .s{ font-size:12px; color:var(--t-dim); margin:0; }
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
.tm-badge{ display:inline-block; padding:3px 11px; margin:0 0 8px;
  font-size:10px; letter-spacing:.14em; font-weight:700;
  border-radius:9999px; border:1px solid transparent; }
.st-key-pos_real, .st-key-pos_paper{ border-radius:var(--t-r) !important;
  padding:12px 14px 6px !important; margin-bottom:14px !important; }
.st-key-pos_real{ border:1px solid rgba(229,72,77,.55) !important;
  border-left:4px solid var(--t-dn) !important;
  background:rgba(229,72,77,.04) !important; }
.st-key-pos_paper{ border:1px solid rgba(12,206,107,.45) !important;
  border-left:4px solid var(--t-up) !important;
  background:rgba(12,206,107,.04) !important; }
.st-key-pos_real .tm-badge{ background:rgba(229,72,77,.15);
  color:#ff8589; border-color:rgba(229,72,77,.5); }
.st-key-pos_paper .tm-badge{ background:rgba(12,206,107,.13);
  color:#3fe08f; border-color:rgba(12,206,107,.45); }

/* The close button sits in its own column beside the row. */
.st-key-term [data-testid="stColumn"] .stButton button{ padding:2px 8px !important;
  font-size:10px !important; letter-spacing:.06em; width:100%; }

/* Trade-history tabs, in the band's own palette. */
.st-key-term [data-testid="stTabs"] button{ font-family:var(--font-mono) !important;
  font-size:11px !important; letter-spacing:.12em; text-transform:uppercase;
  color:var(--t-dim) !important; transition:color 150ms ease !important; }
.st-key-term [data-testid="stTabs"] button[aria-selected="true"]{
  color:var(--t-amber) !important; }
.st-key-term [data-testid="stTabs"] [data-baseweb="tab-highlight"]{
  background:var(--t-amber) !important; }
.st-key-term [data-testid="stTabs"] [data-baseweb="tab-border"]{
  background:var(--t-rule2) !important; }

/* ---- ledger panels: ruled rows, totals set off by a heavy rule ---- */
.tm-p{ border:1px solid var(--t-rule); background:var(--t-panel);
  border-radius:var(--t-r); padding:12px 14px; font-size:12px; line-height:1.85; }
.tm-p .row{ display:flex; justify-content:space-between; gap:8px; }
.tm-p .sub{ border-top:1px solid var(--t-rule2); margin-top:5px; padding-top:5px; }
.tm-p .tot{ border-top:2px solid var(--t-rule2); margin-top:4px; padding-top:5px;
  font-weight:700; }
.tm-big{ font-size:34px; font-weight:700; line-height:1.1; letter-spacing:-.03em; }
.tm-feed{ max-height:230px; overflow-y:auto; border:1px solid var(--t-rule);
  background:var(--t-panel); border-radius:var(--t-r); padding:8px 11px; font-size:11.5px; line-height:1.65;
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
/* Radio dots come from the app theme's orange primary; inside this band the
   accent is blue, and a second unexplained accent color reads as a state. */
.st-key-term label[data-baseweb="radio"] > div:first-child{
  border-color:var(--t-rule2) !important; background:var(--t-panel2) !important; }
.st-key-term label[data-baseweb="radio"]:has(input:checked) > div:first-child{
  background:var(--t-amber) !important; border-color:var(--t-amber) !important; }
.st-key-term input, .st-key-term textarea{ background:var(--t-panel2) !important;
  color:var(--t-ink) !important; border-color:var(--t-rule2) !important;
  border-radius:var(--t-rc) !important; }
.st-key-term [data-baseweb="select"] > div{ background:var(--t-panel2) !important;
  border-color:var(--t-rule2) !important; border-radius:var(--t-rc) !important;
  color:var(--t-ink) !important; }
.st-key-term [data-baseweb="tag"]{ background:var(--t-panel2) !important;
  color:var(--t-amber) !important; border-radius:var(--t-rc) !important; }
/* A multiselect's search box is a 16px-wide input that BaseWeb parks UNDER
   the first tag and keeps transparent. Giving every input in the band an
   opaque panel background painted it over the tag's first glyph, so
   PROVE_USDT rendered as "ROVE_USDT". Measured: input at x=136 w=16, the
   tag's text starts at x=144. */
.st-key-term [data-baseweb="select"] input{ background:transparent !important; }
.st-key-term .stButton button{ background:var(--t-panel2) !important;
  color:var(--t-ink) !important; border:1px solid var(--t-rule2) !important;
  border-radius:var(--t-rc) !important; font-family:var(--font-mono) !important;
  font-size:11.5px !important; letter-spacing:.1em; text-transform:uppercase;
  transition:transform 160ms cubic-bezier(0.23,1,0.32,1),
             border-color 150ms ease, background 150ms ease !important;
  box-shadow:none !important; }
@media (hover:hover) and (pointer:fine){
  .st-key-term .stButton button:hover{ border-color:#3f3f46 !important;
    background:#1c1c1f !important; } }
.st-key-term .stButton button:active{ transform:scale(0.97); }
.st-key-term .stButton button:focus-visible{
  outline:2px solid var(--t-amber) !important; outline-offset:2px; }
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
/* =====================================================================
   APEX TREATMENT — ported from apex-django.dashboardpack.com, 2026-08-20.
   Measured, not guessed: card = white, 1px oklch(92.2% .005 230) border,
   radius 10px, NO shadow, overflow hidden; the table sits flush inside it;
   thead is the muted token at ~30% alpha with NO uppercase and NO letter-
   spacing, 14px/500, padding 12px 16px; rows are 61px tall with hairline
   separators and no zebra; status is a soft rounded-full pill at 12px/600.
   Their stylesheet and assets are NOT copied — this is the same treatment
   rebuilt on the tokens above.
   ADAPTED, deliberately: their rows are 61px for five columns of prose. This
   grid carries fourteen columns of numbers, so rows are 36px and cells 12px —
   the same rhythm at this density. Numbers keep the monospace face because
   tabular alignment is the one thing Apex's sans cannot do.
   ===================================================================== */
.st-key-term{ --t-sans:-apple-system,system-ui,"Segoe UI",Roboto,
  "Helvetica Neue",Arial,sans-serif; }
/* Text wears the sans; anything numeric keeps the mono. */
.st-key-term .tm-h, .st-key-term .tm-h *,
.st-key-term .tm-rib .l, .st-key-term .tm-rib .s,
.st-key-term .tm-pt-h, .st-key-term .tm-pt-h *,
.st-key-term [data-testid="stCaptionContainer"] p,
.st-key-term .tm-badge, .st-key-term .tm-pill{
  font-family:var(--t-sans) !important; }

/* ---- SECTION = card. White, hairline, 10px, no shadow. */
.st-key-term [class*="st-key-tmsec_"]{
  background:var(--t-panel); border:1px solid var(--t-rule);
  border-radius:var(--t-r); box-shadow:none;
  padding:16px 18px 14px; margin-bottom:16px; }
.st-key-term [class*="st-key-tmsec_"]:first-of-type{ border-top:1px solid var(--t-rule); }
/* Inner tiles step DOWN onto the muted token, so a card inside a card still
   reads as one surface rather than three frames. */
/* The stat cards are excluded here: Apex's are --card on the page ground at the
   full 10px radius, and this rule was repainting them muted at 8px. Panels and
   the feed keep the muted step. */
.st-key-term [class*="st-key-tmsec_"] .tm-p,
.st-key-term [class*="st-key-tmsec_"] .tm-feed{
  background:var(--t-panel2); border:1px solid var(--t-rule);
  border-radius:var(--t-rc); }
.st-key-term [class*="st-key-tmsec_"] .tm-rib > div{
  background:var(--t-panel); border:1px solid var(--t-rule);
  border-radius:var(--t-r); }

/* ---- SECTION HEADER = title + muted subtitle + divider, sentence case. */
.st-key-term .tm-h{ display:flex; align-items:baseline; gap:10px;
  margin:0 0 12px; padding-bottom:10px;
  border-bottom:1px solid var(--t-rule); }
.st-key-term .tm-h .k{ color:var(--t-ink); font-size:15px; font-weight:600;
  letter-spacing:-.01em; text-transform:none; }
.st-key-term .tm-h .k::before{ content:none; }
.st-key-term .tm-h .r{ flex:1; height:0; background:none; }
.st-key-term .tm-h .v{ color:var(--t-dim); font-size:12.5px;
  letter-spacing:0; text-transform:none; font-weight:400; }

/* ---- TABLES. Faint tinted header, hairline rows, no zebra, no uppercase. */
/* Same spec as /customers/, at this grid's density: its rows are 44.5px for
   seven columns, these carry up to fourteen, so 34px with the same 8px/12px
   cell padding and the same uppercase 12px/600 .6px-tracked header. */
.st-key-term .tm-pt{ padding:8px 12px; font-size:12.5px; min-height:34px;
  border-bottom:1px solid var(--t-rule); }
/* The positions books carry Apex's two-line identity cell, so their rows take
   its 44px and their cells stop clipping the sub-line. */
.st-key-pos_real .tm-pt, .st-key-pos_paper .tm-pt{ min-height:44px; }
/* The Close control lives in a sibling column, so nothing makes it the same
   height as the row it closes — Streamlit's vertical_alignment centres the
   COLUMN, and the column was 7px shorter than the 44px row. Give it the row's
   height and centre inside it, so the two cannot drift again. */
/* Streamlit's column is [data-testid="stColumn"], not a bare div — the first
   attempt targeted `> div:last-child` and matched nothing, so the button stayed
   7px above its row. Measured, not assumed: scripts/pos_align.mjs. */
/* No guessed height. The identity cell is two lines, so a row is 49px, not the
   44px min-height — pinning the button column to 44 left it 7px high. Let the
   column inherit the ROW's height from the flex block and centre in that, and
   kill the 4px of leading Streamlit puts above the row's own container. */
.st-key-pos_real [data-testid="stColumn"]:has(.stButton),
.st-key-pos_paper [data-testid="stColumn"]:has(.stButton){
  display:flex; align-items:center; }
.st-key-pos_real [data-testid="stColumn"]:has(.stButton) > div,
.st-key-pos_paper [data-testid="stColumn"]:has(.stButton) > div{
  width:100%; display:flex; justify-content:center; }
.st-key-pos_real [data-testid="stColumn"] > [data-testid="stVerticalBlock"],
.st-key-pos_paper [data-testid="stColumn"] > [data-testid="stVerticalBlock"]{
  gap:0 !important; }
/* THE actual cause, measured: Streamlit's own markdown container carries
   margin-bottom:-14px, so a 49px row reported 35px to its parents and the flex
   block sized itself to 35. The button then centred in 35px while the row's
   real centre was 7px lower. Undo the collapse for these rows and let the
   block stretch, so both columns share the row's true height. */
.st-key-pos_real [data-testid="stMarkdownContainer"]:has(.tm-pt),
.st-key-pos_paper [data-testid="stMarkdownContainer"]:has(.tm-pt){
  margin-bottom:0 !important; }
.st-key-pos_real [data-testid="stHorizontalBlock"],
.st-key-pos_paper [data-testid="stHorizontalBlock"]{
  align-items:stretch !important; }
/* A Streamlit button cannot live inside a markdown grid, so the Close control
   is a SIBLING column — which made it look like it sat outside the table. It
   cannot be moved inside, so the column is dressed as the table's last cell:
   the same hairline under it, the same tinted band across the header, the same
   fill across the total. The ruled area now runs the full width of the box. */
/* ══ the row's detail disclosure: labelled pairs, not another table */
.st-key-term .pd{ display:grid;
  grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:10px 18px;
  padding:4px 2px 8px; }
.st-key-term .pd-i{ display:flex; flex-direction:column; gap:1px; }
.st-key-term .pd-i em{ font-style:normal; font-size:10.5px; letter-spacing:.06em;
  text-transform:uppercase; color:var(--t-faint); font-family:var(--t-sans); }
.st-key-term .pd-i b{ font-size:12.5px; font-weight:500; }
.st-key-term [data-testid="stExpander"]{ border:0 !important;
  background:transparent !important; margin:0 0 2px; }
.st-key-term [data-testid="stExpander"] summary{ font-size:11px !important;
  color:var(--t-faint) !important; padding:2px 12px !important; }
.st-key-term [data-testid="stExpander"] summary:hover{ color:var(--t-amber) !important; }
.st-key-term [data-testid="stExpander"] [data-testid="stExpanderDetails"]{
  padding:0 12px !important; }

/* ══ ANALYST DESK — the chart band (design 09, chosen 2026-08-20).
   Charts lead and tables follow, and every panel carries a caption that says
   what the number MEANS rather than repeating its name. */
.st-key-term .an-grid{ display:grid; grid-template-columns:2.1fr 1fr; gap:14px; }
@media (max-width:1100px){ .st-key-term .an-grid{ grid-template-columns:1fr; } }
.st-key-term .an-panel{ background:var(--t-panel); border:1px solid var(--t-rule);
  border-radius:var(--t-r); padding:14px 16px; }
.st-key-term .an-panel h4{ margin:0 0 2px; font-size:14px; font-weight:600;
  font-family:var(--t-sans); color:var(--t-ink); }
.st-key-term .an-cap{ font-size:12px; color:var(--t-dim); margin:0 0 12px;
  font-family:var(--t-sans); line-height:1.5; }
.st-key-term .an-svg{ width:100%; height:132px; display:block; }
.st-key-term .an-legend{ display:flex; gap:14px; flex-wrap:wrap; margin-top:9px;
  font-size:11.5px; color:var(--t-dim); font-family:var(--t-sans); }
.st-key-term .an-legend i{ width:9px; height:9px; border-radius:2px;
  display:inline-block; margin-right:5px; }
.st-key-term .an-bar{ margin-bottom:11px; }
.st-key-term .an-bl{ display:flex; justify-content:space-between; gap:10px;
  font-size:12px; font-family:var(--t-sans); }
.st-key-term .an-tr{ height:7px; background:var(--t-panel2); border-radius:99px;
  overflow:hidden; margin:4px 0 3px; }
.st-key-term .an-tr i{ display:block; height:100%; border-radius:99px; }
.st-key-term .an-bs{ font-size:11px; color:var(--t-faint);
  font-family:var(--t-sans); }
.st-key-term .an-empty{ font-size:12px; color:var(--t-faint);
  font-family:var(--t-sans); padding:22px 0; }

/* Apex's table card: one border round the whole table, corners clipped so the
   header tint and the last row stop at the radius. Asked for on 2026-08-20:
   "also make border on tables". */
.st-key-term .tm-tbl{ border:1px solid var(--t-rule); border-radius:var(--t-r);
  overflow:hidden; background:var(--t-panel); }
.st-key-term .tm-tbl .tm-pt-h{ border-radius:0; }
.st-key-term .tm-tbl .tm-pt:last-child{ border-bottom:0; }

/* The positions books are built row-by-row from Streamlit columns, so the table
   has no single element to border — each block carries one edge instead, which
   adds up to one frame around the whole grid. */
.st-key-pos_real [data-testid="stHorizontalBlock"]:has(.tm-pt) > [data-testid="stColumn"]:first-child,
.st-key-pos_paper [data-testid="stHorizontalBlock"]:has(.tm-pt) > [data-testid="stColumn"]:first-child{
  border-left:1px solid var(--t-rule); }
.st-key-pos_real [data-testid="stHorizontalBlock"]:has(.tm-pt) > [data-testid="stColumn"]:last-child,
.st-key-pos_paper [data-testid="stHorizontalBlock"]:has(.tm-pt) > [data-testid="stColumn"]:last-child{
  border-right:1px solid var(--t-rule); }
.st-key-pos_real [data-testid="stHorizontalBlock"]:has(.tm-pt-h) > [data-testid="stColumn"],
.st-key-pos_paper [data-testid="stHorizontalBlock"]:has(.tm-pt-h) > [data-testid="stColumn"]{
  border-top:1px solid var(--t-rule); }
.st-key-pos_real [data-testid="stHorizontalBlock"]:has(.tm-pt-h) > [data-testid="stColumn"]:first-child,
.st-key-pos_paper [data-testid="stHorizontalBlock"]:has(.tm-pt-h) > [data-testid="stColumn"]:first-child{
  border-radius:var(--t-rc) 0 0 0; }
.st-key-pos_real [data-testid="stHorizontalBlock"]:has(.tm-pt-t) > [data-testid="stColumn"],
.st-key-pos_paper [data-testid="stHorizontalBlock"]:has(.tm-pt-t) > [data-testid="stColumn"]{
  border-bottom:1px solid var(--t-rule); }

/* No column gap in these blocks, or the 14px gutter cuts a white notch through
   the header band and every row hairline. */
.st-key-pos_real [data-testid="stHorizontalBlock"],
.st-key-pos_paper [data-testid="stHorizontalBlock"]{ gap:0 !important; }
.st-key-pos_real [data-testid="stHorizontalBlock"]:has(.tm-pt)
  > [data-testid="stColumn"]:last-child{
  border-bottom:1px solid var(--t-rule); }
.st-key-pos_real [data-testid="stHorizontalBlock"]:has(.tm-pt-h)
  > [data-testid="stColumn"]:last-child{
  background:color-mix(in oklab, var(--t-panel2) 55%, transparent);
  border-bottom:1px solid var(--t-rule);
  border-radius:0 var(--t-rc) 0 0; }
.st-key-pos_real [data-testid="stHorizontalBlock"]:has(.tm-pt-t)
  > [data-testid="stColumn"]:last-child,
.st-key-pos_paper [data-testid="stHorizontalBlock"]:has(.tm-pt-t)
  > [data-testid="stColumn"]:last-child{
  background:var(--t-panel2); border-top:1px solid var(--t-rule2);
  border-bottom:0; }
/* and the row's hover carries across it, so one row still reads as one row */
@media (hover:hover) and (pointer:fine){
  .st-key-pos_real [data-testid="stHorizontalBlock"]:has(.tm-pt):hover
    > [data-testid="stColumn"]{
    background:color-mix(in oklab, var(--t-amber) 8%, transparent); } }
.st-key-term .tm-pt .c:has(.ap-cell){ overflow:visible; }
.st-key-term .ap-cell{ display:flex; align-items:center; line-height:1.25; }
.st-key-term .ap-av{ font-family:var(--t-sans); }
.st-key-term .ap-sub{ font-family:var(--t-sans); }
.st-key-term .tm-pt-h{
  background:color-mix(in oklab, var(--t-panel2) 55%, transparent);
  color:var(--t-dim); font-size:11.5px; font-weight:600; letter-spacing:.6px;
  text-transform:uppercase; padding:10px 12px; white-space:nowrap;
  border-bottom:1px solid var(--t-rule); border-radius:var(--t-rc) var(--t-rc) 0 0; }
.st-key-term .tm-pt-t{ font-weight:600; background:var(--t-panel2);
  border-top:1px solid var(--t-rule2); border-bottom:0; }
@media (hover:hover) and (pointer:fine){
  .st-key-term .tm-pt:not(.tm-pt-h):not(.tm-pt-t):hover{
    background:color-mix(in oklab, var(--t-amber) 8%, transparent); } }

/* ---- soft status pill, Apex's shape: rounded-full, tinted, 600. */
.st-key-term .tm-badge{ border-radius:9999px; font-size:11px; font-weight:600;
  letter-spacing:0; text-transform:none; padding:3px 10px; }
.st-key-term .tm-pill{ display:inline-block; border-radius:9999px;
  font-size:11px; font-weight:600; padding:2px 9px;
  background:color-mix(in oklab, var(--t-panel2) 80%, transparent);
  border:1px solid var(--t-rule); color:var(--t-dim); }

/* Pagination: the current page is a filled pill, the others are buttons. */
.st-key-term .tm-pg-on{
  text-align:center; font-size:11.5px; font-weight:700; line-height:1;
  padding:9px 0; border-radius:var(--t-rc);
  background:var(--t-amber); color:#ffffff; }
.st-key-term [data-testid="stHorizontalBlock"] .stButton button{
  min-height:0; padding:7px 0; font-size:11.5px; }
</style>
"""

# Night mode for the terminal: it redefines the SEVEN token groups above and
# nothing else, so no rule can paint ink without its ground having been painted
# too — which is what caused the two invisible-text bugs of 2026-08-15.
TERMINAL_DARK_CSS = """
<style>
.st-key-term{
  /* Apex's own dark set — its sidebar tokens, which are its dark surface:
     --sidebar, --sidebar-accent, --sidebar-border, --sidebar-primary. */
  --t-ground:transparent; --t-panel:oklch(19% 0 0);
  --t-panel2:oklch(23.5% 0 0);
  --t-rule:oklch(28% 0 0); --t-rule2:oklch(36% 0 0);
  --t-ink:oklch(98.5% 0 0); --t-dim:oklch(72% 0 0);
  --t-faint:oklch(60% 0 0);
  --t-amber:oklch(62% .21 264.376); --t-up:oklch(69.6% .17 162.48);
  --t-dn:oklch(64.5% .246 16.439);
}
/* Streamlit paints its dataframe canvas itself and reads none of our tokens,
   so it is inverted to match. LIGHT mode must never get this rule: it turned a
   white grid black, which is half of what the operator reported. */
.st-key-term [data-testid="stDataFrame"]{ filter:invert(.92) hue-rotate(180deg); }
</style>
"""

# Bar length -> the name a trader uses for it.
_TF_NAMES = {60: "1m", 300: "5m", 900: "15m", 1800: "30m", 3600: "1h",
             7200: "2h", 14400: "4h", 28800: "8h", 86400: "1d"}


def _tm_tf(spec: dict) -> str:
    """Timeframe read from the spec's bar length, never parsed out of a key."""
    return _TF_NAMES.get(int(spec.get("bar_seconds") or 0), "—")


# The operator's own name for a row, drawn in the STRATEGY column beside the
# signal. The tile label carries it too, but the label is only read on the
# backtest header and in the note — asked for on 2026-08-19: "i said to add the
# 8.67 in the name", meaning the grid row itself.
_TILE_TAGS = {
    "fade15_1h_pv2": "Best 8.67 for August",
}


def _tm_sig(key: str) -> str:
    """The signal name inside a strategy key ('mom15_4h_w' -> 'mom15')."""
    parts = key.split("_")
    return parts[1] if parts and parts[0] == "ict" and len(parts) > 1 else parts[0]


def _an_equity(dry: bool = False) -> list:
    """Cumulative realised PnL per closed trade, oldest first.

    Built from the ledger's own exit rows — the same rows every other figure on
    this screen reads — so the curve cannot disagree with the totals beside it.
    """
    from tradingagents import auto_trader as at
    out, run = [], 0.0
    for e in at.ledger_since(0):
        if e.get("action") != "exit" or bool(e.get("dry_run")) is not dry:
            continue
        run += float(e.get("pnl_est") or 0.0)
        out.append((int(e.get("ts", 0)), round(run, 4)))
    return out


def _an_curve(series: list, *, w: int = 640, h: int = 132) -> str:
    """An area chart of the equity curve. Inline SVG, no library, no request.

    Zero is drawn as a real axis rather than implied, because a curve that lives
    entirely below zero must LOOK like it does.
    """
    if len(series) < 2:
        return (f"<div class='an-empty'>No closed trades yet — the curve needs "
                f"at least two to have a shape.</div>")
    ys = [v for _t, v in series]
    lo, hi = min(min(ys), 0.0), max(max(ys), 0.0)
    span = (hi - lo) or 1.0
    n = len(series) - 1
    px = lambda i: i / n * w
    py = lambda v: h - (v - lo) / span * h
    pts = " ".join(f"{px(i):.1f},{py(v):.1f}" for i, (_t, v) in enumerate(series))
    zero = py(0.0)
    last = ys[-1]
    tone = "var(--buy)" if last >= 0 else "var(--sell)"
    return (
        f"<svg viewBox='0 0 {w} {h}' preserveAspectRatio='none' "
        f"class='an-svg' role='img' aria-label='Equity curve, "
        f"{len(series)} closed trades, ending {last:+.2f} USDT'>"
        f"<defs><linearGradient id='anfill' x1='0' y1='0' x2='0' y2='1'>"
        f"<stop offset='0' stop-color='{tone}' stop-opacity='.30'/>"
        f"<stop offset='1' stop-color='{tone}' stop-opacity='0'/>"
        f"</linearGradient></defs>"
        f"<line x1='0' y1='{zero:.1f}' x2='{w}' y2='{zero:.1f}' "
        f"stroke='var(--t-rule2)' stroke-dasharray='3 3'/>"
        f"<polyline points='{pts}' fill='none' stroke='{tone}' "
        f"stroke-width='2' vector-effect='non-scaling-stroke'/>"
        f"<polygon points='0,{zero:.1f} {pts} {w},{zero:.1f}' fill='url(#anfill)'/>"
        f"<circle cx='{w}' cy='{py(last):.1f}' r='3.5' fill='{tone}'/>"
        f"</svg>")


def _an_bars(stats: dict, limit: int = 8) -> str:
    """Lifetime per strategy as a ranked bar list — design 09's second panel.

    Sorted by SIZE, not sign, so the biggest mover is first whichever way it
    went; the bar length is relative to that mover.
    """
    rows = [(k, float(v.get("pnl", 0.0)), v) for k, v in (stats or {}).items()
            if v.get("trades")]
    if not rows:
        return "<div class='an-empty'>No closed trades on this book yet.</div>"
    rows.sort(key=lambda r: -abs(r[1]))
    top = abs(rows[0][1]) or 1.0
    out = []
    for key, pnl, v in rows[:limit]:
        pct = min(100.0, abs(pnl) / top * 100.0)
        tone = "var(--buy)" if pnl >= 0 else "var(--sell)"
        out.append(
            f"<div class='an-bar'><div class='an-bl'>"
            f"<span>{html.escape(key)}</span>"
            f"<b class='{_tm_cls(pnl)}'>{pnl:+,.2f}</b></div>"
            f"<div class='an-tr'><i style='width:{pct:.1f}%;background:{tone}'>"
            f"</i></div>"
            f"<div class='an-bs'>{v.get('wins', 0)}W / {v.get('losses', 0)}L "
            f"&middot; {v.get('trades', 0)} trades</div></div>")
    return "".join(out)


# ui-ux-pro-max checklist, first line: "No emojis as icons (use SVG:
# Heroicons/Lucide)". The stat cells carried text glyphs — $, Σ, ◷, ◈, ◇, ● —
# which are neither emoji nor icons: they inherit the text baseline, they cannot
# be sized independently of the type, and a screen reader announces them as
# characters. These are Lucide paths, 24x24 on a 2px stroke, marked
# aria-hidden because the label beside each one already names it.
_MV_ICONS = {
    "wallet": "M19 7V5a2 2 0 0 0-2-2H5a2 2 0 0 0 0 4h15a2 2 0 0 1 2 2v8a2 2 0 0"
              " 1-2 2H5a2 2 0 0 1-2-2V5M16 12h.01",
    "trend": "M3 17l6-6 4 4 8-8M21 7v6h-6",
    "clock": "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zM12 6v6l4 2",
    "layers": "M12 2 2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5",
    "flask": "M9 3h6M10 3v6L5 19a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-10V3",
    "pulse": "M22 12h-4l-3 9L9 3l-3 9H2",
}


def _mv_icon(name: str, tone: str = "currentColor", size: int = 16) -> str:
    d = _MV_ICONS.get(name)
    if not d:
        return ""
    return (f"<svg width='{size}' height='{size}' viewBox='0 0 24 24' fill='none' "
            f"stroke='{tone}' stroke-width='2' stroke-linecap='round' "
            f"stroke-linejoin='round' aria-hidden='true' focusable='false'>"
            f"<path d='{d}'/></svg>")


def _mv_ring(pct: float, tone: str) -> str:
    """Progress to the barrier as a ring. A percentage you have to read is a
    number; a ring is a shape, and the shape is what you catch at a glance."""
    p = max(0.0, min(100.0, float(pct or 0)))
    return (f"<div class='mv-ring' style='background:conic-gradient({tone} 0 "
            f"{p:.1f}%,var(--s1) {p:.1f}% 100%);color:{tone}'>"
            f"<i>{p:.0f}%</i></div>")


# ---------------------------------------------------------------------------
# COUNTING MONEY
#
# A figure that counts from what was last on screen to what it is now, in pure
# CSS. No JavaScript is involved and none can be: st.markdown strips <script>,
# so a JS counter cannot run inside anything this app renders.
#
# The mechanism is a REGISTERED custom property. `--aw` is declared with
# `syntax:"<integer>"`, which makes it a real animatable type rather than an
# opaque string, so the browser can interpolate it. `counter-reset` seeds a
# counter from that property and `content: counter(...)` prints it, so
# animating the number animates the printed digits.
#
# Money needs a decimal point and thousands separators, and a counter cannot
# contain either — so the value is split into up to three counters (thousands,
# remainder, cents) and the "," and "." are literal text between them. The
# remainder and cents are printed through @counter-style rules that zero-pad,
# or 1,005.07 would print as "1,5.7".
_ANI_STATE: dict = {}
_ANI_SEQ = [0]

# Beyond this the value would need a fourth counter group; a static figure is
# correct and honest, rather than a wrong one that animates.
_ANI_MAX = 1_000_000


def _ani_money(value, *, key: str, sign: bool = False,
               unit: str = "", cls: str = "") -> str:
    """Money that counts up to `value` from whatever this key showed before.

    `key` identifies the figure across reruns — the account balance keeps
    counting from its own last value, not from another tile's.
    """
    if value is None:
        return "<span>&mdash;</span>"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "<span>&mdash;</span>"

    prev = _ANI_STATE.get(key)
    _ANI_STATE[key] = v
    # First paint has nothing to count from, so it counts up from zero — the
    # thing a dashboard does on load.
    start = 0.0 if prev is None else prev

    def _split(x):
        cents = int(round(abs(x) * 100))
        whole, frac = divmod(cents, 100)
        k, rem = divmod(whole, 1000)
        return k, rem, frac, whole

    if abs(v) >= _ANI_MAX or abs(start) >= _ANI_MAX:
        big = f"{v:+,.2f}" if sign else f"{v:,.2f}"
        return f"<span class='{cls}'>{big}{unit}</span>"

    k1, r1, f1, w1 = _split(v)
    k0, r0, f0, w0 = _split(start)
    # The sign is text, never a counter: a counter would render its own minus
    # and the digits would fight the label. It follows the FINAL value.
    pre = ("-" if v < 0 else "+") if sign else ("-" if v < 0 else "")

    _ANI_SEQ[0] += 1
    eid = f"anm{_ANI_SEQ[0]}"
    grouped = w1 >= 1000 or w0 >= 1000
    if grouped:
        frm = f"--ak:{k0}; --aw:{r0}; --af:{f0}"
        to = f"--ak:{k1}; --aw:{r1}; --af:{f1}"
        digits = ("<i class='k'></i>,<i class='w3'></i>"
                  ".<i class='f'></i>")
        seed = f"--ak:{k1};--aw:{r1};--af:{f1}"
    else:
        frm = f"--aw:{w0}; --af:{f0}"
        to = f"--aw:{w1}; --af:{f1}"
        digits = "<i class='w'></i>.<i class='f'></i>"
        seed = f"--aw:{w1};--af:{f1}"
    # A counter is GLYPHS, not text. Measured 2026-08-20: Chrome's full
    # accessibility tree exposes zero of these figures — a screen reader gets
    # silence where the account balance is, and innerText reads "." Hence the
    # visually-hidden real text node, which is the accessible value AND the
    # only way a test can read back what the page actually prints. The counter
    # half is aria-hidden so the figure is never announced twice.
    txt = f"{v:+,.2f}" if sign else f"{v:,.2f}"
    return (
        f"<style>@keyframes {eid}{{from{{{frm}}}to{{{to}}}}}"
        f"#{eid}{{animation:{eid} .9s cubic-bezier(.22,1,.36,1) both}}</style>"
        # The seed values are set inline as well as animated to, so the figure
        # is CORRECT with no animation at all — which is what a reduced-motion
        # reader gets, and what shows if @property is unsupported.
        f"<span class='ani {cls}' id='{eid}' style='{seed}'>"
        f"<span class='ani-sr'>{txt}{unit}</span>"
        f"<span aria-hidden='true'>{pre}{digits}{unit}</span></span>")


def _mv_hero(equity, day, open_real, life, series, armed: bool) -> str:
    """The one number that matters, with its own curve behind it."""
    curve = ""
    if len(series) >= 2:
        ys = [v for _t, v in series]
        lo, hi = min(ys), max(ys)
        span = (hi - lo) or 1.0
        n = len(series) - 1
        pts = " ".join(
            f"{i / n * 100:.2f},{28 - (v - lo) / span * 26:.2f}"
            for i, (_t, v) in enumerate(series))
        tone = "var(--up)" if ys[-1] >= 0 else "var(--dn)"
        curve = (
            f"<svg viewBox='0 0 100 30' preserveAspectRatio='none' aria-hidden='true'>"
            f"<defs><linearGradient id='mvg' x1='0' y1='0' x2='0' y2='1'>"
            f"<stop offset='0' stop-color='{tone}' stop-opacity='.34'/>"
            f"<stop offset='1' stop-color='{tone}' stop-opacity='0'/></linearGradient></defs>"
            f"<polygon points='0,30 {pts} 100,30' fill='url(#mvg)'/>"
            f"<polyline points='{pts}' fill='none' stroke='{tone}' stroke-width='.6'"
            f" vector-effect='non-scaling-stroke'/></svg>")
    return (
        "<div class='mv-hero'>"
        + (f"<span class='badge'><i></i>{'Trading' if armed else 'Halted'}</span>")
        + "<div class='k'>Account</div>"
        + "<div class='v'>"
        + _ani_money(equity, key="hero.equity")
        + "<span style='font-size:.42em;color:var(--dim);font-weight:500'>"
          " USDT</span></div>"
        + "<div class='d'>"
        + f"<span>Open <b class='{_mv_cls(open_real)}'>"
        + _ani_money(open_real, key="hero.open", sign=True) + "</b></span>"
        + f"<span>Today <b class='{_mv_cls(day)}'>"
        + _ani_money(day, key="hero.day", sign=True) + "</b></span>"
        + f"<span>Lifetime <b class='{_mv_cls(life)}'>"
        + _ani_money(life, key="hero.life", sign=True) + "</b></span>"
        + "</div>" + curve + "</div>")


def _mv_cls(v) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "mv-nil"
    return "mv-up" if v > 0 else "mv-dn" if v < 0 else "mv-nil"


def _mv_positions(rows: list, label: str, sub: str, live: bool) -> str:
    """The positions table, as my own grid. Six columns, a ring for distance,
    and no widget anywhere inside it."""
    cols = "2.6fr .9fr 1.1fr 1.2fr 1fr .9fr"
    # Live and Paper render the same coins. Without this the paper row would
    # count from the live row's figure and vice versa.
    _bk = "live" if live else "paper"
    out = [f"<div class='mv-panel'><div class='mv-ph'><h3>{label}</h3>"
           f"<span class='sub'>{sub}</span>"
           f"<span class='mv-seg'><span class='{'on' if live else ''}'>Live</span>"
           f"<span class='{'' if live else 'on'}'>Paper</span></span></div>"]
    if not rows:
        out.append("<div class='mv-empty'>Nothing open on this book.</div></div>")
        return "".join(out)
    out.append(f"<div class='mv-row hd' style='grid-template-columns:{cols}'>"
               "<div>Position</div><div>Side</div><div class='mv-r'>Open P/L</div>"
               "<div>To barrier</div><div class='mv-r'>At risk</div>"
               "<div class='mv-r'>Entry</div></div>")
    tot_open = tot_risk = 0.0
    for r in rows:
        coin = str(r.get("coin", ""))
        tone_av = _AP_AVATAR[sum(map(ord, coin)) % len(_AP_AVATAR)]
        side = str(r.get("side") or "").upper()
        op = float(r.get("open $") or 0)
        risk = float(r.get("margin $") or 0)
        tot_open += op
        tot_risk += risk
        pct = r.get("prog_pct")
        tone = "var(--up)" if r.get("prog_to") == "TP" else "var(--dn)"
        out.append(
            f"<div class='mv-row' style='grid-template-columns:{cols}'>"
            f"<div class='mv-id'><span class='mv-av' style='background:{tone_av}'>"
            f"{html.escape(coin[:2].upper())}</span><span><span class='nm'>"
            f"{html.escape(coin)}</span><br><span class='sb'>"
            f"{html.escape(str(r.get('strategy') or ''))}</span></span></div>"
            f"<div><span class='mv-pill {'up' if side == 'LONG' else 'dn'}'>"
            f"{side.title()}</span></div>"
            f"<div class='mv-r mv-num {_mv_cls(op)}'>"
            + _ani_money(op, key=f"pos.{_bk}.{coin}.op", sign=True) + "</div>"
            + (f"<div>{_mv_ring(pct, tone)}</div>" if pct is not None
               else "<div class='mv-sm mv-nil'>&mdash;</div>")
            + "<div class='mv-r mv-num'>"
            + _ani_money(risk, key=f"pos.{_bk}.{coin}.risk") + "</div>"
            + f"<div class='mv-r mv-sm'>{r.get('entry') or '&mdash;'}</div></div>")
    out.append(f"<div class='mv-row ft' style='grid-template-columns:{cols}'>"
               f"<div>{len(rows)} open</div><div></div>"
               f"<div class='mv-r {_mv_cls(tot_open)}'>"
               + _ani_money(tot_open, key=f"pos.{_bk}.total", sign=True)
               + "</div>"
               f"<div></div><div class='mv-r'>"
               + _ani_money(tot_risk, key=f"pos.{_bk}.risktotal") + "</div>"
               "<div></div></div>")
    out.append("</div>")
    return "".join(out)


def _mv_strategies(tiles, saved, stats, specs) -> str:
    """One line per strategy: what it is, where it trades, whether it is armed,
    and the only number that decides anything — its lifetime."""
    out = ["<div class='mv-panel'><div class='mv-ph'><h3>Strategies</h3>"
           "<span class='sub'>armed on this account</span></div>",
           "<div class='mv-str'><div class='hd'><span>Rule</span><span>Bar</span>"
           "<span>Contract</span><span>Stop / target</span>"
           "<span>Lifetime</span><span>Books</span></div>"]
    from tradingagents import auto_trader as at
    for key, _lab, _note, coins in tiles:
        sp = specs.get(key) or {}
        bk = at.books_for(key, saved) if key in (saved.get("strategies") or []) else []
        st_ = stats.get(key) or {}
        pnl = st_.get("pnl")
        dot = ("var(--up)" if False in bk else
               "var(--acc)" if True in bk else "var(--faint)")
        books = ("Live + paper" if False in bk and True in bk else
                 "Live" if False in bk else "Paper" if True in bk else "Off")
        out.append(
            f"<div><span class='nm'>{html.escape(_tm_sig(key))}"
            + (f" <span class='tf'>{html.escape(_TILE_TAGS[key])}</span>"
               if key in _TILE_TAGS else "")
            + f"</span><span class='tf'>{html.escape(_tm_tf(sp))}</span>"
            + f"<span class='mv-sm'>"
              f"{html.escape(', '.join(c.replace('_USDT','') for c in coins))}</span>"
            + f"<span class='mv-sm'>{sp.get('sl', 0) * 100:.2f}"
              f" / {sp.get('tp', 0) * 100:.2f}</span>"
            + ((f"<span class='mv-num {_mv_cls(pnl)}'>"
                + _ani_money(float(pnl), key=f"strat.{key}.pnl", sign=True)
                + "</span>")
               if pnl is not None and st_.get("trades")
               else "<span class='mv-sm mv-nil'>no trades</span>")
            + f"<span class='mv-sm'><i class='mv-dot' style='background:{dot}'></i>"
              f"{books}</span></div>")
    out.append("</div></div>")
    return "".join(out)


ANI_CSS = """
<style>
/* Registered properties: `syntax:"<integer>"` is what makes these animatable.
   Declared as plain custom properties they would be opaque strings and the
   browser would jump straight to the end value instead of counting. */
@property --aw { syntax:"<integer>"; initial-value:0; inherits:false; }
@property --af { syntax:"<integer>"; initial-value:0; inherits:false; }
@property --ak { syntax:"<integer>"; initial-value:0; inherits:false; }

/* A counter prints "7", not "07", so 1,005.07 would come out as "1,5.7".
   These pad the groups that sit to the right of a separator. */
@counter-style ani2 { system:extends decimal; pad:2 "0"; }
@counter-style ani3 { system:extends decimal; pad:3 "0"; }

.ani{ counter-reset: aw var(--aw) af var(--af) ak var(--ak);
      font-variant-numeric:tabular-nums; font-feature-settings:"tnum";
      white-space:nowrap; }
.ani i{ font-style:normal; }
/* The accessible copy of the figure: read by assistive tech, never seen. Not
   display:none — that would remove it from the accessibility tree too, which
   is the whole problem it exists to solve. */
.ani-sr{ position:absolute !important; width:1px; height:1px; overflow:hidden;
  clip-path:inset(50%); white-space:nowrap; border:0; padding:0; margin:-1px; }
.ani i.k::after  { content:counter(ak); }
.ani i.w::after  { content:counter(aw); }
.ani i.w3::after { content:counter(aw, ani3); }
.ani i.f::after  { content:counter(af, ani2); }

/* Reduced motion keeps the FIGURE and drops the count. The inline seed values
   already hold the final number, so switching the animation off cannot leave a
   stale or zeroed figure on screen. */
@media (prefers-reduced-motion: reduce){
  .ani{ animation:none !important; }
}
</style>
"""

MODERN_CSS = """
<style>
/* ═══════════════════════════════════════════════════════════════════════
   THE VIEW — Auto Trade rendered as one block of markup I control, instead
   of Streamlit widgets re-skinned with !important. Built 2026-08-20 after the
   operator said the re-skin was not impressive; the honest reason it was not
   is that the row markup belonged to Streamlit. Everything here is mine: the
   grid, the type scale, the ring, the transitions.
   Interaction stays in Streamlit, in ONE action bar, which also permanently
   ends the Close-button alignment problem — there is no button in the table.
   ═══════════════════════════════════════════════════════════════════════ */
.mv{ --r:14px; --gap:16px;
  --s0:var(--panel); --s1:var(--panel-2); --line:var(--border);
  --ink:var(--text); --dim:var(--muted); --faint:var(--faint);
  --up:var(--buy); --dn:var(--sell); --acc:var(--accent);
  font-family:-apple-system,system-ui,"Segoe UI",Roboto,sans-serif;
  color:var(--ink); font-variant-numeric:tabular-nums;
  display:flex; flex-direction:column; gap:var(--gap); }
.mv *{ box-sizing:border-box; }

/* ── hero: the one number that matters, with the curve behind it ── */
.mv-hero{ position:relative; overflow:hidden; border:1px solid var(--line);
  border-radius:var(--r); background:
    radial-gradient(120% 140% at 88% -20%, color-mix(in oklab,var(--acc) 16%,transparent), transparent 60%),
    var(--s0); padding:26px 28px 0; }
.mv-hero .k{ font-size:11.5px; letter-spacing:.14em; text-transform:uppercase;
  color:var(--dim); }
.mv-hero .v{ font-size:clamp(38px,5vw,54px); font-weight:650; letter-spacing:-.035em;
  line-height:1; margin:6px 0 8px; }
.mv-hero .d{ display:flex; gap:16px; flex-wrap:wrap; font-size:13px; color:var(--dim);
  padding-bottom:18px; }
.mv-hero .d b{ font-weight:600; }
.mv-hero svg{ display:block; width:100%; height:86px; margin:0 -28px; }
.mv-hero .badge{ position:absolute; top:22px; right:26px; display:inline-flex;
  align-items:center; gap:7px; font-size:12px; font-weight:600; padding:5px 12px;
  border-radius:999px; background:color-mix(in oklab,var(--up) 14%,transparent);
  color:var(--up); border:1px solid color-mix(in oklab,var(--up) 32%,transparent); }
.mv-hero .badge i{ width:7px; height:7px; border-radius:50%; background:currentColor;
  animation:mvpulse 2.4s ease-in-out infinite; }
@keyframes mvpulse{ 0%,100%{ opacity:1 } 50%{ opacity:.35 } }
@media (prefers-reduced-motion:reduce){ .mv-hero .badge i{ animation:none } }

/* ── the strip of secondary readouts ── */
.mv-strip{ display:grid; gap:var(--gap);
  grid-template-columns:repeat(auto-fit,minmax(168px,1fr)); }
.mv-cell{ border:1px solid var(--line); border-radius:var(--r); background:var(--s0);
  padding:15px 16px; transition:border-color .16s ease, transform .16s ease; }
.mv-cell:hover{ border-color:color-mix(in oklab,var(--acc) 45%,var(--line));
  transform:translateY(-1px); }
.mv-cell em{ font-style:normal; font-size:11px; letter-spacing:.12em;
  text-transform:uppercase; color:var(--dim); display:flex;
  align-items:center; gap:7px; }
.mv-cell em svg{ flex:0 0 16px; opacity:.85; }
.mv-cell b{ font-size:24px; font-weight:600; letter-spacing:-.025em; display:block;
  margin-top:5px; }
.mv-cell span{ font-size:11.5px; color:var(--faint); display:block; margin-top:3px; }

/* ── my table. real grid, sticky head, no widget anywhere near it ── */
.mv-panel{ border:1px solid var(--line); border-radius:var(--r); background:var(--s0);
  overflow:hidden; }
.mv-ph{ display:flex; align-items:baseline; gap:12px; padding:15px 18px 13px;
  border-bottom:1px solid var(--line); }
.mv-ph h3{ margin:0; font-size:14.5px; font-weight:600; letter-spacing:-.01em; }
.mv-ph .sub{ font-size:12px; color:var(--dim); flex:1; }
.mv-seg{ display:inline-flex; border:1px solid var(--line); border-radius:8px;
  overflow:hidden; font-size:11.5px; }
.mv-seg span{ padding:4px 11px; color:var(--dim); }
.mv-seg span.on{ background:var(--s1); color:var(--ink); font-weight:600; }
.mv-row{ display:grid; align-items:center; gap:14px; padding:13px 18px;
  border-bottom:1px solid var(--line); transition:background .14s ease; }
.mv-row:last-child{ border-bottom:0; }
.mv-row.hd{ padding:9px 18px; background:var(--s1); border-bottom:1px solid var(--line); }
.mv-row.hd div{ font-size:10.5px; letter-spacing:.13em; text-transform:uppercase;
  color:var(--dim); font-weight:600; }
.mv-row:not(.hd):not(.ft):hover{ background:color-mix(in oklab,var(--acc) 6%,transparent); }
.mv-row.ft{ background:var(--s1); font-weight:600; border-bottom:0; }
.mv-r{ text-align:right; }
.mv-id{ display:flex; align-items:center; gap:11px; min-width:0; }
.mv-av{ width:34px; height:34px; flex:0 0 34px; border-radius:10px; display:grid;
  place-items:center; font-size:12px; font-weight:700; color:#fff; letter-spacing:.02em; }
.mv-id .nm{ font-size:13.5px; font-weight:600; line-height:1.25; }
.mv-id .sb{ font-size:11.5px; color:var(--faint); }
.mv-pill{ display:inline-block; font-size:11px; font-weight:600; padding:2px 9px;
  border-radius:999px; }
.mv-pill.up{ background:color-mix(in oklab,var(--up) 15%,transparent); color:var(--up) }
.mv-pill.dn{ background:color-mix(in oklab,var(--dn) 15%,transparent); color:var(--dn) }
.mv-num{ font-size:14px; font-weight:600; letter-spacing:-.01em; }
.mv-sm{ font-size:12px; color:var(--dim); }
.mv-up{ color:var(--up) } .mv-dn{ color:var(--dn) } .mv-nil{ color:var(--faint) }

/* progress to the barrier, as a ring — reads at a glance, unlike a number */
.mv-ring{ width:38px; height:38px; border-radius:50%; display:grid; place-items:center;
  font-size:10.5px; font-weight:700; }
.mv-ring i{ width:28px; height:28px; border-radius:50%; background:var(--s0);
  display:grid; place-items:center; font-style:normal; }

/* ── strategy list: one line each, the numbers that decide things ── */
.mv-str{ display:grid; gap:1px; background:var(--line); }
.mv-str > div{ background:var(--s0); padding:12px 18px; display:grid; gap:14px;
  align-items:center; grid-template-columns:1.9fr .8fr .9fr 1fr 1.1fr .9fr;
  transition:background .14s ease; }
.mv-str > div:hover{ background:color-mix(in oklab,var(--acc) 6%,transparent); }
.mv-str > div.hd{ background:var(--s1); }
.mv-str > div.hd span{ font-size:10.5px; letter-spacing:.13em; text-transform:uppercase;
  color:var(--dim); font-weight:600; }
.mv-str .nm{ font-size:13px; font-weight:600 }
.mv-str .tf{ font-size:11.5px; color:var(--faint) }
.mv-dot{ width:7px; height:7px; border-radius:50%; display:inline-block; margin-right:7px }
.mv-empty{ padding:26px 18px; font-size:12.5px; color:var(--faint); text-align:center }
</style>
"""


def _tm_tile_head(label: str, glyph: str, tone: str) -> str:
    """Apex's stat-card head: the name left, a 36x36 icon chip hard right.

    ``tone`` is a CSS colour; the chip carries it at 10% alpha behind the full
    colour, which is exactly what their dashboard does
    (rgba(22,163,74,.1) on rgb(22,163,74)).
    """
    return (f"<div class='hd'><div class='l'>{label}</div>"
            f"<span class='ic' style='background:color-mix(in oklab,"
            f"{tone} 12%, transparent);color:{tone}'>{glyph}</span></div>")


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


def _timeframe_locks(rows, specs, is_live) -> dict:
    """Which strategy rows may not go LIVE, because their coin is taken.

    One coin runs ONE timeframe **with real money**: two live strategies on the
    same coin at different bar sizes net into a single MEXC position, so the
    second entry resizes the first and either stop closes part of a trade it
    does not own. That is an exchange fact, and it is the only thing this
    locks. DEMO is never locked — a simulated book has no MEXC position to
    fight over, so the operator can paper the same coin on two timeframes to
    compare them.

    ``rows`` is [(key, [coins])] in display order, ``specs`` maps key -> spec
    (for ``interval``), and ``is_live(key)`` says whether that row's LIVE box
    is ticked right now. The FIRST live row in display order wins a coin, so
    freeing it is an explicit untick rather than a silent reassignment.
    Returns ``{locked_key: (coin, holder_key)}``.

    A second row on the SAME timeframe is not locked — that is one position on
    one bar size, which the runner already handles; only a different timeframe
    is the conflict.

    Two passes, because the rule is SYMMETRIC. Claiming and locking in one
    sweep only ever locked rows BELOW the holder: going live on the 4h row
    left the 30m row above it armable, so the operator could still tick
    both. The live rows claim first; then every row on a claimed coin at
    another timeframe is locked, wherever it sits in the list.
    """
    iv_of = lambda k: (specs.get(k) or {}).get("interval", "")   # noqa: E731
    claim: dict[str, tuple[str, str]] = {}
    for key, coins in rows:
        if not is_live(key):
            continue
        interval = iv_of(key)
        # A live row that is ALREADY double-booked claims nothing — the
        # earlier holder keeps the coin and this row is locked below.
        if any(c in claim and claim[c][1] != interval for c in coins):
            continue
        for c in coins:
            claim.setdefault(c, (key, interval))
    locked: dict[str, tuple[str, str]] = {}
    for key, coins in rows:
        interval = iv_of(key)
        hit = next((c for c in coins
                    if c in claim and claim[c][1] != interval), None)
        if hit:
            locked[key] = (hit, claim[hit][0])
    return locked


def _page_numbers(page: int, pages: int, window: int = 7) -> list:
    """The page numbers to draw: first, last, a window around the current one,
    and ``None`` where a gap is elided.

    Numbered pages beat `newer`/`older` because the operator can see how much
    history there is and jump straight to it — but 40 pages of a busy ledger
    would be a wall of buttons, so the middle is elided.
    """
    if pages <= window:
        return list(range(1, pages + 1))
    half = (window - 3) // 2
    lo, hi = page - half, page + half
    if lo < 2:
        lo, hi = 2, window - 1
    if hi > pages - 1:
        lo, hi = pages - window + 2, pages - 1
    out: list = [1]
    if lo > 2:
        out.append(None)
    out.extend(range(lo, hi + 1))
    if hi < pages - 1:
        out.append(None)
    out.append(pages)
    return out


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
    # FIVE columns, rebuilt 2026-08-20: "total remake ... i want clean". It was
    # fourteen — coin, unreal, progress, TP%, SL%, W, L, trades, side, opened,
    # held, entry, margin, stop — every one of them ellipsised on a laptop, and
    # thirteen of them are not what you look at when you open the screen.
    #
    # What survives is the question each row answers: WHAT is open, WHICH WAY,
    # HOW MUCH is it up or down, HOW FAR to the barrier, and HOW BIG is the bet.
    # Entry, liquidation, W/L, age and the stop's state moved into the row's own
    # detail panel, one click away and nothing lost — see `_tm_pos_detail`.
    ("ident", "position", 3.0, "l", "ident"),
    ("side", "side", 1.0, "l", "side"),
    ("open $", "open p/l", 1.3, "r", "money"),
    ("prog", "to barrier", 2.6, "l", "html"),
    ("margin $", "at risk", 1.1, "r", "money0"),
)
_TM_POS_GRID = " ".join(f"{w}fr" for _, _, w, _a, _k in _TM_POS)


def _tm_pos_head() -> str:
    return "".join(
        f"<span class='c {a}'>{html.escape(lab)}</span>"
        for _k, lab, _w, a, _kind in _TM_POS)


def _tm_prog_calc(entry, tp, sl, px, side: int):
    """How far this position has travelled, as (percent, "TP"|"SL") or None.

    Split out of `_tm_progress` on 2026-08-20 because the custom view was
    RE-PARSING the rendered bar's HTML to recover the number — and failed, since
    the markup separates them with &nbsp; rather than a space, so every ring drew
    0%. Two readers of one figure means one calculation, not a regex over the
    other one's output.
    """
    try:
        entry, tp, sl, px = float(entry), float(tp), float(sl), float(px)
    except (TypeError, ValueError):
        return None
    if not entry or not px or side == 0:
        return None
    tp_span, sl_span = tp - entry, sl - entry
    moved = px - entry
    if tp_span and (moved / tp_span) >= 0:
        frac, target = moved / tp_span, "TP"
    elif sl_span:
        frac, target = moved / sl_span, "SL"
    else:
        return None
    return max(0.0, min(frac, 1.0)) * 100, target


def _tm_progress(entry, tp, sl, px, side: int) -> str:
    """A bar showing how far this position has travelled from its ENTRY
    toward its take-profit — green — or toward its stop — red.

    Works for both directions because the span is signed: for a short, tp sits
    below entry, so (px - entry) / (tp - entry) is still positive when the
    trade is winning. Returns "" when any leg is missing rather than drawing a
    bar from a guess.
    """
    got = _tm_prog_calc(entry, tp, sl, px, side)
    if got is None:
        return ""
    pct, target = got
    colour = "var(--t-up)" if target == "TP" else "var(--t-dn)"
    return (
        f"<span style='display:inline-flex;align-items:center;gap:6px;"
        f"width:100%'>"
        f"<span style='flex:1;height:9px;background:var(--t-panel2);"
        f"border:1px solid var(--t-rule2);position:relative;min-width:40px'>"
        f"<span style='position:absolute;left:0;top:0;bottom:0;"
        f"width:{pct:.1f}%;background:{colour}'></span></span>"
        f"<span style='color:{colour};font-size:10.5px;white-space:nowrap'>"
        f"{pct:.0f}%&nbsp;{target}</span></span>")


# Apex's avatar palette, read off /orders/: one deterministic colour per
# identity, white initials at 12px/600 in a 32px circle. Theirs were teal
# rgb(14,116,144), pink rgb(190,24,93), indigo rgb(79,70,229), amber
# rgb(180,83,9) and rgb(3,105,161) for the signed-in user.
_AP_AVATAR = ("#0e7490", "#be185d", "#4f46e5", "#b45309", "#0369a1",
              "#047857", "#7c3aed", "#b91c1c", "#0891b2", "#a16207")


def _ap_avatar(name: str) -> str:
    """A coloured circle with the contract's initials — Apex's row identity."""
    txt = (name or "?").replace("_USDT", "")
    ini = (txt[:2] or "?").upper()
    tone = _AP_AVATAR[sum(map(ord, txt)) % len(_AP_AVATAR)]
    return (f"<span class='ap-av' style='background:{tone};color:#fff'>"
            f"{html.escape(ini)}</span>")


def _ap_pill(text: str, tone: str = "") -> str:
    """Apex's status pill: its own colour at 10% alpha behind the full colour."""
    return f"<span class='ap-pill {tone}'>{html.escape(str(text))}</span>"


def _tm_pos_cell(val, kind: str) -> str:
    """One cell. An absent value prints an em dash, never 'None' — a missing
    price and a broken one must not look the same."""
    if kind == "html":
        return str(val) if val else ""
    if val is None or val == "":
        # A blank is a blank. "text" was the only kind exempt from the em dash,
        # so adding the ident/side/pill kinds made the TOTAL row print dashes
        # under SIDE and BRACKET where it has nothing to say.
        return "" if kind in ("text", "ident", "side", "pill", "html") else "—"
    if kind == "money":
        return f"<span class='{_tm_cls(float(val))}'>{float(val):+.2f}</span>"
    if kind == "money0":
        # A stake is not a gain: no sign, no colour. Signing it made $5 of
        # margin read as five dollars of profit.
        return f"{float(val):,.2f}"
    if kind == "px" and isinstance(val, (int, float)):
        # Simulated brackets carry full float noise (0.09547200000000002);
        # six significant figures is past any contract's price scale.
        return f"{val:.6g}"
    if kind == "num" and isinstance(val, (int, float)):
        return f"{val:g}"
    if kind == "ident":
        # Apex's CUSTOMER cell: avatar, name in medium, detail underneath.
        name, _, sub = str(val).partition("\n")
        return (f"<span class='ap-cell'>{_ap_avatar(name)}"
                f"<span><b>{html.escape(name.replace('_USDT', ''))}</b>"
                + (f"<span class='ap-sub'>{html.escape(sub)}</span>"
                   if sub else "")
                + "</span></span>")
    if kind == "side":
        v = str(val).upper()
        return _ap_pill(v, "ok" if v == "LONG" else
                        "bad" if v == "SHORT" else "")
    if kind == "pill":
        v = str(val)
        return _ap_pill(v, "bad" if "NO STOP" in v.upper() else "")
    return html.escape(str(val))


def _tm_pos_detail(r: dict) -> str:
    """Everything the five-column row does not show, as labelled pairs.

    Nothing was deleted when the table was cut down — entry, liquidation, the
    barriers in both price and percent, the age, the ladder rung and the stop's
    real state all live here, one disclosure away.
    """
    def _pair(k, v, cls=""):
        if v in (None, "", "—"):
            return ""
        return (f"<div class='pd-i'><em>{k}</em>"
                f"<b class='{cls}'>{v}</b></div>")

    _stop = r.get("bracket") or ""
    _px = lambda v: f"{float(v):.6g}" if isinstance(v, (int, float)) else v
    return ("<div class='pd'>"
            + _pair("strategy", r.get("strategy"))
            + _pair("entry", _px(r.get("entry")))
            + _pair("take profit", _px(r.get("TP")))
            + _pair("stop", _px(r.get("SL")))
            + _pair("target %", r.get("tp_pct") and str(r["tp_pct"]))
            + _pair("stop %", r.get("sl_pct") and str(r["sl_pct"]))
            + _pair("contracts", r.get("vol"))
            + _pair("opened", r.get("opened"))
            + _pair("held", r.get("held"))
            + _pair("leverage", r.get("lev"))
            + _pair("record", f"{r.get('W', 0)}W / {r.get('L', 0)}L "
                              f"&middot; {r.get('trades', 0)} trades")
            + (_pair("protection", _stop, "tm-dn") if "NO STOP" in _stop.upper()
               else "")
            + "</div>")


def _tm_pos_row(r: dict) -> str:
    # `ident` is derived, not stored: "COIN\nstrategy", which the ident cell
    # renders as Apex's avatar + name + sub-line. Doing it here means every
    # caller — both books and the TOTAL row — gets it without being touched.
    if "ident" not in r:
        r = dict(r)
        _st = r.get("strategy")
        _cn = str(r.get("coin", ""))
        if _cn == "TOTAL":
            # A summary line is not an identity: giving it an avatar printed a
            # circle reading "TO" beside the word TOTAL.
            r["ident"] = None
            r["_plain"] = "TOTAL"
        else:
            r["ident"] = (f"{_cn}\n{_st}"
                          if _st and _st not in ("—", "-") else _cn)
    if r.get("_plain"):
        head = (f"<span class='c l'><b>{html.escape(r['_plain'])}</b></span>")
        return head + "".join(
            f"<span class='c {a}'>{_tm_pos_cell(r.get(k), kind)}</span>"
            for k, _lab, _w, a, kind in _TM_POS[1:])
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
    # Apex wraps every table in a bordered card with the corners clipped, so
    # the header's tint and the last row's edge both stop at the radius.
    out = [f"<div class='tm-tbl'>",
           f"<div class='tm-pt tm-pt-h' style='{tmpl}'>{head}</div>"]
    if not rows:
        return ("".join(out) + f"<div style='font-size:11.5px;"
                f"color:var(--t-faint);padding:10px 12px'>{empty}</div></div>")
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
    out.append("</div>")          # close .tm-tbl
    return "".join(out)


def render_auto_trade_tab() -> None:
    """The trading terminal: status ribbon, strategy grid, risk, book, feed."""
    _ledger_sync_tick()
    from tradingagents import auto_trader as at
    from tradingagents.dataflows import mexc_credentials as cred
    from tradingagents.dataflows import mexc_futures as fx

    cred.load_into_env()
    saved = _auto_trade_load()
    # The `term` container and its stylesheet are created in main() now, so
    # every screen gets them and this tab does not send the sheet twice. The
    # positions grid template still comes from _TM_POS, so the header, every
    # row and the CSS can never disagree about the column count.
    term = st.container()

    with term:

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
                # Six Apex stat cards: name + icon chip, the number, then one
                # muted line of detail. Explicit `+` throughout — mixing
                # implicit adjacency with a call is a syntax error, and this
                # block is long enough that the error is not obvious.
                + "<div>"
                + _tm_tile_head("Futures wallet", "$", "var(--t-amber)")
                + f"<div class='n'>"
                + (f"{equity:,.2f}" if equity is not None else "—")
                + "</div><div class='s'>USDT collateral</div></div>"
                + "<div>"
                + _tm_tile_head("Real &middot; all time", "\u03a3",
                                "var(--t-amber)")
                + f"<div class='n {_tm_cls(all_time)}'>{all_time:+,.2f}</div>"
                + f"<div class='s'>{life_total:+.2f} closed &middot; "
                  f"{open_real:+.2f} open</div></div>"
                + "<div>"
                + _tm_tile_head("Real &middot; today closed", "\u25d4",
                                "oklch(60% .16 250)")
                + f"<div class='n {_tm_cls(day['total'])}'>"
                  f"{day['total']:+,.2f}</div>"
                + f"<div class='s'>{day['wins']}W / {day['losses']}L &middot; "
                  f"{day['trades']} closed</div></div>"
                # Unrealized is money that has NOT been banked, so it never
                # joins the realized figure in one number. It is also not a
                # "today" quantity — a position open since the 13th carries its
                # whole life in here — so the label says OPEN NOW, and the coins
                # are itemised rather than hidden behind a total (a summed figure
                # once shipped labelled with one coin's name).
                + "<div>"
                + _tm_tile_head("Open now &middot; unrealized", "\u25c8",
                                "oklch(60% .16 320)")
                + f"<div class='n {_tm_cls(open_real)}'>{open_real:+,.2f}</div>"
                + "<div class='s'>"
                + (" &middot; ".join(f"{_c} {_v:+.2f}" for _c, _v in open_bits)
                   if open_bits else "no position open")
                + "</div></div>"
                + "<div>"
                + _tm_tile_head("Paper &middot; demo", "\u25c7", "var(--t-dim)")
                + f"<div class='n {_tm_cls(paper_total)}'>{paper_total:+,.2f}"
                  f"</div><div class='s'>not real money</div></div>"
                + "<div>"
                + _tm_tile_head("Runner", "\u25cf", "oklch(70% .15 75)")
                + f"<div class='n {mode_cls}'>{mode}</div>"
                + f"<div class='s'>"
                + ("entries halted" if at.halted() else "scanning")
                + "</div></div></div>", unsafe_allow_html=True)

        # Both the view and the legacy band read these rows, so a position
        # cannot appear in one and not the other.
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
                        "L": v["losses"], "bracket": ""}

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
                    # Blank when the stop is where it should be. "on
                    # MEXC" and "SIMULATED" told the operator what the
                    # book they are already labelled with implies, and
                    # they asked for it gone. The column keeps its space
                    # for the ONE state worth interrupting for: a
                    # rejected stop means real money is open with no
                    # protection, so that shouts.
                    "bracket": ("" if dry or _pos.get("bracket", True)
                                else "NO STOP — RETRYING"),
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
                _pc = _tm_prog_calc(_e, _tp, _sl, _now, _side)
                r["prog_pct"], r["prog_to"] = (_pc if _pc else (None, None))
            out.sort(key=lambda r: r["total $"])
            return out

        # ── THE VIEW. One block of my own markup replaces the System,
        # Performance and Positions bands. Streamlit keeps exactly one job on
        # this screen: the action bar underneath, which is also why there is no
        # longer a button inside a table to misalign.
        st.markdown(MODERN_CSS, unsafe_allow_html=True)

        # 15s, matching the shortest data cache on this screen
        # (_live_open_positions is ttl=10). The bands this view replaced ran at
        # 10s and 20s; when they were removed as duplicates the refresh went
        # with them, and the screen sat still until the operator reloaded.
        @st.fragment(run_every=15)
        def _view() -> None:
            _eq = _an_equity(dry=False)
            _life = _eq[-1][1] if _eq else 0.0
            _day = at.pnl_today(dry=False)["total"]
            _stats = at.strategy_stats(dry=False)
            _open_real = 0.0
            _bits = []
            try:
                for _p in _live_open_positions():
                    _v = float(_p.get("unRealizedPnl") or 0)
                    _open_real += _v
                    _bits.append((str(_p.get("symbol", "")).replace("_USDT", ""), _v))
            except Exception:
                pass
            try:
                _eqty = float((fx.assets().get("USDT") or {}).get("equity") or 0)
            except Exception:
                _eqty = 0.0
            # Read each figure ONCE. fx.assets() was called three times and
            # pnl_today(dry=False) twice while building this one block, and each
            # call is a live round trip to MEXC.
            _usdt = fx.assets().get("USDT") or {}
            _free = float(_usdt.get("availableBalance") or 0)
            _today = at.pnl_today(dry=False)
            _paper_total = sum(float(v.get("pnl") or 0)
                               for v in at.strategy_stats(dry=True).values())
            _real, _paper = _book_rows(False), _book_rows(True)
            _real = [r for r in _real if r.get("state") != "flat"]
            _paper = [r for r in _paper if r.get("state") != "flat"]
            st.markdown(
                "<div class='mv'>"
                + _mv_hero(_eqty, _day, _open_real, _life, _eq,
                           armed=bool(at.runner_pid()) and not at.halted())
                + "<div class='mv-strip'>"
                + f"<div class='mv-cell'><em>{_mv_icon("wallet")}Free margin</em><b>"
                + _ani_money(_free, key="tile.free")
                + "</b><span>uncommitted</span></div>"
                + f"<div class='mv-cell'><em>{_mv_icon("trend")}Open now</em>"
                + f"<b class='{_mv_cls(_open_real)}'>"
                + _ani_money(_open_real, key="tile.open", sign=True) + "</b>"
                + "<span>"
                + (" &middot; ".join(f"{c} {v:+.2f}" for c, v in _bits)
                   if _bits else "no position open") + "</span></div>"
                + f"<div class='mv-cell'><em>{_mv_icon("clock")}Closed today</em>"
                + f"<b class='{_mv_cls(_day)}'>"
                + _ani_money(_day, key="tile.day", sign=True) + "</b>"
                + f"<span>{_today['trades']} trades</span></div>"
                + f"<div class='mv-cell'><em>{_mv_icon("flask")}Paper book</em>"
                + f"<b class='{_mv_cls(_paper_total)}'>"
                + _ani_money(_paper_total, key="tile.paper", sign=True)
                + "</b><span>not real money</span></div>"
                + "</div>"
                + _mv_positions(_real, "Open positions",
                                f"{len(_real)} real &middot; {at.LEVERAGE}x isolated",
                                True)
                + _mv_positions(_paper, "Demo positions",
                                f"{len(_paper)} simulated", False)
                + _mv_strategies(AUTO_STRATEGIES, saved, _stats,
                                 at.STRATEGY_SPECS)
                + "</div>", unsafe_allow_html=True)
            # the only interaction on this screen
            _open_syms = [r["symbol"] for r in _real]
            if _open_syms:
                a1, a2, _a3 = st.columns([2, 1, 5], vertical_alignment="bottom")
                _pick = a1.selectbox("Close a position", _open_syms,
                                     key="mv_close_pick")
                if a2.button("Close at market", key="mv_close_go",
                             use_container_width=True):
                    st.session_state["close_pending"] = _pick
                    st.rerun(scope="fragment")

        with st.container(key="tmsec_view"):
            _view()

        # The System ribbon is GONE. Its six tiles said what the hero and the
        # four readouts above already say — wallet, all-time, today, open,
        # paper, runner — so the screen printed every figure twice, which is
        # what the operator meant by "still messy". `_ribbon` itself is kept
        # unused for now rather than deleted, so nothing else that calls it
        # breaks; it is no longer rendered here.

        # ================= BAND 1b — PERFORMANCE ========================
        # Design 09's defining move: the equity curve is the FIRST object after
        # the status strip, and each panel says what its number means. Both are
        # built from the ledger's own exit rows, so the curve, the bars and the
        # tiles above cannot disagree.
        @st.fragment
        def _performance() -> None:
            _eq = _an_equity(dry=False)
            _live_stats = at.strategy_stats(dry=False)
            _last = _eq[-1][1] if _eq else 0.0
            _peak, _dip = 0.0, 0.0
            for _t, _v in _eq:
                _peak = max(_peak, _v)
                _dip = max(_dip, _peak - _v)
            _worst = min(((v.get("pnl", 0.0), k)
                          for k, v in _live_stats.items() if v.get("trades")),
                         default=(0.0, None))
            _best = max(((v.get("pnl", 0.0), k)
                         for k, v in _live_stats.items() if v.get("trades")),
                        default=(0.0, None))
            _cap = (f"{len(_eq)} closed trades, ending {_last:+,.2f} USDT. "
                    f"Worst dip along the way {_dip:,.2f}.")
            if _worst[1]:
                _cap += (f" {_worst[1]} is the drag at {_worst[0]:+,.2f}"
                         + (f"; {_best[1]} the lift at {_best[0]:+,.2f}."
                            if _best[1] and _best[1] != _worst[1] else "."))
            st.markdown(
                _tm_head("Performance", "real money &middot; from the ledger")
                + "<div class='an-grid'>"
                + "<div class='an-panel'><h4>Equity, every closed trade</h4>"
                + f"<div class='an-cap'>{_cap}</div>"
                + _an_curve(_eq)
                + "<div class='an-legend'>"
                # The swatch takes the CURVE's colour. It was hardcoded green
                # while the curve was coral, because the book is down — a legend
                # that disagrees with the line it labels is the same class of
                # fault as a mislabelled total.
                + f"<span><i style='background:"
                  f"{'var(--t-up)' if _last >= 0 else 'var(--t-dn)'}'></i>"
                  f"realised, cumulative</span>"
                + f"<span><i style='background:var(--t-rule2)'></i>"
                  f"break-even</span></div></div>"
                + "<div class='an-panel'><h4>Lifetime by strategy</h4>"
                + "<div class='an-cap'>Ranked by size, not sign — the biggest "
                  "mover first whichever way it went.</div>"
                + _an_bars(_live_stats)
                + "</div></div>", unsafe_allow_html=True)

        # The Performance band is GONE for the same reason: the equity curve now
        # sits behind the hero number and "lifetime by strategy" is the LIFETIME
        # column of the strategy list. Two charts of one series is not
        # information, it is noise.

        # ================= BAND 2 — POSITIONS ===========================
        @st.fragment(run_every=20)
        def _positions() -> None:
            with st.container(key="tmsec_positions"):
                # ONE table per book. Open positions and per-coin PnL used to be
                # four separate tables; the same contract appeared in two of them
                # with different columns, which read as duplication.
                # _book_rows now lives at tab scope (hoisted 2026-08-20) so the custom view and this band read the SAME rows.

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
                        # vertical_alignment: the row is 44px tall since the
                        # identity cell gained its avatar and sub-line, and a
                        # top-aligned button sat above the text it belongs to.
                        _rc, _bc = st.columns([10, 1.15], gap="small",
                                              vertical_alignment="center")
                        _rc.markdown(f"<div class='tm-pt'>{_tm_pos_row(_r)}</div>",
                                     unsafe_allow_html=True)
                        # Everything the five columns dropped, one click away.
                        with _rc.expander("Detail", expanded=False):
                            st.markdown(_tm_pos_detail(_r),
                                        unsafe_allow_html=True)
                        if _closable:
                            # The coin moved out of the label and into the
                            # tooltip, and the confirm step names the contract in
                            # full before anything is sent — so a bare "Close"
                            # cannot flatten something the operator did not mean.
                            # NOTE: this comment used to claim the row/button
                            # alignment was "asserted at 0px". No such test
                            # existed, which is why it drifted to -7px when the
                            # rows grew to 44px. The CSS now pins the column to
                            # the row height, and scripts/pos_align.mjs measures
                            # it for real.
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
                        # Margin IS summable and it is the number that matters:
                        # how much is at risk in this book right now. It printed
                        # an em dash, which read as "no data".
                        "margin $": round(sum(float(r.get("margin $") or 0)
                                              for r in _rows), 2) or None,
                        # A total has no barriers and no progress of its own.
                        "tp_pct": None, "sl_pct": None, "prog": "",
                        "trades": sum(int(r["trades"]) for r in _rows),
                        "W": sum(int(r["W"]) for r in _rows),
                        "L": sum(int(r["L"]) for r in _rows),
                        "open $": round(sum(r["open $"] or 0 for r in _rows), 2)}
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

            with st.container(key="tmsec_history"):
                # ---- TRADE HISTORY. Its own section, LIVE and DEMO on
                # separate tabs, paginated 5 rows at a time. Every closed trade,
                # not just today's — a net figure hides the trades inside it, and
                # a wall of 200 rows hides them just as effectively.
                st.markdown(
                    _tm_head("Trade history", "every closed trade"),
                    unsafe_allow_html=True)
                _hcols = (("when", "closed", 1.6, "l", "text"),
                          ("coin", "coin", 1.1, "l", "text"),
                          ("side", "side", 0.9, "l", "text"),
                          ("strategy", "strategy", 1.9, "l", "text"),
                          ("why", "closed by", 1.9, "l", "text"),
                          ("PROFIT $", "PROFIT $", 1.3, "r", "money"),
                          ("run", "running $", 1.3, "r", "money"))
                _tl, _td = st.tabs(["LIVE — real money", "DEMO — simulated"])
                for _tab, _dry, _tag in ((_tl, False, "live"), (_td, True, "demo")):
                    with _tab:
                        _ex = [e for e in at.ledger_tail(100000)
                               if e.get("action") == "exit"
                               and bool(e.get("dry_run")) is _dry]
                        _ex.sort(key=lambda x: float(x.get("ts") or 0))
                        _run = 0.0
                        _all = []
                        for _e in _ex:
                            _p = round(float(_e.get("pnl_est") or 0), 2)
                            _run = round(_run + _p, 2)
                            _all.append({
                                "when": _dt.datetime.fromtimestamp(
                                    float(_e.get("ts") or 0)).strftime("%m-%d %H:%M"),
                                "coin": str(_e.get("symbol", "?")).replace("_USDT", ""),
                                "side": (_e.get("side") or "—"),
                                "strategy": _e.get("strategy") or "—",
                                "why": (_e.get("why") or "—"),
                                "PROFIT $": _p, "run": _run})
                        _all.reverse()          # newest first
                        # ---- per-month summary. The paginated list shows five
                        # trades; this is the overview it cannot give.
                        _mo = {}
                        for _e in _ex:
                            _k = _dt.datetime.fromtimestamp(
                                float(_e.get("ts") or 0)).strftime("%Y-%m")
                            _p = round(float(_e.get("pnl_est") or 0), 2)
                            _m = _mo.setdefault(_k, {"month": _k, "trades": 0,
                                                     "W": 0, "L": 0,
                                                     "PROFIT $": 0.0})
                            _m["trades"] += 1
                            _m["W" if _p > 0 else "L"] += 1
                            _m["PROFIT $"] = round(_m["PROFIT $"] + _p, 2)
                        _mrows = sorted(_mo.values(), key=lambda x: x["month"],
                                        reverse=True)
                        for _m in _mrows:
                            _m["win %"] = round(100 * _m["W"] / _m["trades"], 1)
                        _mcols = (("month", "month", 1.4, "l", "text"),
                                  ("trades", "trades", 1.0, "r", "num"),
                                  ("W", "W", 0.8, "r", "num"),
                                  ("L", "L", 0.8, "r", "num"),
                                  ("win %", "win %", 1.0, "r", "num"),
                                  ("PROFIT $", "PROFIT $", 1.4, "r", "money"))
                        _mtot = {"month": "TOTAL",
                                 "trades": sum(m["trades"] for m in _mrows),
                                 "W": sum(m["W"] for m in _mrows),
                                 "L": sum(m["L"] for m in _mrows),
                                 "win %": None,
                                 "PROFIT $": round(sum(m["PROFIT $"]
                                                       for m in _mrows), 2)}
                        st.markdown(
                            "<div style='font-size:10px;letter-spacing:.14em;"
                            "text-transform:uppercase;color:var(--t-dim);"
                            "margin:2px 0 4px'>Profit per month</div>"
                            + _tm_table(_mcols, _mrows,
                                        _mtot if _mrows else None,
                                        "no closed trades yet"),
                            unsafe_allow_html=True)
                        st.markdown(
                            "<div style='font-size:10px;letter-spacing:.14em;"
                            "text-transform:uppercase;color:var(--t-dim);"
                            "margin:14px 0 4px'>Every trade</div>",
                            unsafe_allow_html=True)
                        _per = 10
                        _pages = max(1, -(-len(_all) // _per))
                        _pk = f"hist_page_{_tag}"
                        _pg = int(st.session_state.get(_pk, 1))
                        _pg = max(1, min(_pg, _pages))
                        _slice = _all[(_pg - 1) * _per:_pg * _per]
                        # The TOTAL is over EVERY trade, not the five on screen —
                        # a footer that summed the page would change as you paged.
                        _wins = sum(1 for r in _all if r["PROFIT $"] > 0)
                        _tot = {"when": "TOTAL", "coin": "", "side": "",
                                "strategy": f"{len(_all)} trades",
                                "why": f"{_wins}W / {len(_all) - _wins}L",
                                "PROFIT $": round(sum(r["PROFIT $"] for r in _all), 2),
                                "run": None}
                        st.markdown(
                            _tm_table(_hcols, _slice, _tot if _all else None,
                                      "no closed trades yet"),
                            unsafe_allow_html=True)
                        if _pages > 1:
                            _nums = _page_numbers(_pg, _pages)
                            # Narrow number columns hugging the left, one wide
                            # filler to the right. Equal weights spread eight
                            # buttons across the whole table width, which read
                            # as scattered controls rather than one pager.
                            _pcols = st.columns([1] * len(_nums) +
                                                [3 * len(_nums)], gap="small")
                            # Numbered pages, on the operator's ask. `newer`
                            # and `older` said which DIRECTION they moved but
                            # never how far there was to go, and jumping to
                            # page 9 of 14 took eight clicks.
                            for _i, _num in enumerate(_nums):
                                _c = _pcols[_i]
                                if _num is None:
                                    _c.markdown(
                                        "<div style='text-align:center;"
                                        "font-size:11px;color:var(--t-faint);"
                                        "padding-top:7px'>&hellip;</div>",
                                        unsafe_allow_html=True)
                                elif _num == _pg:
                                    _c.markdown(
                                        f"<div class='tm-pg-on'>{_num}</div>",
                                        unsafe_allow_html=True)
                                elif _c.button(str(_num),
                                               key=f"{_pk}_p{_num}"):
                                    st.session_state[_pk] = _num
                                    st.rerun(scope="fragment")
                            st.markdown(
                                f"<div style='font-size:10.5px;"
                                f"color:var(--t-dim);margin-top:2px'>page "
                                f"{_pg} of {_pages} &middot; showing "
                                f"{(_pg-1)*_per+1}-"
                                f"{min(_pg*_per, len(_all))} of {len(_all)} "
                                f"trades</div>", unsafe_allow_html=True)


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

        # The old positions band is GONE — the view renders both books with the
        # same rows from the same `_book_rows`. Its per-row detail disclosure is
        # the one thing it had that the view does not; that is the next thing to
        # port, and it is listed as such rather than left as a duplicate table.


        # ================= BAND 3 — STRATEGY ============================
        # Progressive disclosure (ui-ux-pro-max priority table §8 — the ux
        # search returned no rule for this, so it is the built-in guidance, not
        # a database match). The clean strategy LIST is the default reading; the
        # fourteen-column control grid is configuration, which you open when you
        # intend to change something. Before this they rendered one above the
        # other, so every strategy appeared twice on one screen.
        with st.expander("Configure strategies  ·  arm, size, loss cap, backtest",
                         expanded=False):
          with st.container(key="tmsec_strategy"):
            try:
                contracts = _futures_contracts()
                symbols = sorted(c["symbol"] for c in contracts)
            except Exception as exc:
                symbols = []
                st.warning(f"Could not fetch the MEXC contract list ({exc}); "
                           "showing saved selections only.")
            saved_strats = saved.get("strategies", ["ict_fvg"])
            # `strategy_coins` and `coins` are still WRITTEN — the runner
            # reads them — but never read back into this table. The contract
            # is part of the strategy, fixed by the tile that defines it.
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
            # STREAK carries "3 loss · PI" now, so it needs the width the
            # ladder can spare — a clipped "3 loss · P" is the label bug the
            # column was widened to fix.
            # STRATEGY carries the operator's own row name now, so it takes
            # the width the ladder can spare.
            _W = [2.0, 1.3, .62, .62, .95, .95, 1.15, 1.75, .9, .95, 1.0,
                  .95, 1.0, 1.05]
            _HEADS = ("strategy", "contracts", "LIVE", "DEMO", "base $",
                      "notional $", "streak", f"ladder $ · {'flat' if _flat else 'DEEP'}",
                      "next $", "SL / TP", "loss cap $", "W / L", "PROFIT $",
                      "backtest")

            _head_slot = st.empty()
            st.caption(
                "One row per strategy. LIVE places real orders on MEXC, DEMO "
                "simulates fills in a separate book — independent, so a strategy "
                "can run both, one, or neither. Contracts are fixed per "
                "strategy — a row is one signal on one coin, backtested "
                "together — and a row whose coin another row already trades LIVE "
                "cannot go live too, because MEXC nets them into one position. "
                "DEMO is never locked, so two timeframes on one coin can be "
                "papered side by side. Base margin and loss cap are typed in "
                "place; press Save & run to commit them. "
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

            # ---- ONE TIMEFRAME PER COIN ON REAL MONEY, enforced where the choice
            # is MADE. Contracts are fixed per row, so the only way to double-book
            # a coin is to tick a SECOND row that carries it; that row's LIVE box
            # is disabled and forced off while the first row holds the coin.
            # DEMO is deliberately NOT locked — the operator asked to paper PI on
            # 30m and 1h at once to compare them, and a simulated book has no MEXC
            # position for the two to fight over. The save-time guard further down
            # applies the same live-only rule as the backstop.
            # The first live tile in AUTO_STRATEGIES wins the coin, so moving PI
            # means unticking the row that holds it — a visible, deliberate act.
            def _row_live(_k: str) -> bool:
                _lv = st.session_state.get(f"g_live_{_k}")
                if _lv is None:
                    return False in (at.books_for(_k, saved)
                                     if _k in saved_strats else [])
                return bool(_lv)

            _locked = _timeframe_locks(
                [(k, list(dc)) for k, _, _, dc in AUTO_STRATEGIES],
                at.STRATEGY_SPECS, _row_live)
            for key, _label_raw, note, default_coins in AUTO_STRATEGIES:
                label = _strategy_label(key, _label_raw)
                _spec = at.STRATEGY_SPECS.get(key, {})
                _bks = at.books_for(key, saved) if key in saved_strats else []
                # The contract is part of the strategy, not a saved preference:
                # #3M3CRXP8 IS trend50 / 30m / TP 2.5 / SL 2.0 *on PI*. So the row
                # always shows its own contract and the saved copy is ignored —
                # which is what killed the "contracts: none" row, left behind when
                # PI moved off mom15_4h_w and its saved list was emptied to [].
                _coins = list(default_coins)
                _lock = _locked.get(key)
                _mgs = float(saved_margins.get(key) or 5.0)
                # The LOSING STREAK is the ladder's own counter: it advances on a
                # loss and resets to zero on a win, so it IS the streak, and it is
                # what decides the next stake. Read per contract, worst one wins.
                #
                # It belongs to the COIN AND BOOK, not to this strategy — the
                # state key is `PI_USDT` live and `PI_USDT#paper` on demo — so a
                # new strategy on a coin inherits whatever streak the previous one
                # left, and really will stake that rung on its first trade. Two
                # corrections here: read the book this row trades (a demo-only row
                # was printing the LIVE ladder), and say whose streak it is.
                _bk = "" if (False in _bks or not _bks) else "#paper"
                _streak = max((int((_runstate.get(c + _bk) or {}).get("step", 0) or 0)
                               for c in _coins), default=0)
                c = st.columns(_W, gap="small", vertical_alignment="center")
                _tag = _TILE_TAGS.get(key)
                c[0].markdown(
                    f"<div style='{_cell};overflow:visible'>{_tm_sig(key)}"
                    f"<span style='color:var(--t-faint)'> {_tm_tf(_spec)}</span>"
                    + (f"<span style='color:var(--t-amber);font-size:10px;"
                       f"margin-left:6px'>{html.escape(_tag)}</span>" if _tag else "")
                    + "</div>", unsafe_allow_html=True)
                # Contracts are NOT typed. Each row is one strategy chosen FOR a
                # specific contract — #3M3CRXP8 is trend50/30m/2.5/2.0 *on PI*, and
                # the same signal on another coin is a different, untested
                # combination (CLAUDE.md rule 21: sizing and coin are part of the
                # strategy, not dials turned afterwards). An editable box invited
                # exactly that edit, so the column now renders what is configured.
                _shown = ", ".join(x.replace("_USDT", "") for x in _coins)
                c[1].markdown(
                    f"<div style='{_cell}'>"
                    + (f"<b>{_shown}</b>" if _shown else
                       "<span style='color:var(--t-faint)'>none</span>")
                    + (f"<span style='color:var(--t-faint)'> &middot; live on "
                       f"{_tm_tf(at.STRATEGY_SPECS.get(_lock[1], {}))}</span>"
                       if _lock else "")
                    + "</div>", unsafe_allow_html=True)
                _why = None
                if _lock:
                    # A ticked LIVE box on a locked row is un-ticked BEFORE the
                    # widget is rebuilt — Streamlit refuses the write afterwards,
                    # and a disabled box that stays green is a false label.
                    if st.session_state.get(f"g_live_{key}"):
                        st.session_state[f"g_live_{key}"] = False
                    _why = (f"{_lock[0].replace('_USDT', '')} already trades REAL "
                            f"money on {_tm_tf(at.STRATEGY_SPECS.get(_lock[1], {}))} "
                            f"candles ({_tm_sig(_lock[1])}). MEXC nets both into ONE "
                            f"position, so the second entry resizes the first and "
                            f"either stop closes part of a trade it does not own. "
                            f"DEMO is still free — paper both and compare. Untick "
                            f"that row's LIVE to free "
                            f"{_lock[0].replace('_USDT', '')}.")
                _live = c[2].checkbox("LIVE", value=(False in _bks) and not _lock,
                                      key=f"g_live_{key}", disabled=bool(_lock),
                                      label_visibility="collapsed",
                                      help=_why or "REAL money — sends orders to MEXC.")
                _demo = c[3].checkbox("DEMO", value=True in _bks,
                                      key=f"g_demo_{key}",
                                      label_visibility="collapsed",
                                      help="Simulated fills, separate book, no real "
                                           "orders. Never locked — two timeframes on "
                                           "one coin can be papered side by side.")
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
                # NAME whose streak it is. `3 loss` on a strategy row reads as
                # "this strategy lost 3" — trend50 had not traded at all; the 3
                # was PI's own ladder, left by mom15_4h_w, and it is what the
                # NEXT $ column is computed from.
                _who = ", ".join(x.replace("_USDT", "") for x in _coins) or "—"
                c[6].markdown(
                    f"<div style='{_cell}' class='{_scol}' title='Ladder step for "
                    f"{_who} on the {'demo' if _bk else 'live'} book. It belongs "
                    f"to the contract, not to this strategy: a strategy taking "
                    f"over a coin inherits the streak and stakes that rung.'>"
                    f"<b>{_streak}</b>"
                    f"<span style='color:var(--t-faint)'> loss &middot; {_who}"
                    f"</span></div>",
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

                # Still validated, because a saved settings file can name a
                # contract MEXC has since delisted. Read-only is not unchecked.
                _known = set(symbols)
                _cs = [x for x in _coins if not _known or x in _known]
                _bad_syms.extend(x for x in _coins if _known and x not in _known)
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
                         f"{_n_off} off"
                         + (f" &middot; {len(_locked)} live-locked" if _locked else "")
                         + f" &middot; {len(AUTO_STRATEGIES)} loaded"),
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
                _lbl = {k: _strategy_label(k, l) for k, l, *_ in AUTO_STRATEGIES}
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

            # The legacy union is the runner's fallback, so it must follow the
            # ARMED rows only. Built from every row, a locked or off row's
            # contract joined it and a coin nothing trades looked selected.
            chosen_coins = list(dict.fromkeys(
                c for k in chosen_strats for c in strategy_coins.get(k, [])))

        # ================= BAND 4 — RISK ================================
        with st.expander("Risk  ·  sizing, books in use, account loss cap",
                         expanded=False):
          with st.container(key="tmsec_risk"):
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
                # One timeframe per coin, refused at the point of saving. The
                # runner also refuses (auto_trader.timeframe_conflicts), but a
                # config that cannot legally run should never reach the disk: MEXC
                # nets same-symbol positions into one, so two strategies on a coin
                # at different bar sizes resize each other's trade and either stop
                # closes part of a position it does not own.
                _probe = {"strategies": chosen_strats,
                          "strategy_coins": {k: strategy_coins.get(k, [])
                                             for k in chosen_strats},
                          # Without the book map, books_for() falls back to the
                          # global switches and reads every strategy as live —
                          # which would refuse the save for two PAPER timeframes
                          # on one coin, the exact thing the operator asked for.
                          "strategy_books": {k: v for k, v in strategy_books.items()
                                             if v}}
                _clashes = at.timeframe_conflicts(_probe)
                if _clashes:
                    for _c in _clashes:
                        st.error(
                            f"**{_c['coin']} is LIVE on two timeframes at once** "
                            f"({' and '.join(_c['timeframes'])}, via "
                            f"{', '.join(_c['strategies'])}). MEXC nets them into one "
                            f"position, so one coin trades real money on one timeframe "
                            f"— untick all but one LIVE box, then save again. DEMO is "
                            f"unaffected. Nothing was written.")
                    st.stop()
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
                    + ("".join(f"<div>{html.escape(_fmt_log_line(l))}</div>"
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

        with st.expander("Feed  ·  runner log and every event",
                         expanded=False):
          with st.container(key="tmsec_feed"):
            _feed()

        # ================= BAND 7 — CONNECTION ==========================
        with st.expander("Connection  ·  MEXC keys and permissions",
                         expanded=False):
          with st.container(key="tmsec_connection"):
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



# ---------------------------------------------------------------------------
# Back Test — the market-wide sweep, and its REFRESH.
#
# The first run measures a year for every eligible contract. A refresh does not
# repeat it: candles are cached and only the new tail is fetched, and every
# combination's backtest is CONTINUED from the state the engine handed back, so
# only the new bars are tested. Verified exact — continuing a split run
# reproduces a single-pass run trade-for-trade (tests/test_market_sweep.py).
# ---------------------------------------------------------------------------
BT_ALL_PAGE = BT_REPORT_DIR / "all-coins.html"


def _bt_eligible(min_days: int = 365) -> list[str]:
    """Contracts at least `min_days` old, cheapest book first. Cached a day."""
    import json as _json

    f = Path(os.path.expanduser("~/.tradingagents/backtest/eligible.json"))
    try:
        d = _json.loads(f.read_text())
        if d.get("day") == _dt.date.today().isoformat():
            return d["symbols"]
    except (OSError, ValueError, KeyError):
        pass
    from tradingagents.dataflows import mexc_futures as fx
    from tradingagents import auto_trader as at

    raw = fx._get_public(f"{fx.BASE}/api/v1/contract/detail").get("data") or []
    syms = sorted(x["symbol"] for x in raw
                  if str(x.get("symbol", "")).endswith("_USDT")
                  and int(x.get("state", 1)) == 0)
    keep = []
    bar = st.progress(0.0, text="finding contracts a year old…")
    for i, sym in enumerate(syms, 1):
        try:
            d = fx.klines(sym, "Day1", 500)
            if (d["Date"].iloc[-1] - d["Date"].iloc[0]).days >= min_days:
                c = fx.book_cost(sym, 100.0)
                rt = 2 * (at.taker_fee(sym, fx=fx)
                          + float(c.get("spread") or 0) / 2
                          + float(c.get("slippage") or 0))
                keep.append((rt, sym))
        except Exception:
            pass
        if i % 20 == 0:
            bar.progress(i / len(syms),
                         text=f"{i}/{len(syms)} screened · {len(keep)} eligible")
    bar.empty()
    keep.sort()
    out = [s2 for _rt, s2 in keep]
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(_json.dumps({"day": _dt.date.today().isoformat(),
                              "symbols": out}))
    return out


def _bt_build_page(rows: list) -> tuple[str, str] | None:
    """Render the stored grid as the standard page."""
    from tradingagents import backtest_report as br
    from tradingagents import market_sweep as msw

    if not rows:
        return None
    months = sorted({m for r in rows for m in (r.get("monthly") or {})},
                    reverse=True)
    for r in rows:
        r["mon"] = [(r.get("monthly") or {}).get(m) for m in months]
        r.pop("monthly", None)
        r["id"] = br.row_code(r["coin"], r["tf"], r["signal"], r["th"],
                              r["sl"], r["tp"], r["sizing"])
        r.setdefault("tpd", round(r["trades"] / max(r.get("days", 1), 1), 2))
    meta = {}
    for r in rows:
        meta.setdefault(f"{r['coin']}|{r['tf']}",
                        {"bars": r.get("bars", 0), "days": r.get("days", 0),
                         "rt": r.get("rt"), "liq": 0.0, "fee": 0.0})
    cov = msw.coverage()
    payload = {"rows": rows, "meta": meta, "series": {}, "months": months,
               "cur": months[0] if months else "", "lev": 20, "slip": 0.0003,
               "base": rows[0].get("base", 5.0),
               "ladder": [1, 1, 2, 2, 4, 4, 8], "deployed": [],
               "excluded": [], "days_asked": 365,
               "fetched": cov.get("last_bar") or "",
               "rec_min_trades": 300, "rec_min_days": 300, "card_cap": 8}
    BT_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    br.write_report(
        str(BT_ALL_PAGE), payload,
        title="Back Test — Every MEXC Coin a Year Old",
        note=(f"<b>{cov['coins']} contracts, {cov['pairs']} coin/timeframe "
              f"pairs, {len(rows)} rows.</b> Candles are cached, so a refresh "
              f"fetches only the bars printed since the last run and CONTINUES "
              f"each backtest rather than repeating the year. Newest bar "
              f"measured: {cov.get('last_bar') or 'n/a'}. Trade-by-trade replay "
              f"is not embedded on this market-wide page — run a single coin "
              f"from Auto Trade for that."))
    return f"app/static/bt/{BT_ALL_PAGE.name}", BT_ALL_PAGE.name


@st.fragment(run_every=15)
def _bt_cloud_panel() -> None:
    """A GitHub run, watched from here — and pulled into the local store the
    moment it finishes, so the operator never touches github.com."""
    import pandas as pd

    from tradingagents import cloud_sweep as cs
    from tradingagents import market_sweep as msw

    run = st.session_state.get("bt_cloud_run") or cs.remembered()
    if not run:
        return
    try:
        stt = cs.status(run["id"], run.get("repo"))
    except Exception as exc:
        st.caption(f"GitHub run {run['id']}: cannot read status ({exc})")
        return
    done, total = stt["shards_done"], max(stt["shards"], 1)
    st.markdown("<div style='font-size:10px;letter-spacing:.16em;"
                "text-transform:uppercase;color:#C2560B;margin:14px 0 2px'>"
                f"GitHub run #{run['id']}</div>", unsafe_allow_html=True)
    if stt.get("waiting_for_runners"):
        st.warning("Waiting for a free machine — every GitHub runner is busy. "
                   "A free repository gets about 20 at once, so another sweep "
                   "of yours is holding them. Stop that one to start this now.")
    else:
        st.caption(f"{done} of {total} machines finished · "
                   f"{stt.get('running', 0)} still testing · "
                   f"{stt.get('queued', 0)} not started"
                   + (f" · {stt['failed']} failed" if stt["failed"] else ""))

    # What each machine SAYS it is doing — the shards publish this themselves,
    # because GitHub serves no log for a job that is still running.
    live = {}
    try:
        for d in cs.live_progress(run["id"], run.get("repo")):
            live[int(d.get("shard", -1))] = d
    except Exception:
        live = {}
    if live:
        tot_done = sum(d.get("done", 0) for d in live.values())
        tot_all = sum(d.get("total", 0) for d in live.values())
        rows_now = sum(d.get("rows", 0) for d in live.values())
        if tot_all:
            st.progress(min(1.0, tot_done / tot_all),
                        text=(f"{100 * tot_done / tot_all:.0f}% · "
                              f"{tot_done} of {tot_all} contracts · "
                              f"{rows_now:,} rows found so far"))

    # One row per machine, because "0 of 20 finished" answers nothing about
    # where the work actually is.
    jobs = stt.get("jobs") or []
    if jobs:
        now = _dt.datetime.now(_dt.timezone.utc)

        def _stamp(v):
            """GitHub returns 0001-01-01T00:00:00Z for "hasn't happened yet".
            Parsed naively that reads as two thousand years, which is how the
            table showed "-1065379229 min"."""
            if not v or v.startswith("0001-01-01"):
                return None
            try:
                return _dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
            except ValueError:
                return None

        def _mins(a, b=None):
            t0 = _stamp(a)
            if t0 is None:
                return ""
            t1 = _stamp(b) or now
            m = (t1 - t0).total_seconds() / 60
            return f"{m:.0f} min" if m >= 0 else ""

        rows = []

        def _num(x):
            m = re.search(r"\((\d+)\)", x["name"])
            return int(m.group(1)) if m else 999

        for j in sorted(jobs, key=_num):
            state = ("finished" if j["status"] == "completed"
                     else "testing" if j["status"] == "in_progress"
                     else "waiting")
            if j.get("conclusion") == "failure":
                state = "FAILED"
            # "sweep (7)" -> "#7", and a step name carries GitHub's internal
            # id ("Sweep shard 7-1065379229") which means nothing here
            num = re.search(r"\((\d+)\)", j["name"])
            step = re.sub(r"-\d{6,}$", "", (j.get("step") or "")).strip()
            sid = int(num.group(1)) if num else -1
            rep = live.get(sid) or {}
            stage = {"screening": "checking ages",
                     "testing": "analysing",
                     "done": "done"}.get(rep.get("stage"), "")
            rows.append({
                "machine": f"#{sid}" if sid >= 0 else j["name"],
                "state": state,
                "stage": stage or (step or
                                   ("done" if state == "finished" else "queued")),
                "%": (f"{rep['pct']:.0f}%" if rep.get("pct") is not None
                      else ""),
                "on": rep.get("note", ""),
                "rows": rep.get("rows", ""),
                "running for": _mins(j.get("startedAt"), j.get("completedAt")),
            })
        st.dataframe(pd.DataFrame(rows), width="stretch", height=260,
                     hide_index=True)
        st.caption("Each machine reports its own stage and percentage every "
                   "45 seconds — 'checking ages' is picking which contracts "
                   "have a year of history, 'analysing' is the backtesting.")

    st.markdown(f"<a class='bt-open' href='{stt['url']}' target='_blank' "
                f"rel='noopener'>WATCH ON GITHUB &#8599;</a>"
                f"<span class='bt-open-note'>run #{run['id']} · started "
                f"{run.get('started', '')}</span>", unsafe_allow_html=True)
    s1, s2 = st.columns([1, 5])
    if stt["status"] != "completed":
        if s1.button("STOP RUN", key=f"bt_cloud_stop_{run['id']}"):
            try:
                cs.cancel(run["id"], run.get("repo"))
                cs.forget()
                st.session_state.pop("bt_cloud_run", None)
                st.warning("Cancelled on GitHub. The machines stop now.")
            except Exception as exc:
                st.error(f"Could not cancel: {exc}")
    elif s1.button("DISMISS", key=f"bt_cloud_hide_{run['id']}"):
        cs.forget()
        st.session_state.pop("bt_cloud_run", None)
        st.rerun()
    if stt["status"] == "completed" and not st.session_state.get(
            f"bt_pulled_{run['id']}"):
        with st.spinner("Downloading results from GitHub…"):
            try:
                rows = cs.fetch(run["id"], run.get("repo"))
                got = cs.merge_into_store(rows)
                st.session_state[f"bt_pulled_{run['id']}"] = True
                st.session_state.pop("bt_all_page", None)
                cs.forget()
                st.success(f"Pulled {got['rows']:,} rows covering "
                           f"{got['coins']} coins from GitHub.")
            except Exception as exc:
                st.error(f"Run finished but the results could not be "
                         f"downloaded: {exc}")


@st.fragment(run_every=5)
def _bt_progress_panel() -> None:
    """Redraws itself every 5 seconds while a sweep runs, without touching the
    rest of the page — a market sweep is hours, and the operator should not
    have to click to see where it is."""
    from tradingagents import market_sweep as msw

    prog = msw.progress()
    if prog:
        running = msw.is_running()
        st.markdown("<div style='font-size:10px;letter-spacing:.16em;"
                    "text-transform:uppercase;color:var(--faint);margin:14px 0 2px'>"
                    "This Mac</div>", unsafe_allow_html=True)
        pct = prog["done"] / max(prog["total"], 1)
        phase = prog.get("phase", "sweeping")
        unit = "contracts screened" if phase == "screening" else "jobs"
        st.progress(min(1.0, pct),
                    text=(f"{prog['done']}/{prog['total']} {unit} · "
                          + (f"{prog['rows']:,} rows · "
                             if phase != "screening" else "")
                          + (f"ETA {prog.get('eta_min')} min · "
                             if running and prog.get("eta_min") is not None
                             else "")
                          + (prog.get("last") or "")))
        cols = st.columns(4)
        cols[0].caption(f"started {prog.get('started', '—')}")
        cols[1].caption(f"{prog.get('workers', '—')} workers")
        cols[2].caption(f"{prog.get('new_bars', 0):,} new bars tested")
        cols[3].caption("RUNNING" if running
                        else f"finished {prog.get('finished', '—')}")
        r1, r2 = st.columns([1, 5])
        if running and r1.button("STOP THIS MAC", key="bt_stop"):
            msw.stop()
            st.warning("Stop signalled — the current jobs finish, then it exits.")
        if r2.button("Refresh this view", key="bt_poll"):
            st.session_state.pop("bt_all_page", None)
            st.rerun()


def render_db_dashboard_section() -> None:
    """How full the Neon database is: measured size against the plan limit,
    and each table's share. The percent is derived, never guessed."""
    import pandas as pd
    from tradingagents.dataflows import market_db as mdb

    st.markdown('<div class="ta-section">Database — storage used</div>',
                unsafe_allow_html=True)
    if not mdb.available():
        st.caption("No database configured.")
        return
    stats = mdb.storage_stats()
    if stats is None:
        st.caption("Database unreachable right now — the app retries by "
                   "itself within 2 minutes.")
        return
    used_mb = stats["db_bytes"] / 1048576
    limit_mb = stats["limit_bytes"] / 1048576
    pct = stats["percent"]
    st.progress(min(pct / 100, 1.0),
                text=f"{pct:g}% used — {used_mb:,.1f} MB of {limit_mb:,.0f} "
                     "MB (Neon plan limit)")
    if pct >= 80:
        st.warning(f"Over 80% full. At 100% Neon refuses new writes — "
                   f"{limit_mb - used_mb:,.0f} MB left. Delete unused "
                   "coins/timeframes or upgrade the plan.")
    c = st.columns(3)
    c[0].metric("Size now", f"{used_mb:,.1f} MB")
    c[1].metric("Free", f"{limit_mb - used_mb:,.1f} MB")
    c[2].metric("Plan limit", f"{limit_mb:,.0f} MB")
    rows = [{
        "table": t["table"],
        "size MB": round(t["bytes"] / 1048576, 2),
        "share of used": f"{100 * t['bytes'] / max(stats['db_bytes'], 1):.1f}%",
        "rows (estimate)": t["rows"],
    } for t in stats["tables"]]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("Size as Postgres reports it (pg_database_size). Row counts "
               "are the planner's live estimate, not an exact count. Limit "
               f"is {limit_mb:,.0f} MB — override with \"size_limit_mb\" in "
               "~/.tradingagents/neon_db.json if the plan changes.")


def render_market_data_section() -> None:
    """The permanent candle archive on Neon: download once, update the tail,
    and every backtest reads from it instead of re-paging MEXC."""
    import pandas as pd
    from tradingagents.dataflows import market_db as mdb
    from tradingagents import auto_trader as at

    st.markdown('<div class="ta-section">Market data — permanent archive '
                '(Neon Postgres)</div>', unsafe_allow_html=True)
    if not mdb.available():
        st.info("No database configured. Put the connection URL in "
                "~/.tradingagents/neon_db.json as {\"url\": \"postgresql://…\"} "
                "or export TRADINGAGENTS_DB_URL.")
        return

    coins = (at.load_settings().get("coins") or [])
    _all = _all_mexc_symbols()
    coin_opts = coins + [s for s in sorted(_all) if s not in coins]
    c1, c2, c3, c4 = st.columns([2, 1, 1, 1], vertical_alignment="bottom")
    coin_sel = c1.multiselect(
        "Coins", coin_opts, default=[], key="mdb_coins",
        help=f"All {len(coin_opts)} MEXC USDT perpetuals — pick any set, or "
             "use the list's Select all. Defaults to your configured coins.")
    # With hundreds of chips on screen, the one thing the operator cannot see
    # is how many they picked.
    c1.caption(f"**{len(coin_sel)}** of {len(coin_opts)} coins selected"
               if coin_sel else f"none of {len(coin_opts)} coins selected")
    tf_sel = c2.multiselect("Timeframes", list(mdb.TIMEFRAMES),
                            default=list(mdb.TIMEFRAMES), key="mdb_tfs")
    dl = c3.button("DOWNLOAD", key="mdb_download", use_container_width=True,
                   disabled=not (coin_sel and tf_sel),
                   help="Fetch everything MEXC serves for the selection and "
                        "store it permanently. Re-running only adds what is "
                        "missing.")
    up = c4.button("UPDATE", key="mdb_update", use_container_width=True,
                   disabled=not (coin_sel and tf_sel),
                   help="Fetch only candles newer than the archive's last "
                        "bar for the selection.")
    where = st.radio(
        "Run where", ["This Mac", "GitHub (free machines)"], horizontal=True,
        key="mdb_where",
        help="GitHub runs it on 10 of their machines and writes straight to "
             "the database — your Mac stays free. Results appear in the "
             "coverage table as shards finish.")

    if (dl or up) and where.startswith("GitHub"):
        from tradingagents import cloud_jobs as cj
        _ok, _slug = cj.available()
        if not _ok:
            st.error(f"GitHub unavailable — {_slug}. Run on This Mac instead.")
            return
        _everything = len(coin_sel) >= len(coin_opts)
        try:
            run = cj.dispatch("download.yml", {
                "coins": "ALL" if _everything else ",".join(coin_sel),
                "timeframes": ",".join(tf_sel),
                "shards": str(min(10, max(1, len(coin_sel) // 5 or 1))),
            })
            st.success(f"Started on GitHub — run #{run['id']}. Candles land "
                       "in the database as each machine finishes; re-open "
                       "this tab later and the coverage table will have "
                       "grown.")
            st.markdown(f"[Watch the run]({run['url']})")
        except Exception as exc:
            st.error(f"Could not start on GitHub: {exc}")
        return

    from tradingagents import db_jobs
    if dl or up:
        symbols = list(coin_sel)
        if len(symbols) > 50:
            st.warning(f"{len(symbols)} contracts x {len(tf_sel)} "
                       "timeframe(s) — a first download this size takes "
                       "hours and can outgrow the database plan. It keeps "
                       "whatever finishes.")
        db_jobs.start("download", {"coins": symbols, "tfs": list(tf_sel)})
        st.rerun()

    # A running job renders its live progress + STOP, whoever started it.
    _dj = db_jobs.status("download")
    if _dj.get("running"):
        done, total = _dj.get("done", 0), max(_dj.get("total", 0), 1)
        st.progress(min(done / total, 1.0),
                    text=f"Downloading {_dj.get('now', '…')} — {done}/{total} "
                         f"pairs, {_dj.get('bars_stored', 0):,} bars stored")
        s1, s2 = st.columns([1, 5])
        if s1.button("STOP DOWNLOAD", key="mdb_stop"):
            db_jobs.request_stop("download")
            st.warning("Stop signalled — the current pair finishes, then it "
                       "exits. Everything downloaded so far is kept.")
        if s2.button("Refresh progress", key="mdb_poll"):
            st.rerun()
    elif _dj.get("finished"):
        _msg = (f"Last download: {_dj.get('bars_stored', 0):,} bars, "
                f"{_dj.get('done', 0)}/{_dj.get('total', 0)} pairs"
                + (f" — {_dj['note']}" if _dj.get("note") else "")
                + (f" — first error: {_dj['first_error']}"
                   if _dj.get("first_error") else ""))
        (st.warning if _dj.get("stopped") or _dj.get("errors")
         else st.caption)(_msg)

    cov = mdb.coverage()
    if not cov:
        # An unreachable database must never read as an empty one — "empty"
        # on a network blip would say your data is gone when it isn't.
        if mdb.is_down():
            st.caption("Database unreachable right now — the app retries "
                       "by itself within 2 minutes. Your data is intact.")
        else:
            st.caption("Archive is empty — pick a coin and click DOWNLOAD.")
        return
    label_of = {v: k for k, v in mdb.TIMEFRAMES.items()}
    rows = [{
        "coin": c["symbol"].replace("_USDT", ""),
        "timeframe": label_of.get(c["timeframe"], c["timeframe"]),
        "bars": c["bars"],
        "from": _dt.datetime.fromtimestamp(c["first_ts"])
                   .strftime("%Y-%m-%d"),
        "to": _dt.datetime.fromtimestamp(c["last_ts"])
                 .strftime("%Y-%m-%d %H:%M"),
        "days": round((c["last_ts"] - c["first_ts"]) / 86400),
    } for c in cov]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption(f"{sum(r['bars'] for r in rows):,} candles stored across "
               f"{len(rows)} coin/timeframe pairs. Every long fetch anywhere "
               "in the app also tops this archive up automatically.")


_BT_WINDOWS = {"Previous month": 30, "Previous 3 months": 90,
               "Previous 6 months": 180, "Previous 1 year": 365}


@st.cache_data(ttl=3600, show_spinner=False)
def _all_mexc_symbols() -> list[str]:
    """Every tradeable USDT perpetual on MEXC, for the coin pickers."""
    from tradingagents.dataflows import mexc_futures as fx
    try:
        return [c["symbol"] for c in fx.list_contracts()]
    except Exception:
        return []


def render_archive_backtest_section() -> None:
    """Backtest straight off the archive: pick coin, timeframe and window,
    run the SAME shared grid (`backtest_report`), get the standard report
    page. Candles come from the archive/disk cache, so nothing re-downloads."""
    from tradingagents import auto_trader as at
    from tradingagents import backtest_report as br
    from tradingagents.dataflows import market_db as mdb

    st.markdown('<div class="ta-section">Backtest — from the archive</div>',
                unsafe_allow_html=True)
    settings = _auto_trade_load()
    coins = settings.get("coins") or []
    _all = _all_mexc_symbols()
    coin_opts = coins + [s for s in sorted(_all) if s not in coins]
    c1, c2, c3, c4, c5 = st.columns([2, 1, 1, 1, 1],
                                    vertical_alignment="bottom")
    sel = c1.multiselect("Coins", coin_opts, default=[], key="mdbt_coins")
    c1.caption(f"**{len(sel)}** of {len(coin_opts)} coins selected"
               if sel else f"none of {len(coin_opts)} coins selected")
    tfs = c2.multiselect("Timeframes", list(br.TFS),
                         default=list(br.TFS), key="mdbt_tfs")
    win_sel = c3.selectbox("Dates", list(_BT_WINDOWS), index=3,
                           key="mdbt_win")
    run = c4.button("BACKTEST", key="mdbt_run", use_container_width=True,
                    disabled=not (sel and tfs),
                    help="Every signal x barrier pair x both sizings from the "
                         "shared grid, over the chosen window. Instant when "
                         "this exact question was already answered today.")
    upd = c5.button("UPDATE BACKTEST", key="mdbt_update",
                    use_container_width=True, disabled=not (sel and tfs),
                    help="CONTINUE the stored backtests over new candles "
                         "only — ladder rung, running totals and any open "
                         "trade carry across the seam. Never recomputes "
                         "what was already tested.")
    bt_where = st.radio(
        "Run where", ["This Mac", "GitHub (free machines)"], horizontal=True,
        key="mdbt_where",
        help="GitHub runs the same grid on their machine: rows land in the "
             "database, the report page hangs off the run as an artifact.")

    # A running job shows its live progress + STOP, whoever started it.
    from tradingagents import db_jobs
    _uj = db_jobs.status("btupdate")
    if upd and not _uj.get("running"):
        db_jobs.start("btupdate", {"coins": sel, "tfs": list(tfs),
                                   "days": _BT_WINDOWS[win_sel],
                                   "base": float(settings.get("margin", 5.0))})
        st.rerun()
    if _uj.get("running"):
        done_u, total_u = _uj.get("done", 0), max(_uj.get("total", 0), 1)
        st.progress(min(done_u / total_u, 1.0),
                    text=f"Continuing {_uj.get('now', '…')} — {done_u}/"
                         f"{total_u} pairs, {_uj.get('new_bars', 0):,} new "
                         f"bars, {_uj.get('rows', 0):,} rows so far")
        u1, u2 = st.columns([1, 5])
        if u1.button("STOP UPDATE", key="mdbt_upd_stop"):
            db_jobs.request_stop("btupdate")
            st.warning("Stop signalled — the current pair finishes, then it "
                       "exits. Every pair already continued is kept.")
        if u2.button("Refresh progress", key="mdbt_upd_poll"):
            st.rerun()
        return
    if not run and _uj.get("finished"):
        st.caption(f"Last update: {_uj.get('done', 0)}/{_uj.get('total', 0)} "
                   f"pairs continued over {_uj.get('new_bars', 0):,} new "
                   f"bars — {_uj.get('rows', 0):,} surviving rows, "
                   f"{_uj.get('saved', 0):,} saved to the database"
                   + (f" — save FAILED: {_uj['save_error']}"
                      if _uj.get("save_error") else "")
                   + (f" — {_uj['note']}" if _uj.get("note") else "") + ".")
    _bj = db_jobs.status("backtest")
    if _bj.get("running"):
        st.progress(min(_bj.get("done", 0) / 100, 1.0),
                    text=f"Backtesting — {_bj.get('now', '…')}")
        s1, s2 = st.columns([1, 5])
        if s1.button("STOP BACKTEST", key="mdbt_stop"):
            db_jobs.request_stop("backtest")
            st.warning("Stop signalled — it exits at the next step. A "
                       "backtest has no partial answer, so nothing is saved.")
        if s2.button("Refresh progress", key="mdbt_poll"):
            st.rerun()
        return
    if not run and _bj.get("finished"):
        if _bj.get("report"):
            st.caption(f"Last backtest: {_bj.get('rows', 0):,} combinations, "
                       f"{_bj.get('saved', 0):,} rows saved to the database"
                       + (f" — save FAILED: {_bj['save_error']}"
                          if _bj.get("save_error") else "") + ".")
            st.markdown(
                f"**[OPEN THE REPORT](app/static/bt/{_bj['report']})**")
        elif _bj.get("note"):
            st.caption(f"Last backtest: {_bj['note']}.")
    if not run:
        return

    days = _BT_WINDOWS[win_sel]
    if bt_where.startswith("GitHub"):
        from tradingagents import cloud_jobs as cj
        _ok, _slug = cj.available()
        if not _ok:
            st.error(f"GitHub unavailable — {_slug}. Run on This Mac instead.")
            return
        try:
            gh_run = cj.dispatch("archive-backtest.yml", {
                "coins": ",".join(sel), "timeframes": ",".join(tfs),
                "days": str(days),
                "base": f"{float(_auto_trade_load().get('margin', 5.0)):g}",
            })
            st.success(f"Started on GitHub — run #{gh_run['id']}. Rows land "
                       "in the database when it finishes; the report page is "
                       "the run's artifact.")
            st.markdown(f"[Watch the run]({gh_run['url']})")
        except Exception as exc:
            st.error(f"Could not start on GitHub: {exc}")
        return
    # Rule 21: the deployed combination must appear in its own page.
    sizing = at.sizing_for(settings)
    dep = []
    for key in settings.get("strategies", []):
        spec = at.STRATEGY_SPECS.get(key) or {}
        own = _BT_TF_NAME.get(spec.get("interval"))
        for c in at.coins_for(key, settings):
            if c in sel and own in tfs:
                dep.append({"coin": c.replace("_USDT", ""), "tf": own,
                            "signal": _tm_sig(key),
                            "th": round(float(spec.get("threshold") or 0)
                                        * 100, 3),
                            "sl": round(float(spec.get("sl", 0)) * 100, 3),
                            "tp": round(float(spec.get("tp", 0)) * 100, 3),
                            "sizing": sizing})

    base = float(settings.get("margin", 5.0))
    sig = "-".join(["archive", ",".join(sorted(sel)), ",".join(tfs),
                    str(days), f"{base:g}", sizing, str(len(br.SIGNALS))])
    stamp = _dt.datetime.now().strftime("%Y%m%d")
    digest = _hashlib.blake2s(sig.encode(), digest_size=4).hexdigest()
    name = f"archive-{digest}-{stamp}.html"
    fresh = BT_REPORT_DIR / name
    if fresh.exists() and fresh.stat().st_size > 10_000:
        built = _dt.datetime.fromtimestamp(fresh.stat().st_mtime)
        st.success(f"Already computed today at {built.strftime('%H:%M')} — "
                   "cached result.")
        st.markdown(f"**[OPEN THE REPORT](app/static/bt/{name})**")
        return

    db_jobs.start("backtest", {
        "coins": sel, "tfs": list(tfs), "days": days, "base": base,
        "deployed": dep, "report_name": name,
        "title": ("Archive backtest · "
                  + ", ".join(c.replace("_USDT", "") for c in sel)),
        "note": (f"{win_sel} ({days} days), {', '.join(tfs)}, base margin "
                 f"{base:g} USDT. Candles from the permanent archive."),
    })
    st.rerun()


def render_backtest_tab() -> None:
    from tradingagents import market_sweep as msw
    from tradingagents import backtest_report as br

    render_db_dashboard_section()
    render_market_data_section()
    render_archive_backtest_section()
    st.markdown('<div class="ta-section">Sweep</div>', unsafe_allow_html=True)

    cov = msw.coverage()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Coins measured", cov["coins"])
    c2.metric("Coin/timeframe pairs", cov["pairs"])
    c3.metric("Rows kept", f"{cov['rows']:,}")
    c4.metric("Newest bar tested", cov.get("last_bar") or "—")

    st.caption(
        f"{len(br.SIGNALS)} entry rules x {len(br.pairs_for('15m'))} barrier "
        f"pairs x 2 sizings, on 15m and 30m, over a year. All three costs are "
        f"charged: taker fee per contract, 0.03%/side slippage, and funding per "
        f"settlement held. Liquidation is modelled from MEXC's own maintenance "
        f"margin. Rows under {msw.MIN_TRADES} trades are dropped.")

    from tradingagents import cloud_sweep as cs

    _ok, _why = (False, "")
    try:
        _ok, _why = cs.available()
    except Exception as exc:
        _ok, _why = False, str(exc)[:120]
    where = st.radio(
        "Run where", ["GitHub (free, 20 machines)", "This Mac"],
        horizontal=True, key="bt_where",
        index=0 if _ok else 1,
        help="GitHub runs the same sweep on 20 machines in parallel and costs "
             "nothing on a public repo. This Mac uses 7 of your 8 cores.")
    if not _ok:
        st.caption(f"GitHub unavailable — {_why}. Falling back to this Mac.")
    cloud = _ok and where.startswith("GitHub")

    a, b, c = st.columns([1, 1, 2])
    run_all = a.button("RUN ALL COINS", key="bt_run_all",
                       help="Measure every contract at least a year old. "
                            "Hours on a first run; minutes once cached.")
    refresh = b.button("REFRESH", key="bt_refresh",
                       help="Fetch only the candles printed since the last run "
                            "and continue each backtest from where it stopped.")
    limit = c.number_input("Coins this pass (0 = all eligible)", min_value=0,
                           max_value=1000, value=25, step=25, key="bt_limit")

    # The sweep runs DETACHED, across every core. Doing it inline meant one
    # core and a restart on any click; a market sweep is hours, and Streamlit
    # reruns the script whenever a widget moves.
    if (run_all or refresh) and cloud:
        try:
            # The box says "coins this pass"; the workflow input is coins PER
            # SHARD. Passing it straight through meant 25 became 20x25=500.
            shards = 20
            per_shard = 0 if not limit else max(
                1, -(-int(limit) // shards))          # ceil, so 25 -> 2/shard
            run = cs.dispatch(shards=shards, coins=per_shard, min_days=365)
            st.session_state["bt_cloud_run"] = run
            cs.remember(run)          # survives a reload and a tab switch
            st.success(f"Started on GitHub — 20 machines. Run #{run['id']}.")
        except Exception as exc:
            st.error(f"Could not start on GitHub: {exc}")
    elif run_all or refresh:
        if msw.is_running():
            st.warning("A sweep is already running — watch it below.")
        else:
            cmd = [sys.executable, "-m", "tradingagents.market_sweep",
                   "--coins", str(int(limit)), "--min-days", "365",
                   "--tfs", "15m,30m", "--base", "5.0"]
            logf = open(os.path.expanduser(
                "~/.tradingagents/backtest/sweep.log"), "a")
            subprocess.Popen(cmd, cwd=str(Path(__file__).parent), stdout=logf,
                             stderr=subprocess.STDOUT, start_new_session=True)
            st.success("Sweep started in the background. It keeps running if "
                       "you leave this page, and survives a refresh.")
            time.sleep(2)

    _bt_cloud_panel()
    _bt_progress_panel()

    page = st.session_state.get("bt_all_page")
    if not page and cov["rows"]:
        # rows on disk but no page yet — render it now rather than show nothing
        page = _bt_build_page(msw.all_rows())
        st.session_state["bt_all_page"] = page
    if page:
        st.markdown(
            f"<a class='bt-open' href='{page[0]}' target='_blank' "
            f"rel='noopener'>OPEN RESULTS &#8599;</a>"
            f"<span class='bt-open-note'>every coin, every rule, sortable "
            f"&middot; filters &middot; last-N-months window</span>",
            unsafe_allow_html=True)
    elif not cov["rows"]:
        st.warning("Nothing measured yet — press RUN ALL COINS.")


def _bt2_deployed(coins: list[str], tfs: list[str]) -> list[dict]:
    """Every live strategy trading a selected coin on a selected timeframe,
    as `run_grid` deployed-injection dicts.

    Read from disk at RUN time, never from an earlier read — the config
    changed mid-task once (2026-08-19, PI re-added to mom15_4h_w at 07:39)
    and a page shipped saying "no deployed row" while a strategy was live.
    """
    from tradingagents import auto_trader as at

    cfg = at.load_settings()
    sizing = at.sizing_for(cfg)
    keys = list(cfg.get("strategies") or []) or list(
        (cfg.get("strategy_coins") or {}).keys())
    dep: list[dict] = []
    for key in keys:
        spec = at.STRATEGY_SPECS.get(key) or {}
        tf = _BT_TF_NAME.get(spec.get("interval"))
        if tf not in tfs:
            continue
        for c in at.coins_for(key, cfg):
            if c in coins:
                dep.append({
                    "coin": c.replace("_USDT", ""), "tf": tf,
                    "signal": _tm_sig(key),
                    "th": round(float(spec.get("threshold") or 0) * 100, 3),
                    "sl": round(float(spec.get("sl", 0)) * 100, 3),
                    "tp": round(float(spec.get("tp", 0)) * 100, 3),
                    "sizing": sizing})
    return dep


def render_stored_strategies_section() -> None:
    """Every strategy ever measured, kept in the archive.

    A strategy here is the seven fields the operator names: coin, timeframe,
    signal, threshold, TP, SL, sizing. BTC alone carries dozens — rsi14 and
    fade15 and the rest, each at several barrier pairs — so the browser filters
    rather than dumps.
    """
    import pandas as pd

    from tradingagents.dataflows import market_db as mdb

    st.markdown('<div class="ta-section">Stored strategies</div>',
                unsafe_allow_html=True)
    if not mdb.available():
        st.caption("The archive is not reachable, so nothing can be listed.")
        return
    try:
        rows = mdb.load_results()
    except Exception as exc:
        st.warning(f"Could not read stored strategies: {str(exc)[:120]}")
        return
    if not rows:
        st.caption("No strategies stored yet — run a backtest above and its "
                   "rows are written here automatically.")
        return

    coins = sorted({r["symbol"] for r in rows})
    tfs = sorted({r["timeframe"] for r in rows})
    sigs = sorted({r["signal"] for r in rows})
    c1, c2, c3, c4 = st.columns([2, 1, 1, 1], vertical_alignment="bottom")
    f_coin = c1.multiselect("Coin", coins, default=coins[:1] or coins,
                            key="mdbs_coin")
    f_tf = c2.multiselect("Timeframe", tfs, default=tfs, key="mdbs_tf")
    f_sig = c3.multiselect("Signal", sigs, default=[], key="mdbs_sig")
    only_green = c4.checkbox("Profitable only", value=True, key="mdbs_green")

    sel = [r for r in rows
           if (not f_coin or r["symbol"] in f_coin)
           and (not f_tf or r["timeframe"] in f_tf)
           and (not f_sig or r["signal"] in f_sig)
           and (not only_green or (r.get("profit") or 0) > 0)]
    st.caption(f"**{len(sel):,}** of {len(rows):,} stored strategies · "
               f"{len(coins)} coins · {len(sigs)} signals")
    if not sel:
        st.caption("Nothing matches those filters.")
        return
    tbl = pd.DataFrame([{
        "id": r["row_code"],
        "coin": r["symbol"].replace("_USDT", ""),
        "tf": r["timeframe"],
        "signal": r["signal"],
        "thresh %": r.get("threshold"),
        "SL %": r["sl"], "TP %": r["tp"],
        "sizing": r["sizing"],
        "PROFIT $": r.get("profit"),
        "win %": r.get("win_rate"),
        "trades": r.get("trades"),
        "W": r.get("wins"), "L": r.get("losses"),
        "green": (f"{r.get('months_green')}/{r.get('months_total')}"
                  if r.get("months_total") else ""),
        "worst dip $": r.get("max_dd") or r.get("worst_streak"),
        "funding $": r.get("funding"),
        "days": r.get("days"),
        "measured": (_dt.datetime.fromtimestamp(r["computed_at"])
                     .strftime("%Y-%m-%d") if r.get("computed_at") else ""),
    } for r in sorted(sel, key=lambda x: -(x.get("profit") or 0))])
    st.dataframe(tbl, width="stretch", height=420, hide_index=True)
    st.caption("Sorted by profit. Every row is one strategy — the same signal "
               "at a different threshold or a different TP/SL is a different "
               "row, because it is a different strategy.")


# Set once per PROCESS, not per session. The throttle used to live in
# st.session_state, so it read 0 on every fresh browser session and the sync
# ran again — which is why a plain refresh was slow every single time.
_LEDGER_SYNC_AT = 0.0
_LEDGER_SYNC_LOCK = _threading.Lock()


def _ledger_sync_worker() -> None:
    """The archive copy, off the render thread.

    ensure_schema() issues twenty DDL/migration statements against a REMOTE
    Neon Postgres. Measured 2026-08-20: 12,490 ms for that one call. It used to
    be the first statement of render_auto_trade_tab(), synchronous, before a
    single pixel was drawn — so the whole terminal waited on a schema check for
    a database the screen does not read.
    """
    global _LEDGER_SYNC_AT
    try:
        from tradingagents import auto_trader as at
        from tradingagents.dataflows import market_db as mdb

        if not mdb.available():
            return
        mdb.ensure_schema()
        n = mdb.sync_ledger(at.ledger_tail(100000))
        if n:
            _LEDGER_SYNC_LAST["rows"] = n
    except Exception:
        pass
    finally:
        _LEDGER_SYNC_LAST["at"] = _time_mod.time()
        with _LEDGER_SYNC_LOCK:
            _LEDGER_SYNC_AT = _time_mod.time()


_LEDGER_SYNC_LAST: dict = {"at": 0.0, "rows": 0}


def _ledger_sync_tick(every: int = 300) -> None:
    """Kick the archive copy onto a daemon thread and return immediately.

    The ledger is one local file — every entry, exit and venue rejection this
    account has ever made. A disk failure ends the record, so the copy still
    happens; it just no longer holds the page hostage.
    """
    global _LEDGER_SYNC_AT
    with _LEDGER_SYNC_LOCK:
        if _time_mod.time() - _LEDGER_SYNC_AT < every:
            return
        # Claim the slot BEFORE starting the thread, or two quick reruns each
        # start their own sync and both pay the schema cost.
        _LEDGER_SYNC_AT = _time_mod.time()
    _threading.Thread(target=_ledger_sync_worker, name="ledger-sync",
                      daemon=True).start()


def render_history_section() -> None:
    """What was live, and what it did — both out of the archive."""
    import pandas as pd

    from tradingagents.dataflows import market_db as mdb

    st.markdown('<div class="ta-section">Deployment history</div>',
                unsafe_allow_html=True)
    if not mdb.available():
        st.caption("The archive is not reachable, so history cannot be shown.")
        return
    deps = mdb.deployments(limit=200)
    if not deps:
        st.caption("No changes recorded yet — the next save writes one.")
    else:
        st.dataframe(pd.DataFrame([{
            "when": _dt.datetime.fromtimestamp(d["changed_at"])
                    .strftime("%Y-%m-%d %H:%M"),
            "coin": (d["symbol"] or "").replace("_USDT", ""),
            "what": d["action"],
            "strategy": d["strategy_key"],
            "tf": d["timeframe"], "signal": d["signal"],
            "thresh %": d["threshold"], "SL %": d["sl"], "TP %": d["tp"],
            "sizing": d["sizing"], "books": d["books"],
            "base $": d["base_margin"], "row id": d["row_code"],
            "note": d["note"],
        } for d in deps]), width="stretch", height=240, hide_index=True)

    rows = mdb.ledger_rows(limit=100000)
    st.markdown('<div class="ta-section">Trade ledger, archived</div>',
                unsafe_allow_html=True)
    if not rows:
        st.caption("Nothing synced yet.")
        return
    import collections as _c
    by = _c.Counter(r["action"] for r in rows)
    # dry_run is absent on most historical lines. Counting absent as real
    # money labelled 497 lines REAL that may not be — say unknown instead.
    real = sum(1 for r in rows if r["dry_run"] is False)
    unknown = sum(1 for r in rows if r["dry_run"] is None)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Lines archived", f"{len(rows):,}")
    c2.metric("Real money", f"{real:,}",
              help=f"{unknown:,} older lines do not record which book they "
                   f"were on, and are counted as neither.")
    c3.metric("Entries / exits", f"{by.get('enter', 0):,} / {by.get('exit', 0):,}")
    c4.metric("Errors", f"{by.get('error', 0):,}")
    show = [r for r in rows if r["action"] in ("enter", "exit")][:200]
    if show:
        st.dataframe(pd.DataFrame([{
            "when": _dt.datetime.fromtimestamp(r["ts"]).strftime("%Y-%m-%d %H:%M"),
            "coin": (r["symbol"] or "").replace("_USDT", ""),
            "action": r["action"], "strategy": r["strategy"],
            "side": r["side"], "entry": r["entry"], "exit": r["exit_price"],
            "margin $": r["margin"], "pnl $": r["pnl"], "closed by": r["why"],
            "book": ("paper" if r["dry_run"] else
                     "unknown" if r["dry_run"] is None else "REAL"),
        } for r in show]), width="stretch", height=300, hide_index=True)


def render_backtest2_tab() -> None:
    """Version 2: the DAILY sweep. One click runs every signal on the
    operator's own coins across every timeframe, marks every live strategy
    DEPLOYED, and opens the grid page — where LAST N DAYS re-simulates the
    week so "what is working right now" is answered by survivors on a
    current streak, not by yesterday's luck.

    V1 (`Back Test`) measures the whole market on 15m/30m; this one measures
    YOUR book, deeper (all four timeframes), in minutes — one walk per
    combination (`fast_grid`, parity-pinned) plus the disk candle cache.
    """
    from tradingagents import auto_trader as at
    from tradingagents import backtest_report as br

    # The archive controls belong on BOTH backtest pages. This tab runs off the
    # candle cache, and the cache is what DOWNLOAD/UPDATE fill — but the section
    # was wired only into `Back Test`, so from here there was no way to fetch or
    # refresh the candles the grid then reads.
    render_db_dashboard_section()
    render_market_data_section()
    # The operator's requested flow lives here too: BACKTEST + date window
    # (months/year) + run-on-Mac-or-GitHub, reading the archive.
    render_archive_backtest_section()
    render_stored_strategies_section()
    render_history_section()

    cfg = at.load_settings()
    _keys = list(cfg.get("strategies") or []) or list(
        (cfg.get("strategy_coins") or {}).keys())
    _live = sorted({c for k in _keys for c in at.coins_for(k, cfg)}
                   | set(cfg.get("coins") or []))
    if not _live:
        _live = ["PI_USDT", "PROVE_USDT", "APEX_USDT", "ALICE_USDT",
                 "XAUT_USDT"]

    st.markdown('<div class="ta-section">Daily grid</div>',
                unsafe_allow_html=True)
    # Every MEXC contract is selectable; the operator's own coins are just
    # the default. The picker was capped at the configured five, which made
    # "test something new" impossible from this page.
    _opts = _all_mexc_symbols() or _live
    _opts = sorted(set(_opts) | set(_live))
    c1, c2 = st.columns([3, 2])
    coins = c1.multiselect("Coins", options=_opts, default=[],
                           key="bt2_coins",
                           help=f"All {len(_opts)} MEXC USDT perpetuals. "
                                "Defaults to your configured coins.")
    tfs = c2.multiselect("Timeframes", options=list(br.TFS),
                         default=["15m", "30m", "1h", "4h"], key="bt2_tfs")
    c3, c4, c5 = st.columns([1, 1, 2])
    base = c3.number_input("Base margin $", min_value=1.0, max_value=1000.0,
                           value=5.0, step=1.0, key="bt2_base")
    days = c4.number_input("Days of history", min_value=30, max_value=730,
                           value=365, step=30, key="bt2_days")
    run = c5.button("RUN THE DAILY GRID", key="bt2_run",
                    disabled=not (coins and tfs))

    # Say the cost before spending it: combos from the real registry, ETA
    # from the measured rate (~92s per coin for all four timeframes with the
    # candle cache warm, 2026-08-20; roughly 3x that cold).
    _nsig = len(br.SIGNALS)
    _per_tf = ((_nsig - len(br.THRESH_SIGNALS)) * 110 * 2
               + len(br.THRESH_SIGNALS) * 3 * 110 * 2)
    _combos = _per_tf * len(tfs) * len(coins)
    _eta = 92 * len(coins) * max(1, len(tfs)) / 4
    st.caption(
        f"{_nsig} signals x 110 barrier pairs x 2 sizings x "
        f"{len(tfs)} timeframe(s) x {len(coins)} coin(s) = "
        f"~{_combos:,} combinations. About {_eta / 60:.0f} min with warm "
        f"candles (up to ~3x on the first run of the day). All three costs "
        f"charged; liquidation modelled; every live strategy on these "
        f"coins/timeframes is marked DEPLOYED.")

    if run:
        dep = _bt2_deployed(coins, tfs)
        _sig = "-".join([",".join(sorted(coins)), ",".join(sorted(tfs)),
                         f"{base:g}", str(int(days)), str(_nsig),
                         str(len(dep))])
        _stamp = _dt.datetime.now().strftime("%Y%m%d")
        _name = ("daily-" + _hashlib.blake2s(_sig.encode(),
                                             digest_size=4).hexdigest()
                 + f"-{_stamp}.html")
        fresh = BT_REPORT_DIR / _name
        if fresh.exists() and fresh.stat().st_size > 10_000:
            st.session_state["bt2_page"] = (f"app/static/bt/{_name}", _name)
            st.info("Same coins, timeframes and margin already ran today — "
                    "reusing that page. Change any input to force a re-run.")
        else:
            bar = st.progress(0.0, text="fetching candles…")
            note = st.empty()
            note.caption("Leave this tab alone while it runs; clicking "
                         "anything restarts Streamlit's script.")
            try:
                payload = br.run_grid(
                    coins, tfs, base_margin=float(base), days=int(days),
                    deployed=dep,
                    progress=lambda m, f: bar.progress(min(1.0, f), text=m))
            finally:
                bar.empty()
                note.empty()
            if not payload["rows"]:
                st.error("No rows survived the trade floor — nothing to "
                         "show. (Thin history or too-tight filters.)")
                return
            BT_REPORT_DIR.mkdir(parents=True, exist_ok=True)
            _shown = [c.replace("_USDT", "") for c in dict.fromkeys(coins)]
            br.write_report(
                str(BT_REPORT_DIR / _name), payload,
                title="Daily grid · " + ", ".join(_shown),
                note=(f"The operator's whole book on one page: "
                      f"{len(_shown)} coin(s) x {len(tfs)} timeframe(s), "
                      f"every signal, both sizings. {len(dep)} live "
                      f"strategy row(s) are marked DEPLOYED. To see what is "
                      f"working RIGHT NOW: set Last N to 7 and the unit to "
                      f"days — every figure re-simulates over that window, "
                      f"and the year-long record stays in the same row so a "
                      f"lucky week cannot masquerade as an edge."))
            old = sorted(BT_REPORT_DIR.glob("*.html"),
                         key=lambda p: p.stat().st_mtime, reverse=True)
            for stale in old[BT_REPORT_KEEP:]:
                try:
                    stale.unlink()
                except OSError:
                    pass
            st.session_state["bt2_page"] = (f"app/static/bt/{_name}", _name)

    page = st.session_state.get("bt2_page")
    if page:
        st.markdown(
            f"<a class='bt-open' href='{page[0]}' target='_blank' "
            f"rel='noopener'>OPEN THE DAILY GRID &#8599;</a>"
            f"<span class='bt-open-note'>set LAST N = 7 days on the page "
            f"&middot; survivors on a current streak float to the top "
            f"&middot; {html.escape(page[1])}</span>",
            unsafe_allow_html=True)


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
