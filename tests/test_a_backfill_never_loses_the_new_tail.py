"""Filling the history BACKWARDS may not throw away the bars just fetched
(docs/RCA.md RCA-2026-09-18-N).

`Sep 18, 2026 4:07pm`, XPIN_USDT 1h: `refresh_candles` fetched 522 new hours
(to Sep 18 07:00), then `klines_backfill` returned the disk cache grown at the
front — 8,602 bars ending **Aug 27 13:00** — and the code took it because it
was LONGER. The operator's own row #LG9NSU4B was re-measured over candles that
stopped three weeks earlier, so its trade log ended `Aug 27, 2026 4:00pm`
twice in a row, and they said so twice.
"""
from __future__ import annotations

import pandas as pd
import pytest

from tradingagents import market_sweep as msw
from tradingagents.dataflows import mexc_futures as fx

H = 3_600_000


def _frame(first_ms: int, n: int, px: float = 1.0) -> pd.DataFrame:
    t = [first_ms + i * H for i in range(n)]
    return pd.DataFrame({
        "Date": pd.to_datetime(t, unit="ms"),
        "Open": [px] * n, "High": [px] * n, "Low": [px] * n,
        "Close": [px] * n, "Volume": [10.0] * n})


T0 = 1_756_857_600_000          # Sep 03, 2025 00:00 UTC


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(msw, "CANDLES", tmp_path / "candles")
    (tmp_path / "candles").mkdir()
    monkeypatch.setattr(msw, "_paths", lambda: None)
    return tmp_path


def test_a_longer_but_older_backfill_never_shortens_the_history(store, monkeypatch):
    """The exact shape: a 150-bar cache ending LATE, a 310-bar backfill
    ending EARLY. The result must hold both ends."""
    have = _frame(T0, 150)                      # >100 bars: the DELTA path
    msw.save_candles_cache("XPIN_USDT", "1h", have)

    fresh = _frame(T0 + 150 * H, 12)            # 12 NEW hours on the end
    old_long = _frame(T0 - 160 * H, 310)        # longer, but ends at T0 + 149h

    monkeypatch.setattr(fx, "klines", lambda s, i, n: pd.concat([have, fresh]))
    monkeypatch.setattr(fx, "klines_backfill", lambda s, i, n: old_long)
    # no forming-bar trimming in this test: every bar is closed
    import tradingagents.auto_trader as at
    monkeypatch.setattr(at, "_closed_bars", lambda df, bs: df)

    df, added, source = msw.refresh_candles("XPIN_USDT", "1h", days=3650)
    assert source == "delta"
    assert df["Date"].iloc[-1] == fresh["Date"].iloc[-1], \
        "the newest bar fetched must survive the backfill"
    assert df["Date"].iloc[0] == old_long["Date"].iloc[0], \
        "and the older history the backfill found must survive too"
    assert len(df) == 322, len(df)
    assert added >= 12


def test_the_stored_file_ends_where_the_venue_ends(store, monkeypatch):
    """What the operator sees: the pair file on disk, after the refresh."""
    have = _frame(T0, 150)
    msw.save_candles_cache("XPIN_USDT", "1h", have)
    fresh = _frame(T0 + 150 * H, 12)
    monkeypatch.setattr(fx, "klines", lambda s, i, n: pd.concat([have, fresh]))
    monkeypatch.setattr(fx, "klines_backfill", lambda s, i, n: _frame(T0 - 100 * H, 250))
    import tradingagents.auto_trader as at
    monkeypatch.setattr(at, "_closed_bars", lambda df, bs: df)

    msw.refresh_candles("XPIN_USDT", "1h", days=3650)
    on_disk = msw.cached_candles("XPIN_USDT", "1h")
    assert on_disk["Date"].iloc[-1] == fresh["Date"].iloc[-1]


def test_a_backfill_that_raises_still_keeps_the_new_tail(store, monkeypatch):
    have = _frame(T0, 150)
    msw.save_candles_cache("XPIN_USDT", "1h", have)
    fresh = _frame(T0 + 150 * H, 12)
    monkeypatch.setattr(fx, "klines", lambda s, i, n: pd.concat([have, fresh]))

    def boom(*a, **k):
        raise RuntimeError("Requests are too frequent")

    monkeypatch.setattr(fx, "klines_backfill", boom)
    import tradingagents.auto_trader as at
    monkeypatch.setattr(at, "_closed_bars", lambda df, bs: df)

    df, _added, _src = msw.refresh_candles("XPIN_USDT", "1h", days=3650)
    assert df["Date"].iloc[-1] == fresh["Date"].iloc[-1]
