"""Land the PRO TRADER STORE run in Backtest v2 as the group "Oct 21".

The operator, Oct 20, 2026, after the Pro Trader research: *"okay deploy this
i want this new batch as group 'Oct 21'"* — the group filter of Stored
strategies, beside "Sep 25 Strat" and "Sep 27 ML".

The machines (.github/workflows/pro.yml with store=1 ->
.github/scripts/pro_store_shard.py) measure every Pro Trader setting as
Backtest v2 rows; this brings them home and lands them the way the learned
families land (learn_collect), through the same two steps:

* the pair files: each coin + timeframe the run ANSWERED for (a report line
  with no error) has its old `pt_` rows replaced by the new ones under the
  pair's lock (`market_sweep.rewrite_pair_rows`); every other row is
  untouched, and the pair's watermark and state file NEVER move (the nightly
  grid does not measure pt_, so telling the store a pair was measured would
  make the next collect refuse its fresher rows);
* the index: only those pt_ rules re-filed, a hundred pairs a transaction
  (`learn_collect.file_learned`), each hundred as soon as it is rewritten
  (Oct 22, 2026: rewriting every pair first left thousands behind the list
  for hours, long enough for its safety net to start a whole rebuild under
  the landing), then the group's own sort index started.

ONE BODY FOR EVERY GROUP LANDED THIS WAY (`Group`): "Oct 21" here, "Oct 22"
(the confluence picks, tradingagents/cq_store.py) through the same `land`.

The rows are STREAMED, one coin + timeframe at a time (a machine writes a
pair's rows together, once the pair is measured): the whole market is about
1.8 million rows, several GB as Python objects. Rows for a pair the report
does not account for (a machine stopped mid-coin) are dropped and NAMED,
never landed half; a pair met twice keeps its later rows; a row measured at
another resolution, or that is not a pt_ rule, is refused. Run it in the v2
environment (it re-execs itself):

    python -m tradingagents.pro_store collect [state-name]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from tradingagents import learn_collect as lc

PT = lc.Family("pt", "pt_", "", "", ("pro-out-*",), "pro-store", "rows_pt_profit", "PRO_TERMS")
REPORT_FILE = Path(__file__).resolve().parent / "learned" / "oct21_report.json"


@dataclass(frozen=True)
class Group:
    """One batch of rules landed as a group of Stored strategies: the group's
    key in rows_index.GROUPS, its name on the screen, its rows' family, the
    machines' row files, and where the landing's report goes (a function, so
    the module global is read at CALL time)."""
    key: str
    label: str
    family: lc.Family
    rows_glob: str
    report_file: Callable[[], Path]


OCT21 = Group("oct21", "Oct 21", PT, "pro-rows-*.jsonl", lambda: REPORT_FILE)


def pairs_in(roots, pattern: str = OCT21.rows_glob):
    """Yield (coin, tf, rows) per run of one pair's rows in every machine's
    rows file, and the files whose last line was cut (in `pairs_in.cut`)."""
    from tradingagents import pro_search as ps

    pairs_in.cut = []
    for f in ps.files(roots, pattern):
        cur, buf = None, []
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    pairs_in.cut.append(str(f))
                    continue
                if r.get("pair_done"):
                    continue
                key = (str(r["coin"]), str(r["tf"]))
                if key != cur:
                    if buf:
                        yield cur[0], cur[1], buf
                    cur, buf = key, []
                buf.append(r)
        if buf:
            yield cur[0], cur[1], buf


pairs_in.cut = []


def _check(rows: list, group: Group = OCT21) -> None:
    bad = sorted({str(r.get("res") or "") for r in rows} - {"1m"})
    if bad:
        raise ValueError(f"rows measured at res={bad[0]!r} cannot land in the v2 store")
    wrong = sorted({str(r.get("signal")) for r in rows
                    if not str(r.get("signal", "")).startswith(group.family.prefix)})
    if wrong:
        raise ValueError(f"the store run carries rows that are not {group.label}'s: {wrong[:5]}")


def land(report: list, roots, *, run=None, group: Group = OCT21) -> dict:
    """Write one store run into the v2 store. See module doc."""
    from tradingagents import market_sweep as msw, rows_index as ri
    from tradingagents.positions_view import fmt_when

    fam = group.family
    if msw.FINE_TF != "1m":
        raise RuntimeError(f"the {group.label} rows belong to Backtest v2 — run this in the v2 "
                           "environment (stores.V2.env_for())")
    attempted = {(str(e["coin"]), str(e["tf"])) for e in report
                 if e.get("tf") not in (None, "*") and not e.get("error")}
    # every pair's rows, checked before ANY pair file is touched
    seen: dict = {}
    for coin, tf, rows in pairs_in(roots, group.rows_glob):
        _check(rows, group)
        seen[(coin, tf)] = seen.get((coin, tf), 0) + 1
    twice = sorted(k for k, n in seen.items() if n > 1)
    stray = sorted(k for k in seen if k not in attempted)
    landed = filed = pairs_filed = 0
    pending: list = []
    known: list = []                  # the pairs already holding the family's rows, asked once
    done: set = set()

    def flush() -> None:
        # EACH BATCH FILED AS SOON AS IT IS REWRITTEN: a rewritten pair is
        # behind the list until it is filed, and the list's safety net files
        # (or rebuilds) whatever has been behind it for 30 minutes
        # (rows_index.keep_list_filed)
        nonlocal filed
        if not pending:
            return
        if not known:
            con = ri._connect()
            try:
                known.append(lc.filed_pairs(con, fam))
            finally:
                con.close()
        filed += lc.file_learned(list(pending), family=fam, filed_before=known[0])
        pending.clear()

    def put(coin: str, tf: str, new: list) -> None:
        nonlocal landed, pairs_filed
        old_fam: set = set()

        def swap(old, new=new, old_fam=old_fam):
            # under the pair's lock: the family's old rows out, the new in,
            # every other row untouched
            old_fam.update(str(r.get("signal")) for r in old
                           if str(r.get("signal", "")).startswith(fam.prefix))
            return [r for r in old if not str(r.get("signal", "")).startswith(fam.prefix)] + new

        path = msw.ROWDIR / f"{coin}-{tf}.json"
        if not new and (not path.exists() or not any(
                str(r.get("signal", "")).startswith(fam.prefix) for r in msw.pair_rows(coin, tf))):
            return                    # nothing to add and nothing to remove
        msw.rewrite_pair_rows(coin, tf, swap)
        if new or old_fam:
            landed += len(new)
            pairs_filed += 1
            pending.append((path, sorted(old_fam | {str(r["signal"]) for r in new})))
            if len(pending) >= lc.FILE_BATCH:
                flush()

    counts: dict = {}
    for coin, tf, rows in pairs_in(roots, group.rows_glob):
        key = (coin, tf)
        if key not in attempted:
            continue
        counts[key] = counts.get(key, 0) + 1
        if counts[key] < seen[key]:
            continue                  # a pair met twice keeps its LATER rows
        put(coin, tf, rows)
        done.add(key)
    # an answered pair with no rows this time loses the family's rows it had
    for coin, tf in sorted(attempted - done):
        put(coin, tf, [])
    flush()
    report_file = group.report_file()
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(json.dumps({"collected": fmt_when(time.time()), "run": run,
                                       "report": report}, indent=0), encoding="utf-8")
    out = {"pairs": len(attempted), "rows": landed, "indexed": filed,
           "pairs_filed": pairs_filed}
    if stray:
        out["stray"] = [f"{c} {t}" for c, t in stray]
    if twice:
        out["twice"] = [f"{c} {t}" for c, t in twice]
    if pairs_in.cut:
        out["cut"] = sorted(set(pairs_in.cut))
    return out


def start_group_index(group: Group = OCT21) -> bool:
    """The group's own profit index, so the group ranked by profit is a seek
    the moment the operator opens it (the 503-and-build contract builds it
    otherwise on the first look)."""
    from tradingagents import rows_index as ri

    return ri._build_index(ri.group_index(group.key, "profit"))


def collect(state_name: str | None = None) -> dict:
    """Bring a finished store run home (both accounts) and land it."""
    from tradingagents import db_jobs as dj, pro_search as ps

    holder = dj.disk_holder("collect_v2")
    if holder:
        raise RuntimeError(f"{holder} is running — one job at a time on the store; "
                           f"collect when it finishes")
    got = ps.collect(state_name or ps.STORE_STATE)
    report = ps.read_json_parts(got["roots"], "pro-store-report-*.json", "report")
    result = land(report, got["roots"], run=got["runs"])
    result["coverage"] = got["coverage"]
    result["group_index"] = start_group_index()
    return result


def main(argv: list[str]) -> int:
    from tradingagents import market_sweep as msw

    if msw.FINE_TF != "1m":
        from tradingagents import stores

        env = {**os.environ, **stores.V2.env_for(), "PYTHONUNBUFFERED": "1"}
        return subprocess.call([sys.executable, "-m", "tradingagents.pro_store", *argv], env=env)
    if argv and argv[0] == "collect":
        got = collect(argv[1] if len(argv) > 1 else None)
        cov = got.get("coverage") or {}
        got["coverage"] = {**cov, "not_reached": (cov.get("not_reached") or [])[:50],
                           "pairs_failed": (cov.get("pairs_failed") or [])[:50]}
        print(json.dumps(got, indent=2, ensure_ascii=False))
        return 0
    print("usage: python -m tradingagents.pro_store collect [state-name]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
