"""Batch classic_a of the reviewed GitHub repos' strategies (tradingagents/gh_strats/classic_a.py):
je-suis-tm/quant-trading, Log-zz-ikIO/crypto-signal and QuantConnect/Research, Nov 18, 2026."""
import numpy as np
import pandas as pd
import pytest

from tradingagents.gh_strats import classic_a as ca

CLOCK = ("gh_qt_dual_thrust", "gh_qt_london")


def _df(n=900, seed=5, freq="1h", vol=0.003, stars=True):
    """A calm random walk (about a crypto 15m candle's move) whose candles open a little away from
    the last close and whose high and low hold both the open and the close. `stars` plants a
    textbook shooting star and its confirming candle every 150 candles: the repo's rule needs an
    opening gap above the last close, which a random walk (like a 24-hour market) almost never
    makes - measured Nov 18, 2026 on a month of BTC minutes: 0 stars on 5m, 15m and 1h."""
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, vol, n)))
    opn = np.r_[close[0], close[:-1]] * np.exp(rng.normal(0, vol / 6, n))
    top, bot = np.maximum(opn, close), np.minimum(opn, close)
    high = top * (1 + np.abs(rng.normal(0, vol / 2, n)))
    low = bot * (1 - np.abs(rng.normal(0, vol / 2, n)))
    if stars:
        for j in range(120, n - 2, 150):
            x = close[j - 2]
            close[j - 1] = opn[j - 1] = high[j - 1] = low[j - 1] = x * 1.002     # a rising close
            opn[j], close[j] = x * 1.005, x * 1.005 * (1 - 1e-7)               # a tiny red body
            low[j], high[j] = close[j], x * 1.02                                 # no lower wick
            opn[j + 1], close[j + 1] = close[j], x * 1.0                         # no higher high/close
            high[j + 1], low[j + 1] = x * 1.01, x * 0.99
    idx = pd.date_range("2026-01-01", periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({"open": opn, "high": high, "low": low, "close": close,
                         "volume": rng.lognormal(3, 0.6, n)}, index=idx)


def _key(s):
    return None if s is None else (s.entry, s.direction if s.entry else None, s.exit, s.exit_dir)


@pytest.mark.parametrize("name,freq", [(n, "1h") for n in ca.GRID] + [(n, "15min") for n in CLOCK])
def test_no_signal_reads_a_later_candle(name, freq):
    df = _df(700, freq=freq)
    strat = ca.STRATEGIES[name]
    for params in ca.GRID[name]:
        whole = [_key(s) for s in strat.signals_all(df, params)]
        assert len(whole) == len(df)
        for cut in (260, 333, 401, 520, 699):
            part = [_key(s) for s in strat.signals_all(df.iloc[:cut], params)]
            assert part == whole[:cut], (name, params, cut)


@pytest.mark.parametrize("name", list(ca.GRID))
def test_every_strategy_trades_on_a_moving_market(name):
    df = _df(2000, seed=12, freq="15min" if name in CLOCK else "1h")
    n = sum(bool(s and s.entry) for p in ca.GRID[name] for s in ca.STRATEGIES[name].signals_all(df, p))
    assert n > 0, name


@pytest.mark.parametrize("name", CLOCK)
@pytest.mark.parametrize("freq", ["4h", "1D"])
def test_clock_rules_do_not_trade_on_big_candles(name, freq):
    df = _df(300, freq=freq)
    for p in ca.GRID[name]:
        assert all(s is None for s in ca.STRATEGIES[name].signals_all(df, p))


@pytest.mark.parametrize("freq", ["15min", "30min", "1h"])
def test_london_enters_only_in_the_first_half_hour_and_leaves_by_five(freq):
    df = _df(3000, seed=3, freq=freq)
    sig = ca.STRATEGIES["gh_qt_london"].signals_all(df, ca.GRID["gh_qt_london"][0])
    entries = [df.index[i] for i, s in enumerate(sig) if s and s.entry]
    assert entries
    assert all(t.hour == 8 and t.minute < 30 for t in entries)
    bar = df.index[1] - df.index[0]
    exits = [(df.index[i] + bar) for i, s in enumerate(sig) if s and s.exit]
    assert all(t.hour < 17 or (t.hour == 17 and t.minute == 0) for t in exits)


def test_dual_thrust_closes_everything_at_the_session_end():
    df = _df(3000, seed=4, freq="30min")
    p = ca.GRID["gh_qt_dual_thrust"][0]
    sig = ca.STRATEGIES["gh_qt_dual_thrust"].signals_all(df, p)
    bar = pd.Timedelta("30min")
    for i, s in enumerate(sig):
        if s and s.entry:
            t = df.index[i]
            assert 8 <= t.hour < 17, t                     # entries only inside 8am-5pm UTC
    held = 0
    for i, s in enumerate(sig):
        if s is None:
            continue
        if s.exit:
            held = 0
        if s.entry:
            held = 1
        if (df.index[i] + bar).hour == 17 and (df.index[i] + bar).minute == 0:
            assert held == 0 or s.exit


def test_a_shooting_star_is_shorted_one_candle_late_and_held_at_most_seven():
    df = _df(1000, seed=7)
    sig = ca.STRATEGIES["gh_qt_shooting_star"].signals_all(df, ca.GRID["gh_qt_shooting_star"][0])
    entries = [i for i, s in enumerate(sig) if s and s.entry]
    assert set(range(121, 998, 150)) <= set(entries)       # the candle AFTER each planted star
    assert all(sig[i].direction == "short" for i in entries)
    for i in entries:
        out = next(k for k in range(i + 1, len(df)) if sig[k].exit)
        assert out - i <= 7 and sig[out].exit_dir == "short"


# ------------------------------------------------- hand-written copies of the repos' own code

def test_macd_is_the_scripts_own_rule():
    df = _df(800)
    for p in ca.GRID["gh_qt_macd"]:
        ma1, ma2 = p["ma1"], p["ma2"]
        s = pd.DataFrame({"Close": df["close"].to_numpy()})        # MACD Oscillator backtest.py
        s["ma1"] = s["Close"].rolling(window=ma1, min_periods=1, center=False).mean()
        s["ma2"] = s["Close"].rolling(window=ma2, min_periods=1, center=False).mean()
        s["positions"] = 0
        s.loc[ma1:, "positions"] = np.where(s["ma1"][ma1:] >= s["ma2"][ma1:], 1, 0)
        want = s["positions"].diff().to_numpy()
        got = ca.STRATEGIES["gh_qt_macd"].signals_all(df, p)
        for i in range(ma2, len(df)):
            assert bool(got[i].entry) == (want[i] == 1), (p, i)
            assert bool(got[i].exit) == (want[i] == -1), (p, i)


def test_parabolic_sar_is_the_scripts_own_loop():
    df = _df(600)
    new = pd.DataFrame({"High": df["high"].to_numpy(), "Low": df["low"].to_numpy(),
                        "Close": df["close"].to_numpy()})                # Parabolic SAR backtest.py
    initial_af, step_af, end_af = 0.02, 0.02, 0.2
    for col in ("trend", "sar", "real sar", "ep", "af"):
        new[col] = 0.0
    new.at[1, "trend"] = 1 if new["Close"][1] > new["Close"][0] else -1
    new.at[1, "sar"] = new["High"][0] if new["trend"][1] > 0 else new["Low"][0]
    new.at[1, "real sar"] = new["sar"][1]
    new.at[1, "ep"] = new["High"][1] if new["trend"][1] > 0 else new["Low"][1]
    new.at[1, "af"] = initial_af
    for i in range(2, len(new)):
        temp = new["sar"][i - 1] + new["af"][i - 1] * (new["ep"][i - 1] - new["sar"][i - 1])
        if new["trend"][i - 1] < 0:
            new.at[i, "sar"] = max(temp, new["High"][i - 1], new["High"][i - 2])
            temp = 1 if new["sar"][i] < new["High"][i] else new["trend"][i - 1] - 1
        else:
            new.at[i, "sar"] = min(temp, new["Low"][i - 1], new["Low"][i - 2])
            temp = -1 if new["sar"][i] > new["Low"][i] else new["trend"][i - 1] + 1
        new.at[i, "trend"] = temp
        if new["trend"][i] < 0:
            temp = min(new["Low"][i], new["ep"][i - 1]) if new["trend"][i] != -1 else new["Low"][i]
        else:
            temp = max(new["High"][i], new["ep"][i - 1]) if new["trend"][i] != 1 else new["High"][i]
        new.at[i, "ep"] = temp
        if np.abs(new["trend"][i]) == 1:
            temp = new["ep"][i - 1]
            new.at[i, "af"] = initial_af
        else:
            temp = new["sar"][i]
            if new["ep"][i] == new["ep"][i - 1]:
                new.at[i, "af"] = new["af"][i - 1]
            else:
                new.at[i, "af"] = min(end_af, new["af"][i - 1] + step_af)
        new.at[i, "real sar"] = temp
    want = pd.Series(np.where(new["real sar"] < new["Close"], 1, 0)).diff().to_numpy()
    got = ca.STRATEGIES["gh_qt_psar"].signals_all(df, ca.GRID["gh_qt_psar"][0])
    assert np.allclose(ca.qt_psar(df), new["real sar"].to_numpy())
    for i in range(5, len(df)):
        assert bool(got[i].entry) == (want[i] == 1), i
        assert bool(got[i].exit) == (want[i] == -1), i


def test_rsi_is_the_scripts_own_smoothed_rsi_and_rule():
    df = _df(800)
    n = 14

    def smma(series, n):                              # RSI Pattern Recognition backtest.py
        output = [series[0]]
        for i in range(1, len(series)):
            output.append((output[-1] * (n - 1) + series[i]) / n)
        return output

    delta = df["close"].diff().dropna()
    up = np.where(delta > 0, delta, 0)
    down = np.where(delta < 0, -delta, 0)
    rs = np.divide(smma(up, n), smma(down, n))
    rsi = np.zeros(len(df))
    rsi[n:] = (100 - 100 / (1 + rs))[n - 1:]
    positions = np.select([rsi < 30, rsi > 70], [1, -1], default=0)
    want = pd.Series(positions).diff().to_numpy()
    got = ca.STRATEGIES["gh_qt_rsi"].signals_all(df, ca.GRID["gh_qt_rsi"][0])
    assert np.allclose(ca.qt_rsi(df["close"], n), rsi)
    trades = 0
    for i in range(n + 1, len(df)):
        was, now = positions[i - 1], positions[i]
        assert bool(got[i].entry) == (now != 0 and now != was), i
        if got[i].entry:
            trades += 1
            assert got[i].direction == ("long" if now == 1 else "short"), i
        assert bool(got[i].exit) == (was != 0 and now != was), i
        if got[i].exit:
            assert got[i].exit_dir == ("long" if was == 1 else "short"), i
    assert trades and np.any(want != 0)


def test_crypto_signal_rsi_is_ta_libs_rsi():
    """TA-Lib's RSI: the first average is the plain mean of 14 changes, then Wilder's smoothing."""
    df = _df(400)
    c = df["close"].to_numpy()
    d = np.diff(c)
    g, l_ = np.clip(d, 0, None), np.clip(-d, 0, None)
    want = np.full(len(c), np.nan)
    ag, al = g[:14].sum() / 14, l_[:14].sum() / 14
    want[14] = 100 * ag / (ag + al)
    for k in range(14, len(d)):
        ag, al = (ag * 13 + g[k]) / 14, (al * 13 + l_[k]) / 14
        want[k + 1] = 100 * ag / (ag + al)
    assert np.allclose(ca.talib_rsi(df["close"], 14), want, equal_nan=True)
    got = ca.STRATEGIES["gh_cs_rsi"].signals_all(df, ca.GRID["gh_cs_rsi"][0])
    for i in range(15, len(df)):
        assert bool(got[i].entry) == (want[i] <= 30), i
        assert bool(got[i].exit) == (want[i] >= 70), i


# ------------------------------------------------- the tables

def test_the_tables_are_complete_and_small():
    names = set(ca.STRATEGIES)
    for table in (ca.GRID, ca.TARGETS, ca.REPO_OF, ca.RULE_OF):
        assert set(table) == names
    assert set(ca.STOPS) <= names
    assert all(n.startswith(("gh_qt_", "gh_cs_", "gh_qc_")) for n in names)
    assert all(1 <= len(v) <= 2 for v in ca.GRID.values())
    assert sum(len(v) for v in ca.GRID.values()) <= 24
    assert set(ca.REPO_OF.values()) == {"je-suis-tm/quant-trading", "Log-zz-ikIO/crypto-signal",
                                        "QuantConnect/Research"}
    assert "je-suis-tm/quant-trading: Pair trading" in ca.NOT_PORTED


def test_the_package_loads_this_batch():
    import tradingagents.gh_strats as g

    assert "classic_a" in g.LOADED
    for name in ca.STRATEGIES:
        assert g.STRATEGIES[name] is ca.STRATEGIES[name]
    assert g.STOPS["gh_qt_london"] == (0.005,) and g.STOPS["gh_qt_macd"] == g.DEFAULT_STOPS
