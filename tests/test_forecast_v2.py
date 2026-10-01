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
def _fake_run(tmp, sets_trades, shards=2):
    """Forecast artifacts as the shard writes them: per shard and rule set,
    entry/exit minutes and profit, plus random draws."""
    start = "2026-07-01"
    end_ms = int(dt.datetime(2026, 9, 30, 12, 0, tzinfo=NY).timestamp() * 1000)
    for sh in range(shards):
        arrays, info = {}, {"shard": str(sh), "stage": "base", "end_ms": end_ms, "start": start,
                            "books": 10, "trades": 100, "sets": [], "rooms": {}, "write": {"wr": 70}}
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
    assert got["total"] == 20 and got["of"] == 30 and len(got["rows"]) == f2a.PER_PAGE - 5
    assert all(r["length"] >= 11 for r in got["rows"])
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
    side = (ROOT / "webapp/src/layout/AppSidebar.tsx").read_text(encoding="utf-8")
    assert '{ name: "Forecast v2", path: "/forecast-v2" }' in side
