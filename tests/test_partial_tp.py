"""PARTIAL TP/SL: several strategies hold one coin, each with its own slice.

Operator, Sep 09, 2026: *"do a switch 'Enable Partial TP/SL for DEMO' and
'Enable Partial TP/SL for Live' / if this is turned on then do the partial
trading / take note the win/L should still go in a specific trade so i can
still see which trade strategy id thas high winrate and how much i lose/earn
for that specific trade strategy"*.

MEXC nets every order on a contract into ONE position, so 20 GPNSTOCK
strategies cannot hold 20 live trades. They can hold 20 SLICES of one
position: own contracts, own entry, own TP/SL resting with volType=PARTIAL.
Each slice is its own state slot (`SYM#live#KEY`), so every enter/exit ledger
row still carries one strategy id, one entry, one exit and one pnl — which is
the operator's condition on the whole feature.

These drive `process_symbol`, the function the RUNNER calls, with the
operator's own settings shape (CLAUDE.md: test the path the runner takes).
"""
import json

import pandas as pd
import pytest

import tradingagents.auto_trader as at

A, B, C = "stoch14_1h_sl3tp3", "pivot_1h_sl3tp3", "prank_1h_sl3tp3"
COIN = "GPNSTOCK_USDT"


def _bars(n=300, px=100.0):
    """Hourly candles whose LAST bar closed one minute ago.

    Not `floor("h")`: that leaves the newest bar closed anywhere from 0 to 59
    minutes back, and the runner refuses a signal older than half its bar
    (MAX_SIGNAL_AGE_FRACTION — 30 min on 1h). So these tests passed when run
    at :10 and failed at :46, which is a clock deciding whether a coin rule
    is correct. The last bar now closes 60 s before the test runs, always.
    """
    last_open = (pd.Timestamp.utcnow().tz_localize(None)
                 - pd.Timedelta(hours=1) - pd.Timedelta(minutes=1))
    t0 = last_open - pd.Timedelta(hours=n - 1)
    return pd.DataFrame([
        {"Date": t0 + pd.Timedelta(hours=i), "Open": px, "High": px,
         "Low": px, "Close": px, "Volume": 1000.0} for i in range(n)])


class FX:
    """A venue that holds one netted position and remembers every stop."""

    def __init__(self, df=None, vol=0):
        self.df = df if df is not None else _bars()
        self.vol = vol
        self.stops = []
        self.orders = []
        self.VOL_PARTIAL, self.VOL_POSITION = 1, 2
        self.SIDE_OPEN_LONG, self.SIDE_CLOSE_LONG = 1, 4
        self.SIDE_OPEN_SHORT, self.SIDE_CLOSE_SHORT = 3, 2

    def klines(self, symbol, interval, n):
        return self.df

    def open_positions(self, symbol=None):
        if self.vol <= 0:
            return []
        return [{"symbol": COIN, "positionId": 1, "holdVol": self.vol,
                 "positionType": 1, "holdAvgPrice": 100.0,
                 "liquidatePrice": 50.0}]

    def submit(self, symbol, side, vol, **kw):
        self.orders.append((side, vol))
        self.vol += int(vol) if side in (1, 3) else -int(vol)
        return {"orderId": len(self.orders)}

    def place_position_stop(self, symbol, position_id, vol, **kw):
        self.stops.append({"vol": vol, **kw})
        return {"ok": True}

    def verify_position_stop(self, symbol, position_id):
        return {"protected": True, "active": [{"id": 1}], "failed": []}

    def position_history(self, symbol=None, **kw):
        return []

    def contract_spec(self, symbol):
        return {"priceScale": 4, "contractSize": 1, "volUnit": 1,
                "minVol": 1, "maxVol": 25000, "maintenanceMarginRate": 0.005,
                "takerFeeRate": 0.0002}

    def last_price(self, symbol):
        return 100.0

    def contracts_for(self, symbol, notional_usd, price=None):
        return max(1, int(notional_usd / (price or 100.0)))

    def book_cost(self, symbol, notional):
        # the REAL payload's shape (mexc_futures.book_cost) — a double that
        # invents its own keys tests a gate that does not exist
        return {"symbol": symbol, "mid": 100.0, "spread": 0.0004,
                "slippage": 0.0002, "book_exhausted": False,
                "notional_tested": notional}

    def funding_history(self, symbol):
        return []

    def liquidation_move_pct(self, symbol, lev):
        return 50.0


