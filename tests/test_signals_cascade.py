"""The NON-LINEAR confluence rules: cascades, votes and vetoes.

Operator, Sep 11, 2026: *"Make sure the formula for the strategy is not
linear, meaning for example if i met this criteria then open a position ...
you can use (if confluence 1 is met then open else if confluence 2 is met
open as well else if confluence 3 is met open ad well)"*, and *"you should
use differenct approach per coin per timeframe"*.

`build_cascades` takes its pieces as arguments, so these drive the real rules
with FAKE member setups — the combination logic is what is under test, and a
fake lets a test say "soup1 says long, mom says short" in one line.
"""
import pytest

from tradingagents.signals_cascade import build_cascades


def _ok(opens, close):
    return bool(opens) and bool(close)


def _zeros(close):
    return [0] * len(close)


def _bundle(*a, **k):
    return {"fake": True}


def _level1(o, h, l, c, b):
    """Pretend every bar is WITH the trend unless the test says otherwise."""
    return list(_LEVEL1)


def _level2_hits(o, h, l, c, v, t, b):
    return list(_HITS)


_LEVEL1: list = []
_HITS: list = []


# every rule abstains under five bars (signals_conf's own floor), so the
# fixtures are PADDED to that and only the bars a test wrote are compared
_MIN_BARS = 5


def _rules(**says):
    """Build the cascades over member setups that say exactly what a test
    dictates. `says` maps a setup name to its per-bar directions."""
    n = max((len(v) for v in says.values()), default=1)
    width = max(n, _MIN_BARS)
    setups = {}
    for name in ("soup1", "mom", "soup", "donch", "ttm",
                 "bosfvg", "obretest", "stflip", "diadx"):
        seq = list(says.get(name, [])) + [0] * width
        setups[name] = (lambda s: (lambda *a, **k: list(s)))(seq[:width])
    return build_cascades(setups, _bundle, _level1, _level2_hits, _ok, _zeros), n


def _run(name, **says):
    global _LEVEL1, _HITS
    rules, n = _rules(**says)
    width = max(n, _MIN_BARS)
    _LEVEL1 = (list(_LEVEL1) + [1] * width)[:width]
    _HITS = (list(_HITS) + [0] * width)[:width]
    close = [100.0] * width
    got = rules[name]([100.0] * width, close, close, close, [1.0] * width,
                      [i * 3600_000 for i in range(width)])
    return got[:n]                      # only the bars the test wrote


@pytest.fixture(autouse=True)
def _reset():
    global _LEVEL1, _HITS
    _LEVEL1, _HITS = [], []
    yield
    _LEVEL1, _HITS = [], []


# ------------------------------------------------------- the operator's shape

def test_the_first_confluence_that_fires_wins_and_the_rest_are_not_asked():
    """"if confluence 1 is met then open else if confluence 2 is met open as
    well" — and when the first one is silent the second gets its turn."""
    got = _run("cx_first", soup1=[1, 0, 0], mom=[-1, -1, 0], soup=[0, 0, 1])
    assert got == [1, -1, 1], got


def test_the_priority_ORDER_changes_the_trade():
    """The same four setups, asked in the other order, take the other side —
    which is why both orders are measured and neither is assumed."""
    says = {"soup1": [1], "mom": [0], "soup": [0], "donch": [-1]}
    assert _run("cx_first", **says) == [1]
    assert _run("cx_firstr", **says) == [-1]


# --------------------------------------------------------------- the votes

def test_no_setup_can_open_a_trade_alone():
    assert _run("cx_any2", soup1=[1], mom=[0], soup=[0], donch=[0]) == [0]
    assert _run("cx_any2", soup1=[1], mom=[1], soup=[0], donch=[0]) == [1]


def test_a_tie_is_not_a_majority():
    """Two longs against two shorts is the market disagreeing with itself —
    exactly the bar where a single-setup rule would happily trade."""
    assert _run("cx_any2", soup1=[1], mom=[1], soup=[-1], donch=[-1]) == [0]


def test_three_of_five_is_stricter_than_two_of_four():
    two = {"soup1": [1], "mom": [1], "soup": [0], "donch": [0], "ttm": [0]}
    assert _run("cx_any2", **two) == [1]
    assert _run("cx_maj3", **two) == [0], "two votes must not clear a 3-of-5"
    assert _run("cx_maj3", soup1=[1], mom=[1], soup=[1], donch=[0],
                ttm=[0]) == [1]


