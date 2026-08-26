"""The row index has to be FAST and EXACT.

Fast is why it exists: `/api/strategies` re-parsed 363 MB per request and the
grid polls every 4 seconds. Exact is the harder half — a "top-N summary" would
have been fast and quietly wrong the moment anyone filtered by timeframe. Every
test below compares the index's answer to the same answer computed from the
JSON files, which stay the source of truth.
"""

import json

import pytest

from tradingagents import market_sweep as msw, rows_index as ri


def _settled(**kw):
    """Sync as if the settle window had already passed — these tests write a
    file and index it in the same millisecond, which the real sweep never
    does."""
    import time

    return ri.sync(now=time.time() + ri.SETTLE_S + 1, **kw)


def _row(coin, tf, signal, profit, *, sizing="flat", th=0.1, sl=0.3, tp=0.9):
    return {"coin": coin, "tf": tf, "signal": signal, "th": th, "sl": sl,
            "tp": tp, "rr": tp / sl, "sizing": sizing, "lev": 20, "base": 5.0,
            "notional": 100.0, "trades": 120, "wins": 70, "losses": 50,
            "winrate": 58.3, "profit": profit, "funding": -0.2, "h1": profit / 2,
            "h2": profit / 2, "green": 8, "months": 12, "worst": -4.1,
            "dd": 22.0, "liqs": 0, "stop_reachable": True, "days": 360,
            "bars": 34000, "monthly": {"2026-01": profit / 3},
            "cost_of_tp": 12.5, "rt": 0.04, "gate": "ok"}


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A small row store on disk, plus the index pointed beside it."""
    rows_dir = tmp_path / "rows"
    rows_dir.mkdir()
    monkeypatch.setattr(msw, "ROWDIR", rows_dir)
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    made = {}
    for coin in ("BTC", "PI", "APEX"):
        for tf in ("15m", "1h"):
            batch = [_row(coin, tf, sig, profit)
                     for sig, profit in (("mom6", 10.0), ("trend50", -5.0),
                                         ("rsi14", 42.5))]
            batch += [_row(coin, tf, "mom6", 7.5, sizing="martingale")]
            (rows_dir / f"{coin}-{tf}.json").write_text(json.dumps(batch))
            made[(coin, tf)] = batch
    return rows_dir, made


def _from_json(rows_dir, **f):
    """The truth, computed the slow way the API used to — including the SAME
    tiebreaker, because ties on profit are common and an order that is not
    total is an order that reshuffles between polls."""
    from tradingagents import backtest_report as br

    out = []
    for p in sorted(rows_dir.glob("*.json")):
        out += json.loads(p.read_text())
    for k, v in f.items():
        if k == "profitable" and v:
            out = [r for r in out if (r.get("profit") or 0) > 0]
        elif v is not None and k != "profitable":
            out = [r for r in out if r.get(k) == v]
    for r in out:
        r.setdefault("id", br.row_code(r["coin"], r["tf"], r["signal"],
                                       r.get("th") or 0.0, r["sl"], r["tp"],
                                       r["sizing"]))
    return sorted(out, key=lambda r: (-(r.get("profit") or 0), r["id"]))


def test_index_matches_the_json_store_exactly(store):
    rows_dir, _ = store
    ri.sync()
    got = ri.query(limit=2000)
    want = _from_json(rows_dir)
    assert got["total"] == len(want), "row count disagrees with the files"
    assert [r["profit"] for r in got["rows"]] == [r["profit"] for r in want], \
        "profit ordering disagrees with the files"
    assert [(r["coin"], r["tf"], r["signal"], r["sizing"]) for r in got["rows"]] \
        == [(r["coin"], r["tf"], r["signal"], r["sizing"]) for r in want]


@pytest.mark.parametrize("filt", [
    {"coin": "PI"},
    {"tf": "1h"},
    {"signal": "mom6"},
    {"profitable": True},
    {"coin": "BTC", "tf": "15m"},
    {"coin": "APEX", "tf": "1h", "signal": "rsi14"},
])
def test_every_filter_is_exact_not_approximate(store, filt):
    """A top-N cache would pass the unfiltered test and fail these."""
    rows_dir, _ = store
    ri.sync()
    got = ri.query(limit=2000, **filt)
    want = _from_json(rows_dir, **filt)
    assert got["total"] == len(want), f"{filt}: {got['total']} vs {len(want)}"
    assert [r["profit"] for r in got["rows"]] == [r["profit"] for r in want]


def test_a_row_survives_the_round_trip_whole(store):
    """Every field the grid prints must come back, with its type — a dict that
    returns as the string "{...}" renders as garbage in the monthly columns."""
    rows_dir, _ = store
    ri.sync()
    r = ri.query(coin="BTC", tf="15m", signal="rsi14", limit=1)["rows"][0]
    src = next(x for x in json.loads((rows_dir / "BTC-15m.json").read_text())
               if x["signal"] == "rsi14")
    for k, v in src.items():
        assert k in r, f"the index dropped {k}"
        if isinstance(v, float):
            assert r[k] == pytest.approx(v), k
        else:
            assert r[k] == v, k
    assert isinstance(r["monthly"], dict), "monthly must survive as a dict"
    assert r["stop_reachable"] is True, "a bool must not come back as 1"
    assert r["id"], "every row carries its stable id"


def test_paging_does_not_repeat_or_skip_a_row(store):
    ri.sync()
    page1 = ri.query(limit=5, offset=0)["rows"]
    page2 = ri.query(limit=5, offset=5)["rows"]
    all_ids = [r["id"] for r in ri.query(limit=2000)["rows"]]
    assert [r["id"] for r in page1] == all_ids[:5]
    assert [r["id"] for r in page2] == all_ids[5:10]
    assert not {r["id"] for r in page1} & {r["id"] for r in page2}


def test_only_changed_pairs_are_reindexed(store):
    """The sweep rewrites a pair every 200 combinations. Re-indexing all of
    them on every change is how a 25 GB store becomes unservable again."""
    rows_dir, _ = store
    first = ri.sync()
    assert first["pairs"] == 6
    assert ri.sync()["pairs"] == 0, "nothing changed, nothing should be redone"

    target = rows_dir / "PI-1h.json"
    batch = json.loads(target.read_text())
    batch.append(_row("PI", "1h", "sweep30", 99.0))
    target.write_text(json.dumps(batch))
    again = _settled()
    assert again["pairs"] == 1, f"reindexed {again['pairs']} pairs, wanted 1"
    top = ri.query(limit=1)["rows"][0]
    assert top["profit"] == 99.0 and top["signal"] == "sweep30"


def test_a_shrinking_pair_does_not_leave_orphans(store):
    """A pair re-measured with fewer signals must LOSE the old rows, or the
    grid keeps recommending a combination that no longer exists."""
    rows_dir, _ = store
    ri.sync()
    before = ri.query(coin="BTC", tf="1h", limit=2000)["total"]
    (rows_dir / "BTC-1h.json").write_text(json.dumps([_row("BTC", "1h", "mom6", 1.0)]))
    _settled()
    after = ri.query(coin="BTC", tf="1h", limit=2000)
    assert before == 4 and after["total"] == 1, f"{before} -> {after['total']}"
    assert all(r["signal"] == "mom6" for r in after["rows"])


def test_facets_come_from_the_index(store):
    rows_dir, _ = store
    ri.sync()
    f = ri.facets()
    assert f["coins"] == ["APEX", "BTC", "PI"]
    assert f["tfs"] == ["15m", "1h"]
    assert f["signals"] == ["mom6", "rsi14", "trend50"]


def test_status_says_how_far_behind_it_is(store):
    """The grid must be able to say "indexing" rather than showing a partial
    list as if it were the whole store."""
    rows_dir, _ = store
    files = sorted(rows_dir.glob("*.json"))
    ri.sync(paths=files[:2])
    st = ri.status()
    assert st["pairs_indexed"] == 2 and st["pairs_on_disk"] == 6
    assert st["behind"] == 4
    ri.sync()
    assert ri.status()["behind"] == 0


def test_a_query_is_fast_enough_to_poll(store):
    """The whole point. all_rows() measured 28.6s on the real store; a query
    the UI polls has to be milliseconds."""
    import time

    ri.sync()
    t = time.perf_counter()
    for _ in range(20):
        ri.query(limit=300)
    per = (time.perf_counter() - t) / 20
    assert per < 0.05, f"{per*1000:.0f}ms per query is too slow to poll"


def test_a_corrupt_pair_file_does_not_break_the_index(store):
    rows_dir, _ = store
    ri.sync()
    (rows_dir / "PI-15m.json").write_text("{ this is not json")
    out = _settled()                      # must not raise
    assert ri.query(limit=2000)["total"] > 0, "one bad file emptied the index"
    assert out["pairs"] >= 1


def test_the_index_never_lands_in_live_state_during_tests():
    """Canary, same class as the db_jobs one: a test that wrote the real
    rows.db would corrupt the operator's own strategy list."""
    from pathlib import Path

    assert not str(ri.DB_PATH).startswith(str(Path.home() / ".tradingagents")), \
        f"the index is pointing at live state: {ri.DB_PATH}"