def _settings(book="real", **extra):
    s = {"strategies": [A, B, C],
         "strategy_coins": {A: [COIN], B: [COIN], C: [COIN]},
         "strategy_books": {A: [book], B: [book], C: [book]},
         "strategy_margins": {A: 5.0, B: 5.0, C: 5.0},
         "strategy_sizing": {A: "flat", B: "flat", C: "flat"}}
    s.update(extra)
    return s


def _pos(strategy, side=1, vol=10, dry=False, entry=100.0):
    return {"side": side, "vol": vol, "entry": entry,
            "tp": entry * (1 + 0.03 * side), "sl": entry * (1 - 0.03 * side),
            "margin": 5.0, "strategy": strategy, "entry_ts": 1,
            "opened_at": 1, "dry": dry, "bracket": True, "position_id": 1}


def _rows(tmp_path):
    f = tmp_path / "ledger.jsonl"
    if not f.exists():
        return []
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def led(tmp_path, monkeypatch):
    monkeypatch.setattr(at, "LEDGER_PATH", tmp_path / "ledger.jsonl")
    monkeypatch.setattr(at, "_SAID", {})
    return tmp_path


def _always(side):
    """Drive a real signal: flat candles fire nothing, and the rule under
    test is the COIN rule, not the indicator."""
    return lambda key, high, low, close, **kw: side


# ------------------------------------------------------------ the switches

def test_the_defaults_are_demo_on_live_off():
    """Demo ON is today's demo behaviour (a slot per strategy). Live OFF
    because more slices is more money on one coin, and money is never opted
    in by a default."""
    assert at.partial_on({}, True) is True
    assert at.partial_on({}, False) is False
    assert at.partial_on({"partial_tp_live": True}, False) is True
    assert at.partial_on({"partial_tp_demo": False}, True) is False


def test_the_cap_defaults_to_four_and_is_the_operators_to_set():
    """20 slices of $5 on GPNSTOCK is $100 of margin behind ONE liquidation
    price while their account cap is $5."""
    assert at.max_slices({}) == 4
    assert at.max_slices({"partial_max_slices": 20}) == 20
    assert at.max_slices({"partial_max_slices": 0}) == 1      # never zero
    assert at.max_slices({"partial_max_slices": "junk"}) == 4


def test_a_slice_slot_is_the_real_mirror_of_a_paper_slot():
    assert at.state_key(COIN, False) == COIN
    assert at.state_key(COIN, False, A) == f"{COIN}#live#{A}"
    assert at.is_slice_slot(f"{COIN}#live#{A}") is True
    assert at.is_slice_slot(COIN) is False
    assert at.is_paper_slot(f"{COIN}#live#{A}") is False, \
        "a slice is REAL money — it must never be read as paper"
    assert at.strategy_of_slot(f"{COIN}#live#{A}") == A
    assert at.coin_of_slot(f"{COIN}#live#{A}") == COIN


def test_every_slice_is_saved_with_the_coin():
    """A slot left out of book_slots lives one cycle in RAM and is gone —
    the Sep 04, 2026 phantom, which cost a duplicate entry."""
    state = {COIN: {}, f"{COIN}#live#{A}": {}, f"{COIN}#live#{B}": {},
             "OTHER_USDT#live#x": {}, f"{COIN}#paper#{A}": {}}
    got = at.book_slots(state, COIN, False)
    assert set(got) == {COIN, f"{COIN}#live#{A}", f"{COIN}#live#{B}"}


# ------------------------------------------------------- partial OFF: one

