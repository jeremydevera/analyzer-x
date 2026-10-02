"""Forecast v2 (operator, Oct 01, 2026: "okay run that prompt and create
Forecast v2, use harddev skill and make sure to document this";
docs/FORECAST-V2.md).

ONE TIMELINE: every trade, open position, switch-on and rebuilt backtest below
sits on the same clock, NOW, the way a running site sees them — a test whose
candles and positions sat on different clocks once passed with a bug in it
(CLAUDE.md, "a fill may only see price the order was exposed to").
"""
import datetime as dt
import importlib.util
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from tradingagents import (
    auto_trader as at,
    forecast_rules as fr,
    forecast_v2 as f2,
    forecast_v2_api as f2a,
    forecast_v2_merge as fm,
    profiles,
    rolling30 as r30,
    room_stats as rs,
)

ROOT = Path(__file__).resolve().parents[1]
NY = ZoneInfo("America/New_York")
# Thursday Oct 01, 2026 2:00pm New York — every timestamp below is relative to it
NOW = dt.datetime(2026, 10, 1, 14, 0, tzinfo=NY).timestamp()
HOUR = 3600.0
ROOM = "4FC03172"

spec = importlib.util.spec_from_file_location("forecast_shard", ROOT / ".github/scripts/forecast_shard.py")
fs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fs)


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    """Every room's files, rolling30's cache and Forecast v2's own files under
    tmp_path; every cache cleared."""
    monkeypatch.setattr(at, "STATE_DIR", tmp_path)
    monkeypatch.setattr(at, "LEDGER_PATH", tmp_path / "auto_trade_ledger.jsonl")
    monkeypatch.setattr(at, "STATE_PATH", tmp_path / "auto_trade_state.json")
    monkeypatch.setattr(at, "SETTINGS_PATH", tmp_path / "auto_trade.json")
    from tradingagents import local_history as lh

    monkeypatch.setattr(lh, "_deploy_log", lambda: Path(profiles.path(tmp_path / "deployments.jsonl",
                                                                       profiles.current())))
    rs._LEDGERS.clear()
    rs._STATES.clear()
    f2._ROLL.clear()
    f2._ROLL_DIR["stamp"] = None
    f2._READS.clear()
    f2.spec_of.cache_clear()
    f2a._FILES.clear()
    monkeypatch.setitem(f2a._LIVE, "value", None)
    monkeypatch.setitem(f2a._LIVE, "error", "")
    yield tmp_path
    rs._LEDGERS.clear()
    rs._STATES.clear()
    f2._ROLL.clear()


def _file(name, room=ROOM):
    return Path(profiles.path(at.STATE_DIR / name, room))


def trades(pnls, *, room=ROOM, symbol="KKRSTOCK_USDT", key="stoch14_15m_sl1tp15",
           start=NOW - 20 * HOUR, step=600.0, held=300.0):
    """An enter and an exit row per pnl, in time order, $5 at 20x."""
    rows = []
    for i, p in enumerate(pnls):
        t = start + i * step
        tid = f"T{room[:2]}{symbol[:3]}{i:04d}"
        rows.append({"ts": t, "symbol": symbol, "action": "enter", "trade_id": tid,
                     "strategy": key, "opened_at": t, "margin": 5.0, "leverage": 20,
                     "dry_run": True, "entry": 100.0})
        exit_price = 100.0 * (1 + (p / 100.0 + 0.002))
        rows.append({"ts": t + held, "symbol": symbol, "action": "exit", "trade_id": tid,
                     "strategy": key, "opened_at": t, "entry": 100.0, "exit": exit_price,
                     "side": "LONG", "pnl_est": round(p, 2), "dry_run": True,
                     "why": "TP" if p > 0 else "SL", "held_s": held})
    return rows


def write(rows, room=ROOM, mode="a"):
    with _file("auto_trade_ledger.jsonl", room).open(mode, encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def settings(room=ROOM, coins=(("stoch14_15m_sl1tp15", "KKRSTOCK_USDT"),), slots=None):
    st = {"strategy_coins": {}, "watcher_slots": slots or {}}
    for k, c in coins:
        st["strategy_coins"].setdefault(k, []).append(c)
    _file("auto_trade.json", room).write_text(json.dumps(st), encoding="utf-8")


def deployed(slot, on_s, room=ROOM, off_s=None):
    with _file("deployments.jsonl", room).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"changed_at": on_s, "strategy_key": slot, "action": "deployed"}) + "\n")
        if off_s is not None:
            fh.write(json.dumps({"changed_at": off_s, "strategy_key": slot, "action": "disarmed"}) + "\n")


def rebuilt(slot, bt, end_s):
    """rolling30's cache for one row: [entry_ms, exit_ms, pnl]."""
    r30.home().mkdir(parents=True, exist_ok=True)
    r30._cache_path(slot).write_text(json.dumps({
        "slot": slot, "wm": int(end_s * 1000), "end_ms": int(end_s * 1000),
        "trades": [[int(a * 1000), int(b * 1000), p] for a, b, p in bt]}), encoding="utf-8")


def room(pid=ROOM):
    return f2.room_data(pid, NOW)


# ------------------------------------------------------------ definitions
def test_a_key_reads_back_its_timeframe_and_barriers():
    assert [f2.pct_decode(c) for c in ("03", "15", "2", "125", "12p5")] == [0.3, 1.5, 2.0, 1.25, 12.5]
    sp = f2.spec_of("stoch14_15m_sl1tp15")
    assert (sp["tf"], sp["signal"], sp["sl"], sp["tp"]) == ("15m", "stoch14", 1.0, 1.5)
    assert f2.family("ml_ALUMINUM_15m_3") == "ml (learned models)"


def test_break_even_is_stop_plus_cost_over_target_plus_stop():
    # CLAUDE.md rule 11: 1.2/1.2 with a 0.31% cost needs 62.9% — never 50%
    assert f2.break_even(1.2, 1.2, 0.31) == pytest.approx(100 * 1.51 / 2.4)


def test_a_streak_is_the_run_at_the_end_and_zero_is_a_loss():
    s = f2.streak_of([{"pnl": p, "ts": i, "key": "k"} for i, p in enumerate([1, -1, 1, 1, 1])])
    assert (s["kind"], s["length"], s["profit"]) == ("win", 3, 3)
    s = f2.streak_of([{"pnl": p, "ts": i, "key": "k"} for i, p in enumerate([1, 0.0, -2])])
    assert (s["kind"], s["length"]) == ("loss", 2), "$0.00 is not a win"


def test_practice_streaks_are_per_room_and_coin_longest_first():
    settings()
    write(trades([1.0] * 9))
    write(trades([-1.0] * 4, symbol="DHRSTOCK_USDT", start=NOW - 10 * HOUR))
    got = f2.practice_streaks([room()])
    assert [(s["coin"], s["kind"], s["length"]) for s in got] == [("KKRSTOCK", "win", 9),
                                                                   ("DHRSTOCK", "loss", 4)]
    assert got[0]["switched_on"] and not got[1]["switched_on"]
    assert got[0]["tf"] == "15m" and got[0]["tp"] == 1.5 and got[0]["sl"] == 1.0


def test_coins_to_avoid_need_five_losing_trades_and_carry_the_backtest():
    settings()
    write(trades([-1.0] * 4 + [0.5], symbol="IGV_USDT"))                 # 5 trades, -3.50
    write(trades([-1.0] * 4, symbol="USTOCK_USDT", start=NOW - 9 * HOUR))  # only 4: not judged
    rebuilt("stoch14_15m_sl1tp15|IGV_USDT", [(NOW - 50 * HOUR, NOW - 49 * HOUR, 0.5)] * 3, NOW - 30 * HOUR)
    a = f2.coins_to_avoid([room()])
    assert [c["coin"] for c in a["coins"]] == ["IGV"] and a["examined"] == 2
    c = a["coins"][0]
    assert (c["trades"], c["wins"], c["profit"], c["worst_run"], c["worst_run_trades"]) == (5, 1, -3.5, -4.0, 4)
    assert c["backtest"]["winrate"] == 100.0 and c["backtest"]["trades"] == 3


