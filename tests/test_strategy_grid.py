"""The editable strategy grid's pure logic.

The grid is a canvas widget, so its cells cannot be driven by a DOM click in
the test harness. What CAN be pinned is everything the grid hands back: the
book round-trip and the contract parsing. Those two decide whether a strategy
trades real money and on what, so they are tested directly.
"""
import pytest

import app
from tradingagents import auto_trader as at

# ------------------------------------------------------ book round-trip

@pytest.mark.parametrize("choice,books", [
    ("off", []),
    ("paper", ["paper"]),
    ("real", ["real"]),
    ("both", ["real", "paper"]),
])
def test_choice_to_books_round_trips(choice, books):
    assert app._choice_to_books(choice) == books
    assert app._books_to_choice(books) == choice


def test_books_to_choice_ignores_order():
    assert app._books_to_choice(["paper", "real"]) == "both"


def test_unknown_contents_never_grant_a_real_book():
    """Anything that is not literally 'real' must not open the live book."""
    assert app._books_to_choice(["REAL"]) == "off"
    assert app._books_to_choice(["live"]) == "off"
    assert app._books_to_choice([]) == "off"


# -------------------------------------------------------- contract text

def test_bare_symbols_get_the_usdt_suffix():
    good, bad = app._parse_contracts("PI, PROVE")
    assert good == ["PI_USDT", "PROVE_USDT"]
    assert bad == []


def test_full_symbols_are_left_alone():
    good, _ = app._parse_contracts("BTC_USDT, ETH_USDT")
    assert good == ["BTC_USDT", "ETH_USDT"]


def test_case_and_whitespace_are_forgiven():
    good, _ = app._parse_contracts("  pi ,   prove  ,\tapex ")
    assert good == ["PI_USDT", "PROVE_USDT", "APEX_USDT"]


def test_duplicates_collapse():
    good, _ = app._parse_contracts("PI, pi, PI_USDT")
    assert good == ["PI_USDT"]


def test_empty_and_trailing_commas_are_not_symbols():
    assert app._parse_contracts("") == ([], [])
    assert app._parse_contracts("  ") == ([], [])
    assert app._parse_contracts("PI,,") == (["PI_USDT"], [])


def test_unknown_symbol_is_REPORTED_not_silently_dropped():
    """A typo that quietly empties a strategy is how a book stops trading
    without anyone noticing."""
    good, bad = app._parse_contracts("PI, PRVE", known={"PI_USDT"})
    assert good == ["PI_USDT"]
    assert bad == ["PRVE_USDT"]


def test_no_known_set_means_no_validation():
    """Offline, the contract list cannot be fetched; the operator's saved
    picks must still survive a rerun rather than being rejected wholesale."""
    good, bad = app._parse_contracts("ANYTHING", known=None)
    assert good == ["ANYTHING_USDT"]
    assert bad == []


def test_none_is_not_a_crash():
    assert app._parse_contracts(None) == ([], [])


def test_contracts_column_is_READ_ONLY():
    """The operator picks the best strategy PER COIN, so the coin is part of
    the strategy, not a field to retype. An editable box let a row's signal be
    pointed at a contract that combination was never backtested on."""
    import ast
    import inspect
    import pathlib

    src = pathlib.Path(inspect.getfile(app)).read_text(encoding="utf-8")
    tree = ast.parse(src)
    keys = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == "text_input"):
            continue
        for kw in node.keywords:
            if kw.arg == "key" and isinstance(kw.value, ast.JoinedStr):
                keys.append(ast.unparse(kw.value))
    assert not [k for k in keys if "g_c_" in k], (
        f"contracts column is editable again: {keys}")


# --------------------------------------------------------------------------
# One coin runs ONE timeframe — enforced where the choice is made.
# The operator's words: "if i enable 15m timeframe for pi, i should not be
# able to enable the 1hr timeframe for pi".
SPECS = {
    "pi_30m": {"interval": "Min30"},
    "pi_4h": {"interval": "Hour4"},
    "pi_30m_b": {"interval": "Min30"},
    "prove_1h": {"interval": "Min60"},
}
ROWS = [("pi_30m", ["PI_USDT"]), ("pi_4h", ["PI_USDT"]),
        ("prove_1h", ["PROVE_USDT"])]


def test_arming_a_coin_locks_it_on_every_other_timeframe():
    locks = app._timeframe_locks(ROWS, SPECS, lambda k: k == "pi_30m")
    assert locks == {"pi_4h": ("PI_USDT", "pi_30m")}


