"""The operator can make the index catch up, without waiting hours.

Measured 2026-08-26 while a 1,994-pair sweep ran: 973 coins had measured rows
on disk and the strategy list offered 711, because the indexer trickles ONE
pair per cycle while a backtest is running (rows_index.TRICKLE_PAIRS) — 1,094
pairs behind, about three hours away. The data was there; only the index was
starved, and nothing on the screen could ask it to hurry.
"""
import pytest

from tradingagents import api, rows_index as ri


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(ri, "_machine_is_busy", lambda: True)
    ri._syncing.clear()
    yield
    ri._syncing.clear()


def test_the_route_forces_a_sync_even_while_a_sweep_runs(monkeypatch):
    calls = []
    monkeypatch.setattr(ri, "sync_in_background",
                        lambda budget_s=0.0, force=False: calls.append((budget_s, force)) or True)
    monkeypatch.setattr(ri, "status", lambda: {"behind": 1094, "pairs_indexed": 2612,
                                               "pairs_on_disk": 3706, "syncing": False})
    got = api.strategies_reindex()
    assert got["started"] is True
    assert got["behind"] == 1094
    assert calls and calls[0][1] is True, "force=True, or the trickle guard refuses it"


def test_a_second_click_does_not_start_a_second_sync(monkeypatch):
    monkeypatch.setattr(ri, "sync_in_background", lambda budget_s=0.0, force=False: False)
    monkeypatch.setattr(ri, "status", lambda: {"behind": 12, "syncing": True})
    got = api.strategies_reindex()
    assert got["started"] is False
    assert "already" in got["why"].lower()


def test_nothing_to_do_says_so(monkeypatch):
    monkeypatch.setattr(ri, "status", lambda: {"behind": 0, "syncing": False})
    monkeypatch.setattr(ri, "sync_in_background",
                        lambda budget_s=0.0, force=False: pytest.fail("nothing to index"))
    got = api.strategies_reindex()
    assert got["started"] is False and got["behind"] == 0
    assert "up to date" in got["why"].lower()


def test_the_status_the_screen_polls_says_how_far_behind_it_is():
    st = ri.status()
    for k in ("pairs_indexed", "pairs_on_disk", "behind", "syncing"):
        assert k in st, k