def test_where_the_money_goes_splits_by_hour_held_and_kind():
    settings()
    nine_thirty = dt.datetime(2026, 10, 1, 9, 30, tzinfo=NY).timestamp()
    write(trades([-1.0, -1.0], start=nine_thirty, held=600))                  # 9am to noon, fast stops
    write(trades([1.0], symbol="BTC_USDT", start=NOW - 2 * HOUR, held=7200))  # noon to 4pm, crypto
    m = f2.money([room()])
    hours = {g["group"]: g for g in m["by_hour"]}
    assert hours["9am to noon"]["trades"] == 2 and hours["noon to 4pm"]["trades"] == 1
    stops = {g["group"]: g for g in m["stop_outs"]}
    assert stops["within 15 minutes"]["trades"] == 2 and stops["after an hour"]["trades"] == 0
    kinds = {g["group"]: g["trades"] for g in m["by_kind"]}
    assert kinds == {"stocks": 2, "crypto": 1}
    assert all(g["thin"] for g in m["by_tf"]), "3 trades is too few to mean anything"
    z = m["sizes"]
    assert (z["avg_win"], z["avg_loss"], z["break_even"]) == (1.0, -1.0, 50.0)
    # the costs: price move x size less what was booked, $100 of coin, 0.2% charged
    assert m["costs"]["costs"] == pytest.approx(0.6, abs=0.01)
    assert m["costs"]["without_costs"] == pytest.approx(m["costs"]["profit"] + 0.6, abs=0.01)


def test_one_coin_in_many_rooms_is_flagged():
    for pid in ("main", "55D32617", ROOM):
        _file("auto_trade_state.json", pid).write_text(json.dumps(
            {"VUG_USDT#paper#k": {"position": {"side": 1, "entry": 100, "sl": 99, "margin": 5, "dry": True}}}),
            encoding="utf-8")
    ov = f2.overlap([f2.room_data(pid, NOW) for pid in ("main", "55D32617", ROOM)])
    assert ov[0]["coin"] == "VUG" and ov[0]["count"] == 3 and ov[0]["flag"]


# ------------------------------------------------------- the reality check
def test_the_reality_check_compares_the_same_rows_over_the_same_hours():
    """Switched on 10 hours ago; the rebuilt backtest ends 2 hours ago. Only
    trades that OPENED inside that stretch count — on both sides."""
    slot = "stoch14_15m_sl1tp15|KKRSTOCK_USDT"
    on, end = NOW - 10 * HOUR, NOW - 2 * HOUR
    settings(slots={slot: {"id": "ABCDEFGH", "on_at": on}})
    deployed(slot, on)
    rebuilt(slot, [(on - 5 * HOUR, on - 4 * HOUR, 9.0),          # before the switch-on: never
                   (on + 1 * HOUR, on + 1.5 * HOUR, 1.0),
                   (on + 3 * HOUR, on + 3.5 * HOUR, 1.0),
                   (on + 5 * HOUR, on + 5.5 * HOUR, -1.0)], end)
    write(trades([0.5, -1.0], start=on + 1 * HOUR, step=2 * HOUR))     # practice took 2 of 3
    write(trades([5.0], start=end + 0.5 * HOUR))                      # after the backtest: never
    r = f2.reality([room()])["rooms"][0]
    assert (r["bt_trades"], r["bt_profit"], r["pr_trades"], r["pr_profit"]) == (3, 1.0, 2, -0.5)
    assert r["took"] == pytest.approx(2 / 3, abs=1e-4) and r["gap"] == pytest.approx(1 / 3 + 0.25, abs=1e-4)
    # the correction gives back practice exactly on the window it was measured on
    assert f2.corrected(r["bt_profit"], r["bt_trades"], r) == pytest.approx(-0.5, abs=0.01)


def test_the_backtest_side_keeps_the_runners_trades_per_coin():
    """Found in the bug hunt: uncapped, 2,592 rows "made" 7,470 trades in
    fourteen hours against practice's 138."""
    on, end = NOW - 10 * HOUR, NOW - 1 * HOUR
    slots = {}
    for i in range(6):                       # six strategies on ONE coin, same hour
        slot = f"stoch14_15m_sl1tp{i + 2}|KKRSTOCK_USDT"
        slots[slot] = {"id": f"ID{i}", "on_at": on}
        deployed(slot, on)
        rebuilt(slot, [(on + HOUR, on + 2 * HOUR, 1.0)], end)
    settings(slots=slots)
    r = f2.reality([room()])["rooms"][0]
    assert r["bt_uncapped"] == 6 and r["bt_trades"] == 4 and r["cap"] == 4


# ------------------------------------------------------------- the rules
def test_the_grid_ids_and_short_form():
    g = fr.base_grid()
    assert len(g) == 576 and len({fr.rule_id(c) for c in g}) == 576
    assert len(fr.with_options(g[:2])) == 2 * len(fr.OPTIONS)
    c = fr.cfg_of(30, 90, 40, ">", 2.0)
    assert fr.decode(fr.encode(c)) == c and fr.rule_id(fr.decode(fr.encode(c))) == fr.rule_id(c)
    assert fr.words(c) == "90% wins, 40+ trades in 30 days, TP wider than SL, stop 2% or tighter"
    rooms = {"main": c, ROOM: fr.cfg_of(30, 70, 50, ">", 2.0)}
    assert fr.decode_rooms(fr.encode_rooms(rooms)) == rooms


def test_tp_rules_and_what_a_room_can_run_today():
    tp, sl = np.array([1.5, 2.0, 3.0, 0.5]), np.array([1.0, 1.0, 1.0, 1.0])
    assert list(fr.tp_ok(tp, sl, ">")) == [True, True, True, False]
    assert list(fr.tp_ok(tp, sl, "1.5x")) == [True, True, True, False]
    assert list(fr.tp_ok(tp, sl, "2x")) == [False, True, True, False]
    assert fr.deployable(fr.cfg_of(30, 90, 40, ">", 2.0))[0]
    ok, why = fr.deployable(fr.cfg_of(30, 90, 40, "2x", 2.0))
    assert not ok and "TP at least 2x SL" in why
    assert not fr.deployable({**fr.cfg_of(30, 90, 40, ">", 2.0), "skip_jp": True})[0]


def test_the_row_options():
    meta = [{"coin": "MITSUBISHISTOCK", "tf": "15m", "signal": "stoch14", "tp": 1.5, "sl": 1.0, "cost_of_tp": 8.0},
            {"coin": "BTC", "tf": "1h", "signal": "keltner", "tp": 3.0, "sl": 1.0, "cost_of_tp": 12.0},
            {"coin": "GPNSTOCK", "tf": "15m", "signal": "ibs", "tp": 2.0, "sl": 0.3, "cost_of_tp": 3.0}]
    base = fr.cfg_of(30, 90, 20, ">", 2.0)
    m = lambda **o: list(fr.row_mask(meta, {**base, **o}, {"avoid": ["GPNSTOCK"], "families": ["keltner"],  # noqa: E731
                                                          "move": {"GPNSTOCK": 0.5}}))
    assert m() == [True, True, True]
    assert m(skip_jp=True) == [False, True, True]
    assert m(kind="crypto") == [False, True, False]
    assert m(only_tf="1h") == [False, True, False]
    assert m(max_cost=10.0) == [True, False, True]
    assert m(skip_coins=True) == [True, True, False]
    assert m(skip_families=True) == [True, False, True]
    assert m(stop_vs_move=True) == [True, True, False], "a 0.3% stop under a 0.5% normal move"


def test_the_trade_options_read_each_market_in_its_own_time():
    tokyo_morning = dt.datetime(2026, 10, 1, 10, 0, tzinfo=ZoneInfo("Asia/Tokyo")).timestamp() * 1000
    ny_morning = dt.datetime(2026, 10, 1, 10, 0, tzinfo=NY).timestamp() * 1000
    e = np.array([tokyo_morning, ny_morning], dtype=np.int64)
    assert list(fr.trade_keep("MITSUBISHISTOCK", e, {"own_market": True})) == [True, False]
    assert list(fr.trade_keep("GPNSTOCK", e, {"own_market": True})) == [False, True]
    assert list(fr.trade_keep("KIMISTOCK", e, {"own_market": True})) == [False, False], "no market"
    assert list(fr.trade_keep("BTC", e, {"no_ny_morning": True})) == [True, False]


def test_the_daily_loss_limit_stops_that_days_new_trades():
    """Realized only, the account loss cap's own rule: two -6 losses close
    by 10:00am, so the 11:00am trade (limit 10) is never taken; the next day
    trades again."""
    d0 = dt.datetime(2026, 9, 2, 9, 0, tzinfo=NY).timestamp() * 1000
    h = 3_600_000
    t = np.array([[d0, d0 + h / 2, -6, 1], [d0 + h / 4, d0 + h, -6, 1],
                  [d0 + 2 * h, d0 + 3 * h, 5, 1], [d0 + 24 * h, d0 + 25 * h, 1, 1]], dtype=np.float64)
    slots = [{"coin": "A", "trades": t.copy()}]
    fr.day_loss(slots, 10.0)
    assert list(slots[0]["trades"][:, 2]) == [-6, -6, 1]


