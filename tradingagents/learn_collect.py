"""Land a finished LEARNED run on this PC — either of the two families.

* **Sep 25 Strat** (`LX`, `lx_` rows): .github/workflows/learn.yml; the
  formulas go to `signals_learned.LEARNED_FILE`, the report to
  `sep25_report.json`.
* **Sep 27 ML** (`ML`, `ml_` rows): .github/workflows/ml.yml; the decision-tree
  models go to `signals_ml.MODEL_FILE` (gzipped, capped at `ML.max_mb`), the
  report to `sep27_ml_report.json`. One stored row per kept model.

Both land through ONE body (`land`), so a fix to one is a fix to both. Each
workflow leaves three artifacts per machine: the rows it measured (Backtest
v2 rows, res="1m"), the formulas/models it kept, and a report line for every
coin+timeframe it attempted — kept or not, with the reason.

Rows for a pair the report does not account for: Sep 25 Strat REFUSES the
collect; Sep 27 ML drops them and names them in the result's `stray` (a
machine stopped mid-coin must not sink the rest).

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

    python -m tradingagents.learn_collect <run_id> [owner/repo]
                                          (Sep 25 Strat; re-execs itself in v2)
    python -m tradingagents.learn_collect --ml <run_id> [owner/repo]
                                          (Sep 27 ML, the same way)
    python -m tradingagents.learn_collect --usual-costs (the seed file)
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

USUAL_FILE = Path(__file__).resolve().parent / "learned" / "usual_costs.json"
REPORT_FILE = Path(__file__).resolve().parent / "learned" / "sep25_report.json"
ML_REPORT_FILE = Path(__file__).resolve().parent / "learned" / "sep27_ml_report.json"


@dataclass(frozen=True)
class Family:
    """One learned set: where its formulas live, its rows' prefix, its report,
    its GitHub artifacts and its partial index. Sep 25 Strat and Sep 27 ML
    land through ONE body, so a fix to one is a fix to both."""
    key: str
    prefix: str
    registry: str               # module with read_file / write_file / reload
    report_attr: str            # a module global, read at CALL time
    artifacts: tuple
    scratch: str
    index: str
    terms_attr: str             # rows_index global naming the family's rows
    max_mb: float | None = None


LX = Family("lx", "lx_", "tradingagents.signals_learned", "REPORT_FILE",
            ("learn-rows-*", "learn-formulas-*"), "learn", "rows_lx_profit",
            "LEARNED_TERMS")
ML = Family("ml", "ml_", "tradingagents.signals_ml", "ML_REPORT_FILE",
            ("ml-rows-*", "ml-models-*"), "ml", "rows_ml_profit", "ML_TERMS",
            max_mb=50.0)


def _registry(family: Family):
    import importlib

    return importlib.import_module(family.registry)


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


def download(run_id: int, slug: str | None = None, family: Family | None = None) -> Path:
    """The run's artifacts, unpacked on the STORE's drive (CLAUDE.md: big
    files go where the store is, never the system drive)."""
    from tradingagents import cloud_sweep as cs

    family = family or LX
    root = Path(cs._scratch()) / f"{family.scratch}-{run_id}"
    # THIS RUN'S OWN SCRATCH, emptied first: `gh run download` refuses to
    # write over files a previous attempt left ("file exists"), which is how
    # the re-run of a stopped collect failed on Sep 25, 2026. Nothing but
    # this run's unpacked artifacts lives here.
    if root.exists():
        import shutil

        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    cmd = ["gh", "run", "download", str(run_id), "-D", str(root)]
    for p in family.artifacts:
        cmd += ["-p", p]
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


def forget_verdicts(pairs: set) -> int:
    """Drop the old-data verdicts (learn_verify) of every coin+timeframe this
    run re-learned. A new run REUSES the names — lx_ETH_1h_1 is whatever the
    newest run kept first — so a verdict left behind would put a formula that
    was never tested into "Sep 25 Strat · passed old-data test" under the
    old one's pass (operator, Sep 28, 2026: *"So re create the group sept 25
    again"*). Returns how many verdicts went."""
    from tradingagents import learn_verify as lv

    try:
        raw = json.loads(lv.VERIFIED_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    rows = raw.get("formulas") or {}
    gone = [n for n, r in rows.items()
            if (str(r.get("coin")), str(r.get("tf"))) in pairs]
    if not gone:
        return 0
    for n in gone:
        rows.pop(n)
    counts: dict = {}
    for r in rows.values():
        counts[r.get("status")] = counts.get(r.get("status"), 0) + 1
    raw.update(formulas=rows, counts=counts)
    tmp = lv.VERIFIED_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(raw, indent=0), encoding="utf-8")
    tmp.replace(lv.VERIFIED_FILE)
    return len(gone)


