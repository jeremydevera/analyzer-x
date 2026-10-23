"""The v3 smoke run reads one coin and summarises it; under test every venue
call is a stand-in, so nothing reaches the network."""
import time

import pandas as pd

from tradingagents import v3_smoke as sm

H = 3_600_000
BASE = 1_790_000_000_000 - (1_790_000_000_000 % H)
N = 400
T0 = BASE - N * H


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


class Fx:
    """Flat hours (O 100, H 100.6, L 99.4, C 100). `highs` and `lows` set single
    candles' high and low by index; `minute_bars` maps a candle index to
    {minute: (high, low)}; `anchored` ends the frame with the FORMING hour."""

    def __init__(self, highs=None, lows=None, minute_bars=None, anchored=False):
        last = (int(time.time() * 1000) // H) * H if anchored else None
        t0 = (last - (N - 1) * H) if anchored else T0
        self.t0 = t0
        hi = dict.fromkeys(range(N), 100.6)
        lo = dict.fromkeys(range(N), 99.4)
        hi.update(highs or {})
        lo.update(lows or {})
        self.df = pd.DataFrame({
            "Date": pd.to_datetime([t0 + k * H for k in range(N)], unit="ms"),
            "Open": [100.0] * N, "High": [hi[k] for k in range(N)],
            "Low": [lo[k] for k in range(N)], "Close": [100.0] * N, "Volume": [1.0] * N})
        self.minute_bars = minute_bars or {}
        self.asked_since = None

    def klines(self, sym, iv, limit):
        return self.df.tail(limit).reset_index(drop=True)

    def minutes(self, sym, start_s, end_s):
        rows = []
        for k, per_min in self.minute_bars.items():
            for m, (h, lo) in per_min.items():
                rows.append((pd.Timestamp((self.t0 + k * H) // 1000 + 60 * m, unit="s"), h, lo))
        if not rows:
            return pd.DataFrame({"Date": pd.to_datetime([], unit="s"), "High": [], "Low": []})
        return pd.DataFrame(sorted(rows), columns=["Date", "High", "Low"])

    def funding_history(self, sym, since_ms=None):
        self.asked_since = since_ms
        return [{"settle_ms": self.t0 + k * 8 * H, "rate": 0.0, "cycle_h": 8}
                for k in range(0, N // 8)]            # every 8 h, from before the window

    def contract_spec(self, sym):
        return {"contractSize": 0.01, "minVol": 1, "maintenanceMarginRate": 0.005,
                "maxLeverage": 20, "minLeverage": 1}


def t_of(k: int) -> int:
    return T0 + k * H


def _patch(mp, signals):
    import tradingagents.auto_trader as at
    from tradingagents import cost_store

    mp.setattr(at, "_dirs_for_backtest",
               lambda key, hi, *a, **k: [1 if i in signals else 0 for i in range(len(hi))])
    mp.setattr(cost_store, "engine_book", lambda *a, **k: cost_store.empty())
    mp.setattr(at, "maker_fee_floor", lambda *a, **k: 0.0002)      # Gate's two floors, so a swap shows
    mp.setattr(at, "fee_floor", lambda *a, **k: 0.00075)


EXIT = {"kind": "fixed", "tp": 0.02, "sl": 0.01}


def test_the_window_money_and_missed_orders_match_hand_arithmetic(monkeypatch):
    """Signals: 5 (lead-in, must not trade), 310 + 320 (TP wins), 340 (touch only = missed,
    its market twin wins), 360 (stopped)."""
    from tradingagents import v3_smoke as sm
    from tradingagents.positions_view import fmt_when

    _patch(monkeypatch, {5, 310, 320, 340, 360})
    fx = Fx(highs={7: 103.0, 312: 103.0, 322: 103.0, 342: 103.0}, lows={341: 100.0, 362: 98.5})
    got = sm.run("TEST_USDT", "1h", "bb20", EXIT, days=10, fx=fx)
    # the walk starts at the window, not at the first candle
    assert got["trades"] == 3 and got["wins"] == 2 and got["losses"] == 1
    assert got["start"] == fmt_when(t_of(300) // 1000)
    # two wins: 100 x 2% less maker in and out (0.02% each way) = +1.96 each; one stop:
    # -1.00 less maker in, taker out and the flat gap (0.0002 + 0.00075 + 0.0003) = -1.125
    assert abs(got["profit"] - (2 * 1.96 - 1.125)) < 0.011
    # the touch is not a fill: one missed order, its market twin (taker + flat gap in, maker out)
    assert got["missed"] == 1 and got["missed_entered"] == 1
    assert abs(got["missed_pnl"] - (2.0 - 100 * (0.00075 + 0.0003 + 0.0002))) < 0.011
    assert got["counts"]["cost_unmeasured"] >= 1
    # funding is asked from a day before the window and carried to the walk
    assert fx.asked_since == (t_of(300) // 1000 - 86400) * 1000
    assert got["counts"]["funding_estimated"] == 0


def test_the_window_ends_where_the_forming_candle_starts(monkeypatch):
    from tradingagents import v3_smoke as sm
    from tradingagents.positions_view import fmt_when

    _patch(monkeypatch, set())
    fx = Fx(anchored=True)
    got = sm.run("TEST_USDT", "1h", "bb20", EXIT, days=10, fx=fx)
    last_open_s = (fx.t0 + (N - 1) * H) // 1000          # the hour still being drawn
    assert got["end"] == fmt_when(last_open_s), "the window ends where the forming hour starts"


def test_minute_bars_reach_the_walk_without_candle_fallbacks(monkeypatch):
    """A fill and a target found in 1-minute bars: no candle-rule fallbacks."""
    from tradingagents import v3_smoke as sm

    _patch(monkeypatch, {310})
    flat = dict.fromkeys(range(60), (100.3, 99.7))
    minute_bars = {k: dict(flat) for k in range(300, 400)}
    minute_bars[311][30] = (100.3, 99.9)         # trades through 100.0: the order fills here
    minute_bars[312][10] = (102.5, 99.7)         # the target is traded through here
    fx = Fx(minute_bars=minute_bars, highs={312: 102.5})    # the candle holds its minutes' high
    got = sm.run("TEST_USDT", "1h", "bb20", EXIT, days=10, fx=fx)
    assert got["trades"] == 1 and got["wins"] == 1
    assert got["counts"]["fill_by_candle"] == 0 and got["counts"]["settled_by_candle"] == 0


def test_the_coverage_line_prints_before_the_trades_line(monkeypatch, capsys):
    from tradingagents import v3_smoke as sm

    monkeypatch.setattr(sm, "run", lambda *a, **k: {
        "sym": "T_USDT", "tf": "1h", "signal": "bb20", "exit": {}, "start": "S", "end": "E",
        "coverage": 0.5, "trades": 2, "wins": 1, "losses": 1, "profit": 0.84, "missed": 0,
        "missed_entered": 0, "missed_pnl": 0.0, "counts": {"missed": 0}})
    assert sm.main(["T_USDT", "1h", "bb20", "fixed:0.02:0.01"]) == 0
    out = capsys.readouterr().out
    assert out.index("order books cover 50.0%") < out.index("2 trades, 1 won, 1 lost")
