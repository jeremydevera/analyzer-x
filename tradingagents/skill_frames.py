"""THE CANDLE FRAME THE SKILL STRATEGIES ARE WALKED OVER (moved out of .github/scripts/skill_shard.py,
Nov 10, 2026).

The daily GitHub shard, the backtest and the skill rooms' follower all read candles through this ONE
function, so a room sees the candles its backtest saw. `end_ms` keeps only candles that OPENED before
it - the follower's midnight warm-up reads the frame as it stood at 12:00am UTC.
"""
from __future__ import annotations

# candles a timeframe is walked over: 30 days of 15m, 60 of 30m, 90 of 1h, 180 of 4h, two years of 1d
BARS = {"15m": 2880, "30m": 2880, "1h": 2160, "4h": 1080, "1d": 730}


def frame(sym: str, tf: str, bars: int | None = None, *, end_ms: int | None = None):
    import time

    import pandas as pd

    import tradingagents.auto_trader as at
    from tradingagents import backtest_report as br
    from tradingagents.dataflows import exchange as fx

    n = BARS[tf] if bars is None else int(bars)
    iv, bs, _cap = br.TFS[tf]
    extra = 0
    if end_ms is not None:        # candles opened since end_ms are cut away: read that many more
        extra = max(0, int((time.time() * 1000 - end_ms) // (bs * 1000)) + 1)
    df = at._closed_bars(fx.klines(sym, iv, n + 5 + extra), bs)
    if end_ms is not None:
        opened = pd.DatetimeIndex(pd.to_datetime(df["Date"]).to_numpy()).as_unit("ms").asi8
        df = df[opened < int(end_ms)]
    df = df.tail(n)
    return pd.DataFrame({"open": df["Open"].to_numpy(), "high": df["High"].to_numpy(),
                         "low": df["Low"].to_numpy(), "close": df["Close"].to_numpy(),
                         "volume": df["Volume"].to_numpy()},
                        index=pd.DatetimeIndex(pd.to_datetime(df["Date"]).to_numpy()))
