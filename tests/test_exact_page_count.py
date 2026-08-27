"""A numbered pager needs a real LAST page (2026-08-27).

The count for a filtered view used to stop at COUNT_CAP and print "of 10+".
Measured on the operator's own store (35,863,520 rows, mechanical disk):

    tf='1h', COUNT_CAP =   5,000   ->     5,000+ in   0.69 s
    tf='1h', COUNT_CAP = 100,000   ->   100,000+ in 543.82 s
    tf='1h', from the pair summaries -> 5,458,108 in 0.08 s  (exact)

`pairs` carries one row per coin+timeframe with its own `n`, so any filter
that only names a coin and/or a timeframe is an exact sum over ~4,200 tiny
rows. A signal, a profit floor or a trade floor cuts INSIDE a pair, and those
still get the capped count with the "+".
"""
import json

import pytest

import tradingagents.rows_index as ri


def _seed(tmp_path, monkeypatch):
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    ri._ready.discard(str(tmp_path / "rows.db"))
    ri.forget_indexes()
    ri.ensure()
    made = {}
    for coin, tf, n in (("AAA", "1h", 7), ("AAA", "4h", 3), ("BBB", "1h", 5)):
        rows = [{"id": f"{coin}{tf}{i}", "coin": coin, "tf": tf,
                 "signal": "ema" if i % 2 else "rsi",
                 "profit": (i - 2) * 1.5, "winrate": 50 + i,
                 "trades": 10 * (i + 1), "dd": 1.0, "monthly": {}}
                for i in range(n)]
        made[(coin, tf)] = rows
        f = tmp_path / f"{coin}_USDT-{tf}.json"
        f.write_text(json.dumps(rows), encoding="utf-8")
        with ri._open() as con:
            ri.index_pair(f, con)
    return made


def test_a_timeframe_filter_counts_exactly_and_says_so(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    got = ri.query(tf="1h", limit=1)
    assert got["total"] == 12, got["total"]          # 7 AAA + 5 BBB
    assert got["total_capped"] is False, "an exact count must not print a +"


def test_a_coin_filter_counts_exactly(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    got = ri.query(coin="AAA", limit=1)
    assert (got["total"], got["total_capped"]) == (10, False)
    both = ri.query(coin="AAA", tf="4h", limit=1)
    assert (both["total"], both["total_capped"]) == (3, False)


def test_the_cap_still_guards_a_filter_that_cuts_inside_a_pair(
        tmp_path, monkeypatch):
    """profitable / min_trades / min_winrate / signal are not in `pairs`, so
    they keep the bounded count — 543 s is not a page number."""
    _seed(tmp_path, monkeypatch)
    monkeypatch.setattr(ri, "COUNT_CAP", 2)
    got = ri.query(profitable=True, limit=1)
    assert got["total"] == 2 and got["total_capped"] is True
    got = ri.query(signal="ema", limit=1)
    assert got["total"] == 2 and got["total_capped"] is True
    # and a coin/tf filter is still exact even under a tiny cap
    got = ri.query(tf="1h", limit=1)
    assert got["total"] == 12 and got["total_capped"] is False


def test_an_empty_timeframe_answers_at_once(tmp_path, monkeypatch):
    """1d had 739 row files of `[]`. The exact count is 0, so the row query is
    skipped entirely — otherwise SQLite scans the whole profit index for a
    first match that does not exist (past five minutes on the real store)."""
    _seed(tmp_path, monkeypatch)
    got = ri.query(tf="1d", limit=500)
    assert (got["total"], got["rows"]) == (0, [])


def test_the_page_count_the_screen_would_print(tmp_path, monkeypatch):
    """What the pager divides: total / rows-a-page, and every page reachable."""
    _seed(tmp_path, monkeypatch)
    per = 5
    total = ri.query(tf="1h", limit=1)["total"]
    pages = -(-total // per)
    assert pages == 3
    seen = []
    for page in range(1, pages + 1):
        seen += [r["id"] for r in
                 ri.query(tf="1h", limit=per, offset=(page - 1) * per)["rows"]]
    assert len(seen) == total == 12, seen
    assert len(set(seen)) == total, "a row must not appear on two pages"