def land(formulas: dict, report: list, rows: dict, *, run_id=None,
         family: Family | None = None) -> dict:
    """Write one run into the v2 store and its formula/model file. See module
    doc. `family` picks Sep 25 Strat (lx_, the default) or Sep 27 ML (ml_) —
    same body, different registry, prefix, report file and partial index."""
    from tradingagents import market_sweep as msw
    from tradingagents.positions_view import fmt_when

    family = family or LX
    reg = _registry(family)
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
    # loss over the period it was CHOSEN on is not kept here, and its rows go
    # with it. That period is `validate` since Sep 26, 2026; a file from
    # before then chose on `unseen`, so for those the old rule stands. A
    # formula that carries `validate` is NEVER dropped for its unseen
    # result: that number is the test, and dropping the losers would make
    # the test a choice again (formula_learner's docstring, "WHY THREE").
    def _chosen_profit(f):
        lr = f.get("learned") or {}
        chosen_on = lr.get("validate") if "validate" in lr else lr.get("unseen")
        return (chosen_on or {}).get("profit")

    # only a RECORDED loss: a formula whose file carries no grade is not
    # judged by a default that reads as data
    losing = {n for n, f in formulas.items()
              if _chosen_profit(f) is not None and float(_chosen_profit(f)) <= 0}
    if losing:
        formulas = {n: f for n, f in formulas.items() if n not in losing}
        rows = {k: [r for r in rs if str(r.get("signal")) not in losing]
                for k, rs in rows.items()}
    stray = sorted({k for k in rows if k not in attempted and rows[k]})
    dropped: list = []
    if stray and family is LX:
        raise ValueError(f"rows for pairs the report does not account for: "
                         f"{stray[:5]}")
    if stray:
        # SEP 27 ML: a machine stopped mid-coin (a GitHub timeout, a cancel)
        # can leave rows whose timeframe never reached the report. Those rows
        # are DROPPED and NAMED — one unfinished timeframe must not sink the
        # whole collect (Sep 27 ML final review, F3). Sep 25 Strat keeps its
        # refusal above, as it always had.
        dropped = [f"{c} {t}" for c, t in stray]
        rows = {k: rs for k, rs in rows.items() if k not in set(stray)}
    # the formula/model file: that pair's old formulas out, the new ones in
    old_f = reg.read_file()
    # which pairs carry rows NOW: exactly the pairs with a formula/model in
    # the file (rows are only ever written for kept ones). Only those and the
    # pairs with new rows are rewritten — never all ~5,000 attempted pair
    # files at ~5 MB each for nothing.
    had = {(str(v.get("coin")), str(v.get("tf"))) for v in old_f.values()}
    have = {k: v for k, v in old_f.items()
            if (str(v.get("coin")), str(v.get("tf"))) not in attempted}
    have.update({k: v for k, v in formulas.items()
                 if (str(v.get("coin")), str(v.get("tf"))) in attempted})
    reg.write_file(dict(sorted(have.items())), run_id,
                   max_bytes=int(family.max_mb * 1_000_000) if family.max_mb else None)
    if family is LX:
        forget_verdicts(attempted)
    # the rows, pair by pair: FILES first (each under its lock), then ONE
    # index pass in batches (see file_learned)
    landed = refiled = 0
    to_file: list = []
    for coin, tf in sorted(attempted):
        new = rows.get((coin, tf), [])
        old_lx: set = set()

        def swap(old, new=new, old_lx=old_lx):
            # under the pair's lock (market_sweep.rewrite_pair_rows): the old
            # rows of this family out, the new in, every other row untouched
            old_lx.update(str(r.get("signal")) for r in old
                          if str(r.get("signal", "")).startswith(family.prefix))
            return [r for r in old
                    if not str(r.get("signal", "")).startswith(family.prefix)] + new

        if not new and (coin, tf) not in had:
            continue                 # nothing to add and nothing to remove
        msw.rewrite_pair_rows(coin, tf, swap)
        if not new and not old_lx:
            continue
        landed += len(new)
        names = old_lx | {str(r["signal"]) for r in new}
        to_file.append((msw.ROWDIR / f"{coin}-{tf}.json", sorted(names)))
    refiled = file_learned(to_file, family=family)
    # the report, without the round-by-round detail
    # MERGED, pair by pair, like the formula file: a run replaces the lines of
    # the coins+timeframes it reported on and keeps everyone else's. Written
    # whole each time, the second account's collect would have erased the
    # first account's half of the market from the report (found before the
    # second collect, Sep 26, 2026).
    slim = [{k: v for k, v in e.items() if k != "rounds_detail"} | {"run": run_id}
            for e in report]
    mine = {(str(e["coin"]), str(e.get("tf"))) for e in slim}
    report_file = globals()[family.report_attr]
    old = []
    try:
        old = json.loads(report_file.read_text(encoding="utf-8")).get("report") or []
    except (OSError, ValueError):
        old = []
    kept_old = [e for e in old if (str(e.get("coin")), str(e.get("tf"))) not in mine]
    report_file.write_text(json.dumps({"collected": fmt_when(time.time()),
                                       "report": kept_old + slim}, indent=0),
                           encoding="utf-8")
    result = {"pairs": len(attempted), "formulas": len(formulas), "rows": landed,
              "indexed": refiled}
    if dropped:
        result["stray"] = sorted(dropped)
    return result


