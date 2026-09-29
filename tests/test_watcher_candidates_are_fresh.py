"""The watcher judges a row by its pair file, never by a stale index.

Measured Sep 28, 2026: the top v2 rows by win rate read measured-through
Sep 22, 2026 in the index while their pair files ended Sep 28, 2026
12:30pm, with 3,656 of 5,006 pairs stale behind export_v2. A decision on the
index's figures would be a decision on last week."""
import pytest

from tradingagents import watcher_candidates as wc, watcher_policy as wp

NOW = 1_790_700_000.0
H = 3600.0


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = {"index": [], "pairs": {}, "last_ms": {}}
    monkeypatch.setattr(wc, "_index_rows", lambda cfg, limit: list(s["index"]))
    monkeypatch.setattr(wc, "_pair_rows",
                        lambda coin, tf: list(s["pairs"].get((coin, tf), [])))
    monkeypatch.setattr(wc, "_last_ms",
                        lambda coin, tf: s["last_ms"].get((coin, tf)))
    return s


def _row(**kw):
    base = {"coin": "FASTSTOCK", "tf": "15m", "signal": "bb20", "th": 0.0,
            "sl": 1.2, "tp": 1.2, "sizing": "flat", "trades": 97, "wins": 82,
            "losses": 15, "winrate": 84.54, "profit": 63.11, "gate": "ok"}
    return {**base, **kw}


def test_a_stale_index_row_is_judged_on_its_pair_file(store):
    store["index"] = [{**_row(), "id": "R6FRS3KD"}]
    store["pairs"][("FASTSTOCK", "15m")] = [_row(winrate=61.0, wins=59)]
    store["last_ms"][("FASTSTOCK", "15m")] = (NOW - 3 * H) * 1000
    got = wc.fresh_candidates(dict(wp.DEFAULTS), now=NOW)
    assert got["rows"][0]["winrate"] == 61.0, "the pair file's figure, not the index's"


def test_a_pair_older_than_fresh_hours_is_skipped_and_counted(store):
    store["index"] = [{**_row(), "id": "R6FRS3KD"}]
    store["pairs"][("FASTSTOCK", "15m")] = [_row()]
    store["last_ms"][("FASTSTOCK", "15m")] = (NOW - 37 * H) * 1000
    got = wc.fresh_candidates(dict(wp.DEFAULTS), now=NOW)
    assert got["rows"] == [] and got["stale"] == 1
    assert "1 row" in got["why"] and "36 hours" in got["why"]


def test_a_row_gone_from_its_pair_file_is_counted_not_invented(store):
    store["index"] = [{**_row(), "id": "R6FRS3KD"}]
    store["pairs"][("FASTSTOCK", "15m")] = []
    store["last_ms"][("FASTSTOCK", "15m")] = NOW * 1000
    got = wc.fresh_candidates(dict(wp.DEFAULTS), now=NOW)
    assert got["rows"] == [] and got["gone"] == 1


def test_each_pair_file_is_read_once_however_many_rows_it_holds(store, monkeypatch):
    reads = []
    store["index"] = [{**_row(sl=s, tp=s), "id": f"X{s}"} for s in (1.2, 1.5, 2.0)]
    rows = [_row(sl=s, tp=s) for s in (1.2, 1.5, 2.0)]
    monkeypatch.setattr(wc, "_pair_rows",
                        lambda coin, tf: (reads.append((coin, tf)), rows)[1])
    store["last_ms"][("FASTSTOCK", "15m")] = NOW * 1000
    wc.fresh_candidates(dict(wp.DEFAULTS), now=NOW)
    assert reads == [("FASTSTOCK", "15m")]


def test_the_id_is_rehashed_from_the_pair_row_itself(store):
    """The id printed beside a switched-on row must be that row's own hash
    (deploy-by-id), never carried over from the index."""
    from tradingagents import backtest_report as br

    store["index"] = [{**_row(), "id": "R6FRS3KD"}]
    store["pairs"][("FASTSTOCK", "15m")] = [_row()]
    store["last_ms"][("FASTSTOCK", "15m")] = NOW * 1000
    got = wc.fresh_candidates(dict(wp.DEFAULTS), now=NOW)["rows"][0]
    assert got["id"] == br.row_code("FASTSTOCK", "15m", "bb20", 0.0, 1.2, 1.2,
                                    "flat", res="1m") == "R6FRS3KD"


def test_learned_formulas_are_candidates_too(store):
    """The replay the operator approved walked all four groups (Sep 28, 2026:
    "i want all then"), so a learned formula is a candidate like any row."""
    store["index"] = [{**_row(signal="lx_FASTSTOCK_15m_3"), "id": "L1"}]
    store["pairs"][("FASTSTOCK", "15m")] = [_row(signal="lx_FASTSTOCK_15m_3")]
    store["last_ms"][("FASTSTOCK", "15m")] = NOW * 1000
    got = wc.fresh_candidates(dict(wp.DEFAULTS), now=NOW)
    assert [r["signal"] for r in got["rows"]] == ["lx_FASTSTOCK_15m_3"]


def test_a_running_slot_is_re_read_from_its_pair_file(store):
    store["pairs"][("FASTSTOCK", "15m")] = [_row(winrate=71.0)]
    store["last_ms"][("FASTSTOCK", "15m")] = (NOW - 50 * H) * 1000
    got = wc.fresh_row("R6FRS3KD", "FASTSTOCK", "15m", _row(), now=NOW, cfg=dict(wp.DEFAULTS))
    assert got["winrate"] == 71.0 and got["measured_ms"] == (NOW - 50 * H) * 1000
    store["pairs"][("FASTSTOCK", "15m")] = []
    assert wc.fresh_row("R6FRS3KD", "FASTSTOCK", "15m", _row(), now=NOW,
                        cfg=dict(wp.DEFAULTS)) is None