def test_facets_do_not_scan_every_measurement(store):
    """SELECT DISTINCT over the row table measured 1.7s at 690,630 rows and the
    dropdowns load on mount. They come from the per-pair summary instead."""
    import time

    ri.sync()
    t = time.perf_counter()
    for _ in range(50):
        ri.facets()
    per = (time.perf_counter() - t) / 50
    assert per < 0.02, f"{per*1000:.0f}ms per facet call"
    src = open("tradingagents/rows_index.py", encoding="utf-8").read()
    body = src[src.index("def facets("):src.index("def status(")]
    assert "FROM rows" not in body, "facets must not touch the row table"


def test_facets_drop_a_value_when_its_pair_stops_producing_it(store):
    """A stale dropdown entry offers a filter that returns nothing."""
    rows_dir, _ = store
    ri.sync()
    assert "trend50" in ri.facets()["signals"]
    for tf in ("15m", "1h"):
        for coin in ("BTC", "PI", "APEX"):
            keep = [r for r in json.loads((rows_dir / f"{coin}-{tf}.json").read_text())
                    if r["signal"] != "trend50"]
            (rows_dir / f"{coin}-{tf}.json").write_text(json.dumps(keep))
    _settled()
    assert "trend50" not in ri.facets()["signals"]
    assert "mom6" in ri.facets()["signals"]


