"""Each DEMO strategy gets its own position and its own ladder rung.

Operator, 2026-08-27: *"i deployed multiple strategy for BTC coin in live
strategy / i think the lose and w is being inherited by all strategy for BTC /
i want it isolated meaning if i click live and demo, the win and lose should be
for that strat only"*.

Measured before the change, two demo strategies on one coin:

  * POSITION shared. `state_key(symbol, dry)` returned "BTC_USDT#paper" for
    both, and a slot holds ONE position, so the first strategy to open blocked
    the other. Demo is exempt from the live lock precisely so strategies can be
    compared side by side on a coin ("for demo it can have multiple strategies
    so i can see if its working") - which that made impossible.
  * LADDER RUNG shared, and it cost money: after four losses by
    stoch14_1h_sl3tp3, pivot_1h_sl3tp3's next stake was $20.00 instead of
    $5.00, having never lost a trade.
  * W/L RECORD already isolated - the exit row carries the strategy the
    POSITION held, so `strategy_stats` grouped 0W/2L against 1W/0L correctly.
    That half of the report was wrong and this file says so.

The REAL book keeps ONE slot per coin. MEXC nets every order on a contract into
a single position; a per-strategy real slot would be a position that cannot
exist, and `timeframe_locks` already refuses a second live strategy on a coin.
"""
import json

import pytest

from tradingagents import auto_trader as at

A, B = "stoch14_1h_sl3tp3", "pivot_1h_sl3tp3"
COIN = "BTC_USDT"


def _settings(book="paper", sizing="martingale"):
    return {"strategies": [A, B],
            "strategy_coins": {A: [COIN], B: [COIN]},
            "strategy_books": {A: [book], B: [book]},
            "strategy_margins": {A: 5.0, B: 5.0},
            "strategy_sizing": {A: sizing, B: sizing}}


def test_two_demo_strategies_get_two_slots():
    a = at.state_key(COIN, True, A)
    b = at.state_key(COIN, True, B)
    assert a != b, (a, b)
    assert a == f"{COIN}#paper#{A}" and b == f"{COIN}#paper#{B}"


def test_the_real_book_is_still_one_slot_per_coin():
    """The exchange nets; a second real slot would be a fiction."""
    assert at.state_key(COIN, False, A) == COIN
    assert at.state_key(COIN, False, B) == COIN
    assert at.state_key(COIN, False) == COIN


def test_one_strategys_losing_run_no_longer_raises_the_others_stake():
    """The measured failure: $20.00 instead of $5.00 on a strategy that had
    never lost."""
    s = _settings()
    state = {at.state_key(COIN, True, A): {"step": 4, "position": None,
                                           "last_ts": {}},
             at.state_key(COIN, True, B): {"step": 0, "position": None,
                                           "last_ts": {}}}
    step_a = state[at.state_key(COIN, True, A)]["step"]
    step_b = state[at.state_key(COIN, True, B)]["step"]
    assert step_a == 4 and step_b == 0
    assert at.staked_margin(A, s, step_a) == pytest.approx(20.0)
    assert at.staked_margin(B, s, step_b) == pytest.approx(5.0), \
        "B never lost; its stake must be the base"


def test_both_demo_strategies_can_hold_a_position_at_once():
    state = {}
    for key in (A, B):
        state.setdefault(at.state_key(COIN, True, key),
                         {"step": 0, "last_ts": {}, "position": None})
        state[at.state_key(COIN, True, key)]["position"] = {
            "strategy": key, "side": 1, "entry": 100.0, "dry": True}
    open_on = [(at.strategy_of_slot(k), v["position"]["strategy"])
               for k, v in state.items() if v.get("position")]
    assert len(open_on) == 2, open_on
    for slot_owner, pos_owner in open_on:
        assert slot_owner == pos_owner


def test_the_slot_helpers_read_every_key_shape():
    assert at.is_paper_slot(f"{COIN}#paper#{A}") is True
    assert at.is_paper_slot(f"{COIN}#paper") is True
    assert at.is_paper_slot(COIN) is False
    assert at.coin_of_slot(f"{COIN}#paper#{A}") == COIN
    assert at.coin_of_slot(COIN) == COIN
    assert at.strategy_of_slot(f"{COIN}#paper#{A}") == A
    assert at.strategy_of_slot(f"{COIN}#paper") is None
    assert at.strategy_of_slot(COIN) is None


