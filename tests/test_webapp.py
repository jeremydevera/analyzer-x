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


def test_the_ui_refuses_to_save_a_coin_on_two_timeframes():
    """One coin runs one timeframe. The runner refuses such a config at cycle
    time, but it should never reach the disk: MEXC nets same-symbol positions
    into one, so two strategies on a coin at different bar sizes resize each
    other's trade and either stop closes part of a position it does not own."""
    import inspect

    import app

    src = inspect.getsource(app.render_auto_trade_tab) \
        if hasattr(app, "render_auto_trade_tab") else open("app.py").read()
    assert "timeframe_conflicts" in src, "the save path must run the check"
    assert "is LIVE on two timeframes" in src, "and say which coin"
    assert "Nothing was written" in src, "and not write a broken config"
    assert '"strategy_books": {k: v for k, v in strategy_books.items()' in src, \
        ("the probe must carry the book map, or books_for() falls back to the "
         "global switches and refuses two PAPER timeframes on one coin")


def test_the_new_pi_strategy_is_offered_in_the_ui():
    """A key that exists in STRATEGY_SPECS and in the settings file still will
    not render: the table is built from app.AUTO_STRATEGIES, a separate
    hardcoded list. #3CRXP8 was enabled on disk and invisible on the page."""
    import app
    from tradingagents import auto_trader as at

    keys = [k for k, _, _, _ in app.AUTO_STRATEGIES]
    assert "trend50_30m_pi" in keys
    for k in keys:
        assert k in at.STRATEGY_SPECS, f"{k} is offered but has no spec"


def test_the_contract_column_comes_from_the_TILE_not_the_saved_file():
    """Superseded the empty-list fix: the saved copy is no longer read at all.

    PI was moved off mom15_4h_w, which emptied that row's saved coin list to
    [], and the table then printed `contracts: none` — a row that could be
    armed and would trade nothing. The contract is part of the strategy
    (#3CRXP8 IS trend50/30m on PI), so the row shows its own."""
    src = open("app.py").read()
    assert "_coins = list(default_coins)" in src, "the tile is the source"
    assert "saved_coins_by" not in src, \
        "reading the saved copy back is what produced 'contracts: none'"


def test_the_terminal_follows_the_light_dark_toggle():
    """Operator, 2026-08-19: "even when i light mode, the sections are black".
    The terminal used to paint a near-black ground in both themes on purpose.
    Now the light palette is the default and night redefines the tokens."""
    import re

    import app
    light = re.findall(r"--t-(\w+):\s*([^;]+);", app.TERMINAL_CSS)
    dark = re.findall(r"--t-(\w+):\s*([^;]+);", app.TERMINAL_DARK_CSS)
    lmap, dmap = dict(light), dict(dark)
    # Measure lightness rather than matching a literal — the invariant is what
    # matters: light ink dark, dark ink light. Two notations have to be read,
    # because the tokens were ported to the zenith template's own oklch() values
    # on 2026-08-20 and a hex-only parser silently returned None for every one
    # of them, which made all four assertions compare against None.
    def _lum(v):
        v = v.strip()
        m = re.fullmatch(r"#([0-9a-fA-F]{6})", v)
        if m:
            r, g, b = (int(m.group(1)[i:i + 2], 16) / 255 for i in (0, 2, 4))
            return 0.2126 * r + 0.7152 * g + 0.0722 * b
        # oklch(L% c h) — L IS a perceptual lightness on 0..1, so it answers
        # "is this ink or is this ground" directly.
        m = re.match(r"oklch\(\s*([\d.]+)%", v)
        if m:
            return float(m.group(1)) / 100.0
        return None
    assert _lum(lmap["ink"]) < 0.30, f"light mode needs dark ink: {lmap['ink']}"
    assert _lum(lmap["panel"]) > 0.85, f"light needs a light panel: {lmap['panel']}"
    assert _lum(dmap["ink"]) > 0.70, f"night needs light ink: {dmap['ink']}"
    assert _lum(dmap["panel"]) < 0.20, f"night needs a dark panel: {dmap['panel']}"
    # and the direction's own semantics: jade up, coral down, in both themes
    assert lmap["up"] and lmap["dn"] and dmap["up"] and dmap["dn"]
    # Every colour token the night block redefines must exist in the light one,
    # or a rule paints ink whose ground was never painted — the 2026-08-15 bug.
    missing = [k for k in dmap if k not in lmap]
    assert not missing, f"night defines tokens light does not: {missing}"


