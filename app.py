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
import traceback
from typing import NamedTuple

import streamlit as st

import tickers as ticker_data
from crypto_screener import render_new_crypto_tab
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
_ANTHROPIC = {"label": "anthropic", "provider": "anthropic", "base_url": None, "key_env": "ANTHROPIC_API_KEY"}
_QWEN = {"label": "qwen", "provider": "qwen", "base_url": None, "key_env": "DASHSCOPE_API_KEY"}
# Alibaba MaaS workspace (dedicated host) — OpenAI-compatible; serves glm-5.1 etc.
_MAAS = {"label": "maas", "provider": "openai_compatible",
         "base_url": "https://ws-wu00l7n3hmiafz2q.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
         "key_env": "MAAS_API_KEY"}
# Cloudflare Workers AI — OpenAI-compatible (account id baked into the URL).
# Native @cf/* models run on the free tier; deepseek/* partner models need a
# funded AI Gateway (402 otherwise).
_CF = {"label": "cloudflare", "provider": "openai_compatible",
       "base_url": "https://api.cloudflare.com/client/v4/accounts/4acf69efbeed54838dc0d5f004769933/ai/v1",
       "key_env": "CLOUDFLARE_API_KEY"}

MODELS: dict[str, dict] = {
    "gemini-3.1-flash-lite": _GOOGLE,            # free · fast · clean
    "gemini-3.5-flash": _GOOGLE,                 # free
    "deepseek-ai/deepseek-v4-flash": _NVIDIA,    # NVIDIA NIM
    "deepseek-ai/deepseek-v4-pro": _NVIDIA,      # NVIDIA NIM (slow)
    "moonshotai/kimi-k2.6": _NVIDIA,             # NVIDIA NIM
    "z-ai/glm-5.1": _NVIDIA,                     # NVIDIA NIM
    "glm-4.7": _OLLAMA,                          # Ollama Cloud · free · GLM (clean)
    "qwen3-coder:480b": _OLLAMA,                 # Ollama Cloud · free
    "gpt-oss:120b": _OLLAMA,                     # Ollama Cloud · free
    "gpt-4o-mini": _OPENAI,                      # OpenAI · cheap (needs billing/credits)
    "gpt-5-mini": _OPENAI,                       # OpenAI · cheap reasoning
    "gpt-5.1": _OPENAI,                          # OpenAI · frontier
    "gpt-5.5": _OPENAI,                          # OpenAI · frontier (needs billing)
    "claude-opus-4-8": _ANTHROPIC,               # Anthropic · Opus 4.8 (needs ANTHROPIC_API_KEY)
    "qwen3.6-flash": _QWEN,                      # Qwen Cloud · cheap · clean
    "qwen3.7-plus": _QWEN,                       # Qwen Cloud · balanced
    "qwen3.7-max": _QWEN,                        # Qwen Cloud · top reasoning/coding
    "glm-5.1": _MAAS,                            # Alibaba MaaS · GLM-5.1 (works here!)
    "deepseek-v4-flash": _MAAS,                  # Alibaba MaaS · DeepSeek V4 Flash
    "deepseek-v4-pro": _MAAS,                    # Alibaba MaaS · DeepSeek V4 Pro (free here; CF 402s)
    "@cf/meta/llama-3.3-70b-instruct-fp8-fast": _CF,  # Cloudflare · Llama 3.3 70B · free
    "@cf/openai/gpt-oss-120b": _CF,                   # Cloudflare · GPT-OSS 120B · high-end
    "@cf/meta/llama-4-scout-17b-16e-instruct": _CF,   # Cloudflare · Llama 4 Scout · newest
    "@cf/zai-org/glm-5.2": _CF,                       # Cloudflare · GLM-5.2 · free (newer than 5.1)
    "deepseek/deepseek-v4-pro": _CF,                  # Cloudflare gateway partner · 402 until funded
    # NOTE: nvidia ids use prefixes (z-ai/glm-5.1, deepseek-ai/…) so no clash.
    #       OpenAI models + the Ollama glm-5.1 need a funded/paid account.
}
MODEL_CHOICES = list(MODELS)
CUSTOM_MODEL = "✏️  Custom…"