def test_with_partial_off_a_held_coin_refuses_every_other_strategy(led,
                                                                   monkeypatch):
    """The operator's rule of Sep 04, 2026, unchanged and still the default."""
    monkeypatch.setattr(at, "signal_for", _always(1))
    fx = FX(vol=10)
    state = {COIN: {"position": _pos(A), "last_ts": {}, "step": 0}}
    at.process_symbol(COIN, _settings("real"), state, fx=fx, dry=False)
    assert state[COIN]["position"]["strategy"] == A
    assert not [r for r in _rows(led) if r.get("action") == "enter"]
    assert fx.orders == [], "no order may reach the venue"


def test_with_partial_off_demo_follows_the_same_rule(led, monkeypatch):
    """So demo PREDICTS live instead of flattering it — the operator's own
    complaint of Sep 05, 2026 ("live trade and demo is not the same")."""
    monkeypatch.setattr(at, "signal_for", _always(1))
    state = {f"{COIN}#paper#{A}": {"position": _pos(A, dry=True),
                                   "last_ts": {}, "step": 0}}
    at.process_symbol(COIN, _settings("paper", partial_tp_demo=False), state,
                      fx=FX(), dry=True)
    opened = [k for k, v in state.items()
              if k != f"{COIN}#paper#{A}" and (v or {}).get("position")]
    assert not opened, f"demo opened a second position on a held coin: {opened}"
    busy = [r for r in _rows(led) if r.get("action") == "coin_busy"]
    assert busy and busy[0]["holders"] == [A]


# -------------------------------------------------------- partial ON: many

def test_with_partial_on_a_second_strategy_takes_its_own_slice(led,
                                                               monkeypatch):
    monkeypatch.setattr(at, "signal_for", _always(1))
    fx = FX(vol=10)
    state = {f"{COIN}#live#{A}": {"position": _pos(A), "last_ts": {},
                                  "step": 0}}
    at.process_symbol(COIN, _settings("real", partial_tp_live=True), state,
                      fx=fx, dry=False)
    opened = [k for k in state
              if at.is_slice_slot(k) and (state[k] or {}).get("position")]
    assert len(opened) > 1, f"only {opened} — a second slice must open"
    # each slice names ITS OWN strategy, which is what makes the W/L per
    # strategy possible at all
    owners = {(state[k]["position"] or {}).get("strategy") for k in opened}
    assert len(owners) == len(opened) and A in owners
    ent = [r for r in _rows(led) if r.get("action") == "enter"]
    assert ent and all(r.get("strategy") for r in ent)


def test_a_slice_rests_a_PARTIAL_stop_not_a_whole_position_one(led,
                                                               monkeypatch):
    """With volType=POSITION every slice's stop would close every OTHER
    slice too: the first barrier to fire would end all twenty trades at one
    strategy's target."""
    monkeypatch.setattr(at, "signal_for", _always(1))
    fx = FX(vol=0)
    state = {}
    at.process_symbol(COIN, _settings("real", partial_tp_live=True), state,
                      fx=fx, dry=False)
    assert fx.stops, "the slice must rest a stop at the exchange"
    assert fx.stops[0]["vol_type"] == fx.VOL_PARTIAL


def test_the_base_slot_never_opens_a_trade_while_partial_is_on(led,
                                                               monkeypatch):
    """The base call sees EVERY armed strategy; if it could enter, strategy A
    would open in the base slot and again in its own slice — one signal, two
    positions, twice the money."""
    monkeypatch.setattr(at, "signal_for", _always(1))
    fx = FX(vol=0)
    state = {}
    at.process_symbol(COIN, _settings("real", partial_tp_live=True), state,
                      fx=fx, dry=False)
    assert not (state.get(COIN) or {}).get("position"), \
        "the base slot must MANAGE only"
    ent = [r for r in _rows(led) if r.get("action") == "enter"]
    assert len({r["strategy"] for r in ent}) == len(ent), \
        "no strategy may enter twice on one signal"