def test_a_second_database_still_gets_its_schema(tmp_path, monkeypatch):
    """The ensure() guard is keyed on the path. A bare boolean once left the
    next database with no tables and broke 14 tests."""
    monkeypatch.setattr(msw, "ROWDIR", tmp_path / "r")
    (tmp_path / "r").mkdir()
    for name in ("a.db", "b.db"):
        monkeypatch.setattr(ri, "DB_PATH", tmp_path / name)
        ri.ensure()
        got2 = ri.query(limit=1)
        assert got2["rows"] == [] and got2["total"] == 0, name


def test_reading_never_writes(store, monkeypatch):
    """query() used to fill an empty index inline. That put a writer on a route
    the grid polls every 4 seconds, the polls fought the indexer for SQLite's
    single write lock, and a pair that takes 0.7s alone took 29.2s."""
    called = []
    monkeypatch.setattr(ri, "sync",
                        lambda *a, **k: called.append(k) or {"pairs": 0})
    ri.query(limit=5)
    ri.facets()
    ri.status()
    assert not called, "a read path called sync()"
    src = open("tradingagents/rows_index.py", encoding="utf-8").read()
    body = src[src.index("def query("):src.index("def facets(")]
    for banned in ("sync(", "ensure(", "INSERT", "DELETE", "CREATE"):
        assert banned not in body, f"query() does {banned}"


def test_an_empty_index_answers_empty_rather_than_indexing(store):
    """Nothing indexed yet is not an error and not a stall — it is zero rows
    plus a status line saying how far behind it is."""
    got = ri.query(limit=10)
    # the payload also carries `sort` (the caption is derived from it), so
    # assert what this test is about rather than the whole dict
    assert got["rows"] == [] and got["total"] == 0
    st = ri.status()
    assert st["pairs_indexed"] == 0 and st["behind"] == 6




