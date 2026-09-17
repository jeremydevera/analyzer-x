"""A download that trusts a short cache measures a short story.

Sep 17, 2026: the Candles v2 download stored 3,505 one-minute bars (2.4 days)
for ARKM_USDT and GLM_USDT while MEXC serves 30 days. `klines()` extends a
cached frame at the TAIL only, so a cache seeded by a small call never grew.
`klines_backfill` pages backwards from the cached oldest bar; `refresh_candles`
asks for it whenever the frame is shorter than the timeframe's cap.
"""
import pandas as pd
import pytest

from tradingagents import market_sweep as msw
from tradingagents.dataflows import mexc_futures as fx

T0 = 1_789_516_800          # Sep 16, 2026 00:00 UTC, seconds


def _frame(start_s: int, n: int, per: int = 60):
    ts = [start_s + i * per for i in range(n)]
    return pd.DataFrame({"Date": pd.to_datetime(ts, unit="s"),
                         "Open": [1.0] * n, "High": [1.1] * n, "Low": [0.9] * n,
                         "Close": [1.0] * n, "Volume": [5.0] * n})


def test_backfill_pages_backwards_until_the_venue_runs_dry(monkeypatch, tmp_path):
    monkeypatch.setattr(fx, "KLINE_DISK_DIR", tmp_path)
    monkeypatch.setattr(fx, "_kline_db_store", lambda *a, **k: None)
    # the short cache: 100 minutes ending at T0 + 100 min
    fx._kline_disk_save("ARKM_USDT", "Min1", _frame(T0, 100))
    asked = []

    def fake_page(symbol, interval, limit, end):
        asked.append(end)
        # MEXC answers the closed bars at or before `end`, on the minute — so a
        # request ending one second before a bar gets the bar a minute earlier
        end -= end % 60
        # the venue holds 250 minutes before the cached start, then nothing
        floor = T0 - 250 * 60
        start = max(floor, end - limit * 60 + 60)
        if end < floor:
            return None
        n = (end - start) // 60 + 1
        return _frame(start, n)

    monkeypatch.setattr(fx, "_klines_page", fake_page)
    monkeypatch.setattr(fx, "_KLINE_PAGE", 100)
    out = fx.klines_backfill("ARKM_USDT", "Min1", want=1000)
    assert len(out) == 350, "100 cached + 250 the venue still had"
    assert int(out["Date"].iloc[0].timestamp()) == T0 - 250 * 60
    assert asked[0] == T0 - 1, "the first page ends just before the cached oldest bar"
    assert len(asked) == 4, "three pages of 100, then the empty page that stops it"
    # and the DISK now holds the whole thing, so the next klines() call starts full
    again = fx._kline_disk_load("ARKM_USDT", "Min1")
    assert len(again) == 350


def test_backfill_stops_at_want(monkeypatch, tmp_path):
    monkeypatch.setattr(fx, "KLINE_DISK_DIR", tmp_path)
    monkeypatch.setattr(fx, "_kline_db_store", lambda *a, **k: None)
    fx._kline_disk_save("GLM_USDT", "Min1", _frame(T0, 100))
    monkeypatch.setattr(fx, "_klines_page",
                        lambda s, i, limit, end: _frame(end - limit * 60 + 60, limit))
    monkeypatch.setattr(fx, "_KLINE_PAGE", 100)
    out = fx.klines_backfill("GLM_USDT", "Min1", want=250)
    assert len(out) == 250, "asked for 250, got exactly 250 — no page more than needed"


def test_refresh_candles_fills_a_short_history_from_the_front(monkeypatch, tmp_path):
    """The download's own path: a cached 1m frame far shorter than the 44,000
    cap asks the venue for older bars; a full one does not."""
    import tradingagents.auto_trader as at

    monkeypatch.setattr(msw, "CANDLES", tmp_path / "candles")
    monkeypatch.setattr(msw, "HOME", tmp_path)
    monkeypatch.setattr(msw, "STATES", tmp_path / "state")
    short = _frame(T0, 3_505)
    calls = []
    monkeypatch.setattr(fx, "klines", lambda s, i, n: short)
    monkeypatch.setattr(fx, "klines_backfill",
                        lambda s, i, want: calls.append(want) or _frame(T0 - 40_000 * 60, 43_505))
    monkeypatch.setattr(at, "_closed_bars", lambda df, bs: df)
    df, added, source = msw.refresh_candles("ARKM_USDT", "1m", days=365)
    assert calls == [44_000], "asked the venue for the cap, once"
    assert len(df) == 43_505 and added == 43_505
    # a frame at the cap asks nothing more
    calls.clear()
    full = _frame(T0 - 44_000 * 60, 44_000)
    monkeypatch.setattr(fx, "klines", lambda s, i, n: full)
    msw.refresh_candles("XPIN_USDT", "1m", days=365)
    assert calls == [], "a full history is not re-asked"


def test_the_v2_download_has_its_own_pending_ledger():
    from tradingagents import pending_ledger as pl

    assert "candles_v2" in pl.KINDS
    assert str(pl.path("candles_v2")).endswith("candles_v2.json") or \
        "candles_v2" in str(pl.path("candles_v2"))
    with pytest.raises(ValueError):
        pl.path("candles_v3")
