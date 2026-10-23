"""The v3 smoke run reads one coin and summarises it; under test every venue
call is a stand-in, so nothing reaches the network."""
import pandas as pd

from tradingagents import v3_smoke as sm

H = 3_600_000


class FakeFx:
    """400 closed hours at 100 (high 100.6, low 99.4), no minutes, no funding."""

    def __init__(self, n: int = 400):
        t0 = 1_790_000_000_000 - (1_790_000_000_000 % H) - n * H
        self.df = pd.DataFrame({
            "Date": pd.to_datetime([t0 + k * H for k in range(n)], unit="ms"),
            "Open": [100.0] * n, "High": [100.6] * n, "Low": [99.4] * n,
            "Close": [100.0] * n, "Volume": [1.0] * n})

    def klines(self, sym, iv, limit):
        return self.df.tail(limit).reset_index(drop=True)

    def minutes(self, sym, start_s, end_s):
        return pd.DataFrame({"Date": pd.to_datetime([], unit="s"), "High": [], "Low": []})

    def funding_history(self, sym, **kw):
        return []

    def contract_spec(self, sym):
        return {"contractSize": 0.01, "minVol": 1, "maintenanceMarginRate": 0.005,
                "maxLeverage": 20, "minLeverage": 1}


def test_the_smoke_run_summarises_one_coin_without_the_network(monkeypatch):
    import tradingagents.auto_trader as at
    from tradingagents import cost_store

    monkeypatch.setattr(at, "_dirs_for_backtest",
                        lambda key, hi, *a, **k: [1 if i % 10 == 0 else 0
                                                  for i in range(len(hi))])
    monkeypatch.setattr(cost_store, "engine_book", lambda *a, **k: cost_store.empty())
    got = sm.run("TEST_USDT", "1h", "bb20", {"kind": "fixed", "tp": 0.02, "sl": 0.01},
                 days=10, fx=FakeFx())
    assert got["coverage"] == 0.0, "no recorded book covers nothing"
    # the first signal's order fills on the candle (no minutes) and never
    # reaches 99.0 or 102.0, so it is still open at the last candle
    assert got["trades"] == 1 and got["counts"]["fill_by_candle"] == 1
    assert got["start"].endswith(("am", "pm")) and ", 2026 " in got["start"]


def test_the_exit_is_read_from_its_short_form():
    assert sm.exit_spec("fixed:0.02:0.01") == {"kind": "fixed", "tp": 0.02, "sl": 0.01}
    assert sm.exit_spec("trail:3:50") == {"kind": "trail", "atr_mult": 3.0, "ma_n": 50}
    assert sm.exit_spec("snap:3:24") == {"kind": "snap", "mean_n": 20, "stop_atr": 3.0,
                                         "max_bars": 24}
