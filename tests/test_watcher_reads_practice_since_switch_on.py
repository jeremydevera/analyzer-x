"""Practice results count from the moment the watcher switched a row on."""
import pytest

from tradingagents import auto_trader as at, watcher_results as wr

NOW = 1_790_700_000.0
SLOT = "bb20_15m_sl12tp12|FASTSTOCK_USDT"


def _exit(ts, pnl, dry=True, strat="bb20_15m_sl12tp12", sym="FASTSTOCK_USDT"):
    return {"action": "exit", "dry_run": dry, "strategy": strat,
            "symbol": sym, "pnl_est": pnl, "ts": ts}


@pytest.fixture
def ledger(monkeypatch):
    rows = []
    monkeypatch.setattr(at, "ledger_since",
                        lambda ts: [r for r in rows if r["ts"] >= ts])
    return rows


def test_counts_only_after_switch_on(ledger):
    ledger += [_exit(NOW - 5000, -1.62), _exit(NOW - 100, 0.98)]
    got = wr.practice({SLOT: NOW - 1000}, now=NOW)[SLOT]
    assert (got["trades"], got["wins"], got["losses"]) == (1, 1, 0)


def test_real_money_exits_are_not_practice(ledger):
    ledger += [_exit(NOW - 10, 0.98, dry=False)]
    assert wr.practice({SLOT: NOW - 1000}, now=NOW)[SLOT]["trades"] == 0


def test_another_coin_on_the_same_key_is_not_this_row(ledger):
    ledger += [_exit(NOW - 10, -1.62, sym="KKRSTOCK_USDT")]
    assert wr.practice({SLOT: NOW - 1000}, now=NOW)[SLOT]["trades"] == 0


def test_the_streak_is_the_current_run_of_losses(ledger):
    ledger += [_exit(NOW - 50 + i, p) for i, p in
               enumerate([-1.6, 0.98, -1.6, -1.6, -1.6])]
    assert wr.practice({SLOT: NOW - 1000}, now=NOW)[SLOT]["streak"] == 3


def test_average_win_and_loss_in_dollars(ledger):
    ledger += [_exit(NOW - 30, 1.0), _exit(NOW - 20, 0.96),
               _exit(NOW - 10, -1.62)]
    got = wr.practice({SLOT: NOW - 1000}, now=NOW)[SLOT]
    assert got["win_usd"] == pytest.approx(0.98)
    assert got["loss_usd"] == pytest.approx(1.62)
    assert got["pnl"] == pytest.approx(0.34)


def test_the_window_is_never_older_than_30_days(ledger):
    ledger += [_exit(NOW - 31 * 86400, -1.62)]
    assert wr.practice({SLOT: NOW - 40 * 86400}, now=NOW)[SLOT]["trades"] == 0


def test_a_list_that_is_not_ready_is_a_wait_never_an_empty_day(monkeypatch):
    from tradingagents import watcher_candidates as wc, watcher_policy as wp

    def _boom(cfg, limit):
        raise RuntimeError("rows_wr4 is being built now")

    monkeypatch.setattr(wc, "_index_rows", _boom)
    got = wc.fresh_candidates(dict(wp.DEFAULTS), now=NOW)
    assert got["not_ready"] is True and got["rows"] == []
    assert "rows_wr4" in got["why"] and "again" in got["why"]


def test_the_ledger_is_read_once_however_many_slots(ledger, monkeypatch):
    calls = []
    real = at.ledger_since
    monkeypatch.setattr(at, "ledger_since", lambda ts: (calls.append(ts), real(ts))[1])
    wr.practice({f"k{i}|C{i}_USDT": NOW - 1000 for i in range(50)}, now=NOW)
    assert len(calls) == 1
