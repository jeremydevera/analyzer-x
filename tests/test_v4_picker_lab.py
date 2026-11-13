"""The picker lab (Nov 12, 2026): twenty picker rules walked forward over Backtest v4's trades.

Operator: "Could you give me 20 picker rule then do a backtest to see which of them is most
profitable and highest winrate / Because low winrate does not mean its not profitable".

Every fixture puts its trades and the store's last candle on ONE timeline (CLAUDE.md, "A fill may
only see price the order was exposed to"), so the walk these tests check is the walk a real run
makes. The page's own JavaScript is run under node, on the payload it embeds."""
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone

import numpy as np
import pytest

from tradingagents import forecast_v4 as f4, stores, v4_picker_lab as lab, v4_picker_lab_page as page
from tradingagents import v4_store as v4

H = 3_600_000
DAY = 24 * H
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")


def ms(y, m, d, h=0):
    return int(datetime(y, m, d, h, tzinfo=timezone.utc).timestamp() * 1000)


END = ms(2026, 11, 5, 12)                     # the store's last candle: walk from Aug 01, 2026


def _pick(strategy, stop, target, trades):
    tr = [[en, ex, 1, "TP" if p > 0 else "SL", p] for en, ex, p in trades]
    return {"label": f"{strategy}(n=1) stop {stop * 100:g}%", "strategy": strategy, "params": {"n": 1},
            "stop": stop, "target": target, "older": {}, "newer": {}, "older_lost": False, "trades": tr}


def _line(coin, tf, picks):
    return {"coin": coin, "tf": tf, "fee": 0.00075, "slip": 0.001, "bars": 900, "combos": len(picks),
            "split_ms": ms(2026, 10, 1), "start_ms": ms(2026, 6, 1), "end_ms": END, "bar": 0.0, "picks": picks}


def daily(first, last, pnl_of, hours=(6, 12, 18)):
    """Trades opened at each of `hours` and closed an hour later, every day from `first` to `last`."""
    out, t, i = [], first, 0
    while t <= last:
        for h in hours:
            out.append((t + h * H, t + (h + 1) * H, pnl_of(i)))
        t += DAY
        i += 1
    return out


def _lines(flip_after=None):
    """Four strategies, three trades a day each:
    GOOD 1h wins $1 every time; BAD 1h loses $1 every time (never switched on: it is only the average
    a 1h rule set is held against); FLIP 4h wins $1.50 until Sep 20 and loses $1.50 after (a rule set
    that stops working); LATE 30m starts Sep 25 and wins $2 every time (a rule set that appears later).
    `flip_after` (ms) turns every trade CLOSING at or after it into a $3 loss - the future a pick
    made before it must never read."""
    def cut(trades):
        if flip_after is None:
            return trades
        return [(en, ex, -3.0 if ex >= flip_after else p) for en, ex, p in trades]

    good = _pick("ta_ma_pullback", 0.015, 0.03, cut(daily(ms(2026, 7, 1), ms(2026, 11, 4), lambda i: 1.0)))
    bad = _pick("ta_ma_pullback", 0.02, 0.04, cut(daily(ms(2026, 7, 1), ms(2026, 11, 4), lambda i: -1.0)))
    flip = _pick("ta_ma_pullback", 0.03, 0.06,
                 cut(daily(ms(2026, 7, 1), ms(2026, 11, 4), lambda i: 1.5 if i < 81 else -1.5)))
    late = _pick("bf_momentum", 0.01, None, cut(daily(ms(2026, 9, 25), ms(2026, 11, 4), lambda i: 2.0)))
    return {"GOOD|1h": _line("GOOD", "1h", [good]), "BAD|1h": _line("BAD", "1h", [bad]),
            "FLIP|4h": _line("FLIP", "4h", [flip]), "LATE|30m": _line("LATE", "30m", [late])}


def _store(tmp, mp, lines):
    folder = tmp / "acs"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "skilltaall.json").write_text(json.dumps({"lines": lines}), encoding="utf-8")
    (folder / "skill.json").write_text(json.dumps({"lines": {}}), encoding="utf-8")
    db = tmp / "v4" / "rows.db"
    mp.setattr(stores, "V4", stores.Store(**{**stores.V4.__dict__, "home": tmp / "v4", "rows_db": db}))
    v4.build(folder, target=db, log=lambda *_: None)
    return db


@pytest.fixture(scope="module")
def ran(tmp_path_factory):
    """One lab run over the tiny store, shared by the tests that read it."""
    mp = pytest.MonkeyPatch()
    tmp = tmp_path_factory.mktemp("lab")
    from tradingagents import profiles

    mp.setattr(profiles, "PICKER_PATH", tmp / "picker.json", raising=False)
    db = _store(tmp, mp, _lines())
    doc = lab.run(db, log=lambda *_: None)
    d = lab.load_store(db, log=lambda *_: None)
    M = lab.matrices(d, doc["store"]["data_end_s"], log=lambda *_: None)
    html, files = page.build(doc, _trades(tmp))
    yield {"doc": doc, "tmp": tmp, "db": db, "M": M, "P": lab.Prepared(M), "html": html, "files": files,
           "data": page.payload(doc, _trades(tmp))}
    mp.undo()