def test_the_dataframe_invert_is_night_only():
    """`filter:invert(.92)` turns Streamlit's white grid black. In light mode
    that IS the reported bug, so the rule lives in the night block only."""
    import app
    assert "invert(.92)" not in app.TERMINAL_CSS
    assert "invert(.92)" in app.TERMINAL_DARK_CSS


def test_the_bands_use_apexs_card_treatment():
    """Superseded "the bands are not filled cards": that was the operator's
    2026-08-19 complaint about a BLACK box in light mode. On 2026-08-20 they
    asked for Apex's UI, whose sections are white cards with a hairline border
    and a 10px radius — the opposite problem, and what they now want."""
    import re

    import app
    # 2026-08-20: the operator asked for apex-django.dashboardpack.com's UI,
    # whose sections ARE cards — so the hairline-only rule from earlier the same
    # day is deliberately superseded. What must hold is Apex's treatment: a
    # panel-coloured card, a hairline border, the 10px radius and NO shadow.
    rules = re.findall(r'\.st-key-term \[class\*="st-key-tmsec_"\]\{([^}]+)\}',
                       app.TERMINAL_CSS)
    assert rules, "the band rule is gone entirely"
    body = rules[-1]
    assert "background:var(--t-panel)" in body
    assert "border:1px solid var(--t-rule)" in body
    assert "border-radius:var(--t-r)" in body
    assert "box-shadow:none" in body


def test_the_history_table_pages_ten_at_a_time_with_numbers():
    src = open("app.py").read()
    assert "_per = 10" in src, "the operator asked for 10 rows a page"
    assert "_page_numbers(" in src, "numbered pages, not newer/older"
    assert "◀ newer" not in src and "older ▶" not in src


def test_page_numbers_windows_and_elides():
    import app
    assert app._page_numbers(1, 3) == [1, 2, 3]
    assert app._page_numbers(7, 14) == [1, None, 5, 6, 7, 8, 9, None, 14]
    assert app._page_numbers(14, 14) == [1, None, 9, 10, 11, 12, 13, 14]
    assert app._page_numbers(1, 1) == [1]
    for pages in range(1, 60):
        for pg in range(1, pages + 1):
            nums = app._page_numbers(pg, pages)
            real = [n for n in nums if n is not None]
            assert pg in real, f"page {pg} of {pages} is not reachable"
            assert real == sorted(set(real)), f"{pg}/{pages}: {nums}"
            assert real[0] == 1 and real[-1] == pages
            assert len(nums) <= 9, f"{pg}/{pages} draws {len(nums)} buttons"


def test_the_runner_feed_shows_am_pm_not_a_24_hour_stamp():
    """Operator, 2026-08-20: "make the time in am or pm i dont want this format
    2026-08-20 01:20:50". Reformatted at RENDER time, so the lines already on
    disk read the same way as the ones written next."""
    import app
    assert app._fmt_log_line(
        "2026-08-20 01:20:50,936 INFO scan PI_USDT: step=3") == \
        "Aug 20 1:20:50AM INFO scan PI_USDT: step=3"
    assert app._fmt_log_line("2026-08-20 13:05:09,001 WARNING x") == \
        "Aug 20 1:05:09PM WARNING x"
    assert app._fmt_log_line("2026-08-20 12:00:00,000 INFO noon") == \
        "Aug 20 12:00:00PM INFO noon"
    assert app._fmt_log_line("2026-08-20 00:00:00,000 INFO midnight") == \
        "Aug 20 12:00:00AM INFO midnight"
    # milliseconds are optional
    assert app._fmt_log_line("2026-08-20 09:07:05 INFO x") == \
        "Aug 20 9:07:05AM INFO x"


def test_a_line_with_no_timestamp_is_left_alone():
    """A traceback continuation must not be mangled into something that reads
    like an event."""
    import app
    for line in ("Traceback (most recent call last):",
                 '  File "x.py", line 1, in <module>',
                 "2026-13-45 99:99:99,000 INFO impossible date",
                 ""):
        assert app._fmt_log_line(line) == line


