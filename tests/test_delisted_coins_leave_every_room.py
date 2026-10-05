"""A coin MEXC drops is switched off in EVERY room, not only Main.

RCA-2026-10-05-A: SUPRA_USDT left MEXC by Oct 04, 2026 3:15am; five practice
strategies stayed on for it in #55D32617 and #4FC03172 and failed 1,924 times
in 21 hours. The delisted cleanup called `disarm_coins` once, under whatever
room was current — Main — so no room's own settings were ever touched.
"""
from __future__ import annotations

from tradingagents import auto_trader as at
from tradingagents import profiles
from tradingagents import storage_months as sm


def test_the_delisted_cleanup_disarms_the_coin_in_every_room(monkeypatch):
    seen = []
    monkeypatch.setattr(sm, "delisted_report", lambda *a, **k: {
        "known": True, "coins": [{"coin": "SUPRA", "symbol": "SUPRA_USDT"}]})
    monkeypatch.setattr(sm, "_pairs_by_coin", lambda *a, **k: [])
    monkeypatch.setattr(sm, "_drop_pairs", lambda *a, **k: True)
    for name in ("_remove_coin_candles", "_drop_pair_files", "_forget_lost",
                 "_refresh_candle_index"):
        monkeypatch.setattr(sm, name, lambda *a, **k: None)

    def disarm(symbols, why="delisted"):
        seen.append((profiles.current(), set(symbols), why))
        return {"removed": {"SUPRA_USDT": ["vwaprev_15m_sl1tp12"]}, "rows": 1}

    monkeypatch.setattr(at, "disarm_coins", disarm)
    job = {"errors": [], "done": 0}
    sm._run_delisted(job, lambda: None)
    assert [r for r, _s, _w in seen] == profiles.ids(), "every room, retired ones too"
    assert all(s == {"SUPRA_USDT"} and w == "delisted" for _r, s, w in seen)
    assert set(job["disarmed"]) == set(profiles.ids()) and not job["errors"]
    assert f"in {len(profiles.ids())} room(s)" in job["phase"]