def test_a_pair_being_written_right_now_is_not_reindexed(store):
    """Seven cores each rewrite a pair file of up to 9.7 MB every few seconds.
    Re-indexing those per request costs more disk than the sweep and publishes
    rows that are about to change."""
    rows_dir, _ = store
    ri.sync()
    target = rows_dir / "PI-1h.json"
    batch = json.loads(target.read_text())
    batch.append(_row("PI", "1h", "sweep30", 99.0))
    target.write_text(json.dumps(batch))          # just changed, still hot
    assert target not in ri.stale_pairs(), "a hot file was picked up"
    # once it settles it gets indexed
    later = target.stat().st_mtime + ri.SETTLE_S + 1
    assert target in ri.stale_pairs(now=later)


def test_a_brand_new_pair_is_indexed_at_once(store):
    """Waiting a minute to show a coin that has never appeared is worse than
    the churn the settle window avoids."""
    rows_dir, _ = store
    ri.sync()
    fresh = rows_dir / "NEWCOIN-4h.json"
    fresh.write_text(json.dumps([_row("NEWCOIN", "4h", "mom6", 5.0)]))
    assert fresh in ri.stale_pairs(), "a never-seen pair must not wait"
    ri.sync()
    assert ri.query(coin="NEWCOIN", limit=5)["total"] == 1


def test_a_never_seen_pair_is_indexed_before_a_pair_that_merely_moved(store):
    """The sweep rewrites known pairs at every checkpoint, so a single ordered
    list let them eat the whole budget: the row count climbed 690,630 ->
    715,593 while the pair count sat at 85 and 43 finished coins stayed
    invisible."""
    import time

    rows_dir, _ = store
    ri.sync()
    # a known pair moves...
    known = rows_dir / "APEX-15m.json"
    batch = json.loads(known.read_text())
    batch.append(_row("APEX", "15m", "sweep30", 3.0))
    known.write_text(json.dumps(batch))
    # ...and a pair that has never been seen appears, later in the alphabet
    fresh = rows_dir / "ZZZ-1h.json"
    fresh.write_text(json.dumps([_row("ZZZ", "1h", "mom6", 1.0)]))

    order = ri.stale_pairs(now=time.time() + ri.SETTLE_S + 1)
    assert order[0] == fresh, f"order was {[p.name for p in order]}"
    assert known in order, "the changed pair is still queued, just second"


def test_the_index_advances_with_no_requests_at_all(store, monkeypatch):
    """Syncing from the request handler froze the index whenever the Backtest
    tab was closed."""
    import time

    rows_dir, _ = store
    ri.sync()
    (rows_dir / "LATE-4h.json").write_text(json.dumps([_row("LATE", "4h", "mom6", 2.0)]))
    assert ri.query(coin="LATE", limit=5)["total"] == 0

    assert ri.start_keeping_up(every_s=0.2, budget_s=5.0)
    assert not ri.start_keeping_up(every_s=0.2), "two loops must not run"
    try:
        for _ in range(50):
            if ri.query(coin="LATE", limit=5)["total"] == 1:
                break
            time.sleep(0.1)
        assert ri.query(coin="LATE", limit=5)["total"] == 1, \
            "the timer never picked the new pair up"
    finally:
        ri.stop_keeping_up()


def test_an_old_shaped_index_is_rebuilt_not_trusted(store, monkeypatch):
    """The first index used WITHOUT ROWID with a text primary key, which made
    every insert a random write. Bumping the version has to REPLACE it — a
    stale-shaped table quietly keeps the old performance."""
    import sqlite3

    ri.sync()
    assert ri.query(limit=2000)["total"] == 24
    # forge an index built by the previous version
    con = sqlite3.connect(ri.DB_PATH)
    con.execute("INSERT OR REPLACE INTO meta (k,v) VALUES ('schema','1')")
    con.commit()
    con.close()
    ri._ready.clear()

    ri.ensure()
    assert ri.query(limit=2000)["total"] == 0, "old rows kept"
    assert ri.status()["pairs_indexed"] == 0, "the pair marks must go too"
    assert ri.sync()["pairs"] == 6, "every pair is stale again, so re-read"
    assert ri.query(limit=2000)["total"] == 24, "and the answer is restored"