def test_an_open_demo_position_is_moved_not_orphaned():
    """Existing state uses the legacy key. Renaming the slot without moving
    the position would leave a demo trade nobody manages."""
    state = {f"{COIN}#paper": {"step": 3, "last_ts": {"Min60": 9},
                               "position": {"strategy": A, "side": 1,
                                            "entry": 100.0, "dry": True}}}
    assert at.migrate_paper_slots(state) == 1
    assert f"{COIN}#paper" not in state
    slot = state[at.state_key(COIN, True, A)]
    assert slot["position"]["strategy"] == A
    assert slot["step"] == 3, "its own rung travels with it"
    assert slot["last_ts"] == {"Min60": 9}


def test_a_legacy_slot_with_no_position_is_dropped():
    """All it carries is a rung that belonged to whichever strategies shared
    the coin. Steps are per strategy now, so keeping it leaves a stale number
    in the state file that nothing reads and a summing reader could double
    count."""
    state = {f"{COIN}#paper": {"step": 7, "position": None, "last_ts": {}}}
    at.migrate_paper_slots(state)
    assert f"{COIN}#paper" not in state
    # and it never becomes anybody's rung
    assert at.state_key(COIN, True, A) not in state


def test_an_open_position_with_no_owner_is_left_for_a_human():
    """Something is open on the demo book and nobody can say whose it is.
    Guessing would put it under a strategy that never opened it."""
    state = {f"{COIN}#paper": {"step": 2, "last_ts": {},
                               "position": {"side": 1, "entry": 100.0}}}
    assert at.migrate_paper_slots(state) == 0
    assert state[f"{COIN}#paper"]["position"] is not None


def test_migration_never_overwrites_a_slot_that_already_has_a_position():
    state = {
        f"{COIN}#paper": {"step": 1, "position": {"strategy": A, "side": 1}},
        at.state_key(COIN, True, A): {"step": 9,
                                      "position": {"strategy": A, "side": -1}},
    }
    assert at.migrate_paper_slots(state) == 0
    assert state[at.state_key(COIN, True, A)]["step"] == 9
    assert f"{COIN}#paper" in state, "left for a human to look at"


def test_the_record_was_already_per_strategy(tmp_path, monkeypatch):
    """The half of the operator's report that was not a bug — say so with the
    numbers rather than quietly agreeing."""
    monkeypatch.setattr(at, "LEDGER_PATH", tmp_path / "ledger.jsonl")
    rows = [{"ts": 10, "action": "exit", "symbol": COIN, "strategy": A,
             "pnl_est": -3.1, "dry_run": True},
            {"ts": 11, "action": "exit", "symbol": COIN, "strategy": A,
             "pnl_est": -3.1, "dry_run": True},
            {"ts": 12, "action": "exit", "symbol": COIN, "strategy": B,
             "pnl_est": +2.9, "dry_run": True}]
    at.LEDGER_PATH.write_text("".join(json.dumps(r) + "\n" for r in rows),
                              encoding="utf-8")
    got = at.strategy_stats(dry=True)
    assert (got[A]["wins"], got[A]["losses"]) == (0, 2)
    assert (got[B]["wins"], got[B]["losses"]) == (1, 0)
    assert got[A]["pnl"] == pytest.approx(-6.2)
    assert got[B]["pnl"] == pytest.approx(2.9)
    # and the books never blend
    assert at.strategy_stats(dry=False) == {}


def test_a_demo_row_shares_its_rung_with_nobody():
    """api.py's `streak_shared_with` named other strategies on the coin. On
    paper that is no longer true, and a false label is what the 2026-08-22 fix
    was about in the other direction."""
    import inspect

    from tradingagents import api

    src = inspect.getsource(api.trade_strategies)
    assert "at.state_key(c, not _is_real, key)" in src, \
        "the rung must be read from the per-strategy slot"
    i = src.index('"streak_shared_with"')
    tail = src[i:i + 400]
    assert "_is_real and other != key" in tail, \
        "only a REAL rung can be shared"
