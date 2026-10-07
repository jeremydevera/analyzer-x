"""The daytime rule (Oct 07, 2026; trial on #4FC03172).

Operator: "so what do you think is the correct, because its seems like i
cannot rely on winrate for past 30 days", then "yes" to building the best rule
of the walk-forward test as a room rule. Spec:
docs/superpowers/specs/2026-10-07-daytime-rule-design.md

Measured: today's rule 14,010 takeable bets, 53.4% won, -$672.37; the daytime
rule 1,655 bets, 60.1% won, +$394.82, green on 16 of 16 test days.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from tradingagents import daytime_rule as dr

NY = ZoneInfo("America/New_York")
DAY = 86_400_000


def _ny(y, m, d, h, mi=0) -> float:
    return dt.datetime(y, m, d, h, mi, tzinfo=NY).timestamp()


def _ms(y, m, d, h, mi=0) -> int:
    return int(_ny(y, m, d, h, mi) * 1000)


# ------------------------------------------------------------- market hours
def test_market_hours_are_new_york_weekdays_9_30_to_4():
    assert dr.in_market_hours(_ny(2026, 10, 5, 9, 30))       # Monday open
    assert dr.in_market_hours(_ny(2026, 10, 5, 15, 59))
    assert not dr.in_market_hours(_ny(2026, 10, 5, 16, 0))   # the close
    assert not dr.in_market_hours(_ny(2026, 10, 5, 9, 29))
    assert not dr.in_market_hours(_ny(2026, 10, 6, 22, 15))  # Oct 06 night
    assert not dr.in_market_hours(_ny(2026, 10, 3, 11, 0))   # Saturday


def test_market_hours_follow_daylight_saving():
    # Nov 02, 2026 is after the clocks go back: 9:30am New York is 14:30 UTC
    utc = dt.datetime(2026, 11, 2, 14, 30, tzinfo=dt.timezone.utc).timestamp()
    assert dr.in_market_hours(utc)
    assert not dr.in_market_hours(utc - 60)


def test_a_stock_token_is_named_stock():
    assert dr.is_stock("FWDISTOCK_USDT") and dr.is_stock("INNOLUXSTOCK")
    assert not dr.is_stock("BB_USDT") and not dr.is_stock("ZINC")


# ------------------------------------------------------- pays after fees
def test_a_win_must_pay_a_loss_after_the_rows_own_fee():
    assert dr.pays_a_loss({"tp": 1.5, "sl": 1.0, "rt": 0.22})       # 1.28 vs 1.22
    assert not dr.pays_a_loss({"tp": 1.0, "sl": 0.8, "rt": 0.22})   # 0.78 vs 1.02
    # #TBGNFDCE FWDISTOCK 15m willr14: +$0.38 against -$0.72
    assert not dr.pays_a_loss({"tp": 0.6, "sl": 0.5, "rt": 0.22})


def test_the_fee_comes_from_cost_of_tp_when_rt_is_missing():
    assert dr.fee_of({"tp": 2.0, "sl": 1.0, "cost_of_tp": 11.0}) == pytest.approx(0.22)
    assert dr.pays_a_loss({"tp": 2.0, "sl": 1.0, "cost_of_tp": 11.0})


def test_an_unknown_fee_never_passes():
    assert dr.fee_of({"tp": 2.0, "sl": 1.0}) is None
    assert not dr.pays_a_loss({"tp": 2.0, "sl": 1.0})
    assert not dr.pays_a_loss({"tp": 2.0, "sl": 1.0, "cost_of_tp": 0})


# ------------------------------------------------------------- list checks
def _t(entry_ms, pnl):
    # [entry_ms, known_ms, pnl, closed, exit_ms, why, side]
    return [entry_ms, entry_ms + 600_000, pnl, True, entry_ms + 600_000,
            "TP" if pnl > 0 else "SL", "LONG"]


END = _ms(2026, 10, 2, 20)            # the list's last candle, a Friday night


def _days(n_day, wins_day, n_night, wins_night, *, days_back=10):
    """Trades spread over the 10 weekdays before END: daytime at 11:00am New
    York, night at 10:00pm."""
    out = []
    d = dt.datetime(2026, 10, 2, tzinfo=NY)
    picked = 0
    while picked < days_back:
        if d.weekday() < 5:
            picked += 1
            for i in range(n_day):
                out.append(_t(int(d.replace(hour=11, minute=i % 60).timestamp() * 1000),
                              0.8 if i < wins_day else -1.0))
            for i in range(n_night):
                out.append(_t(int(d.replace(hour=22, minute=i % 60).timestamp() * 1000),
                              0.8 if i < wins_night else -1.0))
        d -= dt.timedelta(days=1)
    return out


def test_a_stock_strategy_that_wins_only_at_night_fails():
    # 3 a day in daytime, 1 won (33%); 5 a night, all won
    why = dr.list_checks(_days(3, 1, 5, 5), "FWDISTOCK", END, 70.0)
    assert "daytime" in why and "33.3%" in why


def test_a_stock_strategy_that_wins_in_daytime_passes():
    assert dr.list_checks(_days(3, 3, 5, 1), "GPNSTOCK", END, 70.0) == ""


def test_too_few_daytime_trades_fail():
    why = dr.list_checks(_days(1, 1, 5, 5), "GPNSTOCK", END, 70.0)   # 10 daytime
    assert "10 daytime trades" in why


def test_crypto_is_judged_on_every_hour():
    assert dr.list_checks(_days(0, 0, 3, 3), "BB", END, 70.0) == ""


def test_the_last_7_days_must_still_win():
    # 30 weekdays of daytime wins, so the 30-day daytime record stays 70%+ ...
    trades = _days(3, 3, 0, 0, days_back=30)
    # ... and the last 7 days before END lose: every trade after END - 7 days
    trades = [t if t[4] < END - 7 * DAY else [*t[:2], -1.0, *t[3:]] for t in trades]
    why = dr.list_checks(trades, "GPNSTOCK", END, 70.0)
    assert "last 7 days" in why


def test_windows_end_at_the_lists_last_candle_not_the_clock():
    """A pair measured a day behind: its 7 days end at ITS last candle."""
    assert dr.list_checks(_days(3, 3, 0, 0), "GPNSTOCK", END, 70.0) == ""


# ------------------------------------------------------------------ screen
CFG = {"on_winrate": 70.0}


def _row(rid, coin="GPNSTOCK", tp=1.5, sl=1.0, rt=0.22):
    return {"id": rid, "coin": coin, "tf": "15m", "signal": "willr14", "th": 0.0,
            "tp": tp, "sl": sl, "rt": rt, "winrate": 80.0, "trades": 90}


def test_screen_fails_the_fee_check_without_building_a_list():
    asked = []

    def lists_for(rows):
        asked.extend(r["id"] for r in rows)
        return {r["id"]: {"trades": _days(3, 3, 0, 0), "end_ms": END} for r in rows}
    passed, failed = dr.screen([_row("A"), _row("B", tp=1.0, sl=0.8)], CFG,
                               lists_for=lists_for)
    assert [r["id"] for r in passed] == ["A"]
    assert "B" in failed and "after fees" in failed["B"]
    assert asked == ["A"], "no list is built for a row the fee check already failed"


def test_screen_fails_a_row_with_no_trade_list():
    passed, failed = dr.screen([_row("A")], CFG, lists_for=lambda rows: {})
    assert passed == [] and "no trade list" in failed["A"]


def test_the_flag_is_the_since_time():
    assert dr.enabled({"daytime_rule": {"since": 1791360000}}) == 1791360000
    assert dr.enabled({}) is None and dr.enabled({"daytime_rule": {}}) is None


# --------------------------------------------- the watcher's daily pass
from tradingagents import auto_trader as at  # noqa: E402
from tradingagents import strategy_watcher as sw  # noqa: E402

NOW = 1_791_400_000.0      # Oct 07, 2026, after the pass hour


def _cand(rid, coin, tp, sl, rt=0.22, signal="macddiv"):
    return {"id": rid, "coin": coin, "tf": "1h", "signal": signal, "th": 0.0,
            "sl": sl, "tp": tp, "rt": rt, "trades": 90, "wins": 80, "losses": 10,
            "winrate": 88.89, "profit": 15.0, "gate": "ok",
            # the row's last bar is the list's last candle (one timeline)
            "measured_ms": END}


@pytest.fixture
def room(tmp_path, monkeypatch):
    w = {"settings": {"strategies": [], "strategy_coins": {}, "strategy_books": {},
                      "strategy_margins": {}, "strategy_sizing": {}, "enabled": False,
                      "daytime_rule": {"since": NOW - 60}},
         "cands": [], "lists": {}, "asked": []}
    monkeypatch.setattr(at, "STATE_DIR", tmp_path)
    from tradingagents import rolling30 as _r30

    _r30._MEMO.clear()
    monkeypatch.setattr(sw, "STATE", tmp_path / "w.json")
    monkeypatch.setattr(sw, "LOG", tmp_path / "w.jsonl")
    monkeypatch.setattr(at, "load_settings", lambda: sw._copy(w["settings"]))

    def _save(s):
        w["settings"] = s
        return []
    monkeypatch.setattr(at, "save_settings", _save)
    monkeypatch.setattr(sw, "_edge", lambda key, sym: {"verdict": "ok", "reason": "test"})
    monkeypatch.setattr(sw, "_candidates", lambda cfg, now: {"rows": list(w["cands"]),
                                                             "why": "fake"})
    monkeypatch.setattr(sw, "_fresh_row", lambda meta, now, cfg: (
        next((c for c in w["cands"] if c["id"] == meta["id"]), None), True))
    monkeypatch.setattr(sw, "_as_the_off_check_sees", lambda rows, now, cfg: rows)
    monkeypatch.setattr(sw, "_register", lambda key, spec, persist=True: "added")
    monkeypatch.setattr(sw, "_sig_of", lambda key: key.split("_")[0])
    monkeypatch.setattr(sw.time, "sleep", lambda s: None)
    monkeypatch.setattr(sw, "_delisted", lambda syms: set())

    def lists(rows):
        w["asked"] += [r["id"] for r in rows]
        return {r["id"]: w["lists"][r["id"]] for r in rows if r["id"] in w["lists"]}
    monkeypatch.setattr(sw, "_daytime_lists", lists)
    # no disk job unless a test says so (never this PC's own job state)
    from tradingagents import room_replay as _rr

    monkeypatch.setattr(_rr, "disk_job", lambda: "")
    from tradingagents import notifications as nt

    monkeypatch.setattr(nt, "record", lambda *a, **k: 1)
    sw.set_mode("act")
    st = sw._read()
    st.setdefault("cfg", {}).update({"on_winrate": 70.0, "off_winrate": 70.0,
                                     "min_trades": 50, "tp_rule": ">", "raw": True})
    sw._write(st)
    return w


GOOD = {"trades": _days(3, 3, 0, 0), "end_ms": END}
NIGHT = {"trades": _days(3, 1, 5, 5), "end_ms": END}


def test_the_pass_switches_on_only_what_passes_the_daytime_checks(room):
    room["cands"] = [_cand("AAAA1111", "GPNSTOCK", 1.5, 1.0),       # passes all
                     _cand("BBBB2222", "GPNSTOCK", 1.0, 0.8),       # fee fails
                     _cand("CCCC3333", "FWDISTOCK", 1.5, 1.0)]      # night winner
    room["lists"] = {"AAAA1111": GOOD, "CCCC3333": NIGHT}
    got = sw.consider(now=NOW)
    on = [d["id"] for d in got["decisions"] if d["action"] == "on"]
    assert on == ["AAAA1111"]
    assert "BBBB2222" not in room["asked"], "no list is built for a fee failure"
    assert "daytime" in (sw._read().get("last_candidates") or "")


def test_a_running_row_that_fails_is_switched_off_by_name(room):
    room["cands"] = [_cand("CCCC3333", "FWDISTOCK", 1.5, 1.0)]
    room["lists"] = {"CCCC3333": NIGHT}
    key = "macddiv_1h_sl1tp15"
    room["settings"]["strategy_coins"] = {key: ["FWDISTOCK_USDT"]}
    room["settings"]["strategy_books"] = {f"{key}|FWDISTOCK_USDT": ["paper"]}
    room["settings"]["watcher_slots"] = {f"{key}|FWDISTOCK_USDT": {
        "id": "CCCC3333", "coin": "FWDISTOCK", "tf": "1h", "signal": "macddiv",
        "tp": 1.5, "sl": 1.0, "on_at": NOW - 86_400}}
    got = sw.consider(now=NOW)
    offs = [d for d in got["decisions"] if d["action"] == "off" and d["id"] == "CCCC3333"]
    assert offs and "daytime rule" in offs[0]["why"] and "33.3%" in offs[0]["why"]
    assert room["settings"]["strategy_coins"][key] == []


def test_without_the_flag_nothing_changes(room):
    room["settings"].pop("daytime_rule")
    room["cands"] = [_cand("BBBB2222", "GPNSTOCK", 1.0, 0.8)]
    got = sw.consider(now=NOW)
    assert [d["id"] for d in got["decisions"] if d["action"] == "on"] == ["BBBB2222"]
    assert room["asked"] == []


# ------------------------------------- the runner never opens one after hours
import json as _json  # noqa: E402
import time as _time  # noqa: E402

import pandas as _pd  # noqa: E402

T_NIGHT = 1790812800        # Sep 30, 2026 8:00pm New York, on a 15-minute line
T_DAY = 1790863200          # Oct 01, 2026 10:00am New York


class _FX:
    def __init__(self, clock):
        self.clock, self.books = clock, 0

    def klines(self, symbol, interval, n):
        step = {"Min15": 900, "Min30": 1800, "Min60": 3600}.get(interval, 900)
        last = int(self.clock()) // step * step
        opens = [last - step * i for i in range(n)][::-1]
        return _pd.DataFrame({"Date": _pd.to_datetime(opens, unit="s"), "Open": 50.0,
                              "High": 50.0, "Low": 50.0, "Close": 50.0, "Volume": 10.0})

    def open_positions(self, symbol=None):
        return []

    def contract_spec(self, symbol):
        return {"priceScale": 4, "contractSize": 1, "volUnit": 1, "minVol": 1,
                "maxVol": 25000, "maintenanceMarginRate": 0.005}

    def last_price(self, symbol):
        return 50.0

    def funding_now(self, symbol):
        return {"per_day": 0.0003, "cycle_h": 8}

    def book_cost(self, symbol, notional_usd=200.0):
        self.books += 1
        return {"spread": 0.035, "slippage": 0.001, "book_exhausted": False}


class _Clock:
    def __init__(self, t):
        self.t = float(t)

    def __call__(self):
        return self.t


@pytest.fixture
def runner(tmp_path, monkeypatch):
    clock = _Clock(T_NIGHT + 10)
    monkeypatch.setattr(_time, "time", clock)
    monkeypatch.setattr(at, "LEDGER_PATH", tmp_path / "ledger.jsonl")
    for name in ("_GATE_CACHE", "_GATE_LOGGED", "_BAR_CACHE", "_FUNDING_CACHE"):
        monkeypatch.setattr(at, name, {}, raising=False)
    monkeypatch.setattr(at, "_MARKET_CLOSED", {}, raising=False)
    fx = _FX(clock)
    r = {"clock": clock, "fx": fx, "state": {}, "path": tmp_path / "ledger.jsonl"}

    def cycle(t, symbol="WIDESTOCK_USDT", key="fade15_15m", flag=True):
        clock.t = float(t)
        s = {"strategies": [key], "strategy_coins": {key: [symbol]},
             "strategy_margins": {key: 5.0}}
        if flag:
            s["daytime_rule"] = {"since": T_NIGHT - 3600}
        at.process_symbol(symbol, s, r["state"], fx=fx, dry=True)
    r["cycle"] = cycle

    def rows(action):
        if not r["path"].exists():
            return []
        return [x for x in (_json.loads(l) for l in r["path"].read_text().splitlines())
                if x.get("action") == action]
    r["rows"] = rows
    return r


def test_a_stock_token_is_not_traded_at_night(runner):
    runner["cycle"](T_NIGHT + 10)
    assert runner["fx"].books == 0, "no cost check, no order, outside market hours"
    got = runner["rows"]("market_closed")
    assert len(got) == 1 and got[0]["candles"] == 1 and "WIDESTOCK" in got[0]["coins"][0]
    assert not runner["rows"]("gate_blocked")


def test_the_same_candle_is_not_counted_twice_and_the_row_is_hourly(runner):
    runner["cycle"](T_NIGHT + 10)
    runner["cycle"](T_NIGHT + 70)          # same candle, next cycle
    runner["cycle"](T_NIGHT + 910)         # next 15-minute candle, same hour
    assert len(runner["rows"]("market_closed")) == 1
    runner["cycle"](T_NIGHT + 3610)        # an hour later
    got = runner["rows"]("market_closed")
    assert len(got) == 2 and got[1]["candles"] == 2, got


def test_in_market_hours_the_runner_checks_as_before(runner):
    runner["cycle"](T_DAY + 10)
    assert runner["fx"].books >= 1 and not runner["rows"]("market_closed")


def test_crypto_is_traded_at_night(runner):
    runner["cycle"](T_NIGHT + 10, symbol="WIDE_USDT")
    assert runner["fx"].books >= 1 and not runner["rows"]("market_closed")


def test_without_the_flag_a_stock_token_trades_at_night_as_before(runner):
    runner["cycle"](T_NIGHT + 10, flag=False)
    assert runner["fx"].books >= 1 and not runner["rows"]("market_closed")


# -------------------------------------------- Backtest a room follows it
def test_the_replay_masks_a_stock_token_entry_after_hours_from_the_rules_start():
    from tradingagents import room_replay as rr

    since = T_NIGHT - 3600
    night_ms = (T_NIGHT + 900) * 1000
    day_ms = T_DAY * 1000
    assert rr._daytime_masks("WIDESTOCK", night_ms, since)
    assert not rr._daytime_masks("WIDESTOCK", day_ms, since)
    assert not rr._daytime_masks("WIDE", night_ms, since), "crypto trades all night"
    assert not rr._daytime_masks("WIDESTOCK", (since - 7200) * 1000, since), \
        "before the rule was switched on, the room traded nights"
    assert not rr._daytime_masks("WIDESTOCK", night_ms, None)


def test_the_room_rebuild_applies_the_mask():
    import inspect

    from tradingagents import room_replay as rr

    assert "_daytime_masks(" in inspect.getsource(rr.room_lists)
    assert "daytime_since" in inspect.getsource(rr.room_follow)


# ================================================== the final review's fixes
# Critical #1: a running row whose list could not be built is KEPT (an
# unreadable file keeps a running row, CLAUDE.md), never switched off.
def _running(room, rid, coin, key="macddiv_1h_sl1tp15", books=("paper",), real=False):
    slot = f"{key}|{coin}_USDT"
    room["settings"]["strategy_coins"] = {key: [f"{coin}_USDT"]}
    room["settings"]["strategy_books"] = {slot: list(books)}
    room["settings"]["watcher_slots"] = {slot: {
        "id": rid, "coin": coin, "tf": "1h", "signal": "macddiv", "tp": 1.5, "sl": 1.0,
        "on_at": NOW - 86_400, "real": real}}
    return key, slot


def test_a_running_row_with_no_list_is_kept_and_named(room):
    room["cands"] = [_cand("CCCC3333", "FWDISTOCK", 1.5, 1.0)]
    room["lists"] = {}                                  # the build failed
    key, _slot = _running(room, "CCCC3333", "FWDISTOCK")
    got = sw.consider(now=NOW)
    assert not [d for d in got["decisions"] if d["action"] == "off"]
    assert room["settings"]["strategy_coins"][key] == ["FWDISTOCK_USDT"]
    assert sw._read()["daytime"]["unread"] == 1


# Important #2: a list that ends a day or more before its row's own last bar
# reads old days — unread, never a switch-on or a switch-off
def test_a_stale_list_neither_switches_on_nor_off(room):
    stale = {"trades": _days(3, 1, 5, 5), "end_ms": END}       # would FAIL
    room["cands"] = [{**_cand("CCCC3333", "FWDISTOCK", 1.5, 1.0),
                      "measured_ms": END + 3 * DAY}]
    room["lists"] = {"CCCC3333": stale}
    key, _slot = _running(room, "CCCC3333", "FWDISTOCK")
    got = sw.consider(now=NOW)
    assert not [d for d in got["decisions"] if d["action"] == "off"]
    assert sw._read()["daytime"]["unread"] == 1


def test_the_lists_are_built_after_the_prices_are_brought_up(monkeypatch):
    from tradingagents import room_replay as rr

    calls = []
    monkeypatch.setattr(rr, "refresh_prices", lambda coins, end_ms, store=None, now=None:
                        calls.append(("prices", sorted(coins))) or {})
    monkeypatch.setattr(rr, "build_lists", lambda cands, store=None, workers=None, **k:
                        (calls.append(("lists", workers)) or {}, {}))
    sw._daytime_lists_real([_cand("AAAA1111", "GPNSTOCK", 1.5, 1.0)], now=NOW)
    assert calls[0] == ("prices", ["GPNSTOCK"]) and calls[1] == ("lists", 2)


# Important #3: US-listed ETF tokens follow US hours like stock tokens
def test_us_etf_tokens_keep_us_hours_and_index_tokens_do_not():
    for name in ("VUG_USDT", "SPY", "IGV", "TQQQ_USDT", "GLD"):
        assert dr.us_hours(name), name
    for name in ("NAS100", "SPX500_USDT", "US30", "BB_USDT", "ZINC"):
        assert not dr.us_hours(name), name
    assert dr.us_hours("GPNSTOCK_USDT")


def test_the_runner_skips_vug_at_night(runner):
    runner["cycle"](T_NIGHT + 10, symbol="VUG_USDT")
    assert runner["fx"].books == 0 and runner["rows"]("market_closed")


def test_the_replay_masks_vug_at_night():
    from tradingagents import room_replay as rr

    assert rr._daytime_masks("VUG", (T_NIGHT + 900) * 1000, T_NIGHT - 3600)


# Important #4: the daytime switch-off keeps the off pass's two protections
def test_the_daytime_rule_never_takes_your_own_real_money_off(room):
    room["cands"] = [_cand("CCCC3333", "FWDISTOCK", 1.5, 1.0)]
    room["lists"] = {"CCCC3333": NIGHT}
    key, slot = _running(room, "CCCC3333", "FWDISTOCK", books=("paper", "real"), real=False)
    got = sw.consider(now=NOW)
    assert not [d for d in got["decisions"] if d["action"] == "off"]
    assert room["settings"]["strategy_books"][slot] == ["paper", "real"]


def test_a_row_you_switched_off_yourself_is_not_logged_off_again(room):
    room["cands"] = [_cand("CCCC3333", "FWDISTOCK", 1.5, 1.0)]
    room["lists"] = {"CCCC3333": NIGHT}
    key, _slot = _running(room, "CCCC3333", "FWDISTOCK")
    room["settings"]["strategy_coins"][key] = []           # you switched it off
    got = sw.consider(now=NOW)
    assert not [d for d in got["decisions"]
                if d["action"] == "off" and "daytime" in d["why"]]


# Important #5: the market_closed count survives a runner restart, the row
# names no single coin for the whole count, and every coin is counted
def test_the_market_closed_count_survives_a_restart(runner, monkeypatch, tmp_path):
    monkeypatch.setattr(at, "STATE_DIR", tmp_path)
    runner["cycle"](T_NIGHT + 10)                      # first row
    runner["cycle"](T_NIGHT + 910)                     # counted, no row
    at._MARKET_CLOSED.clear()                          # the runner is killed
    runner["cycle"](T_NIGHT + 1810)                    # counted after restart
    runner["cycle"](T_NIGHT + 3610)                    # an hour on: the row
    got = runner["rows"]("market_closed")
    assert len(got) == 2 and got[1]["candles"] == 3, got
    assert got[1]["symbol"] == "" and got[1]["coins_total"] == 1


# Important #6: the pass waits for a disk job instead of competing with it
def test_the_daytime_pass_waits_for_a_disk_job(room, monkeypatch):
    from tradingagents import room_replay as rr

    monkeypatch.setattr(rr, "disk_job", lambda: "a candle download (40%)")
    room["cands"] = [_cand("AAAA1111", "GPNSTOCK", 1.5, 1.0)]
    room["lists"] = {"AAAA1111": GOOD}
    got = sw.consider(now=NOW)
    assert not [d for d in got["decisions"] if d["action"] == "on"]
    assert room["asked"] == []


# Minor: per-check counts are kept for the screen
def test_the_pass_keeps_a_count_per_check(room):
    room["cands"] = [_cand("AAAA1111", "GPNSTOCK", 1.5, 1.0),
                     _cand("BBBB2222", "GPNSTOCK", 1.0, 0.8),
                     _cand("CCCC3333", "FWDISTOCK", 1.5, 1.0)]
    room["lists"] = {"AAAA1111": GOOD, "CCCC3333": NIGHT}
    sw.consider(now=NOW)
    d = sw._read()["daytime"]
    assert d["passed"] == 1 and d["checks"]["fee"] == 1 and d["checks"]["daytime record"] == 1


def test_mexcs_own_label_decides_which_tokens_keep_us_hours(monkeypatch):
    """The first preview passed XLI (a US industrials fund) as crypto because
    the hand list missed it. MEXC labels every one: read Oct 07, 2026."""
    from tradingagents.dataflows import mexc_futures as fx

    plates = {"XLI_USDT": ["mc-trade-zone-Stock", "mc-trade-zone-tradfi", "mc-trade-zone-ETF",
                           "mc-trade-zone-stockindex"],
              "NAS100_USDT": ["mc-trade-zone-Stock", "mc-trade-zone-tradfi",
                              "mc-trade-zone-stockindex"],
              "BB_USDT": ["mc-trade-zone-mainly"],
              "ZINC_USDT": ["mc-trade-zone-tradfi"]}
    monkeypatch.setattr(dr, "_PLATES", {})
    monkeypatch.setattr(dr, "_PLATES_FAILED", {})
    monkeypatch.setattr(fx, "contract_spec", lambda sym: {"conceptPlate": plates[sym]})
    assert dr.us_hours("XLI_USDT")
    assert not dr.us_hours("NAS100") and not dr.us_hours("BB") and not dr.us_hours("ZINC")


def test_an_unreadable_label_falls_back_to_the_list_and_is_not_asked_every_call(monkeypatch):
    from tradingagents.dataflows import mexc_futures as fx

    asks = []

    def boom(sym):
        asks.append(sym)
        raise RuntimeError("code 510")
    monkeypatch.setattr(dr, "_PLATES", {})
    monkeypatch.setattr(dr, "_PLATES_FAILED", {})
    monkeypatch.setattr(fx, "contract_spec", boom)
    assert dr.us_hours("VUG") and not dr.us_hours("NAS100")
    assert dr.us_hours("VUG")
    assert asks.count("VUG_USDT") == 1, "a failed ask waits PLATES_RETRY_S"
