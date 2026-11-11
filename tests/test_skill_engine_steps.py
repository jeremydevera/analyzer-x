"""One engine for the skill strategies: the backtest, the daily shard and the skill rooms' follower all
run `skill_bt.step()`, so a room trades exactly what its backtest measured (skill rooms, Task 1)."""
import numpy as np
import pandas as pd
import pytest

from tradingagents import skill_bt as sb, skill_ta as sta

NOTIONAL = sb.NOTIONAL


def _df(n=600, seed=7, start="2026-01-01"):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.006, n)))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.003, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.003, n))
    idx = pd.date_range(start, periods=n, freq="1h")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                         "volume": rng.uniform(100, 1000, n)}, index=idx)


def _old_walk(df, sigs, *, stop, fee, slip, target=None):
    """A frozen copy of walk() as it was before step() existed (Nov 10, 2026)."""
    close = df["close"].to_numpy()
    when = sb._ms(df.index).tolist()
    trades, pos = [], None

    def close_out(i, px):
        side = 1 if pos["dir"] == "long" else -1
        move = (px - pos["px"]) / pos["px"] * side
        pnl = NOTIONAL * move - NOTIONAL * fee - NOTIONAL * (px / pos["px"]) * fee
        trades.append({"entry_ms": pos["t"], "exit_ms": when[i], "side": side,
                       "entry_px": pos["px"], "exit_px": px, "pnl": round(pnl, 4),
                       "why": pos.get("why_out", "SIGNAL"), "stop": stop, "target": target})

    for i, sig in enumerate(sigs):
        if sig is None:
            continue
        c = close[i]
        buy, sell = c * (1 + slip), c * (1 - slip)
        force = won = False
        if pos is not None:
            ret = (c - pos["px"]) / pos["px"] * (1 if pos["dir"] == "long" else -1)
            force = ret <= -stop
            won = target is not None and ret >= target
        mine = sig.exit and getattr(sig, "exit_dir", None) in (None, pos and pos["dir"])
        if pos is not None and (mine or force or won):
            pos["why_out"] = "SL" if force else "TP" if won else "SIGNAL"
            close_out(i, sell if pos["dir"] == "long" else buy)
            pos = None
        if sig.entry and pos is None:
            pos = {"t": when[i], "dir": sig.direction, "px": buy if sig.direction == "long" else sell}
    if pos is not None:
        c = close[-1]
        pos["why_out"] = "END"
        close_out(len(close) - 1, c * (1 - slip) if pos["dir"] == "long" else c * (1 + slip))
    return trades


def _settings():
    out = [(name, ss[0], None) for name, ss in sb.GRID.items()]
    out += [(name, ss[0], sta.TARGETS.get(name)) for name, ss in sta.GRID.items()]
    return out


FEE, SLIP = 0.00075, 0.0003


def test_walk_without_funding_is_unchanged():
    df = _df()
    n = 0
    for name, params, r in _settings():
        sigs = sb.signals(df, name, params)
        for stop in sb.STOPS:
            tg = round(stop * r, 6) if r else None
            new = sb.walk(df, sigs, stop=stop, fee=FEE, slip=SLIP, target=tg)
            old = _old_walk(df, sigs, stop=stop, fee=FEE, slip=SLIP, target=tg)
            assert new == old, (name, stop)
            assert all("fund" not in t for t in new)
            n += len(new)
    assert n > 20                      # the comparison was not over empty lists


def _end_close(pos, df, *, stop, fee, slip, target=None):
    if pos is None:
        return []
    c = df["close"].to_numpy()[-1]
    px = c * (1 - slip) if pos["dir"] == "long" else c * (1 + slip)
    t = sb.close_position(pos, px, sb._ms(df.index).tolist()[-1], why="END", stop=stop, fee=fee,
                          target=target)
    return [t]


def test_run_plus_end_close_is_walk():
    df = _df()
    for name, params, r in _settings():
        sigs = sb.signals(df, name, params)
        stop = sb.STOPS[0]
        tg = round(stop * r, 6) if r else None
        trades, pos = sb.run(df, sigs, stop=stop, fee=FEE, slip=SLIP, target=tg)
        assert trades + _end_close(pos, df, stop=stop, fee=FEE, slip=SLIP, target=tg) == \
            sb.walk(df, sigs, stop=stop, fee=FEE, slip=SLIP, target=tg)


def test_stepping_one_candle_at_a_time_is_walk():
    df = _df()
    close = df["close"].to_numpy()
    when = sb._ms(df.index).tolist()
    for name, params, r in _settings():
        sigs = sb.signals(df, name, params)
        stop = sb.STOPS[1]
        tg = round(stop * r, 6) if r else None
        trades, pos = [], None
        for i, sig in enumerate(sigs):
            pos, done = sb.step(pos, sig, close=close[i], when_ms=when[i], bar_ms=3_600_000, stop=stop,
                                fee=FEE, slip=SLIP, target=tg)
            if done:
                trades.append(done)
        want_t, want_pos = sb.run(df, sigs, stop=stop, fee=FEE, slip=SLIP, target=tg, bar_ms=3_600_000)
        assert trades == want_t
        assert pos == want_pos


def test_a_none_signal_leaves_everything_alone():
    pos = {"t": 1, "dir": "long", "px": 100.0, "fill_ms": 2}
    assert sb.step(pos, None, close=1.0, when_ms=5, bar_ms=10, stop=0.01, fee=FEE, slip=SLIP) == (pos, None)
    assert sb.step(None, None, close=1.0, when_ms=5, bar_ms=10, stop=0.01, fee=FEE, slip=SLIP) == (None, None)


class _Sig:
    def __init__(self, entry=False, exit=False, direction="long"):
        self.entry, self.exit, self.direction = entry, exit, direction