def test_nothing_is_locked_while_the_holder_is_off():
    """An unarmed row holds no coin — the operator must be free to pick
    either timeframe from a cold start."""
    assert app._timeframe_locks(ROWS, SPECS, lambda k: False) == {}


def test_the_lock_frees_itself_when_the_holder_is_unticked():
    on = {"pi_30m"}
    assert "pi_4h" in app._timeframe_locks(ROWS, SPECS, lambda k: k in on)
    on.clear()
    assert app._timeframe_locks(ROWS, SPECS, lambda k: k in on) == {}, \
        "unticking 30m must release PI, not strand the coin"
    on.add("pi_4h")
    assert app._timeframe_locks(ROWS, SPECS, lambda k: k in on) == \
        {"pi_30m": ("PI_USDT", "pi_4h")}, "the coin swaps sides cleanly"


def test_display_order_decides_the_holder_not_which_was_ticked_last():
    """Deterministic: the first tile wins, so the row that keeps the coin is
    never a function of click order."""
    both = app._timeframe_locks(ROWS, SPECS, lambda k: True)
    assert both == {"pi_4h": ("PI_USDT", "pi_30m")}


def test_a_different_coin_is_never_locked():
    locks = app._timeframe_locks(ROWS, SPECS, lambda k: True)
    assert "prove_1h" not in locks


def test_same_timeframe_twice_is_not_a_conflict():
    """The rule is one TIMEFRAME per coin. Two rows on the same bar size are
    one position on one bar size, which the runner already handles."""
    rows = [("pi_30m", ["PI_USDT"]), ("pi_30m_b", ["PI_USDT"])]
    assert app._timeframe_locks(rows, SPECS, lambda k: True) == {}


def test_every_shipped_tile_carries_at_least_one_contract():
    """A row with no contract can be armed and trades nothing — that is the
    `contracts: none` the operator found on mom15_4h_w."""
    empty = [k for k, _l, _n, coins in app.AUTO_STRATEGIES if not coins]
    assert empty == [], f"tiles with no contract: {empty}"


def test_the_shipped_tiles_never_double_book_a_coin_by_themselves():
    locks = app._timeframe_locks(
        [(k, list(c)) for k, _l, _n, c in app.AUTO_STRATEGIES],
        at.STRATEGY_SPECS, lambda k: True)
    # Locks are allowed — they are the guard working — but every locked row
    # must be the SECOND holder, never the deployed one.
    for key, (coin, holder) in locks.items():
        assert holder != key
        assert coin in {k: c for k, _l, _n, c in app.AUTO_STRATEGIES}[key]


def test_a_locked_row_cannot_go_LIVE_but_DEMO_stays_free():
    """`disabled=` must be wired to the lock, or the guard is decorative — and
    it must be wired to LIVE only: the operator papers two timeframes on one
    coin on purpose, to compare them."""
    src = open("app.py").read()
    assert 'key=f"g_live_{key}", disabled=bool(_lock)' in src
    assert 'key=f"g_demo_{key}", disabled=bool(_lock)' not in src, \
        "DEMO is never locked"
    assert 'st.session_state[f"g_live_{key}"] = False' in src, \
        "a disabled box that stays green is a false label"


def test_the_lock_is_SYMMETRIC_whichever_row_is_armed():
    """Arming the LOWER row must lock the upper one too. A single-pass rule
    only locked rows below the holder, so ticking the 4h row left the 30m row
    above it armable and both could be on at once."""
    locks = app._timeframe_locks(ROWS, SPECS, lambda k: k == "pi_4h")
    assert locks == {"pi_30m": ("PI_USDT", "pi_4h")}


def test_an_already_double_booked_row_does_not_claim_a_second_coin():
    """A saved file with both rows armed: the first keeps PI, the second is
    locked — and must not go on to claim anything else as if it were live."""
    rows = [("pi_30m", ["PI_USDT"]), ("pi_4h", ["PI_USDT", "PROVE_USDT"]),
            ("prove_1h", ["PROVE_USDT"])]
    locks = app._timeframe_locks(rows, SPECS, lambda k: True)
    assert locks == {"pi_4h": ("PI_USDT", "pi_30m")}
    assert "prove_1h" not in locks, "PROVE was never claimed by a locked row"