def test_the_feed_actually_uses_the_formatter():
    src = open("app.py").read()
    assert "html.escape(_fmt_log_line(l))" in src, \
        "the runner-log column must render through it"


def test_tables_match_the_apex_customers_spec():
    """Measured cell by cell off apex-django.dashboardpack.com/customers/ on
    2026-08-20. This CORRECTS the first port: the dashboard's "Recent Orders"
    card is sentence case, so uppercase was stripped everywhere — but the data
    table the operator asked for has UPPERCASE headers at 12px/600 with .6px
    tracking. Rows are 44.5px with a hairline under each and an accent hover."""
    import re

    import app
    css = app.CSS
    m = re.search(r'\[data-testid="stTable"\] thead th[^{]*\{([^}]+)\}', css)
    assert m, "the table header rule is gone"
    th = m.group(1)
    assert "text-transform:uppercase" in th
    assert "font-size:12px" in th
    assert "font-weight:600" in th
    assert "letter-spacing:.6px" in th
    assert "position:sticky" in th, "its header sticks while the body scrolls"

    m = re.search(r'\[data-testid="stTable"\] tbody td[^{]*\{([^}]+)\}', css)
    td = m.group(1)
    assert "padding:8px 12px" in td
    assert "height:44px" in td
    assert "border-bottom:1px solid var(--border)" in td

    # the ornaments its rows are built from
    for cls in (".ap-av", ".ap-pill", ".ap-sub"):
        assert cls in css, f"{cls} missing"
    assert "border-radius:9999px" in css, "avatars and pills are round"


def test_the_terminal_grid_uses_the_same_header_spec():
    """One app, one table language — the dense grid keeps the spec at its own
    row height rather than looking like a different product."""
    import re

    import app
    m = re.search(r'\.st-key-term \.tm-pt-h\{([^}]+)\}', app.TERMINAL_CSS)
    assert m, "the grid header rule is gone"
    h = m.group(1)
    assert "text-transform:uppercase" in h
    assert "letter-spacing:.6px" in h
    assert "font-weight:600" in h


def test_positions_rows_use_the_apex_orders_shape():
    """Ported from apex-django.dashboardpack.com/orders/ on 2026-08-20: its row
    is avatar + name + email underneath, a status PILL, and a right-aligned
    total. Ours is avatar + contract + strategy underneath, LONG/SHORT as the
    pill, and the bracket as a second pill."""
    import app
    row = app._tm_pos_row({
        "coin": "PROVE", "strategy": "mom6_1h_pv", "side": "LONG",
        "bracket": "on MEXC", "open $": 2.11, "W": 4, "L": 8, "trades": 12,
        "entry": 0.1563, "margin $": 5, "opened": "08-19 03:00", "held": "22h",
        "prog": "", "tp_pct": "", "sl_pct": ""})
    assert "ap-av" in row and ">PR<" in row, "avatar with the contract initials"
    assert "<b>PROVE</b>" in row
    assert "ap-sub'>mom6_1h_pv" in row, "strategy is the sub-line"
    assert "ap-pill ok'>LONG" in row, "LONG is a green pill"
    # The bracket pill used to read "on MEXC" here. Removed on the operator's
    # instruction the same day — see
    # test_the_stop_column_is_silent_unless_the_stop_is_missing.
    short = app._tm_pos_row({"coin": "PI", "strategy": "x", "side": "SHORT",
                             "bracket": "SIMULATED", "open $": -1.0})
    assert "ap-pill bad'>SHORT" in short


def test_the_total_row_gets_no_avatar():
    """It printed a circle reading "TO" beside the word TOTAL — a summary line
    is not an identity."""
    import app
    tot = app._tm_pos_row({"coin": "TOTAL", "side": "", "bracket": "",
                           "open $": 0.5, "W": 4, "L": 11, "trades": 15})
    assert "ap-av" not in tot
    assert "<b>TOTAL</b>" in tot


def test_the_avatar_colour_is_stable_per_contract():
    """Apex gives each identity its own colour; a colour that moved between
    reruns would make the same contract look like a different one."""
    import app
    a = app._ap_avatar("PROVE_USDT")
    assert a == app._ap_avatar("PROVE_USDT") == app._ap_avatar("PROVE")
    assert app._ap_avatar("PI") != app._ap_avatar("XAUT")
    assert "PR" in a and "#" in a


