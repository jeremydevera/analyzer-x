"""Every shape of room rule, ready to research and to run (Oct 01, 2026).

Operator: "can you create me a prompt that will look for best posible room
combination ... different winrate, tp sl, number of trades criteria? because
currently i think you are avoiding sl is greater than tp or avoiding tp that is
very high but low trade", then "i want it ready then".

Ready meant four things the tools could not do: a target EQUAL to the stop,
a SMALLEST target, a room that can actually find stop-wider-than-target rows,
and a grid of 8,064 rule sets inside GitHub's six hours. raw_trades is the
fast path, and it must give raw_fast's answer to the trade.
"""
from __future__ import annotations

import json
import datetime as dt
from pathlib import Path

import numpy as np
import pytest

from tradingagents import research_merge as rmg
from tradingagents import research_page as rp
from tradingagents import watcher_policy as wp
from tradingagents import watcher_replay as wr
from tradingagents import watcher_research as rs

ROOT = Path(__file__).resolve().parents[1]


def _row(tp, sl, **kw):
    return {"tp": tp, "sl": sl, "winrate": 90.0, "trades": 40, "profit": 1.0, "gate": "ok", **kw}


def test_equal_and_smallest_target_are_rules():
    cfg = {**wp.DEFAULTS, "tp_rule": "=", "max_sl": 0.0, "on_winrate": 50.0, "min_trades": 1}
    assert wp.passes_on(_row(1.2, 1.2), cfg) == ""
    assert wp.passes_on(_row(1.5, 1.2), cfg) == "TP 1.5% is not equal to SL 1.2%"
    cfg = {**cfg, "tp_rule": "any", "min_tp": 2.0}
    assert wp.passes_on(_row(2.0, 0.5), cfg) == ""
    assert wp.passes_on(_row(1.5, 0.5), cfg) == "TP 1.5% is under 2%"
    assert wp.DEFAULTS["min_tp"] == 0.0 and "=" in wp.TP_RULES


def test_the_live_watcher_takes_them(tmp_path, monkeypatch):
    from tradingagents import auto_trader as at
    from tradingagents import strategy_watcher as sw
    monkeypatch.setattr(sw, "_state_path", lambda: tmp_path / "w.json")
    monkeypatch.setattr(sw, "_log_path", lambda: tmp_path / "w.jsonl")
    monkeypatch.setattr(at, "load_settings", lambda: {})
    sw.set_cfg({"tp_rule": "=", "min_tp": 2.0})
    assert sw.cfg_of()["tp_rule"] == "=" and sw.cfg_of()["min_tp"] == 2.0
    with pytest.raises(ValueError, match="tp_rule must be one of"):
        sw.set_cfg({"tp_rule": "wide"})


def test_a_room_that_allows_a_wider_stop_is_shown_one(monkeypatch):
    """The rooms' search asked TP >= SL of every rule, so "<" and "any"
    rooms could never be shown a stop-wider-than-target row."""
    from tradingagents import rows_index as ri
    from tradingagents import watcher_candidates as wc
    seen = []
    monkeypatch.setattr(ri, "query", lambda **kw: seen.append(kw) or {"rows": []})
    for rule, asked in ((">", True), (">=", True), ("=", True), ("<", False), ("any", False)):
        wc._index_page({"tp_rule": rule, "min_trades": 5, "on_winrate": 70.0, "max_sl": 0,
                        "min_tp": 1.5, "_at_line": True}, 10, 0)
        assert seen[-1]["tp_over_sl"] is asked, rule
        assert seen[-1]["min_tp"] == 1.5


def _db(tmp_path, rows):
    import sqlite3

    from tradingagents import rows_index as ri
    path = tmp_path / "rows.db"
    con = sqlite3.connect(path)
    con.executescript(ri._SCHEMA)
    for r in rows:
        con.execute(f"INSERT INTO rows ({','.join(ri.COLS)},monthly,pair) VALUES "
                    f"({','.join('?' * (len(ri.COLS) + 2))})", ri._values(r, f"{r['coin']}-1h"))
    con.commit()
    con.close()
    return path