def test_the_streak_column_reads_the_book_the_row_trades():
    """`3 loss` was read from the LIVE ladder on a DEMO-only row. The ladder
    lives on the coin AND the book — `PI_USDT` vs `PI_USDT#paper`."""
    src = open("app.py").read()
    assert '_bk = "" if (False in _bks or not _bks) else "#paper"' in src
    assert '_runstate.get(c + _bk)' in src


def test_the_streak_column_names_whose_streak_it_is():
    """label-must-match-data: `3 loss` on the trend50 row read as trend50's
    record. trend50 had never traded — it was PI's ladder, inherited from
    mom15_4h_w, and it is what NEXT $ is computed from."""
    src = open("app.py").read()
    assert 'loss &middot; {_who}' in src
    assert "_who = " in src


def test_tile_labels_are_DERIVED_from_the_spec_not_typed():
    """Two tiles advertised barriers the runner does not trade: APEX said
    'TP 4.0%' against a real 3.0% (changed 2026-08-19, text not), and XAUT said
    'TP 2.4%' against 2.0%. A label that repeats a number will disagree with it
    eventually, so it is built from STRATEGY_SPECS."""
    import re
    for key, raw, _note, _coins in app.AUTO_STRATEGIES:
        spec = at.STRATEGY_SPECS[key]
        shown = app._strategy_label(key, raw)
        assert "TP " not in raw and "SL " not in raw, \
            f"{key}: barriers are typed into the label again"
        tp = float(re.search(r"TP ([\d.]+)%", shown).group(1))
        sl = float(re.search(r"SL ([\d.]+)%", shown).group(1))
        assert abs(tp - spec["tp"] * 100) < 0.005, f"{key} TP label"
        assert abs(sl - spec["sl"] * 100) < 0.005, f"{key} SL label"


def test_the_label_keeps_its_contract_suffix():
    shown = app._strategy_label("mom6_1h_gx", "Momentum 6 (1h) — XAUT gold")
    assert shown == "Momentum 6 (1h) · TP 2.00% / SL 1.50% — XAUT gold"


def test_the_august_prove_row_is_the_one_the_operator_asked_for():
    """#8ZFUXG8F, added 2026-08-19. Three rows in the August sweep are identical
    in coin, bar, signal, barriers and sizing and differ ONLY in threshold —
    0.20 is #8ZFUXG8F, 0.30 is #5P3SYZDY, 0.50 is #AVEP6U3N — so the spec must
    carry 0.20 or the deployed row is not the row that was picked."""
    from tradingagents import backtest_report as br
    spec = at.STRATEGY_SPECS["fade15_1h_pv2"]
    assert spec == {"interval": "Min60", "bar_seconds": 3600,
                    "tp": 0.080, "sl": 0.003, "threshold": 0.002}
    assert br.row_code("PROVE", "1h", "fade15", spec["threshold"] * 100,
                       spec["sl"] * 100, spec["tp"] * 100,
                       "martingale") == "8ZFUXG8F"
    assert "fade15_1h_pv2" in at.STRATEGY_ORDER


def test_no_coin_has_two_LIVE_strategies_at_once():
    """The real invariant, replacing an assertion that the new PROVE tile ships
    unarmed — the operator armed it themselves at 22:46 on 2026-08-19 and moved
    mom6_1h_pv to paper, which is the correct swap. What must never happen is
    TWO live strategies on one coin: MEXC nets them into a single position, so
    the second entry resizes the first and either stop closes part of a trade it
    does not own. Until sliced brackets ship, one live row per coin."""
    import collections
    import json
    import pathlib

    import pytest

    # This asserts on the OPERATOR'S live configuration, which exists only on
    # their machine. A CI runner has no ~/.tradingagents, so the test raised
    # FileNotFoundError there and the whole suite went red on every push for a
    # file it can never have. Skip where there is nothing to check; the
    # invariant still runs where it matters, which is the machine that trades.
    cfg = pathlib.Path.home() / ".tradingagents" / "auto_trade.json"
    if not cfg.exists():
        pytest.skip("no live auto_trade.json on this machine")
    saved = json.loads(cfg.read_text())
    live = collections.defaultdict(list)
    for key in saved.get("strategies", []):
        if "real" not in ((saved.get("strategy_books") or {}).get(key) or []):
            continue
        for coin in at.coins_for(key, saved):
            live[coin].append(key)
    clashes = {c: ks for c, ks in live.items() if len(ks) > 1}
    assert not clashes, f"coins with two LIVE strategies: {clashes}"


