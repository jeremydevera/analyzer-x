"""The ids SAVED while the exchange was hashed into them are rewritten, once.

Oct 10 - 13, 2026: `row_code` hashed `|venue=gate` into every id, so every
strategy got a new one. The operator: *"i dont understand why did you changed
the ids just because i switched to gate"*, then *"yes"* to taking it out, and
*"just to be clear i dont need the mexc results anymore"*. The ids are plain
again; what the app SAVED in those three days — a room's switched-on rows,
its cooling marks, its decisions, Forecast v2's streaks — is rewritten to the
plain id the screens now print, so the watcher still knows what it switched
on and the operator's search finds what the page shows.

Every fixture here sits on ONE timeline: the switch at SINCE, a MEXC mark a
day before it, a Gate mark an hour after it.
"""
import json

import numpy as np
import pytest

from tradingagents import ids_without_exchange as iwe

SINCE = 1_791_619_184.0
BEFORE = SINCE - 86_400
AFTER = SINCE + 3_600
# measured against the code as it was on Oct 13, 2026 (commit 5d60a33)
BTC = ("BTC", "1h", "trend50", 0.3, 0.4)        # Gate #76GWV3UK, plain #4EVLXP67
FAST = ("FASTSTOCK", "15m", "prank", 1.2, 1.5)  # Gate #68BZF2L9, plain #2WCGB7VB


def test_a_gate_era_id_is_proved_before_it_is_rewritten():
    assert iwe.gate_code("BTC", "1h", "trend50", 0, 0.3, 0.4, "flat", res="1m") == "76GWV3UK"
    assert iwe.plain_for("76GWV3UK", *BTC) == "4EVLXP67"
    assert iwe.plain_for("68BZF2L9", *FAST) == "2WCGB7VB"
    assert iwe.plain_for("68BZF2L9", "FASTSTOCK_USDT", "15m", "prank", 1.2, 1.5) == "2WCGB7VB"
    # the wrong combination proves nothing
    assert iwe.plain_for("76GWV3UK", "ETH", "1h", "trend50", 0.3, 0.4) is None
    # a barrier the record cannot read proves nothing, and never raises
    assert iwe.plain_for("76GWV3UK", "BTC", "1h", "trend50", "", None) is None


def test_a_threshold_signal_is_found_without_its_threshold():
    """The decisions log keeps no threshold, so a mom6 row is tried across
    the grid's thresholds — and only the one that hashes to it is taken."""
    from tradingagents import backtest_report as br

    th = sorted(br.THRESHOLDS["15m"])[-1]
    old = iwe.gate_code("PEPE", "15m", "mom6", th, 0.5, 1.0, "flat", res="1m")
    assert iwe.plain_for(old, "PEPE", "15m", "mom6", 0.5, 1.0) == \
        br.row_code("PEPE", "15m", "mom6", th, 0.5, 1.0, "flat", res="1m")