def test_the_15_day_search_follows_the_target_rule(tmp_path):
    from tradingagents import rows_index as ri

    def r(coin, tp, sl):
        return {"coin": coin, "tf": "1h", "signal": "macddiv", "th": 0.0, "sl": sl, "tp": tp,
                "sizing": "flat", "trades": 60, "wins": 50, "losses": 10, "winrate": 83.3,
                "profit": 1.0, "res": "1m", "t15": 30, "w15": 27, "p15": 2.0}
    db = _db(tmp_path, [r("WIDE", 1.5, 1.0), r("EQ", 1.0, 1.0), r("NARROW", 0.5, 1.0), r("BIG", 3.0, 2.0)])
    got = lambda **k: sorted(x["coin"] for x in ri.recent_rows(min_trades=10, min_winrate=80.0,  # noqa: E731
                                                               db_path=db, **k))
    assert got(tp_rule=">") == ["BIG", "WIDE"]
    assert got(tp_rule="=") == ["EQ"]
    assert got(tp_rule="<") == ["NARROW"]
    assert got(tp_rule="any") == ["BIG", "EQ", "NARROW", "WIDE"]
    assert got(tp_rule="any", min_tp=2.0) == ["BIG"]


def test_room_ids_made_before_the_target_floor_are_unchanged():
    c = {**rs.CURRENT, **rs.RAW, "window_days": 15, "on_winrate": 70.0, "off_winrate": 70.0,
         "min_trades": 50, "tp_rule": ">", "max_sl": 2.0}
    assert rs.rule_id(c) == "55D32617"
    assert rs.rule_id({**c, "min_tp": 0.0}) == "55D32617"
    assert rs.rule_id({**c, "min_tp": 2.0}) != "55D32617"


def test_the_loosest_rule_covers_every_shape():
    g = lambda *rules: [{**rs.CURRENT, "tp_rule": t, "min_tp": f} for t, f in rules]  # noqa: E731
    assert rs.loose(g((">", 0)))["tp_rule"] == ">"
    assert rs.loose(g((">", 0), ("=", 0)))["tp_rule"] == ">="
    assert rs.loose(g(("=", 0)))["tp_rule"] == "="
    assert rs.loose(g((">", 0), ("<", 0)))["tp_rule"] == "any"
    assert rs.loose(g((">", 2.0), (">", 1.0)))["min_tp"] == 1.0


def test_data_and_fairness_know_the_equal_shape():
    import importlib.util
    spec = importlib.util.spec_from_file_location("replay_shard", ROOT / ".github/scripts/replay_shard.py")
    src = (ROOT / ".github/scripts/replay_shard.py").read_text(encoding="utf-8")
    assert '("=", ">", ">=", "<", "any")' in src or '(">", ">=", "=", "<", "any")' in src
    assert "if rule == \"=\":\n        return abs(tp - sl) < 1e-6" in src
    assert spec is not None
    w = {"wr": 40.0, "trades": 1, "tp": ">"}
    c = {"on_winrate": 50.0, "min_trades": 5}
    assert rp.unfair({**c, "tp_rule": "="}, w), "data with only wider targets holds no equal one"
    assert not rp.unfair({**c, "tp_rule": "="}, {**w, "tp": ">="})
    assert not rp.unfair({**c, "tp_rule": "<"}, {**w, "tp": "any"})
    assert rp.unfair({**c, "tp_rule": ">"}, {**w, "tp": "<"})


