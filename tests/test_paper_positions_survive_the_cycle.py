"""A demo position must reach the disk, and must reach the screen as ITSELF.

Operator, Sep 04, 2026: *"I RECEIVED THIS NOTIFICATION BUT WHY IS IT NOT UNDER
MY PAPER — DEMO, NOT REAL MONEY"* — three bell rows saying PAPER LONG GPNSTOCK
(10:41am, 10:42am) and PAPER SHORT PSXSTOCK (10:46am) while the Paper book on
`/api/trade/positions` returned an empty list.

Nothing had closed them. `auto_trade_state.json` was 74 bytes and held no
position at all, and its own `_rev` receipt named exactly one slot,
`_tripped_logged`, in three saves. Two failures, one cause — the Aug 27, 2026
change that made a paper slot per-STRATEGY (`SYM#paper#KEY`) was never carried
to two call sites that still assume one slot per coin:

1. WRITE. `run_cycle` built its save list as `state_key(symbol, dry)`, which
   with no strategy returns the LEGACY `SYM#paper`. `save_state` skips a key
   that is not in the dict (`if k not in state: continue`), so every paper slot
   was dropped on every cycle and the position lived one cycle in RAM. The
   ledger shows what that cost: GPNSTOCK keltner_30m_sl08tp08 entered at
   10:41am at 89.38 and AGAIN at 10:42am at 89.36 under the same trade id
   YMSUZZRU — the runner had already forgotten it held the position.
2. READ. `positions_view.build_rows` keyed its rows by SYMBOL, so the two
   GPNSTOCK strategies that opened a second apart would have collapsed into one
   row even once they persisted — which is the whole thing per-strategy slots
   were introduced to make possible.

The REAL book is not affected either way: `state_key(sym, False)` returns the
bare symbol in both places, and MEXC nets a contract into one position.
"""

from tradingagents import auto_trader as at, positions_view as pv

A, B = "keltner_30m_sl08tp08", "keltner_30m_sl08tp1"
COIN = "GPNSTOCK_USDT"


def _pos(strategy, side=1, entry=89.36):
    return {"side": side, "vol": 1.0, "entry": entry, "tp": entry * 1.008,
            "sl": entry * 0.992, "margin": 5.0, "strategy": strategy,
            "entry_ts": 1788_000_000, "opened_at": 1788_000_000,
            "dry": True, "bracket": True, "step": 0}


# --------------------------------------------------------------- the write
def test_the_cycle_names_every_paper_slot_it_must_save():
    """The bug in one assertion: the save list has to contain the slot the
    position is actually in."""
    state = {at.state_key(COIN, True, A): {"step": 0, "position": _pos(A)},
             at.state_key(COIN, True, B): {"step": 0, "position": _pos(B)}}
    slots = at.book_slots(state, COIN, True)
    assert at.state_key(COIN, True, A) in slots
    assert at.state_key(COIN, True, B) in slots
    assert at.state_key(COIN, True) not in slots, \
        "the legacy SYM#paper key is not a slot anything writes any more"


def test_the_real_book_still_saves_one_slot_per_coin():
    state = {COIN: {"step": 0, "position": None}}
    assert at.book_slots(state, COIN, False) == [COIN]


def test_a_legacy_slot_is_still_saved_if_one_is_on_disk():
    """Migration runs inside the cycle, but a slot that has not been migrated
    yet must not be dropped from the save on the way past."""
    state = {f"{COIN}#paper": {"step": 3, "position": _pos(A)}}
    assert f"{COIN}#paper" in at.book_slots(state, COIN, True)


def test_another_coins_slots_are_never_touched():
    state = {at.state_key(COIN, True, A): {"position": _pos(A)},
             at.state_key("PSXSTOCK_USDT", True, A): {"position": _pos(A)}}
    assert at.book_slots(state, COIN, True) == [at.state_key(COIN, True, A)]


def test_a_paper_position_reaches_the_disk(tmp_path, monkeypatch):
    """The end-to-end shape of the failure: open on paper, save the way the
    cycle saves, read it back the way the API reads it."""
    monkeypatch.setattr(at, "STATE_DIR", tmp_path)
    monkeypatch.setattr(at, "STATE_PATH", tmp_path / "auto_trade_state.json")
    monkeypatch.setattr(at, "STATE_LOCK_PATH", tmp_path / "state.lock")

    state = at.load_state()
    slot_a = at.state_key(COIN, True, A)
    slot_b = at.state_key(COIN, True, B)
    state[slot_a] = {"step": 0, "last_ts": {}, "position": _pos(A, entry=89.38)}
    state[slot_b] = {"step": 0, "last_ts": {}, "position": _pos(B, entry=89.36)}
    at.save_state(state, keys=at.book_slots(state, COIN, True))

    back = at.load_state()
    assert back.get(slot_a, {}).get("position"), "the demo position was lost"
    assert back.get(slot_b, {}).get("position"), "the demo position was lost"
    assert back[slot_a]["position"]["entry"] == 89.38
    assert back[slot_b]["position"]["entry"] == 89.36
    # the receipt that made the diagnosis: _rev names what was really written
    assert set(back["_rev"]) == {slot_a, slot_b}


