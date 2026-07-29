"""New Crypto tab — MEXC new-listing screener with per-coin agent analysis.

Kept out of app.py, which already carries the whole single-run screen. The pure
helpers here (config building, instrument context, row formatting) are unit
tested without a Streamlit runtime; render_new_crypto_tab() is the only part
that touches st.*.
"""

from __future__ import annotations

import time
from copy import deepcopy

# Fundamentals is omitted rather than disabled: a three-week-old memecoin has no
# filings, and giving that analyst nothing to read only feeds placeholders into
# the debate. Mirrors how the CLI filters analysts for crypto.
CRYPTO_ANALYSTS = ("market", "social", "news")


def build_crypto_config(base: dict, *, provider: str, deep_model: str,
                        quick_model: str, debate_rounds: int,
                        risk_rounds: int) -> dict:
    """Config for a new-coin run: MEXC prices, Yahoo news, Twitter on.

    Returns a copy — the caller's DEFAULT_CONFIG must stay untouched so a later
    stock run in the same process still routes prices to yfinance.
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
    cfg["include_twitter"] = True
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


def verdict_key(symbol: str, date: str) -> str:
    """Session-state key so each coin/date verdict survives analyzing another coin."""
    return f"verdict:{symbol}:{date}"


def verdict_label(signal: str | None) -> str:
    """Render a signal as its table chip."""
    return {"BUY": "▲ BUY", "SELL": "▼ SELL", "HOLD": "■ HOLD"}.get(
        (signal or "").strip().upper(), "—"
    )


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
        "age": f"{coin.age_days}d",
        "price": price,
        "change": f"{coin.change_pct:+.2f}%",
        "volume": _fmt_volume(coin.quote_volume),
    }


def status_caption(result) -> str:
    """One line describing sweep coverage. Never hides what could not be checked."""
    parts = [f"{result.scanned} MEXC USDT pairs scanned"]
    if result.unresolved:
        parts.append(f"{result.unresolved} could not be checked (rate-limited)")
    if result.hidden_by_volume:
        parts.append(f"{result.hidden_by_volume} hidden by the volume floor")
    if result.stale:
        parts.append("data is STALE — refresh failed, showing the last good sweep")
    elif result.fetched_at:
        age_min = max(0, int((time.time() - result.fetched_at) / 60))
        parts.append(f"data {age_min} min old")
    return " · ".join(parts)


# Column widths for the screener grid, shared by the header and every row.
_WIDTHS = [1.0, 2.0, 1.1, 0.6, 1.2, 0.9, 1.0, 1.0, 0.9]
_HEADINGS = ("SYMBOL", "NAME", "LISTED", "AGE", "PRICE", "24H", "VOLUME",
             "VERDICT", "")


def render_new_crypto_tab(*, model: str, provider: str, trade_date: str,
                          base_config: dict, debate_rounds: int, risk_rounds: int,
                          configure_cfg, streaming_runner) -> None:
    """Render the screener table and run one coin's analysis on demand.

    ``configure_cfg`` and ``streaming_runner`` are injected from app.py so this
    module never imports app.py, which would re-execute its Streamlit setup.
    """
    import streamlit as st

    from tradingagents.dataflows import mexc

    st.markdown(
        '<div style="font-family:var(--font-display);font-size:13px;'
        'letter-spacing:.08em;text-transform:uppercase;color:var(--muted);'
        f'margin-bottom:4px">New crypto · MEXC · first traded within '
        f'{mexc.WINDOW_DAYS} days</div>',
        unsafe_allow_html=True)

    c1, c2, c3 = st.columns([1.4, 1, 1])
    min_vol = c1.number_input("Min 24h volume (USDT)", min_value=0.0,
                              value=mexc.DEFAULT_MIN_QUOTE_VOLUME, step=10_000.0,
                              key="crypto_min_vol")
    include_all = c2.checkbox("Show all (incl. dust)", value=False,
                              key="crypto_include_all")
    scan = c3.button("↻ Scan MEXC", key="crypto_refresh",
                     help="Sweep all MEXC USDT pairs now (~2 minutes)")

    # Streamlit re-runs every tab body on every interaction, so the sweep must be
    # explicit: rendering it automatically would cost ~1700 requests each time
    # anyone touched the app, including users who never open this tab.
    if scan:
        try:
            with st.spinner("Scanning ~1700 MEXC pairs — this takes about 2 minutes…"):
                result = mexc.screen_new_listings(
                    min_quote_volume=min_vol, include_all=include_all,
                    force_refresh=True)
        except mexc.MexcUnavailable as exc:
            st.error(f"Cannot reach MEXC: {exc}")
            return
    else:
        result = mexc.cached_listings(min_quote_volume=min_vol,
                                      include_all=include_all)

    if result is None:
        st.info("No scan yet. Press **↻ Scan MEXC** to sweep the exchange "
                "for coins listed in the last 30 days (about 2 minutes).")
        return

    st.caption(status_caption(result))
    if not result.coins:
        st.info("No MEXC coins matched the window and volume floor.")
        return

    header = st.columns(_WIDTHS)
    for col, label in zip(header, _HEADINGS):
        col.markdown(
            f"<div style='font-family:var(--font-mono);font-size:11px;"
            f"letter-spacing:.08em;color:var(--faint)'>{label}</div>",
            unsafe_allow_html=True)

    to_run = None
    for coin in result.coins:
        cells = row_cells(coin)
        cols = st.columns(_WIDTHS)
        cols[0].markdown(f"**{cells['symbol']}**")
        cols[1].write(cells["name"])
        cols[2].write(cells["listed"])
        cols[3].write(cells["age"])
        cols[4].write(cells["price"])
        colour = "#22C55E" if coin.change_pct >= 0 else "#EF4444"
        cols[5].markdown(f"<span style='color:{colour}'>{cells['change']}</span>",
                         unsafe_allow_html=True)
        cols[6].write(cells["volume"])
        stored = st.session_state.get(verdict_key(coin.symbol, trade_date), "")
        cols[7].markdown(f"**{verdict_label(stored)}**")
        if cols[8].button("Analyze", key=f"analyze_{coin.symbol}"):
            to_run = coin

    if to_run is None:
        return

    st.markdown('<div class="ta-rule"></div>', unsafe_allow_html=True)
    st.markdown(f"### {to_run.base} · {to_run.name}")
    cfg = build_crypto_config(
        base_config, provider=provider, deep_model=model, quick_model=model,
        debate_rounds=debate_rounds, risk_rounds=risk_rounds)
    configure_cfg(cfg, model)
    signal = streaming_runner(
        to_run.symbol, trade_date, list(CRYPTO_ANALYSTS), cfg, provider, model,
        asset_type="crypto", instrument_context=coin_instrument_context(to_run))
    st.session_state[verdict_key(to_run.symbol, trade_date)] = signal or ""
