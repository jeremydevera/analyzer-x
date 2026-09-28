"""Collecting a watcher replay: merged once, cut to one common end.

Operator, Sep 28, 2026: "Then do the backtest replay so i know the pnl for
every day". Twenty machines each measured their own coins at their own
moment; a coin measured an hour later must not see an hour further.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from tradingagents import replay_collect as rc

H = 3_600_000


def _ms(y, m, d, h=0):
    return int(dt.datetime(y, m, d, h).timestamp() * 1000)


def _combo(cid, coin, n, start):
    trades = [[start + i * 24 * H, start + i * 24 * H + 2 * H, 0.8, 1]
              for i in range(n)]
    return {"id": cid, "coin": coin, "tf": "1h", "signal": "macddiv", "th": 0.0,
            "sl": 0.7, "tp": 1.0, "gate": "ok", "trades": trades}


def _machine(folder, n, combos, spans, tested):
    d = folder / f"replay-{n}"
    d.mkdir()
    with open(d / f"replay-{n}.jsonl", "w", encoding="utf-8") as fh:
        for c in combos:
            fh.write(json.dumps(c) + "\n")
    (d / f"replay-report-{n}.json").write_text(json.dumps({
        "start": "2026-09-01", "tz": "America/New_York", "cfg": {},
        "coins_board": 900, "coins_done": 2, "pairs": 10, "tested": tested,
        "kept": len(combos), "failed": {}, "short": [], "spans": spans}))


def test_two_machines_merge_and_one_id_seen_twice_is_kept_once(tmp_path):
    a = _combo("GOOD0001", "GPNSTOCK", 40, _ms(2026, 8, 3, 5))
    _machine(tmp_path, 0, [a], {"GPNSTOCK 1h": [0, _ms(2026, 9, 28, 14)]}, 7000)
    _machine(tmp_path, 1, [a], {"KKRSTOCK 1h": [0, _ms(2026, 9, 28, 15)]}, 5000)
    got = rc.merge(str(tmp_path))
    assert len(got["combos"]) == 1
    assert got["totals"]["tested"] == 12_000 and got["totals"]["machines"] == 2


def test_the_common_end_is_the_earliest_last_bar():
    assert rc.common_end({"A 1h": [0, 5], "B 1h": [0, 3]}) == 3
    assert rc.common_end({}) is None


def test_the_daily_frame_does_not_pull_the_end_back_a_day():
    """Run 36478015729: every 1d pair ended Sep 27, 2026 8:00pm (its last
    closed day) while the intraday ones reached Sep 28 afternoon."""
    daily = _ms(2026, 9, 27, 20)
    intraday = _ms(2026, 9, 28, 16)
    spans = {"GPNSTOCK 1d": [0, daily], "GPNSTOCK 15m": [0, intraday],
             "KKRSTOCK 1h": [0, intraday + 3_600_000]}
    assert rc.common_end(spans) == intraday
    assert rc.common_end({"GPNSTOCK 1d": [0, daily]}) == daily


def test_after_the_common_end_a_close_becomes_open_and_a_new_entry_vanishes():
    end = _ms(2026, 9, 28, 12)
    c = {"id": "x", "trades": [[end - 3 * H, end - H, 0.8, 1],
                               [end - H, end + H, 0.8, 1],
                               [end + H, end + 2 * H, 0.8, 1]]}
    got = rc.cut([c], end)[0]["trades"]
    assert got == [[end - 3 * H, end - H, 0.8, 1], [end - H, end + H, 0.0, 0]]


def test_the_replay_end_to_end_books_every_day(tmp_path):
    a = _combo("GOOD0001", "GPNSTOCK", 50, _ms(2026, 8, 3, 5))
    _machine(tmp_path, 0, [a], {"GPNSTOCK 1h": [0, _ms(2026, 9, 10, 12)]}, 7000)
    res = rc.replay(str(tmp_path), run_id="1", repo="o/r")
    assert res["totals"]["tested"] == 7000 and res["combos_written"] == 1
    assert res["days"][0]["day"] == "2026-09-01" and len(res["days"]) == 10
    assert res["summary"]["profit"] == pytest.approx(sum(d["pnl"] for d in res["days"]))
    assert res["slots"][0]["id"] == "GOOD0001"


def test_nothing_measured_is_an_error_never_an_empty_replay(tmp_path):
    with pytest.raises(RuntimeError):
        rc.replay(str(tmp_path))


def test_the_download_lands_beside_the_store_not_on_c():
    import inspect

    src = inspect.getsource(rc.fetch)
    assert "dir=cs._scratch()" in src and 'prefix=f"tmp' in src