def test_the_slice_cap_is_enforced_and_named(led, monkeypatch):
    monkeypatch.setattr(at, "signal_for", _always(1))
    fx = FX(vol=20)
    state = {f"{COIN}#live#{A}": {"position": _pos(A), "last_ts": {}, "step": 0},
             f"{COIN}#live#{B}": {"position": _pos(B), "last_ts": {}, "step": 0}}
    at.process_symbol(COIN, _settings("real", partial_tp_live=True,
                                      partial_max_slices=2),
                      state, fx=fx, dry=False)
    third = (state.get(f"{COIN}#live#{C}") or {}).get("position")
    assert not third, "the cap must hold"
    busy = [r for r in _rows(led) if r.get("action") == "coin_busy"]
    assert busy and "cap" in busy[0]["why"]
    assert sorted(busy[0]["holders"]) == sorted([A, B]), "it names the holders"


def test_an_opposite_direction_slice_is_refused(led, monkeypatch):
    """Netting: a long slice and a short slice on one contract are not two
    trades, they cancel into one smaller trade nobody backtested."""
    monkeypatch.setattr(at, "signal_for", _always(-1))
    fx = FX(vol=10)
    state = {f"{COIN}#live#{A}": {"position": _pos(A, side=1), "last_ts": {},
                                  "step": 0}}
    at.process_symbol(COIN, _settings("real", partial_tp_live=True), state,
                      fx=fx, dry=False)
    others = [k for k in state
              if at.is_slice_slot(k) and k != f"{COIN}#live#{A}"
              and (state[k] or {}).get("position")]
    assert not others, f"a short slice opened against a long one: {others}"
    busy = [r for r in _rows(led) if r.get("action") == "coin_busy"]
    assert busy and "other way" in busy[0]["why"]


# ------------------------------------------- one slice closes, the rest run

def test_one_slices_stop_firing_does_not_close_the_others(led, monkeypatch):
    """A's contracts are gone from the netted position; B's are not. A books
    its own exit with its own pnl, and B keeps running."""
    monkeypatch.setattr(at, "signal_for", _always(0))
    # 10 contracts left of the 20 the two slices hold: A's slice is gone
    fx = FX(vol=10)
    state = {f"{COIN}#live#{A}": {"position": _pos(A, vol=10), "last_ts": {},
                                  "step": 0},
             f"{COIN}#live#{B}": {"position": _pos(B, vol=10), "last_ts": {},
                                  "step": 0}}
    at.process_symbol(COIN, _settings("real", partial_tp_live=True), state,
                      fx=fx, dry=False)
    exits = [r for r in _rows(led) if r.get("action") == "exit"]
    assert len(exits) == 1, f"exactly one slice closed: {exits}"
    assert exits[0]["strategy"] in (A, B)
    assert "pnl_est" in exits[0], "the W/L is booked to THAT strategy"
    still = [k for k in state
             if at.is_slice_slot(k) and (state[k] or {}).get("position")]
    assert len(still) == 1, "the other slice must still be open"


def test_an_unreadable_volume_never_books_an_exit(led, monkeypatch):
    """"I could not ask" must not read as "the position is gone" — a phantom
    exit flushes the book while the money is still on the table (rule 14)."""
    monkeypatch.setattr(at, "signal_for", _always(0))
    fx = FX(vol=10)
    fx.open_positions = lambda symbol=None: [{"symbol": COIN}]   # no holdVol
    assert at._symbol_vol(COIN, fx=fx) is None
    state = {f"{COIN}#live#{A}": {"position": _pos(A, vol=10), "last_ts": {},
                                  "step": 0}}
    at.process_symbol(COIN, _settings("real", partial_tp_live=True), state,
                      fx=fx, dry=False)
    assert state[f"{COIN}#live#{A}"]["position"], "the slice stays tracked"
    assert not [r for r in _rows(led) if r.get("action") == "exit"]


