"""Many strategies on one coin, ONE open position — first signal wins.

Operator, 2026-09-04, arming 35 rows over 9 coins (20 of them on GPNSTOCK):

    "SINCE THERE ARE MULTIPLE STRATEGY FOR A COIN ... THEN I RECEIVED A SIGNAL
    FOR 73YCAX4Y / SINCE I RECEIVED A SIGNAL AND I HAVE OPEN POSITION THEN DO
    NOT ACCEPT SIGNAL FOR F2MGMJBK, KGY7YXF6, UQB99Z99 / FOR EXAMPLE 73YCAX4
    HAS BEEN CLOSED, THEN THAT'S THE TIME TO ACCEPT SIGNAL / WHICH EVER COMES
    FIRST SHOULD BE THE ONE TO FOLLOWED"

What changed is the ARMING, not the runtime. `timeframe_locks` meant ONE ARMED
live row per coin and would have refused 19 of those 20 GPNSTOCK rows before
they ever saw a signal. It is now a no-op, because one-position-per-coin is a
TIGHTER guarantee than one-armed-row-per-coin: real state is keyed by SYMBOL,
so the coin holds one position whoever opened it, `process_symbol` returns
while it is open, and it opens at most one per cycle (it returns after placing
the order). The netting incident that lock was written for — PROVE,
2026-08-22, `fade15_1h_pv2` and `mom6_1h_pv` live together, either stop able to
close part of a trade it did not own — needed TWO OPEN POSITIONS.

The refusal is also SAID now. With 20 strategies on one coin, a silent early
return is indistinguishable from a strategy that never fires.
"""
import inspect
import json

import pandas as pd

import tradingagents.auto_trader as at

A, B, C = "stoch14_1h_sl3tp3", "pivot_1h_sl3tp3", "cci20_4h_sl3tp3"
COIN = "GPNSTOCK_USDT"


def _bars(n=300, px=100.0):
    t0 = pd.Timestamp.utcnow().tz_localize(None).floor("h") - pd.Timedelta(hours=n)
    return pd.DataFrame([
        {"Date": t0 + pd.Timedelta(hours=i), "Open": px, "High": px,
         "Low": px, "Close": px, "Volume": 1000.0} for i in range(n)])


class FX:
    def __init__(self, df):
        self.df = df

    def klines(self, symbol, interval, n):
        return self.df

    def open_positions(self, symbol=None):
        # THE EXCHANGE IS THE SOURCE OF TRUTH (rule 14): with [] here the
        # runner reads the book's position as manually closed and closes it,
        # which is not the state this file is about.
        return [{"symbol": COIN, "positionId": 1, "holdVol": 1,
                 "positionType": 1, "liquidatePrice": 50.0}]

    def position_history(self, symbol=None, **kw):
        return []

    def contract_spec(self, symbol):
        return {"priceScale": 4, "contractSize": 1, "volUnit": 1,
                "minVol": 1, "maxVol": 25000, "maintenanceMarginRate": 0.005}

    def last_price(self, symbol):
        return 100.0

    def funding_history(self, symbol):
        return []


def _settings(book="real"):
    return {"strategies": [A, B, C],
            "strategy_coins": {A: [COIN], B: [COIN], C: [COIN]},
            "strategy_books": {A: [book], B: [book], C: [book]},
            "strategy_margins": {A: 5.0, B: 5.0, C: 5.0},
            "strategy_sizing": {A: "flat", B: "flat", C: "flat"}}


# ------------------------------------------------------------- the arming

def test_arming_many_live_rows_on_one_coin_is_allowed_now():
    """20 of the operator's 35 rows are GPNSTOCK."""
    assert at.timeframe_locks(_settings("real")) == {}
    assert at.timeframe_locks() == {}


def test_the_real_book_still_holds_ONE_slot_per_coin():
    """Which is what makes the position rule work at all: one state, one
    position, whoever opened it."""
    assert at.state_key(COIN, False, A) == COIN
    assert at.state_key(COIN, False, B) == COIN
    assert at.state_key(COIN, False, C) == COIN


def test_demo_is_still_one_slot_per_strategy():
    """"for demo it can have multiple strategies so i can see if its working"
    — comparing them side by side on one coin is the point of paper."""
    assert len({at.state_key(COIN, True, k) for k in (A, B, C)}) == 3


# ------------------------------------------------------------- the runtime