def _funding_trade(direction):
    f = sb.Funding([{"settle_ms": 900_000, "rate": 0.5}, {"settle_ms": 1_500_000, "rate": 0.001},
                    {"settle_ms": 1_900_000, "rate": 0.002}, {"settle_ms": 2_500_000, "rate": 0.7}])
    bar = 100_000
    pos, done = sb.step(None, _Sig(entry=True, direction=direction), close=100.0, when_ms=900_000,
                        bar_ms=bar, stop=0.5, fee=0.0, slip=0.0, funding=f)
    assert pos["fill_ms"] == 1_000_000 and done is None
    pos, done = sb.step(pos, _Sig(exit=True, direction=direction), close=100.0, when_ms=1_800_000,
                        bar_ms=bar, stop=0.5, fee=0.0, slip=0.0, funding=f)
    return pos, done


def test_funding_is_charged_inside_the_hold():
    # fill 1,000,000 -> 1,900,000: the settlement at 900,000 is outside, 1,500,000 and 1,900,000 inside
    pos, t = _funding_trade("long")
    assert pos is None
    assert t["fund"] == pytest.approx(-0.3) and t["pnl"] == pytest.approx(-0.3)
    pos, t = _funding_trade("short")
    assert t["fund"] == pytest.approx(0.3) and t["pnl"] == pytest.approx(0.3)


def test_funding_paid_is_an_open_closed_window():
    f = sb.Funding([{"settle_ms": 10, "rate": 1.0}, {"settle_ms": 20, "rate": 2.0}, {"settle_ms": 30, "rate": 4.0}])
    assert f.paid(10, 30) == 6.0 and f.paid(0, 10) == 1.0 and f.paid(30, 99) == 0.0 and f.paid(5, 5) == 0.0
    assert sb.Funding([]).paid(0, 10**12) == 0.0


def test_walk_with_funding_adds_fund_to_every_trade():
    df = _df()
    sigs = sb.signals(df, "sma_crossover", sb.GRID["sma_crossover"][0])
    when = sb._ms(df.index).tolist()
    f = sb.Funding([{"settle_ms": when[0] + k * 8 * 3_600_000, "rate": 0.0001} for k in range(200)])
    plain = sb.walk(df, sigs, stop=0.03, fee=FEE, slip=SLIP)
    funded = sb.walk(df, sigs, stop=0.03, fee=FEE, slip=SLIP, funding=f, bar_ms=3_600_000)
    assert len(plain) == len(funded) > 2
    assert any(t["fund"] != 0 for t in funded)
    for a, b in zip(plain, funded):
        assert b["pnl"] == pytest.approx(a["pnl"] + b["fund"], abs=2e-4)


def _same(a, b):
    if a is None or b is None:
        return a is None and b is None
    return (a.entry, a.exit, a.direction, getattr(a, "exit_dir", None)) == \
           (b.entry, b.exit, b.direction, getattr(b, "exit_dir", None))


def test_signal_at_equals_the_backtests_signal():
    df = _df(500, seed=11)
    for name in ("sma_crossover", "rsi_reversal", "bollinger_bands", "breakout"):
        params = sb.GRID[name][0]
        want = sb.signals(df, name, params)
        seen = 0
        for i in range(len(df)):
            got = sb.signal_at(df.iloc[: i + 1], name, params, 400)
            assert _same(got, want[i]), (name, i)
            seen += got is not None and (got.entry or got.exit)
        assert seen > 0, name
    for name in ("ta_wyckoff_spring", "ta_rsi_divergence", "ta_vwap_reversion", "ta_ma_pullback", "bf_momentum"):
        params = sta.GRID[name][0]
        for i in range(399, len(df), 7):
            want = sta.STRATEGIES[name].signals_all(df.iloc[i - 399: i + 1], params)[-1]
            got = sb.signal_at(df.iloc[: i + 1], name, params, 400)
            assert _same(got, want), (name, i)


def test_the_frame_is_the_one_the_shard_reads():
    from tradingagents import skill_frames

    assert skill_frames.BARS == {"15m": 2880, "30m": 2880, "1h": 2160, "4h": 1080, "1d": 730}
    import inspect

    sig = inspect.signature(skill_frames.frame)
    assert list(sig.parameters) == ["sym", "tf", "bars", "end_ms"]
    shard = open(".github/scripts/skill_shard.py", encoding="utf-8").read()
    assert "from tradingagents.skill_frames import BARS, frame" in shard
    assert "def frame(" not in shard


def test_the_frame_keeps_only_candles_opened_before_end_ms(monkeypatch):
    import time

    from tradingagents import skill_frames
    from tradingagents.dataflows import exchange as fx

    now_s = int(time.time() // 3600 * 3600)
    dates = pd.to_datetime([now_s - 3600 * k for k in range(60, 0, -1)], unit="s")
    raw = pd.DataFrame({"Date": dates, "Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.5, "Volume": 10.0})
    asked = []
    monkeypatch.setattr(fx, "klines", lambda sym, iv, n: (asked.append(n), raw)[1])
    full = skill_frames.frame("BTC_USDT", "1h", 40)
    assert len(full) == 40 and list(full.columns) == ["open", "high", "low", "close", "volume"]
    cut_ms = int(dates[30].value // 1_000_000) if dates.unit == "ns" else int(dates[30].timestamp() * 1000)
    cut = skill_frames.frame("BTC_USDT", "1h", 40, end_ms=cut_ms)
    assert len(cut) == 30 and sb._ms(cut.index)[-1] < cut_ms         # candle 30 opened AT end_ms: out
    assert asked[1] > asked[0]            # it read further back to make up for the candles it cuts away