def test_a_venue_that_cannot_be_asked_is_unknown_not_empty():
    class Dead(FX):
        def open_positions(self, symbol=None):
            raise RuntimeError("venue down")

    assert at._symbol_vol(COIN, fx=Dead()) is None


# --------------------------------------------------------- the other readers

def test_the_orphan_sweep_skips_a_coin_the_slices_track():
    """The base slot is empty in partial mode while the slices hold the
    netted position between them; adopting it would track the same contracts
    twice and bracket them a second time."""
    import inspect

    src = inspect.getsource(at.adopt_orphans)
    assert "is_slice_slot" in src


def test_the_ladder_rung_reads_the_slot_that_exists():
    """`state_key(sym, False, key)` used to ignore the strategy and answer the
    base slot; api.py reads a real row's rung with exactly that call, so every
    real row would have shown rung 0 while partial is off."""
    base = {COIN: {"step": 3, "position": _pos(A)}}
    assert at.slot_of(base, COIN, False, A).get("step") == 3
    assert at.slot_of(base, COIN, False, B).get("step", 0) == 0, \
        "another strategy's rung is not this row's rung"
    sliced = {f"{COIN}#live#{A}": {"step": 5, "position": _pos(A)}}
    assert at.slot_of(sliced, COIN, False, A).get("step") == 5
    api = open("tradingagents/api.py", encoding="utf-8").read()
    assert "at.slot_of(runstate, c, not _is_real, key)" in api


def test_a_panic_close_clears_the_slices_it_closed(led, monkeypatch):
    """`report["closed"]` holds SYMBOLS and a slice slot is `SYM#live#KEY`;
    comparing the two left every slice in the book as a phantom after a panic
    that really had closed it, with the SLOT KEY written into the ledger's
    symbol column."""
    fx = FX(vol=20)
    state = {f"{COIN}#live#{A}": {"position": _pos(A, vol=10), "last_ts": {},
                                  "step": 0},
             f"{COIN}#live#{B}": {"position": _pos(B, vol=10), "last_ts": {},
                                  "step": 0}}
    monkeypatch.setattr(at, "load_state", lambda: state)
    monkeypatch.setattr(at, "save_state", lambda s, keys=None: None)
    monkeypatch.setattr(at, "stop_runner", lambda: True)
    monkeypatch.setattr(at, "KILL_PATH", led / "kill")
    monkeypatch.setattr(at, "_force_close", lambda sym, pos, fx=None: True)

    rep = at.panic_stop(fx=fx, close_positions=True)

    assert COIN in rep["closed"]
    for k in (f"{COIN}#live#{A}", f"{COIN}#live#{B}"):
        assert state[k]["position"] is None, f"{k} left as a phantom"
    ex = [r for r in _rows(led) if r.get("why") == "PANIC_CLOSE"]
    assert len(ex) == 2
    assert {r["symbol"] for r in ex} == {COIN}, "the COIN, never the slot key"
    assert {r["strategy"] for r in ex} == {A, B}, "each slice books its own"


def test_the_reconcile_sweep_asks_about_the_CONTRACT_not_the_slot(led,
                                                                  monkeypatch):
    """`symbol = key` was right while every real slot WAS a symbol. With
    slices it would have asked the venue about
    "GPNSTOCK_USDT#live#stoch14_30m_sl2tp2" and written that into the
    ledger's symbol column."""
    asked = []

    class Seen(FX):
        def open_positions(self, symbol=None):
            asked.append(symbol)
            return []

    fx = Seen(vol=0)
    state = {f"{COIN}#live#{A}": {"position": _pos(A), "last_ts": {},
                                  "step": 0}}
    at.reconcile_unconfigured({"strategies": []}, state, fx=fx)
    assert asked and all(a == COIN for a in asked), \
        f"the venue was asked about {asked}"
    ex = [r for r in _rows(led) if r.get("why") == "RECONCILED"]
    assert ex and ex[0]["symbol"] == COIN
    assert ex[0]["strategy"] == A, "the slice's own strategy books the exit"