# --------------------------------------------------------------- the shard
def _book(cid, coin, pnls, start_ms, step_ms=3_600_000, tp=1.5, sl=1.0):
    from tradingagents import watcher_research as wres

    tr = np.array([[start_ms + i * step_ms, start_ms + i * step_ms + 600_000, p, 1]
                   for i, p in enumerate(pnls)], dtype=np.float64)
    meta = {"id": cid, "coin": coin, "tf": "15m", "signal": "stoch14", "th": 0.0, "tp": tp,
            "sl": sl, "gate": "ok", "cost_of_tp": 5.0, "group": "classic"}
    return wres.ArrBook(meta, tr)


def test_streaks_and_what_followed_them():
    s0 = int((NOW - 50 * HOUR) * 1000)
    books = [_book("AAAA", "A", [1, 1, 1, 1, 1, 1, 1], s0), _book("BBBB", "B", [1, -1, -1, -1, -1, -1], s0)]
    rows, ft = fs.streaks(books, int(NOW * 1000))
    assert [(r["id"], r["kind"], r["length"]) for r in rows] == [("AAAA", "win", 7), ("BBBB", "loss", 5)]
    # after one win: A's six continuations all won; B's one win was followed by a loss
    assert ft[0, 0, 0] == 7 and ft[0, 0, 1] == 6
    # after a run of 5 losses there is no next trade yet: no case
    assert ft[1, 4, 0] == 0 and ft[1, 3, 0] == 1 and ft[1, 3, 1] == 0


def test_beat_random_is_per_trade():
    s0 = int((NOW - 50 * HOUR) * 1000)
    books = [_book("GOOD", "A", [1.0] * 4, s0), _book("BAD", "B", [-1.0] * 8, s0, step_ms=1_800_000)]
    flat = fs.Flat(books, int(NOW * 1000))
    prof, n = flat.sums(np.array([1], np.int64), np.array([s0], np.int64), np.array([s0 + 10 ** 9], np.int64))
    assert (float(prof[0]), int(n[0])) == (-8.0, 8)