def test_the_close_column_shares_the_rows_height():
    """The Close button drifted 7px above its row and I claimed in a comment
    that alignment was "asserted at 0px" — no such test existed.

    Measured cause: Streamlit's own markdown container carries
    margin-bottom:-14px, so a 49px row (the identity cell is two lines) reported
    35px to its parents; the flex block sized to 35 and the button centred
    there. The CSS undoes that collapse and stretches the block, and
    scripts/pos_align.mjs measures the real offset in a browser — it reads 0px.
    """
    import app
    css = app.TERMINAL_CSS
    assert '[data-testid="stMarkdownContainer"]:has(.tm-pt)' in css, \
        "the negative-margin collapse must be undone for position rows"
    assert "align-items:stretch !important" in css, \
        "the row block must stretch so both columns share the row height"
    assert '[data-testid="stColumn"]:has(.stButton)' in css, \
        "the button column is stColumn, not a bare div"


def test_a_summary_row_prints_no_stray_dashes():
    """The TOTAL row showed em dashes under SIDE and BRACKET, because the new
    ident/side/pill kinds fell through to the em-dash branch that only "text"
    was exempt from."""
    import app
    for kind in ("text", "ident", "side", "pill", "html"):
        assert app._tm_pos_cell("", kind) == ""
        assert app._tm_pos_cell(None, kind) == ""
    for kind in ("num", "money", "px"):
        assert app._tm_pos_cell(None, kind) == "—"


def test_the_total_row_sums_the_margin_at_risk():
    """It printed an em dash, which reads as "no data" for the one number that
    says how much is exposed in this book."""
    src = open("app.py").read()
    assert 'sum(float(r.get("margin $") or 0)' in src


def test_the_stop_column_is_silent_unless_the_stop_is_missing():
    """Operator, 2026-08-20: "remove the on mexc". It said what the book label
    already implies. But the column has a THIRD state — a rejected stop, which
    means real money is open with no protection — so the column keeps its space
    and only speaks for that."""
    src = open("app.py").read()
    assert '"" if dry or _pos.get("bracket", True)' in src
    assert '"NO STOP — RETRYING"' in src
    assert '"on MEXC"' not in src, "the noise is gone"

    import app
    assert app._tm_pos_cell("", "pill") == ""
    loud = app._tm_pos_cell("NO STOP — RETRYING", "pill")
    assert "ap-pill bad" in loud, "an unprotected position is red, not amber"


def test_the_close_column_is_dressed_as_the_tables_last_cell():
    """A Streamlit button cannot live inside a markdown grid, so Close is a
    sibling column and looked like it sat outside the table. It cannot be moved
    in, so the column carries the row hairline, the header band and the total
    fill, and the column gap is collapsed so the band is continuous."""
    css = __import__("app").TERMINAL_CSS
    import re
    assert re.search(r'\[data-testid="stHorizontalBlock"\]:has\(\.tm-pt\)\s*'
                     r'>\s*\[data-testid="stColumn"\]:last-child', css)
    assert '[data-testid="stHorizontalBlock"]:has(.tm-pt-h)' in css
    assert '[data-testid="stHorizontalBlock"]:has(.tm-pt-t)' in css
    assert "gap:0 !important" in css, "the gutter cut a notch through the band"


def test_backtest2_page_is_registered(app):
    assert "Backtest 2" in app.PAGES
    assert callable(app.render_backtest2_tab)


