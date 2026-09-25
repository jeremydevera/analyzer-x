"""Land a finished LEARNED-formula run ("Sep 25 Strat") on this PC.

.github/workflows/learn.yml leaves three artifacts per machine: the rows it
measured (Backtest v2 rows, res="1m"), the formulas it kept, and a report line
for every coin+timeframe it attempted — kept or not, with the reason.

What this does, per coin+timeframe the run ATTEMPTED (and only those):

* the formulas: that pair's old learned formulas are replaced by the new ones
  in `signals_learned.LEARNED_FILE` (the file the grid, the trade log, the
  UPDATE button and the runner all read — commit it after collecting);
* the rows: that pair's old `lx_` rows are removed from its pair file and the
  new ones added, every other row untouched; then ONLY those formulas are
  re-filed in the v2 index (`rows_index.index_pair(signals=...)`).

What it never does: move a pair's watermark or state file. A learned run
measured the learned formulas only, and telling the store the whole pair was
measured would make the next market-grid collect refuse its fresher rows as
"stale" (`cloud_sweep.is_fresher`).

A pair the run did not attempt, or whose attempt raised, keeps everything it
had. Run it in the v2 environment:

    python -m tradingagents.learn_collect <run_id>      (re-execs itself in v2)
    python -m tradingagents.learn_collect --usual-costs (the seed file)
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import time
from pathlib import Path

USUAL_FILE = Path(__file__).resolve().parent / "learned" / "usual_costs.json"
REPORT_FILE = Path(__file__).resolve().parent / "learned" / "sep25_report.json"


def _in_v2() -> bool:
    from tradingagents import market_sweep as msw

    return msw.FINE_TF == "1m"


def build_usual_costs(sample: int = 200) -> dict:
    """coin -> the median round trip (fraction) its Backtest v2 rows were
    charged. The GitHub machines seed each coin's cost readings with it, so a
    book read while a stock coin's market is shut is a spike and not the price
    (backtest_report.charged_slippage) — the same seed the PC's own UPDATE
    uses (market_sweep._rows_slippage)."""
    import sqlite3
    import statistics

    from tradingagents import stores

    con = sqlite3.connect(f"file:{stores.V2.rows_db}?mode=ro", uri=True)
    try:
        coins = [r[0] for r in con.execute("SELECT DISTINCT coin FROM pairs")]
        out = {}
        for c in sorted(coins):
            rts = [float(r[0]) for r in con.execute(
                "SELECT rt FROM rows WHERE coin = ? AND rt IS NOT NULL LIMIT ?",
                (c, sample))]
            if rts:
                out[str(c).upper()] = round(statistics.median(rts) / 100.0, 8)
    finally:
        con.close()
    from tradingagents.positions_view import fmt_when

    USUAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    USUAL_FILE.write_text(json.dumps({
        "about": "median round-trip cost (fraction) of each coin's Backtest v2 "
                 "rows; seeds the learned run's cost readings",
        "built": fmt_when(time.time()), "rt": out}, indent=0, sort_keys=True),
        encoding="utf-8")
    return out


def download(run_id: int, slug: str | None = None) -> Path:
    """The run's learn-* artifacts, unpacked on the STORE's drive (CLAUDE.md:
    big files go where the store is, never the system drive)."""
    from tradingagents import cloud_sweep as cs

    root = Path(cs._scratch()) / f"learn-{run_id}"
    # THIS RUN'S OWN SCRATCH, emptied first: `gh run download` refuses to
    # write over files a previous attempt left ("file exists"), which is how
    # the re-run of a stopped collect failed on Sep 25, 2026. Nothing but
    # this run's unpacked artifacts lives here.
    if root.exists():
        import shutil

        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    cmd = ["gh", "run", "download", str(run_id), "-D", str(root),
           "-p", "learn-rows-*", "-p", "learn-formulas-*"]
    if slug:
        cmd += ["-R", slug]
    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=1800)
    return root


def read_run(root: Path) -> tuple[dict, list, dict]:
    """(formulas, report entries, rows by (coin, tf)) from an unpacked run."""
    formulas: dict = {}
    report: list = []
    rows: dict = {}
    for f in glob.glob(str(root / "**" / "formulas-*.json"), recursive=True):
        formulas.update(json.loads(Path(f).read_text(encoding="utf-8")).get("formulas") or {})
    for f in glob.glob(str(root / "**" / "report-*.json"), recursive=True):
        report += json.loads(Path(f).read_text(encoding="utf-8")).get("report") or []
    for f in glob.glob(str(root / "**" / "rows-*.jsonl"), recursive=True):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                if r.get("pair_done"):
                    continue
                rows.setdefault((str(r["coin"]), str(r["tf"])), []).append(r)
    return formulas, report, rows


def land(formulas: dict, report: list, rows: dict, *, run_id=None) -> dict:
    """Write one run into the v2 store and the formula file. See module doc."""
    from tradingagents import market_sweep as msw, signals_learned as sl_
    from tradingagents.positions_view import fmt_when

    if not _in_v2():
        raise RuntimeError("learned rows belong to Backtest v2 — run this in "
                           "the v2 environment (stores.V2.env_for())")
    # THE PAIRS THIS RUN ANSWERED FOR: every coin+timeframe it reported on
    # without an error. A failed attempt keeps what it had.
    attempted = {(str(e["coin"]), str(e["tf"])) for e in report
                 if e.get("tf") not in (None, "*") and not e.get("error")}
    bad = sorted({str(r.get("res") or "") for rs in rows.values() for r in rs}
                 - {msw.FINE_TF})
    if bad:
        raise ValueError(f"rows measured at res={bad[0]!r} cannot land in the "
                         f"v2 store (res={msw.FINE_TF!r})")
    # THE KEEP RULE, AGAIN, where the rows land: a formula the run kept at a
    # loss over its unseen period is not kept here (runs started before the
    # learner enforced profit > 0 could hand one over), and its rows go with it
    def _unseen_profit(f):
        return ((f.get("learned") or {}).get("unseen") or {}).get("profit")

    # only a RECORDED loss: a formula whose file carries no grade is not
    # judged by a default that reads as data
    losing = {n for n, f in formulas.items()
              if _unseen_profit(f) is not None and float(_unseen_profit(f)) <= 0}
    if losing:
        formulas = {n: f for n, f in formulas.items() if n not in losing}
        rows = {k: [r for r in rs if str(r.get("signal")) not in losing]
                for k, rs in rows.items()}
    stray = sorted({k for k in rows if k not in attempted and rows[k]})
    if stray:
        raise ValueError(f"rows for pairs the report does not account for: "
                         f"{stray[:5]}")
    # the formula file: that pair's old learned formulas out, the new ones in
    raw = {}
    try:
        raw = json.loads(sl_.LEARNED_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    # which pairs carry learned rows NOW: exactly the pairs with a formula in
    # the file (rows are only ever written for kept formulas). Only those and
    # the pairs with new rows are rewritten — never all ~5,000 attempted pair
    # files at ~5 MB each for nothing.
    had = {(str(v.get("coin")), str(v.get("tf")))
           for v in (raw.get("formulas") or {}).values()}
    have = {k: v for k, v in (raw.get("formulas") or {}).items()
            if (str(v.get("coin")), str(v.get("tf"))) not in attempted}
    have.update({k: v for k, v in formulas.items()
                 if (str(v.get("coin")), str(v.get("tf"))) in attempted})
    sl_.LEARNED_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = sl_.LEARNED_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({
        "about": "Sep 25 Strat — learned formulas, one set per coin and "
                 "timeframe (tradingagents/formula_learner.py)",
        "run": run_id, "collected": fmt_when(time.time()),
        "formulas": dict(sorted(have.items()))}, indent=1, sort_keys=False),
        encoding="utf-8")
    tmp.replace(sl_.LEARNED_FILE)
    sl_.reload()
    # the rows, pair by pair: FILES first (each under its lock), then ONE
    # index pass in batches (see file_learned)
    landed = refiled = 0
    to_file: list = []
    for coin, tf in sorted(attempted):
        new = rows.get((coin, tf), [])
        old_lx: set = set()

        def swap(old, new=new, old_lx=old_lx):
            # under the pair's lock (market_sweep.rewrite_pair_rows): the old
            # learned rows out, the new in, every other row untouched
            old_lx.update(str(r.get("signal")) for r in old
                          if str(r.get("signal", "")).startswith(sl_.PREFIX))
            return [r for r in old
                    if not str(r.get("signal", "")).startswith(sl_.PREFIX)] + new

        if not new and (coin, tf) not in had:
            continue                 # nothing to add and nothing to remove
        msw.rewrite_pair_rows(coin, tf, swap)
        if not new and not old_lx:
            continue
        landed += len(new)
        names = old_lx | {str(r["signal"]) for r in new}
        to_file.append((msw.ROWDIR / f"{coin}-{tf}.json", sorted(names)))
    refiled = file_learned(to_file)
    # the report, without the round-by-round detail
    # MERGED, pair by pair, like the formula file: a run replaces the lines of
    # the coins+timeframes it reported on and keeps everyone else's. Written
    # whole each time, the second account's collect would have erased the
    # first account's half of the market from the report (found before the
    # second collect, Sep 26, 2026).
    slim = [{k: v for k, v in e.items() if k != "rounds_detail"} | {"run": run_id}
            for e in report]
    mine = {(str(e["coin"]), str(e.get("tf"))) for e in slim}
    old = []
    try:
        old = json.loads(REPORT_FILE.read_text(encoding="utf-8")).get("report") or []
    except (OSError, ValueError):
        old = []
    kept_old = [e for e in old if (str(e.get("coin")), str(e.get("tf"))) not in mine]
    REPORT_FILE.write_text(json.dumps({"collected": fmt_when(time.time()),
                                       "report": kept_old + slim}, indent=0),
                           encoding="utf-8")
    return {"pairs": len(attempted), "formulas": len(formulas), "rows": landed,
            "indexed": refiled}


# pairs per index transaction, and the page cache that lets a batch write each
# scattered index page once instead of once per pair
FILE_BATCH = 100
FILE_CACHE_MB = 1024


def file_learned(entries: list, log=print) -> int:
    """Re-file the learned rules of many pairs in the v2 index, FILE_BATCH
    pairs per transaction on one connection with a large page cache.

    Pair by pair (index_pair's own commit) measured ~20 s a pair on the
    operator's 15 GB table on a spinning disk — about seven hours for one
    account's ~1,300 pairs — because each commit flushes pages of nine
    indexes scattered across the file. Same rows, same deletes by pair and
    signal, same `pairs` bookkeeping: only the commits are grouped. A crash
    mid-way loses at most the open batch, and a re-run re-files it (the
    files already hold the new rows; the delete-by-signal is idempotent)."""
    import time as _t

    from tradingagents import rows_index as ri

    if not entries:
        return 0
    con = ri._connect()
    n = 0
    t0 = _t.time()
    try:
        con.execute(f"PRAGMA cache_size = -{FILE_CACHE_MB * 1024}")
        # WHICH PAIRS ALREADY HAVE LEARNED ROWS FILED — one read of the small
        # learned-rows slice (the rows_lx_* partial index serves it), instead
        # of a delete per rule that walks each coin's ~13,000 rows to find
        # nothing. A pair not in this set is filed `fresh` (no delete).
        # INDEXED BY the partial index: left to itself the planner walked
        # rows_pair — every row's key, 244.6 s on the operator's store — to
        # find 68 pairs. Without that index (a new store) the plain query.
        import sqlite3 as _sq

        try:
            filed_before = {r[0] for r in con.execute(
                f"SELECT DISTINCT pair FROM rows INDEXED BY rows_lx_profit "
                f"WHERE {ri.LEARNED_TERMS}")}
        except _sq.OperationalError:
            filed_before = {r[0] for r in con.execute(
                f"SELECT DISTINCT pair FROM rows WHERE {ri.LEARNED_TERMS}")}
        for i, (path, names) in enumerate(entries, 1):
            n += ri.index_pair(path, con, signals=names, commit=False,
                               fresh=path.stem not in filed_before)
            if i % FILE_BATCH == 0 or i == len(entries):
                con.commit()
                log(f"filed {i:,} of {len(entries):,} pair(s), {n:,} row(s), "
                    f"{_t.time() - t0:.0f}s")
    finally:
        con.close()
    return n


def collect(run_id: int, slug: str | None = None) -> dict:
    from tradingagents import db_jobs as dj

    # ONE JOB ON THE DISK: a v2 sweep, collect or rebuild holding the store
    # is named, never raced (the rule start() and resume_if_died share)
    holder = dj.disk_holder("collect_v2")
    if holder:
        raise RuntimeError(f"{holder} is running — one job at a time on the "
                           f"store; collect when it finishes")
    root = download(run_id, slug)
    formulas, report, rows = read_run(root)
    return land(formulas, report, rows, run_id=run_id)


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--usual-costs":
        got = build_usual_costs()
        print(f"usual costs for {len(got)} coin(s) -> {USUAL_FILE}")
        return 0
    if not _in_v2():
        # the v2 roots travel as environment, read at import (stores.py), so
        # the collect runs as a child process with them set
        from tradingagents import stores

        env = {**os.environ, **stores.V2.env_for(), "PYTHONUNBUFFERED": "1"}
        return subprocess.call([sys.executable, "-m", "tradingagents.learn_collect",
                                *argv], env=env)
    run_id = int(argv[0])
    slug = argv[1] if len(argv) > 1 else None
    print(json.dumps(collect(run_id, slug)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
