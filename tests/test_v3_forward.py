"""The forward-tested v3 strategies, followed from the day they were chosen (Nov 05, 2026)."""
import json

from tradingagents import v3_forward as vfw

H = 3_600_000


def _row(key, setting, prof, rid="A"):
    return {"id": rid, "_key": key, "_set": setting, "_prof": prof}


def test_the_list_is_the_pages_rule():
    k = ("MOVR_USDT", "v3_trend", "4h", "none")
    a = [_row(k, "n20", False, "X1"),
         _row(("KAS_USDT", "v3_trend", "4h", "none"), "n50", True, "X2"),
         _row(("ORCA_USDT", "v3_snap", "4h", "btc_mood"), "k2", True, "X3")]
    b = [_row(k, "n20", True),                                           # won 2025, same setting
         _row(("KAS_USDT", "v3_trend", "4h", "none"), "n20", True),     # another setting
         _row(("ORCA_USDT", "v3_snap", "4h", "btc_mood"), "k2", False)]  # lost 2025
    got = vfw.picks(a, b)
    assert [x["id"] for x in got] == ["X1"]
    assert got[0] == {"id": "X1", "coin": "MOVR_USDT", "family": "v3_trend", "tf": "4h",
                      "filter": "none", "setting": "n20"}


def _trade(entry_ms, why="TRAIL", pnl=1.0, exit_ms=None):
    return {"side": "long", "entry_ms": entry_ms, "entry": 1.0, "exit_ms": exit_ms or entry_ms + H,
            "exit": 1.01, "why": why, "pnl": pnl, "leverage": 20, "notional": 100.0,
            "measured_exit": True}


def test_only_trades_opened_after_the_start_count_and_an_open_one_is_never_a_result():
    since = 100 * H
    seen = {}

    def run(body, fx=None, plan=None, now_ms=None):
        seen.update(body, now_ms=now_ms)
        return {"trades": [_trade(since - 5 * H, pnl=-3.0),            # before the start
                           _trade(since + H, pnl=2.0),                 # after, closed
                           _trade(since + 9 * H, why="END", pnl=-0.4)],  # after, still open
                "provenance": {"end_ms": since + 10 * H}}

    x = {"id": "X1", "coin": "MOVR_USDT", "family": "v3_trend", "tf": "4h", "filter": "none",
         "setting": "n20"}
    got = vfw.follow(x, {}, since, since + 10 * H, run=run)
    assert [t["pnl"] for t in got["closed"]] == [2.0]
    assert [t["pnl"] for t in got["open"]] == [-0.4]
    assert got["carried"] == 0
    assert seen["risk_usd"] == 5.0 and seen["setting"] == "n20" and seen["now_ms"] == since + 10 * H
    assert seen["days"] >= 30


def test_a_trade_from_before_the_start_still_open_is_counted_as_carried():
    since = 100 * H

    def run(body, fx=None, plan=None, now_ms=None):
        return {"trades": [_trade(since - 5 * H, why="END", pnl=1.0)],
                "provenance": {"end_ms": since + 10 * H}}

    got = vfw.follow({"id": "X", "coin": "A", "family": "v3_trend", "tf": "4h", "filter": "none",
                      "setting": "n20"}, {}, since, since + 10 * H, run=run)
    assert got["closed"] == [] and got["open"] == [] and got["carried"] == 1


def test_the_window_always_holds_thirty_days_before_the_start():
    day = 86_400_000
    assert vfw.window_days(0, 1 * day) == 60       # 31 days needed -> 60
    assert vfw.window_days(0, 0) == 30
    assert vfw.window_days(0, 100 * day) == 180
    assert vfw.window_days(0, 2000 * day) == 365   # the longest the tab offers


def test_a_pass_names_a_coin_that_fails_twice_and_keeps_the_others(tmp_path, monkeypatch):
    monkeypatch.setattr(vfw, "home", lambda: tmp_path)
    since = 100 * H
    calls = []

    def run(body, fx=None, plan=None, now_ms=None):
        calls.append(body["sym"])
        if body["sym"] == "BAD_USDT":
            raise RuntimeError("klines returned 0 bars")
        if body["sym"] == "FLAKY_USDT" and calls.count("FLAKY_USDT") == 1:
            raise TimeoutError("cut")
        return {"trades": [_trade(since + H, pnl=2.0 if body["sym"] == "GOOD_USDT" else -1.0)],
                "provenance": {"end_ms": since + 10 * H}}

    roster = {"since_ms": since, "strategies": [
        {"id": i, "coin": c, "family": "v3_trend", "tf": "4h", "filter": "none", "setting": "n20"}
        for i, c in (("G", "GOOD_USDT"), ("B", "BAD_USDT"), ("F", "FLAKY_USDT"))]}
    st = vfw.run_pass(since + 10 * H, roster=roster, plan={}, run=run, log=lambda *_: None)
    assert calls.count("BAD_USDT") == 2 and calls.count("FLAKY_USDT") == 2
    assert st["failed"] == ["BAD_USDT 4h v3_trend: RuntimeError: klines returned 0 bars"]
    assert [r["coin"] for r in st["rows"]] == ["GOOD_USDT", "FLAKY_USDT"]
    s = st["summary"]
    assert (s["trades"], s["wins"], s["losses"], s["profit"]) == (2, 1, 1, 1.0)
    assert json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))["listed"] == 3