def test_the_grid_is_every_shape_and_slices_cover_it_once():
    g = rs.scenarios6()
    assert len(g) == 8064 and len({rs.rule_id(c) for c in g}) == 8064
    assert {c["tp_rule"] for c in g} == {"any", ">", "=", "<"}
    assert min(c["on_winrate"] for c in g) == 40.0 and min(c["min_trades"] for c in g) == 1
    parts = [rs.chunk_of(g, i, 4) for i in range(4)]
    assert sorted(rs.rule_id(c) for c in sum(parts, [])) == sorted(rs.rule_id(c) for c in g)
    assert [len(p) for p in parts] == [2016] * 4
    # DEALT, so every slice gets the same mix of loose rule sets
    loose = [sum(1 for c in p if c["on_winrate"] == 40.0 and c["min_trades"] == 1) for p in parts]
    assert max(loose) - min(loose) <= 1, loose
    assert rs.SCENARIOS6_WRITE == "wr=40,trades=1,tp=any,windows=7|15|30"
    w = {"wr": 40.0, "trades": 1, "tp": "any"}
    assert not any(rp.unfair(c, w) for c in g), "no rule set looser than its data"


# ------------------------------------------------- the fast path is the answer
D = 86_400_000


def _books(seed=3, n=160):
    rng = np.random.default_rng(seed)
    start = int(dt.datetime(2026, 7, 20).timestamp() * 1000)
    out = []
    for i in range(n):
        k = int(rng.integers(5, 40))
        ent = np.sort(start + rng.integers(0, 70 * D, k)).astype(np.float64)
        ent = ent // 1000 * 1000
        ext = ent + rng.integers(1, 3 * D, k) // 1000 * 1000
        win = rng.random(k) < rng.uniform(0.3, 0.95)
        tp, sl = (float(rng.choice([0.5, 1.0, 1.5, 2.0, 3.0])), float(rng.choice([0.5, 1.0, 1.5, 2.0])))
        pnl = np.where(win, tp, -sl)
        closed = (rng.random(k) < 0.97).astype(np.float64)
        t = np.column_stack([ent, ext, pnl, closed])
        meta = {"id": f"B{i:04d}", "coin": f"C{i % 9}", "tf": "1h", "signal": "macddiv",
                "th": 0.0, "tp": tp, "sl": sl, "group": "classic"}
        out.append(rs.ArrBook(meta, t, packed=True))
    return out


@pytest.mark.parametrize("cfg", [
    dict(window_days=15, on_winrate=40.0, min_trades=1, tp_rule="any", max_sl=0.0, min_tp=0.0),
    dict(window_days=7, on_winrate=50.0, min_trades=3, tp_rule="=", max_sl=0.0, min_tp=1.0),
    dict(window_days=30, on_winrate=60.0, min_trades=5, tp_rule="<", max_sl=2.0, min_tp=0.0),
    dict(window_days=15, on_winrate=70.0, min_trades=2, tp_rule=">", max_sl=3.0, min_tp=2.0),
])
def test_raw_trades_is_raw_fast_to_the_trade(cfg):
    books = _books()
    flat = rs.Flat(books)
    checks = wr.local_midnights(int(dt.datetime(2026, 8, 1).timestamp() * 1000),
                                int(dt.datetime(2026, 9, 25).timestamp() * 1000))
    end = checks[-1] + D
    c = {**rs.CURRENT, **rs.RAW, **cfg, "off_winrate": cfg["on_winrate"]}
    grid = rs.count_grid(books, checks, c["window_days"] * D)
    r1 = rs.raw_fast(books, grid, checks, c, end)
    r2 = rs.raw_trades(books, flat, grid, checks, c, end)
    a = sorted((s["id"], int(x[0]), int(x[1]), round(float(x[2]), 4), bool(x[3]))
               for s in r1["slots"] for x in s["trades"])
    ids = [b.c["id"] for b in books]
    b = sorted((ids[i], int(e), int(x), round(float(p), 4), bool(cl))
               for i, e, x, p, cl in zip(r2["book"], r2["ent"], r2["ext"], r2["pnl"], r2["closed"]))
    assert a == b
    assert (r1["summary"]["slots"], r1["summary"]["open"]) == (r2["slots"], r2["open"])
    assert r2["slots"] > 0 or cfg["tp_rule"] == "=", "the fixture must exercise the walk"