def test_the_row_table_appends_rather_than_inserting_at_random(store):
    import sqlite3

    ri.sync()
    con = sqlite3.connect(ri.DB_PATH)
    sql = con.execute("SELECT sql FROM sqlite_master WHERE name='rows'"
                      ).fetchone()[0]
    con.close()
    assert "WITHOUT ROWID" not in sql.upper()


def test_no_call_leaves_a_connection_open(store):
    """`with sqlite3.connect(...)` commits but does NOT close. Leaked readers
    blocked the indexer for minutes: syncing:True with the pair count frozen."""
    import gc
    import sqlite3

    ri.sync()
    gc.collect()
    before = sum(1 for o in gc.get_objects() if isinstance(o, sqlite3.Connection))
    for _ in range(30):
        ri.query(limit=5)
        ri.facets()
        ri.status()
        ri.stale_pairs()
    gc.collect()
    after = sum(1 for o in gc.get_objects() if isinstance(o, sqlite3.Connection))
    assert after <= before, f"leaked {after - before} connections over 30 polls"


def test_reads_do_not_block_the_indexer(store):
    """The end-to-end property: hold readers open and the indexer still lands
    a pair. This is the failure the operator saw as a frozen count."""
    import json as _json
    import threading
    import time

    rows_dir, _ = store
    ri.sync()
    stop = threading.Event()

    def poll():
        while not stop.is_set():
            ri.query(limit=5)
            ri.status()

    readers = [threading.Thread(target=poll, daemon=True) for _ in range(4)]
    for t in readers:
        t.start()
    try:
        (rows_dir / "UNDERLOAD-1h.json").write_text(
            _json.dumps([_row("UNDERLOAD", "1h", "mom6", 4.0)]))
        t0 = time.time()
        got = ri.sync(now=time.time() + ri.SETTLE_S + 1)
        el = time.time() - t0
        assert got["pairs"] >= 1, "the indexer made no progress under readers"
        assert el < 10, f"indexing took {el:.1f}s with four readers polling"
    finally:
        stop.set()
    assert ri.query(coin="UNDERLOAD", limit=5)["total"] == 1


def test_nothing_the_ui_polls_scans_the_row_table(store):
    """query(), status() and facets() are polled every few seconds. A COUNT(*)
    over the rows is 25ms at 27k rows and unbounded at the sweep's real size —
    the per-pair counts already sum to the same number."""
    raw = open("tradingagents/rows_index.py", encoding="utf-8").read()
    # strip comments: an earlier version of this test matched the COMMENT that
    # explains the rule and failed on documentation, which is how a CSS block
    # once got anchored to a JavaScript comment in this repo.
    src = "\n".join(ln for ln in raw.splitlines()
                    if not ln.lstrip().startswith("#"))
    q = src[src.index("def query("):src.index("def facets(")]
    # a COUNT with a WHERE rides an index; the UNFILTERED one is the scan, and
    # it must come from the pair summaries instead
    assert 'COALESCE(SUM(n),0) FROM pairs' in q, \
        "the unfiltered total must come from the pair counts"
    assert q.index("if where:") < q.index("FROM rows{where}"), \
        "the row COUNT must sit behind the filtered branch only"
    # and even there it is BOUNDED: an exact filtered count is a full scan —
    # 30 s on the operator's 21,858,026-row store, and the proxy gave up at 30
    assert "LIMIT {COUNT_CAP + 1}" in q, \
        "the filtered count must stop at COUNT_CAP and report N+"
    for name, nxt in (("def facets(", "def status("),
                      ("def status(", "def start_keeping_up(")):
        body = src[src.index(name):src.index(nxt, src.index(name))]
        assert "FROM rows" not in body, f"{name} touches the row table at all"

    ri.sync()
    # and the unfiltered total still equals the truth
    from_files = sum(len(json.loads(p.read_text()))
                     for p in (msw.ROWDIR).glob("*.json"))
    assert ri.query(limit=1)["total"] == from_files
    assert ri.status()["rows"] == from_files


