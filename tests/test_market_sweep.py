"""The Back Test module's promise: a refresh must equal a full re-run.

If continuing a backtest ever diverges from running it whole, every number the
Back Test tab shows after a refresh is wrong — silently. So the equality is
tested directly, on synthetic candles, including the case that broke it twice:
a position still open at the boundary.
"""
import pytest

from tradingagents import auto_trader as at
from tradingagents import market_sweep as msw


def _bars(n=900, seed=7):
    """Deterministic zig-zag with a drift, enough to trigger entries."""
    import math

    import pandas as pd
    close = [100 + i * 0.02 + 6 * math.sin(i / 11.0 + seed) for i in range(n)]
    return pd.DataFrame({
        "Date": pd.date_range("2026-01-01", periods=n, freq="h"),
        "Open": close,
        "High": [c + 0.5 for c in close],
        "Low": [c - 0.5 for c in close],
        "Close": close})


def _dirs(n, every=40):
    d = [0] * n
    for i in range(30, n, every):
        d[i] = 1 if (i // every) % 2 == 0 else -1
    return d


KEY = "_msw_test"
SPEC = {"interval": "Min60", "bar_seconds": 3600, "tp": 0.02, "sl": 0.01}


@pytest.fixture(autouse=True)
def _spec():
    at.STRATEGY_SPECS[KEY] = dict(SPEC)
    yield
    at.STRATEGY_SPECS.pop(KEY, None)


def _run(df, dirs, **kw):
    return at.backtest_strategy(KEY, df, 10.0, fee=0.0004, slippage=0.0003,
                                sizing="martingale", dirs=dirs, tp=0.02,
                                sl=0.01, liq_move_pct=4.5, keep_log=False,
                                **kw)


@pytest.mark.parametrize("cut", [300, 455, 620, 880])
def test_continuing_equals_running_it_whole(cut):
    df = _bars()
    dirs = _dirs(len(df))
    whole = _run(df, dirs, resume={})
    first = _run(df.iloc[:cut], dirs[:cut], resume={})
    ctx = msw.CONTEXT_BARS
    lo = max(0, cut - ctx)
    tail = df.iloc[lo:].reset_index(drop=True)
    second = _run(tail, dirs[lo:], resume=first["state"], start_at=cut - lo)
    assert second["trades"] == whole["trades"]
    assert second["wins"] == whole["wins"]
    assert second["profit"] == pytest.approx(whole["profit"], abs=0.01)
    assert second["max_dd"] == pytest.approx(whole["max_dd"], abs=0.01)
    assert second["monthly"] == whole["monthly"]


def test_a_position_open_at_the_boundary_is_carried_not_closed():
    """The bug that made a refresh read 912 trades instead of 76: a carried
    trade must be continued once, not re-entered on every following bar."""
    import pandas as pd
    n = 900
    # dead flat after the entry, so neither barrier can ever fire
    df = pd.DataFrame({"Date": pd.date_range("2026-01-01", periods=n, freq="h"),
                       "Open": [100.0] * n, "High": [100.0] * n,
                       "Low": [100.0] * n, "Close": [100.0] * n})
    dirs = [0] * n
    dirs[100] = 1
    first = _run(df.iloc[:200], dirs[:200], resume={})
    assert first["trades"] == 0, "the trade has not closed yet"
    assert first["state"]["open"], "so it must be handed on as open"
    tail = df.iloc[100:].reset_index(drop=True)
    second = _run(tail, dirs[100:], resume=first["state"], start_at=100)
    assert second["trades"] <= 1, "a carried trade must not re-enter each bar"


def test_funding_of_a_carried_trade_starts_at_its_own_entry():
    df = _bars()
    dirs = [0] * len(df)
    dirs[50] = 1
    ms = int(df["Date"].iloc[0].value // 1_000_000)
    hour = 3_600_000
    funding = [{"settle_ms": ms + 60 * hour, "rate": 0.01},
               {"settle_ms": ms + 200 * hour, "rate": 0.01}]
    whole = _run(df, dirs, resume={}, funding=funding)
    first = _run(df.iloc[:300], dirs[:300], resume={}, funding=funding)
    tail = df.iloc[100:].reset_index(drop=True)
    second = _run(tail, dirs[100:], resume=first["state"], start_at=200,
                  funding=funding)
    assert second["funding_total"] == pytest.approx(whole["funding_total"],
                                                    abs=1e-6)


def test_state_without_rows_is_re_measured_not_skipped():
    src = open("tradingagents/market_sweep.py").read()
    assert "not pair_rows(coin, tf)" in src
    assert "states, last_ms = {}, 0" in src


def test_the_tab_exists_and_is_wired():
    import app

    assert "Back Test" in app.PAGES
    assert hasattr(app, "render_backtest_tab")
    src = open("app.py").read()
    assert 'page == "Back Test"' in src


def test_the_store_keeps_losing_rows_too(monkeypatch, tmp_path):
    """"i want everything stored" — a loser is a measurement, not noise. The
    trade floor still applies; profitability must not."""
    src = open("tradingagents/market_sweep.py").read()
    assert 'r["profit"] <= 0' not in src, \
        "run_pair still throws away losing rows"
    assert "MIN_TRADES" in src, "the trade floor must survive"
