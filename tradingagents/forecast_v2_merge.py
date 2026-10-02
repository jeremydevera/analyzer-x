"""Bring a Forecast v2 run home and turn it into predictions.

    python -m tradingagents.forecast_v2_merge <base run> [<options run>] [--runs JSON] [--keep]

Each machine of .github/workflows/forecast.yml replayed whole coins, and a raw
rule set links strategies only through the runner's per-coin limit, so a rule
set's closed trades over the market are the machines' closed trades put
together. Every figure is then worked out from that SUM — never added from
per-machine figures, which would be wrong for a losing run or a peak (the same
rule as research_merge.py).

What comes out, beside the store (~/.tradingagents/forecast_v2/):
* latest.json — every rule set: its months, its prediction for this month
  (the typical past month and the range), the same corrected by the reality
  check, how often it beat random picks, the money it needs, its id and its
  words; the rooms' rules split the way "where the money goes" splits
  practice; what followed past streaks.
* streaks.npz — EVERY strategy on a run of 5+ at the data's end, as columns
  (650,000 rows measured on run 36936689969: as JSON dicts in the API that
  would have been over a gigabyte; as arrays it is tens of megabytes and the
  page is cut from it by the server).
* predictions.jsonl — the FIRST prediction made for each month, kept so the
  month can be graded once it is over.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import statistics
import sys
import time
from pathlib import Path

import numpy as np

from tradingagents import (
    forecast_rules as fr,
    forecast_v2 as f2,
    watcher_replay as wr,
    watcher_research as rs,
)

T0_MIN = 1_767_225_600 // 60
MARGIN = 5.0                 # the rooms' stake per trade, $5 at 20x
LUCK_LINE = 80               # beat random fewer times in 100 than this: "could be luck"
THIN_MONTHS = 3              # fewer past months than this: "thin"


def home() -> Path:
    return f2._home()


def _month(ms: float) -> str:
    """The local calendar month a moment falls in — a KEY (YYYY-MM), never
    printed; the page prints months as 'Sep 2026'."""
    return dt.datetime.fromtimestamp(float(ms) / 1000).strftime("%Y-%m")


def months_of(start_ms: int, end_ms: int) -> tuple[list[str], list[str]]:
    """(every month the data touches, the COMPLETE ones): a month is complete
    when the data reaches its last day — Sep 30, 2026 12:00pm completes
    September, and the hours after noon are named on the page."""
    out, complete = [], []
    d = dt.datetime.fromtimestamp(start_ms / 1000).replace(day=1, hour=0, minute=0,
                                                           second=0, microsecond=0)
    end = dt.datetime.fromtimestamp(end_ms / 1000)
    while d <= end:
        key = d.strftime("%Y-%m")
        nxt = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        last_day = nxt - dt.timedelta(days=1)
        out.append(key)
        if end >= last_day:
            complete.append(key)
        d = nxt
    return out, complete


# ----------------------------------------------------------------- reading
# MACHINES ACROSS ACCOUNTS (Oct 02, 2026: "moving forward i want 40 machines
# to be used always"): each GitHub account runs its own machines 0..19, so
# account i's machine k is numbered i * ACCOUNT_STEP + k — two accounts'
# machine 3 stay two machines, and the base and options runs are matched
# machine by machine on the same numbers.
ACCOUNT_STEP = 100


def folders(art) -> list[tuple[int, Path]]:
    """[(account, folder)] from one folder, from "0=<dir>;1=<dir>" (the
    chain's command line) or from a list of (account, folder)."""
    if isinstance(art, (list, tuple)):
        return [(int(i), Path(d)) for i, d in art]
    s = str(art)
    if "=" in s:
        out = []
        for part in s.split(";"):
            if part.strip():
                i, d = part.split("=", 1)
                out.append((int(i), Path(d)))
        return out
    return [(0, Path(s))]


def load(art_dir) -> tuple[list[dict], list]:
    """Every machine's meta and arrays, in machine order, over every
    account's folder (`folders`)."""
    found = []
    for i, d in folders(art_dir):
        for a in d.rglob("forecast-*.json"):
            found.append((i * ACCOUNT_STEP + int(a.stem.split("-")[1]), a))
    found.sort(key=lambda x: x[0])
    metas, packs = [], []
    for n, a in found:
        m = json.loads(a.read_text(encoding="utf-8"))
        m["shard"] = n                       # its number across every account
        metas.append(m)
        packs.append(np.load(a.with_suffix(".npz")))
    if not metas:
        raise FileNotFoundError(f"no forecast-<N>.json under {art_dir}")
    ids = [s["id"] for s in metas[0]["sets"]]
    for m in metas[1:]:
        if [s["id"] for s in m["sets"]] != ids:
            raise ValueError(f"shard {m['shard']} replayed different rule sets from shard "
                             f"{metas[0]['shard']} — the runs cannot be added together")
    return metas, packs


def trades_of(packs: list, j: int) -> np.ndarray:
    """Rule set j's closed trades over every machine: (n, 4) entry ms, exit
    ms, profit, closed — the shape watcher_research.score reads."""
    e = np.concatenate([(pk[f"{j}_e"].astype(np.int64) + T0_MIN) * 60_000 for pk in packs])
    x = np.concatenate([(pk[f"{j}_x"].astype(np.int64) + T0_MIN) * 60_000 for pk in packs])
    p = np.concatenate([pk[f"{j}_p"].astype(np.float64) for pk in packs])
    if not len(e):
        return np.zeros((0, 4))
    return np.column_stack([e, x, p, np.ones(len(e))])


# ----------------------------------------------------------------- one set
def summarize(j: int, metas: list, packs: list, start_ms: int, end_ms: int,
              months: list[str], complete: list[str], reality: dict,
              days: bool = False) -> dict:
    """One rule set scored; `days` adds what it made by the end of each day
    of every past month (by_day) — kept for the rooms' own rule sets, which
    the month tracker reads."""
    cfg = metas[0]["sets"][j]["cfg"]
    t = trades_of(packs, j)
    by = {m: [0, 0, 0.0] for m in months}
    for x, p in zip(t[:, 1], t[:, 2], strict=True):
        cell = by.setdefault(_month(x), [0, 0, 0.0])
        cell[0] += 1
        cell[1] += int(p > 0)
        cell[2] += float(p)
    month_rows = []
    for m in months:
        n, w, p = by.get(m, [0, 0, 0.0])
        month_rows.append({"month": m, "complete": m in complete, "trades": n, "wins": w,
                           "losses": n - w, "profit": round(p, 2),
                           "corrected": f2.corrected(p, n, reality)})
    past = [r for r in month_rows if r["complete"]]
    pred = None
    if past:
        prof = [r["profit"] for r in past]
        corr = [r["corrected"] for r in past if r["corrected"] is not None]
        pred = {"profit": round(statistics.median(prof), 2), "low": min(prof), "high": max(prof),
                "trades": int(statistics.median([r["trades"] for r in past])),
                "months": len(past), "thin": len(past) < THIN_MONTHS,
                "corrected": round(statistics.median(corr), 2) if corr else None,
                "corrected_low": min(corr) if corr else None,
                "corrected_high": max(corr) if corr else None}
    res = {"summary": {"slots": sum(m["sets"][j]["slots"] for m in metas),
                       "open": sum(m["sets"][j]["open"] for m in metas)},
           "days": _days(t, start_ms, end_ms), "slots": [{"trades": t}]}
    sc = rs.score(res, end_ms=end_ms)
    wins = t[t[:, 2] > 0, 2]
    losses = -t[t[:, 2] <= 0, 2]
    be = (round(100 * float(losses.mean()) / (float(wins.mean()) + float(losses.mean())), 1)
          if len(wins) and len(losses) else None)
    # BEAT RANDOM, per trade (forecast_shard.beat_random says why)
    rp = np.sum([pk[f"{j}_r"].astype(np.float64) for pk in packs], axis=0)
    rn = np.sum([pk[f"{j}_rn"].astype(np.int64) for pk in packs], axis=0)
    own = float(t[:, 2].sum()) / len(t) if len(t) else None
    rpt = rp / np.maximum(rn, 1)
    beat = int((own > rpt[rn > 0]).sum()) if own is not None and (rn > 0).any() else None
    ok, why = fr.deployable(cfg)
    extra = {"by_day": by_day(t, complete)} if days else {}
    return {**extra, "id": fr.rule_id(cfg), "cfg": cfg, "words": fr.words(cfg),
            "options": fr.options_of(cfg), "base": not fr.options_of(cfg) and
            str(cfg.get("tp_rule")) in fr.BASE["tp_rule"],
            "deployable": ok, "deploy_why": why,
            "months": month_rows, "predicted": pred,
            "total": {k: sc[k] for k in ("closed", "wins", "losses", "winrate", "profit",
                                          "worst_run", "worst_run_n", "max_open", "worst_day",
                                          "green_days", "days_n", "max_dd")},
            "per_trade": round(own, 4) if own is not None else None,
            "break_even": be, "money_needed": round(sc["max_open"] * MARGIN, 2),
            "random": {"draws": int((rn > 0).sum()), "beat": beat,
                       "per_trade": round(float(np.median(rpt[rn > 0])), 4) if (rn > 0).any() else None},
            "luck": beat is not None and beat < LUCK_LINE,
            "slots": res["summary"]["slots"]}


def by_day(t: np.ndarray, complete: list[str]) -> dict:
    """For each COMPLETE past month, the running profit and trade count at the
    end of every day of it — what "by today" really was in that month.

    Bug hunt, round 6 (RCA-2026-10-01-J): the month tracker divided a month's
    worst case by the days in the month, so on Oct 01, 2026 Main's −7.29 was
    held against a "worst case by today" of −0.01 and all six rooms rang. A
    day of a month is compared with the same day of past months, measured."""
    out = {}
    for m in complete:
        y, mo = map(int, m.split("-"))
        first = dt.datetime(y, mo, 1)
        nxt = (first.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        edges = np.asarray([int((first + dt.timedelta(days=i)).timestamp() * 1000)
                            for i in range((nxt - first).days)]
                           + [int(nxt.timestamp() * 1000)], dtype=np.int64)
        days = len(edges) - 1
        if len(t):
            k = np.searchsorted(edges, t[:, 1].astype(np.int64), "right") - 1
            ok = (k >= 0) & (k < days)
            p = np.bincount(k[ok], weights=t[ok, 2], minlength=days).cumsum()
            n = np.bincount(k[ok], minlength=days).cumsum()
        else:
            p, n = np.zeros(days), np.zeros(days, dtype=np.int64)
        out[m] = {"p": [round(float(v), 2) for v in p], "n": [int(v) for v in n]}
    return out


def _days(t: np.ndarray, start: int, end: int) -> list:
    """One row per check day: the profit of the trades that CLOSED that day."""
    checks = wr.local_midnights(start, end)
    if not checks:
        return []
    later = [m for m in wr.local_midnights(checks[-1], checks[-1] + 2 * wr.DAY_MS) if m > checks[-1]]
    edges = np.asarray(checks + later[:1], dtype=np.int64)
    if not len(t):
        return [{"pnl": 0.0} for _ in checks]
    k = np.searchsorted(edges, t[:, 1].astype(np.int64), "right") - 1
    ok = (k >= 0) & (k < len(checks))
    raw = np.bincount(k[ok], weights=t[ok, 2], minlength=len(checks))
    return [{"pnl": round(float(v), 2)} for v in raw]


def rank_key(s: dict):
    """The WORST past month after the reality check first (the still-working
    rule), then the typical one."""
    past = [m for m in s["months"] if m["complete"]]
    worst = min((m["corrected"] if m["corrected"] is not None else m["profit"]) for m in past) \
        if past else -1e18
    pred = s["predicted"] or {}
    typical = pred.get("corrected") if pred.get("corrected") is not None else pred.get("profit", -1e18)
    return (-worst, -(typical if typical is not None else -1e18), s["id"])


# ------------------------------------------------------------------ merge
def merge(base_dir: str | Path, options_dir: str | Path | None = None, *,
          runs: dict | None = None, reality: dict | None = None, keep: bool = True) -> dict:
    """Both stages, scored and ranked, written to latest.json."""
    if reality is None:
        reality = f2.live()["reality"]["all"]
    metas, packs = load(base_dir)
    om = op = None
    if options_dir:
        om, op = load(options_dir)
        # BOTH STAGES OVER THE SAME COINS (bug hunt, round 12): a machine is a
        # share of the coins, and a run is used with some machines red — base
        # without machine 3 and options without machine 7 would rank rule sets
        # measured on different markets against each other
        common = {m["shard"] for m in metas} & {m["shard"] for m in om}
        metas, packs = _only(metas, packs, common)
        om, op = _only(om, op, common)
        if not metas:
            raise ValueError("the base and options runs share no machine")
    end_ms, start = int(metas[0]["end_ms"]), metas[0]["start"]
    start_ms = int(dt.datetime(*map(int, start.split("-"))).timestamp() * 1000)
    months, complete = months_of(start_ms, end_ms)
    rooms = _rooms(metas)
    room_ids = {v["id"]: k for k, v in rooms.items()}
    sets = [summarize(j, metas, packs, start_ms, end_ms, months, complete, reality,
                      days=metas[0]["sets"][j]["id"] in room_ids)
            for j in range(len(metas[0]["sets"]))]
    tested = {"base": len(sets), "options": 0}
    if om:
        if int(om[0]["end_ms"]) != end_ms:
            raise ValueError("the options run read a different replay end from the base run")
        have = {s["id"] for s in sets}
        extra = [summarize(j, om, op, start_ms, end_ms, months, complete, reality,
                           days=om[0]["sets"][j]["id"] in room_ids)
                 for j in range(len(om[0]["sets"]))]
        sets += [s for s in extra if s["id"] not in have]
        tested["options"] = len(extra)
    sets.sort(key=rank_key)
    for i, s in enumerate(sets):
        s["rank"] = i + 1
    for s in sets:
        s["room"] = room_ids.get(s["id"])
    streak_rows = streak_arrays([r for m in metas for r in m.get("streaks", [])])
    ft = np.sum([pk["ft"] for pk in packs if "ft" in pk.files], axis=0) if packs else None
    follow = {}
    if ft is not None and np.ndim(ft) == 3:
        for kind, name in ((0, "win"), (1, "loss")):
            follow[name] = [{"k": k + 1, "cases": int(ft[kind, k, 0]), "next_win": int(ft[kind, k, 1]),
                             "cases10": int(ft[kind, k, 2]), "pnl10": round(float(ft[kind, k, 3]), 2)}
                            for k in range(ft.shape[1])]
    now = time.time()
    out = {"made_at": int(now), "runs": runs or {}, "reality": reality,
           "data": {"start": start, "end_ms": end_ms, "months": months, "complete": complete,
                    "write": metas[0].get("write"), "machines": len(metas),
                    # of how many: the chain says (runs["shards"]); the page
                    # prints "N of 20" whenever a machine is missing
                    "of": int((runs or {}).get("shards") or len(metas)),
                    # WHAT THE REPLAY COVERED (round 16): a prediction and the
                    # result it is graded on are only comparable over the same
                    "universe": (runs or {}).get("universe") or {},
                    "shards": sorted(int(m["shard"]) for m in metas),
                    "strategies": sum(int(m["books"]) for m in metas),
                    "trades": sum(int(m["trades"]) for m in metas)},
           "tested": {**tested, "total": len(sets)}, "sets": sets, "rooms": rooms,
           "follow": follow,
           "streaks": {"count": int(len(streak_rows["length"])),
                       "win": int((streak_rows["kind"] == 0).sum()),
                       "loss": int((streak_rows["kind"] == 1).sum()),
                       "floor": 5}}
    _save(out, streak_rows, keep)
    return out


def _only(metas: list, packs: list, shards: set) -> tuple[list, list]:
    """The machines whose shard is in `shards`, in order."""
    keep = [(m, p) for m, p in zip(metas, packs, strict=True) if m["shard"] in shards]
    return [m for m, _ in keep], [p for _, p in keep]


def _rooms(metas: list) -> dict:
    """The rooms' rules replayed, their last 30 days split every way, added
    up over the machines."""
    out: dict = {}
    for m in metas:
        for rid, b in (m.get("rooms") or {}).items():
            o = out.setdefault(rid, {"id": b["id"], "tf": {}, "family": {}, "kind": {},
                                     "hour": {}, "stops": {}, "sizes": [0, 0.0, 0, 0.0],
                                     "costs": 0.0, "trades": 0, "profit": 0.0})
            for g in ("tf", "family", "kind", "hour", "stops"):
                for k, v in b[g].items():
                    cell = o[g].setdefault(k, [0, 0, 0.0])
                    for i in range(3):
                        cell[i] += v[i]
            for i in range(4):
                o["sizes"][i] += b["sizes"][i]
            for k in ("costs", "trades", "profit"):
                o[k] += b[k]
    for o in out.values():
        o["costs"] = round(o["costs"], 2)
        o["profit"] = round(o["profit"], 2)
    return out


# a coin, timeframe and signal name is stored ONCE, and each row carries its
# number in the list: 689,474 rows as text columns were 287 MB on run
# 36936689969, almost all of it the same 1,100 coins and 400 signals
STREAK_CODED = ("coin", "tf", "signal")
STREAK_NUM = {"th": np.float32, "tp": np.float32, "sl": np.float32, "cost_of_tp": np.float32,
              "length": np.int32, "started_ms": np.int64, "last_ms": np.int64,
              "profit": np.float32, "trades": np.int32, "wins": np.int32,
              "break_even": np.float32}


def streak_arrays(rows: list[dict]) -> dict:
    """The machines' streak rows as columns, longest first (kind 0 = a
    winning run, 1 = a losing run)."""
    out = {"id": np.array([str(r["id"]) for r in rows], dtype="S8")}
    for k in STREAK_CODED:
        names = sorted({str(r[k]) for r in rows})
        ix = {n: i for i, n in enumerate(names)}
        out[k] = np.array([ix[str(r[k])] for r in rows], dtype=np.int32)
        out[f"{k}_names"] = np.array(names, dtype=object).astype("U")
    for k, t in STREAK_NUM.items():
        if k == "break_even":
            out[k] = np.array([f2.break_even(r["tp"], r["sl"], r["cost_of_tp"] / 100 * r["tp"]) or np.nan
                               for r in rows], dtype=t)
        else:
            out[k] = np.array([r[k] for r in rows], dtype=t)
    out["kind"] = np.array([0 if r["kind"] == "win" else 1 for r in rows], dtype=np.int8)
    order = np.lexsort((out["id"], out["coin"], out["kind"], -out["length"]))
    return {k: (v if k.endswith("_names") else v[order]) for k, v in out.items()}


def _save(out: dict, streak_rows: dict, keep: bool = True) -> None:
    """latest.json and streaks.npz, each written whole or not at all; the
    month's FIRST prediction kept for grading."""
    d = home()
    d.mkdir(parents=True, exist_ok=True)
    text = json.dumps(out, separators=(",", ":"), allow_nan=False)
    tmp_npz = d / f"streaks.{os.getpid()}.tmp.npz"
    np.savez_compressed(tmp_npz, **streak_rows)
    # each swap retried while the page reads the file it replaces (bug hunt,
    # round 8): np.load holds streaks.npz open for the whole read
    f2.replace_retry(tmp_npz, d / "streaks.npz")
    f2.publish(d / "latest.json", text)
    if keep:
        # only the FINAL merge of a day: the base-only merge in between has
        # no option rule sets, and the month's first saved prediction is the
        # one it is graded on (bug hunt, round 2)
        keep_prediction(out)


def keep_prediction(out: dict, path: Path | None = None) -> bool:
    """The month's FIRST prediction, so it can be graded when the month is
    over. A later run in the same month never overwrites it."""
    path = Path(path or (home() / "predictions.jsonl"))
    month = dt.datetime.fromtimestamp(out["made_at"]).strftime("%Y-%m")
    have = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                have.add(json.loads(line)["month"])
            except (ValueError, KeyError):
                continue
    if month in have:
        return False
    rows = [{"id": s["id"], "words": s["words"], "room": s.get("room"),
             "predicted": s["predicted"]} for s in out["sets"] if s["predicted"]]
    line = {"month": month, "made_at": out["made_at"], "data_end_ms": out["data"]["end_ms"],
            "universe": out["data"].get("universe") or {},
            "reality": {k: out["reality"].get(k) for k in ("took", "gap")}, "sets": rows}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, separators=(",", ":"), allow_nan=False) + "\n")
    return True