def test_bt2_deployed_reads_config_at_call_time(app, monkeypatch):
    """Backtest 2 injects EVERY live strategy on the selected coins/timeframes,
    and reads the settings file at run time — the config changed mid-task once
    and a page shipped claiming no deployed row while one was live."""
    from tradingagents import auto_trader as at

    monkeypatch.setitem(at.STRATEGY_SPECS, "mom15_4h_w",
                        {"interval": "Hour4", "threshold": 0.006,
                         "sl": 0.02, "tp": 0.08})
    monkeypatch.setitem(at.STRATEGY_SPECS, "trend50_30m_pi",
                        {"interval": "Min30", "threshold": None,
                         "sl": 0.02, "tp": 0.025})
    cfg = {"strategies": ["mom15_4h_w", "trend50_30m_pi"],
           "strategy_coins": {"mom15_4h_w": ["PI_USDT"],
                              "trend50_30m_pi": ["PI_USDT"]},
           "sizing": "martingale"}
    monkeypatch.setattr(at, "load_settings", lambda: cfg)
    monkeypatch.setattr(at, "sizing_for", lambda c: "martingale")

    dep = app._bt2_deployed(["PI_USDT"], ["30m", "4h"])
    got = {(d["coin"], d["tf"], d["signal"], d["sl"], d["tp"]) for d in dep}
    assert ("PI", "4h", "mom15", 2.0, 8.0) in got
    assert ("PI", "30m", "trend50", 2.0, 2.5) in got

    # a timeframe outside the page must not inject its strategy
    dep_1h = app._bt2_deployed(["PI_USDT"], ["1h"])
    assert dep_1h == []

    # nor a coin that was not selected
    dep_other = app._bt2_deployed(["APEX_USDT"], ["30m", "4h"])
    assert dep_other == []


def test_the_system_tiles_match_apexs_stat_card():
    """Measured off apex-django.dashboardpack.com's dashboard on 2026-08-20:
    `rounded-lg border border-border bg-card p-4 flex flex-col gap-3` — so 16px
    padding, 12px gap, 10px radius, --card ground, no shadow — with a 36x36 icon
    chip at 8px radius carrying its tone at ~10% alpha behind the full colour
    (theirs: rgba(22,163,74,.1) on rgb(22,163,74))."""
    import re

    import app
    css = app.TERMINAL_CSS
    m = re.search(r'\.tm-rib > div\{([^}]+)\}', css)
    assert m, "the tile rule is gone"
    tile = m.group(1)
    assert "padding:16px" in tile and "gap:12px" in tile
    assert "border-radius:var(--t-r)" in tile
    ic = re.search(r'\.tm-rib \.ic\{([^}]+)\}', css).group(1)
    assert "width:36px" in ic and "height:36px" in ic and "border-radius:8px" in ic
    n = re.search(r'\.tm-rib \.n\{([^}]+)\}', css).group(1)
    assert "font-size:30px" in n and "font-weight:700" in n
    lb = re.search(r'\.tm-rib \.l\{([^}]+)\}', css).group(1)
    assert "font-size:14px" in lb and "text-transform:none" in lb

    # the later "inner tiles" rule repainted them muted at 8px; it must not
    assert re.search(r'\.tm-rib > div\{\s*background:var\(--t-panel\);', css), \
        "the stat card is --card, not the muted step"

    head = app._tm_tile_head("Futures wallet", "$", "var(--t-amber)")
    assert "class='hd'" in head and "class='ic'" in head
    assert "color-mix(in oklab,var(--t-amber) 12%" in head, "tone at ~10% alpha"


def test_tables_have_a_border():
    """"also make border on tables" — one frame round the whole table with the
    corners clipped, plus the positions grid bordered edge by edge because it is
    built from Streamlit columns and has no single element to border."""
    import app
    css = app.TERMINAL_CSS
    assert ".tm-tbl{ border:1px solid var(--t-rule)" in css
    assert "border-radius:var(--t-r)" in css and "overflow:hidden" in css
    assert "border-left:1px solid var(--t-rule)" in css
    assert "border-right:1px solid var(--t-rule)" in css
    assert "border-top:1px solid var(--t-rule)" in css
    assert "border-bottom:1px solid var(--t-rule)" in css
    # and the wrapper is actually emitted
    out = app._tm_table((("a", "A", 1, "l", "text"),), [{"a": "x"}])
    assert out.startswith("<div class='tm-tbl'>") and out.endswith("</div>")


def test_backtest2_offers_the_archive_controls():
    """"where is the download in backtest 2?" — `render_market_data_section`
    holds DOWNLOAD/UPDATE for the permanent candle archive. Backtest 2 is the
    only backtest page now (V1 removed at the operator's request 2026-08-20),
    so it must carry the controls."""
    import inspect

    import app
    src = inspect.getsource(app.render_backtest2_tab)
    assert "render_market_data_section()" in src, \
        "render_backtest2_tab does not offer the archive controls"


