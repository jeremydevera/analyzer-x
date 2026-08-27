"""The candle cache keeps VOLUME, or every volume rule silently abstains.

Found Aug 27, 2026 while explaining why 15 of the 30 new confluence rules had
no rows in a 22,478,876-row sweep. The cache is written by refresh_candles as
{"t","o","h","l","c"} -- no volume -- and cached_candles rebuilds a DataFrame
with Date/Open/High/Low/Close. run_pair then does:

    vol_l = [...] if "Volume" in frame.columns else None

so every pair served from that cache hands the signals `volume=None`, and the
module contract says a rule whose stream is missing ABSTAINS with zeros. The
comment three lines above that very code names the consequence: "they appear in
the signal list and can never produce a row -- a silent hole in the grid."

Measured in the finished sweep: cf_mom (no volume needed) has 294,394 rows,
while cf_emarsi (needs volume) has 7,700 -- only the pairs that happened to be
fetched fresh rather than read from cache -- and cf_donch and cf_maobv have
NONE. The same hole takes obv20, cmf20, mfi14, force13, volspike, volclimax and
relvolbrk from the older library.

The parquet copy of the same candles has always had Volume (BTC_USDT-1h:
9,479 bars, every one non-zero), so nothing needs re-downloading.
"""
import json

import pandas as pd
import pytest

from tradingagents import market_sweep as msw, parquet_store as pqs


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(msw, "CANDLES", tmp_path / "candles")
    monkeypatch.setattr(pqs, "CANDLES", tmp_path / "pq")
    (tmp_path / "candles").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _frame(n=6, vol=True):
    ts = [1_787_000_000_000 + i * 3_600_000 for i in range(n)]
    d = {"Date": pd.to_datetime(ts, unit="ms"),
         "Open": [1.0 + i for i in range(n)], "High": [2.0 + i for i in range(n)],
         "Low": [0.5 + i for i in range(n)], "Close": [1.5 + i for i in range(n)]}
    if vol:
        d["Volume"] = [100.0 * (i + 1) for i in range(n)]
    return pd.DataFrame(d)


def test_the_cache_stores_volume(store):
    """A fresh save must write it, so the cache is self-sufficient next time."""
    msw.save_candles_cache("APEX_USDT", "1h", _frame())
    raw = json.loads((msw.CANDLES / "APEX_USDT-1h.json").read_text())
    assert "v" in raw, "volume must be written to the cache"
    assert raw["v"] == [100.0, 200.0, 300.0, 400.0, 500.0, 600.0]


def test_reading_it_back_gives_a_volume_column(store):
    msw.save_candles_cache("APEX_USDT", "1h", _frame())
    got = msw.cached_candles("APEX_USDT", "1h")
    assert "Volume" in got.columns
    assert list(got["Volume"]) == [100.0, 200.0, 300.0, 400.0, 500.0, 600.0]


def test_an_old_cache_file_borrows_volume_from_the_parquet_copy(store):
    """4,985 cache files were written before this fix. The parquet store has
    the same bars WITH volume, so they are usable immediately -- no refetch."""
    msw.CANDLES.mkdir(parents=True, exist_ok=True)
    f = _frame()
    old = {"t": [int(x) for x in f["Date"].to_numpy().astype("datetime64[ms]").astype("int64")],
           "o": list(f["Open"]), "h": list(f["High"]),
           "l": list(f["Low"]), "c": list(f["Close"])}          # no "v"
    (msw.CANDLES / "APEX_USDT-1h.json").write_text(json.dumps(old))
    pqs.save_candles("APEX_USDT", "1h", f)
    got = msw.cached_candles("APEX_USDT", "1h")
    assert "Volume" in got.columns, "the parquet copy must fill the gap"
    assert list(got["Volume"]) == list(f["Volume"])


def test_a_missing_parquet_copy_is_not_an_error(store):
    """No volume anywhere: the frame comes back without the column and the
    volume rules abstain, exactly as the contract says -- but nothing raises."""
    msw.CANDLES.mkdir(parents=True, exist_ok=True)
    f = _frame(vol=False)
    old = {"t": [int(x) for x in f["Date"].to_numpy().astype("datetime64[ms]").astype("int64")],
           "o": list(f["Open"]), "h": list(f["High"]),
           "l": list(f["Low"]), "c": list(f["Close"])}
    (msw.CANDLES / "APEX_USDT-1h.json").write_text(json.dumps(old))
    got = msw.cached_candles("APEX_USDT", "1h")
    assert got is not None and len(got) == 6
    assert "Volume" not in got.columns


def test_a_parquet_copy_of_the_wrong_length_is_ignored(store):
    """Aligned by position, so a mismatch must be refused rather than pasted
    onto the wrong bars."""
    msw.CANDLES.mkdir(parents=True, exist_ok=True)
    f = _frame(n=6)
    old = {"t": [int(x) for x in f["Date"].to_numpy().astype("datetime64[ms]").astype("int64")],
           "o": list(f["Open"]), "h": list(f["High"]),
           "l": list(f["Low"]), "c": list(f["Close"])}
    (msw.CANDLES / "APEX_USDT-1h.json").write_text(json.dumps(old))
    pqs.save_candles("APEX_USDT", "1h", _frame(n=9))        # different length
    got = msw.cached_candles("APEX_USDT", "1h")
    assert "Volume" in got.columns, "aligned on Date, so a longer copy still works"
    assert list(got["Volume"]) == [100.0, 200.0, 300.0, 400.0, 500.0, 600.0]


def test_refresh_writes_the_cache_through_one_function():
    """One writer, so the cache and its reader cannot drift again."""
    import inspect

    src = inspect.getsource(msw.refresh_candles)
    assert "save_candles_cache(" in src
    assert '"t": [int(x)' not in src, "the JSON layout belongs in one place"


def test_a_cache_without_volume_is_refetched_in_full(store, monkeypatch):
    """The delta path cannot add volume to bars already on disk, so a pair whose
    cache predates volume must be fetched whole -- once."""
    import json as _json

    f = _frame(n=300, vol=False)
    old = {"t": [int(x) for x in f["Date"].to_numpy().astype("datetime64[ms]").astype("int64")],
           "o": list(f["Open"]), "h": list(f["High"]),
           "l": list(f["Low"]), "c": list(f["Close"])}
    (msw.CANDLES / "APEX_USDT-1h.json").write_text(_json.dumps(old))

    fetched = []
    fresh = _frame(n=300, vol=True)
    # patch the real module: refresh_candles imports it inside the function, so
    # a sys.modules swap after import would not be seen
    from tradingagents.dataflows import mexc_futures as fx

    def klines(symbol, interval, limit):
        fetched.append((symbol, interval, limit))
        return fresh

    monkeypatch.setattr(fx, "klines", klines)
    monkeypatch.setattr("tradingagents.auto_trader._closed_bars", lambda df, bs: df)

    df, added, source = msw.refresh_candles("APEX_USDT", "1h", days=60)
    assert fetched, "a volume-less cache must trigger a full fetch"
    assert source == "fetch", f"expected a full fetch, got {source}"
    assert "Volume" in df.columns
    raw = _json.loads((msw.CANDLES / "APEX_USDT-1h.json").read_text())
    assert raw.get("v"), "and the cache now carries volume for next time"