def main(argv=None) -> int:
    """`<base dir> [<options dir>] [--runs JSON] [--keep]` — run by the
    daily chain as its OWN PROCESS: adding up the machines' streaks peaks
    over a gigabyte, which must never happen inside the API. A dir may be
    one folder or every account's, "0=<dir>;1=<dir>" (`folders`). `--keep`
    keeps the month's first prediction; only the chain's final merge passes it."""
    argv = list(argv or sys.argv[1:])
    runs = {}
    if "--runs" in argv:
        i = argv.index("--runs")
        runs = json.loads(argv[i + 1])
        del argv[i:i + 2]
    # A MONTH IS KEPT ONLY WHEN ASKED (bug hunt, round 16): the default kept,
    # so a merge run by hand on a research replay claimed October's
    # prediction twice on Oct 01, 2026 (RCA-2026-10-01-K). The daily chain's
    # final merge passes --keep; nothing else does.
    keep = "--keep" in argv
    argv = [a for a in argv if a not in ("--keep", "--no-keep")]
    out = merge(argv[0], argv[1] if len(argv) > 1 else None, runs=runs, keep=keep)
    top = out["sets"][0]
    print(f"{out['tested']['total']} rule sets; best #{top['id']} {top['words']}: "
          f"{top['predicted']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