def test_the_equity_curve_is_built_from_the_ledgers_own_exits():
    """Design 09 leads with the curve, so it must be the same source as every
    figure beside it — the ledger's exit rows — or the chart and the totals can
    disagree on the same screen."""
    import inspect

    import app
    src = inspect.getsource(app._an_equity)
    assert 'e.get("action") != "exit"' in src
    assert 'bool(e.get("dry_run")) is not dry' in src, "books never mix"


def test_the_curve_draws_a_real_zero_axis_and_takes_its_sign():
    import app
    up = app._an_curve([(1, 0.0), (2, 5.0), (3, 12.0)])
    dn = app._an_curve([(1, 0.0), (2, -5.0), (3, -12.0)])
    assert "stroke-dasharray" in up, "break-even is drawn, not implied"
    assert "var(--buy)" in up and "var(--sell)" not in up
    assert "var(--sell)" in dn and "var(--buy)" not in dn
    assert "aria-label" in up, "the curve names itself for a screen reader"
    # two points minimum, and it says so rather than drawing a lie
    assert "an-empty" in app._an_curve([(1, 1.0)])


def test_the_legend_swatch_takes_the_curves_colour():
    """It was hardcoded green while the curve was coral, because the book is
    down. A legend that disagrees with its own line is a false label."""
    src = open("app.py").read()
    assert "'var(--t-up)' if _last >= 0 else 'var(--t-dn)'" in src


def test_the_strategy_bars_rank_by_size_not_sign():
    """The biggest mover first whichever way it went — a list sorted by signed
    value buries the worst loser at the bottom where it gets skimmed past."""
    import app
    out = app._an_bars({
        "small_win": {"pnl": 2.0, "wins": 1, "losses": 0, "trades": 1},
        "big_loss": {"pnl": -40.0, "wins": 0, "losses": 4, "trades": 4},
        "mid_win": {"pnl": 16.0, "wins": 2, "losses": 1, "trades": 3},
        "never_traded": {"pnl": 0.0, "wins": 0, "losses": 0, "trades": 0}})
    assert out.index("big_loss") < out.index("mid_win") < out.index("small_win")
    assert "never_traded" not in out, "a strategy with no trades has no bar"
    assert "width:100.0%" in out, "the biggest mover sets the scale"
    assert app._an_bars({}).count("an-empty") == 1


def test_the_progress_figure_has_ONE_calculation():
    """The custom view first recovered the percentage by regexing the rendered
    bar's HTML — and got 0% on every row, because the markup separates the number
    from its target with &nbsp; rather than a space. Two readers of one figure
    means one function, not a regex over the other one's output."""
    import app
    assert app._tm_prog_calc(100, 110, 95, 104, 1) == (40.0, "TP")
    assert app._tm_prog_calc(100, 90, 105, 102, -1) == (40.0, "SL")
    assert app._tm_prog_calc(100, None, 95, 104, 1) is None, "no guessing"
    assert app._tm_prog_calc(100, 110, 95, 104, 0) is None, "no side, no bar"
    # the bar renders FROM the calc, so they cannot disagree
    assert "40%" in app._tm_progress(100, 110, 95, 104, 1)
    src = open("app.py").read()
    assert 'r["prog_pct"], r["prog_to"]' in src, "the row carries the numbers"
    assert '_re.search(r">(\\d+)%' not in src, "and nobody parses the markup back"


def test_the_view_owns_its_markup_and_holds_no_widgets():
    """The point of the rebuild: the table is mine, so nothing inside it can be a
    Streamlit widget — which is also what permanently ends the Close-button
    alignment problem. Interaction lives in one action bar underneath."""
    import app
    assert "MODERN_CSS" in dir(app)
    for cls in (".mv-hero", ".mv-row", ".mv-ring", ".mv-av", ".mv-pill", ".mv-str"):
        assert cls in app.MODERN_CSS, f"{cls} missing"
    assert "prefers-reduced-motion" in app.MODERN_CSS, "the pulse must be optional"
    src = open("app.py").read()
    # The close moved INTO the row on 2026-08-20 ("where is the close button in
    # open position?"). It is still not a widget inside our markup — it is an
    # anchor, which is how a designed table can own its own controls — and the
    # confirm that actually sends the order is a real button underneath.
    assert "class='mv-x'" in src and "href='?close=" in src
    assert 'key="mvx_confirm"' in src
    assert 'key="mv_close_pick"' not in src, "the dropdown it replaced is gone"


