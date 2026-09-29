"""Bring a finished watcher-replay run home and replay the watcher over it.

Operator, `Sep 28, 2026`: *"Then do the backtest replay so i know the pnl for
every day to know if my plan has relevenave"*.

`.github/workflows/replay.yml` leaves one artifact per machine: the
combinations that could ever pass (`replay-<N>.jsonl`, every trade) and the
machine's counts (`replay-report-<N>.json`). This downloads them BESIDE THE
STORE (`cloud_sweep._scratch()`, never C:), merges them, cuts every coin to
ONE common end (the earliest last bar any machine saw — a trade that closed
after it on a later machine is treated as still open, so no coin sees further
into the future than another), runs `watcher_replay.simulate`, and writes the
result to `~/.tradingagents/replay/<run>.json`.

    python -m tradingagents.replay_collect <run_id> [--repo owner/name]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import tempfile
from pathlib import Path

from tradingagents import watcher_policy as wp
from tradingagents import watcher_replay as wr

OUT_DIR = Path(os.path.expanduser("~/.tradingagents")) / "replay"


def group_of(sig: str) -> str:
    """The Stored strategies group of a signal (rows_index.GROUP_PREFIXES) —
    for combinations written before the machine tagged them."""
    from tradingagents import rows_index as ri

    for g, prefixes in ri.GROUP_PREFIXES.items():
        if str(sig).startswith(tuple(prefixes)):
            return g
    return "classic"


def combo_files(folder) -> list[str]:
    """Every machine's combination file under `folder` (a path or a list)."""
    folders = [folder] if isinstance(folder, str) else list(folder)
    return [f for d in folders for f in sorted(glob.glob(
        os.path.join(d, "**", "replay-*.jsonl"), recursive=True))]


def merge_reports(folder) -> dict:
    """The machines' counts only — `merge` without reading a single trade,
    for a caller that streams the combinations itself (watcher_research)."""
    return merge(folder, _combos=False)["totals"]


def merge(folder, _combos: bool = True) -> dict:
    """Every machine's combinations and counts under `folder` (one path, or a
    list of them — one per run), merged.

    A coin is claimed by exactly one machine, so an id seen twice is the same
    combination written twice (a retried coin) and is kept once."""
    combos: dict[str, dict] = {}
    totals = {"coins_board": 0, "coins_done": 0, "pairs": 0, "tested": 0,
              "kept": 0, "machines": 0, "failed": {}, "short": [],
              "spans": {}, "start": "", "tz": "", "cfg": {}, "groups": []}
    folders = [folder] if isinstance(folder, str) else list(folder)
    files = [f for d in folders for f in sorted(glob.glob(
        os.path.join(d, "**", "replay-*.jsonl"), recursive=True))]
    reports = [f for d in folders for f in sorted(glob.glob(
        os.path.join(d, "**", "replay-report-*.json"), recursive=True))]
    for f in (files if _combos else []):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    c = json.loads(line)
                    c.setdefault("group", group_of(c["signal"]))
                    combos.setdefault(c["id"], c)
    starts = set()
    by_groups: dict = {}
    for f in reports:
        with open(f, encoding="utf-8") as fh:
            r = json.load(fh)
        totals["machines"] += 1
        totals["coins_board"] = max(totals["coins_board"], int(r.get("coins_board") or 0))
        for k in ("coins_done", "pairs", "tested", "kept"):
            totals[k] += int(r.get(k) or 0)
        totals["failed"].update(r.get("failed") or {})
        totals["short"] += list(r.get("short") or [])
        totals["spans"].update(r.get("spans") or {})
        for k in ("start", "tz", "cfg"):
            totals[k] = totals[k] or r.get(k)
        starts.add(r.get("start"))
        # WHICH COINS each set of groups was measured on, from the pairs that
        # actually had bars and rules — never a sum of runs' coin counts,
        # which read "1,873 of 1,067 coins" once two runs were merged
        key = ",".join(r.get("groups") or ["classic", "preset"])
        by_groups.setdefault(key, set()).update(
            str(k).rsplit(" ", 1)[0] for k in (r.get("spans") or {}))
        # a report from before `groups` existed walked the shared rules only
        for g in (r.get("groups") or ["classic", "preset"]):
            if g not in totals["groups"]:
                totals["groups"].append(g)
    if len(starts) > 1:
        raise RuntimeError(f"these runs start on different days: {sorted(starts)}")
    totals["coins_by_groups"] = {k: len(v) for k, v in by_groups.items()}
    return {"combos": list(combos.values()), "totals": totals}


