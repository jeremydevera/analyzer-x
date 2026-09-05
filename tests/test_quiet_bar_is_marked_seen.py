"""A bar with no signal must be marked seen, like any other.

Leaving it unmarked made the runner re-evaluate the same quiet candle every
few seconds until it aged past the staleness limit, so every quiet hour
emitted a `stale_skip` at HH:30. 282 of 341 skips in the operator's ledger
carried "age 30 min" — the feed looked like the bot was missing most of its
checks when it had examined every one and simply found no trade.
"""
import pandas as pd

import tradingagents.auto_trader as at


def _slot(state, symbol="FLAT_USDT"):
    """The coin's one paper slot - per strategy since 2026-08-27."""
    from tradingagents import auto_trader as _at

    keys = [k for k in state
            if _at.is_paper_slot(k) and _at.coin_of_slot(k) == symbol]
    return state[keys[0]] if len(keys) == 1 else None

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

    # A READABLE, cheap book. Without it the liquidity gate reads "unknown",
    # which since Sep 05, 2026 REFUSES the entry (rule 12) — so this test was
    # measuring the gate, not the quiet bar. Tests that want a refused coin
    # define their own double.
    def book_cost(self, symbol, notional_usd=200.0):
        return {"spread": 0.0002, "slippage": 0.0002, "book_exhausted": False}


SETTINGS = {"strategies": ["mom6_1h_g"],
            "strategy_coins": {"mom6_1h_g": ["FLAT_USDT"]},
            "strategy_margins": {"mom6_1h_g": 5.0}}


def test_a_quiet_bar_is_recorded_as_seen():
    fx, state = FX(_bars()), {}
    at.process_symbol("FLAT_USDT", SETTINGS, state, fx=fx, dry=True)
    seen = (_slot(state) or {}).get("last_ts") or {}
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
    first = dict((_slot(state) or {}).get("last_ts") or {})
    at.process_symbol("FLAT_USDT", SETTINGS, state, fx=fx, dry=True)
    assert (_slot(state) or {}).get("last_ts") == first
    rows = at.ledger_tail(50) if at.LEDGER_PATH.exists() else []
    assert not [r for r in rows if r.get("action") == "stale_skip"], (
        "a quiet bar produced a stale_skip")


class GatedFX(FX):
    """A book so wide no target can clear it — the gate refuses every entry."""

    def book_cost(self, symbol, notional_usd=200.0):
        return {"spread": 0.05, "slippage": 0.05, "book_exhausted": False}


class UnreadableFX(FX):
    """The venue will not answer — verdict "unknown"."""

    def book_cost(self, symbol, notional_usd=200.0):
        raise RuntimeError("510 request frequency too high")


def test_a_gate_refused_bar_is_marked_seen_too():
    """A refused bar has still been EXAMINED.

    Leaving it unmarked made a gated coin re-read the same candle every cycle
    until it aged past the staleness limit, so the feed emitted a `stale_skip`
    every quiet hour about a bar that was never going to be traded. Measured in
    the operator's ledger on Sep 05, 2026: 160 of 166 stale_skip rows were on a
    coin+strategy the gate was refusing.
    """
    at._GATE_CACHE.clear()
    fx, state = GatedFX(_bars()), {}
    at.process_symbol("FLAT_USDT", SETTINGS, state, fx=fx, dry=True)
    seen = (_slot(state) or {}).get("last_ts") or {}
    assert seen.get("Min60"), (
        "a gate-refused bar was not marked seen — it will be re-read until it "
        "goes stale, emitting a false stale_skip every quiet hour")


def test_an_unreadable_book_leaves_the_bar_for_the_next_cycle():
    """The other direction, and it must NOT be marked.

    "unknown" is a book that could not be READ — transient by definition. If
    the bar were marked seen, a 510 lasting one second would skip that candle's
    trade for good. Missing a trade is a money problem; one honest stale line
    on a coin whose book is down is not.
    """
    at._GATE_CACHE.clear()
    fx, state = UnreadableFX(_bars()), {}
    at.process_symbol("FLAT_USDT", SETTINGS, state, fx=fx, dry=True)
    seen = (_slot(state) or {}).get("last_ts") or {}
    assert not seen.get("Min60"), (
        "an unreadable book must leave the bar for the next cycle, not consume it")