def test_a_failed_read_keeps_the_last_pass_trades_marked_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(vfw, "home", lambda: tmp_path)
    since = 100 * H
    roster = {"since_ms": since, "strategies": [
        {"id": "G", "coin": "GOOD_USDT", "family": "v3_trend", "tf": "4h", "filter": "none",
         "setting": "n20"}]}

    def ok(body, fx=None, plan=None, now_ms=None):
        return {"trades": [_trade(since + H, pnl=2.0)], "provenance": {"end_ms": now_ms}}

    def down(body, fx=None, plan=None, now_ms=None):
        raise ConnectionError("no internet")

    vfw.run_pass(since + 10 * H, roster=roster, plan={}, run=ok, log=lambda *_: None)
    st = vfw.run_pass(since + 20 * H, roster=roster, plan={}, run=down, log=lambda *_: None)
    assert st["rows"][0]["stale"] is True
    assert st["summary"]["trades"] == 1 and st["summary"]["profit"] == 2.0
    assert st["failed"] == ["GOOD_USDT 4h v3_trend: ConnectionError: no internet"]


def test_the_summary_adds_up_and_walks_the_worst_run_in_closing_order():
    rows = [{"closed": [_trade(1, pnl=-1.0, exit_ms=10), _trade(2, pnl=3.0, exit_ms=40)], "open": []},
            {"closed": [_trade(3, pnl=-2.0, exit_ms=20)], "open": [_trade(4, why="END", pnl=0.5)],
             "carried": 1}]
    s = vfw.summary(rows)
    assert (s["trades"], s["wins"], s["losses"], s["profit"]) == (3, 1, 2, 0.0)
    assert (s["worst_run_usd"], s["worst_run_trades"]) == (-3.0, 2)    # -1 then -2, before +3
    assert (s["open"], s["open_pnl"], s["carried"]) == (1, 0.5, 1)
    assert s["in_profit"] == 1


def test_a_pass_runs_once_an_hour_ten_minutes_past():
    hr = 3600
    assert vfw.due(10 * hr + 700, None)
    assert vfw.due(10 * hr + 600, 9 * hr + 900)          # 10:10 is the slot
    assert not vfw.due(10 * hr + 500, 9 * hr + 900)      # 10:08: the 9:10 slot is done
    assert not vfw.due(10 * hr + 900, 10 * hr + 650)     # already ran this hour
    assert vfw.due(14 * hr + 700, 10 * hr + 650)         # after a gap: due at once


def test_the_supervisor_tick_never_runs_under_pytest():
    assert vfw.tick() is None


def test_the_mood_is_worked_out_again_to_today(monkeypatch, tmp_path):
    from tradingagents import v3_universe as vu

    day = vu.DAY_MS
    plan = {"start_ms": 100 * day, "end_ms": 150 * day, "mood": {"t": [1], "up": [1]}}
    pf = tmp_path / "plan.json"
    pf.write_text(json.dumps(plan), encoding="utf-8")
    monkeypatch.setattr(vu, "load", lambda p: json.loads(open(p, encoding="utf-8").read()))

    class FX:
        @staticmethod
        def klines(sym, interval, count):
            import pandas as pd

            n = 200
            t = pd.to_datetime([(k * day) for k in range(n)], unit="ms")
            c = [100.0 + k for k in range(n)]
            return pd.DataFrame({"Date": t, "Open": c, "High": c, "Low": c, "Close": c,
                                 "Volume": [1.0] * n})

    got = vfw.plan_now(199 * day + 5, fx=FX, plan_file=pf)
    assert got["mood"]["t"][-1] == 199 * day          # the last daily close before now
    assert got["mood"]["up"][-1] == 1                 # a rising BTC is "up"