def test_a_stake_is_not_a_gain():
    """`at risk` printed +5.00 in green. Margin is what you put up, not what you
    made."""
    import app
    assert app._tm_pos_cell(5.0, "money0") == "5.00"
    assert "+" not in app._tm_pos_cell(5.0, "money0")
    assert "tm-up" not in app._tm_pos_cell(5.0, "money0")


def test_backtest2_shows_the_storage_panel():
    """Growth must be visible before it is a problem — and pure local means
    the panel lists THIS MACHINE's stores and nothing else ("i told you that
    its pure local")."""
    src = open("app.py").read()
    assert "def render_storage_panel" in src
    assert src.count("render_storage_panel()") >= 1
    body = src.split("def render_storage_panel", 1)[1].split("\ndef ", 1)[0]
    assert "parquet_store" in body, "disk stores must be listed"
    assert "pair rows" in body and "resume states" in body
    assert "trade ledger" in body and "deployments" in body
    assert "table_sizes" not in body, "no database in a pure-local panel"
    assert "pure local" in body


def test_the_browser_uses_one_date_format_everywhere():
    """`Aug 22, 2026 4:00PM`, the format the operator asked for twice.

    Python keeps it in positions_view.fmt_when. The browser had NO shared
    formatter, so six components each called toLocaleString() and rendered
    `8/22/2026, 4:00:00 PM` — a different format on every screen the API did
    not pre-format, including the runner's own job panel.
    """
    import pathlib
    import re

    src = pathlib.Path("webapp/src")
    offenders = []
    for f in list(src.rglob("*.tsx")) + list(src.rglob("*.ts")):
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if re.search(r"new Date\([^)]*\)\.toLocale", line):
                offenders.append(f"{f}:{i}")
    assert not offenders, (
        "these format a date in the browser instead of using fmtWhen:\n  "
        + "\n  ".join(offenders))

    api = (src / "lib" / "api.ts").read_text()
    assert "export function fmtWhenMs" in api and "export const fmtWhen" in api


