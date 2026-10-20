"""THE PRO TRADER RESEARCH'S CHECKS (Oct 20, 2026): what a coin + timeframe row
must pass on the days it was never chosen on, before anyone calls it ready.

The approved prompt's list, each check named and explained on the page:
* pays at least 2:1 after the fees its untouched-days trades PAID;
* makes money with at least 20 WINS on the untouched days, and stays above
  zero at the low end of a 90% range per trade;
* beats random entries with the same stop and target on the same coin;
* still makes money with costs x 1.5 and every stop filling 0.1% worse;
* its neighbouring settings (one knob one step away) make money on average;
* when it is its group's choice, that choice made money on both halves of
  the group's coins;
* every on/off filter in it helps (switching one off made less);
* "one minute late" cannot be measured (the engine has no entry delay) and
  says so — never a silent pass.
Re-choosing before every test month (the walk-forward) is reported beside
them; it does not decide a pass.

A check that cannot be judged is None. The checks a row MUST pass are never
passed by being unjudgeable (`passed`): a row that could not be compared with
random entries, or whose neighbours never traded, has not shown what they ask
(code review, Oct 20, 2026).
"""
from __future__ import annotations

import math

import numpy as np

from tradingagents import pro_report as pr, signals_pro as sp

Z90 = 1.6449                      # one-sided 90%: the low end of the range


def after_fees(sl: float, tp: float, rt: float) -> tuple[float, float]:
    """(a win, a loss) in $ on a $100 trade after a round trip of `rt` %."""
    return tp - rt, sl + rt


def break_even(sl: float, tp: float, rt: float) -> float:
    """The win rate (%) at which this stop/target makes nothing after fees."""
    win, loss = after_fees(sl, tp, rt)
    return 100.0 * loss / (win + loss) if win + loss > 0 else 100.0


def low_end(pnls: list) -> float | None:
    """The low end of a one-sided 90% range for the average trade, or None
    with fewer than 2 trades."""
    n = len(pnls)
    if n < 2:
        return None
    a = np.asarray(pnls, dtype=float)
    return float(a.mean() - Z90 * a.std(ddof=1) / math.sqrt(n))


def neighbours(name: str) -> list[str]:
    """Every setting of the same family one step away on exactly one knob."""
    spec = sp.spec_for(name)
    if spec is None:
        return []
    kn = sp.FAMILIES[spec["family"]]["knobs"]
    out = []
    for j, (_l, _s, values) in enumerate(kn):
        for step in (-1, 1):
            d = list(spec["digits"])
            d[j] += step
            if 0 <= d[j] < len(values):
                out.append(sp.name_of(spec["family"], d))
    return out


def toggles(name: str) -> list[tuple[str, str]]:
    """(setting, the same name with that ON filter switched OFF) for every
    on/off knob that is on."""
    spec = sp.spec_for(name)
    if spec is None:
        return []
    kn = sp.FAMILIES[spec["family"]]["knobs"]
    out = []
    for j, (_l, setting, values) in enumerate(kn):
        if set(values) == {True, False} and spec["settings"][setting] is True:
            d = list(spec["digits"])
            d[j] = values.index(False)
            out.append((setting, sp.name_of(spec["family"], d)))
    return out


class Index:
    """Line lookups by (coin, tf, setting name, stop/target slot)."""

    def __init__(self, lines: dict, mon: np.ndarray):
        self.lines, self.mon = lines, mon
        names = lines["names"]
        self.at = {(int(c), int(t), names[int(v)], int(b)): i for i, (c, t, v, b) in
                   enumerate(zip(lines["coin"], lines["tf"], lines["var"], lines["bar"], strict=True))}

    def oos(self, coin: int, tf: int, name: str, bar: int):
        """(trades, wins, profit) of a FIXED setting over the four test months,
        or None when it made no trade there — a line that traded only on the
        choosing days is no evidence about the untouched ones, so it is never
        counted as $0 (code review, Oct 20, 2026)."""
        i = self.at.get((coin, tf, name, bar))
        if i is None:
            return None
        got = tuple(float(x) for x in self.mon[i, 1:].sum(axis=0))
        return got if got[0] > 0 else None


def untouched_cost(v) -> float | None:
    """The round trip (% of the position) an average trade of the four test
    months PAID — never the whole window's average, which is mostly older
    days at the coin's usual cost (code review, Oct 20, 2026: a 0.20% window
    average passed 2:1 while those trades paid 0.40%). None when the line has
    no trade there and no measured cost at all."""
    t = float(v[pr.F["t120"]])
    if t > 0:
        return float(v[pr.F["c120"]]) / t
    rt = float(v[pr.F["rt_paid"]])
    return None if math.isnan(rt) else rt