# --------------------------------------------------------------- the merge
def _fake_run(tmp, sets_trades, shards=2, rooms=None):
    """Forecast artifacts as the shard writes them: per shard and rule set,
    entry/exit minutes and profit, plus random draws; `rooms` {room: cfg} are
    the rooms' own rules, replayed in the base stage."""
    start = "2026-07-01"
    end_ms = int(dt.datetime(2026, 9, 30, 12, 0, tzinfo=NY).timestamp() * 1000)
    blank = {"tf": {}, "family": {}, "kind": {}, "hour": {}, "stops": {}, "sizes": [0, 0.0, 0, 0.0],
             "costs": 0.0, "trades": 0, "profit": 0.0}
    for sh in range(shards):
        arrays, info = {}, {"shard": str(sh), "stage": "base", "end_ms": end_ms, "start": start,
                            "books": 10, "trades": 100, "sets": [],
                            "rooms": {r: {**blank, "id": fr.rule_id(c)} for r, c in (rooms or {}).items()},
                            "write": {"wr": 70}}
        for j, (cfg, tr) in enumerate(sets_trades):
            mine = tr[sh::shards]
            e = np.array([a for a, _x, _p in mine], dtype=np.int64)
            x = np.array([b for _a, b, _p in mine], dtype=np.int64)
            arrays[f"{j}_e"] = (e // 60_000 - fs.T0_MIN).astype(np.int32)
            arrays[f"{j}_x"] = (x // 60_000 - fs.T0_MIN).astype(np.int32)
            arrays[f"{j}_p"] = np.array([p for _a, _b, p in mine], dtype=np.float32)
            arrays[f"{j}_r"] = np.full(100, -1.0, np.float32)            # random: -1 over 2 trades
            arrays[f"{j}_rn"] = np.full(100, 2, np.int64)
            info["sets"].append({"id": fr.rule_id(cfg), "cfg": cfg, "slots": 3, "open": 0})
        arrays["ft"] = np.zeros((2, 30, 4))
        info["streaks"] = []
        d = tmp / f"forecast-{sh}"
        d.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(d / f"forecast-{sh}.npz", **arrays)
        (d / f"forecast-{sh}.json").write_text(json.dumps(info), encoding="utf-8")
    return tmp


def _ms(y, m, d, h=12):
    return int(dt.datetime(y, m, d, h, tzinfo=NY).timestamp() * 1000)


def test_the_merge_predicts_the_month_from_the_past_ones(tmp_path):
    good = fr.cfg_of(30, 90, 40, ">", 2.0)
    bad = fr.cfg_of(30, 70, 20, ">", 2.0)
    g = [(_ms(2026, 7, 5), _ms(2026, 7, 5, 13), 10.0), (_ms(2026, 8, 5), _ms(2026, 8, 5, 13), 20.0),
         (_ms(2026, 9, 5), _ms(2026, 9, 5, 13), 30.0), (_ms(2026, 9, 6), _ms(2026, 9, 6, 13), -1.0)]
    b = [(_ms(2026, 7, 5), _ms(2026, 7, 5, 13), -5.0), (_ms(2026, 8, 5), _ms(2026, 8, 5, 13), 50.0),
         (_ms(2026, 9, 5), _ms(2026, 9, 5, 13), 5.0)]
    art = _fake_run(tmp_path / "art", [(good, g), (bad, b)])
    reality = {"took": 0.5, "gap": 1.0}
    out = fm.merge(art, reality=reality)
    by = {s["id"]: s for s in out["sets"]}
    s = by[fr.rule_id(good)]
    assert out["data"]["complete"] == ["2026-07", "2026-08", "2026-09"]
    assert [m["profit"] for m in s["months"]] == [10.0, 20.0, 29.0]
    p = s["predicted"]
    assert (p["profit"], p["low"], p["high"], p["months"], p["thin"]) == (20.0, 10.0, 29.0, 3, False)
    # corrected month by month: took x (profit - gap x trades) — Sep has 2 trades
    assert [m["corrected"] for m in s["months"]] == [4.5, 9.5, 13.5]
    assert p["corrected"] == 9.5
    # the WORST past month after the correction ranks: good's worst 4.5 beats bad's -3.0
    assert out["sets"][0]["id"] == fr.rule_id(good)
    # per trade 58/4 = 14.5 against random's -0.5: beat 100 times in 100
    assert s["random"]["beat"] == 100 and not s["luck"]
    assert s["money_needed"] == s["total"]["max_open"] * 5
    json.dumps(out, allow_nan=False)


def test_a_months_first_prediction_is_kept_and_never_overwritten(tmp_path):
    p = tmp_path / "predictions.jsonl"
    out = {"made_at": NOW, "data": {"end_ms": 1}, "reality": {"took": 0.5, "gap": 1.0},
           "sets": [{"id": "X", "words": "w", "room": None, "predicted": {"profit": 1, "low": 0, "high": 2}}]}
    assert fm.keep_prediction(out, p) and not fm.keep_prediction({**out, "made_at": NOW + 3600}, p)
    assert len(p.read_text(encoding="utf-8").splitlines()) == 1


# ----------------------------------------------------------------- the page
def test_the_lists_are_filtered_and_paged_by_the_server():
    settings()
    for i in range(30):
        write(trades([1.0] * (10 + i % 3), symbol=f"C{i:02d}STOCK_USDT", start=NOW - 30 * HOUR + i * 60))
    got = f2a.streaks("practice", "win", 11, page=1)
    assert got["total"] == 20 and got["of"] == 30 and len(got["rows"]) == min(20, f2a.PER_PAGE)
    assert all(r["length"] >= 11 for r in got["rows"])
    # the last page holds what is left, never a page cut in the browser
    last = f2a.streaks("practice", "win", 11, page=got["pages"])
    assert got["pages"] == -(-20 // f2a.PER_PAGE) and len(last["rows"]) == 20 - (got["pages"] - 1) * f2a.PER_PAGE
    assert "every room and coin" in got["examined"]["what"]
    with pytest.raises(ValueError):
        f2a.streaks("everything", "win")
    empty = f2a.rules()
    assert empty["rows"] == [] and "no Forecast v2" in empty["why"]


def test_the_page_prints_and_works_nothing_out():
    src = (ROOT / "webapp/src/components/forecast/ForecastV2.tsx").read_text(encoding="utf-8")
    for words in ("Streaks", "Coins to avoid", "Where the money goes", "Best room rules this month",
                  "Reality check", "What if", "This month so far", "could be luck",
                  "api.forecastV2Streaks", "api.forecastV2Rules", "api.forecastV2WhatIf"):
        assert words in src, words
    assert "toLocale" not in src.replace("toLocaleString()", "")
    assert "new Date(" not in src
    assert ".filter(" not in src.split("function Avoid")[0], "the streak lists are filtered by the server"
    # a day reaches the screen through fmtWhen, never as its "2026-10-01" key
    # (found on the phone pass, Oct 01, 2026 7:35pm)
    assert "worst_day.day" not in src and "fmtWhen(r.worst_day.at)" in src
    # every card and grid column may shrink: a wide table scrolls inside its
    # own box instead of widening the page (1,590px at 1,440; 489px at 390)
    assert 'const card = "min-w-0 ' in src and src.count("[&>*]:min-w-0") >= 2
    # the month tracker is measured by the day, never a month shared out
    # (RCA-2026-10-01-J), and a what-if prints the server's own words for
    # where its run is, never a fixed "about 10-15 minutes" (bug hunt, round 6)
    assert "shared out over the days" not in src and "pastMonths(t.rooms)" in src
    assert "10-15 minutes" not in src
    side = (ROOT / "webapp/src/layout/AppSidebar.tsx").read_text(encoding="utf-8")
    # ONE Forecast item since Oct 02, 2026 (the merge): it opens this page
    assert '{ name: "Forecast", path: "/forecast-v2" }' in side


# ------------------------------------------------------------ the daily chain
def test_a_dispatch_finds_its_own_run_by_title_not_the_newest(monkeypatch):
    """Bug hunt, round 3: two sessions dispatch replay.yml; the newest run
    can be the other session's."""
    from tradingagents import forecast_v2_daily as fd

    inputs = {"shards": 20, "timeframes": "15m", "coin_list": "", "start": "2026-07-01",
              "base": 5, "groups": "all", "write_rule": fd.WRITE_RULE}
    want = fd.title_of(fd.REPLAY_WF, inputs)
    calls = {"n": 0}

    def gh(*args, timeout=120):
        if args[:2] == ("run", "list"):
            calls["n"] += 1
            if calls["n"] == 1:
                return json.dumps([{"databaseId": 1, "displayTitle": want}])
            return json.dumps([{"databaseId": 3, "displayTitle": "Watcher replay · from 2026-07-01 · wr=40,trades=1"},
                               {"databaseId": 2, "displayTitle": want + " "},
                               {"databaseId": 1, "displayTitle": want}])
        return ""

    monkeypatch.setattr(fd, "_gh", gh)
    monkeypatch.setattr(fd.time, "sleep", lambda s: None)
    assert fd.dispatch(fd.REPLAY_WF, inputs, "x/y") == 2


def test_a_custom_run_carries_its_id_in_the_title():
    from tradingagents import forecast_v2_daily as fd

    t = fd.title_of(fd.FORECAST_WF, {"stage": "custom", "source_run": 9, "custom": '{"id":"ABC"}'})
    assert t == 'Forecast v2 · custom · replay 9 {"id":"ABC"}'
    assert fd.title_of(fd.FORECAST_WF, {"stage": "base", "source_run": 9, "custom": ""}) == \
        "Forecast v2 · base · replay 9"
    wf = (ROOT / ".github/workflows/forecast.yml").read_text(encoding="utf-8")
    assert 'run-name: "Forecast v2 · ${{ inputs.stage }} · replay ${{ inputs.source_run }} ${{ inputs.custom }}"' in wf
    rp = (ROOT / ".github/workflows/replay.yml").read_text(encoding="utf-8")
    assert 'run-name: "Watcher replay · from ${{ inputs.start }} · ${{ inputs.write_rule }}"' in rp


def test_streak_bells_ring_once_and_never_for_the_runs_already_going(monkeypatch):
    from tradingagents import forecast_v2_daily as fd, notifications as nt

    rung = []
    monkeypatch.setattr(nt, "record", lambda *a, **k: rung.append(a[1]))
    old = {"room": ROOM, "room_name": "#4FC03172", "coin": "KIMISTOCK", "kind": "win",
           "length": 16, "started_at": NOW - 9 * HOUR, "profit": 6.48}
    assert fd.streak_bells({"streaks": [old]}) == [] and rung == [], "the first run only remembers"
    new = {**old, "coin": "VUG", "length": 9, "started_at": NOW - HOUR}
    assert len(fd.streak_bells({"streaks": [old, new]}, NOW)) == 1
    assert rung == ["VUG has won 9 in a row in #4FC03172"]
    assert fd.streak_bells({"streaks": [old, {**new, "length": 10}]}, NOW + 60) == [], \
        "the same run never rings twice"
    # AT MOST ONE BELL AN HOUR (bug hunt, round 6: one per run would have been
    # 46 bells on Oct 01, 2026); a run inside the hour waits and is named in it,
    # and a room that is off never rings
    loss = {**old, "coin": "DHRSTOCK", "kind": "loss", "length": 5, "started_at": NOW - 600, "profit": -5.1}
    win = {**old, "coin": "CAVASTOCK", "length": 9, "started_at": NOW - 300}
    gone = {**loss, "room": "DC57174E", "room_name": "#DC57174E", "coin": "IGV"}
    assert profiles.retired("DC57174E")
    assert fd.streak_bells({"streaks": [old, new, loss, gone]}, NOW + 600) == []
    assert fd.streak_bells({"streaks": [old, new, loss, win, gone]}, NOW + 1800) == []
    got = fd.streak_bells({"streaks": [old, new, loss, win, gone]}, NOW + HOUR + 1)
    assert len(got) == 2 and rung[-1] == "2 new streaks: 1 winning, 1 losing"
    assert len(rung) == 2 and not any("IGV" in k for k in got)


def test_the_chain_never_runs_under_a_test():
    from tradingagents import forecast_v2_daily as fd

    assert fd.tick()["why"] == "never under a test run"


def test_a_what_if_answers_at_once_and_starts_behind_the_answer(monkeypatch):
    from tradingagents import forecast_v2_daily as fd

    # a replay still running (6) is never what a what-if measures on: the
    # last FINISHED data (5) is (bug hunt, round 4)
    fd._write({"phase": "replay", "replay_run": 6, "end_ms": None, "start": "2026-07-01", "repo": "x/y",
               "ready": {"replay_run": 5, "end_ms": 1, "start": "2026-07-01", "repo": "x/y"}})
    started = []
    monkeypatch.setattr(fd.threading, "Thread", lambda target, args, name, daemon: type(
        "T", (), {"start": lambda self: started.append(args)})())
    got = fd.whatif({"window_days": 30, "on_winrate": 90, "min_trades": 40, "tp_rule": ">", "max_sl": 2})
    assert got["status"] == "starting" and started and json.loads(started[0][2])["id"] == got["id"]
    assert started[0][1]["replay_run"] == 5, "measured on the finished replay, not the running one"
    again = fd.whatif({"window_days": 30, "on_winrate": 90, "min_trades": 40, "tp_rule": ">", "max_sl": 2})
    assert again["id"] == got["id"] and len(started) == 1, "asked twice, started once"


# ------------------------------------------------------ bug hunt, round 6
def test_the_month_tracker_holds_a_day_against_the_same_day_of_past_months(tmp_path, monkeypatch):
    """RCA-2026-10-01-J: the "worst case by today" was a month's worst case
    divided by its days. On Oct 01, 2026 at 7:25pm all six rooms rang — Main
    for -7.29 against "-0.01 by today". A day is held against what the
    room's own rules made by the end of that same day of each past month."""
    from tradingagents import notifications as nt

    rule = fr.cfg_of(30, 90, 20, ">", 2.0)
    # ONE TIMELINE: each past month opens with a losing first day (mid-day,
    # so it is the same calendar day in any zone) and is won back later
    t = [(_ms(2026, 7, 1, 10), _ms(2026, 7, 1, 13), -9.0), (_ms(2026, 7, 20), _ms(2026, 7, 20, 13), 30.0),
         (_ms(2026, 8, 1, 10), _ms(2026, 8, 1, 13), -4.0), (_ms(2026, 8, 20), _ms(2026, 8, 20, 13), 25.0),
         (_ms(2026, 9, 1, 10), _ms(2026, 9, 1, 13), -6.0), (_ms(2026, 9, 2, 10), _ms(2026, 9, 2, 13), -2.0),
         (_ms(2026, 9, 29, 10), _ms(2026, 9, 29, 11), 20.0)]
    out = fm.merge(_fake_run(tmp_path / "art", [(rule, t)], rooms={"main": rule}),
                   reality={"took": 0.5, "gap": 1.0}, keep=False)
    s = out["sets"][0]
    bd = s["by_day"]
    assert sorted(bd) == ["2026-07", "2026-08", "2026-09"]
    assert [len(bd[m]["p"]) for m in sorted(bd)] == [31, 31, 30], "every day of each past month"
    assert bd["2026-09"]["p"][:2] == [-6.0, -8.0] and bd["2026-09"]["n"][:2] == [1, 2]
    assert bd["2026-09"]["p"][-1] == 12.0 and bd["2026-07"]["p"][-1] == 21.0
    # day 1, after the reality check took x (profit - gap x trades):
    # Jul 0.5 x (-9 - 1) = -5.0, Aug -2.5, Sep -3.5
    band = f2a.band_on(s, 1, out["reality"])
    assert (band["corrected_low"], band["corrected"], band["corrected_high"]) == (-5.0, -3.5, -2.5)
    assert (band["low"], band["high"], band["day"]) == (-9.0, -4.0, 1)
    # a day past a month's end is that whole month: day 31 of September is its 30th
    assert f2a.band_on(s, 31, out["reality"])["high"] == 21.0
    assert f2a.band_on({"id": "old"}, 1, out["reality"]) is None, "no days kept: no guess"

    rung = []
    monkeypatch.setattr(nt, "record", lambda *a, **k: rung.append((a[1], k.get("detail"))))

    def room(made):
        return {"rooms": [{"id": "main", "name": "Main", "retired": False,
                           "month": {"trades": 3, "wins": 0, "losses": 3, "profit": made, "days": []}}]}

    # -4.00 on day 1 is inside what past day 1s did (worst -5.00): no bell —
    # the old rule held it against this month's worst 4.50 / 31 = +0.15 and rang
    monkeypatch.setattr(f2a, "live", lambda: room(-4.0))
    tr = f2a.tracker(NOW)
    assert tr["day"] == 1 and tr["rooms"][0]["so_far"]["corrected_low"] == -5.0
    assert not tr["rooms"][0]["below"] and f2a.tracker_alarms(NOW) == [] and rung == []
    # Main's real -7.29 is under it: one bell, naming the months and the day
    monkeypatch.setattr(f2a, "live", lambda: room(-7.29))
    assert f2a.tracker_alarms(NOW) == ["2026-10|main"]
    assert rung == [("Main is under its predicted worst case",
                     f"Main has made -7.29 this month; in Jul, Aug and Sep 2026 its rules "
                     f"#{fr.rule_id(rule)} made at worst -5.00 by the end of day 1, after the "
                     f"reality check")]
    assert f2a.tracker_alarms(NOW) == [], "once a room a month"


def test_off_stays_off_when_a_busy_tick_writes_the_state_back():
    """Bug hunt, round 6: a tick reads the state, can spend minutes in a
    download and a merge, then writes the whole state back — a switch saved
    into the same file meanwhile came back "on"."""
    from tradingagents import forecast_v2_daily as fd

    fd._write({"phase": "replay", "replay_run": 6})
    st = fd.read()                              # the tick reads ...
    assert st["on"] is True
    fd.switch(False)                            # ... the box is switched off mid-merge ...
    fd._write(st)                               # ... and the tick writes back what it read
    assert fd.read()["on"] is False and fd.is_on() is False
    assert "on" not in json.loads(fd._state_path().read_text(encoding="utf-8"))
    fd.switch(True)
    assert fd.read()["on"] is True


def test_a_what_if_asked_while_another_is_polled_is_kept(monkeypatch):
    """Bug hunt, round 6: the poll saved its own copy of the what-if file
    after minutes at GitHub, and a what-if asked meanwhile vanished from it
    while its run went on."""
    from tradingagents import forecast_v2_daily as fd

    fd._whatif_save({"A": {"id": "A", "status": "working", "run": 5, "end_ms": 1,
                           "asked_at": NOW - HOUR}})

    def status(run, repo):
        # while the poll is out at GitHub, the operator asks B
        with fd._WHATIF_LOCK:
            w = fd.whatifs()
            w["B"] = {"id": "B", "status": "working", "run": 9, "end_ms": 1, "asked_at": NOW}
            fd._whatif_save(w)
        return {"status": "queued", "machines": 0, "done": 0, "failed": [], "created": None}

    monkeypatch.setattr(fd, "run_status", status)
    fd._whatifs({"repo": "x/y", "phase": "replay"}, NOW)
    w = fd.whatifs()
    assert set(w) == {"A", "B"}, "the what-if asked meanwhile is still there"
    # a QUEUED what-if names the chain's run beside it — what it waits behind
    assert w["A"]["why"] == ("waiting in GitHub's queue, not started yet — the daily Forecast v2's "
                             "replay run is on GitHub too")


def test_a_run_github_listed_late_is_adopted_never_started_twice(monkeypatch):
    """Bug hunt, round 6: a dispatch that raised because GitHub listed its
    run late was tried again 30 minutes later — and started a SECOND replay,
    20 machines for an hour. A retry adopts the run made since the first try."""
    from tradingagents import forecast_v2_daily as fd

    inputs = {"shards": 20, "timeframes": "15m", "coin_list": "", "start": "2026-07-01",
              "base": 5, "groups": "all", "write_rule": fd.WRITE_RULE}
    want = fd.title_of(fd.REPLAY_WF, inputs)

    def iso(s):
        return dt.datetime.fromtimestamp(s, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    calls, shown = [], {"late": False}

    def gh(*args, timeout=120):
        calls.append(args[:2])
        if args[:2] == ("run", "list"):
            rows = [{"databaseId": 1, "displayTitle": want, "createdAt": iso(NOW - 24 * HOUR)}]
            if shown["late"]:
                rows.insert(0, {"databaseId": 7, "displayTitle": want, "createdAt": iso(NOW + 30)})
            return json.dumps(rows)
        return ""

    monkeypatch.setattr(fd, "_gh", gh)
    monkeypatch.setattr(fd.time, "sleep", lambda s: None)
    st = {}
    with pytest.raises(RuntimeError):
        fd.dispatch(fd.REPLAY_WF, inputs, "x/y", since=fd._tried(st, "replay 2026-07-01", NOW))
    shown["late"] = True                       # GitHub had taken it after all
    assert fd.dispatch(fd.REPLAY_WF, inputs, "x/y",
                       since=fd._tried(st, "replay 2026-07-01", NOW + 1800)) == 7
    assert calls.count(("workflow", "run")) == 1, "the run GitHub took is adopted, never started twice"
    assert fd._tried({"tried": {"what": "base 5", "at": NOW}}, "options 5", NOW + 9) is None, \
        "another dispatch's attempt is not this one's"


def test_a_queued_run_says_it_is_waiting_not_working():
    """Bug hunt, round 6: a what-if asked at 7:26pm sat QUEUED behind the
    daily replay's 20 machines while the page said "working on GitHub: 0 of
    0 machines done"."""
    from tradingagents import forecast_v2_daily as fd
    from tradingagents.positions_view import fmt_when

    assert fd.run_words({"status": "queued", "machines": 0, "done": 0, "created": NOW}) == \
        f"waiting in GitHub's queue since {fmt_when(NOW)}, not started yet"
    assert fd.run_words({"status": "in_progress", "machines": 0, "done": 0}) == "GitHub is starting it"
    assert fd.run_words({"status": "in_progress", "machines": 20, "done": 3}) == \
        "working on GitHub: 3 of 20 machines done"


def test_a_cut_title_still_finds_its_run():
    from tradingagents import forecast_v2_daily as fd

    want = ('Forecast v2 · custom · replay 36763426504 {"id":"2F39EAEC","on_winrate":85.0,'
            '"off_winrate":85.0,"min_trades":30,"tp_rule":">","window_days":30}')
    assert fd.same_title(want, want) and fd.same_title(want + " ", want)
    assert fd.same_title(want[:70] + "…", want), "GitHub's cut of a long title"
    assert not fd.same_title(want[:40], want), "too short to hold the rule id"
    assert not fd.same_title(want.replace("2F39EAEC", "AAAAAAAA")[:70], want)


def test_a_what_if_cut_off_by_a_restart_is_asked_again_and_its_run_adopted(monkeypatch):
    """Bug hunt, round 6: a site restart between "starting" and GitHub's
    answer left the what-if "starting" for ever — and asking again returned
    that same stuck answer."""
    from tradingagents import forecast_v2_daily as fd

    monkeypatch.setattr(fd, "_STARTING", set())
    fd._write({"phase": "idle", "ready": {"replay_run": 5, "end_ms": 1, "start": "2026-07-01", "repo": "x/y"}})
    started = []
    monkeypatch.setattr(fd.threading, "Thread", lambda target, args, name, daemon: type(
        "T", (), {"start": lambda self: started.append(args)})())
    cfg = {"window_days": 30, "on_winrate": 85, "min_trades": 30, "tp_rule": ">", "max_sl": 2}
    got = fd.whatif(cfg)
    assert fd._cut_starts(got["asked_at"] + 61) == [], "a start this process is still making is never cut"
    fd._STARTING.clear()                        # the site restarted: nothing is asking GitHub for it
    assert fd._cut_starts(got["asked_at"] + 30) == [], "a second-old start is never cut"
    assert fd._cut_starts(got["asked_at"] + 61) == [got["id"]]
    assert fd.whatifs()[got["id"]]["status"] == "failed"
    again = fd.whatif(cfg)
    assert again["status"] == "starting" and len(started) == 2
    assert started[1][3] == got["tried_at"], "the re-ask adopts a run the cut-off start made"


def test_a_chain_that_ran_past_midnight_does_not_hold_back_the_next_update(monkeypatch):
    """Bug hunt, round 6: "one a day" counted by the day the chain FINISHED,
    so a chain started Sep 30 11pm and done Oct 01 1:30am held Oct 01's
    update back until the midnight after it."""
    from tradingagents import forecast_v2_daily as fd, room_forecasts as rf

    monkeypatch.setattr(rf, "_update", lambda: {"runs": [1], "collected": [1], "when": NOW - 5 * HOUR})
    st = {"phase": "done", "started_day": "2026-09-30", "started_at": NOW - 15 * HOUR,
          "done_day": "2026-10-01", "done_at": NOW - 12.5 * HOUR, "last_update": NOW - 48 * HOUR}
    ok, why = fd.due(NOW, st)
    assert ok, why
    ok, why = fd.due(NOW, {**st, "started_day": "2026-10-01"})
    assert not ok and why.startswith("today's Forecast v2 was made at")
    # a state from before started_day was kept counts the day it started at
    ok, _why = fd.due(NOW, {k: v for k, v in st.items() if k != "started_day"})
    assert ok


def test_a_what_if_is_corrected_with_the_tables_own_numbers():
    from tradingagents import forecast_v2_daily as fd

    fd.home().mkdir(parents=True, exist_ok=True)
    (fd.home() / "latest.json").write_text(json.dumps({"reality": {"took": 0.1799, "gap": 0.2225}}),
                                           encoding="utf-8")
    assert fd._reality_of_table() == {"took": 0.1799, "gap": 0.2225}


def test_only_the_days_final_merge_keeps_the_months_prediction(monkeypatch, tmp_path):
    """RCA-2026-10-01-K: October's graded prediction was kept at Oct 01, 2026
    6:59pm by the base-only merge — 576 rule sets, without the 572 with an
    option or the best of all, #A8CD8C72. The chain's base merge keeps
    nothing; only the day's final merge keeps the month."""
    from tradingagents import forecast_v2_daily as fd

    merges = []
    monkeypatch.setattr(fd, "run_status", lambda run, repo: {
        "status": "completed", "conclusion": "success", "machines": 20, "done": 20, "failed": [],
        "created": None})
    monkeypatch.setattr(fd, "download", lambda run, repo, pattern: tmp_path / str(run))
    monkeypatch.setattr(fd, "run_merge", lambda base, opts, runs, keep: merges.append((opts is None, keep)))
    monkeypatch.setattr(fd, "_latest", lambda: {"made_at": 1, "sets": [
        {"base": True, "cfg": fr.cfg_of(30, 90, 40, ">", 2.0)}]})
    monkeypatch.setattr(fd, "dispatch", lambda wf, inputs, repo, since=None: 77)
    monkeypatch.setattr(fd, "room_rules", lambda: {})
    monkeypatch.setattr(fd, "bell", lambda out, live: None)
    monkeypatch.setattr(fd.f2, "live", lambda: {})
    # a base step that failed an hour ago and is now tried again
    st = {"phase": "base", "on": True, "repo": "x/y", "replay_run": 5, "base_run": 6,
          "end_ms": 1, "start": "2026-07-01", "error": "base: RuntimeError: download cut",
          "failed_at": NOW - HOUR}
    said = []
    monkeypatch.setattr(fd, "run_merge", lambda base, opts, runs, keep: (
        said.append(fd.read()["why"]), merges.append((opts is None, keep))))
    fd._step(st, NOW)
    assert st["phase"] == "options" and merges == [(True, False)], "the base-only merge keeps nothing"
    # bug hunt, round 11: a step that got through clears the error it was retried for
    assert st["error"] == "" and st["failed_at"] == 0
    # bug hunt, round 15: through the merge the page says the run FINISHED,
    # never "working on GitHub" — said on disk before the slow part
    assert said == ["base run 6 finished on GitHub — downloading and adding it up on this PC (a few minutes)"]
    fd._step(st, NOW + 600)
    assert st["phase"] == "done" and merges[-1] == (False, True), "the day's final merge keeps the month"
    assert st["ready"]["replay_run"] == 5
    # bug hunt, rounds 16-17: "made at" is the merge's own stamp — the time
    # the card under it prints — never the tick's start
    assert st["done_at"] == 1.0 and st["why"].startswith("made at ")


# ------------------------------------------------------ bug hunt, round 7
def test_the_daily_bell_names_each_rooms_month_against_its_range(monkeypatch):
    """Bug hunt, round 7: the build prompt's section E asks for "the longest
    winning streak, the longest losing streak, the worst coin to avoid, and
    each room's month so far against its predicted range"; the bell said so
    in its docstring and never added the rooms."""
    from tradingagents import forecast_v2_daily as fd, notifications as nt

    rung = []
    monkeypatch.setattr(nt, "record", lambda kind, title, **k: rung.append((title, k)))
    live = {"streaks": [{"kind": "win", "coin": "KIMISTOCK", "room_name": "#CC94D9FB", "length": 16},
                        {"kind": "loss", "coin": "DHRSTOCK", "room_name": "#4FC03172", "length": 13}],
            "avoid": {"coins": [{"coin": "IGV", "profit": -50.87, "trades": 47}]}}

    def room(name, made, lo, hi, below):
        return {"name": name, "month": {"profit": made}, "below": below,
                "so_far": {"corrected_low": lo, "corrected_high": hi, "day": 1}}

    # the six rooms as the bell of Oct 01, 2026 8:54pm had them — it named 3
    # of them and "and 4 more" (bug hunt, round 16): every room fits now
    rooms = [room("Main", -5.51, 0.0, 0.47, True), room("#55D32617", -34.43, -5.27, 19.78, True),
             room("#4FC03172", -175.07, -3.12, 0.78, True), room("#B2404C0B", -19.02, 0.0, 9.53, True),
             room("#6B08FF64", 1.0, 0.24, 5.14, False), room("#CC94D9FB", -42.72, 0.0, 3.49, True)]
    out = {"made_at": 1, "sets": [{"id": "A8CD8C72", "predicted": {"profit": 1018.99, "corrected": 92.17}}]}
    fd.bell(out, live, rooms)
    title, k = rung[0]
    d = k["detail"]
    assert title == "Forecast v2 is ready" and len(d) <= fd.BELL_CHARS
    order = ["longest winning run: KIMISTOCK in #CC94D9FB, 16 in a row",
             "longest losing run: DHRSTOCK in #4FC03172, 13 in a row",
             "worst coin: IGV -50.87 over 47 trades",
             "each room this month vs its rules by day 1 (after the reality check): "
             "Main -5.51 below (+0.00 to +0.47)",
             "#55D32617 -34.43 below (-5.27 to +19.78)", "#4FC03172 -175.07 below (-3.12 to +0.78)",
             "#B2404C0B -19.02 below (+0.00 to +9.53)", "#6B08FF64 +1.00 (+0.24 to +5.14)",
             "#CC94D9FB -42.72 below (+0.00 to +3.49)"]
    assert [d.find(x) for x in order] == sorted(d.find(x) for x in order) and min(d.find(x) for x in order) == 0
    assert k["ok"] is False, "a room under its worst case is not an all-clear"


def test_a_long_bell_keeps_its_count_of_the_rest(monkeypatch):
    """Bug hunt, round 7: notifications.record keeps 500 characters of a
    detail, so twelve names and "and 34 more on the Forecast v2 page" lost
    the count first. A part that does not fit is left out whole and counted."""
    from tradingagents import forecast_v2_daily as fd, notifications as nt

    texts = [f"C{i:02d}STOCK has lost 5 in a row in #4FC03172" for i in range(46)]
    d = fd.fit(texts[:12], left=34)
    assert len(d) <= 500 and d.endswith("more on the Forecast v2 page")
    shown = d.count("has lost 5 in a row")
    assert d.endswith(f"and {46 - shown} more on the Forecast v2 page") and shown < 12
    assert fd.fit(["a", "b"]) == "a; b" and fd.fit(["x" * 600]) == "and 1 more on the Forecast v2 page"
    # the streak bell itself, 46 new runs in one hour
    rung = []
    monkeypatch.setattr(nt, "record", lambda kind, title, **k: rung.append((title, k["detail"])))
    base = {"room": ROOM, "room_name": "#4FC03172", "kind": "loss", "length": 5, "profit": -5.0}
    assert fd.streak_bells({"streaks": []}, NOW) == []                     # the first run only remembers
    runs = [{**base, "coin": f"C{i:02d}STOCK", "started_at": NOW + i} for i in range(46)]
    assert len(fd.streak_bells({"streaks": runs}, NOW + 10)) == 46
    title, d = rung[-1]
    assert title == "46 new streaks: 0 winning, 46 losing" and len(d) <= 500
    assert d.endswith(f"and {46 - d.count('in a row')} more on the Forecast v2 page")


# ------------------------------------------------------ bug hunt, round 8
def test_a_refused_swap_is_retried_not_lost(tmp_path, monkeypatch):
    """Bug hunt, round 8: on Windows a reader holding a file open refuses the
    swap that replaces it — the page reads state.json and whatif.json every
    30 seconds, and a refused swap once ended a 96%-finished backtest
    (RCA-2026-09-18-B). Every Forecast v2 file swaps through replace_retry."""
    real = Path.replace
    refused = {"n": 0}

    def flaky(self, target):
        if refused["n"] < 3:
            refused["n"] += 1
            raise PermissionError(13, "the page is reading it")
        return real(self, target)

    monkeypatch.setattr(Path, "replace", flaky)
    f2.publish(tmp_path / "state.json", '{"phase":"base"}')
    assert refused["n"] == 3 and (tmp_path / "state.json").read_text(encoding="utf-8") == '{"phase":"base"}'
    # past the budget it raises, and leaves no temp file behind
    monkeypatch.setattr(f2, "REPLACE_BUDGET_S", 0.05)
    monkeypatch.setattr(Path, "replace", lambda self, target: (_ for _ in ()).throw(PermissionError(13, "held")))
    with pytest.raises(PermissionError):
        f2.publish(tmp_path / "state.json", '{"phase":"options"}')
    assert not [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    for src in ("forecast_v2_daily.py", "forecast_v2_api.py", "forecast_v2_merge.py"):
        code = (ROOT / "tradingagents" / src).read_text(encoding="utf-8")
        assert "os.replace(" not in code and ".write_text(json.dumps" not in code, src


def test_a_dispatch_is_on_disk_before_it_is_made(monkeypatch):
    """Bug hunt, round 8: the tick saved its state only at its end, so a tick
    that dispatched a replay and then failed to save left no trace — and the
    next tick started the same 20-machine run again. The attempt is saved
    BEFORE the dispatch, and the next tick adopts what it started."""
    from tradingagents import forecast_v2_daily as fd, room_forecasts as rf

    monkeypatch.setattr(fd, "due", lambda now, st: (True, "the update is on this PC"))
    monkeypatch.setattr(fd, "skip_lists", lambda: ([], []))
    monkeypatch.setattr(rf, "_update", lambda: {"runs": [1], "collected": [1], "when": NOW - HOUR})
    sinces = []

    def dispatch(wf, inputs, repo, since=None):
        sinces.append(since)
        if len(sinces) == 1:
            raise RuntimeError("GitHub took it but did not list it within 90 seconds")
        return 41

    monkeypatch.setattr(fd, "dispatch", dispatch)
    st = {"phase": "idle", "on": True, "repo": "x/y"}
    with pytest.raises(RuntimeError):
        fd._step(st, NOW)                      # this tick never reaches its own save
    fresh = fd.read()                           # the next tick reads only what is on disk
    assert fresh["tried"]["what"].startswith("replay ") and fresh["tried"]["at"] == NOW
    fd._step(fresh, NOW + 1800)
    assert sinces == [None, NOW], "the retry looks for the run the first try started"
    assert fresh["phase"] == "replay" and fresh["replay_run"] == 41 and "tried" not in fresh


def test_an_off_saved_before_the_box_had_its_own_file_stays_off():
    """Bug hunt, round 10: the box used to live in state.json; the first
    save after the switch got its own file dropped it, so a chain switched
    off on another machine would have come back on after `git pull`."""
    from tradingagents import forecast_v2_daily as fd

    fd.home().mkdir(parents=True, exist_ok=True)
    fd._state_path().write_text('{"phase":"done","on":false}', encoding="utf-8")
    assert not fd._switch_path().exists() and fd.read()["on"] is False
    fd._write(fd.read())                       # the first save by the new code
    assert fd.read()["on"] is False and fd.is_on() is False
    assert "on" not in json.loads(fd._state_path().read_text(encoding="utf-8"))
    fd.switch(True)
    fd._write(fd.read())
    assert fd.read()["on"] is True, "once the box has its own file, it alone decides"


# ----------------------------------------------------- bug hunt, round 12
def test_a_run_red_on_every_machine_is_started_again_once_then_the_day_is_given_up(monkeypatch):
    """Bug hunt, round 12: a run that failed on every machine raised, and the
    retry 30 minutes later read the SAME failed run again — for ever: never
    started again, never back to idle, so no later day ran either."""
    from tradingagents import forecast_v2_daily as fd

    red = {"status": "completed", "conclusion": "failure", "machines": 20, "done": 20,
           "failed": [f"forecast ({i})" for i in range(20)], "created": None}
    monkeypatch.setattr(fd, "run_status", lambda run, repo: red)
    monkeypatch.setattr(fd, "room_rules", lambda: {})
    started = []
    monkeypatch.setattr(fd, "dispatch", lambda wf, inputs, repo, since=None: started.append(
        (wf, inputs["stage"])) or 88)
    ready = {"replay_run": 5, "end_ms": 1, "start": "2026-07-01", "repo": "x/y"}
    st = {"phase": "base", "on": True, "repo": "x/y", "replay_run": 6, "base_run": 7, "end_ms": 2,
          "start": "2026-07-01", "started_day": "2026-10-01", "ready": ready}
    fd._step(st, NOW)
    assert started == [(fd.FORECAST_WF, "base")] and st["base_run"] == 88 and st["phase"] == "base"
    assert st["why"].endswith("started again as run 88 (try 2 of 2)")
    fd._step(st, NOW + 600)                     # the second run is red on every machine too
    assert len(started) == 1 and st["phase"] == "idle", "started again ONCE, then the day is given up"
    assert st["error"].startswith("base: base run 88 ended failure on every machine")
    assert st["ready"] == ready, "the last finished data stays on the page"
    ok, why = fd.due(NOW + 700, st)
    assert not ok and why.startswith("today's Forecast v2 was given up")


def test_both_stages_are_merged_over_the_same_machines(tmp_path):
    """Bug hunt, round 12: a run is used with some machines red, and a
    machine is a share of the coins — base without one machine and options
    without another would rank rule sets measured on different markets."""
    good = fr.cfg_of(30, 90, 40, ">", 2.0)
    opt = {**good, "skip_jp": True}
    t = [(_ms(2026, 7, 5), _ms(2026, 7, 5, 13), 10.0), (_ms(2026, 8, 5), _ms(2026, 8, 5, 13), 20.0),
         (_ms(2026, 9, 5), _ms(2026, 9, 5, 13), 30.0)]
    base = _fake_run(tmp_path / "base", [(good, t)], shards=3)
    opts = _fake_run(tmp_path / "opts", [(opt, t)], shards=3)
    import shutil

    shutil.rmtree(opts / "forecast-2")          # the options run's machine 2 failed
    out = fm.merge(base, opts, runs={"shards": 3}, reality={"took": 0.5, "gap": 1.0}, keep=False)
    assert (out["data"]["machines"], out["data"]["of"], out["data"]["shards"]) == (2, 3, [0, 1])
    by = {s["id"]: s for s in out["sets"]}
    # trade j of 3 sits on machine j % 3: machine 2 held September's +30
    assert by[fr.rule_id(good)]["total"]["profit"] == 30.0, "the base set lost machine 2 as well"
    assert by[fr.rule_id(opt)]["total"]["profit"] == 30.0


def test_the_page_names_the_machines_a_run_was_used_without(monkeypatch):
    """Bug hunt, round 12: the chain's own comment said the missing machines
    were "named in the state and on the page" — the page was never sent them."""
    from tradingagents import forecast_v2_daily as fd

    monkeypatch.setattr(f2a, "live", lambda: {"at": 1, "took_ms": 1, "rooms": [], "avoid": {}, "money": {},
                                              "reality": {}, "defaults": {}, "streaks": []})
    gone = {"base": {"of": 20, "failed": ["forecast (3)"]}}
    fd._write({"phase": "options", "missing": gone})
    assert f2a.summary()["chain"]["missing"] == gone
    src = (ROOT / "webapp/src/components/forecast/ForecastV2.tsx").read_text(encoding="utf-8")
    assert "PART OF THE MARKET" in src and "used without:" in src


def test_a_what_if_says_which_data_it_was_measured_on():
    """Bug hunt, round 13: once the daily run lands, the table is measured on
    a newer replay (tonight's ends Oct 01, 2026 4:00pm) than a what-if asked
    the day before (Sep 30, 2026 12:00pm), and the row never said which."""
    from tradingagents import forecast_v2_daily as fd

    src = (ROOT / "webapp/src/components/forecast/ForecastV2.tsx").read_text(encoding="utf-8")
    assert '"measured on"' in src and "data to ${fmtWhenMs(w.end_ms)}" in src
    assert "older than the table's; ask again to measure it on the newest" in src
    # and asking again really does measure it on the newest data
    fd._write({"phase": "done", "ready": {"replay_run": 9, "end_ms": 2, "start": "2026-07-01", "repo": "x/y"}})
    cfg = {"window_days": 30, "on_winrate": 85, "min_trades": 30, "tp_rule": ">", "max_sl": 2}
    rid = fr.rule_id(fr.cfg_of(30, 85.0, 30, ">", 2.0))
    fd._whatif_save({rid: {"id": rid, "status": "done", "run": 4, "end_ms": 1, "result": {}}})
    import threading as _t

    started = []
    real = _t.Thread
    try:
        fd.threading.Thread = lambda target, args, name, daemon: type(
            "T", (), {"start": lambda self: started.append(args)})()
        got = fd.whatif(cfg)
    finally:
        fd.threading.Thread = real
        fd._STARTING.discard(rid)
    assert got["status"] == "starting" and got["end_ms"] == 2 and started[0][1]["replay_run"] == 9


def test_a_what_ifs_download_is_gone_once_it_is_read(tmp_path, monkeypatch):
    """Bug hunt, round 14: the what-if's download was deleted while its .npz
    files were still open, which Windows refuses; ignore_errors hid it, and
    #2F39EAEC's 20 .npz files stayed on disk at Oct 01, 2026 8:35pm while its
    .json files went. (On Windows this test is red on the old code.)"""
    from tradingagents import forecast_v2_daily as fd

    cfg = fr.cfg_of(30, 85, 30, ">", 2.0)
    art = _fake_run(tmp_path / "w", [(cfg, [(_ms(2026, 8, 5), _ms(2026, 8, 5, 13), 4.0)])])
    monkeypatch.setattr(fd, "run_status", lambda run, repo: {
        "status": "completed", "conclusion": "success", "machines": 2, "done": 2, "failed": [],
        "created": None})
    monkeypatch.setattr(fd, "download", lambda run, repo, pattern: art)
    monkeypatch.setattr(fd, "_reality_of_table", lambda: {"took": 0.5, "gap": 1.0})
    fd._whatif_save({"W": {"id": "W", "status": "working", "run": 5, "end_ms": 1, "asked_at": NOW}})
    fd._whatifs({"repo": "x/y"}, NOW)
    w = fd.whatifs()["W"]
    assert w["status"] == "done" and w["result"]["total"]["profit"] == 4.0
    assert not art.exists(), "the download is gone once it is read"


# ----------------------------------------------------- bug hunt, round 16
def test_a_prediction_carries_the_strategies_it_was_measured_over(tmp_path):
    """Bug hunt, round 16: the same rule set on two replays — #562C0147 made
    1,703 July trades on the first (2 signal groups, 1,079 coins, 50% / 10
    trades / TP wider than SL) and 2,098 on Oct 01, 2026's (4 groups, 1,092
    coins, 70% / 20 trades / any TP). A prediction graded against a result
    over different strategies is not a grade, so each one says what it covered."""
    from tradingagents import forecast_v2_daily as fd

    rep = tmp_path / "rep" / "replay-report-0"
    rep.mkdir(parents=True)
    write = {"wr": 70.0, "trades": 20, "tp": "any", "windows": [15, 30]}
    (rep / "replay-report-0.json").write_text(json.dumps({
        "kept": 42930, "tested": 2_000_000, "start": "2026-07-01", "write": write,
        "groups": ["classic", "preset", "sep25", "sep27ml"],
        "spans": {"BTC_USDT 15m": [1, _ms(2026, 10, 1, 16)], "BTC_USDT 1d": [1, _ms(2026, 9, 30, 20)],
                  "ASESTOCK_USDT 15m": [1, _ms(2026, 10, 1, 17)]}}), encoding="utf-8")
    got = fd.read_reports(tmp_path / "rep")
    assert got["end_ms"] == _ms(2026, 10, 1, 16), "the common end, intraday frames only"
    uni = {"write": write, "groups": ["classic", "preset", "sep25", "sep27ml"], "coins": 2, "strategies": 42930}
    assert got["universe"] == uni
    good = fr.cfg_of(30, 90, 40, ">", 2.0)
    t = [(_ms(2026, 7, 5), _ms(2026, 7, 5, 13), 10.0), (_ms(2026, 8, 5), _ms(2026, 8, 5, 13), 20.0),
         (_ms(2026, 9, 5), _ms(2026, 9, 5, 13), 30.0)]
    out = fm.merge(_fake_run(tmp_path / "art", [(good, t)]), runs={"universe": uni, "shards": 2},
                   reality={"took": 0.5, "gap": 1.0}, keep=False)
    assert out["data"]["universe"] == uni
    p = tmp_path / "predictions.jsonl"
    assert fm.keep_prediction(out, p)
    assert json.loads(p.read_text(encoding="utf-8"))["universe"] == uni


def test_only_the_chain_keeps_a_months_prediction(tmp_path, monkeypatch):
    """Bug hunt, round 16: `python -m tradingagents.forecast_v2_merge` kept the
    month BY DEFAULT, so a merge run by hand on a research replay claimed
    October's prediction (6:59pm, and the 7:57pm repair). Keeping is asked
    for with --keep, which only the chain's final merge passes."""
    from tradingagents import forecast_v2_daily as fd

    monkeypatch.setattr(fm.f2, "live", lambda: {"reality": {"all": {"took": 0.5, "gap": 1.0}}})
    good = fr.cfg_of(30, 90, 40, ">", 2.0)
    t = [(_ms(2026, 7, 5), _ms(2026, 7, 5, 13), 10.0), (_ms(2026, 8, 5), _ms(2026, 8, 5, 13), 20.0)]
    art = _fake_run(tmp_path / "art", [(good, t)])
    kept = fm.home() / "predictions.jsonl"
    assert fm.main([str(art)]) == 0 and not kept.exists(), "a merge by hand keeps nothing"
    assert fm.main([str(art), "--keep"]) == 0 and kept.exists()
    # and the chain asks for it on its final merge only
    import subprocess

    calls = []
    monkeypatch.setattr(subprocess, "run", lambda args, **k: calls.append(args) or type(
        "R", (), {"returncode": 0})())
    fd.run_merge("b", None, {}, keep=False)
    fd.run_merge("b", "o", {}, keep=True)
    assert "--keep" not in calls[0] and "--no-keep" not in calls[0] and calls[1][-1] == "--keep"


def test_a_grade_says_when_it_covers_other_strategies():
    """Bug hunt, round 16: the store grows — Oct 01, 2026 went from 2 signal
    groups and 1,079 coins to 4 and 1,092 — so a month graded on newer data
    says what each side covered when they differ."""
    old = {"write": {"wr": 70.0, "trades": 20, "tp": "any", "windows": [15, 30]},
           "groups": ["classic", "preset", "sep25", "sep27ml"], "coins": 1092, "strategies": 695845}
    new = {**old, "groups": old["groups"] + ["oct12"], "coins": 1100}
    home = f2._home()
    home.mkdir(parents=True, exist_ok=True)
    (home / "predictions.jsonl").write_text(json.dumps(
        {"month": "2026-10", "made_at": NOW, "data_end_ms": 1, "universe": old, "sets": []}) + "\n",
        encoding="utf-8")
    (home / "latest.json").write_text(json.dumps({"data": {"complete": [], "universe": new}, "sets": []}),
                                      encoding="utf-8")
    g = f2a.grading()["months"][0]
    assert g["differs"] and g["universe"] == old and g["now"] == new
    f2a._FILES.clear()
    (home / "latest.json").write_text(json.dumps({"data": {"complete": [], "universe": old}, "sets": []}),
                                      encoding="utf-8")
    g = f2a.grading()["months"][0]
    assert not g["differs"] and g["now"] is None
    src = (ROOT / "webapp/src/components/forecast/ForecastV2.tsx").read_text(encoding="utf-8")
    assert "the newest data covers" in src
