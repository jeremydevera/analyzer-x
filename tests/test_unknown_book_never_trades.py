"""An unreadable order book must refuse the order, not place it.

Operator, Sep 05, 2026: *"i have trades in demo that is winning but i have
trades in live that is losing"*. Three live trades on PSXSTOCK_USDT, each
paired with a demo trade of the same strategy in the same second:

    08:45:09  LIVE  SHORT willr14_15m_sl1tp12 entry 253.50 -> 257.72  -1.80
    08:45:10  PAPER SHORT willr14_15m_sl1tp12 entry 257.35 -> 254.26  +0.98
    09:01:18  LIVE  ... entry 253.53 -> 257.72                        -1.78
    09:01:18  PAPER ... entry 257.51 -> 254.42                        +0.98
    09:17:21  LIVE  ... entry 253.52 -> 257.72                        -1.78
    09:17:22  PAPER ... entry 257.75 -> 254.66                        +0.98

CLAUDE.md rule 12 already says it: "`unknown` (book unreadable) is never
treated as ok." `edge_check` is honest — it returns `{"verdict": "unknown"}`
when `book_cost` raises, and `test_a_broken_book_reader_is_unknown_not_ok`
covers that. The CALLER was not: it refused only on `"block"`, so `"unknown"`
fell through to the order.

PSXSTOCK's book is ~1.9% round trip against a 1.20% take-profit — 162% of the
target, which the gate blocks on every reading it manages to take (09:06:44,
09:12:10). At 08:45, 09:01 and 09:17 it took no reading, said `unknown`, and
the order went out. The runner then sold into a bid 1.5% below the last price,
recomputed the stop from that fill (256.04 instead of the intended 259.944),
found it already breached (MEXC 5003), and closed at the ask.

Worse, the unknown was CACHED for `_GATE_TTL` (300 s), so one failed read
opened a five-minute window in which every signal on that pair traded ungated
— and because the caller only logged on `"block"`, an `unknown` left no log
line and no ledger row at all. The order was the only evidence.
"""
from __future__ import annotations

from tradingagents import auto_trader as at


# --------------------------------------------------------------- the verdict
def test_an_unreadable_book_refuses_the_order():
    """rule 12, as a decision rather than a docstring."""
    assert at.gate_refuses({"verdict": "unknown"}) is True, \
        "an unreadable book is not permission to trade"
    assert at.gate_refuses({"verdict": "block"}) is True


def test_a_readable_book_still_trades():
    """The gate must not become a blanket refusal — `warn` is 'allow, loudly'
    (COST_RATIO_WARN), and `ok` is the ordinary case."""
    assert at.gate_refuses({"verdict": "ok"}) is False
    assert at.gate_refuses({"verdict": "warn"}) is False


def test_a_verdict_that_is_missing_entirely_refuses():
    """A gate result with no verdict is less information than `unknown`, not
    more. Defaulting to trade is how this class of bug is written."""
    assert at.gate_refuses({}) is True
    assert at.gate_refuses({"verdict": None}) is True


# ---------------------------------------------------------------- the cache
def test_an_unknown_is_never_cached(monkeypatch):
    """A cached `unknown` turned one failed read into five minutes of ungated
    trading. It must be retried on the very next cycle instead."""
    at._GATE_CACHE.clear()
    calls = {"n": 0}

    def _flaky(key, symbol, margin, *, fx=None):
        calls["n"] += 1
        return {"verdict": "unknown", "reason": "510 rate limit"}

    monkeypatch.setattr(at, "edge_check", _flaky)
    for _ in range(3):
        at._edge_gate_cached("k", "PSXSTOCK_USDT", 5.0, fx=None)
    assert calls["n"] == 3, \
        f"the book was re-read {calls['n']} time(s) in 3 cycles, not 3"
    assert ("k", "PSXSTOCK_USDT") not in at._GATE_CACHE


def test_a_real_verdict_is_still_cached(monkeypatch):
    """The cache exists because `book_cost` walks a live order book; a good
    reading must not be thrown away with the bad ones."""
    at._GATE_CACHE.clear()
    calls = {"n": 0}

    def _ok(key, symbol, margin, *, fx=None):
        calls["n"] += 1
        return {"verdict": "block", "reason": "162% of the target"}

    monkeypatch.setattr(at, "edge_check", _ok)
    for _ in range(3):
        at._edge_gate_cached("k", "PSXSTOCK_USDT", 5.0, fx=None)
    assert calls["n"] == 1, "a readable book must be cached, not re-walked"
    assert at._GATE_CACHE[("k", "PSXSTOCK_USDT")][1]["verdict"] == "block"


def test_the_cache_still_expires(monkeypatch):
    at._GATE_CACHE.clear()
    calls = {"n": 0}

    def _ok(key, symbol, margin, *, fx=None):
        calls["n"] += 1
        return {"verdict": "ok"}

    monkeypatch.setattr(at, "edge_check", _ok)
    at._edge_gate_cached("k", "S_USDT", 5.0, fx=None)
    # age the entry past the TTL
    ts, res = at._GATE_CACHE[("k", "S_USDT")]
    at._GATE_CACHE[("k", "S_USDT")] = (ts - at._GATE_TTL - 1, res)
    at._edge_gate_cached("k", "S_USDT", 5.0, fx=None)
    assert calls["n"] == 2, "a stale reading must be re-taken"


# ------------------------------------------------------------- the call site
def test_the_entry_path_uses_the_shared_decision():
    """The line that was wrong. A helper nothing calls fixes nothing — this is
    the same shape as the paper slot key that changed in one place only."""
    import inspect

    src = inspect.getsource(at._process_slot)
    assert "gate_refuses(" in src, \
        "the entry path must ask the shared decision, not re-spell it"
    assert 'gate["verdict"] == "block"' not in src, \
        'refusing only on "block" is what let an unreadable book trade'


def test_a_refusal_is_always_recorded():
    """`unknown` used to leave NO log line and NO ledger row — the live order
    was the only evidence it had happened. Every refusal is written down."""
    import inspect

    src = inspect.getsource(at._process_slot)
    i = src.index("gate_refuses(")
    tail = src[i:i + 2000]
    assert "append_ledger(" in tail, "a refused entry must reach the ledger"
    assert "gate_blocked" in tail
    assert "continue" in tail, "and must not fall through to the order"


def test_the_reason_survives_an_exception(monkeypatch):
    """The ledger row for an unknown has to say WHY it could not read the
    book, or "gate_blocked" with an empty reason sends somebody to the logs."""
    class Broken:
        def book_cost(self, symbol, notional):
            raise RuntimeError("510 request frequency too high")

    r = at.edge_check(next(iter(at.STRATEGY_SPECS)), "PSXSTOCK_USDT", 5.0,
                      fx=Broken())
    assert r["verdict"] == "unknown"
    assert "510" in r["reason"], r["reason"]
    assert at.gate_refuses(r) is True