def test_the_runner_cycle_uses_the_slot_list(monkeypatch):
    """The call site itself, not just the helper — this is the line that was
    wrong, and a passing helper with a stale caller changes nothing."""
    import inspect

    src = inspect.getsource(at.run_cycle)
    assert "book_slots(" in src, \
        "run_cycle must name the slots it visited, not a legacy key"
    assert "touched.append(state_key(symbol, dry))" not in src, \
        "state_key(symbol, dry) is the legacy paper key — it saves nothing"


# ---------------------------------------------------------------- the read
def test_two_demo_strategies_on_one_coin_are_two_rows():
    """Collapsing them by symbol makes the per-strategy book invisible: the
    operator opened GPNSTOCK twice, a second apart, on two strategies."""
    state = {at.state_key(COIN, True, A): {"position": _pos(A, entry=89.38)},
             at.state_key(COIN, True, B): {"position": _pos(B, entry=89.36)}}
    rows = pv.build_rows(state=state, exchange_positions=[], stats={},
                         dry=True, last_price=lambda s: 90.0,
                         contract_size=lambda s: 1.0, taker_fee=0.0004,
                         leverage=20, now=1788_000_600)
    assert len(rows) == 2, [r.get("strategy") for r in rows]
    assert {r["strategy"] for r in rows} == {A, B}
    assert {r["entry"] for r in rows} == {89.38, 89.36}
    for r in rows:
        assert r["coin"] == "GPNSTOCK", "the coin name never carries the slot"


def test_the_real_book_is_still_one_row_per_coin():
    """MEXC nets a contract into a single position; two real rows on one coin
    would be a position that cannot exist."""
    live = [{"symbol": COIN, "side": "LONG", "vol": 1.0, "entry": 89.38}]
    rows = pv.build_rows(state={COIN: {"position": dict(_pos(A), dry=False)}},
                         exchange_positions=live, stats={}, dry=False,
                         last_price=lambda s: 90.0,
                         contract_size=lambda s: 1.0, taker_fee=0.0004,
                         leverage=20, now=1788_000_600)
    assert len(rows) == 1, rows


def test_a_paper_row_says_which_strategy_it_belongs_to():
    """label-must-match-data: two rows on one coin are only readable if each
    names its own strategy."""
    state = {at.state_key(COIN, True, A): {"position": _pos(A)}}
    rows = pv.build_rows(state=state, exchange_positions=[], stats={},
                         dry=True, last_price=lambda s: 90.0,
                         contract_size=lambda s: 1.0, taker_fee=0.0004,
                         leverage=20, now=1788_000_600)
    assert rows[0]["strategy"] == A
    assert rows[0]["side"] == "LONG"


# ------------------------------------------------- the route the UI calls
def test_the_paper_book_route_returns_both_rows(monkeypatch):
    """End to end through `/api/trade/positions`, which is what the Paper
    table on screen reads. Two strategies, one coin, two rows."""
    from fastapi.testclient import TestClient

    from tradingagents.api import app
    from tradingagents.dataflows import mexc_credentials as cred, mexc_futures as fx

    monkeypatch.setattr(cred, "load_into_env", lambda: None)
    monkeypatch.setattr(fx, "open_positions", lambda symbol=None: [])
    monkeypatch.setattr(fx, "last_price", lambda s: 90.0)
    monkeypatch.setattr(fx, "contract_spec", lambda s: {"contractSize": 1.0})
    monkeypatch.setattr(at, "coin_stats", lambda dry=None: {})
    monkeypatch.setattr(at, "load_settings", lambda: {})
    monkeypatch.setattr(at, "load_state", lambda: {
        at.state_key(COIN, True, A): {"position": _pos(A, entry=89.38)},
        at.state_key(COIN, True, B): {"position": _pos(B, entry=89.36)}})

    got = TestClient(app).get("/api/trade/positions").json()
    assert got["real"] == []
    assert len(got["paper"]) == 2, [r["strategy"] for r in got["paper"]]
    assert {r["strategy"] for r in got["paper"]} == {A, B}
    # label-must-match-data: each row's entry belongs to the strategy beside it
    by_key = {r["strategy"]: r for r in got["paper"]}
    assert by_key[A]["entry"] == 89.38 and by_key[B]["entry"] == 89.36
    assert all(r["coin"] == "GPNSTOCK" for r in got["paper"])