def _home(tmp_path):
    room = tmp_path / "profiles" / "55D32617"
    room.mkdir(parents=True)
    old_btc, old_fast = "76GWV3UK", "68BZF2L9"
    (room / "strategy_watcher.json").write_text(json.dumps({
        "mode": "act",
        # a MEXC switch-off from before the move, and a Gate one after it
        "cooling": {"LG9NSU4B": BEFORE, old_fast: AFTER},
        "reported": {old_btc: "2026-10-12"}}), encoding="utf-8")
    log = [
        {"at": BEFORE, "action": "off", "id": "LG9NSU4B", "coin": "XPIN", "tf": "1h",
         "signal": "ote", "tp": 1.0, "sl": 3.0, "why": "#LG9NSU4B XPIN 1h ote — MEXC"},
        {"at": AFTER, "action": "on", "id": old_btc, "coin": "BTC", "tf": "1h",
         "signal": "trend50", "tp": 0.4, "sl": 0.3, "why": f"#{old_btc} BTC 1h trend50 — on"},
        {"at": AFTER, "action": "off", "id": old_fast, "coin": "FASTSTOCK", "tf": "15m",
         "signal": "prank", "tp": 1.5, "sl": 1.2, "why": f"#{old_fast} FASTSTOCK 15m prank — off"},
    ]
    (room / "strategy_watcher.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in log), encoding="utf-8")
    (room / "auto_trade.json").write_text(json.dumps({"watcher_slots": {
        "trend50_1h_sl03tp04|BTC_USDT": {"id": old_btc, "coin": "BTC", "tf": "1h",
                                         "signal": "trend50", "th": 0.0, "sl": 0.3,
                                         "tp": 0.4, "real": False}}}), encoding="utf-8")
    f2 = tmp_path / "forecast_v2"
    f2.mkdir()
    np.savez_compressed(f2 / "streaks.npz", id=np.array([old_btc.encode()], dtype="S8"),
                        coin=np.array([0], dtype="int32"), coin_names=np.array(["BTC"]),
                        tf=np.array([0], dtype="int32"), tf_names=np.array(["1h"]),
                        signal=np.array([0], dtype="int32"), signal_names=np.array(["trend50"]),
                        th=np.array([0.0], dtype="float32"), tp=np.array([0.4], dtype="float32"),
                        sl=np.array([0.3], dtype="float32"), length=np.array([9], dtype="int32"))
    return room


def test_every_saved_id_of_the_three_days_is_rewritten_once(tmp_path):
    room = _home(tmp_path)
    got = iwe.migrate(home=tmp_path, since=SINCE)
    assert got["mapped"] >= 2 and not got["failed"]

    st = json.loads((room / "strategy_watcher.json").read_text(encoding="utf-8"))
    # the MEXC mark is dropped: it never held a Gate row back, and must not start now
    assert st["cooling"] == {"2WCGB7VB": AFTER}
    assert st["reported"] == {"4EVLXP67": "2026-10-12"}
    assert st["mode"] == "act"

    log = [json.loads(x) for x in
           (room / "strategy_watcher.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [e["id"] for e in log] == ["LG9NSU4B", "4EVLXP67", "2WCGB7VB"]
    assert log[1]["why"].startswith("#4EVLXP67 BTC") and log[2]["why"].startswith("#2WCGB7VB")

    s = json.loads((room / "auto_trade.json").read_text(encoding="utf-8"))
    assert s["watcher_slots"]["trend50_1h_sl03tp04|BTC_USDT"]["id"] == "4EVLXP67"

    z = np.load(tmp_path / "forecast_v2" / "streaks.npz")
    assert [x.decode() for x in z["id"]] == ["4EVLXP67"]
    assert list(z["length"]) == [9], "every other column is kept"

    assert (tmp_path / iwe.MARK_NAME).exists()
    before = {p: p.read_bytes() for p in room.iterdir()}
    assert iwe.migrate(home=tmp_path, since=SINCE)["skipped"]
    assert {p: p.read_bytes() for p in room.iterdir()} == before


def test_an_id_that_cannot_be_proved_is_left_alone(tmp_path):
    room = tmp_path / "profiles" / "6B08FF64"
    room.mkdir(parents=True)
    line = {"at": AFTER, "action": "off", "id": "76GWV3UK", "coin": "ETH", "tf": "1h",
            "signal": "trend50", "tp": 0.4, "sl": 0.3, "why": "#76GWV3UK"}
    (room / "strategy_watcher.jsonl").write_text(json.dumps(line) + "\n", encoding="utf-8")
    iwe.migrate(home=tmp_path, since=SINCE)
    assert json.loads((room / "strategy_watcher.jsonl").read_text(encoding="utf-8"))["id"] \
        == "76GWV3UK"


def test_a_failed_file_leaves_no_mark_so_the_next_start_tries_again(tmp_path, monkeypatch):
    _home(tmp_path)

    def boom(*a, **k):
        raise PermissionError("held open")

    monkeypatch.setattr(iwe, "_replace", boom)
    got = iwe.migrate(home=tmp_path, since=SINCE)
    assert got["failed"]
    assert not (tmp_path / iwe.MARK_NAME).exists()


def test_never_on_the_real_home_from_a_test():
    got = iwe.migrate()
    assert got["skipped"] and "pytest" in got["skipped"]


def test_the_api_rewrites_before_the_watcher_thread_starts():
    """The watcher runs inside the API and reads `cooling` and the
    switched-on ids on every pass: the rewrite is the FIRST startup step."""
    from tradingagents import api

    names = [f.__name__ for f in api.app.router.on_startup]
    assert names.index("_ids_lose_the_exchange") < names.index("_keep_the_row_index_current")


@pytest.mark.parametrize("since", [0.0, None])
def test_an_app_that_never_switched_has_nothing_to_rewrite(tmp_path, since, monkeypatch):
    from tradingagents import venue

    monkeypatch.setattr(venue, "since", lambda: 0.0)
    got = iwe.migrate(home=tmp_path, since=since)
    assert got["mapped"] == 0 and (tmp_path / iwe.MARK_NAME).exists()


def test_the_room_strategies_retest_names_its_strategies_by_the_plain_id(tmp_path):
    """`room_strategies_now.npz` lists each traded strategy as
    [id, coin, tf, signal, th, TP, SL] — the Room strategies trade log
    prints that id. The trades and every other field are kept."""
    out = tmp_path / "backtest" / "forecast_v2"
    out.mkdir(parents=True)
    meta = {"made_at": AFTER, "ids": ["11823416"],
            "strategies": [["76GWV3UK", "BTC", "1h", "trend50", 0.0, 0.4, 0.3],
                           ["ZZZZZZZZ", "ETH", "1h", "trend50", 0.0, 0.4, 0.3]]}
    np.savez(out / "room_strategies_now.npz", e=np.array([1], dtype="int32"),
             s=np.array([0], dtype="int32"), meta=np.array(json.dumps(meta)))
    iwe.migrate(home=tmp_path, since=SINCE)
    z = np.load(out / "room_strategies_now.npz")
    got = json.loads(str(z["meta"]))
    assert [r[0] for r in got["strategies"]] == ["4EVLXP67", "ZZZZZZZZ"]
    assert got["ids"] == ["11823416"] and list(z["e"]) == [1] and list(z["s"]) == [0]