def test_a_held_coin_accepts_no_other_signal_and_SAYS_SO(tmp_path, monkeypatch):
    monkeypatch.setattr(at, "LEDGER_PATH", tmp_path / "ledger.jsonl")
    fx = FX(_bars())
    state = {COIN: {"position": {"side": 1, "vol": 1, "entry": 100.0,
                                 "tp": 103.0, "sl": 97.0, "margin": 5.0,
                                 "strategy": A, "entry_ts": 1,
                                 "dry": False, "bracket": True},
                    "last_ts": {}, "step": 0}}

    at.process_symbol(COIN, _settings("real"), state, fx=fx, dry=False)

    # nothing else opened: one coin, one position
    assert state[COIN]["position"]["strategy"] == A
    rows = [json.loads(x) for x in
            (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]
    busy = [r for r in rows if r.get("action") == "coin_busy"]
    assert busy, f"the refusal has to be visible: {rows}"
    assert busy[0]["strategy"] == A, "it names the holder"
    assert sorted(busy[0]["waiting"]) == sorted([B, C]), \
        "and the strategies it is holding off"
    assert not [r for r in rows if r.get("action") == "enter"]


def test_it_says_it_once_per_bar_not_once_per_cycle(tmp_path, monkeypatch):
    """The runner polls every few seconds; a line per poll is the noise that
    made `stale_skip` unreadable."""
    monkeypatch.setattr(at, "LEDGER_PATH", tmp_path / "ledger.jsonl")
    fx = FX(_bars())
    state = {COIN: {"position": {"side": 1, "vol": 1, "entry": 100.0,
                                 "tp": 103.0, "sl": 97.0, "margin": 5.0,
                                 "strategy": A, "entry_ts": 1, "dry": False,
                                 "bracket": True},
                    "last_ts": {}, "step": 0}}
    for _ in range(4):
        at.process_symbol(COIN, _settings("real"), state, fx=fx, dry=False)
    rows = [json.loads(x) for x in
            (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len([r for r in rows if r.get("action") == "coin_busy"]) == 1


def test_a_lone_strategy_on_a_coin_says_nothing(tmp_path, monkeypatch):
    """No other strategy is waiting, so there is nothing to report."""
    monkeypatch.setattr(at, "LEDGER_PATH", tmp_path / "ledger.jsonl")
    fx = FX(_bars())
    settings = {"strategies": [A], "strategy_coins": {A: [COIN]},
                "strategy_books": {A: ["real"]}, "strategy_margins": {A: 5.0}}
    state = {COIN: {"position": {"side": 1, "vol": 1, "entry": 100.0,
                                 "tp": 103.0, "sl": 97.0, "margin": 5.0,
                                 "strategy": A, "entry_ts": 1, "dry": False,
                                 "bracket": True},
                    "last_ts": {}, "step": 0}}
    at.process_symbol(COIN, settings, state, fx=fx, dry=False)
    text = ((tmp_path / "ledger.jsonl").read_text(encoding="utf-8")
            if (tmp_path / "ledger.jsonl").exists() else "")
    assert "coin_busy" not in text


def test_when_it_closes_the_coin_is_free_again(tmp_path, monkeypatch):
    """"FOR EXAMPLE 73YCAX4 HAS BEEN CLOSED, THEN THAT'S THE TIME TO ACCEPT
    SIGNAL" — the slot holds no position, so the entry loop runs again."""
    monkeypatch.setattr(at, "LEDGER_PATH", tmp_path / "ledger.jsonl")
    fx = FX(_bars())
    state = {COIN: {"position": None, "last_ts": {}, "step": 0}}
    at.process_symbol(COIN, _settings("real"), state, fx=fx, dry=False)
    # flat candles, so no strategy fires — but the coin was NOT refused for
    # being busy, which is the difference this test is about
    text = ((tmp_path / "ledger.jsonl").read_text(encoding="utf-8")
            if (tmp_path / "ledger.jsonl").exists() else "")
    assert "coin_busy" not in text


def test_at_most_one_entry_per_cycle():
    """Two strategies whose bars close together must not both open: the
    function returns after placing an order."""
    src = inspect.getsource(at.process_symbol) + inspect.getsource(
        at._process_slot)
    i = src.index('st["position"] = {"side"')
    tail = src[i:]
    assert "\n        return\n" in tail, \
        "an entry must end the cycle for this slot"


def test_the_dead_arming_check_is_gone_from_the_entry_loop():
    src = inspect.getsource(at._process_slot)
    assert "_live_locks" not in src
    assert "ONE OPEN POSITION PER COIN" in src, "and the rule is written down"