def _spec(model: str) -> dict:
    return MODELS.get(model, {"label": DEFAULT_CONFIG["llm_provider"],
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
    for m in [default, *MODEL_CHOICES]:
        if m and m not in seen:
            seen.append(m)
    return [*seen, CUSTOM_MODEL]


# --- Pure, testable helpers ------------------------------------------------
def build_config(base: dict, *, provider: str, deep_model: str, quick_model: str,
                 debate_rounds: int, risk_rounds: int) -> dict:
    """base config overlaid with the UI's per-run choices. `.env` still supplies keys."""
    cfg = base.copy()
    cfg["llm_provider"] = provider
    cfg["deep_think_llm"] = deep_model
    cfg["quick_think_llm"] = quick_model
    cfg["max_debate_rounds"] = int(debate_rounds)
    cfg["max_risk_discuss_rounds"] = int(risk_rounds)
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


HEALTH_ICON = {"ok": "✅", "degraded": "⚠️", "ratelimit": "⏱️", "auth": "🔑", "error": "❌"}


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
    """Render a health result dict as an icon + status + latency string. Pure."""
    if not result:
        return "—"
    status = result.get("status", "error")
    return f"{HEALTH_ICON.get(status, '❌')} **{status}** · {result.get('ms', '?')}ms"


# --- Design system (CSS) ---------------------------------------------------
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600&family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600&family=JetBrains+Mono:wght@400;500;600&display=swap');

/* Editorial financial terminal: paper surfaces, ink type, one burnt-orange
   accent, hairline rules. The data is the interface, so the chrome stays quiet
   and the numbers get the good typography — JetBrains Mono with tabular figures
   so columns of prices line up digit for digit. */
:root {
  --bg:#FAF9F7;            /* warm paper, not clinical white */
  --panel:#FFFFFF;
  --panel-2:#F3F2EF;
  --sidebar:#F3F2EF;
  --border:#E4E1DB;
  --border-soft:#EDEBE6;
  --border-strong:#CFCBC2;
  --text:#171612;          /* ink, not pure black */
  --muted:#6C695F;
  --faint:#9B978C;
  --accent:#C2560B;        /* burnt orange: passes contrast on paper */
  --accent-dim:#96420A;
  --accent-wash:#FDF3EA;
  --buy:#0A6B45; --sell:#A8231B; --hold:#9A5B08;
  --font-display:'Newsreader',Georgia,serif;
  --font-body:'Instrument Sans',sans-serif;
  --font-mono:'JetBrains Mono',ui-monospace,monospace;
  --r:5px;
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
.block-container{ padding-top:calc(var(--s) * 2); max-width:1240px; }

/* Serif headings against a sans UI: editorial contrast, and it makes a verdict
   read as a statement rather than a label. */
h1,h2,h3,h4{ font-family:var(--font-display); font-weight:500; color:var(--text);
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
@keyframes pulse{ 0%,100%{ box-shadow:0 0 0 0 rgba(194,86,11,.35);} 50%{ box-shadow:0 0 0 5px rgba(194,86,11,0);} }

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

/* ---- Tabs ---- */
[data-baseweb="tab-list"]{ gap:calc(var(--s) * 3) !important;
  border-bottom:1px solid var(--border); background:transparent !important; }
[data-baseweb="tab"]{ padding:var(--s) 0 !important; font-size:13.5px; color:var(--muted);
  background:transparent !important; }
[data-baseweb="tab"][aria-selected="true"]{ color:var(--text); font-weight:600; }
[data-baseweb="tab-highlight"]{ background:var(--accent) !important; height:2px !important; }

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
  border:1px solid #EBD3BC !important; border-radius:3px !important;
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
[data-baseweb="input"]:hover, [data-baseweb="select"] > div:hover{ border-color:#B4AFA4 !important; }
[data-baseweb="input"]:focus-within, [data-baseweb="base-input"]:focus-within,
[data-baseweb="select"] > div:focus-within{
  border-color:var(--accent) !important; box-shadow:0 0 0 3px rgba(194,86,11,.12) !important;
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
        ("📈  Market Analyst", "market_report"),
        ("💬  Sentiment Analyst", "sentiment_report"),
        ("📰  News Analyst", "news_report"),
        ("📊  Fundamentals Analyst", "fundamentals_report"),
    ]:
        if _nonempty(state.get(key)):
            sections.append((label, state[key]))
    if _nonempty(debate.get("bull_history")):
        sections.append(("🐂  Bull Researcher", debate["bull_history"]))
    if _nonempty(debate.get("bear_history")):
        sections.append(("🐻  Bear Researcher", debate["bear_history"]))
    if _nonempty(state.get("investment_plan")):
        sections.append(("🧭  Research Manager — Plan", state["investment_plan"]))
    if _nonempty(state.get("trader_investment_plan")):
        sections.append(("💼  Trader — Proposal", state["trader_investment_plan"]))
    for label, rkey in [
        ("🔥  Risk — Aggressive", "aggressive_history"),
        ("🛡️  Risk — Conservative", "conservative_history"),
        ("⚖️  Risk — Neutral", "neutral_history"),
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
        for i, (label, content) in enumerate(sections):
            with st.expander(label, expanded=(i == len(sections) - 1)):
                st.markdown(safe_markdown(content))


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


# status → (bar color, label, fill fraction). Providers don't expose exact
# remaining quota, so the bar reflects live *usability*: green=has capacity now,
# amber=rate-limited (no quota this minute), red=down/no-key.
_BAR = {
    "ok":        ("#16C784", "available", 1.0),
    "ratelimit": ("#F0B90B", "rate-limited now", 0.12),
    "degraded":  ("#EA3943", "provider down", 0.0),
    "auth":      ("#EA3943", "no / invalid key", 0.0),
    "error":     ("#EA3943", "error", 0.0),
    "untested":  ("#586374", "not tested", 0.06),
}


def provider_status(provider: str, health: dict) -> str:
    """Aggregate a provider's models into one status. `health` maps model→result.
    If any model is ok the provider is ok; else the worst seen. Pure/testable."""
    seen = [health[m]["status"] for m in MODEL_CHOICES
            if provider_for(m) == provider and m in health and health[m]]
    if not seen:
        return "untested"
    for rank in ("ok", "ratelimit", "degraded", "auth", "error"):
        if rank in seen:
            return rank
    return seen[0]


def render_provider_bars(container) -> None:
    health = {m: st.session_state.get(f"health_{m}") for m in MODEL_CHOICES}
    health = {m: r for m, r in health.items() if r}
    rows = ""
    for p in sorted({provider_for(m) for m in MODEL_CHOICES}):
        color, label, frac = _BAR[provider_status(p, health)]
        rows += (
            f"<div style='margin:7px 0'>"
            f"<div style='display:flex;justify-content:space-between;font-family:var(--font-mono);font-size:12px'>"
            f"<span style='color:var(--text)'>{html.escape(p)}</span>"
            f"<span style='color:{color}'>{label}</span></div>"
            f"<div style='height:8px;background:#0E141B;border:1px solid var(--border);"
            f"border-radius:6px;overflow:hidden;margin-top:3px'>"
            f"<div style='height:100%;width:{int(frac*100)}%;background:{color}'></div></div></div>")
    container.markdown(
        "<div class='ta-card'><h4>Engine capacity</h4>"
        "<div style='font-size:11px;color:var(--muted);margin-bottom:6px'>Live usability from the last "
        "health check — green = has capacity now, amber = rate-limited, red = down / no key. "
        "(Providers don't expose an exact balance; click <b>Test ALL</b> to refresh.)</div>"
        f"{rows}</div>", unsafe_allow_html=True)


def render_health_panel() -> None:
    """Per-provider capacity bars + a 'Test' button per model + 'Test all'.
    Each model pings its OWN provider; rows update LIVE via as_completed."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    st.markdown("#### 🔌 Model health")
    bars = st.empty()                       # top placeholder, refreshed after tests
    render_provider_bars(bars)
    st.caption("Live ping each model on its own provider — confirms it actually responds right now.")
    test_all = st.button("⚡ Test ALL models (parallel)", key="test_all", type="primary")

    # Build rows with a placeholder per status cell so we can update them live.
    slots: dict[str, object] = {}
    for m in MODEL_CHOICES:
        c1, c2, c3 = st.columns([4, 1, 4])
        c1.markdown(f"`{m}`  ·  _{provider_for(m)}_")
        single = c2.button("Test", key=f"test_{m}")
        slots[m] = c3.empty()
        if single:
            slots[m].markdown("⏳ testing…")
            st.session_state[f"health_{m}"] = ping_model(m)
        slots[m].markdown(_health_line(st.session_state.get(f"health_{m}")))

    if test_all:
        if st.button("⏹  Stop tests", key="stop_tests",
                     help="Abandon the in-flight tests (effective at the next model finishing)."):
            st.rerun()
        for m in MODEL_CHOICES:                       # all flip to testing at once…
            slots[m].markdown("⏳ testing…")
        with ThreadPoolExecutor(max_workers=len(MODEL_CHOICES)) as ex:
            futs = {ex.submit(ping_model, m): m for m in MODEL_CHOICES}
            for fut in as_completed(futs):            # …and resolve as each finishes
                m = futs[fut]
                res = fut.result()
                st.session_state[f"health_{m}"] = res
                slots[m].markdown(_health_line(res))
                render_provider_bars(bars)            # progressive: refresh bars per result

    render_provider_bars(bars)              # final refresh with latest results


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
            cards += _summary_card(m, f"{done}/{total}", "#2DD4BF", (running or "starting…") + " ⏳")
    return f"<div style='display:flex;gap:10px;flex-wrap:wrap;margin-bottom:10px'>{cards}</div>"


def run_parallel_live(models, ticker, date, analysts, debate_rounds, risk_rounds,
                      keys=None) -> None:
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
                           quick_model=model, debate_rounds=debate_rounds, risk_rounds=risk_rounds)
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
                            with st.expander("🧾  Full final decision", expanded=False):
                                st.markdown(fd)
                            st.download_button(
                                "⬇  Download (.md)", data=fd, key=f"dl_{m}",
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
    progress_col, report_col = st.columns([1, 2], gap="large")
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
            status.update(label=f"⏳ {label}  ·  {done}/{total} stages done")
            progress_bar.progress(frac, text=f"{label}  ·  {done}/{total}")
            render_progress(progress_box, final_state, selected)
            render_reports(report_box, final_state)
        progress_bar.progress(1.0, text="Complete")
        status.update(label="✅ Analysis complete", state="complete", expanded=False)
    except Exception as exc:  # noqa: BLE001
        status.update(label="❌ Run failed — raw API error below", state="error", expanded=True)
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
        with st.expander("🧾  Full final decision", expanded=True):
            st.markdown(safe_markdown(final_decision))
        st.download_button("⬇  Download decision (.md)", data=final_decision,
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
    mode = st.radio("Run mode", ["🎯 Selected model", "⚡ Parallel — compare models"],
                    horizontal=True, label_visibility="collapsed", key="run_mode")
    if mode.startswith("🎯"):
        opts = model_options(default_model)
        sel = st.selectbox("Model", opts, index=0, key="single_model", label_visibility="collapsed")
        if sel == CUSTOM_MODEL:
            sel = st.text_input("Custom model id", value="", key="single_custom",
                                placeholder="vendor/model-id").strip() or default_model
        return mode, [sel], {}
    default_two = MODEL_CHOICES[:2]
    models = st.multiselect("Models to run in parallel", MODEL_CHOICES, default=default_two,
                            key="parallel_models", format_func=lambda m: f"{m}  ·  {provider_for(m)}")
    st.caption("⚠️ Each model runs a full analysis at once, each on **its own provider** "
               "(mixing NVIDIA + Gemini = separate quotas → best for dodging rate limits).")
    keys: dict[str, str] = {}
    with st.expander("🔑 Per-model API keys (optional)"):
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
    provs = "+".join(sorted({provider_for(m) for m in MODEL_CHOICES}))
    return (
        "<div style='background:var(--panel-2);border:1px solid var(--border);"
        "border-radius:5px;padding:7px 11px;margin-bottom:10px;"
        "font-family:var(--font-mono);font-size:11.5px'>"
        "<span style='color:var(--faint);letter-spacing:.1em'>ENGINE</span>  "
        f"<span style='color:var(--accent-dim)'>{html.escape(provs)}</span>"
        "<span style='color:var(--faint);font-size:10px'> · auto per model</span></div>")


def main() -> None:
    # No sidebar: Streamlit renders one sidebar for the whole app, so settings
    # placed there appear on both tabs and imply they apply to whichever tab is
    # open. Each tab owns its own controls instead.
    st.set_page_config(page_title="TradingAgents", page_icon="◈", layout="wide",
                       initial_sidebar_state="collapsed")
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(header_html(), unsafe_allow_html=True)

    tab_run, tab_new = st.tabs(["Run analysis", "New Crypto"])
    with tab_run:
        # A plain `with` block cannot host the run screen's early `return`s — they
        # would exit main() and skip the second tab — so it is its own function.
        render_run_analysis_tab()
    with tab_new:
        render_crypto_tab()


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
    trade_date = c2.date_input("Analysis date").isoformat()

    selected = st.multiselect(
        "Analysts", options=[k for k, _, _ in ANALYST_STAGES],
        default=[k for k, _, _ in ANALYST_STAGES],
        format_func=lambda k: ANALYST_LABELS[k])
    r1, r2, r3 = st.columns([1, 1, 2])
    debate_rounds = r1.number_input("Debate rounds", 1, 5, 1)
    risk_rounds = r2.number_input("Risk rounds", 1, 5, 1)
    run = r3.button("Run analysis", type="primary")
    return ticker, trade_date, selected, debate_rounds, risk_rounds, run


def render_crypto_tab() -> None:
    """Model, date and round controls for the crypto tab, then the screener."""
    default_model = DEFAULT_CONFIG["deep_think_llm"]
    opts = model_options(default_model)
    m1, m2 = st.columns([3, 1])
    model = m1.selectbox("Model", opts, index=0, key="crypto_model",
                         format_func=lambda m: f"{m}  ·  {provider_for(m)}")
    if model == CUSTOM_MODEL:
        model = m1.text_input("Custom model id", value="", key="crypto_custom",
                              placeholder="vendor/model-id").strip() or default_model
    trade_date = m2.date_input("Analysis date", key="crypto_date").isoformat()
    d1, d2, _ = st.columns([1, 1, 2])
    debate_rounds = d1.number_input("Debate rounds", 1, 5, 1, key="crypto_debate")
    risk_rounds = d2.number_input("Risk rounds", 1, 5, 1, key="crypto_risk")

    render_new_crypto_tab(
        model=model, provider=provider_for(model), trade_date=trade_date,
        base_config=DEFAULT_CONFIG, debate_rounds=debate_rounds,
        risk_rounds=risk_rounds, configure_cfg=configure_cfg,
        streaming_runner=run_single_streaming)


def render_run_analysis_tab() -> None:
    """The original single/parallel run screen, with its settings inline."""
    ticker, trade_date, selected, debate_rounds, risk_rounds, run = render_run_settings()
    st.markdown('<div class="ta-rule"></div>', unsafe_allow_html=True)
    # Two options on top: run mode + which model(s).
    mode, models_to_run, model_keys = render_run_mode(DEFAULT_CONFIG["deep_think_llm"])
    st.markdown('<div class="ta-rule"></div>', unsafe_allow_html=True)

    if not run:
        st.markdown(
            '<div class="ta-card"><h4>Ready</h4><div style="color:var(--muted);font-size:14px">'
            'Pick a ticker/date and a run mode, then Run. <b>Selected model</b> streams one run live; '
            '<b>Parallel</b> runs several models at once and compares their calls side-by-side.</div></div>',
            unsafe_allow_html=True)
        st.write("")
        render_health_panel()
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
    if st.button("⏹  Stop", key="stop_run",
                 help="Abandon the current run and return to idle (takes effect at the next stage/model boundary)."):
        st.rerun()

    if mode.startswith("🎯"):
        model = models_to_run[0]
        prov = provider_for(model)
        cfg = build_config(DEFAULT_CONFIG, provider=prov, deep_model=model, quick_model=model,
                           debate_rounds=debate_rounds, risk_rounds=risk_rounds)
        configure_cfg(cfg, model)               # real provider / base_url / key
        run_single_streaming(ticker, trade_date, selected, cfg, prov, model)
    else:
        run_parallel_live(models_to_run, ticker, trade_date, selected,
                          debate_rounds, risk_rounds, model_keys)


if __name__ == "__main__":
    main()