def common_end(spans: dict) -> int | None:
    """The earliest last bar across every INTRADAY pair: the one moment every
    coin's 15m-4h candles reached. None when nothing was measured.

    NOT the daily frame. A 1d pair's last CLOSED bar ends at the last local
    8:00pm (00:00 UTC), so counting it cut the first real run (36478015729,
    measured Sep 28, 2026 4:16-4:55pm) to Sep 27, 2026 8:00pm and threw away
    almost a day of every 15m/30m/1h/4h coin. A daily combination cannot
    exit between its closes anyway, so leaving it out lets no coin see
    further than it could have: a 1d trade still open at its last close is
    already marked open by the machine."""
    ends = [int(v[1]) for k, v in spans.items()
            if v and len(v) == 2 and not str(k).endswith(" 1d")]
    if not ends:
        ends = [int(v[1]) for v in spans.values() if v and len(v) == 2]
    return min(ends) if ends else None


def cut(combos: list[dict], end_ms: int) -> list[dict]:
    """Every trade that CLOSED after `end_ms` becomes an open trade, and every
    trade that ENTERED after it is dropped: nothing past the common end."""
    out = []
    for c in combos:
        trades = []
        for t in c["trades"]:
            if t[0] >= end_ms:
                continue
            if t[3] and t[1] > end_ms:
                trades.append([t[0], t[1], 0.0, 0])
            else:
                trades.append(list(t))
        out.append({**c, "trades": trades})
    return out


def start_ms(start: str) -> int:
    import datetime as dt

    y, m, d = (int(x) for x in start.split("-"))
    return int(dt.datetime(y, m, d).timestamp() * 1000)


def replay(folder: str, *, run_id: str = "", repo: str = "") -> dict:
    got = merge(folder)
    tot = got["totals"]
    end = common_end(tot["spans"])
    if end is None or not tot["start"]:
        raise RuntimeError("no machine reported a measured pair — nothing to replay")
    combos = cut(got["combos"], end)
    cfg = {**wp.DEFAULTS, **(tot.get("cfg") or {})}
    res = wr.simulate(combos, start_ms=start_ms(tot["start"]), end_ms=end,
                      cfg=cfg)
    return {"run": run_id, "repo": repo, "totals": tot, "end_ms": end,
            "cfg": cfg, "combos_written": len(combos), **res}


def fetch(run_id: str, repo: str) -> str:
    """Download the run's artifacts beside the store and return the folder."""
    from tradingagents import cloud_sweep as cs

    # "tmp" prefix: _scratch() sweeps its own tmp* leftovers after 6 hours
    d = tempfile.mkdtemp(prefix=f"tmp-replay-{run_id}-", dir=cs._scratch())
    cs._gh("run", "download", str(run_id), "--repo", repo, "--dir", d,
           timeout=1800)
    return d


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_ids", nargs="+", help="one or more replay runs, merged")
    ap.add_argument("--repo", default="jeremydevera/analyzer-x")
    ap.add_argument("--folder", action="append", default=[],
                    help="already-downloaded artifacts (repeat per run, in order)")
    a = ap.parse_args(argv)
    folders = list(a.folder)
    for rid in a.run_ids[len(folders):]:
        folders.append(fetch(rid, a.repo))
    name = "+".join(a.run_ids)
    res = replay(folders, run_id=name, repo=a.repo)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}.json"
    path.write_text(json.dumps(res, separators=(",", ":")), encoding="utf-8")
    s = res["summary"]
    print(f"{res['totals']['tested']:,} combinations tested, "
          f"{res['combos_written']:,} could pass; {s['slots']} switched on, "
          f"{s['closed']} trades, {s['wins']}W/{s['losses']}L, "
          f"profit {s['profit']:+.2f} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