def test_the_per_coin_limit_skips_a_full_coin_and_still_agrees():
    """With 4 open, everything entering before the first close is refused in
    one step — the answer must be the walk's."""
    coin = np.zeros(8, np.int32)
    ent = np.array([0, 1, 2, 3, 4, 5, 6, 20], np.int64)
    ext = np.array([10, 11, 12, 13, 5, 6, 7, 30], np.int64)
    closed = np.ones(8, bool)
    keep = rs._cap(coin, ent, ext, closed, np.arange(8), 4)
    assert keep.tolist() == [True, True, True, True, False, False, False, True]


def test_the_merge_puts_slices_back_in_order_and_logs_only_the_top(tmp_path, monkeypatch):
    monkeypatch.setattr(rmg.rc, "merge_reports", lambda dirs: {"write": {}})
    monkeypatch.setattr(rmg.rs, "OUT_DIR", tmp_path / "out")
    grid = rs.scenarios5()[:4]
    end = int(dt.datetime(2026, 9, 30, 12).timestamp() * 1000)
    t_min = (int(dt.datetime(2026, 9, 10).timestamp()) // 60) - rmg.T0_MIN
    for shard in (0, 1):
        for chunk in (0, 1):
            rules = rs.chunk_of(grid, chunk, 2)
            arrays, meta = {}, {"shard": shard, "chunk": chunk, "chunks": 2, "end_ms": end,
                                "books": 100 + shard, "rules": [],
                                "strategies": [[f"S{shard}", "VUG", "1h", "macddiv", 0.0, 1.0, 0.5],
                                               ["SHARED", "KII", "1h", "bb20", 0.0, 1.0, 0.5]]}
            for j, cfg in enumerate(rules):
                meta["rules"].append({"cfg": cfg, "train": {"slots": 1, "open": 0},
                                      "test": {"slots": 2, "open": 0}})
                for part in ("train", "test"):
                    arrays[f"{j}_{part}_e"] = np.array([t_min], np.int32)
                    arrays[f"{j}_{part}_x"] = np.array([t_min + 60], np.int32)
                    arrays[f"{j}_{part}_p"] = np.array([1.0 + j + chunk], np.float32)
                arrays[f"{j}_test_s"] = np.array([1], np.int32)
            d = tmp_path / "art" / f"research-{shard}-{chunk}"
            d.mkdir(parents=True)
            np.savez_compressed(d / f"research-{shard}-{chunk}.npz", **arrays)
            (d / f"research-{shard}-{chunk}.json").write_text(json.dumps(meta), encoding="utf-8")
    out = json.loads(Path(rmg.merge("t", str(tmp_path / "art"), str(tmp_path), log_top=1))
                     .read_text(encoding="utf-8"))
    assert [r["id"] for r in out["rows"]] == [rs.rule_id(c) for c in grid]
    assert [s[0] for s in out["strategies"]] == ["S0", "SHARED", "S1"], "each strategy once"
    assert out["combos"] == 201
    assert all(r["test"]["closed"] == 2 for r in out["rows"]), "both shards' trades added"
    assert sum(1 for r in out["rows"] if r.get("test_log")) == 1, "only the top rule set's list"


# ------------------------------------- a shard measured coin batch by batch
def _write_shard(folder, books, dup=None):
    """The replay's own line shape: id, then coin, first."""
    d = folder / "replay-0"
    d.mkdir(parents=True)
    with open(d / "replay-0.jsonl", "w", encoding="utf-8") as fh:
        for b in books:
            c = {k: b.c[k] for k in ("id", "coin", "tf", "signal", "th", "tp", "sl", "group")}
            fh.write(json.dumps({**c, "trades": b.c["trades"].tolist()}) + "\n")
            if dup is not None and b.c["id"] == dup:
                # a later line for the same id: load_lean keeps the FIRST
                fh.write(json.dumps({**c, "trades": b.c["trades"][:1].tolist()}) + "\n")
    return d


def test_coin_batches_hold_whole_coins_and_the_first_line_of_every_id(tmp_path):
    """Shard 8 of replay run 37007971331 (206,094,384 trades) was loaded whole
    and the GitHub machine was shut down; a batch of whole coins must load
    exactly the books the one pass loaded."""
    books = _books()
    _write_shard(tmp_path, books, dup="B0007")
    end = int(dt.datetime(2026, 12, 1).timestamp() * 1000)
    batches = rs.coin_batches([str(tmp_path)], 2000)
    assert len(batches) > 3, "the fixture must be split"
    got = [rs.load_batch(b, end) for b in batches]
    coins = [{b.c["coin"] for b in g} for g in got]
    assert all(not (a & b) for i, a in enumerate(coins) for b in coins[i + 1:]), "a coin in two batches"
    flat = {b.c["id"]: b for g in got for b in g}
    assert sorted(flat) == sorted(b.c["id"] for b in books), "every id once"
    for b in books:
        assert np.array_equal(flat[b.c["id"]].exits, b.exits), b.c["id"]
    assert len(rs.coin_batches([str(tmp_path)], 10 ** 9)) == 1


@pytest.mark.parametrize("out", ["daily", "full"])
def test_a_shard_in_batches_adds_up_to_the_shard_at_once(tmp_path, monkeypatch, out):
    """research_shard with one coin a batch against one batch for the lot,
    through main() itself: every day total, every trade, every count."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("research_shard_t", ROOT / ".github/scripts/research_shard.py")
    sh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sh)
    books = _books(seed=5, n=200)
    src = _write_shard(tmp_path / "src", books)
    sets = [dict(window_days=15, on_winrate=40.0, min_trades=1, tp_rule="any", max_sl=0.0, min_tp=0.0),
            dict(window_days=7, on_winrate=50.0, min_trades=3, tp_rule="=", max_sl=0.0, min_tp=1.0),
            dict(window_days=30, on_winrate=60.0, min_trades=5, tp_rule="<", max_sl=2.0, min_tp=0.0),
            dict(window_days=15, on_winrate=70.0, min_trades=2, tp_rule=">", max_sl=3.0, min_tp=2.0)]
    rf = tmp_path / "round.json"
    rf.write_text(json.dumps(sets), encoding="utf-8")
    end = int(dt.datetime(2026, 9, 30, 12).timestamp() * 1000)
    res = {}
    for mb in ("0", "100000"):
        run = tmp_path / f"run{mb}"
        run.mkdir()
        monkeypatch.chdir(run)
        for k, v in dict(SRC=str(src.parent), SHARD="0", CHUNK="0", CHUNKS="1", OUT=out,
                         END_MS=str(end), SCEN=f"file:{rf}", BATCH_MB=mb).items():
            monkeypatch.setenv(k, v)
        assert sh.main() == 0
        res[mb] = (np.load(run / "out/research-0.npz"),
                   json.loads((run / "out/research-0.json").read_text(encoding="utf-8")))
    (A, am), (B, bm) = res["0"], res["100000"]
    assert am["batches"] == 9 and bm["batches"] == 1, "one batch a coin (C0..C8) against one"
    assert (am["books"], am["trades"]) == (bm["books"], bm["trades"]) == (200, am["trades"])
    assert [(r["cfg"], r["train"], r["test"]) for r in am["rules"]] == \
        [(r["cfg"], r["train"], r["test"]) for r in bm["rules"]]
    assert set(A.files) == set(B.files)
    kept = 0
    for j in range(len(sets)):
        for part in ("train", "test"):
            if out == "daily":
                assert np.array_equal(A[f"{j}_{part}_dn"], B[f"{j}_{part}_dn"])
                assert np.array_equal(A[f"{j}_{part}_dw"], B[f"{j}_{part}_dw"])
                assert np.allclose(A[f"{j}_{part}_dp"], B[f"{j}_{part}_dp"], atol=1e-4)
                kept += int(A[f"{j}_{part}_dn"].sum())
                continue
            ta = sorted(zip(A[f"{j}_{part}_e"].tolist(), A[f"{j}_{part}_x"].tolist(),
                            np.round(A[f"{j}_{part}_p"], 4).tolist()))
            tb = sorted(zip(B[f"{j}_{part}_e"].tolist(), B[f"{j}_{part}_x"].tolist(),
                            np.round(B[f"{j}_{part}_p"], 4).tolist()))
            assert ta == tb, (j, part)
            kept += len(ta)
        if out == "full":
            sa = sorted(am["strategies"][i][0] for i in A[f"{j}_test_s"].tolist())
            sb = sorted(bm["strategies"][i][0] for i in B[f"{j}_test_s"].tolist())
            assert sa == sb, j
    assert kept > 100, "the fixture must keep trades"


@pytest.mark.parametrize("cfg", [
    dict(window_days=15, on_winrate=40.0, min_trades=1, tp_rule="any", max_sl=0.0, min_tp=0.0),
    dict(window_days=7, on_winrate=50.0, min_trades=3, tp_rule="=", max_sl=0.0, min_tp=1.0),
    dict(window_days=30, on_winrate=60.0, min_trades=5, tp_rule="<", max_sl=2.0, min_tp=0.0),
    dict(window_days=15, on_winrate=70.0, min_trades=2, tp_rule=">", max_sl=3.0, min_tp=2.0),
])
def test_one_shared_walk_gives_each_rule_set_its_own_answer(cfg):
    """research_shard walks the switch-ons once per (window, trades, line)
    and filters them per rule set: same trades, same order, same counts."""
    books = _books(seed=9, n=220)
    flat = rs.Flat(books)
    checks = wr.local_midnights(int(dt.datetime(2026, 8, 1).timestamp() * 1000),
                                int(dt.datetime(2026, 9, 25).timestamp() * 1000))
    end = checks[-1] + D
    c = {**rs.CURRENT, **rs.RAW, **cfg, "off_winrate": cfg["on_winrate"]}
    grid = rs.count_grid(books, checks, c["window_days"] * D)
    alone = rs.raw_trades(books, flat, grid, checks, c, end)
    shared = rs.raw_trades(books, flat, grid, checks, c, end, starts=rs.all_starts(flat, grid, checks, c))
    for k in ("book", "ent", "ext", "pnl", "closed"):
        assert np.array_equal(alone[k], shared[k]), k
    assert (alone["slots"], alone["open"]) == (shared["slots"], shared["open"])
    other = {**c, "tp_rule": "any", "max_sl": 0.0, "min_tp": 0.0}
    assert rs.starts_key(other) == rs.starts_key(c), "shape, cap and floor do not change the walk"


def test_the_one_pass_sort_is_the_three_key_sort():
    """_cap sorts (coin, entry) once when the candidates arrive slot by
    slot; a tie must still go to the slot switched on first."""
    rng = np.random.default_rng(4)
    for _ in range(30):
        n = int(rng.integers(5, 400))
        slot = np.sort(rng.integers(0, 40, n))
        coin = rng.integers(0, 3, n).astype(np.int32)
        ent = rng.integers(0, 60, n).astype(np.int32)          # many ties ACROSS slots
        # one slot is one book's run: it never holds two entries at once
        _, first = np.unique(slot.astype(np.int64) * 1000 + ent, return_index=True)
        first = np.sort(first)
        slot, coin, ent = slot[first], coin[first], ent[first]
        n = len(slot)
        ext = ent + rng.integers(1, 30, n).astype(np.int32)
        closed = rng.random(n) < 0.9
        fast = rs._cap(coin, ent, ext, closed, slot, 2)
        shuffled = rng.permutation(n)                          # not slot order: lexsort path
        slow = np.empty(n, bool)
        slow[shuffled] = rs._cap(coin[shuffled], ent[shuffled], ext[shuffled], closed[shuffled],
                                 slot[shuffled], 2)
        assert np.array_equal(fast, slow)