def test_the_new_tile_is_offered_in_the_ui():
    keys = [k for k, *_ in app.AUTO_STRATEGIES]
    assert "fade15_1h_pv2" in keys
    coins = {k: c for k, _l, _n, c in app.AUTO_STRATEGIES}
    assert coins["fade15_1h_pv2"] == ("PROVE_USDT",)


def test_the_operators_row_name_is_drawn_in_the_strategy_column():
    """"i said to add the 8.67 in the name" — the tile label only appears on the
    backtest header, so the name has to reach the grid row itself."""
    src = open("app.py").read()
    assert "_TILE_TAGS" in src
    assert app._TILE_TAGS.get("fade15_1h_pv2") == "Best 8.67 for August"
    assert "_tag = _TILE_TAGS.get(key)" in src
    assert "html.escape(_tag)" in src, "an operator-supplied name must be escaped"


def test_the_tag_matches_the_tile_label():
    """Two places carry the name; they must not drift apart."""
    labels = {k: l for k, l, _n, _c in app.AUTO_STRATEGIES}
    for key, tag in app._TILE_TAGS.items():
        assert tag in labels[key], f"{key}: label {labels[key]!r} lacks {tag!r}"


# ---------------------------------------------------------- one live per coin
# The operator's rule, in their words: "a coin should not have 2 strategies
# running for live ... but for demo it can have multiple strategies so i can
# see if its working".
def _cfg(books, coins):
    return {"strategies": list(books), "strategy_books": books,
            "strategy_coins": coins}


def test_two_live_strategies_on_one_coin_is_blocked_at_any_timeframe():
    """The guard compared TIMEFRAMES, so it only caught clashes across
    different bar sizes. PROVE ran fade15_1h_pv2 and mom6_1h_pv live together
    at the same 1h on 2026-08-22 and it waved them through. MEXC nets by
    CONTRACT; the bar size has nothing to do with it."""
    order = list(at.STRATEGY_ORDER)
    pair = [k for k in order if (at.STRATEGY_SPECS.get(k) or {}).get("interval")]
    a, b = pair[0], next(k for k in pair[1:]
                         if (at.STRATEGY_SPECS[k].get("interval")
                             == at.STRATEGY_SPECS[pair[0]].get("interval")))
    cfg = _cfg({a: ["real"], b: ["real"]},
               {a: ["PROVE_USDT"], b: ["PROVE_USDT"]})
    locks = at.timeframe_locks(cfg)
    assert len(locks) == 1, f"same-timeframe clash not caught: {locks}"
    loser = next(iter(locks))
    assert locks[loser]["coin"] == "PROVE_USDT"
    assert locks[loser]["held_by"] != loser


def test_demo_may_run_as_many_strategies_on_one_coin_as_it_likes():
    """Comparing strategies side by side on one coin is the POINT of paper."""
    order = list(at.STRATEGY_ORDER)[:4]
    cfg = _cfg({k: ["paper"] for k in order},
               {k: ["PROVE_USDT"] for k in order})
    assert at.timeframe_locks(cfg) == {}, "demo must never be locked"


def test_a_live_row_does_not_lock_a_demo_row_on_the_same_coin():
    """One live plus several demo on one coin is the normal, wanted setup."""
    order = list(at.STRATEGY_ORDER)
    live, d1, d2 = order[0], order[1], order[2]
    cfg = _cfg({live: ["real"], d1: ["paper"], d2: ["paper"]},
               {live: ["PROVE_USDT"], d1: ["PROVE_USDT"], d2: ["PROVE_USDT"]})
    locks = at.timeframe_locks(cfg)
    assert live not in locks, "the live holder must not lock itself"
    # the demo rows are reported as unable to GO live, which is true, and it
    # does not stop them trading on paper
    assert set(locks) <= {d1, d2}


def test_the_runner_refuses_a_live_entry_on_a_coin_already_live():
    """A save-time check cannot protect a config that is ALREADY double-booked
    — which is exactly the state the operator's machine was in."""
    import inspect

    src = inspect.getsource(at.process_symbol)
    assert "_live_locks = timeframe_locks(settings) if not dry else {}" in src, (
        "the runner must consult the lock, not just the settings screen")
    i = src.index("_live_locks.get(key)")
    body = src[i:i + 900]
    assert "REFUSED live entry" in body, "a refusal must be logged loudly"
    assert '"action": "refused"' in body, "and recorded in the ledger"
    assert "continue" in body, "and must actually skip the order"
