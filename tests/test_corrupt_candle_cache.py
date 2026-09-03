"""A half-written candle cache must never poison a pair for ever.

Found by running the operator's own RETRY FAILED button on Sep 03, 2026. Their
5,117-pair update had ended with 26 lost pairs; the retry recovered 25 of them
(690 bars) and ENPHSTOCK_USDT 1d failed three times with

    Expecting value: line 1 column 1 (char 0)

MEXC serves that contract perfectly — the same request by hand returned 2,068
bytes of daily bars. The empty body was OURS: `~/.tradingagents/backtest/
candles/ENPHSTOCK_USDT-1d.json` was **597 NUL bytes**, the shape a file takes
on Windows when a process is killed after the size is allocated and before the
data reaches the disk. `start.py` kills detached jobs with `taskkill /T`, so
that is a routine death here.

Two faults, one file:

* `save_candles_cache` wrote IN PLACE, so a death mid-write destroys the bars
  that were already there.
* `cached_candles` let the parse error out, so the pair's own DOWNLOAD reported
  it. The pair went onto `lost.json` as a wire failure, every update fetched it
  again, hit the same local file, and no button in the UI could ever clear it.

Exactly 1 of 5,131 cache files was damaged, which is why this took a month to
surface.
"""
import json
import os

import pandas as pd
import pytest

from tradingagents import market_sweep as msw


def _frame(n=3, vol=True):
    d = {"Date": pd.to_datetime([1_787_000_000_000 + i * 86_400_000
                                 for i in range(n)], unit="ms"),
         "Open": [1.0] * n, "High": [2.0] * n, "Low": [0.5] * n,
         "Close": [1.5] * n}
    if vol:
        d["Volume"] = [10.0] * n
    return pd.DataFrame(d)


def _path(sym, tf):
    return msw.CANDLES / f"{sym}-{tf}.json"


@pytest.fixture(autouse=True)
def _dir():
    msw.CANDLES.mkdir(parents=True, exist_ok=True)


def test_a_cache_file_of_nul_bytes_reads_as_no_cache(capsys):
    """The exact file. It must answer "nothing cached", not raise."""
    f = _path("ENPHSTOCK_USDT", "1d")
    f.write_bytes(b"\x00" * 597)

    assert msw.cached_candles("ENPHSTOCK_USDT", "1d") is None

    assert not f.exists(), "the unreadable bytes must not be read again"
    quarantined = f.with_suffix(".json.corrupt")
    assert quarantined.exists() and quarantined.stat().st_size == 597, \
        "kept, so it can be looked at once"
    out = capsys.readouterr().out
    assert "ENPHSTOCK_USDT 1d" in out and "unreadable" in out, \
        "silence here is what made this look like a venue failure"


def test_a_truncated_cache_file_reads_as_no_cache():
    f = _path("TRUNC_USDT", "15m")
    f.write_text('{"t":[1787000000000,17870008', encoding="utf-8")
    assert msw.cached_candles("TRUNC_USDT", "15m") is None
    assert f.with_suffix(".json.corrupt").exists()


def test_a_good_cache_file_still_comes_back_whole():
    msw.save_candles_cache("GOOD_USDT", "1h", _frame(4))
    got = msw.cached_candles("GOOD_USDT", "1h")
    assert got is not None and len(got) == 4
    assert list(got["Volume"]) == [10.0] * 4
    assert not _path("GOOD_USDT", "1h").with_suffix(".json.corrupt").exists()


def test_the_cache_is_written_atomically(monkeypatch):
    """A death between the first byte and the last must leave the OLD bars
    intact — the whole point of the file is that a pair is not re-downloaded."""
    msw.save_candles_cache("ATOMIC_USDT", "4h", _frame(5))
    before = _path("ATOMIC_USDT", "4h").read_bytes()

    real = os.replace

    def die(src, dst):
        raise OSError("killed between the write and the rename")

    monkeypatch.setattr(os, "replace", die)
    with pytest.raises(OSError):
        msw.save_candles_cache("ATOMIC_USDT", "4h", _frame(9))
    monkeypatch.setattr(os, "replace", real)

    assert _path("ATOMIC_USDT", "4h").read_bytes() == before, \
        "the old bars survived a failed write"
    got = msw.cached_candles("ATOMIC_USDT", "4h")
    assert got is not None and len(got) == 5


def test_no_half_file_is_left_behind():
    msw.save_candles_cache("CLEAN_USDT", "30m", _frame(3))
    strays = [p.name for p in msw.CANDLES.glob("*.tmp")]
    assert strays == [], strays
    assert json.loads(_path("CLEAN_USDT", "30m").read_text())["t"]


def test_a_corrupt_cache_makes_the_pair_download_in_full(monkeypatch):
    """The behaviour the operator sees: the pair repairs itself on the next
    update instead of failing for ever."""
    from tradingagents.dataflows import mexc_futures as fx

    f = _path("ENPHSTOCK_USDT", "1d")
    f.write_bytes(b"\x00" * 597)
    asked = []

    def klines(symbol, interval, limit, **kw):
        asked.append((symbol, interval, limit))
        return _frame(6)

    monkeypatch.setattr(fx, "klines", klines)
    monkeypatch.setattr(fx, "funding_history", lambda *a, **k: [])

    df, added, src = msw.refresh_candles("ENPHSTOCK_USDT", "1d", days=365)

    assert asked, "it must have gone to the venue, which serves this pair fine"
    assert len(df) == 6 and added == 6
    assert src == "fetch", f"a full download, not a delta: {src}"
    assert msw.cached_candles("ENPHSTOCK_USDT", "1d") is not None, \
        "and the repaired file is readable"