def checks(ix: Index, coin: int, tf: int, line: int, how: str, group: str,
           group_coins: list, trades: list, wf: list | None, notional: float = 100.0) -> list:
    """[(key, label, ok True/False/None, plain detail)] for one row. `trades`
    are the row's untouched-days trades from the check run:
    [entry ms, exit ms, side, why, profit, round trip % or None]. Every $ in a
    detail is on `notional` of position (the search's margin x leverage)."""
    L = ix.lines
    names = L["names"]
    name = names[int(L["var"][line])]
    bar = int(L["bar"][line])
    v = L["vals"][line]
    sl, tp = (float(x) * 100 for x in L["barriers"][f"barriers_{L['tfs'][tf]}"][bar])
    k = notional / 100.0
    rt = untouched_cost(v)
    out = []
    if rt is None:
        out.append(("pay2", "Pays at least 2:1 after fees", None,
                    "no round trip was measured for this row"))
    else:
        win, loss = after_fees(sl, tp, rt)
        out.append(("pay2", "Pays at least 2:1 after fees",
                    bool(win > 0 and win + pr.PAY_SLACK >= pr.PAY_RATIO * loss),
                    f"a win pays +${win * k:.2f}, a loss costs -${loss * k:.2f} on ${notional:.0f} after "
                    f"the {rt:.3f}% round trip its untouched-days trades paid"))
    pnls = [float(t[4]) for t in trades]
    n = len(pnls)
    wins = sum(1 for p in pnls if p > 0)
    prof = sum(pnls)
    out.append(("wins", f"Made money with at least {pr.MIN_WINS} wins", prof > 0 and wins >= pr.MIN_WINS,
                f"{wins} wins of {n} trades, {'+' if prof >= 0 else '-'}${abs(prof):.2f}"))
    lo = low_end(pnls)
    out.append(("range", "Still above zero at the low end of a 90% range",
                None if lo is None else lo > 0,
                "fewer than 2 trades" if lo is None else f"low end ${lo:+.3f} a trade "
                f"(average ${prof / n:+.3f})"))
    rand = [ix.oos(coin, tf, nm, bar) for nm in sp.variants(["rand"])]
    rand = [r for r in rand if r is not None]
    if rand:
        r_t = sum(r[0] for r in rand)
        r_ppt = sum(r[2] for r in rand) / r_t
        mine = prof / n if n else -math.inf
        out.append(("random", "Beat random entries with the same stop and target", mine > r_ppt,
                    f"${mine:+.3f} a trade against ${r_ppt:+.3f} for {len(rand)} random runs "
                    f"({int(r_t)} trades)"))
    else:
        out.append(("random", "Beat random entries with the same stop and target", None,
                    "no random run traded this coin, timeframe and stop/target on these days"))
    # costs x 1.5: half again of each trade's round trip as the engine charged
    # it (fees, the exit's fill and the entry's walk past the best price; a
    # book-priced entry's spread is inside its price and is not stressed),
    # and every stop filling 0.1% worse
    extra = sum(0.5 * (float(t[5]) if t[5] is not None else (rt or 0.0)) for t in trades) * k
    worse = STOP_WORSE * sum(1 for t in trades if t[3] == "SL") * k
    stressed = prof - extra - worse
    out.append(("stress", "Survives costs x1.5 and stops filling 0.1% worse", n > 0 and stressed > 0,
                f"${stressed:+.2f} after +${extra:.2f} of extra cost and -${worse:.2f} on stops"))
    nb = [x for x in (ix.oos(coin, tf, nm, bar) for nm in neighbours(name)) if x is not None]
    if nb:
        avg = sum(x[2] for x in nb) / len(nb)
        up = sum(1 for x in nb if x[2] > 0)
        out.append(("plateau", "Its neighbouring settings made money on average", avg > 0,
                    f"{up} of {len(nb)} settings one step away made money; ${avg:+.2f} each on average"))
    else:
        out.append(("plateau", "Its neighbouring settings made money on average", None,
                    "no setting one step away traded on these days"))
    if how == "group default" and len(group_coins) >= 2:
        halves = [0.0, 0.0]
        for j, ci in enumerate(sorted(group_coins)):
            x = ix.oos(ci, tf, name, bar)
            if x is not None:
                halves[j % 2] += x[2]
        out.append(("halves", "Its group's choice made money on both halves of the group",
                    halves[0] > 0 and halves[1] > 0,
                    f"${halves[0]:+.2f} and ${halves[1]:+.2f} on the two halves of {group}"))
    else:
        out.append(("halves", "Its group's choice made money on both halves of the group", None,
                    "this coin's own pick" if how != "group default" else "a one-coin group"))
    tg = toggles(name)
    mine = ix.oos(coin, tf, name, bar)
    seen = [(st, x) for st, other in tg if (x := ix.oos(coin, tf, other, bar)) is not None]
    if seen and mine is not None:
        bad = [st for st, x in seen if x[2] >= mine[2]]
        out.append(("filters", "Every on/off filter in it helps", not bad,
                    "; ".join(f"without {st}: ${x[2]:+.2f}" for st, x in seen)
                    + f" (with every filter: ${mine[2]:+.2f})"))
    else:
        out.append(("filters", "Every on/off filter in it helps", None,
                    "no on/off filter is on" if not tg else
                    "switching its filter off left nothing that traded on these days"))
    out.append(("late", "Still works one minute late", None,
                "not measured: the backtest engine cannot delay an entry"))
    if wf:
        w_p = sum(m[4] for m in wf if m)
        out.append(("walk", "Re-choosing before every month also made money (shown, not required)",
                    None, f"${w_p:+.2f} over the four months"))
    return out


# must be judged AND pass: a row that could not be compared with luck, or
# whose neighbours never traded, has not shown what these checks ask
# (code review, Oct 20, 2026: None used to count as a pass)
MUST = ("pay2", "wins", "range", "random", "stress", "plateau")
# may be "not applicable": an own pick has no group halves, and a setting with
# no on/off filter switched on has nothing to switch off
WHEN_APPLICABLE = ("halves", "filters")
REQUIRED = MUST + WHEN_APPLICABLE
STOP_WORSE = pr.STOP_WORSE


def passed(cks: list) -> bool:
    """Every MUST check judged and passed; every other required check passed
    or not applicable."""
    got = {k: ok for k, _l, ok, _d in cks}
    return (all(got.get(k) is True for k in MUST)
            and all(got.get(k) is not False for k in WHEN_APPLICABLE))
