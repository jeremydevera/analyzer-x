"""A bar with no signal must be marked seen, like any other.

Leaving it unmarked made the runner re-evaluate the same quiet candle every
few seconds until it aged past the staleness limit, so every quiet hour
emitted a `stale_skip` at HH:30. 282 of 341 skips in the operator's ledger
carried "age 30 min" — the feed looked like the bot was missing most of its
checks when it had examined every one and simply found no trade.
"""
import pandas as pd

import tradingagents.auto_trader as at


def _bars(n=300, px=100.0):
    """Flat candles — no momentum, so no signal on any bar."""
    t0 = pd.Timestamp.utcnow().tz_localize(None).floor("h") - pd.Timedelta(hours=n)
    return pd.DataFrame([
        {"Date": t0 + pd.Timedelta(hours=i), "Open": px, "High": px,
         "Low": px, "Close": px} for i in range(n)])


class FX:
    def __init__(self, df):
        self.df = df

    def klines(self, symbol, interval, n):
        return self.df

    def open_positions(self, symbol=None):
        return []

    def contract_spec(self, symbol):
        return {"priceScale": 4, "contractSize": 1, "volUnit": 1,
                "minVol": 1, "maxVol": 25000, "maintenanceMarginRate": 0.005}

    def last_price(self, symbol):
        return 100.0


SETTINGS = {"strategies": ["mom6_1h_g"],
            "strategy_coins": {"mom6_1h_g": ["FLAT_USDT"]},
            "strategy_margins": {"mom6_1h_g": 5.0}}


def test_a_quiet_bar_is_recorded_as_seen():
    fx, state = FX(_bars()), {}
    at.process_symbol("FLAT_USDT", SETTINGS, state, fx=fx, dry=True)
    seen = (state.get("FLAT_USDT#paper") or {}).get("last_ts") or {}
    assert seen.get("Min60"), (
        "a bar with no signal was not marked seen — it will be re-read until "
        "it goes stale, emitting a false stale_skip every quiet hour")


def test_a_quiet_bar_is_not_re_evaluated_forever(tmp_path, monkeypatch):
    """Second pass over the same candles must do nothing at all.

    Staleness is disabled here so the test isolates the re-evaluation loop —
    the bug was that a quiet bar was re-read until it went stale, not the
    staleness rule itself.
    """
    monkeypatch.setattr(at, "LEDGER_PATH", tmp_path / "ledger.jsonl")
    monkeypatch.setattr(at, "MAX_SIGNAL_AGE_FRACTION", 10_000)
    fx, state = FX(_bars()), {}
    at.process_symbol("FLAT_USDT", SETTINGS, state, fx=fx, dry=True)
    first = dict((state.get("FLAT_USDT#paper") or {}).get("last_ts") or {})
    at.process_symbol("FLAT_USDT", SETTINGS, state, fx=fx, dry=True)
    assert (state.get("FLAT_USDT#paper") or {}).get("last_ts") == first
    rows = at.ledger_tail(50) if at.LEDGER_PATH.exists() else []
    assert not [r for r in rows if r.get("action") == "stale_skip"], (
        "a quiet bar produced a stale_skip")