# ------------------------------------------------------------ the invariant
def test_any_slot_a_cycle_opens_reaches_the_disk(tmp_path, monkeypatch):
    """The PROPERTY, not the string. A source check pins the one call site
    that was wrong; this pins the rule that made it wrong — whatever slot the
    pass writes a position into must survive the cycle. It fails for ANY
    future save list that misses a slot, whatever the key is shaped like, so
    the next person to change the key format is told by a test rather than by
    the operator asking why their demo book is empty.
    """
    monkeypatch.setattr(at, "STATE_DIR", tmp_path)
    monkeypatch.setattr(at, "STATE_PATH", tmp_path / "auto_trade_state.json")
    monkeypatch.setattr(at, "STATE_LOCK_PATH", tmp_path / "state.lock")
    monkeypatch.setattr(at, "LEDGER_PATH", tmp_path / "ledger.jsonl")
    monkeypatch.setattr(at, "load_settings", lambda: {
        "strategies": [A, B], "strategy_coins": {A: [COIN], B: [COIN]},
        "strategy_books": {A: ["paper"], B: ["paper"]}})
    monkeypatch.setattr(at, "active_modes", lambda s: [True])   # paper only
    monkeypatch.setattr(at, "timeframe_conflicts", lambda s: [])
    monkeypatch.setattr(at, "adopt_orphans",
                        lambda *a, **k: None)
    monkeypatch.setattr(at, "reconcile_unconfigured", lambda *a, **k: None)
    monkeypatch.setattr(at, "tripped_strategies", lambda s, dry=None: [])
    monkeypatch.setattr(at, "coins_for", lambda key, s: [COIN])

    # the only thing the stub does is what the real pass did on Sep 04:
    # put a position into this strategy's OWN slot
    def _fake_pass(symbol, settings, state, *, fx, dry, tripped):
        for key in (A, B):
            state.setdefault(at.state_key(symbol, dry, key),
                             {"step": 0, "last_ts": {}})
            state[at.state_key(symbol, dry, key)]["position"] = _pos(key)

    monkeypatch.setattr(at, "process_symbol", _fake_pass)
    at.run_cycle(fx=object())

    back = at.load_state()
    for key in (A, B):
        slot = at.state_key(COIN, True, key)
        assert back.get(slot, {}).get("position"), \
            f"the cycle opened {slot} and did not save it"
        assert back[slot]["position"]["strategy"] == key


def test_a_cycle_that_raises_still_saves_what_it_opened(tmp_path, monkeypatch):
    """The position is written BEFORE the bracket rests, on purpose — so a
    pass that dies after opening must not lose it. This is why the save list
    is built in a `finally`."""
    monkeypatch.setattr(at, "STATE_DIR", tmp_path)
    monkeypatch.setattr(at, "STATE_PATH", tmp_path / "auto_trade_state.json")
    monkeypatch.setattr(at, "STATE_LOCK_PATH", tmp_path / "state.lock")
    monkeypatch.setattr(at, "LEDGER_PATH", tmp_path / "ledger.jsonl")
    monkeypatch.setattr(at, "load_settings", lambda: {
        "strategies": [A], "strategy_coins": {A: [COIN]},
        "strategy_books": {A: ["paper"]}})
    monkeypatch.setattr(at, "active_modes", lambda s: [True])
    monkeypatch.setattr(at, "timeframe_conflicts", lambda s: [])
    monkeypatch.setattr(at, "adopt_orphans", lambda *a, **k: None)
    monkeypatch.setattr(at, "reconcile_unconfigured", lambda *a, **k: None)
    monkeypatch.setattr(at, "tripped_strategies", lambda s, dry=None: [])
    monkeypatch.setattr(at, "coins_for", lambda key, s: [COIN])

    def _opens_then_dies(symbol, settings, state, *, fx, dry, tripped):
        state[at.state_key(symbol, dry, A)] = {"step": 0, "last_ts": {},
                                               "position": _pos(A)}
        raise RuntimeError("MEXC 510 rate limit")

    monkeypatch.setattr(at, "process_symbol", _opens_then_dies)
    at.run_cycle(fx=object())          # must not propagate

    slot = at.state_key(COIN, True, A)
    assert at.load_state().get(slot, {}).get("position"), \
        "a pass that raised after opening lost the position"