def test_the_indexer_never_takes_a_lock_that_blocks_a_reader():
    """wal_checkpoint(TRUNCATE) needs an EXCLUSIVE lock. Running it per sync
    cycle convoyed with the grid's 4-second poll: reads went from 0.04s to a
    25s timeout and the pair count froze at 26."""
    src = open("tradingagents/rows_index.py", encoding="utf-8").read()
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    for blocking in ("RESTART", "BEGIN EXCLUSIVE", "locking_mode"):
        assert blocking not in code, f"{blocking} blocks readers"
    # TRUNCATE is allowed in exactly ONE place and only above a size cap.
    # Running it every sync cycle convoyed with the grid's 4-second poll (reads
    # went 0.04s -> 25s, the pair count froze at 26). Never running it let the
    # WAL reach 27.4 GB and take the disk to 3.5 GB free. Both are real; the
    # cap is what separates them.
    assert code.count("wal_checkpoint(TRUNCATE)") == 1, \
        "TRUNCATE belongs in checkpoint_if_bloated and nowhere else"
    fn = code[code.index("def checkpoint_if_bloated"):]
    assert "wal_checkpoint(TRUNCATE)" in fn[:fn.index("def main")], \
        "the one TRUNCATE must be the size-gated one"
    assert "if before < cap" in fn, "it must be gated on the WAL's size"
    assert "wal_autocheckpoint" in code, "the passive checkpoint stays too"


def test_a_bulk_fill_drops_and_rebuilds_its_indexes_exactly_once(store,
                                                                 monkeypatch):
    """Dropping and rebuilding per cycle cost 4-8s of exclusive work every 60
    seconds and the fill stalled at 52 of 232 pairs."""

    rows_dir, _ = store
    for i in range(12):                    # over BULK_PAIRS
        (rows_dir / f"BULK{i}-1h.json").write_text(
            json.dumps([_row(f"BULK{i}", "1h", "mom6", float(i))]))

    ddl = []
    real_connect = ri._connect

    def traced(readonly=False):
        con = real_connect(readonly)
        con.set_trace_callback(
            lambda sql: ddl.append(sql) if "INDEX" in (sql or "").upper()
            else None)
        return con

    monkeypatch.setattr(ri, "_connect", traced)
    got = ri.sync(now=__import__("time").time() + ri.SETTLE_S + 1)
    assert got["left"] == 0, "a bulk pass must finish its backlog, not slice it"
    drops = [d for d in ddl if d.upper().startswith("DROP")]
    assert len(drops) == len(ri.FILTER_INDEXES), f"dropped {drops}"
    assert "rows_profit" not in " ".join(drops), (
        "the default view sorts by profit — that index must survive a fill")


def test_an_incremental_pass_still_respects_its_budget(store):
    """Only a bulk fill ignores the clock."""
    rows_dir, _ = store
    ri.sync()
    for i in range(3):                     # under BULK_PAIRS
        (rows_dir / f"SMALL{i}-1h.json").write_text(
            json.dumps([_row(f"SMALL{i}", "1h", "mom6", 1.0)]))
    got = ri.sync(budget_s=0.0001,
                  now=__import__("time").time() + ri.SETTLE_S + 1)
    assert got["pairs"] == 1 and got["left"] == 2, (
        f"budget ignored: did {got['pairs']}, left {got['left']}")


def test_the_indexer_yields_to_a_running_backtest(store, monkeypatch):
    """Measured 2026-08-22: with the sweep's seven workers on eight cores
    (load average 23-33) the same insert went from 0.25s to 16.42s, and a
    reader waiting on it timed out. The sweep is what the operator is waiting
    three days for.

    It used to TRICKLE one pair per cycle. Measured again on the PC on
    2026-08-26, store on a spinning HDD: trickling held the sweep to 36
    pairs/hour where killing the indexer gave 220 from the same eleven
    workers, and the trickle could never have drained the backlog anyway
    (production ~22 pairs/min against 6 indexed). So it now stands down
    COMPLETELY and takes the lot in one bulk pass afterwards -- see
    tests/test_index_yields_to_the_sweep.py."""
    import time

    rows_dir, _ = store
    for i in range(20):
        (rows_dir / f"MANY{i}-1h.json").write_text(
            json.dumps([_row(f"MANY{i}", "1h", "mom6", float(i))]))

    monkeypatch.setattr(ri, "_machine_is_busy", lambda: True)
    got = ri.sync(now=time.time() + ri.SETTLE_S + 1)
    assert got["pairs"] == 0, f"indexed {got['pairs']} pairs while sweeping"
    assert got["left"] >= 20, "and it must report the backlog honestly"
    assert ri.status()["paused"] is True, "the screen has to be able to say"

    # with the machine free it takes the lot
    monkeypatch.setattr(ri, "_machine_is_busy", lambda: False)
    got = ri.sync(now=time.time() + ri.SETTLE_S + 1)
    assert got["left"] == 0, f"idle machine still left {got['left']}"
    assert ri.status()["paused"] is False