# ---------------------------------------------------- veto and escalator

def test_a_disagreement_cancels_the_trade():
    assert _run("cx_veto", soup1=[1], mom=[0]) == [1], "no objection, take it"
    assert _run("cx_veto", soup1=[1], mom=[-1]) == [0], "mom objects"
    assert _run("cx_veto", soup1=[1], mom=[1]) == [1], "mom agrees"


def test_the_escalator_asks_for_less_agreement_WITH_the_trend():
    """Two votes behind the 200-bar trend, three in front of it. Same bar,
    same setups, different answer — the non-linear part."""
    global _LEVEL1
    says = {"soup1": [1], "mom": [1], "soup": [0], "donch": [0], "ttm": [0]}
    _LEVEL1 = [1]
    assert _run("cx_esc", **says) == [1], "with the trend, two is enough"
    _LEVEL1 = [-1]
    assert _run("cx_esc", **says) == [0], "against it, two is not"


def test_the_level_escalator_falls_back_through_the_gates():
    global _LEVEL1, _HITS
    # ungated soup1 with mom agreeing is the weakest rung that still trades
    _LEVEL1, _HITS = [-1], [0]
    assert _run("cx_lvl", soup1=[1], mom=[1]) == [1]
    _LEVEL1, _HITS = [-1], [0]
    assert _run("cx_lvl", soup1=[1], mom=[0]) == [0], "nothing agrees: no trade"


def test_the_control_is_the_only_linear_one():
    """`cx_both` demands agreement from everybody, so it is in the table to
    show what that costs in trades — not because it is the design."""
    assert _run("cx_both", soup1=[1], mom=[1]) == [1]
    assert _run("cx_both", soup1=[1], mom=[0]) == [0]


# ------------------------------------------------------------- robustness

def test_one_broken_member_does_not_silence_the_cascade():
    """A member that raises casts no vote; the others still decide. Ten rules
    sharing nine setups must not all die because one of them threw."""
    def boom(*a, **k):
        raise ValueError("this setup is broken")

    setups = {n: (lambda *a, **k: [0] * 5) for n in
              ("soup1", "mom", "soup", "donch", "ttm",
               "bosfvg", "obretest", "stflip", "diadx")}
    setups["mom"] = boom
    setups["soup1"] = lambda *a, **k: [1] * 5
    rules = build_cascades(setups, _bundle, _level1, _level2_hits, _ok, _zeros)
    global _LEVEL1, _HITS
    _LEVEL1, _HITS = [1] * 5, [0] * 5
    five = [1.0] * 5
    assert rules["cx_first"](five, five, five, five, five,
                             [0, 1, 2, 3, 4])[0] == 1


def test_a_rule_with_no_opens_abstains():
    """The contract every signal in this repo keeps: missing input means
    zeros, never a guess."""
    rules, _ = _rules(soup1=[1, 1, 1])
    five = [1.0] * 5
    assert rules["cx_first"]([], five, five, five, five,
                             [0, 1, 2, 3, 4]) == [0] * 5


# ------------------------------------------------- wired into both engines

def test_every_cascade_is_measurable_AND_tradeable():
    """A rule the grid can pick and the runner cannot emit is a strategy that
    trades zero times once deployed (the signals_ext lesson, 2026-08-19).
    They register into CONF_SIGNALS, which both dispatchers already walk."""
    from tradingagents import backtest_report as br
    from tradingagents.signals_conf import CONF_SIGNALS

    cx = sorted(k for k in CONF_SIGNALS if k.startswith("cx_"))
    assert len(cx) == 10, cx
    for name in cx:
        assert name in br.SIGNALS, f"{name} is not in the grid's signal list"


def test_the_longer_name_cannot_swallow_the_shorter_one():
    """`cx_first` and `cx_firstr` differ by one letter, and the dispatcher
    matches by prefix — a key like `cx_first_1h_sl2tp4` must reach cx_first,
    never cx_firstr."""
    from tradingagents.signals_conf import CONF_SIGNALS

    key = "cx_first_1h_sl2tp4"
    hit = next(n for n in sorted(CONF_SIGNALS, key=len, reverse=True)
               if key == n or key.startswith(n + "_"))
    assert hit == "cx_first"