# pairs per index transaction, and the page cache that lets a batch write each
# scattered index page once instead of once per pair
FILE_BATCH = 100
FILE_CACHE_MB = 1024


def file_learned(entries: list, log=print, family: Family | None = None) -> int:
    """Re-file the rules of many pairs in the v2 index, FILE_BATCH pairs per
    transaction on one connection with a large page cache.

    Pair by pair (index_pair's own commit) measured ~20 s a pair on the
    operator's 15 GB table on a spinning disk — about seven hours for one
    account's ~1,300 pairs — because each commit flushes pages of nine
    indexes scattered across the file. Same rows, same deletes by pair and
    signal, same `pairs` bookkeeping: only the commits are grouped. A crash
    mid-way loses at most the open batch, and a re-run re-files it (the
    files already hold the new rows; the delete-by-signal is idempotent)."""
    import time as _t

    from tradingagents import rows_index as ri

    family = family or LX
    if not entries:
        return 0
    con = ri._connect()
    n = 0
    t0 = _t.time()
    try:
        con.execute(f"PRAGMA cache_size = -{FILE_CACHE_MB * 1024}")
        # WHICH PAIRS ALREADY HAVE THIS FAMILY'S ROWS FILED — one read of the
        # small slice (its own partial index serves it), instead of a delete
        # per rule that walks each coin's ~13,000 rows to find nothing. A
        # pair not in this set is filed `fresh` (no delete).
        # INDEXED BY the partial index: left to itself the planner walked
        # rows_pair — every row's key, 244.6 s on the operator's store — to
        # find 68 pairs. Without that index (a new store) the plain query.
        import sqlite3 as _sq

        terms = getattr(ri, family.terms_attr)
        try:
            filed_before = {r[0] for r in con.execute(
                f"SELECT DISTINCT pair FROM rows INDEXED BY {family.index} "
                f"WHERE {terms}")}
        except _sq.OperationalError:
            filed_before = {r[0] for r in con.execute(
                f"SELECT DISTINCT pair FROM rows WHERE {terms}")}
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


def collect(run_id: int, slug: str | None = None, family: Family | None = None) -> dict:
    from tradingagents import db_jobs as dj

    family = family or LX
    # ONE JOB ON THE DISK: a v2 sweep, collect or rebuild holding the store
    # is named, never raced (the rule start() and resume_if_died share)
    holder = dj.disk_holder("collect_v2")
    if holder:
        raise RuntimeError(f"{holder} is running — one job at a time on the "
                           f"store; collect when it finishes")
    root = download(run_id, slug, family=family)
    formulas, report, rows = read_run(root)
    return land(formulas, report, rows, run_id=run_id, family=family)


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--usual-costs":
        got = build_usual_costs()
        print(f"usual costs for {len(got)} coin(s) -> {USUAL_FILE}")
        return 0
    if not _in_v2():
        # the v2 roots travel as environment, read at import (stores.py), so
        # the collect runs as a child process with them set. The original
        # argv (including --ml) travels unchanged — the child parses it again.
        from tradingagents import stores

        env = {**os.environ, **stores.V2.env_for(), "PYTHONUNBUFFERED": "1"}
        return subprocess.call([sys.executable, "-m", "tradingagents.learn_collect",
                                *argv], env=env)
    family = ML if argv and argv[0] == "--ml" else LX
    argv = [a for a in argv if a != "--ml"]
    run_id = int(argv[0])
    slug = argv[1] if len(argv) > 1 else None
    print(json.dumps(collect(run_id, slug, family=family)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