def test_the_backlog_is_drained_in_one_bulk_pass_not_a_trickle():
    """A pause is only safe because the catch-up is the FAST path: BULK drops
    the four filter indexes, inserts, and rebuilds them once."""
    import inspect

    src = inspect.getsource(ri.sync)
    assert "bulk = len(todo) > BULK_PAIRS" in src
    assert ri.BULK_PAIRS <= 16, "a whole sweep's backlog must take the bulk path"


def test_the_api_does_not_index_in_its_own_process(monkeypatch, tmp_path):
    """Parsing a 9.7 MB file and building 18,000 tuples is pure Python and
    holds the GIL. Inside the API that made /api/jobs/backtest — one small
    file — take 1.7-2.2s and the health probe time out, which the header
    printed as "API unreachable"."""
    import inspect

    from tradingagents import api

    src = inspect.getsource(api._keep_the_row_index_current)
    assert "spawn_indexer" in src
    assert "start_keeping_up" not in src, (
        "start_keeping_up runs a thread IN this process — that is the bug")


def test_only_one_indexer_process_at_a_time(tmp_path, monkeypatch):
    """Two indexers would fight for SQLite's single write lock."""
    import os

    monkeypatch.setattr(ri, "PIDFILE", tmp_path / "rows_index.pid")
    (tmp_path / "rows_index.pid").write_text(str(os.getpid()))
    assert ri._running_elsewhere() is True
    assert ri.spawn_indexer() is None, "it spawned a second indexer"
    # a dead pid is not a running indexer
    (tmp_path / "rows_index.pid").write_text("999999")
    assert ri._running_elsewhere() is False


def test_the_storage_screen_reads_no_files_at_all(store, monkeypatch, tmp_path):
    """/api/backtest/storage parsed every row file AND every state file — over
    2 GB — on a route the Backtest page polls. Everything it needs now sits in
    the pairs table."""
    states = tmp_path / "state"
    states.mkdir()
    monkeypatch.setattr(msw, "STATES", states)
    (states / "BTC-1h.json").write_text(json.dumps({
        "__last_ms__": 1787000000000, "__version__": "signals75-th3",
        "combo|a": {}, "combo|b": {}}))
    ri.sync()

    got = {(r["coin"], r["tf"]): r for r in ri.pair_storage()}
    btc = got[("BTC", "1h")]
    assert btc["combos"] == 2, "the combination count comes from the state file"
    assert btc["version"] == "signals75-th3"
    assert btc["last_ms"] == 1787000000000
    assert btc["bytes"] > 0 and btc["n"] == 4

    # a pair with no state file is reported, not skipped
    assert got[("PI", "1h")]["combos"] == 0
    assert len(got) == 6

    # and the route itself opens nothing
    opened = []
    real = type(tmp_path).read_text
    monkeypatch.setattr(type(tmp_path), "read_text",
                        lambda self, *a, **k: (opened.append(self.name),
                                               real(self, *a, **k))[1])
    ri.pair_storage()
    assert not opened, f"pair_storage read files: {opened[:3]}"


