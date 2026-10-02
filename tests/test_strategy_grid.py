"""The runner's strategy rules that the old strategy grid used to front.

The grid itself lived in app.py, the retired Streamlit screen, removed on
Oct 02, 2026 with the New Crypto, Analysis and LLM Models screens. Its
widget tests went with it; what stays is everything here that tests the
runner (`auto_trader`), which still trades.
"""
from tradingagents import auto_trader as at


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


def test_the_live_config_cannot_lose_more_than_the_account_cap():
    """The old rule here was "one live row per coin, until sliced brackets
    ship". They shipped on Sep 09, 2026 (partial TP/SL), so several live rows
    on one coin is now the operator's own design — PSXSTOCK carries four.

    What replaces it is the number that actually matters: if every slice a
    coin can hold were stopped out at once, would the day's loss still fit
    inside the account loss cap? Measured on the operator's own config,
    Sep 10, 2026: NGAS -0.60, PDDSTOCK -0.50, PSXSTOCK -0.88, STBL -1.60 =
    -3.58 against a $5 cap. The cap counts CLOSED trades, so open slices can
    run past it before it trips — which is exactly why this is checked here,
    against the config, rather than trusted to the breaker.
    """
    import collections
    import json
    import pathlib

    import pytest

    # The OPERATOR'S live configuration exists only on their machine; a CI
    # runner has no ~/.tradingagents and would go red for a file it can never
    # have. The check runs where it matters: the machine that trades.
    cfg = pathlib.Path.home() / ".tradingagents" / "auto_trade.json"
    if not cfg.exists():
        pytest.skip("no live auto_trade.json on this machine")
    saved = json.loads(cfg.read_text())
    limit = float(saved.get("loss_limit") or 0)
    if not limit:
        pytest.skip("no account loss cap set — nothing to measure against")

    live = collections.defaultdict(list)
    for key in saved.get("strategies", []):
        if "real" not in ((saved.get("strategy_books") or {}).get(key) or []):
            continue
        for coin in at.coins_for(key, saved):
            live[coin].append(key)
    if not live:
        pytest.skip("no live strategies armed")

    # how many of a coin's rows can hold at ONE time — one, unless the
    # operator switched partial TP/SL on for the live book
    cap = at.max_slices(saved) if at.partial_on(saved, False) else 1
    worst = {}
    for coin, keys in live.items():
        holding = sorted(keys)[:cap]
        worst[coin] = sum(
            at.margin_for(k, saved) * at.LEVERAGE
            * ((at.STRATEGY_SPECS.get(k) or {}).get("sl") or 0)
            for k in holding)
    total = sum(worst.values())
    assert total <= limit, (
        f"every live slice stopping out at once loses ${total:.2f}, over the "
        f"${limit:.2f} account cap: "
        + ", ".join(f"{c.replace('_USDT', '')} ${w:.2f}"
                    for c, w in sorted(worst.items(), key=lambda x: -x[1])))


# ---------------------------------------------------------- one live per coin
# The operator's rule, in their words: "a coin should not have 2 strategies
# running for live ... but for demo it can have multiple strategies so i can
# see if its working".
def _cfg(books, coins):
    return {"strategies": list(books), "strategy_books": books,
            "strategy_coins": coins}


def test_two_live_strategies_on_one_coin_lock_NOTHING_now():
    """History first: the ARMING lock existed because PROVE ran two live
    strategies at once on 2026-08-22 and MEXC netted them into one position.
    The operator replaced it on 2026-09-04 — 35 rows over 9 coins, 20 on one
    contract — with ONE OPEN POSITION PER COIN, first signal wins, which is
    the tighter guarantee (tests/test_one_position_per_coin.py). So the lock
    is a no-op and arming both is allowed."""
    order = list(at.STRATEGY_ORDER)
    pair = [k for k in order if (at.STRATEGY_SPECS.get(k) or {}).get("interval")]
    a, b = pair[0], next(k for k in pair[1:]
                         if (at.STRATEGY_SPECS[k].get("interval")
                             == at.STRATEGY_SPECS[pair[0]].get("interval")))
    cfg = _cfg({a: ["real"], b: ["real"]},
               {a: ["PROVE_USDT"], b: ["PROVE_USDT"]})
    assert at.timeframe_locks(cfg) == {}


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


def test_the_runner_holds_a_coin_with_the_position_not_a_lock():
    """The runtime protection since 2026-09-04: the real book keeps ONE slot
    per coin, a held coin refuses every other strategy out loud, and the old
    lock consultation is gone from the entry path."""
    import inspect

    src = inspect.getsource(at._process_slot)
    assert "_live_locks" not in src, "the arming lock is gone from the runner"
    assert "ONE OPEN POSITION PER COIN" in src, "the rule is written down"
    # Sep 09, 2026: with PARTIAL TP/SL off (the default) the real book is
    # still one slot per coin; naming a strategy asks for that strategy's
    # SLICE, which only exists while the switch is on.
    assert at.state_key("PROVE_USDT", False) == "PROVE_USDT"
    assert at.partial_on({}, False) is False
    assert at.state_key("PROVE_USDT", False, "b") == "PROVE_USDT#live#b",         "a named strategy asks for its slice; the base slot is the unnamed one"