def test_the_two_date_formatters_agree(tmp_path):
    """One in Python, one in TypeScript. They must not drift — the whole point
    is that a stamp reads the same wherever it is drawn."""
    import datetime as dt
    import json
    import shutil
    import subprocess

    from tradingagents.positions_view import fmt_when

    node = shutil.which("node")
    if not node:
        import pytest

        pytest.skip("node is not installed")

    cases = [dt.datetime(2026, 8, 22, 0, 5), dt.datetime(2026, 8, 22, 12, 0),
             dt.datetime(2026, 8, 22, 23, 59), dt.datetime(2026, 1, 1, 9, 30),
             dt.datetime(2026, 12, 31, 13, 7)]
    stamps = [c.timestamp() for c in cases]

    js = tmp_path / "p.mjs"
    api = "webapp/src/lib/api.ts"
    body = open(api, encoding="utf-8").read()
    start = body.index("const MONTHS")
    end = body.index("export const fmtWhen =")
    # lift the real implementation, not a copy of it
    lifted = (body[start:end].replace("export function", "function")
              .replace(": number | undefined | null", "")
              .replace(": string", ""))
    js.write_text(lifted + "\nconsole.log(JSON.stringify("
                  + json.dumps(stamps) + ".map(s => fmtWhenMs(s * 1000))));\n")
    out = subprocess.run([node, str(js)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == [fmt_when(s) for s in stamps]


def test_python_has_one_date_formatter_not_two():
    """market_sweep.fmt_stamp was a line-for-line copy of
    positions_view.fmt_when. Two copies of one rule is one rule waiting to
    drift, and this rule is "the operator asked for it twice"."""
    import inspect

    from tradingagents import market_sweep as msw, positions_view as pv

    src = inspect.getsource(msw.fmt_stamp)
    assert "fmt_when" in src, "fmt_stamp must delegate, not reimplement"
    assert "%b" not in src, "it is still formatting on its own"
    for ts in (1787371208, 1787326445.6, 0.0):
        assert msw.fmt_stamp(ts) == pv.fmt_when(ts)


def test_the_date_format_is_exactly_what_the_operator_asked_for():
    """`Aug 03, 2026 8:03pm`, given three times. Each part was wrong once:
    the day was unpadded, the meridiem was uppercase, and two API routes had
    hand-rolled copies with a `.replace(" 0", " ")` hack for a padded hour."""
    import datetime as dt

    from tradingagents.positions_view import fmt_when

    cases = {
        dt.datetime(2026, 8, 3, 20, 3): "Aug 03, 2026 8:03pm",
        dt.datetime(2026, 8, 22, 0, 5): "Aug 22, 2026 12:05am",
        dt.datetime(2026, 8, 22, 12, 0): "Aug 22, 2026 12:00pm",
        dt.datetime(2026, 1, 9, 9, 30): "Jan 09, 2026 9:30am",
        dt.datetime(2026, 12, 31, 13, 7): "Dec 31, 2026 1:07pm",
        dt.datetime(2026, 11, 5, 23, 59): "Nov 05, 2026 11:59pm",
    }
    for when, want in cases.items():
        assert fmt_when(when.timestamp()) == want, (
            f"{when} -> {fmt_when(when.timestamp())!r}, wanted {want!r}")


def test_no_module_formats_a_timestamp_by_hand():
    """Two API routes each had their own `%b %d, %Y %I:%M%p` plus a
    `.replace(" 0", " ")` to undo the padded hour. A copy is a rule that
    drifts, and this rule has now changed twice."""
    import pathlib

    offenders = []
    for f in pathlib.Path("tradingagents").rglob("*.py"):
        if f.name == "positions_view.py":
            continue                    # the one place it is allowed
        for i, line in enumerate(f.read_text().splitlines(), 1):
            # PARSING someone else's format (strptime) is fine — Twitter
            # sends what it sends. Only PRODUCING a stamp is the rule.
            # And a MONTH label ("Aug 2026") is not a timestamp: no clock
            # part, and the monthly columns are meant to read that way.
            if "strptime" in line:
                continue
            if "%b" in line and "%Y" in line and ("%M" in line or "%H" in line):
                offenders.append(f"{f}:{i}")
    assert not offenders, ("hand-rolled date formats:\n  "
                           + "\n  ".join(offenders))


def test_log_lines_carry_the_operator_date_format_too():
    """The Runner feed shows raw log lines, so `%(asctime)s` is a date on the
    operator's screen. basicConfig's default is `2026-08-22 19:27:03,488` —
    the exact compact stamp the rule bans, on every row. Fixing the message
    content but not the line's own timestamp is why this was asked a fourth
    time."""
    import io
    import logging

    from tradingagents.positions_view import WhenFormatter, fmt_when

    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setFormatter(WhenFormatter("%(asctime)s %(levelname)s %(message)s"))
    lg = logging.getLogger("fmt-probe")
    lg.handlers[:] = [h]
    lg.setLevel(logging.INFO)
    lg.propagate = False
    lg.info("scan PI_USDT")

    line = buf.getvalue().strip()
    assert " INFO scan PI_USDT" in line
    stamp = line.split(" INFO ")[0]
    import re

    assert re.fullmatch(r"[A-Z][a-z]{2} \d{2}, \d{4} \d{1,2}:\d{2}[ap]m", stamp), \
        f"log stamp is {stamp!r}"
    # and it is the SAME function, not another copy: the record's own creation
    # time, run through fmt_when, must reproduce the line exactly
    rec = logging.LogRecord("fmt-probe", logging.INFO, __file__, 1, "x", None, None)
    assert WhenFormatter().formatTime(rec) == fmt_when(rec.created)


def test_no_logger_is_configured_with_a_bare_asctime():
    """Every place that configures logging must set WhenFormatter, or that
    logger prints ISO stamps into a feed the operator reads."""
    import pathlib

    bad = []
    for f in [pathlib.Path("spx_bot.py"), *pathlib.Path("tradingagents").rglob("*.py")]:
        if not f.exists():
            continue
        text = f.read_text()
        if "%(asctime)s" in text and "WhenFormatter" not in text:
            bad.append(str(f))
    assert not bad, ("these log ISO timestamps into an operator-facing log:\n  "
                     + "\n  ".join(bad))