def _trades(tmp):
    import pickle

    with open(tmp / "v4" / "picker-lab" / "trades.pkl", "rb") as fh:
        return pickle.load(fh)


def _row(doc, key):
    return next(r for r in doc["rules"] if r["key"] == key)


# ------------------------------------------------------------------ the twenty rules
def test_there_are_twenty_picker_rules_each_with_its_own_stable_id():
    assert len(lab.RULES) == 20
    ids = [lab.rule_id(s) for s in lab.RULES]
    assert len(set(ids)) == 20 and len({s["key"] for s in lab.RULES}) == 20
    assert ids == [lab.rule_id(s) for s in lab.RULES], "an id is hashed from the rule, never a position"
    changed = {**lab.RULES[2], "gate": "(n30 >= 31) & (p30 > 0)"}
    assert lab.rule_id(changed) != ids[2], "another test is another rule: its id changes"
    for s in lab.RULES:
        assert s["promote"] and s["demote"] and s["name"], s["key"]


def test_the_first_rule_is_the_live_pickers_own_test_never_a_copy(ran, monkeypatch):
    from tradingagents import v4_picker as vp

    assert lab.RULES[0]["key"] == "live" and lab.RULES[0]["gate"] == "live3"
    asked = []

    def judge(rec):
        asked.append(rec)
        return (not rec["predicted"]["thin"]), ""

    monkeypatch.setattr(vp, "judge", judge)
    S = lab.Stats(ran["P"], ran["P"].D - 1)
    ok = S["live3"]
    assert asked, "the lab asks v4_picker.judge"
    assert {"trades", "luck", "predicted", "rank", "profit", "months"} <= set(asked[0])
    assert ok.sum() == sum(not r["predicted"]["thin"] for r in asked)