def test_an_unindexed_state_is_unknown_not_interrupted(store, monkeypatch):
    """A pair whose state was never read printed "0 combinations, 0 B,
    interrupted" on screen while holding 12,960 measured rows. Unknown and
    zero are different facts."""
    import sqlite3

    ri.sync()
    con = sqlite3.connect(ri.DB_PATH)
    con.execute("UPDATE pairs SET combos=NULL, last_ms=NULL WHERE pair='BTC-1h'")
    con.commit()
    con.close()

    row = next(r for r in ri.pair_storage()
               if (r["coin"], r["tf"]) == ("BTC", "1h"))
    assert row["combos"] is None and row["last_ms"] is None, (
        "the index must pass NULL through, not coerce it to 0")

    from tradingagents import api

    out = api.backtest_storage()
    got = next(r for r in out["rows"] if (r["coin"], r["tf"]) == ("BTC", "1h"))
    assert got["incomplete"] is False, "unknown state claimed 'interrupted'"
    assert got["combos"] is None, "unknown count printed as zero"


def test_a_pair_that_finished_is_reindexed_even_if_its_rows_did_not_change(
        store, monkeypatch, tmp_path):
    """A pair FINISHING writes its watermark to the state file, not the row
    file. Watching only the row file left 392 completed pairs marked
    "interrupted part-way" on the storage screen, and it is the same field the
    completion percentage reads."""
    import time

    rows_dir, _ = store
    states = tmp_path / "state"
    states.mkdir()
    monkeypatch.setattr(msw, "STATES", states)
    (states / "BTC-1h.json").write_text(json.dumps({"__last_ms__": 0}))
    ri.sync()
    assert next(r for r in ri.pair_storage()
                if (r["coin"], r["tf"]) == ("BTC", "1h"))["last_ms"] == 0

    # the pair finishes: only the STATE file changes
    (states / "BTC-1h.json").write_text(json.dumps({"__last_ms__": 1787450400000}))
    assert ri.stale_watermark("BTC-1h") is True
    later = time.time() + ri.SETTLE_S + 1
    assert any(p.stem == "BTC-1h" for p in ri.stale_pairs(now=later)), \
        "the finished pair was not queued for re-indexing"
    ri.sync(now=later)
    got = next(r for r in ri.pair_storage()
               if (r["coin"], r["tf"]) == ("BTC", "1h"))
    assert got["last_ms"] == 1787450400000, "still showing the stale watermark"


def test_the_watermark_is_read_from_the_tail_not_the_whole_file():
    """State files reach 8.6 MB and there are thousands. Parsing them all to
    answer "how complete is the sweep?" timed out at five minutes."""
    import inspect

    src = inspect.getsource(msw.pair_watermark)
    assert "seek(" in src and "256" in src, "it must tail-read"
    assert "__last_ms__" in src
    # and it must still be correct when the tail does not match
    assert "json.loads" in src, "no fallback for an unexpected layout"


def test_the_write_ahead_log_cannot_grow_without_bound(store, monkeypatch):
    """SQLite's automatic checkpoint is PASSIVE: it cannot reclaim while any
    reader holds a snapshot. One abandoned query pinned it on 2026-08-24 and
    the WAL reached 27.4 GB beside a 13.8 GB database, taking the volume to
    3.5 GB free — the same wall that had already killed the sweep and the
    trading runner."""
    ri.sync()
    # the file itself is capped, so a checkpoint truncates rather than leaving
    # the high-water mark in place
    # through ri._connect, because journal_size_limit is a property of the
    # CONNECTION — a raw sqlite3.connect() would always report the default and
    # prove nothing about the connections this module actually uses
    con = ri._connect()
    limit = con.execute("PRAGMA journal_size_limit").fetchone()[0]
    mode = con.execute("PRAGMA journal_mode").fetchone()[0]
    con.close()
    assert mode.lower() == "wal"
    assert 0 < limit <= 1_073_741_824, f"journal_size_limit is {limit}"

    # and a bloated log is folded back in, while a small one is left alone
    assert ri.checkpoint_if_bloated()["checkpointed"] is False
    got = ri.checkpoint_if_bloated(cap=0)
    assert got["checkpointed"] is True

    # the indexer loop must actually call it, or the cap never fires
    import inspect

    src = inspect.getsource(ri.start_keeping_up)
    assert "checkpoint_if_bloated()" in src


def test_a_long_reader_is_what_pins_the_log(store):
    """Documents the mechanism, so the next person does not delete the cap."""
    import inspect

    doc = inspect.getdoc(ri.checkpoint_if_bloated) or ""
    assert "reader" in doc.lower() and "27.4" in doc