def test_the_live_rule_waits_for_three_whole_months_and_the_early_one_does_not(ran):
    P = ran["P"]
    sep10 = (ms(2026, 9, 10) // 1000 - P.start) // 86_400         # one whole month so far (August)
    nov02 = (ms(2026, 11, 2) // 1000 - P.start) // 86_400         # three whole months
    assert not lab.Stats(P, sep10)["live3"].any()
    assert lab.Stats(P, sep10)["live1"].any()
    assert lab.Stats(P, nov02)["live3"].any()
    live = _row(ran["doc"], "live")
    assert live["first_pick_s"] == ms(2026, 11, 1) // 1000, "its first pick is the first day with 3 whole months"


def test_a_low_win_rate_rule_takes_only_rule_sets_that_win_under_half_and_still_make_money():
    spec = next(s for s in lab.RULES if s["key"] == "low_wr")
    S = _stats(n30=[40, 40, 40, 10], wr30=[25.0, 75.0, 25.0, 20.0], p30=[25.0, 30.0, -5.0, 9.0])
    ok = np.asarray(S.eval(spec["gate"]), bool)
    assert ok.tolist() == [True, False, False, False]   # 25% and in profit; 75%; losing; too few trades


# ------------------------------------------------------------------ one day's pick
class _P:
    def __init__(self, n, tfi=None, filters=None):
        self.id_rank = np.arange(n)
        self.filters = np.zeros(n, np.int64) if filters is None else np.array(filters)
        self.tfi = np.full(n, -1) if tfi is None else np.array(tfi)


def _stats(tfi=None, **cols):
    """A day's figures written by hand: every name a rule reads, one value a rule set."""
    n = len(next(iter(cols.values())))
    S = lab.Stats.__new__(lab.Stats)
    S.P, S.g = _P(n, tfi), 0
    c = {k: np.array(v) for k, v in cols.items()}
    c.setdefault("nA", np.arange(100, 100 + n))         # every record different: no twins unless a test says so
    c.setdefault("wA", np.arange(50, 50 + n))
    c.setdefault("gwA", np.arange(1000, 1000 + n) * 10_000)
    c.setdefault("glA", np.zeros(n, np.int64))
    c.setdefault("pA", (c["gwA"] - c["glA"]) / 1e4)
    c["tfi"] = S.P.tfi
    S.c = c
    return S


MONEY30 = next(s for s in lab.RULES if s["key"] == "money30")


def test_empty_rooms_take_the_three_best_passing_rule_sets_best_first():
    S = _stats(n30=[40, 40, 40, 40, 5], p30=[5.0, 50.0, 20.0, 30.0, 99.0])
    assert lab.decide(MONEY30, S, [-1, -1, -1]) == [1, 3, 2]       # the 5-trade one never passes


def test_a_room_keeps_its_rule_set_while_it_passes_even_when_a_better_one_appears():
    S = _stats(n30=[40, 40, 40, 40], p30=[1.0, 50.0, 20.0, 30.0])
    assert lab.decide(MONEY30, S, [0, 2, 3]) == [0, 2, 3], "churn is the enemy: nothing is swapped for a better one"


def test_a_room_whose_rule_set_failed_takes_the_best_one_no_room_follows():
    S = _stats(n30=[40, 40, 40, 40], p30=[-1.0, 50.0, 20.0, 30.0])
    assert lab.decide(MONEY30, S, [0, 2, 3]) == [1, 2, 3]


def test_a_failed_room_never_takes_its_own_rule_set_back_the_same_day():
    quick = next(s for s in lab.RULES if s["key"] == "quick_exit")
    # rule set 0 still passes the gate's 30 days, but its last 7 lost: dropped, and not taken straight back
    S = _stats(n30=[40, 40], p30=[90.0, 10.0], p7=[-1.0, 2.0], n7=[9, 9])
    assert lab.decide(quick, S, [0, -1, -1])[0] != 0


def test_rule_sets_with_the_same_record_are_one_bet():
    S = _stats(n30=[40, 40, 40], p30=[50.0, 50.0, 20.0],
               nA=[200, 200, 150], wA=[120, 120, 80], gwA=[9_000_000, 9_000_000, 500], glA=[0, 0, 0])
    got = lab.decide(MONEY30, S, [-1, -1, -1])
    assert got == [0, 2, -1], "the twin of a rule set a room follows is never given to another room"


def test_a_room_sits_empty_when_nothing_passes():
    S = _stats(n30=[40, 40], p30=[-3.0, -1.0])
    assert lab.decide(MONEY30, S, [0, -1, -1]) == [-1, -1, -1]


def test_top_three_daily_holds_nothing_but_leaves_a_rule_set_in_its_room():
    top = next(s for s in lab.RULES if s["key"] == "top3_daily")
    S = _stats(n30=[40, 40, 40, 40], p30=[10.0, 50.0, 20.0, 30.0])
    assert lab.decide(top, S, [0, 3, -1]) == [1, 3, 2], "0 left the top three; 3 stays in the room it was in"


def test_spread_never_puts_two_rooms_on_one_timeframe():
    spread = next(s for s in lab.RULES if s["key"] == "spread")
    S = _stats(tfi=[2, 2, 0, 1, -1], n30=[40] * 5, p30=[90.0, 80.0, 30.0, 20.0, 99.0])
    assert lab.decide(spread, S, [-1, -1, -1]) == [0, 2, 3], "the second 1h set and the any-timeframe set are passed over"


# ------------------------------------------------------------------ the figures, and no looking ahead
def test_the_lab_adds_up_exactly_what_forecast_v4_counted(ran):
    M = ran["M"]
    out = ran["tmp"] / "forecast-check.json"
    f4.build(ran["db"], out=out, log=lambda *_: None)
    doc = json.loads(out.read_text(encoding="utf-8"))
    by = {r["id"]: r for r in doc["rules"]}
    assert len(M["rules"]) == len(by)
    day_month = np.searchsorted(np.array(M["ms"]), M["start"] + np.arange(M["D"]) * 86_400, side="right") - 1
    for i, r in enumerate(M["rules"]):
        f = by[r["id"]]
        assert int(M["o_n"][i].sum()) == f["trades"] and int(M["o_w"][i].sum()) == f["wins"]
        assert M["o_p"][i].sum() / 1e4 == pytest.approx(f["profit"], abs=1e-4)
        for mi, m in enumerate(f["months"]):
            assert M["o_p"][i][day_month == mi].sum() / 1e4 == pytest.approx(m["profit"], abs=1e-4)
        # every trade opened is known the first midnight after it closed, none before
        assert int(M["k_n"][i].sum()) == f["trades"]


def test_a_days_figures_read_only_trades_that_closed_before_that_day(ran):
    P = ran["P"]
    one_h = P.index_of(f4.rule_id(7, 50, 3, "any", 0.0, "1h", ""))
    g = (ms(2026, 9, 10) // 1000 - P.start) // 86_400
    S = lab.Stats(P, g)
    # GOOD 1h: three $1 wins a day; the rule set switches it on every day of the walk (BAD never). At
    # 12:00am Sep 10 the trades of Sep 03-09 are the last 7 days' closes; Sep 10's own are not known yet.
    assert int(S["n7"][one_h]) == 21 and S["p7"][one_h] == pytest.approx(21.0)
    assert int(S["n30"][one_h]) == 90 and S["wr30"][one_h] == 100.0
    assert int(S["nA"][one_h]) == 3 * g, "every trade opened since Aug 01 and closed before today"
    assert int(lab.Stats(P, g + 1)["nA"][one_h]) == 3 * (g + 1)
    assert S["edge30"][one_h] == pytest.approx(1.0), "$1 a trade against its kind's average of $0 (GOOD and BAD)"


def test_the_ratios_a_rule_reads(ran):
    P = ran["P"]
    four_h = P.index_of(f4.rule_id(30, 50, 3, "any", 0.0, "4h", ""))
    g = (ms(2026, 9, 30) // 1000 - P.start) // 86_400
    S = lab.Stats(P, g)
    # FLIP 4h flipped to losing on Sep 20: of its last 30 days' 90 closes, 30 (Sep 20-29) lost $1.50
    assert (int(S["n30"][four_h]), int(S["w30"][four_h])) == (90, 60)
    assert S["p30"][four_h] == pytest.approx(45.0) and S["pf30"][four_h] == pytest.approx(2.0)
    assert S["pay30"][four_h] == pytest.approx(1.0) and S["ppt30"][four_h] == pytest.approx(0.5)
    assert S["dd30"][four_h] == pytest.approx(45.0), "its worst dip: the ten losing days"
    assert S["calm30"][four_h] == pytest.approx(1.0)
    assert S["green30"][four_h] == pytest.approx(20 / 30) and int(S["traded30"][four_h]) == 30
    assert S["wkmin"][four_h] == pytest.approx(-31.5), "its worst week of the last four"
    with pytest.raises(KeyError):
        S["nonsense30"]


def test_a_pick_never_changes_when_the_future_does(tmp_path, monkeypatch, ran):
    """The same store, except every trade that closes on or after Oct 10 becomes a $3 loss: every pick
    made up to Oct 10 must be the very same."""
    cut = ms(2026, 10, 10)
    db = _store(tmp_path, monkeypatch, _lines(flip_after=cut))
    d = f4._load(db, lambda *_: None)
    M2 = lab.matrices(d, END // 1000, log=lambda *_: None)
    a = lab.simulate(ran["P"], lab.RULES, log=lambda *_: None)
    b = lab.simulate(lab.Prepared(M2), lab.RULES, log=lambda *_: None)
    ids_a, ids_b = [r["id"] for r in ran["M"]["rules"]], [r["id"] for r in M2["rules"]]
    upto = (cut // 1000 - ran["P"].start) // 86_400 - lab.LEAD_DAYS + 1      # picks for Sep 01 .. Oct 10
    differs_later = False
    for s in lab.RULES:
        fa, fb = a["follow"][s["key"]], b["follow"][s["key"]]
        name = lambda f, ids: [[ids[r] if r >= 0 else None for r in row] for row in f]   # noqa: E731
        assert name(fa[:upto], ids_a) == name(fb[:upto], ids_b), s["key"]
        differs_later |= name(fa[upto:], ids_a) != name(fb[upto:], ids_b)
    assert differs_later, "the changed future must change later picks, or this test proves nothing"


def test_what_the_rooms_make_is_every_trade_their_rule_sets_opened_that_day(ran):
    P, M = ran["P"], ran["M"]
    one_h = P.index_of(f4.rule_id(7, 50, 3, "any", 0.0, "1h", ""))
    days = [40, 41, 42]
    follow = np.array([[one_h, -1, -1], [one_h, -1, -1], [-1, -1, -1]], np.int32)
    t = lab.day_totals(P, days, follow)
    assert t["n"].tolist() == [3, 3, 0] and t["w"].tolist() == [3, 3, 0]
    assert (t["p"] / 1e4).tolist() == [3.0, 3.0, 0.0]
    assert M["o_n"][one_h, 40] == 3
    assert (t["random"] / 1e4).tolist() == [0.0, 0.0, 0.0], "random 1h strategies: GOOD and BAD average $0"


# ------------------------------------------------------------------ the run
def test_a_run_holds_twenty_rules_and_the_rooms_with_no_picker(ran):
    doc = ran["doc"]
    assert len(doc["rules"]) == 21 and sum(r["baseline"] for r in doc["rules"]) == 1
    assert [r["key"] for r in doc["rules"]][:20] == [s["key"] for s in lab.RULES]
    assert doc["days"] == 66 and doc["first_day_s"] == ms(2026, 9, 1) // 1000, "the first pick is 31 days in"
    assert doc["slots"] == 3 and doc["random"]["runs"] == lab.RANDOM_RUNS
    assert set(doc["random"]["shelves"]) == {"any", "in_profit"}
    for r in doc["rules"]:
        assert r["wins"] + r["losses"] == r["trades"]
        assert round(sum(m["profit"] for m in r["months"]), 4) == pytest.approx(r["profit"])
        assert sum(r["day_trades"]) == r["trades"] and sum(r["day_profit"]) == pytest.approx(r["profit"])
        assert len(r["day_profit"]) == len(r["day_random"]) == doc["days"]
        assert 0 <= r["empty_room_days"] <= doc["days"] * 3


def test_the_trades_read_back_are_the_ones_the_day_by_day_totals_counted(ran):
    doc, tp = ran["doc"], _trades(ran["tmp"])
    whys = v4.WHYS
    for r in doc["rules"]:
        t = tp["trades"][r["id"]]
        assert len(t["p4"]) == r["trades"] and int((t["p4"] > 0).sum()) == r["wins"]
        assert t["p4"].sum() / 1e4 == pytest.approx(r["profit"], abs=1e-4)
        assert (np.diff(t["at"]) >= 0).all(), "in closing order"
        for p, why, side in zip(t["p4"], t["why"], t["side"]):
            assert whys[why] == ("TP" if p > 0 else "SL") and side == 1    # the store's own exit kind and side
        assert set(np.unique(t["slot"]).tolist()) <= {0, 1, 2}


def test_a_room_only_ever_follows_a_rule_set_that_was_making_money_that_morning(ran):
    """money30, day by day: every rule set a room follows made money over the 30 days that closed
    before that day, and was picked with 30+ trades in them - checked against the figures themselves."""
    P = ran["P"]
    sim = lab.simulate(P, [MONEY30], log=lambda *_: None)
    f = sim["follow"]["money30"]
    held, picked = 0, 0
    for gi, g in enumerate(sim["days"]):
        S = lab.Stats(P, g)
        for s in range(lab.SLOTS):
            r = int(f[gi, s])
            if r < 0:
                continue
            held += 1
            assert S["p30"][r] > 0, (g, r)
            if gi == 0 or f[gi - 1, s] != r:
                picked += 1
                assert int(S["n30"][r]) >= 30, (g, r)
        mine = [int(x) for x in f[gi] if x >= 0]
        assert len({S.sig(r) for r in mine}) == len(mine), "no two rooms on one bet"
    assert held and picked >= 3
    r = _row(ran["doc"], "money30")
    assert r["trades"] and sum(z["room_days"] for z in r["rule_sets"]) == held


def test_every_rule_is_also_started_afresh_every_seven_days(ran):
    """A rule that holds what it picked on day one is judged on ONE pick: so it is started again, with
    empty rooms, every 7 days while two weeks are left, and each start is its own walk."""
    doc, P = ran["doc"], ran["P"]
    first = ms(2026, 9, 1) // 1000
    assert doc["starts"] == [first + 7 * 86_400 * k for k in range(8)], "Sep 01 then every 7 days to Oct 20"
    assert lab.start_days(P) == [(s - P.start) // 86_400 for s in doc["starts"]]
    for r in doc["rules"]:
        assert [b["start_s"] for b in r["starts"]] == doc["starts"]
        assert (r["starts"][0]["trades"], r["starts"][0]["profit"]) == (r["trades"], r["profit"]), \
            "the first start is the row itself"
        assert r["starts_green"] == sum(b["profit"] > 0 for b in r["starts"])
    # a start is the same rule begun that day with empty rooms: nothing before it, and its own picks after
    g0 = lab.start_days(P)[3]
    sim = lab.simulate(P, [MONEY30], log=lambda *_: None, starts=[g0])
    f = sim["started"]["money30"][g0]
    before = [gi for gi, g in enumerate(sim["days"]) if g < g0]
    assert (f[before] == -1).all() and (f[len(before)] >= 0).any()
    S = lab.Stats(P, g0)
    assert f[len(before)].tolist() == lab.decide(MONEY30, S, [-1, -1, -1]), "its first pick is a pick from empty rooms"
    t = lab.day_totals(P, sim["days"], f)
    mine = next(b for b in _row(doc, "money30")["starts"] if b["start_s"] == P.start + g0 * 86_400)
    assert (mine["trades"], mine["profit"]) == (int(t["n"].sum()), round(float(t["p"].sum() / 1e4), 4))
    assert mine["days"] == P.Dp - g0


def test_a_store_that_ends_on_the_stroke_of_midnight_has_no_empty_last_day(ran):
    M = ran["M"]
    assert ran["P"].Dp == ran["P"].D == 97, "the fixture's last candle is at noon: its last day is a real day"
    at_midnight = lab.Prepared({**M, "end_s": M["start"] + 96 * 86_400})
    assert at_midnight.Dp == 96, "Nov 05 12:00am sharp: Nov 05 has no time in it, so Nov 04 is the last pick day"
    assert lab.simulate(at_midnight, [MONEY30], log=lambda *_: None)["days"][-1] == 95


def test_the_stricter_luck_shelf_holds_only_rule_sets_that_were_making_money(ran):
    P = ran["P"]
    sim = lab.simulate(P, lab.RULES[:1], log=lambda *_: None)
    for gi, g in enumerate(sim["days"][::9]):
        S = lab.Stats(P, g)
        anyone, good = sim["shelf"]["any"][gi * 9], sim["shelf"]["in_profit"][gi * 9]
        assert set(good.tolist()) <= set(anyone.tolist())
        assert (S["n30"][anyone] >= 30).all() and (S["p30"][good] > 0).all()
    a = lab.random_pickers(P, sim, runs=20, shelf="any")
    b = lab.random_pickers(P, sim, runs=20, shelf="in_profit")
    assert a["p"].tolist() != b["p"].tolist(), "two shelves, two sets of blind pickers"


def test_the_random_pickers_are_the_same_every_run(ran):
    P = ran["P"]
    sim = lab.simulate(P, lab.RULES[:1], log=lambda *_: None)
    a, b = lab.random_pickers(P, sim, runs=20), lab.random_pickers(P, sim, runs=20)
    assert a["p"].tolist() == b["p"].tolist() and a["n"].tolist() == b["n"].tolist()


def test_a_run_never_touches_the_live_pickers_file(ran):
    assert not (ran["tmp"] / "picker.json").exists()


def test_the_store_is_read_from_a_private_copy(ran):
    cache = ran["tmp"] / "v4" / "picker-lab" / "cache"
    assert (cache / "rows-copy.db").exists(), "the daily chain swaps the live file: the lab never holds it open"
    assert len(list(cache.glob("rows-copy*.db"))) == 1, "one copy, replaced by the next run"


def test_the_live_store_is_never_copied_while_the_daily_refresh_is_about_to_swap_it(ran, monkeypatch):
    """A copy still reading the old file when the refresh swaps the new one in makes that swap fail on
    Windows, and the refresh then builds the whole store again - NEVER HAPPENED YET, held shut here."""
    from tradingagents import v4_daily

    said = []
    for phase in ("collect", "build", "unreadable"):
        monkeypatch.setattr(v4_daily, "status", lambda phase=phase: {"phase": phase, "why": "building"})
        assert phase in lab.refresh_in_the_way()
        with pytest.raises(RuntimeError, match="not copying the store"):
            lab.load_store(log=said.append, fresh=True)
    assert not said, "nothing was copied"
    for phase in ("idle", "done", "given_up", "running", "lists"):
        monkeypatch.setattr(v4_daily, "status", lambda phase=phase: {"phase": phase})
        assert lab.refresh_in_the_way() is None, phase
    assert len(lab.load_store(log=said.append, fresh=True)["sid"]) and said, "copied once the list has landed"


# ------------------------------------------------------------------ the page
def _js(html: str, data: dict, expr: str):
    logic = re.search(r"/\*LOGIC\*/(.*?)/\*END LOGIC\*/", html, re.S).group(1)
    prog = (f"const D={json.dumps(data)};\n{logic}\nconst T={{}};for(const [id,c] of Object.entries(D.T))"
            f"T[id]=decode(c);\nconsole.log(JSON.stringify({expr}));")
    out = subprocess.run([NODE], input=prog, capture_output=True, text=True, timeout=120, encoding="utf-8")
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout)


def test_every_row_carries_every_field_and_all_its_trades(ran):
    data = ran["data"]
    assert [r["id"] for r in data["rows"]] == [r["id"] for r in ran["doc"]["rules"]]
    for r, src in zip(data["rows"], ran["doc"]["rules"]):
        assert {"id", "name", "promote", "demote", "swaps", "empty", "sets", "rd", "br", "sg", "st"} <= set(r)
        assert len(r["st"]) == len(data["starts"]) and r["sg"] == sum(b[4] > 0 for b in r["st"])
        cols = data["T"][r["id"]]
        assert set(cols) == set(page.FIELDS) and len({len(v) for v in cols.values()}) == 1
        assert len(cols["p"]) == src["trades"]
    assert data["base"] == 5.0 and data["lev"] == 20
    assert page.unpack(re.search(r'const Z="([^"]*)"', ran["html"]).group(1))["rows"] == data["rows"]


@needs_node
def test_the_page_adds_every_row_up_to_the_runs_own_figures(ran):
    data = ran["data"]
    got = _js(ran["html"], data, "D.rows.map(r=>{const m=measure(T[r.id],D.S,null,1);delete m.idx;return m})")
    for m, r in zip(got, ran["doc"]["rules"]):
        assert (m["trades"], m["wins"], m["losses"]) == (r["trades"], r["wins"], r["losses"]), r["key"]
        if not r["trades"]:
            assert m["profit"] is None
            continue
        assert m["profit"] == pytest.approx(r["profit"], abs=1e-6)
        assert m["worst"] == pytest.approx(r["worst_run"], abs=1e-6) and m["worstN"] == r["worst_run_n"]
        assert m["dip"] == pytest.approx(r["worst_dip"], abs=1e-6)
        assert m["green"] == r["green_months"]
        assert {k: pytest.approx(v, abs=1e-6) for k, v in m["months"].items()} == \
            {x["key"]: x["profit"] for x in r["months"]}
        if r["break_even"] is not None:
            assert m["be"] == pytest.approx(r["break_even"], abs=0.01)


@needs_node
def test_the_margin_box_rescales_every_dollar_and_the_window_re_adds_each_row(ran):
    data = ran["data"]
    rid = _row(ran["doc"], "money30")["id"]
    full = _js(ran["html"], data, f"(()=>{{const m=measure(T['{rid}'],D.S,null,1);delete m.idx;return m}})()")
    twice = _js(ran["html"], data, f"(()=>{{const m=measure(T['{rid}'],D.S,null,2);delete m.idx;return m}})()")
    assert twice["profit"] == pytest.approx(2 * full["profit"]) and twice["trades"] == full["trades"]
    assert twice["dip"] == pytest.approx(2 * full["dip"]) and twice["win"] == full["win"]
    w = _js(ran["html"], data, "windowOf(D,10)")
    assert w["days"] == 10 and w["from"] == data["day0"] + (data["days"] - 10) * 86_400
    last10 = _js(ran["html"], data, f"(()=>{{const m=measure(T['{rid}'],D.S,{w['from']},1);delete m.idx;return m}})()")
    t = _trades(ran["tmp"])["trades"][rid]
    mine = t["en"] >= w["from"]
    assert last10["trades"] == int(mine.sum()) and last10["profit"] == pytest.approx(t["p4"][mine].sum() / 1e4)
    assert len(last10["months"]) < len(full["months"]) or len(full["months"]) == 1
    assert _js(ran["html"], data, "windowOf(D,9999)")["clamped"] is True
    assert _js(ran["html"], data, "monthList(D)") == ["2026-09", "2026-10", "2026-11"]


@needs_node
def test_max_tp_and_max_sl_are_inclusive_ceilings_on_every_trades_own_target_and_stop(ran):
    data = ran["data"]
    rid = _row(ran["doc"], "no_picker")["id"]
    m = _js(ran["html"], data, f"(()=>{{const m=measure(T['{rid}'],D.S,null,1);delete m.idx;return m}})()")
    assert m["stop"] is not None and m["stopLeast"] <= m["stop"]
    f = lambda box: _js(ran["html"], data,                                         # noqa: E731
                        f"fails(measure(T['{rid}'],D.S,null,1),{json.dumps(box)})")
    assert "max SL %" not in f({"sl": m["stop"]}), "a stop exactly at the box passes"
    assert "max SL %" in f({"sl": m["stop"] - 0.01})
    if m["target"] is None:
        assert "max TP %" in f({"tp": 99}), "a row with a trade that has no target passes no max TP %"
    else:
        assert "max TP %" not in f({"tp": m["target"]}) and "max TP %" in f({"tp": m["target"] - 0.01})


def test_the_kit_is_on_the_page(ran):
    html = ran["html"]
    cols = re.search(r"const COLS=\[(.*?)\];\n", html, re.S).group(1)
    assert cols.startswith('["id","ID",1]'), "a stable id first (kit H)"
    for label in ("PROFIT (total $)", "TP %", "SL %", "Leverage", '"W"', '"L"', "Worst losing run",
                  "Worst dip", "Trades a day", "Months green", "Break-even win %", "W / L a day",
                  "Start days that made money", "Beat random pickers"):
        assert label in cols, label
    for box in ("f-base", "f-wr", "f-pr", "f-gm", "f-dd", "f-tp", "f-sl", "f-days", "f-id", "clear"):
        assert f'id="{box}"' in html, box
    assert "TOTAL PROFIT" in html and "picker rules tested" in html
    assert "100% typical cost" in html, "the cost every trade paid is said beside the results"
    assert "the picker is not started again" in html, "a window is a re-add, said on the page"
    title = re.search(r"<title>(.*?)</title>", html).group(1)
    assert 2 <= len(title.split()) <= 4
    for tag in ("<!doctype", "<html", "<head>", "<body"):
        assert tag not in html.lower(), "the artifact service adds the document around the page"
    assert ".toLocaleString()" not in html and "toLocaleDateString" not in html and "toISOString" not in html


@needs_node
def test_the_pages_date_format_is_the_projects(ran):
    import datetime as dt

    from tradingagents.positions_view import fmt_when

    js = re.search(r"(const MON=.*?\nfunction fmtWhen\(ms\)\{.*?\n.*?\})\n", ran["html"], re.S).group(1)
    moments = [dt.datetime(2026, 8, 3, 20, 3), dt.datetime(2026, 9, 1, 0, 0), dt.datetime(2026, 9, 12, 12, 0)]
    stamps = [int(x.timestamp() * 1000) for x in moments]
    out = subprocess.run([NODE, "-e", js + f"\nfor (const m of {stamps}) console.log(fmtWhen(m));"],
                         capture_output=True, text=True, timeout=60).stdout.split("\n")
    assert out[:3] == [fmt_when(x / 1000) for x in stamps]


def test_the_page_is_refused_when_a_rows_trades_are_not_the_ones_measured(ran):
    doc, tp = ran["doc"], _trades(ran["tmp"])
    rid = next(r["id"] for r in doc["rules"] if r["trades"])
    tp["trades"][rid]["p4"] = tp["trades"][rid]["p4"].copy()
    tp["trades"][rid]["p4"][0] += 50_000
    with pytest.raises(ValueError, match="not the ones the run measured"):
        page.build(doc, tp)
    with pytest.raises(ValueError, match="two different runs"):
        page.build({**doc, "built_s": doc["built_s"] + 1}, _trades(ran["tmp"]))


def test_a_payload_too_big_for_the_page_goes_into_files_beside_it_never_trimmed(ran, monkeypatch):
    monkeypatch.setattr(page, "INLINE_MAX", 100)
    monkeypatch.setattr(page, "CHUNK", 5_000)
    html, files = page.build(ran["doc"], _trades(ran["tmp"]))
    assert files and 'const Z="";' in html and f"const ZF={json.dumps(sorted(files))};" in html
    whole = "".join(files[k] for k in sorted(files, key=lambda n: int(n.split("-")[1].split(".")[0])))
    assert page.unpack(whole)["rows"] == ran["data"]["rows"]
    assert all(not name.startswith("_") for name in files)


# ------------------------------------------------------------------ the two things Forecast v4 lends
def test_the_walk_hands_a_visitor_the_very_trades_each_rule_set_counted(ran):
    d = f4._load(ran["db"], lambda *_: None)
    seen = []

    def visit(rule, m, sub, km):
        rows = sub["row"][m]
        assert (m & ~km).sum() == 0, "a rule set's trades are trades of its own kind"
        seen.append((rule["id"], int(m.sum()), float(d["pnl"][rows].sum()), rule["trades"], rule["profit"]))

    with_visitor = f4._walk(d, END // 1000, lambda *_: None, visit=visit)
    plain = f4._walk(d, END // 1000, lambda *_: None)
    # the day-by-day figures (the rule sets' calendars, Nov 13, 2026) are arrays: compared as arrays
    dv, dp = with_visitor.pop("days"), plain.pop("days")
    assert set(dv) == set(dp) and all(np.array_equal(dv[k], dp[k]) for k in dp), \
        "a visitor changes no day of any rule set"
    assert json.dumps(with_visitor, sort_keys=True) == json.dumps(plain, sort_keys=True), \
        "a visitor changes nothing the walk writes"
    assert [s[0] for s in seen] == [r["id"] for r in plain["rules"]], "once for every rule set, in order"
    for _id, n, profit, trades, said in seen:
        assert n == trades and profit == pytest.approx(said, abs=1e-4)


def test_the_luck_bar_is_one_function_for_numbers_and_for_whole_columns():
    import math

    cases = [(5, 5, 10.0, 1.0), (10, 5, 10.0, 1.0), (10, 9, 10.0, 1.0), (40, 27, 10.0, 1.0),
             (40, 26, 10.0, 1.0), (40, 30, 1.0, 1.0), (40, 30, 1.0, 2.0), (100, 59, 3.0, 1.0), (100, 58, 3.0, 1.0)]
    old = [(d_ < 10 or b <= d_ / 2 + f4.LUCK_Z * math.sqrt(d_) / 2 or p <= r) for d_, b, p, r in cases]
    assert [bool(f4.could_be_luck(*c)) for c in cases] == old
    cols = [np.array(x) for x in zip(*cases)]
    assert f4.could_be_luck(*cols).tolist() == old
    assert old.count(True) and old.count(False), "both answers are exercised"


def test_the_store_reader_hands_back_side_exit_kind_and_exit_minute_only_when_asked(ran):
    plain = f4._load(ran["db"], lambda *_: None)
    more = f4._load(ran["db"], lambda *_: None, extra=True)
    assert {"why", "side", "at"} <= set(more) and not {"why", "side", "at"} & set(plain)
    for k in ("sid", "ex", "en", "pnl"):
        assert np.array_equal(plain[k], more[k]), "the same trades in the same order either way"
    assert len(more["why"]) == len(more["side"]) == len(more["at"]) == len(more["sid"])
    assert all(v4.WHYS[w] == ("TP" if p > 0 else "SL") for w, p in zip(more["why"], more["pnl"]))
    assert (more["side"] == 1).all()
    assert np.array_equal(more["at"], more["ex"]), "no minute on file: the exit candle's own time"


# ------------------------------------------------------------------ two nights, side by side (RCA-2026-11-12-B)
def test_every_run_is_kept_by_the_day_of_its_store_and_the_page_shows_the_night_before(ran):
    """The store is replaced every night, so a run cannot be made again: each one is kept, and the page
    prints the night before beside tonight - on Nov 12, 2026 the same 20 rules made money in 12 cases
    on one night's store and in 1 on the next."""
    doc = ran["doc"]
    kept = lab.kept_path(doc["store"]["data_end_s"])
    assert kept.name == "lab-2026-11-05.json"
    assert json.loads(kept.read_text(encoding="utf-8"))["built_s"] == doc["built_s"]
    assert lab.previous(doc) is None and ran["data"]["prev"] is None, "no earlier night kept yet"
    earlier = json.loads(kept.read_text(encoding="utf-8"))
    earlier["store"]["data_end_s"] -= 86_400
    for r in earlier["rules"]:
        r["profit"] = round(r["profit"] - 100, 4)
    older = lab.kept_path(earlier["store"]["data_end_s"])
    older.write_text(json.dumps(earlier), encoding="utf-8")
    try:
        prev = lab.previous(doc)
        assert prev["store"]["data_end_s"] == doc["store"]["data_end_s"] - 86_400
        assert lab.previous(earlier) is None, "never a later night, never itself"
        data = page.payload(doc, _trades(ran["tmp"]), prev)
        r0 = next(r for r in doc["rules"] if r["trades"])
        assert data["prev"]["rows"][r0["id"]] == [round(r0["profit"] - 100, 4), r0["trades"], r0["win_rate"],
                                                 r0["starts_green"], len(r0["starts"])]
        assert data["prev"]["end"] == doc["store"]["data_end_s"] - 86_400
    finally:
        older.unlink()


def test_the_page_says_first_how_the_store_priced_each_coins_gap(ran):
    html = ran["html"]
    assert ran["doc"]["store"]["gaps"] is None, "the fixture's store says nothing about its gaps"
    assert 'id="warn"' in html and html.index('id="warn"') < html.index('id="prov"'), "read first, above everything"
    assert "ONE reading of its buy-sell gap" in html and "their usual gap" in html
    assert "PROFIT the night before" in html and "Win % the night before" in html
    assert "Trust a rule only where both nights agree" in html
